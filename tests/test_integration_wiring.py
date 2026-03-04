"""Tests for integration wiring code added to the CLAW project.

Covers:
  1. AgentInterface._resolve_workspace  -- safe cwd resolution, security fix
  2. Factory _create_agent for codex/gemini/grok  -- all 4 agents + unknown
  3. MCP server auth_token  -- dispatch_tool auth checks (pass, fail, missing)
  4. DB engine connection cleanup  -- _conn set to None on connect failure
  5. Token tracker async JSONL  -- _persist_to_jsonl async, _write_line static
  6. Cycle decide() with dispatcher  -- Dispatcher routing, fallback, degradation
  7. Cycle act() with budget  -- budget check before dispatch, budget_exceeded
  8. Cycle verify() with verifier  -- full verifier, fallback inline checks

NO mocks, NO placeholders, NO simulation, NO cached responses.
All tests use real objects with in-memory SQLite.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from claw.agents.claude import ClaudeCodeAgent
from claw.agents.codex import CodexAgent
from claw.agents.gemini import GeminiAgent
from claw.agents.grok import GrokAgent
from claw.agents.interface import AgentInterface
from claw.core.config import AgentConfig, ClawConfig, load_config
from claw.core.factory import ClawContext, _create_agent
from claw.core.models import (
    AgentHealth,
    AgentMode,
    Project,
    Task,
    TaskContext,
    TaskOutcome,
    TaskStatus,
    VerificationResult,
)
from claw.cycle import MicroClaw
from claw.db.engine import DatabaseEngine
from claw.llm.token_tracker import TokenTracker
from claw.mcp_server import ClawMCPServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _make_task(
    project_id: str = "proj-001",
    title: str = "Test task",
    description: str = "A test task description",
    task_type: str = "analysis",
    recommended_agent: Optional[str] = None,
) -> Task:
    """Create a real Task with sensible defaults."""
    return Task(
        project_id=project_id,
        title=title,
        description=description,
        task_type=task_type,
        recommended_agent=recommended_agent,
    )


def _make_agent_cfg(
    mode: str = "cli",
    api_key_env: str = "",
    model: Optional[str] = None,
    timeout: int = 300,
    max_budget_usd: float = 1.0,
) -> AgentConfig:
    """Create a real AgentConfig for factory tests."""
    return AgentConfig(
        enabled=True,
        mode=mode,
        api_key_env=api_key_env,
        model=model,
        timeout=timeout,
        max_budget_usd=max_budget_usd,
    )


class _MinimalAgent(AgentInterface):
    """Concrete AgentInterface subclass for testing _resolve_workspace.

    NOT a mock -- this is a minimal real implementation of the ABC,
    used to test the base class method _resolve_workspace.
    """

    def __init__(self, agent_id: str = "test", workspace_dir: Optional[str] = None):
        super().__init__(agent_id=agent_id, name="Test Agent")
        if workspace_dir is not None:
            self.workspace_dir = workspace_dir

    async def execute(self, task: TaskContext, context: Any = None) -> TaskOutcome:
        return TaskOutcome(
            agent_id=self.agent_id,
            approach_summary="minimal execution",
            tests_passed=True,
            files_changed=[],
        )

    async def health_check(self) -> AgentHealth:
        return AgentHealth(agent_id=self.agent_id, available=True, mode=AgentMode.CLI)

    @property
    def supported_modes(self) -> list[AgentMode]:
        return [AgentMode.CLI]

    @property
    def instruction_file(self) -> str:
        return "TEST.md"


class _SuccessAgent(AgentInterface):
    """Agent that always succeeds -- used in cycle tests.

    Produces a real TaskOutcome with controlled content.
    NOT a mock. Implements the ABC contract with real return values.
    """

    def __init__(self, agent_id: str = "test-success"):
        super().__init__(agent_id=agent_id, name="Success Agent")

    async def execute(self, task: TaskContext, context: Any = None) -> TaskOutcome:
        return TaskOutcome(
            agent_id=self.agent_id,
            approach_summary="Successfully completed the task with proper error handling.",
            tests_passed=True,
            files_changed=["src/fixed.py"],
            diff="--- a/src/fixed.py\n+++ b/src/fixed.py\n+def fixed(): pass\n",
        )

    async def health_check(self) -> AgentHealth:
        return AgentHealth(agent_id=self.agent_id, available=True, mode=AgentMode.CLI)

    @property
    def supported_modes(self) -> list[AgentMode]:
        return [AgentMode.CLI]

    @property
    def instruction_file(self) -> str:
        return "TEST.md"


class _FailAgent(AgentInterface):
    """Agent that always returns a failure outcome.

    NOT a mock. Implements the ABC contract with real failure values.
    """

    def __init__(self, agent_id: str = "test-fail"):
        super().__init__(agent_id=agent_id, name="Fail Agent")

    async def execute(self, task: TaskContext, context: Any = None) -> TaskOutcome:
        return TaskOutcome(
            agent_id=self.agent_id,
            failure_reason="execution_error",
            failure_detail="Task could not be completed",
            tests_passed=False,
        )

    async def health_check(self) -> AgentHealth:
        return AgentHealth(agent_id=self.agent_id, available=True, mode=AgentMode.CLI)

    @property
    def supported_modes(self) -> list[AgentMode]:
        return [AgentMode.CLI]

    @property
    def instruction_file(self) -> str:
        return "TEST.md"


# ===========================================================================
# 1. AgentInterface._resolve_workspace
# ===========================================================================


class TestResolveWorkspace:
    """Tests for AgentInterface._resolve_workspace -- safe cwd resolution."""

    def test_returns_workspace_when_set_and_valid_dir(self, tmp_path):
        """_resolve_workspace returns workspace_dir when it is a valid directory."""
        agent = _MinimalAgent(workspace_dir=str(tmp_path))
        task = _make_task()
        ctx = TaskContext(task=task)
        result = agent._resolve_workspace(ctx)
        assert result == str(tmp_path)

    def test_returns_none_when_workspace_not_set(self):
        """_resolve_workspace returns None when workspace_dir attribute is absent."""
        agent = _MinimalAgent()
        # Ensure workspace_dir is not set
        assert not hasattr(agent, "workspace_dir")
        task = _make_task()
        ctx = TaskContext(task=task)
        result = agent._resolve_workspace(ctx)
        assert result is None

    def test_returns_none_when_workspace_is_invalid_path(self):
        """_resolve_workspace returns None when workspace_dir is set but not a valid directory."""
        agent = _MinimalAgent(workspace_dir="/nonexistent/fake/dir/that/does/not/exist")
        task = _make_task()
        ctx = TaskContext(task=task)
        result = agent._resolve_workspace(ctx)
        assert result is None

    def test_never_uses_task_description_as_cwd(self, tmp_path):
        """Security fix: _resolve_workspace never falls back to task.description.

        Even if task.description looks like a valid path, it must not be used.
        """
        # Create a subdir with the same name as the description
        path_like_desc = str(tmp_path / "sneaky")
        Path(path_like_desc).mkdir()

        agent = _MinimalAgent()  # No workspace_dir set
        task = _make_task(description=path_like_desc)
        ctx = TaskContext(task=task)
        result = agent._resolve_workspace(ctx)
        assert result is None  # Must NOT return the description path

    def test_returns_none_when_workspace_is_file_not_dir(self, tmp_path):
        """_resolve_workspace returns None when workspace_dir points to a file, not directory."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("not a directory", encoding="utf-8")
        agent = _MinimalAgent(workspace_dir=str(file_path))
        task = _make_task()
        ctx = TaskContext(task=task)
        result = agent._resolve_workspace(ctx)
        assert result is None

    def test_returns_none_when_workspace_is_empty_string(self):
        """_resolve_workspace returns None when workspace_dir is an empty string."""
        agent = _MinimalAgent(workspace_dir="")
        task = _make_task()
        ctx = TaskContext(task=task)
        result = agent._resolve_workspace(ctx)
        assert result is None


# ===========================================================================
# 2. Factory _create_agent for codex/gemini/grok
# ===========================================================================


class TestCreateAgent:
    """Tests for _create_agent factory function -- all 4 agents + unknown."""

    def test_create_claude_agent(self):
        """_create_agent('claude', cfg) returns a ClaudeCodeAgent."""
        cfg = _make_agent_cfg()
        agent = _create_agent("claude", cfg, workspace_dir="/tmp/ws")
        assert isinstance(agent, ClaudeCodeAgent)
        assert agent.agent_id == "claude"
        assert agent.workspace_dir == "/tmp/ws"

    def test_create_codex_agent(self):
        """_create_agent('codex', cfg) returns a CodexAgent."""
        cfg = _make_agent_cfg()
        agent = _create_agent("codex", cfg, workspace_dir="/tmp/ws")
        assert isinstance(agent, CodexAgent)
        assert agent.agent_id == "codex"
        assert agent.workspace_dir == "/tmp/ws"

    def test_create_gemini_agent(self):
        """_create_agent('gemini', cfg) returns a GeminiAgent."""
        cfg = _make_agent_cfg()
        agent = _create_agent("gemini", cfg, workspace_dir="/tmp/ws")
        assert isinstance(agent, GeminiAgent)
        assert agent.agent_id == "gemini"
        assert agent.workspace_dir == "/tmp/ws"

    def test_create_grok_agent(self):
        """_create_agent('grok', cfg) returns a GrokAgent."""
        cfg = _make_agent_cfg()
        agent = _create_agent("grok", cfg, workspace_dir="/tmp/ws")
        assert isinstance(agent, GrokAgent)
        assert agent.agent_id == "grok"
        assert agent.workspace_dir == "/tmp/ws"

    def test_create_unknown_returns_none(self):
        """_create_agent('unknown', cfg) returns None for unrecognized agent name."""
        cfg = _make_agent_cfg()
        agent = _create_agent("unknown_agent_xyz", cfg)
        assert agent is None

    def test_create_codex_respects_timeout(self):
        """_create_agent passes timeout from config to CodexAgent."""
        cfg = _make_agent_cfg(timeout=120)
        agent = _create_agent("codex", cfg)
        assert isinstance(agent, CodexAgent)
        assert agent.timeout == 120

    def test_create_gemini_respects_model(self):
        """_create_agent passes model from config to GeminiAgent."""
        cfg = _make_agent_cfg(model="gemini-2.5-pro")
        agent = _create_agent("gemini", cfg)
        assert isinstance(agent, GeminiAgent)
        assert agent.model == "gemini-2.5-pro"

    def test_create_grok_respects_max_budget(self):
        """_create_agent passes max_budget_usd from config to GrokAgent."""
        cfg = _make_agent_cfg(max_budget_usd=2.5)
        agent = _create_agent("grok", cfg)
        assert isinstance(agent, GrokAgent)
        assert agent.max_budget_usd == 2.5

    def test_create_without_workspace(self):
        """_create_agent without workspace_dir sets workspace_dir=None on agents that support it."""
        cfg = _make_agent_cfg()
        agent = _create_agent("codex", cfg)
        assert isinstance(agent, CodexAgent)
        assert agent.workspace_dir is None


# ===========================================================================
# 3. MCP server auth_token
# ===========================================================================


class TestMCPServerAuth:
    """Tests for ClawMCPServer.dispatch_tool auth_token checking."""

    async def test_dispatch_with_correct_token_succeeds(self, repository):
        """dispatch_tool with correct token processes the call."""
        server = ClawMCPServer(
            repository=repository,
            auth_token="secret-token-123",
        )
        # claw_verify_claim is a simple tool that works without semantic_memory
        result = await server.dispatch_tool(
            "claw_verify_claim",
            {"claim": "no placeholders remain"},
            auth_token="secret-token-123",
        )
        assert result["status"] == "ok"
        assert "claim" in result

    async def test_dispatch_with_wrong_token_returns_auth_error(self, repository):
        """dispatch_tool with wrong token returns authentication error."""
        server = ClawMCPServer(
            repository=repository,
            auth_token="correct-token",
        )
        result = await server.dispatch_tool(
            "claw_verify_claim",
            {"claim": "test"},
            auth_token="wrong-token",
        )
        assert result["status"] == "error"
        assert "authentication" in result["error"].lower()
        assert result["error_type"] == "AuthError"

    async def test_dispatch_no_token_when_server_has_token_returns_error(self, repository):
        """dispatch_tool with no token when server requires one returns auth error."""
        server = ClawMCPServer(
            repository=repository,
            auth_token="required-token",
        )
        result = await server.dispatch_tool(
            "claw_verify_claim",
            {"claim": "test"},
            auth_token=None,
        )
        assert result["status"] == "error"
        assert "authentication" in result["error"].lower()

    async def test_dispatch_no_token_when_server_has_no_token_succeeds(self, repository):
        """dispatch_tool with no token when server has no token configured succeeds."""
        server = ClawMCPServer(
            repository=repository,
            auth_token=None,
        )
        result = await server.dispatch_tool(
            "claw_verify_claim",
            {"claim": "no placeholders remain"},
            auth_token=None,
        )
        assert result["status"] == "ok"

    async def test_dispatch_with_token_when_server_has_no_token_succeeds(self, repository):
        """dispatch_tool with a token when server has no auth requirement still succeeds."""
        server = ClawMCPServer(
            repository=repository,
            auth_token=None,
        )
        result = await server.dispatch_tool(
            "claw_verify_claim",
            {"claim": "all tests pass"},
            auth_token="some-token",
        )
        # No auth requirement, so the token is ignored and call proceeds
        assert result["status"] == "ok"

    async def test_dispatch_unknown_tool_raises_value_error(self, repository):
        """dispatch_tool with unknown tool name raises ValueError."""
        server = ClawMCPServer(repository=repository)
        with pytest.raises(ValueError, match="Unknown tool"):
            await server.dispatch_tool("nonexistent_tool", {})


# ===========================================================================
# 4. DB engine connection cleanup
# ===========================================================================


class TestDBEngineConnectionCleanup:
    """Tests for DatabaseEngine.connect() cleanup on failure."""

    async def test_conn_is_none_after_failed_connect(self):
        """If connect() fails partway, _conn is cleaned up to None.

        We trigger the failure by pointing at an invalid path that will
        cause the sqlite-vec extension load to fail or the db path to
        be unreachable.
        """
        from claw.core.config import DatabaseConfig
        from claw.core.exceptions import ConnectionError

        # Use a path under a non-existent directory to guarantee failure
        config = DatabaseConfig(db_path="/nonexistent/impossible/path/db.sqlite")
        engine = DatabaseEngine(config)
        with pytest.raises(ConnectionError):
            await engine.connect()
        # After failure, _conn must be cleaned up to None
        assert engine._conn is None

    async def test_conn_property_raises_when_not_connected(self):
        """The conn property raises ConnectionError when _conn is None."""
        from claw.core.config import DatabaseConfig
        from claw.core.exceptions import ConnectionError

        config = DatabaseConfig(db_path=":memory:")
        engine = DatabaseEngine(config)
        # Never called connect()
        with pytest.raises(ConnectionError, match="not connected"):
            _ = engine.conn

    async def test_double_close_is_safe(self, db_engine):
        """Calling close() twice does not raise."""
        await db_engine.close()
        # Second close should be safe (idempotent)
        await db_engine.close()
        assert db_engine._conn is None


# ===========================================================================
# 5. Token tracker async JSONL
# ===========================================================================


class TestTokenTrackerAsyncJSONL:
    """Tests for TokenTracker._persist_to_jsonl (now async) and _write_line."""

    async def test_persist_to_jsonl_writes_real_file(self, tmp_path, repository):
        """_persist_to_jsonl writes a real JSONL line to disk asynchronously."""
        jsonl_path = str(tmp_path / "token_costs.jsonl")
        tracker = TokenTracker(
            repository=repository,
            jsonl_path=jsonl_path,
            cost_per_1k_input=0.003,
            cost_per_1k_output=0.015,
        )

        record = await tracker.record(
            model="test-model",
            input_tokens=100,
            output_tokens=50,
        )

        # Verify the JSONL file was created and contains valid JSON
        path = Path(jsonl_path)
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["model_used"] == "test-model"
        assert data["input_tokens"] == 100
        assert data["output_tokens"] == 50
        assert data["total_tokens"] == 150

    async def test_persist_multiple_records(self, tmp_path, repository):
        """Multiple records append separate JSONL lines."""
        jsonl_path = str(tmp_path / "costs.jsonl")
        tracker = TokenTracker(
            repository=repository,
            jsonl_path=jsonl_path,
        )

        await tracker.record(model="model-a", input_tokens=10, output_tokens=5)
        await tracker.record(model="model-b", input_tokens=20, output_tokens=10)
        await tracker.record(model="model-c", input_tokens=30, output_tokens=15)

        lines = Path(jsonl_path).read_text().strip().split("\n")
        assert len(lines) == 3
        models = [json.loads(line)["model_used"] for line in lines]
        assert models == ["model-a", "model-b", "model-c"]

    async def test_persist_no_jsonl_path_skips_file(self, repository):
        """When jsonl_path is None, no file is written."""
        tracker = TokenTracker(
            repository=repository,
            jsonl_path=None,
        )
        # Should not raise -- just skips JSONL writing
        record = await tracker.record(model="test", input_tokens=10, output_tokens=5)
        assert record.total_tokens == 15

    def test_write_line_static_method(self, tmp_path):
        """_write_line static method appends a line to a file."""
        path = tmp_path / "output.jsonl"
        line1 = '{"key": "value1"}\n'
        line2 = '{"key": "value2"}\n'

        TokenTracker._write_line(path, line1)
        TokenTracker._write_line(path, line2)

        content = path.read_text()
        assert content == line1 + line2

    async def test_persist_creates_parent_dirs(self, tmp_path, repository):
        """_persist_to_jsonl creates parent directories if they do not exist."""
        jsonl_path = str(tmp_path / "nested" / "deep" / "token_costs.jsonl")
        tracker = TokenTracker(
            repository=repository,
            jsonl_path=jsonl_path,
        )
        await tracker.record(model="test", input_tokens=5, output_tokens=5)
        assert Path(jsonl_path).exists()

    async def test_persist_jsonl_cost_field(self, tmp_path, repository):
        """JSONL records include cost_usd computed from token counts."""
        jsonl_path = str(tmp_path / "costs.jsonl")
        tracker = TokenTracker(
            repository=repository,
            jsonl_path=jsonl_path,
            cost_per_1k_input=0.003,
            cost_per_1k_output=0.015,
        )
        await tracker.record(model="test", input_tokens=1000, output_tokens=1000)
        data = json.loads(Path(jsonl_path).read_text().strip())
        expected_cost = 0.003 + 0.015  # 1k in * 0.003 + 1k out * 0.015
        assert data["cost_usd"] == pytest.approx(expected_cost)


# ===========================================================================
# 6. Cycle decide() with dispatcher
# ===========================================================================


class TestCycleDecideWithDispatcher:
    """Tests for MicroClaw.decide() using Dispatcher and DegradationManager."""

    async def _setup_cycle(self, claw_context, project_id: str, task: Task):
        """Helper: create project, task, and return a MicroClaw with grabbed+evaluated task."""
        ctx = claw_context
        project = Project(
            id=project_id,
            name="decide-test-project",
            repo_path="/tmp/decide-test",
        )
        await ctx.repository.create_project(project)
        await ctx.repository.create_task(task)

        micro = MicroClaw(ctx, project_id)
        grabbed = await micro.grab()
        assert grabbed is not None
        task_ctx = await micro.evaluate(grabbed)
        return micro, task_ctx

    async def test_decide_uses_dispatcher_route_task(self, claw_context, sample_project, sample_task):
        """decide() uses ctx.dispatcher.route_task() when dispatcher is available."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        # Set up a real Dispatcher with a test agent
        test_agent = _SuccessAgent(agent_id="claude")
        ctx.agents = {"claude": test_agent}

        from claw.dispatcher import Dispatcher
        ctx.dispatcher = Dispatcher(
            agents=ctx.agents,
            exploration_rate=0.0,
            repository=ctx.repository,
        )

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)

        agent_id, decided_ctx = await micro.decide(task_ctx)
        assert agent_id == "claude"
        assert decided_ctx is task_ctx

    async def test_decide_falls_back_when_dispatcher_is_none(self, claw_context, sample_project):
        """decide() falls back to recommended_agent or 'claude' when dispatcher is None."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)

        task = Task(
            project_id=sample_project.id,
            title="Fallback test",
            description="Test dispatcher fallback",
            task_type="analysis",
            recommended_agent="grok",
        )
        await ctx.repository.create_task(task)

        # Add a real agent so the agent_id check passes
        test_agent = _SuccessAgent(agent_id="grok")
        ctx.agents = {"grok": test_agent}
        ctx.dispatcher = None

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        agent_id, _ = await micro.decide(task_ctx)
        assert agent_id == "grok"

    async def test_decide_checks_degradation_all_down(self, claw_context, sample_project, sample_task):
        """decide() returns ('none', ctx) when degradation_manager.is_all_down() is True."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        # Create a real DegradationManager with all agents circuit-broken
        from claw.orchestrator.health_monitor import HealthMonitor
        from claw.degradation import DegradationManager
        from claw.core.config import OrchestratorConfig

        hm = HealthMonitor(repository=ctx.repository, config=OrchestratorConfig())
        agent_ids = ["claude", "codex", "gemini", "grok"]
        for aid in agent_ids:
            for _ in range(3):
                hm.record_agent_failure(aid)

        ctx.degradation_manager = DegradationManager(
            health_monitor=hm,
            all_agent_ids=agent_ids,
        )
        ctx.agents = {}

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        agent_id, _ = await micro.decide(task_ctx)
        assert agent_id == "none"

    async def test_decide_gets_fallback_when_preferred_degraded(self, claw_context, sample_project):
        """decide() gets fallback agent when the preferred agent is degraded."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)

        task = Task(
            project_id=sample_project.id,
            title="Fallback routing",
            description="Test degradation fallback",
            task_type="analysis",
        )
        await ctx.repository.create_task(task)

        # Set up real agents
        claude_agent = _SuccessAgent(agent_id="claude")
        codex_agent = _SuccessAgent(agent_id="codex")
        ctx.agents = {"claude": claude_agent, "codex": codex_agent}

        # Dispatcher routes to claude (static routing for analysis)
        from claw.dispatcher import Dispatcher
        ctx.dispatcher = Dispatcher(
            agents=ctx.agents,
            exploration_rate=0.0,
            repository=ctx.repository,
        )

        # Degrade claude via real DegradationManager
        from claw.orchestrator.health_monitor import HealthMonitor
        from claw.degradation import DegradationManager
        from claw.core.config import OrchestratorConfig

        hm = HealthMonitor(repository=ctx.repository, config=OrchestratorConfig())
        for _ in range(3):
            hm.record_agent_failure("claude")

        ctx.degradation_manager = DegradationManager(
            health_monitor=hm,
            all_agent_ids=["claude", "codex"],
        )

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        agent_id, _ = await micro.decide(task_ctx)
        # Claude is degraded, so should fallback to codex
        assert agent_id == "codex"


# ===========================================================================
# 7. Cycle act() with budget
# ===========================================================================


class TestCycleActWithBudget:
    """Tests for MicroClaw.act() with budget enforcement."""

    async def test_act_checks_budget_before_dispatch(self, claw_context, sample_project, sample_task):
        """act() checks budget before dispatching to agent."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        # Set up agent
        success_agent = _SuccessAgent(agent_id="claude")
        ctx.agents = {"claude": success_agent}

        # Set up real BudgetEnforcer that has NOT been exceeded
        from claw.budget import BudgetEnforcer
        ctx.budget_enforcer = BudgetEnforcer(
            repository=ctx.repository,
            config=ctx.config,
        )

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)

        # Decision returns valid agent
        decision = ("claude", task_ctx)

        agent_id, returned_ctx, outcome = await micro.act(decision)
        assert agent_id == "claude"
        assert outcome.agent_id == "claude"
        # The agent executed (no budget_exceeded)
        assert outcome.failure_reason != "budget_exceeded"

    async def test_act_returns_budget_exceeded_when_cap_hit(self, claw_context, sample_project, sample_task):
        """act() returns budget_exceeded when budget enforcer finds exceeding."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        # Set up agent
        success_agent = _SuccessAgent(agent_id="claude")
        ctx.agents = {"claude": success_agent}

        # Set up BudgetEnforcer with extremely low per-task limit
        from claw.budget import BudgetEnforcer
        config = ClawConfig()
        object.__setattr__(config, "budget", SimpleNamespace(
            per_task_usd=0.001,  # Extremely low limit
            per_project_usd=50.0,
            per_day_usd=100.0,
            per_agent_usd=25.0,
        ))
        ctx.budget_enforcer = BudgetEnforcer(
            repository=ctx.repository,
            config=config,
        )

        # Insert a cost record that exceeds the per-task limit
        await ctx.engine.execute(
            """INSERT INTO token_costs
               (id, task_id, agent_id, agent_role, model_used,
                input_tokens, output_tokens, total_tokens, cost_usd, created_at)
               VALUES (?, ?, 'claude', '', 'test', 100, 50, 150, 1.0, datetime('now'))""",
            [_uid(), sample_task.id],
        )

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        decision = ("claude", task_ctx)

        agent_id, returned_ctx, outcome = await micro.act(decision)
        assert outcome.failure_reason == "budget_exceeded"
        assert "Budget cap hit" in outcome.failure_detail

    async def test_act_with_no_budget_enforcer_proceeds(self, claw_context, sample_project, sample_task):
        """act() proceeds normally when budget_enforcer is None."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        success_agent = _SuccessAgent(agent_id="claude")
        ctx.agents = {"claude": success_agent}
        ctx.budget_enforcer = None

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        decision = ("claude", task_ctx)

        agent_id, returned_ctx, outcome = await micro.act(decision)
        assert agent_id == "claude"
        assert outcome.failure_reason is None or outcome.failure_reason == ""

    async def test_act_returns_no_agent_when_agent_id_is_none(self, claw_context, sample_project, sample_task):
        """act() returns no_agent failure when agent_id is 'none'."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        decision = ("none", task_ctx)

        agent_id, returned_ctx, outcome = await micro.act(decision)
        assert outcome.failure_reason == "no_agent"
        assert "No agent available" in outcome.failure_detail


# ===========================================================================
# 8. Cycle verify() with verifier
# ===========================================================================


class TestCycleVerifyWithVerifier:
    """Tests for MicroClaw.verify() with full Verifier and fallback."""

    async def test_verify_uses_verifier_when_available(self, claw_context, sample_project, sample_task):
        """verify() uses ctx.verifier.verify() when verifier is set and outcome has no failure."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        # Set up real Verifier
        from claw.verifier import Verifier
        ctx.verifier = Verifier(
            embedding_engine=None,
            banned_dependencies=[],
            drift_threshold=0.40,
            llm_client=None,
        )

        micro = MicroClaw(ctx, sample_project.id)

        # Create a clean outcome
        clean_outcome = TaskOutcome(
            agent_id="claude",
            approach_summary="Improved error handling in the auth module.",
            tests_passed=True,
            files_changed=["src/auth.py"],
            diff="--- a/src/auth.py\n+++ b/src/auth.py\n+def validate(): pass\n",
        )
        task = await micro.grab()
        task_ctx = await micro.evaluate(task)

        result_tuple = ("claude", task_ctx, clean_outcome)
        agent_id, returned_ctx, outcome, verification = await micro.verify(result_tuple)

        assert isinstance(verification, VerificationResult)
        assert verification.approved is True
        assert len(verification.violations) == 0

    async def test_verify_detects_placeholder_via_verifier(self, claw_context, sample_project, sample_task):
        """verify() with Verifier detects TODO placeholder and rejects."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        from claw.verifier import Verifier
        ctx.verifier = Verifier(
            embedding_engine=None,
            banned_dependencies=[],
            drift_threshold=0.40,
            llm_client=None,
        )

        micro = MicroClaw(ctx, sample_project.id)

        # Outcome with TODO in the diff
        todo_outcome = TaskOutcome(
            agent_id="claude",
            approach_summary="Added feature.",
            tests_passed=True,
            files_changed=["src/feature.py"],
            diff="+def feature():\n+    # TODO: implement this\n+    pass\n",
        )
        task = await micro.grab()
        task_ctx = await micro.evaluate(task)

        result_tuple = ("claude", task_ctx, todo_outcome)
        _, _, _, verification = await micro.verify(result_tuple)

        assert isinstance(verification, VerificationResult)
        assert verification.approved is False
        placeholder_violations = [v for v in verification.violations if v["check"] == "placeholder_scan"]
        assert len(placeholder_violations) >= 1

    async def test_verify_falls_back_when_verifier_is_none(self, claw_context, sample_project, sample_task):
        """verify() falls back to inline checks when verifier is None."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        ctx.verifier = None

        micro = MicroClaw(ctx, sample_project.id)

        clean_outcome = TaskOutcome(
            agent_id="claude",
            approach_summary="Clean work.",
            tests_passed=True,
            files_changed=["src/clean.py"],
        )
        task = await micro.grab()
        task_ctx = await micro.evaluate(task)

        result_tuple = ("claude", task_ctx, clean_outcome)
        _, _, _, verification = await micro.verify(result_tuple)

        assert isinstance(verification, VerificationResult)
        assert verification.approved is True
        assert len(verification.violations) == 0

    async def test_verify_fallback_detects_placeholder_in_raw_output(self, claw_context, sample_project, sample_task):
        """verify() inline fallback detects placeholder markers in raw_output."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        ctx.verifier = None

        micro = MicroClaw(ctx, sample_project.id)

        # Outcome with TODO in raw_output -- fallback check scans raw_output
        outcome_with_todo = TaskOutcome(
            agent_id="claude",
            approach_summary="Done.",
            tests_passed=True,
            files_changed=["src/fix.py"],
            raw_output="Here is the fix:\n# TODO: handle edge case\ndef fix(): pass",
        )
        task = await micro.grab()
        task_ctx = await micro.evaluate(task)

        result_tuple = ("claude", task_ctx, outcome_with_todo)
        _, _, _, verification = await micro.verify(result_tuple)

        # Fallback scans raw_output for TODO, FIXME, etc.
        assert verification.approved is False
        assert len(verification.violations) >= 1

    async def test_verify_fallback_with_execution_failure(self, claw_context, sample_project, sample_task):
        """verify() inline fallback adds execution violation for failed outcomes."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        ctx.verifier = None

        micro = MicroClaw(ctx, sample_project.id)

        failed_outcome = TaskOutcome(
            agent_id="claude",
            failure_reason="execution_error",
            failure_detail="Agent crashed",
            tests_passed=False,
        )
        task = await micro.grab()
        task_ctx = await micro.evaluate(task)

        result_tuple = ("claude", task_ctx, failed_outcome)
        _, _, _, verification = await micro.verify(result_tuple)

        assert verification.approved is False
        exec_violations = [v for v in verification.violations if v["check"] == "execution"]
        assert len(exec_violations) >= 1

    async def test_verify_uses_verifier_but_skips_on_failure_reason(self, claw_context, sample_project, sample_task):
        """verify() falls back to inline checks when outcome has failure_reason, even with verifier present."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        from claw.verifier import Verifier
        ctx.verifier = Verifier(
            embedding_engine=None,
            banned_dependencies=[],
            drift_threshold=0.40,
            llm_client=None,
        )

        micro = MicroClaw(ctx, sample_project.id)

        # Outcome has a failure_reason, so verify() takes the fallback branch
        failed_outcome = TaskOutcome(
            agent_id="claude",
            failure_reason="timeout",
            failure_detail="Agent timed out",
            tests_passed=False,
        )
        task = await micro.grab()
        task_ctx = await micro.evaluate(task)

        result_tuple = ("claude", task_ctx, failed_outcome)
        _, _, _, verification = await micro.verify(result_tuple)

        # Should go through fallback path (not Verifier.verify)
        assert verification.approved is False
        assert len(verification.violations) >= 1
