"""CLAW Cycle — the core orchestration abstraction.

The Claw Cycle is a six-step loop: grab → evaluate → decide → act → verify → learn
operating at four nested scales:

- MacroClaw (Fleet) — scans repo fleet, ranks by enhancement potential
- MesoClaw (Project) — runs evaluation battery on one repo, produces plan
- MicroClaw (Module) — takes one task, routes to agent, monitors/verifies
- NanoClaw (Self-improvement) — updates scores and routing after each task

Phase 1 implements MicroClaw only.
"""

from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Optional

from claw.core.factory import ClawContext
from claw.core.models import (
    CycleResult,
    HypothesisEntry,
    HypothesisOutcome,
    Task,
    TaskContext,
    TaskOutcome,
    TaskStatus,
    VerificationResult,
)

logger = logging.getLogger("claw.cycle")


class ClawCycle(ABC):
    """Abstract base for all claw cycle levels."""

    def __init__(self, ctx: ClawContext, level: str):
        self.ctx = ctx
        self.level = level

    @abstractmethod
    async def grab(self) -> Any:
        """Select the next unit of work."""

    @abstractmethod
    async def evaluate(self, target: Any) -> Any:
        """Analyze the target for enhancement potential."""

    @abstractmethod
    async def decide(self, evaluation: Any) -> Any:
        """Choose the best approach/agent for the work."""

    @abstractmethod
    async def act(self, decision: Any) -> Any:
        """Execute the chosen approach."""

    @abstractmethod
    async def verify(self, result: Any) -> Any:
        """Validate the output (tests, quality gates)."""

    @abstractmethod
    async def learn(self, outcome: Any) -> None:
        """Update scores, memory, and routing from the outcome."""

    async def run_cycle(self, on_step=None) -> CycleResult:
        """Execute one complete grab→evaluate→decide→act→verify→learn cycle.

        Args:
            on_step: Optional callback ``(step_name: str, detail: str) -> None``
                     called at each phase transition for progress reporting.
        """
        def _step(name: str, detail: str = "") -> None:
            if on_step is not None:
                on_step(name, detail)

        start = time.monotonic()
        try:
            _step("grab", "Fetching next task...")
            target = await self.grab()
            if target is None:
                return CycleResult(cycle_level=self.level, success=False)

            _step("evaluate", f"Analyzing: {target.title[:60]}")
            evaluation = await self.evaluate(target)

            _step("decide", "Selecting best agent...")
            decision = await self.decide(evaluation)
            agent_id = decision[0] if isinstance(decision, tuple) else "unknown"
            _step("act", f"Agent '{agent_id}' working...")
            result = await self.act(decision)

            _step("verify", "Running verification checks...")
            verification = await self.verify(result)

            _step("learn", "Recording outcome...")
            await self.learn(verification)

            duration = time.monotonic() - start
            # Unpack the verification tuple for result fields
            v_agent_id = verification[0] if isinstance(verification, tuple) else None
            v_outcome = verification[2] if isinstance(verification, tuple) and len(verification) > 2 else TaskOutcome()
            v_result = verification[3] if isinstance(verification, tuple) and len(verification) > 3 else None
            _step("done", f"Cycle complete ({duration:.1f}s)")
            return CycleResult(
                cycle_level=self.level,
                task_id=getattr(target, "id", None),
                agent_id=v_agent_id,
                outcome=v_outcome,
                verification=v_result,
                success=True,
                tokens_used=v_outcome.tokens_used if v_outcome else 0,
                cost_usd=v_outcome.cost_usd if v_outcome else 0.0,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start
            logger.error("Cycle %s failed: %s", self.level, e, exc_info=True)
            return CycleResult(
                cycle_level=self.level,
                success=False,
                duration_seconds=duration,
            )


class MicroClaw(ClawCycle):
    """Single-task cycle: grab one task → route to agent → verify → learn.

    This is the Phase 1 implementation. It processes one task from the
    work queue through the full pipeline.
    """

    def __init__(
        self,
        ctx: ClawContext,
        project_id: str,
        session_id: Optional[str] = None,
    ):
        super().__init__(ctx, level="micro")
        self.project_id = project_id
        self.session_id = session_id or str(uuid.uuid4())
        self._current_task: Optional[Task] = None
        self._current_outcome: Optional[TaskOutcome] = None
        self._current_verification: Optional[VerificationResult] = None

    async def grab(self) -> Optional[Task]:
        """Get the next pending task for the project."""
        task = await self.ctx.repository.get_next_task(self.project_id)
        if task is None:
            logger.info("No pending tasks for project %s", self.project_id)
            return None

        self._current_task = task
        logger.info("Grabbed task: %s (priority=%d)", task.title, task.priority)

        # Log episode
        await self.ctx.repository.log_episode(
            session_id=self.session_id,
            event_type="task_grabbed",
            event_data={"task_id": task.id, "title": task.title},
            project_id=self.project_id,
            task_id=task.id,
            cycle_level="micro",
        )

        return task

    async def evaluate(self, task: Task) -> TaskContext:
        """Build enriched task context with forbidden approaches."""
        await self.ctx.repository.update_task_status(task.id, TaskStatus.EVALUATING)

        # Get failed approaches for this task
        failed = await self.ctx.repository.get_failed_approaches(task.id)
        forbidden = [h.approach_summary for h in failed]

        task_ctx = TaskContext(
            task=task,
            forbidden_approaches=forbidden,
        )

        logger.info("Evaluated task: %d forbidden approaches", len(forbidden))
        return task_ctx

    async def decide(self, task_ctx: TaskContext) -> tuple[str, TaskContext]:
        """Decide which agent to use via Dispatcher + Degradation checks."""
        await self.ctx.repository.update_task_status(task_ctx.task.id, TaskStatus.DISPATCHED)

        # Check degradation: ensure at least one agent is healthy
        if self.ctx.degradation_manager is not None:
            if self.ctx.degradation_manager.is_all_down():
                logger.error("All agents down — escalating to human")
                return ("none", task_ctx)

        # Use Dispatcher for Bayesian routing (with 10% exploration)
        if self.ctx.dispatcher is not None:
            try:
                agent_id = await self.ctx.dispatcher.route_task(task_ctx.task, task_ctx)
            except Exception as e:
                logger.warning("Dispatcher routing failed: %s, falling back", e)
                agent_id = task_ctx.task.recommended_agent or "claude"
        else:
            agent_id = task_ctx.task.recommended_agent or "claude"

        # Check degradation for the chosen agent; get fallback if needed
        if self.ctx.degradation_manager is not None:
            healthy = self.ctx.degradation_manager.get_healthy_agents()
            if agent_id not in healthy:
                fallback = self.ctx.degradation_manager.get_fallback_agent(agent_id)
                if fallback is not None:
                    logger.info("Agent '%s' degraded, falling back to '%s'", agent_id, fallback)
                    agent_id = fallback

        if agent_id not in self.ctx.agents:
            available = list(self.ctx.agents.keys())
            if available:
                agent_id = available[0]
            else:
                logger.error("No agents available")
                return ("none", task_ctx)

        await self.ctx.repository.update_task_agent(task_ctx.task.id, agent_id)
        logger.info("Decided: routing to agent '%s'", agent_id)

        return (agent_id, task_ctx)

    async def act(self, decision: tuple[str, TaskContext]) -> tuple[str, TaskContext, TaskOutcome]:
        """Execute the task through the chosen agent, with budget check."""
        agent_id, task_ctx = decision

        if agent_id == "none" or agent_id not in self.ctx.agents:
            return (agent_id, task_ctx, TaskOutcome(
                agent_id=agent_id,
                failure_reason="no_agent",
                failure_detail="No agent available to execute task",
            ))

        # Budget check before dispatch
        if self.ctx.budget_enforcer is not None:
            budget_results = await self.ctx.budget_enforcer.check_all(
                task_id=task_ctx.task.id,
                project_id=self.project_id,
                agent_id=agent_id,
            )
            exceeded = [r for r in budget_results if r.exceeded]
            if exceeded:
                first = exceeded[0]
                logger.warning(
                    "Budget exceeded (%s): %s",
                    first.check_type, first.entity_id,
                )
                return (agent_id, task_ctx, TaskOutcome(
                    agent_id=agent_id,
                    failure_reason="budget_exceeded",
                    failure_detail=f"Budget cap hit: {first.check_type} ({first.entity_id})",
                ))

        await self.ctx.repository.update_task_status(task_ctx.task.id, TaskStatus.CODING)
        await self.ctx.repository.increment_task_attempt(task_ctx.task.id)

        agent = self.ctx.agents[agent_id]

        # Set token tracking context
        self.ctx.token_tracker.set_context(
            task_id=task_ctx.task.id,
            agent_id=agent_id,
            agent_role=agent_id,
        )

        outcome = await agent.run(task_ctx)
        self._current_outcome = outcome

        logger.info(
            "Act complete: agent=%s, tests_passed=%s, files=%d",
            agent_id, outcome.tests_passed, len(outcome.files_changed),
        )

        return (agent_id, task_ctx, outcome)

    async def verify(self, result: tuple[str, TaskContext, TaskOutcome]) -> tuple[str, TaskContext, TaskOutcome, VerificationResult]:
        """Verify the agent's output using the full 7-check Verifier."""
        agent_id, task_ctx, outcome = result
        await self.ctx.repository.update_task_status(task_ctx.task.id, TaskStatus.REVIEWING)

        if self.ctx.verifier is not None and not outcome.failure_reason:
            # Use the full 7-check Verifier
            verification = await self.ctx.verifier.verify(
                outcome=outcome,
                task_context=task_ctx,
                workspace_dir=getattr(self.ctx.agents.get(agent_id), "workspace_dir", None),
            )
        else:
            # Fallback: basic checks if verifier unavailable or execution failed
            violations = []
            if outcome.failure_reason:
                violations.append({"check": "execution", "detail": outcome.failure_reason})
            if outcome.raw_output:
                for marker in ["TODO", "FIXME", "NotImplementedError", "placeholder", "mock"]:
                    if marker.lower() in outcome.raw_output.lower():
                        violations.append({"check": "placeholder_scan", "detail": f"Found '{marker}' in output"})

            verification = VerificationResult(
                approved=len(violations) == 0 and outcome.tests_passed,
                violations=violations,
                quality_score=1.0 if not violations else 0.5,
            )

        self._current_verification = verification

        logger.info(
            "Verify: approved=%s, violations=%d",
            verification.approved, len(verification.violations),
        )

        return (agent_id, task_ctx, outcome, verification)

    async def learn(self, verified: tuple[str, TaskContext, TaskOutcome, VerificationResult]) -> None:
        """Update memory and scores from the outcome."""
        agent_id, task_ctx, outcome, verification = verified
        task = task_ctx.task

        if verification.approved:
            # Success path
            await self.ctx.repository.update_task_status(task.id, TaskStatus.DONE)

            # Log successful hypothesis
            attempt = await self.ctx.repository.get_next_hypothesis_attempt(task.id)
            await self.ctx.repository.log_hypothesis(HypothesisEntry(
                task_id=task.id,
                attempt_number=attempt,
                approach_summary=outcome.approach_summary[:500],
                outcome=HypothesisOutcome.SUCCESS,
                files_changed=outcome.files_changed,
                duration_seconds=outcome.duration_seconds,
                model_used=outcome.model_used,
                agent_id=agent_id,
            ))

            # Update agent score
            await self.ctx.repository.update_agent_score(
                agent_id=agent_id,
                task_type=task.task_type or "general",
                success=True,
                duration_seconds=outcome.duration_seconds,
                quality_score=verification.quality_score or 0.0,
                cost_usd=outcome.cost_usd,
            )

            logger.info("Learned: task %s completed by %s", task.title, agent_id)

        else:
            # Failure path
            error_sig = outcome.failure_reason or "unknown"
            attempt = await self.ctx.repository.get_next_hypothesis_attempt(task.id)
            await self.ctx.repository.log_hypothesis(HypothesisEntry(
                task_id=task.id,
                attempt_number=attempt,
                approach_summary=outcome.approach_summary[:500] if outcome.approach_summary else "Failed attempt",
                outcome=HypothesisOutcome.FAILURE,
                error_signature=error_sig,
                error_full=outcome.failure_detail,
                files_changed=outcome.files_changed,
                duration_seconds=outcome.duration_seconds,
                model_used=outcome.model_used,
                agent_id=agent_id,
            ))

            # Update agent score (failure)
            await self.ctx.repository.update_agent_score(
                agent_id=agent_id,
                task_type=task.task_type or "general",
                success=False,
                duration_seconds=outcome.duration_seconds,
                quality_score=verification.quality_score or 0.0,
                cost_usd=outcome.cost_usd,
            )

            # Reset to PENDING for retry
            await self.ctx.repository.update_task_status(task.id, TaskStatus.PENDING)

            logger.info(
                "Learned: task %s failed by %s (error: %s)",
                task.title, agent_id, error_sig,
            )

        # Log episode
        await self.ctx.repository.log_episode(
            session_id=self.session_id,
            event_type="cycle_completed",
            event_data={
                "task_id": task.id,
                "agent_id": agent_id,
                "approved": verification.approved,
                "quality_score": verification.quality_score,
            },
            project_id=self.project_id,
            agent_id=agent_id,
            task_id=task.id,
            cycle_level="micro",
        )
