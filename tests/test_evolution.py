"""Tests for CLAW Phase 3 — Evolution and remaining Memory modules.

Covers:
  1. EpisodicMemory  — session event log (claw.memory.episodic)
  2. MetaMemory      — agent performance tracking + Bayesian scoring (claw.memory.meta)
  3. BayesianRouter  — learned routing with Thompson sampling (claw.evolution.routing_optimizer)
  4. PatternLearner  — cross-project pattern extraction + promotion (claw.evolution.pattern_learner)

NO mocks, NO placeholders, NO cached responses. All tests use real SQLite
in-memory databases via the ``db_engine`` / ``repository`` fixtures from conftest.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from claw.core.models import (
    HypothesisEntry,
    HypothesisOutcome,
    Methodology,
    MethodologyUsageEntry,
    Project,
    Task,
    TaskStatus,
)
from claw.evolution.pattern_learner import PatternLearner
from claw.evolution.routing_optimizer import BayesianRouter
from claw.memory.episodic import EpisodicMemory
from claw.memory.meta import MetaMemory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _make_project(name: str = "test-project") -> Project:
    return Project(
        name=name,
        repo_path=f"/tmp/{name}",
        tech_stack={"language": "python"},
    )


def _make_task(
    project_id: str,
    title: str = "fix bug",
    status: TaskStatus = TaskStatus.PENDING,
    task_type: str = "bug_fix",
) -> Task:
    return Task(
        project_id=project_id,
        title=title,
        description=f"Description for {title}",
        status=status,
        task_type=task_type,
    )


async def _save_methodology_with_counts(
    repository,
    methodology: Methodology,
) -> Methodology:
    """Save a methodology and then update success_count/failure_count in DB.

    The ``Repository.save_methodology`` INSERT does not include
    ``success_count`` or ``failure_count`` columns, so they default to 0
    in SQLite.  This helper patches those values via direct SQL after
    the initial insert, matching the real production flow where counts
    are incremented by ``update_methodology_outcome``.
    """
    await repository.save_methodology(methodology)

    # Patch counts that save_methodology does not persist
    if methodology.success_count != 0 or methodology.failure_count != 0:
        await repository.engine.execute(
            "UPDATE methodologies SET success_count = ?, failure_count = ? WHERE id = ?",
            [methodology.success_count, methodology.failure_count, methodology.id],
        )

    return methodology


# ============================================================================
# 1. EpisodicMemory Tests
# ============================================================================


class TestEpisodicMemoryRecordEvent:
    """Recording events and verifying returned IDs."""

    async def test_record_event_returns_id(self, repository):
        project = _make_project()
        await repository.create_project(project)

        em = EpisodicMemory(repository)
        event_id = await em.record_event(
            project_id=project.id,
            session_id="session-001",
            event_type="task_grabbed",
            event_data={"task": "t1"},
        )

        assert event_id is not None
        assert isinstance(event_id, str)
        assert len(event_id) == 36  # UUID format

    async def test_record_event_with_all_optional_fields(self, repository):
        project = _make_project()
        await repository.create_project(project)

        em = EpisodicMemory(repository)
        event_id = await em.record_event(
            project_id=project.id,
            session_id="session-002",
            event_type="agent_dispatched",
            event_data={"model": "claude"},
            agent_id="claude",
            task_id="task-abc",
            cycle_level="micro",
        )

        assert event_id is not None
        events = await em.get_session_events("session-002")
        assert len(events) == 1
        assert events[0]["agent_id"] == "claude"
        assert events[0]["task_id"] == "task-abc"
        assert events[0]["cycle_level"] == "micro"


class TestEpisodicMemoryGetSessionEvents:
    """Retrieving events by session."""

    async def test_get_session_events(self, repository):
        project = _make_project()
        await repository.create_project(project)

        em = EpisodicMemory(repository)
        session_id = "session-get-test"

        await em.record_event(project.id, session_id, "event_a", {"step": 1})
        await em.record_event(project.id, session_id, "event_b", {"step": 2})
        await em.record_event(project.id, session_id, "event_c", {"step": 3})

        events = await em.get_session_events(session_id)
        assert len(events) == 3
        # Verify all event types are present
        types = {e["event_type"] for e in events}
        assert types == {"event_a", "event_b", "event_c"}

    async def test_get_session_events_respects_limit(self, repository):
        project = _make_project()
        await repository.create_project(project)

        em = EpisodicMemory(repository)
        session_id = "session-limit-test"

        for i in range(10):
            await em.record_event(project.id, session_id, f"event_{i}", {"idx": i})

        events = await em.get_session_events(session_id, limit=3)
        assert len(events) == 3

    async def test_get_session_events_empty_session(self, repository):
        em = EpisodicMemory(repository)
        events = await em.get_session_events("nonexistent-session")
        assert events == []

    async def test_get_session_events_isolation(self, repository):
        """Events from different sessions do not bleed through."""
        project = _make_project()
        await repository.create_project(project)

        em = EpisodicMemory(repository)
        await em.record_event(project.id, "session-A", "ev1", {"s": "A"})
        await em.record_event(project.id, "session-B", "ev2", {"s": "B"})

        events_a = await em.get_session_events("session-A")
        events_b = await em.get_session_events("session-B")
        assert len(events_a) == 1
        assert len(events_b) == 1
        assert events_a[0]["event_type"] == "ev1"
        assert events_b[0]["event_type"] == "ev2"


class TestEpisodicMemoryGetProjectEvents:
    """Retrieving events by project, with optional type filter."""

    async def test_get_project_events(self, repository):
        project_a = _make_project("proj-a")
        project_b = _make_project("proj-b")
        await repository.create_project(project_a)
        await repository.create_project(project_b)

        em = EpisodicMemory(repository)
        await em.record_event(project_a.id, "s1", "task_grabbed", {"x": 1})
        await em.record_event(project_a.id, "s1", "task_completed", {"x": 2})
        await em.record_event(project_b.id, "s2", "task_grabbed", {"x": 3})

        events_a = await em.get_project_events(project_a.id)
        events_b = await em.get_project_events(project_b.id)
        assert len(events_a) == 2
        assert len(events_b) == 1

    async def test_get_project_events_filtered_by_type(self, repository):
        project = _make_project()
        await repository.create_project(project)

        em = EpisodicMemory(repository)
        await em.record_event(project.id, "s1", "task_grabbed", {})
        await em.record_event(project.id, "s1", "task_completed", {})
        await em.record_event(project.id, "s1", "task_grabbed", {})

        grabbed = await em.get_project_events(project.id, event_type="task_grabbed")
        completed = await em.get_project_events(project.id, event_type="task_completed")
        assert len(grabbed) == 2
        assert len(completed) == 1


class TestEpisodicMemoryGetTaskEvents:
    """Retrieving events by task_id."""

    async def test_get_task_events(self, repository):
        project = _make_project()
        await repository.create_project(project)

        em = EpisodicMemory(repository)
        task_id = "task-xyz"
        await em.record_event(
            project.id, "s1", "coding_started", {"t": 1}, task_id=task_id
        )
        await em.record_event(
            project.id, "s1", "coding_completed", {"t": 2}, task_id=task_id
        )
        await em.record_event(
            project.id, "s1", "other_event", {"t": 3}, task_id="other-task"
        )

        events = await em.get_task_events(task_id)
        assert len(events) == 2
        for e in events:
            assert e["task_id"] == task_id


class TestEpisodicMemorySessionSummary:
    """Session summary aggregation."""

    async def test_get_session_summary(self, repository):
        project = _make_project()
        await repository.create_project(project)

        em = EpisodicMemory(repository)
        session_id = "summary-session"

        await em.record_event(
            project.id, session_id, "task_grabbed", {"n": 1},
            agent_id="claude", task_id="task-1",
        )
        await em.record_event(
            project.id, session_id, "agent_dispatched", {"n": 2},
            agent_id="codex", task_id="task-1",
        )
        await em.record_event(
            project.id, session_id, "task_completed", {"n": 3},
            agent_id="claude", task_id="task-2",
        )

        summary = await em.get_session_summary(session_id)

        assert summary["session_id"] == session_id
        assert summary["total_events"] == 3
        assert "task_grabbed" in summary["event_counts"]
        assert "agent_dispatched" in summary["event_counts"]
        assert "task_completed" in summary["event_counts"]
        assert set(summary["agents_used"]) == {"claude", "codex"}
        assert set(summary["tasks_touched"]) == {"task-1", "task-2"}
        assert summary["first_event_at"] is not None
        assert summary["last_event_at"] is not None
        assert summary["duration_seconds"] >= 0.0

    async def test_get_session_summary_empty(self, repository):
        em = EpisodicMemory(repository)
        summary = await em.get_session_summary("nonexistent-session")

        assert summary["session_id"] == "nonexistent-session"
        assert summary["total_events"] == 0
        assert summary["event_counts"] == {}
        assert summary["agents_used"] == []
        assert summary["tasks_touched"] == []
        assert summary["first_event_at"] is None
        assert summary["last_event_at"] is None
        assert summary["duration_seconds"] == 0.0


class TestEpisodicMemoryProjectSummary:
    """Project summary aggregation."""

    async def test_get_project_summary(self, repository):
        project = _make_project()
        await repository.create_project(project)

        em = EpisodicMemory(repository)

        # Events across two sessions
        await em.record_event(
            project.id, "s1", "task_grabbed", {}, agent_id="claude"
        )
        await em.record_event(
            project.id, "s1", "task_completed", {}, agent_id="claude"
        )
        await em.record_event(
            project.id, "s2", "task_grabbed", {}, agent_id="codex"
        )

        summary = await em.get_project_summary(project.id)

        assert summary["project_id"] == project.id
        assert summary["total_events"] == 3
        assert summary["session_count"] == 2
        assert "task_grabbed" in summary["event_counts"]
        assert summary["event_counts"]["task_grabbed"] == 2
        assert set(summary["agents_used"]) == {"claude", "codex"}

    async def test_get_project_summary_empty(self, repository):
        em = EpisodicMemory(repository)
        summary = await em.get_project_summary("nonexistent-project")

        assert summary["project_id"] == "nonexistent-project"
        assert summary["total_events"] == 0
        assert summary["session_count"] == 0
        assert summary["event_counts"] == {}
        assert summary["agents_used"] == []


class TestEpisodicMemoryRetention:
    """Retention policy — deleting old events."""

    async def test_apply_retention_policy(self, repository):
        project = _make_project()
        await repository.create_project(project)

        em = EpisodicMemory(repository)

        # Insert recent event (will survive)
        await em.record_event(project.id, "s-recent", "recent_event", {"fresh": True})

        # Insert old event directly via SQL to set a created_at in the past
        old_date = (datetime.now(UTC) - timedelta(days=120)).isoformat()
        old_id = _uid()
        await repository.engine.execute(
            """INSERT INTO episodes (id, project_id, session_id, event_type, event_data, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [old_id, project.id, "s-old", "old_event", '{"stale": true}', old_date],
        )

        # Verify both exist
        all_events = await em.get_project_events(project.id, limit=100)
        assert len(all_events) == 2

        # Apply retention (90 days default)
        deleted_count = await em.apply_retention_policy(retention_days=90)
        assert deleted_count == 1

        # Verify only recent remains
        remaining = await em.get_project_events(project.id, limit=100)
        assert len(remaining) == 1
        assert remaining[0]["event_type"] == "recent_event"

    async def test_apply_retention_policy_nothing_old(self, repository):
        project = _make_project()
        await repository.create_project(project)

        em = EpisodicMemory(repository)
        await em.record_event(project.id, "s1", "fresh_event", {})

        deleted_count = await em.apply_retention_policy(retention_days=90)
        assert deleted_count == 0


# ============================================================================
# 2. MetaMemory Tests
# ============================================================================


class TestMetaMemoryBayesianScore:
    """Pure computation — no DB needed."""

    def test_bayesian_score_uniform_prior(self, repository):
        mm = MetaMemory(repository)
        # 0 successes, 0 failures with uniform prior (1,1) => 0.5
        score = mm.bayesian_score(0, 0)
        assert score == pytest.approx(0.5)

    def test_bayesian_score_all_success(self, repository):
        mm = MetaMemory(repository)
        # 10 successes, 0 failures => (10+1)/(10+1+0+1) = 11/12
        score = mm.bayesian_score(10, 0)
        assert score == pytest.approx(11.0 / 12.0)
        assert score > 0.9

    def test_bayesian_score_all_failure(self, repository):
        mm = MetaMemory(repository)
        # 0 successes, 10 failures => (0+1)/(0+1+10+1) = 1/12
        score = mm.bayesian_score(0, 10)
        assert score == pytest.approx(1.0 / 12.0)
        assert score < 0.1

    def test_bayesian_score_custom_prior(self, repository):
        mm = MetaMemory(repository)
        # Strong prior toward success: alpha=5, beta=1
        # With 0 observations: (0+5)/(0+5+0+1) = 5/6
        score = mm.bayesian_score(0, 0, prior_alpha=5.0, prior_beta=1.0)
        assert score == pytest.approx(5.0 / 6.0)

    def test_bayesian_score_equal_outcomes(self, repository):
        mm = MetaMemory(repository)
        # 5 successes, 5 failures => (5+1)/(5+1+5+1) = 6/12 = 0.5
        score = mm.bayesian_score(5, 5)
        assert score == pytest.approx(0.5)

    def test_bayesian_score_monotonic_in_successes(self, repository):
        mm = MetaMemory(repository)
        scores = [mm.bayesian_score(s, 5) for s in range(0, 20)]
        for i in range(len(scores) - 1):
            assert scores[i] < scores[i + 1]


class TestMetaMemoryThompsonSample:
    """Thompson sampling draws from Beta distribution."""

    def test_thompson_sample_range(self, repository):
        mm = MetaMemory(repository)
        for _ in range(100):
            sample = mm.thompson_sample(5, 5)
            assert 0.0 <= sample <= 1.0

    def test_thompson_sample_statistical(self, repository):
        """1000 samples with 10 successes, 0 failures => mean > 0.7."""
        mm = MetaMemory(repository)
        random.seed(42)
        samples = [mm.thompson_sample(10, 0) for _ in range(1000)]
        mean = sum(samples) / len(samples)
        assert mean > 0.7, f"Expected mean > 0.7, got {mean:.4f}"

    def test_thompson_sample_low_success_statistical(self, repository):
        """1000 samples with 0 successes, 10 failures => mean < 0.3."""
        mm = MetaMemory(repository)
        random.seed(42)
        samples = [mm.thompson_sample(0, 10) for _ in range(1000)]
        mean = sum(samples) / len(samples)
        assert mean < 0.3, f"Expected mean < 0.3, got {mean:.4f}"


class TestMetaMemoryRecordAndRetrieve:
    """Recording outcomes and retrieving scores via real DB."""

    async def test_record_outcome_and_retrieve(self, repository):
        mm = MetaMemory(repository)
        await mm.record_outcome("claude", "bug_fix", True, quality_score=0.9, cost_usd=0.05)

        scores = await mm.get_agent_scores("claude")
        assert len(scores) == 1
        assert scores[0]["agent_id"] == "claude"
        assert scores[0]["task_type"] == "bug_fix"
        assert scores[0]["successes"] == 1
        assert scores[0]["failures"] == 0
        assert scores[0]["total_attempts"] == 1
        # Enriched with bayesian_score
        assert "bayesian_score" in scores[0]
        assert scores[0]["bayesian_score"] > 0.5

    async def test_record_multiple_outcomes(self, repository):
        mm = MetaMemory(repository)
        # Claude: 3 successes on bug_fix
        for _ in range(3):
            await mm.record_outcome("claude", "bug_fix", True, quality_score=0.8)
        # Codex: 2 successes, 1 failure on bug_fix
        for _ in range(2):
            await mm.record_outcome("codex", "bug_fix", True, quality_score=0.7)
        await mm.record_outcome("codex", "bug_fix", False, quality_score=0.2)

        # Claude on refactor
        await mm.record_outcome("claude", "refactor", True, quality_score=0.95)

        all_scores = await mm.get_agent_scores()
        assert len(all_scores) == 3  # claude/bug_fix, codex/bug_fix, claude/refactor

        claude_scores = await mm.get_agent_scores("claude")
        assert len(claude_scores) == 2  # bug_fix + refactor

    async def test_get_scores_for_task_type(self, repository):
        mm = MetaMemory(repository)
        await mm.record_outcome("claude", "analysis", True)
        await mm.record_outcome("codex", "analysis", False)
        await mm.record_outcome("claude", "testing", True)

        analysis_scores = await mm.get_scores_for_task_type("analysis")
        assert len(analysis_scores) == 2

        testing_scores = await mm.get_scores_for_task_type("testing")
        assert len(testing_scores) == 1


class TestMetaMemoryBestAgent:
    """Thompson-sampling-based best agent selection."""

    async def test_get_best_agent(self, repository):
        mm = MetaMemory(repository)
        # Strongly favor claude with many successes
        for _ in range(20):
            await mm.record_outcome("claude", "bug_fix", True)
        for _ in range(20):
            await mm.record_outcome("codex", "bug_fix", False)

        # Run multiple times to verify claude wins the majority
        random.seed(42)
        wins = {"claude": 0, "codex": 0}
        for _ in range(50):
            best = await mm.get_best_agent("bug_fix")
            wins[best] += 1

        assert wins["claude"] > wins["codex"], (
            f"Expected claude to win majority, got claude={wins['claude']} codex={wins['codex']}"
        )

    async def test_get_best_agent_no_data(self, repository):
        mm = MetaMemory(repository)
        best = await mm.get_best_agent("nonexistent_task_type")
        assert best is None


class TestMetaMemoryPerformanceSummary:
    """Aggregate performance summary."""

    async def test_get_performance_summary(self, repository):
        mm = MetaMemory(repository)
        await mm.record_outcome("claude", "bug_fix", True, quality_score=0.9, cost_usd=0.05, duration_seconds=10.0)
        await mm.record_outcome("codex", "testing", False, quality_score=0.3, cost_usd=0.02, duration_seconds=5.0)
        await mm.record_outcome("claude", "testing", True, quality_score=0.8, cost_usd=0.04, duration_seconds=8.0)

        summary = await mm.get_performance_summary()

        assert summary["total_agents"] == 2
        assert summary["total_task_types"] == 2
        assert summary["total_attempts"] == 3
        assert 0.0 < summary["overall_success_rate"] < 1.0

        assert "claude" in summary["per_agent"]
        assert "codex" in summary["per_agent"]
        assert "bug_fix" in summary["per_task_type"]
        assert "testing" in summary["per_task_type"]

        # Check per-agent structure
        claude_summary = summary["per_agent"]["claude"]
        assert claude_summary["successes"] == 2
        assert claude_summary["failures"] == 0
        assert "bayesian_score" in claude_summary
        assert "success_rate" in claude_summary

    async def test_get_performance_summary_empty(self, repository):
        mm = MetaMemory(repository)
        summary = await mm.get_performance_summary()

        assert summary["total_agents"] == 0
        assert summary["total_task_types"] == 0
        assert summary["total_attempts"] == 0
        assert summary["overall_success_rate"] == 0.0
        assert summary["per_agent"] == {}
        assert summary["per_task_type"] == {}


class TestMetaMemoryScoreDecay:
    """Score decay reduces evidence counts to keep routing fresh."""

    async def test_apply_score_decay(self, repository):
        mm = MetaMemory(repository)
        # Record 10 successes so successes=10, failures=0
        for _ in range(10):
            await mm.record_outcome("claude", "bug_fix", True)

        scores_before = await mm.get_agent_scores("claude")
        assert scores_before[0]["successes"] == 10

        await mm.apply_score_decay("claude", decay_factor=0.5)

        scores_after = await mm.get_agent_scores("claude")
        # 10 * 0.5 = 5 (truncated to int)
        assert scores_after[0]["successes"] == 5
        assert scores_after[0]["total_attempts"] == 5

    async def test_apply_score_decay_preserves_minimum(self, repository):
        mm = MetaMemory(repository)
        await mm.record_outcome("claude", "testing", True)

        # With 1 success and decay 0.1 => int(1*0.1) = 0
        await mm.apply_score_decay("claude", decay_factor=0.1)

        scores = await mm.get_agent_scores("claude")
        assert scores[0]["successes"] == 0
        assert scores[0]["failures"] == 0


# ============================================================================
# 3. BayesianRouter Tests
# ============================================================================


class TestBayesianRouterBasic:
    """Core routing behavior."""

    async def test_route_empty_agents_raises(self, repository):
        mm = MetaMemory(repository)
        router = BayesianRouter(mm)
        with pytest.raises(ValueError, match="non-empty"):
            await router.route("bug_fix", [])

    async def test_route_returns_available_agent(self, repository):
        mm = MetaMemory(repository)
        router = BayesianRouter(mm, exploration_rate=0.0)
        available = ["claude", "codex", "gemini"]

        result = await router.route("bug_fix", available)
        assert result in available

    async def test_route_single_agent(self, repository):
        mm = MetaMemory(repository)
        router = BayesianRouter(mm, exploration_rate=0.0)

        result = await router.route("bug_fix", ["codex"])
        assert result == "codex"


class TestBayesianRouterExploration:
    """Exploration rate controls random vs Thompson selection."""

    async def test_route_exploration_rate_full(self, repository):
        """With exploration_rate=1.0, every call is random."""
        mm = MetaMemory(repository)
        router = BayesianRouter(mm, exploration_rate=1.0)
        available = ["claude", "codex", "gemini", "grok"]

        random.seed(42)
        results = set()
        for _ in range(100):
            result = await router.route("bug_fix", available)
            results.add(result)

        # With 100 random selections among 4 agents, we should see diversity
        assert len(results) >= 2

    async def test_route_no_exploration(self, repository):
        """With exploration_rate=0.0 and strong data, the best agent is consistently chosen."""
        mm = MetaMemory(repository)
        router = BayesianRouter(mm, exploration_rate=0.0)

        # Strongly favor claude
        for _ in range(30):
            await mm.record_outcome("claude", "bug_fix", True)
        for _ in range(30):
            await mm.record_outcome("codex", "bug_fix", False)

        random.seed(42)
        results = []
        for _ in range(50):
            result = await router.route("bug_fix", ["claude", "codex"])
            results.append(result)

        claude_count = results.count("claude")
        assert claude_count > 40, (
            f"Expected claude to dominate routing, got {claude_count}/50"
        )


class TestBayesianRouterFallback:
    """Fallback behavior when no score data exists."""

    async def test_route_fallback_default(self, repository):
        """No score data and claude in available => returns some agent (Thompson from prior)."""
        mm = MetaMemory(repository)
        router = BayesianRouter(mm, exploration_rate=0.0)

        # Without any score data, Thompson draws from uninformative priors;
        # the result is stochastic but must be from available agents.
        result = await router.route("unknown_type", ["claude", "codex"])
        assert result in ["claude", "codex"]

    async def test_route_fallback_random(self, repository):
        """No score data and claude NOT in available => returns random from available."""
        mm = MetaMemory(repository)
        router = BayesianRouter(mm, exploration_rate=0.0)

        result = await router.route("unknown_type", ["codex", "gemini"])
        assert result in ["codex", "gemini"]


class TestBayesianRouterScoreDecay:
    """Decay delegation and unused-agent decay."""

    async def test_apply_score_decay(self, repository):
        mm = MetaMemory(repository)
        router = BayesianRouter(mm, score_decay=0.5)

        for _ in range(10):
            await mm.record_outcome("claude", "bug_fix", True)

        await router.apply_score_decay("claude")

        scores = await mm.get_agent_scores("claude")
        assert scores[0]["successes"] == 5  # 10 * 0.5

    async def test_decay_unused_agents(self, repository):
        mm = MetaMemory(repository)
        router = BayesianRouter(mm, score_decay=0.5)

        # Record scores for all agents
        for _ in range(10):
            await mm.record_outcome("claude", "bug_fix", True)
        for _ in range(10):
            await mm.record_outcome("codex", "bug_fix", True)
        for _ in range(10):
            await mm.record_outcome("gemini", "bug_fix", True)

        # Only claude was used this cycle
        decayed = await router.decay_unused_agents(
            used_agent_ids=["claude"],
            all_agent_ids=["claude", "codex", "gemini"],
        )

        assert set(decayed) == {"codex", "gemini"}

        # Verify claude is untouched
        claude_scores = await mm.get_agent_scores("claude")
        assert claude_scores[0]["successes"] == 10

        # Verify codex/gemini were decayed
        codex_scores = await mm.get_agent_scores("codex")
        assert codex_scores[0]["successes"] == 5

        gemini_scores = await mm.get_agent_scores("gemini")
        assert gemini_scores[0]["successes"] == 5


class TestBayesianRouterRoutingState:
    """Introspection / debugging state."""

    async def test_get_routing_state(self, repository):
        mm = MetaMemory(repository)
        router = BayesianRouter(mm, exploration_rate=0.15, score_decay=0.90)

        await mm.record_outcome("claude", "bug_fix", True, quality_score=0.9)
        await mm.record_outcome("codex", "testing", False, quality_score=0.3)

        state = await router.get_routing_state()

        assert state["exploration_rate"] == 0.15
        assert state["score_decay"] == 0.90
        assert "claude" in state["agents"]
        assert "codex" in state["agents"]
        assert "bug_fix" in state["agents"]["claude"]["task_types"]
        assert "testing" in state["agents"]["codex"]["task_types"]

        claude_bug = state["agents"]["claude"]["task_types"]["bug_fix"]
        assert claude_bug["successes"] == 1
        assert claude_bug["failures"] == 0
        assert "bayesian_score" in claude_bug
        assert "thompson_sample" in claude_bug

    async def test_get_routing_state_empty(self, repository):
        mm = MetaMemory(repository)
        router = BayesianRouter(mm)

        state = await router.get_routing_state()
        assert state["agents"] == {}


class TestBayesianRouterStatisticalConvergence:
    """Statistical convergence — heavily favored agent wins majority of routings."""

    async def test_route_statistical_convergence(self, repository):
        mm = MetaMemory(repository)
        router = BayesianRouter(mm, exploration_rate=0.0)

        # Record 25 successes for claude, 25 failures for codex
        for _ in range(25):
            await mm.record_outcome("claude", "analysis", True, quality_score=0.95)
        for _ in range(25):
            await mm.record_outcome("codex", "analysis", False, quality_score=0.1)

        random.seed(123)
        selections = {"claude": 0, "codex": 0}
        for _ in range(50):
            chosen = await router.route("analysis", ["claude", "codex"])
            selections[chosen] += 1

        # Claude should win the vast majority
        assert selections["claude"] > 40, (
            f"Expected claude >40/50, got {selections['claude']}"
        )


# ============================================================================
# 4. PatternLearner Tests
# ============================================================================


class TestPatternLearnerExtract:
    """Pattern extraction from completed tasks."""

    async def test_extract_patterns_insufficient_completions(self, repository):
        project = _make_project()
        await repository.create_project(project)

        # Create only 3 completed tasks (below default min_completions=5)
        for i in range(3):
            task = _make_task(project.id, title=f"task-{i}")
            await repository.create_task(task)
            await repository.update_task_status(task.id, TaskStatus.DONE)

        pl = PatternLearner(repository)
        patterns = await pl.extract_patterns(project.id)
        assert patterns == []

    async def test_extract_patterns_insufficient_with_custom_min(self, repository):
        project = _make_project()
        await repository.create_project(project)

        # Create 2 completed tasks, require min_completions=3
        for i in range(2):
            task = _make_task(project.id, title=f"task-{i}")
            await repository.create_task(task)
            await repository.update_task_status(task.id, TaskStatus.DONE)

        pl = PatternLearner(repository)
        patterns = await pl.extract_patterns(project.id, min_completions=3)
        assert patterns == []

    async def test_extract_patterns_error_resolution(self, repository):
        """Set up 5+ completed tasks with same error_signature resolved by SUCCESS."""
        project = _make_project()
        await repository.create_project(project)

        tasks = []
        for i in range(6):
            task = _make_task(project.id, title=f"err-task-{i}")
            await repository.create_task(task)
            await repository.update_task_status(task.id, TaskStatus.DONE)
            tasks.append(task)

        # Log hypothesis entries with the same error_signature and SUCCESS
        for i, task in enumerate(tasks[:3]):
            h = HypothesisEntry(
                task_id=task.id,
                attempt_number=1,
                approach_summary="Applied null check fix",
                outcome=HypothesisOutcome.SUCCESS,
                error_signature="NullPointerException::line42",
                agent_id="claude",
            )
            await repository.log_hypothesis(h)

        pl = PatternLearner(repository)
        patterns = await pl.extract_patterns(project.id, min_completions=5)

        # Should find the error_resolution pattern (3 successes with same signature >= 2)
        error_patterns = [p for p in patterns if p["pattern_type"] == "error_resolution"]
        assert len(error_patterns) >= 1
        ep = error_patterns[0]
        assert ep["error_signature"] == "NullPointerException::line42"
        assert ep["evidence_count"] >= 2
        assert "confidence" in ep

    async def test_extract_patterns_methodology_reuse(self, repository):
        """Set up thriving methodology with success_count >= 3 linked to project."""
        project = _make_project()
        await repository.create_project(project)

        # Create 5 completed tasks
        tasks = []
        for i in range(5):
            task = _make_task(project.id, title=f"meth-task-{i}")
            await repository.create_task(task)
            await repository.update_task_status(task.id, TaskStatus.DONE)
            tasks.append(task)

        # Create a thriving methodology linked to a task in this project
        # Use the helper that patches success_count after insert
        meth = Methodology(
            problem_description="Connection pool leak resolution",
            solution_code="pool.close() in finally block",
            source_task_id=tasks[0].id,
            tags=["database", "pool"],
            lifecycle_state="thriving",
            success_count=5,
            failure_count=0,
        )
        await _save_methodology_with_counts(repository, meth)

        pl = PatternLearner(repository)
        patterns = await pl.extract_patterns(project.id, min_completions=5)

        meth_patterns = [p for p in patterns if p["pattern_type"] == "methodology_reuse"]
        assert len(meth_patterns) >= 1
        mp = meth_patterns[0]
        assert mp["evidence_count"] >= 3
        assert "confidence" in mp
        assert mp["lifecycle_state"] == "thriving"


class TestPatternLearnerPromotion:
    """Promoting project-scope methodologies to global scope."""

    async def _create_methodology_with_counts(
        self, repository, task_id: str,
        success_count: int = 5, lifecycle_state: str = "thriving",
        scope: str = "project",
    ) -> Methodology:
        """Helper: create a methodology with the given properties persisted to DB."""
        meth = Methodology(
            problem_description="Reusable pattern for DB transactions",
            solution_code="with engine.begin() as conn: ...",
            source_task_id=task_id,
            tags=["database", "transaction"],
            scope=scope,
            lifecycle_state=lifecycle_state,
            success_count=success_count,
            failure_count=0,
        )
        await _save_methodology_with_counts(repository, meth)
        return meth

    async def _log_attributed_successes(
        self,
        repository,
        methodology_id: str,
        project_id: str,
        count: int = 3,
        expectation_match_score: float = 0.9,
    ) -> None:
        for _ in range(count):
            task = _make_task(project_id, title=f"usage-{_uid()}")
            await repository.create_task(task)
            await repository.log_methodology_usage(
                MethodologyUsageEntry(
                    task_id=task.id,
                    methodology_id=methodology_id,
                    project_id=project_id,
                    stage="outcome_attributed",
                    success=True,
                    expectation_match_score=expectation_match_score,
                    quality_score=0.85,
                )
            )

    async def test_promote_to_global_success(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id)
        await repository.create_task(task)

        meth = await self._create_methodology_with_counts(
            repository, task.id,
            success_count=5, lifecycle_state="thriving", scope="project",
        )
        await self._log_attributed_successes(repository, meth.id, project.id, count=3, expectation_match_score=0.9)

        pl = PatternLearner(repository)
        result = await pl.promote_to_global(meth.id)
        assert result is True

        # Verify in DB
        updated = await repository.get_methodology(meth.id)
        assert updated.scope == "global"

    async def test_promote_to_global_not_thriving(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id)
        await repository.create_task(task)

        meth = await self._create_methodology_with_counts(
            repository, task.id,
            success_count=5, lifecycle_state="viable", scope="project",
        )

        pl = PatternLearner(repository)
        result = await pl.promote_to_global(meth.id)
        assert result is False

        # Scope unchanged
        updated = await repository.get_methodology(meth.id)
        assert updated.scope == "project"

    async def test_promote_to_global_insufficient_successes(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id)
        await repository.create_task(task)

        meth = await self._create_methodology_with_counts(
            repository, task.id,
            success_count=2, lifecycle_state="thriving", scope="project",
        )
        await self._log_attributed_successes(repository, meth.id, project.id, count=2, expectation_match_score=0.9)

        pl = PatternLearner(repository)
        result = await pl.promote_to_global(meth.id)
        assert result is False

    async def test_promote_to_global_rejects_low_expectation_match(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id)
        await repository.create_task(task)

        meth = await self._create_methodology_with_counts(
            repository, task.id,
            success_count=5, lifecycle_state="thriving", scope="project",
        )
        await self._log_attributed_successes(repository, meth.id, project.id, count=3, expectation_match_score=0.4)

        pl = PatternLearner(repository)
        result = await pl.promote_to_global(meth.id)
        assert result is False

    async def test_promote_to_global_already_global(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id)
        await repository.create_task(task)

        meth = await self._create_methodology_with_counts(
            repository, task.id,
            success_count=5, lifecycle_state="thriving", scope="global",
        )

        pl = PatternLearner(repository)
        result = await pl.promote_to_global(meth.id)
        assert result is True  # Already global is a no-op success

    async def test_promote_to_global_not_found(self, repository):
        pl = PatternLearner(repository)
        result = await pl.promote_to_global("nonexistent-methodology-id")
        assert result is False


class TestPatternLearnerGlobalPatterns:
    """Retrieving global-scope methodologies."""

    async def test_get_global_patterns(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id)
        await repository.create_task(task)

        # Create two global-scope methodologies with real success_count
        for i in range(2):
            meth = Methodology(
                problem_description=f"Global pattern {i}",
                solution_code=f"solution_{i}()",
                source_task_id=task.id,
                tags=["global", f"pattern-{i}"],
                scope="global",
                lifecycle_state="thriving",
                success_count=10 - i,
                failure_count=0,
            )
            await _save_methodology_with_counts(repository, meth)
            await repository.log_methodology_usage(
                MethodologyUsageEntry(
                    task_id=task.id,
                    methodology_id=meth.id,
                    project_id=project.id,
                    stage="outcome_attributed",
                    success=True,
                    expectation_match_score=0.9,
                    quality_score=0.85,
                )
            )

        # Create one project-scope methodology (should NOT appear)
        local_meth = Methodology(
            problem_description="Local-only pattern",
            solution_code="local()",
            source_task_id=task.id,
            scope="project",
            lifecycle_state="thriving",
            success_count=20,
        )
        await _save_methodology_with_counts(repository, local_meth)

        pl = PatternLearner(repository)
        patterns = await pl.get_global_patterns()

        assert len(patterns) == 2
        # Ordered by success_count DESC
        assert patterns[0]["success_count"] >= patterns[1]["success_count"]
        assert patterns[0]["methodology_id"] is not None
        assert "problem_description" in patterns[0]
        assert "success_rate" in patterns[0]
        assert "tags" in patterns[0]
        assert "attributed_success_count" in patterns[0]
        assert "avg_expectation_match_score" in patterns[0]
        assert patterns[0]["evidence_source"] in {"attribution", "legacy"}

    async def test_get_global_patterns_empty(self, repository):
        pl = PatternLearner(repository)
        patterns = await pl.get_global_patterns()
        assert patterns == []

    async def test_get_global_patterns_respects_limit(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id)
        await repository.create_task(task)

        for i in range(5):
            meth = Methodology(
                problem_description=f"Pattern {i}",
                solution_code=f"fix_{i}()",
                source_task_id=task.id,
                scope="global",
                lifecycle_state="thriving",
                success_count=i,
            )
            await _save_methodology_with_counts(repository, meth)

        pl = PatternLearner(repository)
        patterns = await pl.get_global_patterns(limit=3)
        assert len(patterns) == 3


class TestPatternLearnerSummary:
    """Pattern summary for a project."""

    async def test_get_pattern_summary(self, repository):
        project = _make_project()
        await repository.create_project(project)

        # Create completed tasks
        tasks = []
        for i in range(7):
            task = _make_task(project.id, title=f"summary-task-{i}")
            await repository.create_task(task)
            await repository.update_task_status(task.id, TaskStatus.DONE)
            tasks.append(task)

        # Create methodologies linked to tasks
        meth_thriving = Methodology(
            problem_description="Thriving method",
            solution_code="fix()",
            source_task_id=tasks[0].id,
            scope="project",
            lifecycle_state="thriving",
            success_count=5,
        )
        await _save_methodology_with_counts(repository, meth_thriving)

        meth_global = Methodology(
            problem_description="Global method",
            solution_code="global_fix()",
            source_task_id=tasks[1].id,
            scope="global",
            lifecycle_state="thriving",
            success_count=10,
        )
        await _save_methodology_with_counts(repository, meth_global)

        meth_viable = Methodology(
            problem_description="Viable method",
            solution_code="viable_fix()",
            source_task_id=tasks[2].id,
            scope="project",
            lifecycle_state="viable",
            success_count=1,
        )
        await _save_methodology_with_counts(repository, meth_viable)

        # Add some hypothesis log entries for error_signature clusters
        for i in range(3):
            h = HypothesisEntry(
                task_id=tasks[i].id,
                attempt_number=1,
                approach_summary="Fixed timeout issue",
                outcome=HypothesisOutcome.SUCCESS,
                error_signature="TimeoutError::connect",
                agent_id="claude",
            )
            await repository.log_hypothesis(h)

        pl = PatternLearner(repository)
        summary = await pl.get_pattern_summary(project.id)

        assert summary["project_id"] == project.id
        assert summary["completed_tasks"] == 7
        assert summary["total_methodologies"] == 3
        assert summary["global_methodologies"] == 1
        assert summary["thriving_methodologies"] == 2  # meth_thriving + meth_global
        assert summary["patterns_available"] is True  # 7 >= 5
        assert summary["error_signature_clusters"] >= 1

    async def test_get_pattern_summary_empty_project(self, repository):
        pl = PatternLearner(repository)
        summary = await pl.get_pattern_summary("nonexistent-project")

        assert summary["project_id"] == "nonexistent-project"
        assert summary["completed_tasks"] == 0
        assert summary["total_methodologies"] == 0
        assert summary["global_methodologies"] == 0
        assert summary["thriving_methodologies"] == 0
        assert summary["patterns_available"] is False
        assert summary["error_signature_clusters"] == 0

    async def test_get_pattern_summary_below_threshold(self, repository):
        project = _make_project()
        await repository.create_project(project)

        # Only 3 completed tasks
        for i in range(3):
            task = _make_task(project.id, title=f"few-{i}")
            await repository.create_task(task)
            await repository.update_task_status(task.id, TaskStatus.DONE)

        pl = PatternLearner(repository)
        summary = await pl.get_pattern_summary(project.id)
        assert summary["completed_tasks"] == 3
        assert summary["patterns_available"] is False
