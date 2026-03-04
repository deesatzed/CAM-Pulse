"""Tests for claw.dispatcher — Dispatcher routing and TaskRouter state machine.

Covers:
  Dispatcher: static routing, fallback, exploration, recommended_agent, error cases.
  TaskRouter: valid/invalid transitions, terminal states, convenience methods.

NO mocks. All objects are real instances of the production models.
"""

from __future__ import annotations

import random

import pytest

from claw.core.exceptions import AgentError, RoutingError
from claw.core.models import Task, TaskStatus
from claw.dispatcher import (
    DEFAULT_AGENT,
    STATIC_ROUTING,
    VALID_TRANSITIONS,
    Dispatcher,
    TaskRouter,
)


# ---------------------------------------------------------------------------
# Helpers — real lightweight objects, no mocks
# ---------------------------------------------------------------------------

def _make_task(
    task_type: str = "analysis",
    recommended_agent: str | None = None,
    status: TaskStatus = TaskStatus.PENDING,
    title: str = "test task",
) -> Task:
    """Create a real Task with sensible defaults."""
    return Task(
        project_id="proj-001",
        title=title,
        description="A test task",
        status=status,
        task_type=task_type,
        recommended_agent=recommended_agent,
    )


# Simple agents dict — Dispatcher only checks key membership and random.choice
# on keys. Any truthy value works.
AGENTS_FULL = {
    "claude": "agent_claude",
    "codex": "agent_codex",
    "gemini": "agent_gemini",
    "grok": "agent_grok",
}

AGENTS_CLAUDE_CODEX = {
    "claude": "agent_claude",
    "codex": "agent_codex",
}


# ============================================================================
# Dispatcher Tests
# ============================================================================


class TestDispatcherStaticRouting:
    """Static routing table lookups — no exploration, no DB."""

    async def test_analysis_routes_to_claude(self):
        dispatcher = Dispatcher(AGENTS_FULL, exploration_rate=0.0)
        task = _make_task(task_type="analysis")
        agent = await dispatcher.route_task(task)
        assert agent == "claude"

    async def test_testing_routes_to_codex(self):
        dispatcher = Dispatcher(AGENTS_FULL, exploration_rate=0.0)
        task = _make_task(task_type="testing")
        agent = await dispatcher.route_task(task)
        assert agent == "codex"

    async def test_dependency_analysis_routes_to_gemini(self):
        dispatcher = Dispatcher(AGENTS_FULL, exploration_rate=0.0)
        task = _make_task(task_type="dependency_analysis")
        agent = await dispatcher.route_task(task)
        assert agent == "gemini"

    async def test_quick_fix_routes_to_grok(self):
        dispatcher = Dispatcher(AGENTS_FULL, exploration_rate=0.0)
        task = _make_task(task_type="quick_fix")
        agent = await dispatcher.route_task(task)
        assert agent == "grok"

    async def test_all_static_routes_covered(self):
        """Every entry in STATIC_ROUTING should route correctly."""
        dispatcher = Dispatcher(AGENTS_FULL, exploration_rate=0.0)
        for task_type, expected_agent in STATIC_ROUTING.items():
            task = _make_task(task_type=task_type)
            result = await dispatcher.route_task(task)
            assert result == expected_agent, (
                f"task_type={task_type!r} expected {expected_agent!r}, got {result!r}"
            )


class TestDispatcherFallback:
    """Fallback routing when task_type is unknown or agent unavailable."""

    async def test_unknown_task_type_falls_back_to_claude(self):
        dispatcher = Dispatcher(AGENTS_FULL, exploration_rate=0.0)
        task = _make_task(task_type="totally_unknown_type")
        agent = await dispatcher.route_task(task)
        assert agent == DEFAULT_AGENT  # "claude"

    async def test_fallback_when_static_agent_not_in_pool(self):
        """Static route says 'gemini' for dependency_analysis, but gemini not in pool."""
        agents_no_gemini = {"claude": "c", "codex": "x", "grok": "g"}
        dispatcher = Dispatcher(agents_no_gemini, exploration_rate=0.0)
        task = _make_task(task_type="dependency_analysis")
        agent = await dispatcher.route_task(task)
        # Should fall through to DEFAULT_AGENT since gemini is not available
        assert agent == "claude"

    async def test_fallback_when_default_agent_not_in_pool(self):
        """If claude (DEFAULT_AGENT) is not in the pool, fall back to first alphabetical."""
        agents_no_claude = {"codex": "x", "gemini": "g", "grok": "k"}
        dispatcher = Dispatcher(agents_no_claude, exploration_rate=0.0)
        task = _make_task(task_type="totally_unknown_type")
        agent = await dispatcher.route_task(task)
        assert agent == "codex"  # first alphabetically


class TestDispatcherExploration:
    """Exploration rate — random agent selection."""

    async def test_exploration_picks_non_static_agent_sometimes(self):
        """Over 100 routings with 10% exploration, at least one should differ
        from the static route. Use fixed seed for determinism."""
        random.seed(42)
        dispatcher = Dispatcher(AGENTS_FULL, exploration_rate=0.10)
        task = _make_task(task_type="analysis")  # static -> claude

        results = []
        for _ in range(100):
            agent = await dispatcher.route_task(task)
            results.append(agent)

        # With 10% exploration and 4 agents, we should see at least one non-claude
        non_claude = [a for a in results if a != "claude"]
        assert len(non_claude) > 0, "Exploration never triggered in 100 routings"

        # But majority should still be claude (static routing)
        claude_count = results.count("claude")
        assert claude_count > 50, (
            f"Expected majority claude, got {claude_count}/100"
        )

    async def test_zero_exploration_never_randomizes(self):
        """With exploration_rate=0.0, static routing is always used."""
        random.seed(99)
        dispatcher = Dispatcher(AGENTS_FULL, exploration_rate=0.0)
        task = _make_task(task_type="testing")  # static -> codex

        results = set()
        for _ in range(50):
            agent = await dispatcher.route_task(task)
            results.add(agent)

        assert results == {"codex"}

    async def test_full_exploration_always_randomizes(self):
        """With exploration_rate=1.0, every routing is random."""
        random.seed(7)
        dispatcher = Dispatcher(AGENTS_FULL, exploration_rate=1.0)
        task = _make_task(task_type="testing")

        results = set()
        for _ in range(100):
            agent = await dispatcher.route_task(task)
            results.add(agent)

        # With 100 tries and 4 agents, all should appear
        assert len(results) >= 2, "Expected multiple distinct agents with full exploration"


class TestDispatcherRecommendedAgent:
    """Task's recommended_agent hint is respected when available."""

    async def test_recommended_agent_used_when_available(self):
        dispatcher = Dispatcher(AGENTS_FULL, exploration_rate=0.0)
        task = _make_task(task_type="analysis", recommended_agent="grok")
        agent = await dispatcher.route_task(task)
        assert agent == "grok"

    async def test_recommended_agent_ignored_when_not_in_pool(self):
        dispatcher = Dispatcher(AGENTS_CLAUDE_CODEX, exploration_rate=0.0)
        task = _make_task(task_type="analysis", recommended_agent="gemini")
        agent = await dispatcher.route_task(task)
        # gemini not in pool -> falls through to static routing
        assert agent == "claude"


class TestDispatcherErrorCases:
    """Error handling and edge cases."""

    def test_no_agents_raises_routing_error(self):
        with pytest.raises(RoutingError, match="No agents provided"):
            Dispatcher({})

    def test_empty_agents_raises_routing_error(self):
        with pytest.raises(RoutingError):
            Dispatcher({}, exploration_rate=0.0)

    def test_invalid_exploration_rate_too_high(self):
        with pytest.raises(ValueError, match="exploration_rate"):
            Dispatcher(AGENTS_FULL, exploration_rate=1.5)

    def test_invalid_exploration_rate_negative(self):
        with pytest.raises(ValueError, match="exploration_rate"):
            Dispatcher(AGENTS_FULL, exploration_rate=-0.1)


class TestDispatcherRoutingInfo:
    """get_routing_info diagnostic method."""

    def test_routing_info_for_known_type(self):
        dispatcher = Dispatcher(AGENTS_FULL, exploration_rate=0.10)
        info = dispatcher.get_routing_info("testing")
        assert info["task_type"] == "testing"
        assert info["static_route"] == "codex"
        assert info["static_available"] is True
        assert info["fallback"] == DEFAULT_AGENT
        assert "claude" in info["available_agents"]

    def test_routing_info_for_unknown_type(self):
        dispatcher = Dispatcher(AGENTS_FULL, exploration_rate=0.10)
        info = dispatcher.get_routing_info("unknown_type_xyz")
        assert info["static_route"] is None
        assert info["static_available"] is False


# ============================================================================
# TaskRouter Tests
# ============================================================================


class _FakeRepository:
    """Minimal real-ish repository that records calls without DB access.
    Not a mock — stores real data for later assertions."""

    def __init__(self):
        self.status_updates: list[tuple[str, TaskStatus]] = []
        self.attempt_increments: list[str] = []
        self.escalation_increments: list[str] = []

    async def update_task_status(self, task_id: str, status: TaskStatus) -> None:
        self.status_updates.append((task_id, status))

    async def increment_task_attempt(self, task_id: str) -> None:
        self.attempt_increments.append(task_id)

    async def increment_task_escalation(self, task_id: str) -> None:
        self.escalation_increments.append(task_id)


class TestTaskRouterValidTransitions:
    """Valid state transitions in the task state machine."""

    async def test_pending_to_evaluating(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.PENDING)
        result = await router.transition(task, TaskStatus.EVALUATING)
        assert result.status == TaskStatus.EVALUATING
        assert len(repo.status_updates) == 1

    async def test_evaluating_to_planning(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.EVALUATING)
        result = await router.transition(task, TaskStatus.PLANNING)
        assert result.status == TaskStatus.PLANNING

    async def test_planning_to_dispatched(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.PLANNING)
        result = await router.transition(task, TaskStatus.DISPATCHED)
        assert result.status == TaskStatus.DISPATCHED

    async def test_dispatched_to_coding(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.DISPATCHED)
        result = await router.transition(task, TaskStatus.CODING)
        assert result.status == TaskStatus.CODING

    async def test_coding_to_reviewing(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.CODING)
        result = await router.transition(task, TaskStatus.REVIEWING)
        assert result.status == TaskStatus.REVIEWING

    async def test_reviewing_to_done(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.REVIEWING)
        result = await router.transition(task, TaskStatus.DONE)
        assert result.status == TaskStatus.DONE

    async def test_coding_to_dispatched_reroute(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.CODING)
        result = await router.transition(task, TaskStatus.DISPATCHED)
        assert result.status == TaskStatus.DISPATCHED

    async def test_reviewing_to_coding_rejection(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.REVIEWING)
        result = await router.transition(task, TaskStatus.CODING)
        assert result.status == TaskStatus.CODING

    async def test_coding_to_stuck(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.CODING)
        result = await router.transition(task, TaskStatus.STUCK)
        assert result.status == TaskStatus.STUCK

    async def test_full_happy_path(self):
        """Walk through the full PENDING -> DONE lifecycle."""
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.PENDING)

        task = await router.transition(task, TaskStatus.EVALUATING)
        task = await router.transition(task, TaskStatus.PLANNING)
        task = await router.transition(task, TaskStatus.DISPATCHED)
        task = await router.transition(task, TaskStatus.CODING)
        task = await router.transition(task, TaskStatus.REVIEWING)
        task = await router.transition(task, TaskStatus.DONE)

        assert task.status == TaskStatus.DONE
        assert len(repo.status_updates) == 6


class TestTaskRouterInvalidTransitions:
    """Invalid transitions raise AgentError."""

    async def test_done_to_coding_raises(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.DONE)
        with pytest.raises(AgentError, match="Invalid transition"):
            await router.transition(task, TaskStatus.CODING)

    async def test_stuck_to_done_raises(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.STUCK)
        with pytest.raises(AgentError, match="Invalid transition"):
            await router.transition(task, TaskStatus.DONE)

    async def test_pending_to_done_raises(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.PENDING)
        with pytest.raises(AgentError, match="Invalid transition"):
            await router.transition(task, TaskStatus.DONE)

    async def test_pending_to_coding_raises(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.PENDING)
        with pytest.raises(AgentError, match="Invalid transition"):
            await router.transition(task, TaskStatus.CODING)


class TestTaskRouterTerminalStates:
    """Terminal state detection (STUCK and DONE)."""

    def test_stuck_is_terminal(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.STUCK)
        assert router.is_terminal(task) is True

    def test_done_is_terminal(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.DONE)
        assert router.is_terminal(task) is True

    def test_pending_is_not_terminal(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.PENDING)
        assert router.is_terminal(task) is False

    def test_coding_is_not_terminal(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.CODING)
        assert router.is_terminal(task) is False


class TestTaskRouterCanTransition:
    """can_transition boolean checks."""

    def test_can_transition_valid(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        assert router.can_transition(TaskStatus.PENDING, TaskStatus.EVALUATING) is True

    def test_can_transition_invalid(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        assert router.can_transition(TaskStatus.DONE, TaskStatus.CODING) is False

    def test_can_transition_stuck_has_no_targets(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        for target in TaskStatus:
            assert router.can_transition(TaskStatus.STUCK, target) is False

    def test_get_valid_transitions(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        valid = router.get_valid_transitions(TaskStatus.CODING)
        assert TaskStatus.REVIEWING in valid
        assert TaskStatus.STUCK in valid
        assert TaskStatus.DISPATCHED in valid
        assert TaskStatus.CODING in valid  # retry within coding


class TestTaskRouterConvenienceMethods:
    """mark_stuck, mark_done, increment_attempt, increment_escalation, etc."""

    async def test_mark_stuck(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.CODING)
        result = await router.mark_stuck(task, "agent timed out")
        assert result.status == TaskStatus.STUCK

    async def test_mark_done(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.REVIEWING)
        result = await router.mark_done(task)
        assert result.status == TaskStatus.DONE
        assert result.completed_at is not None

    async def test_increment_attempt(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task()
        assert task.attempt_count == 0
        result = await router.increment_attempt(task)
        assert result.attempt_count == 1
        assert len(repo.attempt_increments) == 1

    async def test_increment_escalation(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task()
        assert task.escalation_count == 0
        result = await router.increment_escalation(task)
        assert result.escalation_count == 1
        assert len(repo.escalation_increments) == 1

    def test_should_escalate(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task()
        task.attempt_count = 2
        task.escalation_count = 0
        assert router.should_escalate(task) is True

    def test_should_not_escalate_already_escalated(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task()
        task.attempt_count = 2
        task.escalation_count = 1
        assert router.should_escalate(task) is False

    def test_should_mark_stuck(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task()
        task.escalation_count = 3
        assert router.should_mark_stuck(task) is True

    def test_get_state_summary(self):
        repo = _FakeRepository()
        router = TaskRouter(repo)
        task = _make_task(status=TaskStatus.CODING)
        summary = router.get_state_summary(task)
        assert "CODING" in summary
        assert task.id in summary
