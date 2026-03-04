"""Tests for orchestrator support modules:
  - complexity.py   — score_task_complexity
  - health_monitor.py — HealthMonitor, HealthCheck
  - loop_guard.py   — check_error_loop, LoopVerdict
  - budget_hints.py — generate_budget_hint
  - arbitration.py  — AgentArbiter, ArbitrationDecision
  - metrics.py      — PipelineMetrics, PipelineRun, AgentMetric
  - diagnostics.py  — DiagnosticsCollector, RunDiagnostics
  - adaptation.py   — PipelineAdapter, AdaptationSignals, PipelineDecision

NO mocks. All objects are real instances of production models.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from claw.core.config import OrchestratorConfig
from claw.core.models import AgentResult, ComplexityTier, Task, TaskOutcome, TaskStatus
from claw.orchestrator.adaptation import (
    AdaptationSignals,
    PipelineAdapter,
    PipelineDecision,
)
from claw.orchestrator.arbitration import AgentArbiter, ArbitrationDecision, CandidateScore
from claw.orchestrator.budget_hints import generate_budget_hint
from claw.orchestrator.complexity import score_task_complexity
from claw.orchestrator.diagnostics import DiagnosticsCollector, RunDiagnostics
from claw.orchestrator.health_monitor import HealthCheck, HealthMonitor
from claw.orchestrator.loop_guard import LoopVerdict, check_error_loop
from claw.orchestrator.metrics import AgentMetric, PipelineMetrics, PipelineRun


# ---------------------------------------------------------------------------
# Helpers — real objects, no mocks
# ---------------------------------------------------------------------------

def _make_task(
    title: str = "test task",
    description: str = "a task description",
    task_type: str = "analysis",
    status: TaskStatus = TaskStatus.PENDING,
    priority: int = 5,
) -> Task:
    return Task(
        project_id="proj-orch-test",
        title=title,
        description=description,
        task_type=task_type,
        status=status,
        priority=priority,
    )


def _make_agent_result(
    agent_name: str = "claude",
    status: str = "success",
    error: str | None = None,
    duration: float = 1.0,
) -> AgentResult:
    return AgentResult(
        agent_name=agent_name,
        status=status,
        data={"output": "some real output"},
        error=error,
        duration_seconds=duration,
    )


def _make_task_outcome(
    files_changed: list[str] | None = None,
    tests_passed: bool = True,
    failure_reason: str | None = None,
) -> TaskOutcome:
    return TaskOutcome(
        files_changed=files_changed or [],
        test_output="All tests passed" if tests_passed else "FAILED",
        tests_passed=tests_passed,
        approach_summary="Implemented the fix",
        failure_reason=failure_reason,
    )


# ---------------------------------------------------------------------------
# Minimal repository-like object for HealthMonitor and LoopGuard
# No mocking — this is a real object that stores and returns real data.
# ---------------------------------------------------------------------------

class _InMemoryRepository:
    """Lightweight real repository that stores data in memory.

    Satisfies the interface needed by HealthMonitor and LoopGuard without
    requiring a real database connection.
    """

    def __init__(self):
        self._tasks: list[Task] = []
        self._error_signatures: dict[tuple[str, str], int] = {}
        self._failed_approaches: dict[str, list] = {}

    def add_task(self, task: Task) -> None:
        self._tasks.append(task)

    def set_error_count(self, task_id: str, error_signature: str, count: int) -> None:
        self._error_signatures[(task_id, error_signature)] = count

    async def get_in_progress_tasks(self) -> list[Task]:
        return [
            t for t in self._tasks
            if t.status not in (TaskStatus.DONE, TaskStatus.STUCK, TaskStatus.PENDING)
        ]

    async def count_error_signature(self, task_id: str, error_signature: str) -> int:
        return self._error_signatures.get((task_id, error_signature), 0)

    async def get_failed_approaches(self, task_id: str) -> list:
        return self._failed_approaches.get(task_id, [])

    async def get_agent_scores(self, agent_id=None) -> list[dict]:
        return []


# ============================================================================
# Complexity Scoring
# ============================================================================


class TestComplexityScoring:
    """score_task_complexity keyword-based classification.

    The scoring formula is:
        score = (high_hits * 3) + (medium_hits * 1) + desc_length_score - (low_hits * 1)

    Tiers: TRIVIAL (score < 1), LOW (1), MEDIUM (2-3), HIGH (4-5), VERY_HIGH (>= 6)
    """

    def test_migration_keyword_is_very_high(self):
        # High keywords: migration, concurrent, distributed, security = 4 hits * 3 = 12
        # Medium keywords: schema, database = 2 hits * 1 = 2
        # word_count > 50 -> desc_length_score = 1
        # score >= 6 -> VERY_HIGH
        task = _make_task(
            title="Database migration to PostgreSQL",
            description="Migrate the entire SQLite database schema and data to PostgreSQL. "
                        "This requires rewriting all queries, updating the ORM layer, "
                        "and ensuring data integrity during the migration process. "
                        "Must handle concurrent access, distributed locking, and security constraints.",
        )
        tier = score_task_complexity(task)
        assert tier == ComplexityTier.VERY_HIGH

    def test_fix_typo_is_trivial(self):
        # High: 0, Medium: 0, Low: "fix"=1, "typo"=1 = 2 low hits
        # score = 0 + 0 + 0 - 2 = -2 -> TRIVIAL
        task = _make_task(
            title="fix typo",
            description="fix a typo in readme",
        )
        tier = score_task_complexity(task)
        assert tier == ComplexityTier.TRIVIAL

    def test_database_query_task_is_medium(self):
        # High: 0 hits
        # Medium: "database"=1, "query"=1 = 2 medium hits
        # Low: 0 hits
        # score = 0 + 2 + 0 - 0 = 2 -> MEDIUM
        task = _make_task(
            title="Create database query",
            description="Write a new database query to fetch user records from the main table",
        )
        tier = score_task_complexity(task)
        assert tier == ComplexityTier.MEDIUM

    def test_logging_improvement_is_low(self):
        # High: 0 hits
        # Medium: "logging"=1 = 1 medium hit
        # Low: 0 hits (no low keywords present)
        # score = 0 + 1 + 0 - 0 = 1 -> LOW
        task = _make_task(
            title="Improve logging output",
            description="Improve the logging output to include timestamps and request identifiers",
        )
        tier = score_task_complexity(task)
        assert tier == ComplexityTier.LOW

    def test_security_auth_refactor_is_high_or_very_high(self):
        # High: "refactor"=1, "authentication"=1, "authorization"=1,
        #        "security"=1, "encryption"=1, "multi-"=1 = 6 hits * 3 = 18
        # score >= 6 -> VERY_HIGH
        task = _make_task(
            title="Refactor authentication system",
            description="Refactor the authentication and authorization system to support "
                        "multi-tenant security with encryption at rest",
        )
        tier = score_task_complexity(task)
        assert tier in (ComplexityTier.HIGH, ComplexityTier.VERY_HIGH)

    def test_api_with_many_keywords_is_high(self):
        # Combined text has: api, endpoint, validation, error handling, testing -> 5 medium hits
        # Also: "add" -> 1 low hit
        # score = 0 + 5 + 0 - 1 = 4 -> HIGH
        task = _make_task(
            title="API endpoint testing",
            description="Add testing for the new API endpoint including validation and error handling",
        )
        tier = score_task_complexity(task)
        assert tier == ComplexityTier.HIGH


# ============================================================================
# Health Monitor
# ============================================================================


class TestHealthMonitor:
    """HealthMonitor circuit breaker and token budget checks."""

    def _make_monitor(self, repo=None) -> HealthMonitor:
        config = OrchestratorConfig()
        return HealthMonitor(
            repository=repo or _InMemoryRepository(),
            config=config,
            max_task_age_minutes=30,
            max_tokens_per_task=100_000,
        )

    async def test_fresh_monitor_passes_all_checks(self):
        monitor = self._make_monitor()
        checks = await monitor.run_checks()
        # Only stuck_tasks check runs (no agents registered yet)
        assert len(checks) >= 1
        assert all(c.passed for c in checks)

    def test_record_3_failures_opens_circuit(self):
        monitor = self._make_monitor()
        # 3 consecutive failures should open the circuit
        monitor.record_agent_failure("claude")
        assert not monitor.is_agent_circuit_open("claude")
        monitor.record_agent_failure("claude")
        assert not monitor.is_agent_circuit_open("claude")
        monitor.record_agent_failure("claude")
        assert monitor.is_agent_circuit_open("claude")

    def test_success_resets_failures(self):
        monitor = self._make_monitor()
        monitor.record_agent_failure("codex")
        monitor.record_agent_failure("codex")
        # 2 failures, circuit still closed
        assert not monitor.is_agent_circuit_open("codex")

        # Success resets
        monitor.record_agent_success("codex")
        assert not monitor.is_agent_circuit_open("codex")

        # Now 2 more failures won't open (counter was reset)
        monitor.record_agent_failure("codex")
        monitor.record_agent_failure("codex")
        assert not monitor.is_agent_circuit_open("codex")

    def test_token_budget_ok(self):
        monitor = self._make_monitor()
        check = monitor.check_token_budget(50_000)
        assert check.passed is True
        assert "OK" in check.message

    def test_token_budget_exceeded(self):
        monitor = self._make_monitor()
        check = monitor.check_token_budget(150_000)
        assert check.passed is False
        assert "exceeded" in check.message.lower()

    def test_token_budget_at_exactly_limit(self):
        monitor = self._make_monitor()
        check = monitor.check_token_budget(100_000)
        assert check.passed is True  # <= is OK, only > fails

    def test_get_agent_status_empty(self):
        monitor = self._make_monitor()
        status = monitor.get_agent_status()
        assert status == {}

    def test_get_agent_status_tracks_failures(self):
        monitor = self._make_monitor()
        monitor.record_agent_failure("grok")
        monitor.record_agent_failure("grok")
        status = monitor.get_agent_status()
        assert "grok" in status
        assert status["grok"]["consecutive_failures"] == 2
        assert status["grok"]["circuit_open"] is False

    def test_circuit_opens_for_correct_agent_only(self):
        monitor = self._make_monitor()
        # 3 failures for claude
        for _ in range(3):
            monitor.record_agent_failure("claude")
        # 1 failure for codex
        monitor.record_agent_failure("codex")

        assert monitor.is_agent_circuit_open("claude") is True
        assert monitor.is_agent_circuit_open("codex") is False

    async def test_health_check_reports_open_circuit(self):
        monitor = self._make_monitor()
        for _ in range(3):
            monitor.record_agent_failure("gemini")

        checks = await monitor.run_checks()
        circuit_checks = [c for c in checks if "circuit_breaker:gemini" in c.check_name]
        assert len(circuit_checks) == 1
        assert circuit_checks[0].passed is False
        assert "OPEN" in circuit_checks[0].message


# ============================================================================
# Loop Guard
# ============================================================================


class TestLoopGuard:
    """check_error_loop detects repeated error signatures."""

    async def test_empty_error_signature_returns_ok(self):
        repo = _InMemoryRepository()
        verdict = await check_error_loop(repo, "task-1", "")
        assert verdict == LoopVerdict.OK

    async def test_new_error_returns_ok(self):
        repo = _InMemoryRepository()
        # count=0 means error has never been seen
        verdict = await check_error_loop(repo, "task-1", "TypeError: NoneType")
        assert verdict == LoopVerdict.OK

    async def test_repeated_error_2x_returns_force_switch(self):
        repo = _InMemoryRepository()
        repo.set_error_count("task-1", "ImportError: no module named foo", 2)
        verdict = await check_error_loop(repo, "task-1", "ImportError: no module named foo")
        assert verdict == LoopVerdict.FORCE_SWITCH

    async def test_repeated_error_3x_returns_stuck(self):
        repo = _InMemoryRepository()
        repo.set_error_count("task-1", "SyntaxError: invalid syntax", 3)
        verdict = await check_error_loop(repo, "task-1", "SyntaxError: invalid syntax")
        assert verdict == LoopVerdict.STUCK

    async def test_repeated_error_5x_also_stuck(self):
        repo = _InMemoryRepository()
        repo.set_error_count("task-1", "TimeoutError", 5)
        verdict = await check_error_loop(repo, "task-1", "TimeoutError")
        assert verdict == LoopVerdict.STUCK

    async def test_custom_thresholds(self):
        repo = _InMemoryRepository()
        repo.set_error_count("task-2", "SomeError", 1)
        verdict = await check_error_loop(
            repo, "task-2", "SomeError",
            force_switch_threshold=1,
            stuck_threshold=2,
        )
        assert verdict == LoopVerdict.FORCE_SWITCH

    async def test_different_task_ids_are_independent(self):
        repo = _InMemoryRepository()
        repo.set_error_count("task-A", "Error X", 3)
        repo.set_error_count("task-B", "Error X", 0)

        verdict_a = await check_error_loop(repo, "task-A", "Error X")
        verdict_b = await check_error_loop(repo, "task-B", "Error X")

        assert verdict_a == LoopVerdict.STUCK
        assert verdict_b == LoopVerdict.OK


# ============================================================================
# Budget Hints
# ============================================================================


class TestBudgetHints:
    """generate_budget_hint pure-computation budget guidance."""

    def test_healthy_budget_returns_none(self):
        hint = generate_budget_hint(
            tokens_used=10_000,
            token_budget=100_000,
            attempt=1,
            max_retries=5,
        )
        assert hint is None

    def test_low_budget_returns_warning(self):
        hint = generate_budget_hint(
            tokens_used=85_000,
            token_budget=100_000,
            attempt=1,
            max_retries=5,
        )
        assert hint is not None
        assert "limited" in hint.lower() or "low" in hint.lower()

    def test_critically_low_budget(self):
        hint = generate_budget_hint(
            tokens_used=95_000,
            token_budget=100_000,
            attempt=1,
            max_retries=5,
        )
        assert hint is not None
        assert "critical" in hint.lower() or "minimal" in hint.lower()

    def test_exhausted_budget_returns_exhausted_message(self):
        hint = generate_budget_hint(
            tokens_used=100_000,
            token_budget=100_000,
            attempt=1,
            max_retries=5,
        )
        assert hint is not None
        assert "exhausted" in hint.upper() or "EXHAUSTED" in hint

    def test_deadline_iteration_returns_deadline_message(self):
        # attempt >= submit_by triggers deadline hint
        # submit_by = max(5-2, int(5*0.7)) = max(3, 3) = 3
        hint = generate_budget_hint(
            tokens_used=10_000,
            token_budget=100_000,
            attempt=3,
            max_retries=5,
        )
        assert hint is not None
        assert "DEADLINE" in hint

    def test_early_iteration_no_deadline(self):
        hint = generate_budget_hint(
            tokens_used=10_000,
            token_budget=100_000,
            attempt=1,
            max_retries=5,
        )
        # First attempt with healthy budget -> None
        assert hint is None

    def test_second_attempt_shows_iteration_info(self):
        hint = generate_budget_hint(
            tokens_used=10_000,
            token_budget=100_000,
            attempt=2,
            max_retries=5,
        )
        assert hint is not None
        assert "2/5" in hint

    def test_over_budget_returns_exhausted(self):
        hint = generate_budget_hint(
            tokens_used=120_000,
            token_budget=100_000,
            attempt=1,
            max_retries=5,
        )
        assert hint is not None
        assert "EXHAUSTED" in hint


# ============================================================================
# Arbitration
# ============================================================================


class TestArbitration:
    """AgentArbiter scores candidates and selects the best."""

    def test_single_candidate_selected(self):
        arbiter = AgentArbiter()
        result = _make_agent_result(agent_name="claude", status="success")
        outcome = _make_task_outcome(files_changed=["a.py"], tests_passed=True)

        decision = arbiter.choose([("claude", result, outcome)])

        assert isinstance(decision, ArbitrationDecision)
        assert decision.selected_agent_id == "claude"
        assert decision.selected_result is result
        assert decision.selected_outcome is outcome
        assert len(decision.scores) == 1

    def test_candidate_with_tests_passing_wins(self):
        arbiter = AgentArbiter()
        good_result = _make_agent_result(agent_name="claude", status="success")
        good_outcome = _make_task_outcome(files_changed=["a.py"], tests_passed=True)

        bad_result = _make_agent_result(agent_name="codex", status="failure")
        bad_outcome = _make_task_outcome(files_changed=["b.py"], tests_passed=False)

        candidates = [
            ("codex", bad_result, bad_outcome),
            ("claude", good_result, good_outcome),
        ]
        decision = arbiter.choose(candidates)
        assert decision.selected_agent_id == "claude"

    def test_multiple_candidates_scored_and_ranked(self):
        arbiter = AgentArbiter()

        # Claude: success, tests pass, 2 files
        c_result = _make_agent_result(agent_name="claude", status="success")
        c_outcome = _make_task_outcome(files_changed=["a.py", "b.py"], tests_passed=True)

        # Codex: success, tests pass, 1 file (smaller change set)
        x_result = _make_agent_result(agent_name="codex", status="success")
        x_outcome = _make_task_outcome(files_changed=["c.py"], tests_passed=True)

        # Grok: failure, tests fail
        g_result = _make_agent_result(agent_name="grok", status="failure")
        g_outcome = _make_task_outcome(files_changed=[], tests_passed=False)

        candidates = [
            ("claude", c_result, c_outcome),
            ("codex", x_result, x_outcome),
            ("grok", g_result, g_outcome),
        ]
        decision = arbiter.choose(candidates)

        # All 3 scored
        assert len(decision.scores) == 3

        # ranked_agent_ids should have grok last (worst score)
        assert decision.ranked_agent_ids[-1] == "grok"

        # Winner should be claude or codex (both pass tests)
        assert decision.selected_agent_id in ("claude", "codex")

    def test_empty_candidates_raises(self):
        arbiter = AgentArbiter()
        with pytest.raises(ValueError, match="no candidates"):
            arbiter.choose([])

    def test_vetoed_candidate_not_selected(self):
        arbiter = AgentArbiter()
        c_result = _make_agent_result(agent_name="claude", status="success")
        c_outcome = _make_task_outcome(files_changed=["a.py"], tests_passed=True)
        x_result = _make_agent_result(agent_name="codex", status="success")
        x_outcome = _make_task_outcome(files_changed=["b.py"], tests_passed=True)

        candidates = [
            ("claude", c_result, c_outcome),
            ("codex", x_result, x_outcome),
        ]
        vetoes = {"claude": ["security concern"]}

        decision = arbiter.choose(candidates, vetoes=vetoes)
        assert decision.selected_agent_id == "codex"
        assert len(decision.vetoed_candidates) == 1

    def test_to_dict_serialization(self):
        arbiter = AgentArbiter()
        result = _make_agent_result(agent_name="claude", status="success")
        outcome = _make_task_outcome(files_changed=["a.py"], tests_passed=True)

        decision = arbiter.choose([("claude", result, outcome)])
        d = decision.to_dict()

        assert isinstance(d, dict)
        assert d["selected_agent_id"] == "claude"
        assert isinstance(d["scores"], list)
        assert len(d["scores"]) == 1
        assert "total" in d["scores"][0]

    def test_no_artifacts_incurs_risk_penalty(self):
        arbiter = AgentArbiter()
        result = _make_agent_result(agent_name="claude", status="success")
        outcome = _make_task_outcome(files_changed=[], tests_passed=True)

        decision = arbiter.choose([("claude", result, outcome)])
        score = decision.scores[0]
        assert score.risk_penalty > 0.0
        assert "no_artifacts" in score.notes

    def test_large_change_set_incurs_penalty(self):
        arbiter = AgentArbiter(soft_file_limit=3)
        result = _make_agent_result(agent_name="claude", status="success")
        many_files = [f"file_{i}.py" for i in range(10)]
        outcome = _make_task_outcome(files_changed=many_files, tests_passed=True)

        decision = arbiter.choose([("claude", result, outcome)])
        score = decision.scores[0]
        assert score.risk_penalty > 0.0
        assert "large_change_set" in score.notes


# ============================================================================
# Metrics
# ============================================================================


class TestPipelineMetrics:
    """PipelineMetrics tracks runs and agent executions."""

    def test_start_and_complete_run(self):
        metrics = PipelineMetrics()
        run = metrics.start_run("task-1", run_number=1)
        assert isinstance(run, PipelineRun)
        assert run.task_id == "task-1"
        assert run.outcome == "in_progress"

        completed = metrics.complete_run("success")
        assert completed is not None
        assert completed.outcome == "success"
        assert completed.completed_at is not None

    def test_agent_metrics_recorded(self):
        metrics = PipelineMetrics()
        metrics.start_run("task-1", run_number=1)

        agent_metric = metrics.start_agent("task-1", "claude")
        assert isinstance(agent_metric, AgentMetric)
        assert agent_metric.agent_name == "claude"

        metrics.complete_agent(agent_metric, status="success", tokens_used=5000)
        assert agent_metric.status == "success"
        assert agent_metric.tokens_used == 5000
        assert agent_metric.completed_at is not None
        assert agent_metric.succeeded is True

    def test_failed_agent_metric(self):
        metrics = PipelineMetrics()
        metrics.start_run("task-1", run_number=1)

        agent_metric = metrics.start_agent("task-1", "grok")
        metrics.complete_agent(
            agent_metric, status="failure", tokens_used=1000, error="timeout"
        )
        assert agent_metric.succeeded is False
        assert agent_metric.error == "timeout"

    def test_summary_aggregation(self):
        metrics = PipelineMetrics()

        # Run 1 - success
        metrics.start_run("task-1", run_number=1)
        m1 = metrics.start_agent("task-1", "claude")
        metrics.complete_agent(m1, status="success", tokens_used=3000)
        metrics.complete_run("success")

        # Run 2 - failure
        metrics.start_run("task-2", run_number=2)
        m2 = metrics.start_agent("task-2", "codex")
        metrics.complete_agent(m2, status="failure", tokens_used=1000)
        metrics.complete_run("failure")

        summary = metrics.get_summary()
        assert summary["total_runs"] == 2
        assert summary["total_tokens"] == 4000
        assert summary["outcomes"]["success"] == 1
        assert summary["outcomes"]["failure"] == 1

    def test_empty_summary(self):
        metrics = PipelineMetrics()
        summary = metrics.get_summary()
        assert summary == {"total_runs": 0}

    def test_get_runs_filter_by_task(self):
        metrics = PipelineMetrics()
        metrics.start_run("task-A", run_number=1)
        metrics.complete_run("success")
        metrics.start_run("task-B", run_number=2)
        metrics.complete_run("failure")

        a_runs = metrics.get_runs(task_id="task-A")
        assert len(a_runs) == 1
        assert a_runs[0].task_id == "task-A"

        all_runs = metrics.get_runs()
        assert len(all_runs) == 2

    def test_get_latest_run(self):
        metrics = PipelineMetrics()
        assert metrics.get_latest_run() is None

        metrics.start_run("task-1", run_number=1)
        metrics.complete_run("success")
        metrics.start_run("task-2", run_number=2)
        metrics.complete_run("failure")

        latest = metrics.get_latest_run()
        assert latest is not None
        assert latest.task_id == "task-2"

    def test_bottleneck_agent_identification(self):
        metrics = PipelineMetrics()
        metrics.start_run("task-1", run_number=1)

        # Fast agent
        m1 = metrics.start_agent("task-1", "grok")
        metrics.complete_agent(m1, status="success", tokens_used=500)

        # Slow agent (manually set duration for reliable test)
        m2 = metrics.start_agent("task-1", "claude")
        metrics.complete_agent(m2, status="success", tokens_used=5000)
        m2.duration_seconds = 10.0  # Override to make this the bottleneck

        run = metrics.complete_run("success")
        assert run is not None
        assert run.bottleneck_agent == "claude"

    def test_total_tokens_accumulates(self):
        metrics = PipelineMetrics()
        metrics.start_run("task-1", run_number=1)

        m1 = metrics.start_agent("task-1", "claude")
        metrics.complete_agent(m1, status="success", tokens_used=3000)

        m2 = metrics.start_agent("task-1", "codex")
        metrics.complete_agent(m2, status="success", tokens_used=2000)

        run = metrics.complete_run("success")
        assert run is not None
        assert run.total_tokens == 5000


# ============================================================================
# Diagnostics
# ============================================================================


class TestDiagnosticsCollector:
    """DiagnosticsCollector structured diagnostic snapshots."""

    def test_start_record_complete_run(self):
        collector = DiagnosticsCollector()
        diag = collector.start_run("task-1", run_number=1, run_id="run-001")
        assert isinstance(diag, RunDiagnostics)
        assert diag.task_id == "task-1"
        assert collector.get_current() is diag

        result = _make_agent_result(agent_name="claude", status="success", duration=2.5)
        entry = collector.record_agent(
            task_id="task-1",
            agent_name="claude",
            result=result,
            tokens_used=1000,
            input_summary="Fix auth bug",
        )
        assert entry.agent_name == "claude"
        assert entry.tokens_used == 1000
        assert len(diag.entries) == 1

        completed = collector.complete_run("success")
        assert completed is not None
        assert completed.outcome == "success"
        assert collector.get_current() is None

    def test_dump_to_file(self):
        collector = DiagnosticsCollector()
        collector.start_run("task-1", run_number=1)

        result = _make_agent_result(agent_name="codex", status="success", duration=1.0)
        collector.record_agent("task-1", "codex", result, tokens_used=500)
        collector.complete_run("success")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_diag.json"
            written_path = collector.dump_to_file(output_path)
            assert written_path.exists()

            data = json.loads(written_path.read_text())
            assert data["total_runs"] == 1
            assert len(data["runs"]) == 1
            assert data["runs"][0]["task_id"] == "task-1"

    def test_dump_to_directory(self):
        collector = DiagnosticsCollector()
        collector.start_run("task-1", run_number=1)
        collector.complete_run("success")

        with tempfile.TemporaryDirectory() as tmpdir:
            written_path = collector.dump_to_file(tmpdir)
            assert written_path.exists()
            assert written_path.suffix == ".json"

    def test_history_limit(self):
        collector = DiagnosticsCollector(max_history=3)
        for i in range(5):
            collector.start_run(f"task-{i}", run_number=i)
            collector.complete_run("success")

        history = collector.get_history(limit=10)
        assert len(history) == 3  # capped at max_history

    def test_get_history_with_limit(self):
        collector = DiagnosticsCollector()
        for i in range(10):
            collector.start_run(f"task-{i}", run_number=i)
            collector.complete_run("success")

        recent = collector.get_history(limit=3)
        assert len(recent) == 3
        assert recent[-1].task_id == "task-9"

    def test_to_dict_serialization(self):
        collector = DiagnosticsCollector()
        diag = collector.start_run("task-1", run_number=1, run_id="run-abc")

        result = _make_agent_result(agent_name="claude", status="success", duration=1.5)
        collector.record_agent("task-1", "claude", result, tokens_used=800)
        collector.complete_run("success")

        d = diag.to_dict()
        assert d["task_id"] == "task-1"
        assert d["run_id"] == "run-abc"
        assert d["outcome"] == "success"
        assert len(d["entries"]) == 1
        assert d["entries"][0]["agent_name"] == "claude"

    def test_record_event(self):
        collector = DiagnosticsCollector()
        diag = collector.start_run("task-1", run_number=1)

        collector.record_event("gate_pass", {"gate": "claim-gate", "result": "pass"})

        assert len(diag.events) == 1
        assert diag.events[0]["event_type"] == "gate_pass"

    def test_complete_run_without_start_returns_none(self):
        collector = DiagnosticsCollector()
        result = collector.complete_run("success")
        assert result is None

    def test_dump_filter_by_task_id(self):
        collector = DiagnosticsCollector()
        collector.start_run("task-A", run_number=1)
        collector.complete_run("success")
        collector.start_run("task-B", run_number=2)
        collector.complete_run("failure")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "filtered.json"
            collector.dump_to_file(output_path, task_id="task-A")

            data = json.loads(output_path.read_text())
            assert data["total_runs"] == 1
            assert data["runs"][0]["task_id"] == "task-A"


# ============================================================================
# Adaptation
# ============================================================================


class TestPipelineAdaptation:
    """PipelineAdapter selects pipeline configuration from signals."""

    def test_trivial_task_minimal_pipeline(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="TRIVIAL",
            attempt_number=1,
            past_failure_count=0,
            memory_store_size=10,  # non-empty memory
        )
        decision = adapter.adapt(signals)
        assert decision.template_name == "minimal"
        assert decision.force_deep_verification is False

    def test_trivial_cold_start_minimal_skip_research(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="TRIVIAL",
            memory_store_size=0,
        )
        decision = adapter.adapt(signals)
        assert decision.template_name == "minimal"
        assert decision.skip_research is True

    def test_low_cold_start_minimal_skip_research(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="LOW",
            memory_store_size=0,
        )
        decision = adapter.adapt(signals)
        assert decision.template_name == "minimal"
        assert decision.skip_research is True

    def test_medium_cold_start_lean_skip_research(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="MEDIUM",
            memory_store_size=0,
        )
        decision = adapter.adapt(signals)
        assert decision.template_name == "lean"
        assert decision.skip_research is True

    def test_high_complexity_full_with_deep_verification(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="HIGH",
            memory_store_size=10,
        )
        decision = adapter.adapt(signals)
        assert decision.template_name == "full"
        assert decision.force_deep_verification is True

    def test_very_high_complexity_full_with_deep_verification(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="VERY_HIGH",
            memory_store_size=10,
        )
        decision = adapter.adapt(signals)
        assert decision.template_name == "full"
        assert decision.force_deep_verification is True

    def test_low_complexity_no_conflicts_lean(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="LOW",
            retrieval_conflict_count=0,
            memory_store_size=10,
        )
        decision = adapter.adapt(signals)
        assert decision.template_name == "lean"

    def test_retry_escalation_triggers_full(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="MEDIUM",
            attempt_number=3,
            memory_store_size=10,
        )
        decision = adapter.adapt(signals)
        assert decision.template_name == "full"
        assert decision.force_deep_verification is True

    def test_escalation_count_triggers_full(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="MEDIUM",
            escalation_count=1,
            memory_store_size=10,
        )
        decision = adapter.adapt(signals)
        assert decision.template_name == "full"
        assert decision.force_deep_verification is True

    def test_retrieval_conflicts_force_arbitration(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="MEDIUM",
            retrieval_conflict_count=2,
            memory_store_size=10,
        )
        decision = adapter.adapt(signals)
        assert decision.template_name == "full"
        assert decision.force_arbitration is True

    def test_high_with_conflicts_both_flags(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="HIGH",
            retrieval_conflict_count=2,
            memory_store_size=10,
        )
        decision = adapter.adapt(signals)
        assert decision.template_name == "full"
        assert decision.force_deep_verification is True
        assert decision.force_arbitration is True

    def test_medium_default_full(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="MEDIUM",
            memory_store_size=10,
            retrieval_conflict_count=0,
        )
        decision = adapter.adapt(signals)
        assert decision.template_name == "full"

    def test_trivial_with_past_failures_not_minimal(self):
        adapter = PipelineAdapter()
        signals = AdaptationSignals(
            complexity_tier="TRIVIAL",
            attempt_number=1,
            past_failure_count=2,  # past failures -> not minimal
            memory_store_size=10,
        )
        decision = adapter.adapt(signals)
        # With past failures, TRIVIAL should not be minimal
        # (the condition requires past_failure_count == 0)
        assert decision.template_name != "minimal" or decision.template_name == "full"
