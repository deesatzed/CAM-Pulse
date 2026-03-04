"""Episodic memory — session event log.

Records every significant event during a claw cycle (task grabbed,
agent dispatched, verification result, etc.) with timestamps.
Uses the ``episodes`` table in SQLite.  Per-project/session with
90-day default retention.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from claw.db.repository import Repository

logger = logging.getLogger("claw.memory.episodic")


class EpisodicMemory:
    """Session event log for per-project/session tracking.

    Records every significant event during a claw cycle (task grabbed,
    agent dispatched, verification result, etc.) with timestamps.
    Uses the ``episodes`` table in SQLite.
    """

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def record_event(
        self,
        project_id: str,
        session_id: str,
        event_type: str,
        event_data: dict[str, Any],
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        cycle_level: Optional[str] = None,
    ) -> str:
        """Record a session event.  Returns the event ID.

        Parameters
        ----------
        project_id:
            The project this event belongs to.
        session_id:
            The unique session identifier (one per claw run).
        event_type:
            Describes the kind of event.  Canonical values include
            ``task_grabbed``, ``agent_dispatched``, ``verification_passed``,
            ``verification_failed``, ``task_completed``, ``task_stuck``,
            ``escalation_triggered``, ``cycle_started``, ``cycle_ended``.
        event_data:
            Arbitrary JSON-serialisable dict with event details.
        agent_id:
            The agent involved in the event, if any.
        task_id:
            The task involved in the event, if any.
        cycle_level:
            The claw cycle level (``micro``, ``meso``, ``macro``, ``nano``).

        Returns
        -------
        str
            The generated UUID for the newly recorded event.
        """
        episode_id = self.repository.log_episode(
            session_id=session_id,
            event_type=event_type,
            event_data=event_data,
            project_id=project_id,
            agent_id=agent_id,
            task_id=task_id,
            cycle_level=cycle_level,
        )
        # log_episode is async and returns the id
        event_id: str = await episode_id
        logger.debug(
            "Recorded episodic event %s: type=%s session=%s project=%s",
            event_id,
            event_type,
            session_id,
            project_id,
        )
        return event_id

    # ------------------------------------------------------------------
    # Read — by session
    # ------------------------------------------------------------------

    async def get_session_events(
        self, session_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get all events for a session, ordered most-recent-first.

        Parameters
        ----------
        session_id:
            The session to query.
        limit:
            Maximum number of events to return.
        """
        rows = await self.repository.engine.fetch_all(
            """SELECT id, project_id, session_id, event_type, event_data,
                      agent_id, task_id, cycle_level, created_at
               FROM episodes
               WHERE session_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            [session_id, limit],
        )
        return [_row_to_event(r) for r in rows]

    # ------------------------------------------------------------------
    # Read — by project
    # ------------------------------------------------------------------

    async def get_project_events(
        self,
        project_id: str,
        limit: int = 100,
        event_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Get events for a project, optionally filtered by type.

        Parameters
        ----------
        project_id:
            The project to query.
        limit:
            Maximum number of events to return.
        event_type:
            If provided, only return events of this type.
        """
        if event_type is not None:
            rows = await self.repository.engine.fetch_all(
                """SELECT id, project_id, session_id, event_type, event_data,
                          agent_id, task_id, cycle_level, created_at
                   FROM episodes
                   WHERE project_id = ? AND event_type = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                [project_id, event_type, limit],
            )
        else:
            rows = await self.repository.engine.fetch_all(
                """SELECT id, project_id, session_id, event_type, event_data,
                          agent_id, task_id, cycle_level, created_at
                   FROM episodes
                   WHERE project_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                [project_id, limit],
            )
        return [_row_to_event(r) for r in rows]

    # ------------------------------------------------------------------
    # Read — by task
    # ------------------------------------------------------------------

    async def get_task_events(
        self, task_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get all events related to a specific task.

        Parameters
        ----------
        task_id:
            The task to query.
        limit:
            Maximum number of events to return.
        """
        rows = await self.repository.engine.fetch_all(
            """SELECT id, project_id, session_id, event_type, event_data,
                      agent_id, task_id, cycle_level, created_at
               FROM episodes
               WHERE task_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            [task_id, limit],
        )
        return [_row_to_event(r) for r in rows]

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    async def apply_retention_policy(self, retention_days: int = 90) -> int:
        """Delete events older than *retention_days*.

        Returns the count of deleted rows.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()

        # Count first so we can report how many were removed.
        count_row = await self.repository.engine.fetch_one(
            "SELECT COUNT(*) AS cnt FROM episodes WHERE created_at < ?",
            [cutoff],
        )
        count = int(count_row["cnt"]) if count_row else 0

        if count > 0:
            await self.repository.engine.execute(
                "DELETE FROM episodes WHERE created_at < ?",
                [cutoff],
            )
            logger.info(
                "Retention policy applied: deleted %d episodes older than %d days",
                count,
                retention_days,
            )

        return count

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    async def get_session_summary(self, session_id: str) -> dict[str, Any]:
        """Get a summary of a session.

        Returns a dict containing:
        - ``session_id``
        - ``total_events``: total number of events in the session
        - ``event_counts``: dict mapping event_type -> count
        - ``agents_used``: list of distinct agent_ids involved
        - ``tasks_touched``: list of distinct task_ids referenced
        - ``first_event_at``: ISO timestamp of the earliest event
        - ``last_event_at``: ISO timestamp of the latest event
        - ``duration_seconds``: wall-clock duration from first to last event
        """
        # Total count
        total_row = await self.repository.engine.fetch_one(
            "SELECT COUNT(*) AS cnt FROM episodes WHERE session_id = ?",
            [session_id],
        )
        total_events = int(total_row["cnt"]) if total_row else 0

        if total_events == 0:
            return {
                "session_id": session_id,
                "total_events": 0,
                "event_counts": {},
                "agents_used": [],
                "tasks_touched": [],
                "first_event_at": None,
                "last_event_at": None,
                "duration_seconds": 0.0,
            }

        # Event counts by type
        type_rows = await self.repository.engine.fetch_all(
            """SELECT event_type, COUNT(*) AS cnt
               FROM episodes
               WHERE session_id = ?
               GROUP BY event_type
               ORDER BY cnt DESC""",
            [session_id],
        )
        event_counts: dict[str, int] = {
            str(r["event_type"]): int(r["cnt"]) for r in type_rows
        }

        # Distinct agents
        agent_rows = await self.repository.engine.fetch_all(
            """SELECT DISTINCT agent_id
               FROM episodes
               WHERE session_id = ? AND agent_id IS NOT NULL""",
            [session_id],
        )
        agents_used: list[str] = [str(r["agent_id"]) for r in agent_rows]

        # Distinct tasks
        task_rows = await self.repository.engine.fetch_all(
            """SELECT DISTINCT task_id
               FROM episodes
               WHERE session_id = ? AND task_id IS NOT NULL""",
            [session_id],
        )
        tasks_touched: list[str] = [str(r["task_id"]) for r in task_rows]

        # Time bounds
        bounds_row = await self.repository.engine.fetch_one(
            """SELECT MIN(created_at) AS first_at, MAX(created_at) AS last_at
               FROM episodes
               WHERE session_id = ?""",
            [session_id],
        )

        first_event_at = bounds_row["first_at"] if bounds_row else None
        last_event_at = bounds_row["last_at"] if bounds_row else None

        duration_seconds = 0.0
        if first_event_at and last_event_at:
            try:
                first_dt = datetime.fromisoformat(first_event_at)
                last_dt = datetime.fromisoformat(last_event_at)
                duration_seconds = (last_dt - first_dt).total_seconds()
            except (ValueError, TypeError):
                pass

        return {
            "session_id": session_id,
            "total_events": total_events,
            "event_counts": event_counts,
            "agents_used": agents_used,
            "tasks_touched": tasks_touched,
            "first_event_at": first_event_at,
            "last_event_at": last_event_at,
            "duration_seconds": duration_seconds,
        }

    async def get_project_summary(self, project_id: str) -> dict[str, Any]:
        """Get a summary of all episodic activity for a project.

        Returns a dict containing:
        - ``project_id``
        - ``total_events``: total event count
        - ``session_count``: number of distinct sessions
        - ``event_counts``: dict mapping event_type -> count
        - ``agents_used``: list of distinct agent_ids
        """
        total_row = await self.repository.engine.fetch_one(
            "SELECT COUNT(*) AS cnt FROM episodes WHERE project_id = ?",
            [project_id],
        )
        total_events = int(total_row["cnt"]) if total_row else 0

        if total_events == 0:
            return {
                "project_id": project_id,
                "total_events": 0,
                "session_count": 0,
                "event_counts": {},
                "agents_used": [],
            }

        session_row = await self.repository.engine.fetch_one(
            "SELECT COUNT(DISTINCT session_id) AS cnt FROM episodes WHERE project_id = ?",
            [project_id],
        )
        session_count = int(session_row["cnt"]) if session_row else 0

        type_rows = await self.repository.engine.fetch_all(
            """SELECT event_type, COUNT(*) AS cnt
               FROM episodes
               WHERE project_id = ?
               GROUP BY event_type
               ORDER BY cnt DESC""",
            [project_id],
        )
        event_counts = {str(r["event_type"]): int(r["cnt"]) for r in type_rows}

        agent_rows = await self.repository.engine.fetch_all(
            """SELECT DISTINCT agent_id
               FROM episodes
               WHERE project_id = ? AND agent_id IS NOT NULL""",
            [project_id],
        )
        agents_used = [str(r["agent_id"]) for r in agent_rows]

        return {
            "project_id": project_id,
            "total_events": total_events,
            "session_count": session_count,
            "event_counts": event_counts,
            "agents_used": agents_used,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_event(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw SQLite row dict to a cleaned event dict."""
    event_data = row.get("event_data", "{}")
    if isinstance(event_data, str):
        try:
            event_data = json.loads(event_data)
        except (json.JSONDecodeError, TypeError):
            event_data = {}

    return {
        "id": row["id"],
        "project_id": row.get("project_id"),
        "session_id": row["session_id"],
        "event_type": row["event_type"],
        "event_data": event_data,
        "agent_id": row.get("agent_id"),
        "task_id": row.get("task_id"),
        "cycle_level": row.get("cycle_level"),
        "created_at": row.get("created_at"),
    }
