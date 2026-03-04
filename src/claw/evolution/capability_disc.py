"""Capability Boundary Discovery for CLAW.

When all four agents (Claude, Codex, Gemini, Grok) fail the same task,
that task represents a *capability boundary* — a problem that exceeds
the current abilities of every available agent.

This module records, tracks, retests, and escalates capability boundaries.
Boundaries are periodically retested (default every 30 days) because
agent capabilities evolve as models are updated via OpenRouter.  Resolved
boundaries are archived but retained for learning.

Uses the ``capability_boundaries`` table in ``data/claw.db``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from claw.db.repository import Repository

logger = logging.getLogger("claw.evolution.capability_disc")


class CapabilityDiscovery:
    """Capability boundary recording, tracking, and retesting.

    Injected dependencies:
        repository: Database access for the ``capability_boundaries`` table.

    Parameters
    ----------
    repository:
        The data access layer for direct DB queries.
    retest_days:
        Number of days after discovery (or last retest) before a boundary
        is eligible for retesting.  Defaults to 30.
    """

    def __init__(
        self,
        repository: Repository,
        retest_days: int = 30,
    ) -> None:
        self.repository = repository
        self.retest_days = retest_days

    # ------------------------------------------------------------------
    # 1. record_boundary — record a newly discovered boundary
    # ------------------------------------------------------------------

    async def record_boundary(
        self,
        task_type: str,
        task_description: str,
        agents_attempted: list[str],
        failure_signatures: list[str],
    ) -> str:
        """Record a new capability boundary.

        A boundary is recorded when all attempted agents fail the same
        task.  Before inserting, checks whether a similar boundary
        already exists (same task_type and matching description); if so,
        updates the existing row instead of creating a duplicate.

        Parameters
        ----------
        task_type:
            Category of the task (e.g. ``"refactor"``, ``"security_fix"``).
        task_description:
            Human-readable description of what was attempted.
        agents_attempted:
            List of agent_ids that tried and failed.
        failure_signatures:
            List of normalized error signatures from the failures.

        Returns
        -------
        str
            The ID of the boundary row (new or updated).
        """
        # Check for an existing similar boundary to avoid duplicates.
        existing_id = await self._find_similar_boundary(task_type, task_description)
        now = datetime.now(UTC).isoformat()

        if existing_id is not None:
            # Merge agents and failure signatures into the existing row.
            existing = await self.repository.engine.fetch_one(
                "SELECT agents_attempted, failure_signatures FROM capability_boundaries WHERE id = ?",
                [existing_id],
            )
            if existing is not None:
                old_agents = _parse_json_list(existing["agents_attempted"])
                old_sigs = _parse_json_list(existing["failure_signatures"])

                merged_agents = sorted(set(old_agents) | set(agents_attempted))
                merged_sigs = sorted(set(old_sigs) | set(failure_signatures))

                await self.repository.engine.execute(
                    """UPDATE capability_boundaries
                       SET agents_attempted = ?, failure_signatures = ?
                       WHERE id = ?""",
                    [json.dumps(merged_agents), json.dumps(merged_sigs), existing_id],
                )

                logger.info(
                    "Updated existing capability boundary %s with %d new agents, "
                    "%d new failure signatures",
                    existing_id,
                    len(set(agents_attempted) - set(old_agents)),
                    len(set(failure_signatures) - set(old_sigs)),
                )
                return existing_id

        # Insert a new boundary.
        boundary_id = str(uuid.uuid4())
        await self.repository.engine.execute(
            """INSERT INTO capability_boundaries
               (id, task_type, task_description, agents_attempted,
                failure_signatures, discovered_at,
                escalated_to_human, resolved)
               VALUES (?, ?, ?, ?, ?, ?, 0, 0)""",
            [
                boundary_id,
                task_type,
                task_description,
                json.dumps(agents_attempted),
                json.dumps(failure_signatures),
                now,
            ],
        )

        logger.info(
            "Recorded new capability boundary %s: task_type=%s agents=%s",
            boundary_id,
            task_type,
            agents_attempted,
        )
        return boundary_id

    # ------------------------------------------------------------------
    # 2. check_boundary_exists — check if a similar boundary is known
    # ------------------------------------------------------------------

    async def check_boundary_exists(
        self,
        task_type: str,
        task_description: str,
    ) -> bool:
        """Check whether a similar capability boundary already exists.

        Similarity is determined by matching ``task_type`` exactly and
        checking whether the ``task_description`` is a substring match
        or shares significant overlap with an existing unresolved boundary.

        Parameters
        ----------
        task_type:
            The task category.
        task_description:
            Description of the task.

        Returns
        -------
        bool
            ``True`` if a matching unresolved boundary exists.
        """
        found = await self._find_similar_boundary(task_type, task_description)
        return found is not None

    async def _find_similar_boundary(
        self,
        task_type: str,
        task_description: str,
    ) -> Optional[str]:
        """Find an existing unresolved boundary with the same task_type
        and overlapping description.

        Uses a two-pass approach:
        1. Exact match on task_type + task_description.
        2. If no exact match, check task_type matches where the existing
           description is contained in the new one or vice versa.

        Returns the boundary ID if found, else ``None``.
        """
        # Pass 1: exact match.
        row = await self.repository.engine.fetch_one(
            """SELECT id FROM capability_boundaries
               WHERE task_type = ? AND task_description = ? AND resolved = 0""",
            [task_type, task_description],
        )
        if row is not None:
            return str(row["id"])

        # Pass 2: substring containment.
        rows = await self.repository.engine.fetch_all(
            """SELECT id, task_description FROM capability_boundaries
               WHERE task_type = ? AND resolved = 0""",
            [task_type],
        )
        desc_lower = task_description.lower()
        for candidate in rows:
            existing_desc = str(candidate["task_description"]).lower()
            # Check if one description is contained in the other.
            if existing_desc in desc_lower or desc_lower in existing_desc:
                return str(candidate["id"])

        return None

    # ------------------------------------------------------------------
    # 3. get_unresolved_boundaries — list open boundaries
    # ------------------------------------------------------------------

    async def get_unresolved_boundaries(
        self,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get all unresolved capability boundaries.

        Parameters
        ----------
        limit:
            Maximum number of rows to return.

        Returns
        -------
        list[dict]
            Each dict mirrors the ``capability_boundaries`` columns with
            JSON fields parsed to Python lists.
        """
        rows = await self.repository.engine.fetch_all(
            """SELECT * FROM capability_boundaries
               WHERE resolved = 0
               ORDER BY discovered_at DESC
               LIMIT ?""",
            [limit],
        )
        return [_row_to_boundary_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 4. get_retestable_boundaries — boundaries due for retesting
    # ------------------------------------------------------------------

    async def get_retestable_boundaries(self) -> list[dict[str, Any]]:
        """Get unresolved boundaries that are eligible for retesting.

        A boundary is retestable if:
        - It is not resolved.
        - It has not been retested within ``retest_days`` days (or has
          never been retested).

        Returns
        -------
        list[dict]
            Boundary dicts eligible for retesting.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=self.retest_days)).isoformat()

        rows = await self.repository.engine.fetch_all(
            """SELECT * FROM capability_boundaries
               WHERE resolved = 0
                 AND (last_retested_at IS NULL OR last_retested_at < ?)
               ORDER BY discovered_at ASC""",
            [cutoff],
        )
        return [_row_to_boundary_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 5. mark_retested — record the result of a retest
    # ------------------------------------------------------------------

    async def mark_retested(
        self,
        boundary_id: str,
        result: str,
    ) -> bool:
        """Update a boundary after retesting.

        Parameters
        ----------
        boundary_id:
            The boundary that was retested.
        result:
            A description of the retest outcome (e.g.
            ``"still_failing"``, ``"partial_success"``, ``"resolved"``).

        Returns
        -------
        bool
            ``True`` if the boundary was found and updated.
        """
        existing = await self.repository.engine.fetch_one(
            "SELECT id FROM capability_boundaries WHERE id = ?",
            [boundary_id],
        )
        if existing is None:
            logger.warning(
                "Cannot mark retested: boundary %s not found", boundary_id
            )
            return False

        now = datetime.now(UTC).isoformat()
        await self.repository.engine.execute(
            """UPDATE capability_boundaries
               SET last_retested_at = ?, retest_result = ?
               WHERE id = ?""",
            [now, result, boundary_id],
        )

        # If the retest result indicates resolution, auto-resolve.
        if result.lower() in ("resolved", "success", "passed"):
            await self.mark_resolved(boundary_id)

        logger.info(
            "Marked boundary %s as retested: result=%s",
            boundary_id,
            result,
        )
        return True

    # ------------------------------------------------------------------
    # 6. mark_resolved — archive a resolved boundary
    # ------------------------------------------------------------------

    async def mark_resolved(self, boundary_id: str) -> bool:
        """Mark a capability boundary as resolved.

        Resolved boundaries remain in the database for historical
        analysis but are excluded from ``get_unresolved_boundaries``
        and ``get_retestable_boundaries`` queries.

        Parameters
        ----------
        boundary_id:
            The boundary to resolve.

        Returns
        -------
        bool
            ``True`` if the boundary was found and resolved.
        """
        existing = await self.repository.engine.fetch_one(
            "SELECT id, resolved FROM capability_boundaries WHERE id = ?",
            [boundary_id],
        )
        if existing is None:
            logger.warning(
                "Cannot resolve: boundary %s not found", boundary_id
            )
            return False

        if existing["resolved"]:
            logger.info(
                "Boundary %s is already resolved", boundary_id
            )
            return True

        await self.repository.engine.execute(
            "UPDATE capability_boundaries SET resolved = 1 WHERE id = ?",
            [boundary_id],
        )

        logger.info("Resolved capability boundary %s", boundary_id)
        return True

    # ------------------------------------------------------------------
    # 7. escalate_to_human — flag a boundary for human attention
    # ------------------------------------------------------------------

    async def escalate_to_human(self, boundary_id: str) -> bool:
        """Set the escalated flag on a capability boundary.

        This signals to the coordinator and dashboard that the boundary
        requires human intervention and should not be retried
        automatically without human review.

        Parameters
        ----------
        boundary_id:
            The boundary to escalate.

        Returns
        -------
        bool
            ``True`` if the boundary was found and escalated.
        """
        existing = await self.repository.engine.fetch_one(
            "SELECT id, escalated_to_human FROM capability_boundaries WHERE id = ?",
            [boundary_id],
        )
        if existing is None:
            logger.warning(
                "Cannot escalate: boundary %s not found", boundary_id
            )
            return False

        if existing["escalated_to_human"]:
            logger.info(
                "Boundary %s is already escalated", boundary_id
            )
            return True

        await self.repository.engine.execute(
            "UPDATE capability_boundaries SET escalated_to_human = 1 WHERE id = ?",
            [boundary_id],
        )

        logger.warning(
            "Escalated capability boundary %s to human intervention",
            boundary_id,
        )
        return True

    # ------------------------------------------------------------------
    # 8. get_boundary_summary — aggregate statistics
    # ------------------------------------------------------------------

    async def get_boundary_summary(self) -> dict[str, Any]:
        """Get summary statistics for all capability boundaries.

        Returns
        -------
        dict
            Keys:
            - ``total``: total number of recorded boundaries.
            - ``unresolved``: number of unresolved boundaries.
            - ``resolved``: number of resolved boundaries.
            - ``escalated``: number escalated to human.
            - ``retestable``: number currently eligible for retesting.
            - ``by_task_type``: dict of task_type -> count (unresolved only).
            - ``agents_most_involved``: dict of agent_id -> count of
              boundaries where that agent was among those attempted.
        """
        total_row = await self.repository.engine.fetch_one(
            "SELECT COUNT(*) AS cnt FROM capability_boundaries"
        )
        total = int(total_row["cnt"]) if total_row else 0

        unresolved_row = await self.repository.engine.fetch_one(
            "SELECT COUNT(*) AS cnt FROM capability_boundaries WHERE resolved = 0"
        )
        unresolved = int(unresolved_row["cnt"]) if unresolved_row else 0

        resolved_row = await self.repository.engine.fetch_one(
            "SELECT COUNT(*) AS cnt FROM capability_boundaries WHERE resolved = 1"
        )
        resolved = int(resolved_row["cnt"]) if resolved_row else 0

        escalated_row = await self.repository.engine.fetch_one(
            "SELECT COUNT(*) AS cnt FROM capability_boundaries WHERE escalated_to_human = 1"
        )
        escalated = int(escalated_row["cnt"]) if escalated_row else 0

        retestable = await self.get_retestable_boundaries()
        retestable_count = len(retestable)

        # By task_type (unresolved only).
        type_rows = await self.repository.engine.fetch_all(
            """SELECT task_type, COUNT(*) AS cnt
               FROM capability_boundaries
               WHERE resolved = 0
               GROUP BY task_type
               ORDER BY cnt DESC"""
        )
        by_task_type: dict[str, int] = {
            str(r["task_type"]): int(r["cnt"]) for r in type_rows
        }

        # Agents most involved in boundaries.
        all_boundaries = await self.repository.engine.fetch_all(
            "SELECT agents_attempted FROM capability_boundaries WHERE resolved = 0"
        )
        agent_counts: dict[str, int] = {}
        for row in all_boundaries:
            agents = _parse_json_list(row["agents_attempted"])
            for agent in agents:
                agent_counts[agent] = agent_counts.get(agent, 0) + 1

        summary = {
            "total": total,
            "unresolved": unresolved,
            "resolved": resolved,
            "escalated": escalated,
            "retestable": retestable_count,
            "by_task_type": by_task_type,
            "agents_most_involved": agent_counts,
        }

        logger.debug(
            "Boundary summary: total=%d unresolved=%d resolved=%d "
            "escalated=%d retestable=%d",
            total,
            unresolved,
            resolved,
            escalated,
            retestable_count,
        )
        return summary


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _parse_json_list(value: Any) -> list[str]:
    """Safely parse a JSON array string to a Python list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _row_to_boundary_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw DB row to a typed boundary dict with parsed JSON fields."""
    return {
        "id": str(row["id"]),
        "task_type": str(row["task_type"]),
        "task_description": str(row["task_description"]),
        "agents_attempted": _parse_json_list(row.get("agents_attempted", "[]")),
        "failure_signatures": _parse_json_list(row.get("failure_signatures", "[]")),
        "discovered_at": row.get("discovered_at"),
        "last_retested_at": row.get("last_retested_at"),
        "retest_result": row.get("retest_result"),
        "escalated_to_human": bool(row.get("escalated_to_human", 0)),
        "resolved": bool(row.get("resolved", 0)),
    }
