"""Budget enforcement system for CLAW.

Enforces hard spending caps at four levels: per-task, per-project, per-day,
and per-agent. Each check queries the ``token_costs`` table for actual
accumulated spend and compares against configurable limits.

The BudgetEnforcer is consulted before dispatching any agent call. If any
budget dimension is exceeded, the orchestrator pauses and waits for human
approval before continuing.

Budget limits are read from ``ClawConfig.budget`` if present, otherwise
sensible defaults are used. Limits are denominated in USD to provide a
single unit of accounting regardless of which models are invoked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from claw.core.config import ClawConfig
from claw.db.repository import Repository

logger = logging.getLogger("claw.budget")


# ---------------------------------------------------------------------------
# Budget check result
# ---------------------------------------------------------------------------

@dataclass
class BudgetCheckResult:
    """Result of a single budget dimension check.

    Attributes:
        check_type: Which budget dimension was checked.
                    One of "task", "project", "daily", "agent".
        budget_limit_usd: The hard cap for this dimension in USD.
        budget_used_usd: Amount already consumed in USD.
        remaining_usd: Dollars remaining before the cap is hit.
        exceeded: True if budget_used_usd >= budget_limit_usd.
        entity_id: Identifier for the entity being checked. For task
                   checks this is the task_id; for project checks the
                   project_id; for agent checks the agent_id; for daily
                   checks the literal string "daily".
    """

    check_type: str
    budget_limit_usd: float
    budget_used_usd: float
    remaining_usd: float
    exceeded: bool
    entity_id: str


# ---------------------------------------------------------------------------
# Budget enforcer
# ---------------------------------------------------------------------------

class BudgetEnforcer:
    """Enforces hard spending caps across four budget dimensions.

    All budget data is sourced from the ``token_costs`` table via SQL
    aggregation queries. No caching is used -- every check hits the
    database for up-to-date figures.

    Args:
        repository: Data access layer for running budget queries.
        config: Top-level CLAW configuration. If a ``budget`` section
                exists it overrides the default limits.
    """

    # Default budget limits in USD
    DEFAULT_PER_TASK_USD: float = 5.0
    DEFAULT_PER_PROJECT_USD: float = 50.0
    DEFAULT_PER_DAY_USD: float = 100.0
    DEFAULT_PER_AGENT_USD: float = 25.0

    def __init__(self, repository: Repository, config: ClawConfig) -> None:
        self.repository = repository
        self.config = config

        # Read budget limits from config if a budget section exists,
        # otherwise use class-level defaults.
        budget_cfg = getattr(config, "budget", None)
        self.per_task_usd: float = (
            getattr(budget_cfg, "per_task_usd", self.DEFAULT_PER_TASK_USD)
            if budget_cfg is not None
            else self.DEFAULT_PER_TASK_USD
        )
        self.per_project_usd: float = (
            getattr(budget_cfg, "per_project_usd", self.DEFAULT_PER_PROJECT_USD)
            if budget_cfg is not None
            else self.DEFAULT_PER_PROJECT_USD
        )
        self.per_day_usd: float = (
            getattr(budget_cfg, "per_day_usd", self.DEFAULT_PER_DAY_USD)
            if budget_cfg is not None
            else self.DEFAULT_PER_DAY_USD
        )
        self.per_agent_usd: float = (
            getattr(budget_cfg, "per_agent_usd", self.DEFAULT_PER_AGENT_USD)
            if budget_cfg is not None
            else self.DEFAULT_PER_AGENT_USD
        )

        logger.info(
            "BudgetEnforcer initialized: per_task=$%.2f, per_project=$%.2f, "
            "per_day=$%.2f, per_agent=$%.2f",
            self.per_task_usd,
            self.per_project_usd,
            self.per_day_usd,
            self.per_agent_usd,
        )

    # -------------------------------------------------------------------
    # Individual budget checks
    # -------------------------------------------------------------------

    async def check_task_budget(self, task_id: str) -> BudgetCheckResult:
        """Check whether a specific task is within its spending limit.

        Queries ``token_costs`` for all rows matching the given task_id
        and sums their cost_usd values.

        Args:
            task_id: UUID of the task to check.

        Returns:
            BudgetCheckResult for the "task" dimension.
        """
        row = await self.repository.engine.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total FROM token_costs WHERE task_id = ?",
            [task_id],
        )
        used = float(row["total"]) if row else 0.0
        remaining = max(self.per_task_usd - used, 0.0)
        exceeded = used >= self.per_task_usd

        if exceeded:
            logger.warning(
                "Task budget EXCEEDED for task_id=%s: $%.4f / $%.2f",
                task_id, used, self.per_task_usd,
            )

        return BudgetCheckResult(
            check_type="task",
            budget_limit_usd=self.per_task_usd,
            budget_used_usd=used,
            remaining_usd=remaining,
            exceeded=exceeded,
            entity_id=task_id,
        )

    async def check_project_budget(self, project_id: str) -> BudgetCheckResult:
        """Check whether a project's cumulative spend is within its limit.

        Joins ``token_costs`` with ``tasks`` to aggregate all costs
        belonging to the given project.

        Args:
            project_id: UUID of the project to check.

        Returns:
            BudgetCheckResult for the "project" dimension.
        """
        row = await self.repository.engine.fetch_one(
            """SELECT COALESCE(SUM(tc.cost_usd), 0.0) AS total
               FROM token_costs tc
               JOIN tasks t ON tc.task_id = t.id
               WHERE t.project_id = ?""",
            [project_id],
        )
        used = float(row["total"]) if row else 0.0
        remaining = max(self.per_project_usd - used, 0.0)
        exceeded = used >= self.per_project_usd

        if exceeded:
            logger.warning(
                "Project budget EXCEEDED for project_id=%s: $%.4f / $%.2f",
                project_id, used, self.per_project_usd,
            )

        return BudgetCheckResult(
            check_type="project",
            budget_limit_usd=self.per_project_usd,
            budget_used_usd=used,
            remaining_usd=remaining,
            exceeded=exceeded,
            entity_id=project_id,
        )

    async def check_daily_budget(self) -> BudgetCheckResult:
        """Check whether today's total spend across all tasks is within limit.

        Queries ``token_costs`` for all rows with ``created_at`` on or
        after today's midnight UTC.

        Returns:
            BudgetCheckResult for the "daily" dimension.
        """
        today_start = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00Z")
        row = await self.repository.engine.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total FROM token_costs WHERE created_at >= ?",
            [today_start],
        )
        used = float(row["total"]) if row else 0.0
        remaining = max(self.per_day_usd - used, 0.0)
        exceeded = used >= self.per_day_usd

        if exceeded:
            logger.warning(
                "Daily budget EXCEEDED: $%.4f / $%.2f", used, self.per_day_usd,
            )

        return BudgetCheckResult(
            check_type="daily",
            budget_limit_usd=self.per_day_usd,
            budget_used_usd=used,
            remaining_usd=remaining,
            exceeded=exceeded,
            entity_id="daily",
        )

    async def check_agent_budget(self, agent_id: str) -> BudgetCheckResult:
        """Check whether an agent's spend today is within its limit.

        Queries ``token_costs`` for all rows matching the agent_id with
        ``created_at`` on or after today's midnight UTC.

        Args:
            agent_id: Identifier of the agent (e.g. "claude", "codex").

        Returns:
            BudgetCheckResult for the "agent" dimension.
        """
        today_start = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00Z")
        row = await self.repository.engine.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total FROM token_costs WHERE agent_id = ? AND created_at >= ?",
            [agent_id, today_start],
        )
        used = float(row["total"]) if row else 0.0
        remaining = max(self.per_agent_usd - used, 0.0)
        exceeded = used >= self.per_agent_usd

        if exceeded:
            logger.warning(
                "Agent budget EXCEEDED for agent_id=%s: $%.4f / $%.2f",
                agent_id, used, self.per_agent_usd,
            )

        return BudgetCheckResult(
            check_type="agent",
            budget_limit_usd=self.per_agent_usd,
            budget_used_usd=used,
            remaining_usd=remaining,
            exceeded=exceeded,
            entity_id=agent_id,
        )

    # -------------------------------------------------------------------
    # Composite checks
    # -------------------------------------------------------------------

    async def check_all(
        self, task_id: str, project_id: str, agent_id: str
    ) -> list[BudgetCheckResult]:
        """Run all four budget checks and return the results.

        This is the primary entry point called before dispatching a task
        to an agent. All four dimensions are checked sequentially.

        Args:
            task_id: UUID of the task about to be dispatched.
            project_id: UUID of the owning project.
            agent_id: Agent that will execute the task.

        Returns:
            A list of four BudgetCheckResult objects, one per dimension:
            [task, project, daily, agent].
        """
        results: list[BudgetCheckResult] = []

        task_result = await self.check_task_budget(task_id)
        results.append(task_result)

        project_result = await self.check_project_budget(project_id)
        results.append(project_result)

        daily_result = await self.check_daily_budget()
        results.append(daily_result)

        agent_result = await self.check_agent_budget(agent_id)
        results.append(agent_result)

        exceeded_count = sum(1 for r in results if r.exceeded)
        if exceeded_count > 0:
            exceeded_types = [r.check_type for r in results if r.exceeded]
            logger.warning(
                "Budget check: %d of 4 dimensions exceeded: %s",
                exceeded_count, ", ".join(exceeded_types),
            )
        else:
            logger.debug(
                "Budget check: all 4 dimensions within limits for "
                "task=%s, project=%s, agent=%s",
                task_id, project_id, agent_id,
            )

        return results

    async def should_pause(
        self, task_id: str, project_id: str, agent_id: str
    ) -> tuple[bool, str]:
        """Determine if the orchestrator should pause due to budget exceedance.

        Runs all four budget checks. If any dimension is exceeded, returns
        True with a human-readable reason string explaining which budgets
        were exceeded and by how much.

        Args:
            task_id: UUID of the task about to be dispatched.
            project_id: UUID of the owning project.
            agent_id: Agent that will execute the task.

        Returns:
            A tuple of (should_pause: bool, reason: str). If should_pause
            is False, reason is an empty string.
        """
        results = await self.check_all(task_id, project_id, agent_id)
        exceeded = [r for r in results if r.exceeded]

        if not exceeded:
            return False, ""

        reasons: list[str] = []
        for r in exceeded:
            reasons.append(
                f"{r.check_type} budget exceeded for '{r.entity_id}': "
                f"${r.budget_used_usd:.4f} used of ${r.budget_limit_usd:.2f} limit"
            )

        combined_reason = "; ".join(reasons)
        logger.warning("Budget pause triggered: %s", combined_reason)
        return True, combined_reason

    # -------------------------------------------------------------------
    # Status reporting
    # -------------------------------------------------------------------

    async def get_budget_status(self) -> dict[str, Any]:
        """Get a comprehensive summary of the current budget state.

        Returns a dictionary with budget usage across all dimensions,
        suitable for dashboard display or logging.

        Returns:
            Dictionary with keys:
            - ``daily``: BudgetCheckResult dict for today's total spend.
            - ``limits``: The configured limits for all four dimensions.
            - ``daily_breakdown_by_agent``: Per-agent spend for today.
        """
        daily_result = await self.check_daily_budget()
        today_start = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00Z")

        # Per-agent breakdown for today
        agent_rows = await self.repository.engine.fetch_all(
            """SELECT agent_id, COALESCE(SUM(cost_usd), 0.0) AS total
               FROM token_costs
               WHERE created_at >= ? AND agent_id IS NOT NULL
               GROUP BY agent_id
               ORDER BY total DESC""",
            [today_start],
        )
        agent_breakdown: dict[str, float] = {}
        for row in agent_rows:
            agent_id = row.get("agent_id")
            if agent_id:
                agent_breakdown[agent_id] = float(row["total"])

        return {
            "daily": {
                "limit_usd": daily_result.budget_limit_usd,
                "used_usd": daily_result.budget_used_usd,
                "remaining_usd": daily_result.remaining_usd,
                "exceeded": daily_result.exceeded,
            },
            "limits": {
                "per_task_usd": self.per_task_usd,
                "per_project_usd": self.per_project_usd,
                "per_day_usd": self.per_day_usd,
                "per_agent_usd": self.per_agent_usd,
            },
            "daily_breakdown_by_agent": agent_breakdown,
        }
