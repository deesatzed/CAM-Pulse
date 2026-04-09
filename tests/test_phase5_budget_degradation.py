"""Tests for CLAW Phase 5 -- BudgetEnforcer and DegradationManager.

Covers:
  1. BudgetEnforcer  -- per-task, per-project, per-day, per-agent budget checks,
                        composite check_all, should_pause, get_budget_status,
                        custom config limits, BudgetCheckResult dataclass
  2. DegradationManager -- healthy agent tracking, circuit-breaker integration,
                           rate-limit tracking, fallback routing, system-wide
                           health assessment, degradation status reporting

NO mocks, NO placeholders, NO cached responses, NO simulation. All tests use real
SQLite in-memory databases via the ``db_engine`` / ``repository`` fixtures from conftest.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from claw.budget import BudgetCheckResult, BudgetEnforcer
from claw.core.config import ClawConfig, OrchestratorConfig
from claw.core.models import Project, Task, TokenCostRecord
from claw.db.repository import Repository
from claw.degradation import DEFAULT_AGENT_IDS, DegradationManager
from claw.orchestrator.health_monitor import HealthMonitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _yesterday_iso() -> str:
    return (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _create_project(repository: Repository, project_id: str | None = None) -> str:
    """Insert a real project and return its ID."""
    pid = project_id or _uid()
    project = Project(
        id=pid,
        name="budget-test-project",
        repo_path="/tmp/budget-test",
    )
    await repository.create_project(project)
    return pid


async def _create_task(
    repository: Repository,
    project_id: str,
    task_id: str | None = None,
) -> str:
    """Insert a real task under the given project and return its ID."""
    tid = task_id or _uid()
    task = Task(
        id=tid,
        project_id=project_id,
        title="budget test task",
        description="A task for budget testing",
    )
    await repository.create_task(task)
    return tid


async def _insert_project_and_task(
    repository: Repository,
    project_id: str | None = None,
    task_id: str | None = None,
) -> tuple[str, str]:
    """Insert a real project and task; return (project_id, task_id)."""
    pid = await _create_project(repository, project_id)
    tid = await _create_task(repository, pid, task_id)
    return pid, tid


async def _insert_token_cost(
    engine,
    *,
    task_id: str | None = None,
    agent_id: str = "claude",
    cost_usd: float = 1.0,
    created_at: str | None = None,
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> str:
    """Insert a real row into token_costs with controllable fields.

    IMPORTANT: task_id must reference an existing tasks row (FK constraint)
    or be None.
    """
    cost_id = _uid()
    if created_at is None:
        created_at = _now_iso()
    await engine.execute(
        """INSERT INTO token_costs
           (id, task_id, agent_id, agent_role, model_used,
            input_tokens, output_tokens, total_tokens, cost_usd, created_at)
           VALUES (?, ?, ?, '', '', ?, ?, ?, ?, ?)""",
        [cost_id, task_id, agent_id, input_tokens, output_tokens,
         input_tokens + output_tokens, cost_usd, created_at],
    )
    return cost_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def enforcer(repository: Repository) -> BudgetEnforcer:
    """BudgetEnforcer with default config (no budget section)."""
    config = ClawConfig()
    return BudgetEnforcer(repository=repository, config=config)


@pytest.fixture
async def health_monitor(repository: Repository) -> HealthMonitor:
    """Real HealthMonitor using in-memory DB."""
    config = OrchestratorConfig()
    return HealthMonitor(repository=repository, config=config)


@pytest.fixture
async def degradation(health_monitor: HealthMonitor) -> DegradationManager:
    """DegradationManager with default agent list."""
    return DegradationManager(health_monitor=health_monitor)


# ===========================================================================
# Module 1: BudgetEnforcer
# ===========================================================================


class TestBudgetCheckResultDataclass:
    """Tests for the BudgetCheckResult dataclass creation and field access."""

    def test_create_budget_check_result(self):
        """BudgetCheckResult stores all fields correctly."""
        result = BudgetCheckResult(
            check_type="task",
            budget_limit_usd=5.0,
            budget_used_usd=2.0,
            remaining_usd=3.0,
            exceeded=False,
            entity_id="task-123",
        )
        assert result.check_type == "task"
        assert result.budget_limit_usd == 5.0
        assert result.budget_used_usd == 2.0
        assert result.remaining_usd == 3.0
        assert result.exceeded is False
        assert result.entity_id == "task-123"

    def test_exceeded_budget_check_result(self):
        """BudgetCheckResult with exceeded=True has zero remaining."""
        result = BudgetCheckResult(
            check_type="daily",
            budget_limit_usd=100.0,
            budget_used_usd=120.0,
            remaining_usd=0.0,
            exceeded=True,
            entity_id="daily",
        )
        assert result.exceeded is True
        assert result.remaining_usd == 0.0
        assert result.budget_used_usd > result.budget_limit_usd


class TestBudgetEnforcerInit:
    """Tests for BudgetEnforcer initialization and default limits."""

    async def test_init_with_default_config(self, repository: Repository):
        """BudgetEnforcer with no budget section uses default limits."""
        config = ClawConfig()
        enforcer = BudgetEnforcer(repository=repository, config=config)
        assert enforcer.per_task_usd == 5.0
        assert enforcer.per_project_usd == 50.0
        assert enforcer.per_day_usd == 100.0
        assert enforcer.per_agent_usd == 25.0

    async def test_init_with_custom_budget_config(self, repository: Repository):
        """BudgetEnforcer reads limits from config.budget when present."""
        config = ClawConfig()
        # Pydantic models do not allow arbitrary attributes by default,
        # so we set it directly on the instance dict.
        object.__setattr__(config, "budget", SimpleNamespace(
            per_task_usd=10.0,
            per_project_usd=100.0,
            per_day_usd=200.0,
            per_agent_usd=50.0,
        ))
        enforcer = BudgetEnforcer(repository=repository, config=config)
        assert enforcer.per_task_usd == 10.0
        assert enforcer.per_project_usd == 100.0
        assert enforcer.per_day_usd == 200.0
        assert enforcer.per_agent_usd == 50.0

    async def test_init_with_partial_budget_config(self, repository: Repository):
        """BudgetEnforcer falls back to defaults for missing budget attributes."""
        config = ClawConfig()
        object.__setattr__(config, "budget", SimpleNamespace(per_task_usd=7.0))
        enforcer = BudgetEnforcer(repository=repository, config=config)
        assert enforcer.per_task_usd == 7.0
        # Others should fall back to defaults
        assert enforcer.per_project_usd == 50.0
        assert enforcer.per_day_usd == 100.0
        assert enforcer.per_agent_usd == 25.0


class TestCheckTaskBudget:
    """Tests for BudgetEnforcer.check_task_budget()."""

    async def test_no_costs_returns_zero_used(self, enforcer: BudgetEnforcer):
        """Task with no token_costs rows shows $0 used, not exceeded."""
        result = await enforcer.check_task_budget("nonexistent-task")
        assert result.check_type == "task"
        assert result.budget_used_usd == 0.0
        assert result.remaining_usd == 5.0
        assert result.exceeded is False
        assert result.entity_id == "nonexistent-task"

    async def test_costs_below_limit(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """Task with spend below $5 limit is not exceeded."""
        pid, tid = await _insert_project_and_task(repository)
        await _insert_token_cost(repository.engine, task_id=tid, cost_usd=2.50)
        result = await enforcer.check_task_budget(tid)
        assert result.budget_used_usd == pytest.approx(2.50)
        assert result.remaining_usd == pytest.approx(2.50)
        assert result.exceeded is False

    async def test_costs_at_limit_is_exceeded(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """Task with spend exactly at $5 limit triggers exceeded (>= comparison)."""
        pid, tid = await _insert_project_and_task(repository)
        await _insert_token_cost(repository.engine, task_id=tid, cost_usd=5.0)
        result = await enforcer.check_task_budget(tid)
        assert result.budget_used_usd == pytest.approx(5.0)
        assert result.remaining_usd == 0.0
        assert result.exceeded is True

    async def test_costs_above_limit(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """Task with spend above $5 limit is exceeded with zero remaining."""
        pid, tid = await _insert_project_and_task(repository)
        await _insert_token_cost(repository.engine, task_id=tid, cost_usd=3.0)
        await _insert_token_cost(repository.engine, task_id=tid, cost_usd=4.0)
        result = await enforcer.check_task_budget(tid)
        assert result.budget_used_usd == pytest.approx(7.0)
        assert result.remaining_usd == 0.0
        assert result.exceeded is True


class TestCheckProjectBudget:
    """Tests for BudgetEnforcer.check_project_budget()."""

    async def test_no_costs_returns_zero(self, enforcer: BudgetEnforcer):
        """Project with no associated token_costs shows $0 used."""
        result = await enforcer.check_project_budget("no-such-project")
        assert result.check_type == "project"
        assert result.budget_used_usd == 0.0
        assert result.exceeded is False

    async def test_project_budget_with_costs(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """Project budget aggregates costs across multiple tasks via JOIN."""
        pid = await _create_project(repository)
        tid1 = await _create_task(repository, pid)
        tid2 = await _create_task(repository, pid)

        await _insert_token_cost(repository.engine, task_id=tid1, cost_usd=10.0)
        await _insert_token_cost(repository.engine, task_id=tid2, cost_usd=15.0)

        result = await enforcer.check_project_budget(pid)
        assert result.budget_used_usd == pytest.approx(25.0)
        assert result.exceeded is False  # Under $50 default
        assert result.entity_id == pid

    async def test_project_budget_exceeded(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """Project budget triggers exceeded when aggregate crosses $50."""
        pid, tid = await _insert_project_and_task(repository)
        await _insert_token_cost(repository.engine, task_id=tid, cost_usd=50.0)

        result = await enforcer.check_project_budget(pid)
        assert result.exceeded is True
        assert result.remaining_usd == 0.0


class TestCheckDailyBudget:
    """Tests for BudgetEnforcer.check_daily_budget()."""

    async def test_no_costs_today(self, enforcer: BudgetEnforcer):
        """No token_costs rows today results in $0 used."""
        result = await enforcer.check_daily_budget()
        assert result.check_type == "daily"
        assert result.budget_used_usd == 0.0
        assert result.exceeded is False
        assert result.entity_id == "daily"

    async def test_costs_today_below_limit(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """Costs inserted with today's timestamp are counted."""
        # Use task_id=None to avoid FK constraint (daily budget is task-agnostic)
        await _insert_token_cost(
            repository.engine, task_id=None, cost_usd=30.0,
            created_at=_now_iso(),
        )
        result = await enforcer.check_daily_budget()
        assert result.budget_used_usd == pytest.approx(30.0)
        assert result.exceeded is False

    async def test_daily_budget_exceeded(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """Daily budget triggers exceeded at $100."""
        await _insert_token_cost(
            repository.engine, task_id=None, cost_usd=60.0,
            created_at=_now_iso(),
        )
        await _insert_token_cost(
            repository.engine, task_id=None, cost_usd=50.0,
            created_at=_now_iso(),
        )
        result = await enforcer.check_daily_budget()
        assert result.budget_used_usd == pytest.approx(110.0)
        assert result.exceeded is True

    async def test_yesterday_costs_excluded(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """Costs from yesterday are NOT counted in today's daily budget."""
        await _insert_token_cost(
            repository.engine, task_id=None, cost_usd=99.0,
            created_at=_yesterday_iso(),
        )
        result = await enforcer.check_daily_budget()
        assert result.budget_used_usd == pytest.approx(0.0)
        assert result.exceeded is False


class TestCheckAgentBudget:
    """Tests for BudgetEnforcer.check_agent_budget()."""

    async def test_no_costs_for_agent(self, enforcer: BudgetEnforcer):
        """Agent with no token_costs today shows $0."""
        result = await enforcer.check_agent_budget("claude")
        assert result.check_type == "agent"
        assert result.budget_used_usd == 0.0
        assert result.exceeded is False
        assert result.entity_id == "claude"

    async def test_agent_costs_below_limit(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """Agent costs below $25 daily limit are not exceeded."""
        await _insert_token_cost(
            repository.engine, task_id=None, agent_id="codex",
            cost_usd=10.0, created_at=_now_iso(),
        )
        result = await enforcer.check_agent_budget("codex")
        assert result.budget_used_usd == pytest.approx(10.0)
        assert result.exceeded is False

    async def test_agent_budget_exceeded(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """Agent costs at or above $25 trigger exceeded."""
        await _insert_token_cost(
            repository.engine, task_id=None, agent_id="gemini",
            cost_usd=25.0, created_at=_now_iso(),
        )
        result = await enforcer.check_agent_budget("gemini")
        assert result.exceeded is True
        assert result.remaining_usd == 0.0

    async def test_agent_yesterday_costs_excluded(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """Agent costs from yesterday do not count toward today's agent budget."""
        await _insert_token_cost(
            repository.engine, task_id=None, agent_id="grok",
            cost_usd=24.0, created_at=_yesterday_iso(),
        )
        result = await enforcer.check_agent_budget("grok")
        assert result.budget_used_usd == pytest.approx(0.0)
        assert result.exceeded is False


class TestCheckAll:
    """Tests for BudgetEnforcer.check_all() composite check."""

    async def test_returns_four_results(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """check_all returns exactly 4 BudgetCheckResult objects."""
        pid, tid = await _insert_project_and_task(repository)
        results = await enforcer.check_all(tid, pid, "claude")
        assert len(results) == 4
        check_types = [r.check_type for r in results]
        assert check_types == ["task", "project", "daily", "agent"]

    async def test_all_under_budget(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """check_all with no costs shows all dimensions under budget."""
        pid, tid = await _insert_project_and_task(repository)
        results = await enforcer.check_all(tid, pid, "claude")
        assert all(not r.exceeded for r in results)

    async def test_some_exceeded(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """check_all returns correct exceeded flags per dimension."""
        pid, tid = await _insert_project_and_task(repository)
        # Exceed the task budget ($5) but stay under project, daily, agent
        await _insert_token_cost(
            repository.engine, task_id=tid, agent_id="claude",
            cost_usd=6.0, created_at=_now_iso(),
        )
        results = await enforcer.check_all(tid, pid, "claude")
        exceeded_types = [r.check_type for r in results if r.exceeded]
        assert "task" in exceeded_types
        assert "project" not in exceeded_types
        assert "daily" not in exceeded_types
        assert "agent" not in exceeded_types


class TestShouldPause:
    """Tests for BudgetEnforcer.should_pause()."""

    async def test_returns_false_when_under_budget(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """should_pause returns (False, '') when all budgets are clear."""
        pid, tid = await _insert_project_and_task(repository)
        should, reason = await enforcer.should_pause(tid, pid, "claude")
        assert should is False
        assert reason == ""

    async def test_returns_true_when_exceeded(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """should_pause returns (True, reason_string) when a budget is exceeded."""
        pid, tid = await _insert_project_and_task(repository)
        await _insert_token_cost(
            repository.engine, task_id=tid, agent_id="claude",
            cost_usd=6.0, created_at=_now_iso(),
        )
        should, reason = await enforcer.should_pause(tid, pid, "claude")
        assert should is True
        assert reason != ""

    async def test_reason_string_contains_check_type(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """The pause reason string includes the check type that was exceeded."""
        pid, tid = await _insert_project_and_task(repository)
        await _insert_token_cost(
            repository.engine, task_id=tid, agent_id="claude",
            cost_usd=6.0, created_at=_now_iso(),
        )
        _, reason = await enforcer.should_pause(tid, pid, "claude")
        assert "task budget exceeded" in reason
        assert tid in reason


class TestGetBudgetStatus:
    """Tests for BudgetEnforcer.get_budget_status()."""

    async def test_status_structure(self, enforcer: BudgetEnforcer):
        """get_budget_status returns dict with expected top-level keys."""
        status = await enforcer.get_budget_status()
        assert "daily" in status
        assert "limits" in status
        assert "daily_breakdown_by_agent" in status

    async def test_status_daily_fields(self, enforcer: BudgetEnforcer):
        """The daily sub-dict has limit, used, remaining, exceeded fields."""
        status = await enforcer.get_budget_status()
        daily = status["daily"]
        assert "limit_usd" in daily
        assert "used_usd" in daily
        assert "remaining_usd" in daily
        assert "exceeded" in daily
        assert daily["limit_usd"] == 100.0

    async def test_status_limits(self, enforcer: BudgetEnforcer):
        """The limits sub-dict reflects the configured budget limits."""
        status = await enforcer.get_budget_status()
        limits = status["limits"]
        assert limits["per_task_usd"] == 5.0
        assert limits["per_project_usd"] == 50.0
        assert limits["per_day_usd"] == 100.0
        assert limits["per_agent_usd"] == 25.0

    async def test_status_agent_breakdown(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """daily_breakdown_by_agent shows per-agent cost totals for today."""
        await _insert_token_cost(
            repository.engine, task_id=None, agent_id="claude",
            cost_usd=5.0, created_at=_now_iso(),
        )
        await _insert_token_cost(
            repository.engine, task_id=None, agent_id="codex",
            cost_usd=3.0, created_at=_now_iso(),
        )
        status = await enforcer.get_budget_status()
        breakdown = status["daily_breakdown_by_agent"]
        assert "claude" in breakdown
        assert "codex" in breakdown
        assert breakdown["claude"] == pytest.approx(5.0)
        assert breakdown["codex"] == pytest.approx(3.0)

    async def test_status_agent_breakdown_excludes_yesterday(
        self, enforcer: BudgetEnforcer, repository: Repository
    ):
        """daily_breakdown_by_agent does not include yesterday's costs."""
        await _insert_token_cost(
            repository.engine, task_id=None, agent_id="grok",
            cost_usd=20.0, created_at=_yesterday_iso(),
        )
        status = await enforcer.get_budget_status()
        breakdown = status["daily_breakdown_by_agent"]
        assert breakdown.get("grok", 0.0) == pytest.approx(0.0)


# ===========================================================================
# Module 2: DegradationManager
# ===========================================================================


class TestDegradationManagerInit:
    """Tests for DegradationManager initialization."""

    async def test_init_with_defaults(self, health_monitor: HealthMonitor):
        """DegradationManager uses default agent IDs when none provided."""
        dm = DegradationManager(health_monitor=health_monitor)
        assert dm.all_agent_ids == sorted(DEFAULT_AGENT_IDS)
        assert dm.dispatcher is None

    async def test_init_with_custom_agent_ids(self, health_monitor: HealthMonitor):
        """DegradationManager accepts a custom list of agent IDs."""
        custom = ["alpha", "beta"]
        dm = DegradationManager(
            health_monitor=health_monitor, all_agent_ids=custom,
        )
        assert dm.all_agent_ids == ["alpha", "beta"]


class TestGetHealthyAgents:
    """Tests for DegradationManager.get_healthy_agents()."""

    async def test_all_healthy_when_no_failures(self, degradation: DegradationManager):
        """All agents are healthy when no failures have been recorded."""
        healthy = degradation.get_healthy_agents()
        assert sorted(healthy) == sorted(DEFAULT_AGENT_IDS)

    async def test_excludes_circuit_open_agents(
        self, degradation: DegradationManager, health_monitor: HealthMonitor
    ):
        """Agents with open circuit breakers are excluded from healthy list."""
        # 3 failures opens the circuit
        for _ in range(3):
            health_monitor.record_agent_failure("codex")
        healthy = degradation.get_healthy_agents()
        assert "codex" not in healthy
        assert "claude" in healthy
        assert "gemini" in healthy
        assert "grok" in healthy

    async def test_excludes_rate_limited_agents(
        self, degradation: DegradationManager
    ):
        """Agents with active rate-limit backoff are excluded from healthy list."""
        degradation.record_rate_limit("gemini", 300)
        healthy = degradation.get_healthy_agents()
        assert "gemini" not in healthy
        assert "claude" in healthy

    async def test_excludes_both_circuit_open_and_rate_limited(
        self, degradation: DegradationManager, health_monitor: HealthMonitor
    ):
        """Both circuit-open and rate-limited agents are excluded simultaneously."""
        for _ in range(3):
            health_monitor.record_agent_failure("codex")
        degradation.record_rate_limit("grok", 300)
        healthy = degradation.get_healthy_agents()
        assert "codex" not in healthy
        assert "grok" not in healthy
        assert "claude" in healthy
        assert "gemini" in healthy


class TestGetFallbackAgent:
    """Tests for DegradationManager.get_fallback_agent()."""

    async def test_prefers_claude(self, degradation: DegradationManager):
        """When claude is healthy and not the preferred, it is chosen as fallback."""
        fallback = degradation.get_fallback_agent("codex")
        assert fallback == "claude"

    async def test_first_alphabetical_when_claude_is_preferred(
        self, degradation: DegradationManager
    ):
        """When claude IS the preferred, the first alphabetical alternative is selected."""
        fallback = degradation.get_fallback_agent("claude")
        # Remaining healthy: codex, gemini, grok -- codex is first alphabetically
        assert fallback == "codex"

    async def test_returns_none_when_no_alternatives(
        self, health_monitor: HealthMonitor
    ):
        """Returns None when no alternative agents are available."""
        # Only one agent known
        dm = DegradationManager(
            health_monitor=health_monitor, all_agent_ids=["solo"],
        )
        fallback = dm.get_fallback_agent("solo")
        assert fallback is None

    async def test_returns_none_when_all_others_down(
        self, degradation: DegradationManager, health_monitor: HealthMonitor
    ):
        """Returns None when all agents except the preferred are down."""
        for agent in ["codex", "gemini", "grok", "local"]:
            for _ in range(3):
                health_monitor.record_agent_failure(agent)
        fallback = degradation.get_fallback_agent("claude")
        assert fallback is None

    async def test_fallback_skips_rate_limited_agents(
        self, degradation: DegradationManager
    ):
        """Fallback excludes agents that are rate-limited."""
        degradation.record_rate_limit("claude", 300)
        fallback = degradation.get_fallback_agent("codex")
        # Claude is rate limited so should not be chosen
        assert fallback != "claude"
        assert fallback in ["gemini", "grok", "local"]


class TestRouteWithFallback:
    """Tests for DegradationManager.route_with_fallback()."""

    async def test_returns_primary_when_healthy(
        self, degradation: DegradationManager
    ):
        """Returns preferred agent with reason 'primary' when it is healthy."""
        agent, reason = await degradation.route_with_fallback("analysis", "claude")
        assert agent == "claude"
        assert reason == "primary"

    async def test_returns_fallback_when_circuit_open(
        self, degradation: DegradationManager, health_monitor: HealthMonitor
    ):
        """Returns fallback agent when preferred has open circuit breaker."""
        for _ in range(3):
            health_monitor.record_agent_failure("codex")
        agent, reason = await degradation.route_with_fallback("refactoring", "codex")
        assert agent != "codex"
        assert reason.startswith("fallback_")
        assert agent in reason

    async def test_returns_fallback_when_rate_limited(
        self, degradation: DegradationManager
    ):
        """Returns fallback agent when preferred is rate-limited."""
        degradation.record_rate_limit("gemini", 300)
        agent, reason = await degradation.route_with_fallback("analysis", "gemini")
        assert agent != "gemini"
        assert reason.startswith("fallback_")

    async def test_returns_no_fallback_when_all_down(
        self, degradation: DegradationManager, health_monitor: HealthMonitor
    ):
        """Returns preferred agent with 'no_fallback' when everything is down."""
        for agent_id in DEFAULT_AGENT_IDS:
            for _ in range(3):
                health_monitor.record_agent_failure(agent_id)
        agent, reason = await degradation.route_with_fallback("analysis", "claude")
        assert agent == "claude"
        assert reason == "no_fallback"


class TestIsAllDown:
    """Tests for DegradationManager.is_all_down()."""

    async def test_false_when_all_healthy(self, degradation: DegradationManager):
        """is_all_down returns False when all agents are healthy."""
        assert degradation.is_all_down() is False

    async def test_false_when_one_down(
        self, degradation: DegradationManager, health_monitor: HealthMonitor
    ):
        """is_all_down returns False when only one agent is down."""
        for _ in range(3):
            health_monitor.record_agent_failure("grok")
        assert degradation.is_all_down() is False

    async def test_true_when_all_down(
        self, degradation: DegradationManager, health_monitor: HealthMonitor
    ):
        """is_all_down returns True when every agent has open circuit."""
        for agent_id in DEFAULT_AGENT_IDS:
            for _ in range(3):
                health_monitor.record_agent_failure(agent_id)
        assert degradation.is_all_down() is True


class TestShouldNotifyHuman:
    """Tests for DegradationManager.should_notify_human()."""

    async def test_false_when_all_healthy(self, degradation: DegradationManager):
        """No notification when all agents are healthy."""
        assert degradation.should_notify_human() is False

    async def test_false_when_minority_down(
        self, degradation: DegradationManager, health_monitor: HealthMonitor
    ):
        """No notification when less than half of agents are down."""
        for _ in range(3):
            health_monitor.record_agent_failure("grok")
        assert degradation.should_notify_human() is False

    async def test_true_when_majority_down(
        self, degradation: DegradationManager, health_monitor: HealthMonitor
    ):
        """Notification when more than half of agents are down."""
        for agent_id in ["codex", "gemini", "grok"]:
            for _ in range(3):
                health_monitor.record_agent_failure(agent_id)
        assert degradation.should_notify_human() is True

    async def test_true_when_all_down(
        self, degradation: DegradationManager, health_monitor: HealthMonitor
    ):
        """Notification when all agents are down."""
        for agent_id in DEFAULT_AGENT_IDS:
            for _ in range(3):
                health_monitor.record_agent_failure(agent_id)
        assert degradation.should_notify_human() is True

    async def test_false_when_exactly_half_down(
        self, health_monitor: HealthMonitor
    ):
        """Notification NOT triggered when minority are down.

        The condition is ``down_count > total / 2``.
        """
        dm = DegradationManager(health_monitor=health_monitor)
        for agent_id in ["codex", "gemini"]:
            for _ in range(3):
                health_monitor.record_agent_failure(agent_id)
        # 2 down out of 5 -> 2 > 5/2 -> 2 > 2.5 -> False
        assert dm.should_notify_human() is False

    async def test_true_when_zero_agents_configured(
        self, health_monitor: HealthMonitor
    ):
        """Notification triggered when all_agent_ids is empty (total == 0 guard)."""
        dm = DegradationManager(
            health_monitor=health_monitor, all_agent_ids=[],
        )
        assert dm.should_notify_human() is True


class TestRateLimitTracking:
    """Tests for record_rate_limit, get_rate_limit_backoff, _is_rate_limited."""

    async def test_record_rate_limit_sets_backoff(
        self, degradation: DegradationManager
    ):
        """record_rate_limit makes the agent appear in _rate_limits."""
        degradation.record_rate_limit("claude", 60)
        assert degradation._is_rate_limited("claude") is True

    async def test_get_rate_limit_backoff_returns_zero_when_not_limited(
        self, degradation: DegradationManager
    ):
        """Agent with no rate limit returns 0 backoff seconds."""
        assert degradation.get_rate_limit_backoff("codex") == 0

    async def test_get_rate_limit_backoff_returns_remaining_seconds(
        self, degradation: DegradationManager
    ):
        """Agent with active rate limit returns positive remaining seconds."""
        degradation.record_rate_limit("claude", 120)
        remaining = degradation.get_rate_limit_backoff("claude")
        # Should be close to 120 but we allow tolerance for test execution time
        assert 100 <= remaining <= 120

    async def test_get_rate_limit_backoff_cleans_expired_entries(
        self, degradation: DegradationManager
    ):
        """Expired rate limits are cleaned up and return 0."""
        # Set a backoff that has already expired (0 seconds)
        degradation.record_rate_limit("codex", 0)
        remaining = degradation.get_rate_limit_backoff("codex")
        assert remaining == 0
        # Entry should be cleaned up
        assert "codex" not in degradation._rate_limits

    async def test_rate_limited_agent_excluded_from_healthy(
        self, degradation: DegradationManager
    ):
        """A rate-limited agent is not in get_healthy_agents()."""
        degradation.record_rate_limit("grok", 600)
        healthy = degradation.get_healthy_agents()
        assert "grok" not in healthy

    async def test_record_rate_limit_negative_seconds_clamped_to_zero(
        self, degradation: DegradationManager
    ):
        """Negative backoff_seconds is clamped to 0 (already expired)."""
        degradation.record_rate_limit("claude", -10)
        # Should be treated as 0 seconds backoff, meaning already expired
        assert degradation.get_rate_limit_backoff("claude") == 0

    async def test_is_rate_limited_cleans_expired_entry(
        self, degradation: DegradationManager
    ):
        """_is_rate_limited cleans up expired backoff entries and returns False."""
        # Manually set an already-expired backoff time
        expired_time = datetime.now(UTC) - timedelta(seconds=10)
        degradation._rate_limits["codex"] = expired_time
        # Should return False and clean up the entry
        assert degradation._is_rate_limited("codex") is False
        assert "codex" not in degradation._rate_limits


class TestGetDegradationStatus:
    """Tests for DegradationManager.get_degradation_status()."""

    async def test_status_structure(self, degradation: DegradationManager):
        """get_degradation_status returns dict with all expected keys."""
        status = degradation.get_degradation_status()
        expected_keys = {
            "healthy_agents",
            "unhealthy_agents",
            "all_down",
            "should_notify_human",
            "agent_details",
            "total_agents",
            "healthy_count",
        }
        assert set(status.keys()) == expected_keys

    async def test_status_all_healthy(self, degradation: DegradationManager):
        """When all agents healthy, status reflects that."""
        status = degradation.get_degradation_status()
        assert status["healthy_count"] == len(DEFAULT_AGENT_IDS)
        assert status["total_agents"] == len(DEFAULT_AGENT_IDS)
        assert status["all_down"] is False
        assert status["should_notify_human"] is False
        assert len(status["unhealthy_agents"]) == 0

    async def test_status_with_circuit_open(
        self, degradation: DegradationManager, health_monitor: HealthMonitor
    ):
        """Status correctly categorizes circuit-open agents as unhealthy."""
        for _ in range(3):
            health_monitor.record_agent_failure("codex")
        status = degradation.get_degradation_status()
        assert "codex" in status["unhealthy_agents"]
        assert "codex" not in status["healthy_agents"]
        assert status["healthy_count"] == len(DEFAULT_AGENT_IDS) - 1

    async def test_status_agent_details_rate_limit_info(
        self, degradation: DegradationManager
    ):
        """Agent details include rate_limited and rate_limit_remaining_seconds."""
        degradation.record_rate_limit("gemini", 120)
        status = degradation.get_degradation_status()
        gemini_detail = status["agent_details"]["gemini"]
        assert gemini_detail["rate_limited"] is True
        assert gemini_detail["rate_limit_remaining_seconds"] is not None
        assert gemini_detail["rate_limit_remaining_seconds"] > 0
        assert gemini_detail["healthy"] is False

    async def test_status_agent_details_healthy_flag(
        self, degradation: DegradationManager
    ):
        """Each agent detail has a healthy flag matching overall healthy list."""
        status = degradation.get_degradation_status()
        for agent_id in DEFAULT_AGENT_IDS:
            detail = status["agent_details"][agent_id]
            assert detail["healthy"] is True
            assert detail["rate_limited"] is False
            assert detail["rate_limit_remaining_seconds"] is None
