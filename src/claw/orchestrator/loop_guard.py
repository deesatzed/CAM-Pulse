"""Approach loop detection -- prevents retrying the same failing strategy.

When the same error signature repeats beyond a threshold, force a strategy
change (switch agent or approach) or mark the task as STUCK.

Adapted from ralfed's loop_guard with async DB calls and string task IDs
to match CLAW's SQLite TEXT PRIMARY KEY convention.
"""

from __future__ import annotations

import logging
from enum import Enum

from claw.db.repository import Repository

logger = logging.getLogger("claw.orchestrator.loop_guard")


class LoopVerdict(str, Enum):
    OK = "ok"                      # No loop detected, proceed normally
    FORCE_SWITCH = "force_switch"  # Same error 2+ times, force strategy change
    STUCK = "stuck"                # Same error 3+ times, mark task STUCK


async def check_error_loop(
    repository: Repository,
    task_id: str,
    error_signature: str,
    force_switch_threshold: int = 2,
    stuck_threshold: int = 3,
) -> LoopVerdict:
    """Check if an error signature has repeated beyond thresholds.

    Queries the hypothesis_log via Repository.count_error_signature() to
    count how many times the same error_signature has been recorded for
    the given task. Returns a verdict that the orchestrator should act on:

    - OK: Error is new or below threshold, proceed normally.
    - FORCE_SWITCH: Error has repeated force_switch_threshold times.
      The orchestrator should switch to a different agent or approach.
    - STUCK: Error has repeated stuck_threshold times. The orchestrator
      should mark the task as STUCK and escalate to a human.

    Args:
        repository: Async database access layer.
        task_id: The current task (TEXT primary key).
        error_signature: Normalized error signature from the latest failure.
        force_switch_threshold: Repeats before forcing strategy switch (default 2).
        stuck_threshold: Repeats before marking STUCK (default 3).

    Returns:
        LoopVerdict indicating what action to take.
    """
    if not error_signature:
        return LoopVerdict.OK

    count = await repository.count_error_signature(task_id, error_signature)

    if count >= stuck_threshold:
        logger.warning(
            "Loop guard: error '%s' seen %d times for task %s -- STUCK",
            error_signature[:80],
            count,
            task_id,
        )
        return LoopVerdict.STUCK

    if count >= force_switch_threshold:
        logger.info(
            "Loop guard: error '%s' seen %d times for task %s -- forcing strategy switch",
            error_signature[:80],
            count,
            task_id,
        )
        return LoopVerdict.FORCE_SWITCH

    return LoopVerdict.OK
