"""Needs-based pipeline adaptation for CLAW orchestration.

PipelineAdapter examines task properties + memory signals and selects a
pipeline configuration. Determines whether to run full evaluation battery,
lean mode, or minimal mode based on complexity, past failures, and memory
store state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

if TYPE_CHECKING:
    from claw.core.models import Task
    from claw.db.repository import Repository

logger = logging.getLogger("claw.orchestrator.adaptation")


class AdaptationSignals(BaseModel):
    """Aggregated signals for pipeline adaptation decisions."""

    complexity_tier: str = "MEDIUM"
    attempt_number: int = 1
    escalation_count: int = 0
    retrieval_confidence: float = 0.0
    retrieval_conflict_count: int = 0
    memory_store_size: int = 0
    past_failure_count: int = 0
    task_type_hint: str = "unknown"

    @classmethod
    async def from_task(
        cls,
        task: "Task",
        repository: "Repository",
    ) -> "AdaptationSignals":
        """Build signals from a real Task and its database context.

        This is async because CLAW repository calls are async (SQLite with
        aiosqlite). Gathers complexity scoring, past failure counts, and
        task type inference.
        """
        from claw.orchestrator.complexity import score_task_complexity

        complexity_tier = score_task_complexity(task)

        past_failures = 0
        try:
            failed = await repository.get_failed_approaches(task.id)
            past_failures = len(failed)
        except Exception:
            past_failures = 0

        task_type_hint = _infer_task_type(task.title, task.description)

        return cls(
            complexity_tier=complexity_tier.value,
            attempt_number=task.attempt_count,
            escalation_count=task.escalation_count,
            past_failure_count=past_failures,
            task_type_hint=task_type_hint,
        )


class PipelineDecision(BaseModel):
    """What to run and how, based on adaptation signals."""

    template_name: str = "full"
    force_deep_verification: bool = False
    force_arbitration: bool = False
    skip_research: bool = False


class PipelineAdapter:
    """Selects pipeline configuration based on adaptation signals.

    Decision tree:
    - Cold start (empty memory): skip research, use minimal/lean templates
    - TRIVIAL + first attempt + no failures: minimal
    - LOW + no retrieval conflicts: lean
    - HIGH/VERY_HIGH or retry escalation: full + deep verification
    - Retrieval conflicts: full + arbitration
    - Default: full
    """

    def adapt(self, signals: AdaptationSignals) -> PipelineDecision:
        """Evaluate signals and return a pipeline decision."""
        tier = signals.complexity_tier.upper()

        # Cold start: skip research (empty store = wasted call)
        if signals.memory_store_size == 0:
            if tier in ("TRIVIAL", "LOW"):
                return PipelineDecision(
                    template_name="minimal",
                    skip_research=True,
                )
            return PipelineDecision(
                template_name="lean",
                skip_research=True,
            )

        # TRIVIAL + first attempt + no past failures -> minimal
        if (
            tier == "TRIVIAL"
            and signals.attempt_number <= 1
            and signals.past_failure_count == 0
        ):
            return PipelineDecision(template_name="minimal")

        # LOW complexity + no conflicts -> lean
        if tier == "LOW" and signals.retrieval_conflict_count == 0:
            return PipelineDecision(template_name="lean")

        # HIGH/VERY_HIGH or retry escalation -> full + deep verification
        if tier in ("HIGH", "VERY_HIGH") or signals.attempt_number > 2 or signals.escalation_count > 0:
            decision = PipelineDecision(
                template_name="full",
                force_deep_verification=True,
            )
            # Retrieval conflicts -> force arbitration
            if signals.retrieval_conflict_count >= 2:
                decision.force_arbitration = True
            return decision

        # Retrieval conflicts alone -> full + arbitration
        if signals.retrieval_conflict_count >= 2:
            return PipelineDecision(
                template_name="full",
                force_arbitration=True,
            )

        # Default -> full
        return PipelineDecision(template_name="full")


def _infer_task_type(title: str, description: str) -> str:
    """Simple keyword classifier for task type hint."""
    combined = f"{title} {description}".lower()
    if any(kw in combined for kw in ("fix", "bug", "error", "crash")):
        return "bug_fix"
    # Check testing before feature since "add test coverage" is testing, not feature
    if any(kw in combined for kw in ("test", "coverage")):
        return "testing"
    if any(kw in combined for kw in ("add", "implement", "create", "feature")):
        return "feature"
    if any(kw in combined for kw in ("refactor", "rename", "cleanup", "reorganize")):
        return "refactor"
    return "unknown"
