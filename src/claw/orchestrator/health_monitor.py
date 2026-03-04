"""Health monitor for CLAW orchestrator.

Runs at the start of each orchestrator loop iteration to detect and
remediate anomalies before processing the next task.

Checks:
1. Stuck tasks -- tasks in EVALUATING/PLANNING/DISPATCHED/CODING/REVIEWING too long
2. Per-agent circuit breakers -- consecutive failures per agent_id
3. Token budget overrun -- task exceeded max token budget

Adapted from ralfed's HealthMonitor with per-agent circuit breakers
instead of a single global circuit breaker.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from claw.core.config import OrchestratorConfig
from claw.core.models import Task
from claw.db.repository import Repository

logger = logging.getLogger("claw.orchestrator.health_monitor")


class HealthCheck:
    """Result of a single health check."""

    def __init__(
        self,
        check_name: str,
        passed: bool,
        message: str = "",
        remediation: str | None = None,
    ):
        self.check_name = check_name
        self.passed = passed
        self.message = message
        self.remediation = remediation


class HealthMonitor:
    """Anomaly detection and remediation at the start of each loop iteration.

    Per-agent circuit breakers track consecutive failures independently for
    each agent_id. When an agent accumulates 3 consecutive failures, its
    circuit opens with an exponential cooldown (30s * failure_count, capped
    at 300s). A single success resets that agent's failure counter and closes
    its circuit.

    Injected dependencies:
        repository: Async database access for task queries.
        config: Orchestrator configuration for thresholds.
    """

    # Circuit breaker thresholds
    CIRCUIT_OPEN_THRESHOLD = 3
    COOLDOWN_BASE_SECONDS = 30
    COOLDOWN_CAP_SECONDS = 300

    def __init__(
        self,
        repository: Repository,
        config: OrchestratorConfig,
        max_task_age_minutes: int = 30,
        max_tokens_per_task: int = 100_000,
    ):
        self.repository = repository
        self.config = config
        self.max_task_age_minutes = max_task_age_minutes
        self.max_tokens_per_task = max_tokens_per_task

        # Per-agent circuit breaker state
        self._agent_failures: dict[str, int] = {}  # agent_id -> consecutive failures
        self._agent_circuit_open: dict[str, bool] = {}
        self._agent_circuit_until: dict[str, Optional[datetime]] = {}

    async def run_checks(self) -> list[HealthCheck]:
        """Run all health checks. Returns list of check results.

        Checks stuck tasks (async DB query) and all known agent circuits.
        """
        checks: list[HealthCheck] = []

        checks.append(await self._check_stuck_tasks())

        # Check circuit breaker for every known agent
        for agent_id in list(self._agent_failures.keys()):
            checks.append(self._check_agent_circuit(agent_id))

        failed = [c for c in checks if not c.passed]
        if failed:
            logger.warning(
                "Health checks: %d/%d failed: %s",
                len(failed),
                len(checks),
                ", ".join(c.check_name for c in failed),
            )
        else:
            logger.debug("Health checks: all %d passed", len(checks))

        return checks

    async def _check_stuck_tasks(self) -> HealthCheck:
        """Find tasks stuck in processing states too long."""
        in_progress = await self.repository.get_in_progress_tasks()

        stuck_tasks: list[Task] = []
        cutoff = datetime.now(UTC) - timedelta(minutes=self.max_task_age_minutes)

        for task in in_progress:
            # Handle timezone-naive datetimes from DB
            updated = task.updated_at
            if updated is not None and updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            if updated is not None and updated < cutoff:
                stuck_tasks.append(task)

        if not stuck_tasks:
            return HealthCheck("stuck_tasks", passed=True, message="No stuck tasks")

        task_summaries = [
            f"'{t.title}' (status={t.status.value}, updated={t.updated_at.isoformat() if t.updated_at else 'unknown'})"
            for t in stuck_tasks
        ]
        return HealthCheck(
            "stuck_tasks",
            passed=False,
            message=f"{len(stuck_tasks)} stuck task(s): {', '.join(task_summaries)}",
            remediation="Consider rewinding and retrying or marking as STUCK",
        )

    def _check_agent_circuit(self, agent_id: str) -> HealthCheck:
        """Check if a specific agent's circuit breaker is open."""
        is_open = self._agent_circuit_open.get(agent_id, False)

        if not is_open:
            return HealthCheck(
                f"circuit_breaker:{agent_id}",
                passed=True,
                message=f"Agent '{agent_id}' circuit breaker closed",
            )

        circuit_until = self._agent_circuit_until.get(agent_id)
        if circuit_until and datetime.now(UTC) > circuit_until:
            # Cooldown expired -- reset this agent's circuit
            self._agent_circuit_open[agent_id] = False
            self._agent_failures[agent_id] = 0
            self._agent_circuit_until[agent_id] = None
            logger.info("Circuit breaker for agent '%s' reset after cooldown", agent_id)
            return HealthCheck(
                f"circuit_breaker:{agent_id}",
                passed=True,
                message=f"Agent '{agent_id}' circuit breaker reset after cooldown",
            )

        remaining = ""
        if circuit_until:
            delta = circuit_until - datetime.now(UTC)
            remaining_seconds = max(0, int(delta.total_seconds()))
            remaining = f" ({remaining_seconds}s remaining)"

        failures = self._agent_failures.get(agent_id, 0)
        return HealthCheck(
            f"circuit_breaker:{agent_id}",
            passed=False,
            message=f"Agent '{agent_id}' circuit breaker OPEN -- {failures} consecutive failures{remaining}",
            remediation=f"Wait for cooldown or check agent '{agent_id}' provider status",
        )

    def record_agent_success(self, agent_id: str) -> None:
        """Record a successful agent call -- resets that agent's failure counter."""
        self._agent_failures[agent_id] = 0
        if self._agent_circuit_open.get(agent_id, False):
            self._agent_circuit_open[agent_id] = False
            self._agent_circuit_until[agent_id] = None
            logger.info(
                "Circuit breaker for agent '%s' closed after successful call",
                agent_id,
            )

    def record_agent_failure(self, agent_id: str) -> None:
        """Record a failed agent call. Opens circuit breaker after 3 consecutive failures.

        Cooldown uses exponential backoff: 30s * failure_count, capped at 300s.
        """
        current = self._agent_failures.get(agent_id, 0) + 1
        self._agent_failures[agent_id] = current
        logger.warning(
            "Consecutive failures for agent '%s': %d", agent_id, current,
        )

        if current >= self.CIRCUIT_OPEN_THRESHOLD and not self._agent_circuit_open.get(agent_id, False):
            self._agent_circuit_open[agent_id] = True
            cooldown_seconds = min(
                self.COOLDOWN_BASE_SECONDS * current,
                self.COOLDOWN_CAP_SECONDS,
            )
            self._agent_circuit_until[agent_id] = datetime.now(UTC) + timedelta(
                seconds=cooldown_seconds,
            )
            logger.warning(
                "Circuit breaker for agent '%s' OPENED -- cooling down for %ds",
                agent_id,
                cooldown_seconds,
            )

    def check_token_budget(self, task_tokens: int) -> HealthCheck:
        """Check if a task has exceeded its token budget.

        Args:
            task_tokens: Total tokens consumed by the task so far.

        Returns:
            HealthCheck result.
        """
        if task_tokens > self.max_tokens_per_task:
            return HealthCheck(
                "token_budget",
                passed=False,
                message=f"Token budget exceeded: {task_tokens} > {self.max_tokens_per_task}",
                remediation="Mark task as STUCK with reason 'token_budget_exceeded'",
            )
        return HealthCheck(
            "token_budget",
            passed=True,
            message=f"Token budget OK: {task_tokens}/{self.max_tokens_per_task}",
        )

    def is_agent_circuit_open(self, agent_id: str) -> bool:
        """Check if a specific agent's circuit breaker is currently open.

        Also handles auto-reset when cooldown has expired.
        """
        is_open = self._agent_circuit_open.get(agent_id, False)
        if not is_open:
            return False

        circuit_until = self._agent_circuit_until.get(agent_id)
        if circuit_until and datetime.now(UTC) > circuit_until:
            # Cooldown expired -- auto-reset
            self._agent_circuit_open[agent_id] = False
            self._agent_failures[agent_id] = 0
            self._agent_circuit_until[agent_id] = None
            return False

        return True

    def get_agent_status(self) -> dict[str, dict]:
        """Get a summary of all tracked agents' circuit breaker status.

        Returns:
            Dict mapping agent_id to status info including:
            - consecutive_failures: int
            - circuit_open: bool
            - circuit_until: Optional[str] (ISO datetime)
            - cooldown_remaining_seconds: Optional[int]
        """
        result: dict[str, dict] = {}
        now = datetime.now(UTC)

        for agent_id in set(
            list(self._agent_failures.keys())
            + list(self._agent_circuit_open.keys())
        ):
            is_open = self._agent_circuit_open.get(agent_id, False)
            circuit_until = self._agent_circuit_until.get(agent_id)

            # Check if cooldown has expired
            if is_open and circuit_until and now > circuit_until:
                self._agent_circuit_open[agent_id] = False
                self._agent_failures[agent_id] = 0
                self._agent_circuit_until[agent_id] = None
                is_open = False
                circuit_until = None

            cooldown_remaining: Optional[int] = None
            if is_open and circuit_until:
                delta = circuit_until - now
                cooldown_remaining = max(0, int(delta.total_seconds()))

            result[agent_id] = {
                "consecutive_failures": self._agent_failures.get(agent_id, 0),
                "circuit_open": is_open,
                "circuit_until": circuit_until.isoformat() if circuit_until else None,
                "cooldown_remaining_seconds": cooldown_remaining,
            }

        return result
