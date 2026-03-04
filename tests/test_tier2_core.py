"""Tier 2 coverage improvement tests for CLAW core modules.

Targets:
1. src/claw/db/repository.py  (77% -> 90%+)
2. src/claw/cycle.py          (51% -> 80%+)
3. src/claw/orchestrator/adaptation.py    (67% -> 90%+)
4. src/claw/orchestrator/health_monitor.py (78% -> 90%+)

NO mocks. NO placeholders. NO cached responses.
All tests use real SQLite in-memory DB via conftest fixtures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import pytest

from claw.agents.interface import AgentInterface
from claw.core.config import OrchestratorConfig
from claw.core.models import (
    AgentHealth,
    AgentMode,
    HypothesisEntry,
    HypothesisOutcome,
    Methodology,
    Project,
    Task,
    TaskContext,
    TaskOutcome,
    TaskStatus,
)
from claw.cycle import MicroClaw
from claw.orchestrator.adaptation import (
    AdaptationSignals,
    PipelineAdapter,
    _infer_task_type,
)
from claw.orchestrator.health_monitor import HealthCheck, HealthMonitor


# ---------------------------------------------------------------------------
# Real AgentInterface subclass for cycle testing (NOT a mock)
# ---------------------------------------------------------------------------


class LocalAgent(AgentInterface):
    """Real AgentInterface subclass for testing.

    This is a concrete implementation of the abstract class, NOT a mock.
    It implements all abstract methods with deterministic behaviour controlled
    by constructor flags.
    """

    def __init__(self, should_succeed: bool = True):
        super().__init__(agent_id="test", name="Test Agent")
        self.should_succeed = should_succeed
        self.execute_call_count = 0

    @property
    def supported_modes(self) -> list[AgentMode]:
        return [AgentMode.API]

    @property
    def instruction_file(self) -> str:
        return "TEST.md"

    async def execute(
        self, task: TaskContext, context: Optional[Any] = None
    ) -> TaskOutcome:
        self.execute_call_count += 1
        if self.should_succeed:
            return TaskOutcome(
                agent_id="test",
                approach_summary="Test approach: implemented the solution",
                raw_output="Code changes applied successfully",
                files_changed=["src/test.py"],
                tests_passed=True,
                duration_seconds=1.5,
            )
        else:
            return TaskOutcome(
                agent_id="test",
                failure_reason="test_failure",
                failure_detail="Test deliberately failed",
                approach_summary="Tried but failed",
                raw_output="Error occurred",
                files_changed=[],
                tests_passed=False,
                duration_seconds=0.5,
            )

    async def health_check(self) -> AgentHealth:
        return AgentHealth(agent_id="test", available=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(name: str = "tier2-test-project") -> Project:
    return Project(
        name=name,
        repo_path="/tmp/tier2-test-repo",
        tech_stack={"language": "python"},
    )


def _make_task(
    project_id: str,
    title: str = "Test task",
    description: str = "A test task description",
    priority: int = 5,
    task_type: str = "analysis",
    status: TaskStatus = TaskStatus.PENDING,
    recommended_agent: Optional[str] = None,
) -> Task:
    return Task(
        project_id=project_id,
        title=title,
        description=description,
        priority=priority,
        task_type=task_type,
        status=status,
        recommended_agent=recommended_agent,
    )


def _make_methodology(
    source_task_id: Optional[str] = None,
    problem_description: str = "Generic problem",
    solution_code: str = "fix()",
    tags: Optional[list[str]] = None,
    lifecycle_state: str = "viable",
    language: str = "python",
    methodology_type: str = "PATTERN",
    problem_embedding: Optional[list[float]] = None,
    methodology_notes: Optional[str] = None,
) -> Methodology:
    return Methodology(
        problem_description=problem_description,
        solution_code=solution_code,
        source_task_id=source_task_id,
        tags=tags or ["test"],
        lifecycle_state=lifecycle_state,
        language=language,
        methodology_type=methodology_type,
        problem_embedding=problem_embedding,
        methodology_notes=methodology_notes,
    )


async def _setup_project_and_task(
    repository,
    project_name: str = "tier2-proj",
    task_title: str = "Tier2 test task",
    task_description: str = "A task for tier2 tests",
    priority: int = 5,
    task_type: str = "analysis",
    status: TaskStatus = TaskStatus.PENDING,
    recommended_agent: Optional[str] = None,
) -> tuple[Project, Task]:
    """Insert a real project and task into the DB, returning both."""
    project = _make_project(project_name)
    await repository.create_project(project)
    task = _make_task(
        project.id,
        title=task_title,
        description=task_description,
        priority=priority,
        task_type=task_type,
        status=status,
        recommended_agent=recommended_agent,
    )
    await repository.create_task(task)
    return project, task


# ============================================================================
# 1. Repository — missing coverage
# ============================================================================


class TestRepositoryInProgressTasks:
    """get_in_progress_tasks() returns tasks in active states."""

    async def test_returns_empty_when_no_in_progress(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id, status=TaskStatus.PENDING)
        await repository.create_task(task)

        result = await repository.get_in_progress_tasks()
        assert result == []

    async def test_returns_evaluating_task(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id)
        await repository.create_task(task)
        await repository.update_task_status(task.id, TaskStatus.EVALUATING)

        result = await repository.get_in_progress_tasks()
        assert len(result) == 1
        assert result[0].id == task.id
        assert result[0].status == TaskStatus.EVALUATING

    async def test_returns_planning_task(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id)
        await repository.create_task(task)
        await repository.update_task_status(task.id, TaskStatus.PLANNING)

        result = await repository.get_in_progress_tasks()
        assert len(result) == 1
        assert result[0].status == TaskStatus.PLANNING

    async def test_returns_dispatched_task(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id)
        await repository.create_task(task)
        await repository.update_task_status(task.id, TaskStatus.DISPATCHED)

        result = await repository.get_in_progress_tasks()
        assert len(result) == 1
        assert result[0].status == TaskStatus.DISPATCHED

    async def test_returns_coding_task(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id)
        await repository.create_task(task)
        await repository.update_task_status(task.id, TaskStatus.CODING)

        result = await repository.get_in_progress_tasks()
        assert len(result) == 1
        assert result[0].status == TaskStatus.CODING

    async def test_returns_reviewing_task(self, repository):
        project = _make_project()
        await repository.create_project(project)
        task = _make_task(project.id)
        await repository.create_task(task)
        await repository.update_task_status(task.id, TaskStatus.REVIEWING)

        result = await repository.get_in_progress_tasks()
        assert len(result) == 1
        assert result[0].status == TaskStatus.REVIEWING

    async def test_excludes_done_and_pending(self, repository):
        project = _make_project()
        await repository.create_project(project)

        pending = _make_task(project.id, title="Pending")
        done = _make_task(project.id, title="Done")
        coding = _make_task(project.id, title="Coding")
        await repository.create_task(pending)
        await repository.create_task(done)
        await repository.create_task(coding)

        await repository.update_task_status(done.id, TaskStatus.DONE)
        await repository.update_task_status(coding.id, TaskStatus.CODING)

        result = await repository.get_in_progress_tasks()
        assert len(result) == 1
        assert result[0].title == "Coding"

    async def test_returns_multiple_in_progress(self, repository):
        project = _make_project()
        await repository.create_project(project)

        t1 = _make_task(project.id, title="Evaluating")
        t2 = _make_task(project.id, title="Coding")
        t3 = _make_task(project.id, title="Reviewing")
        await repository.create_task(t1)
        await repository.create_task(t2)
        await repository.create_task(t3)

        await repository.update_task_status(t1.id, TaskStatus.EVALUATING)
        await repository.update_task_status(t2.id, TaskStatus.CODING)
        await repository.update_task_status(t3.id, TaskStatus.REVIEWING)

        result = await repository.get_in_progress_tasks()
        assert len(result) == 3


class TestRepositoryTaskStatusSummary:
    """get_task_status_summary() returns dict of status -> count."""

    async def test_empty_project(self, repository):
        project = _make_project()
        await repository.create_project(project)
        summary = await repository.get_task_status_summary(project.id)
        assert summary == {}

    async def test_single_status(self, repository):
        project = _make_project()
        await repository.create_project(project)
        t1 = _make_task(project.id, title="T1")
        t2 = _make_task(project.id, title="T2")
        await repository.create_task(t1)
        await repository.create_task(t2)

        summary = await repository.get_task_status_summary(project.id)
        assert summary["PENDING"] == 2

    async def test_mixed_statuses(self, repository):
        project = _make_project()
        await repository.create_project(project)

        t1 = _make_task(project.id, title="T1")
        t2 = _make_task(project.id, title="T2")
        t3 = _make_task(project.id, title="T3")
        await repository.create_task(t1)
        await repository.create_task(t2)
        await repository.create_task(t3)

        await repository.update_task_status(t1.id, TaskStatus.DONE)
        await repository.update_task_status(t2.id, TaskStatus.CODING)

        summary = await repository.get_task_status_summary(project.id)
        assert summary["DONE"] == 1
        assert summary["CODING"] == 1
        assert summary["PENDING"] == 1

    async def test_global_summary_no_project_id(self, repository):
        p1 = _make_project("project-A")
        p2 = _make_project("project-B")
        await repository.create_project(p1)
        await repository.create_project(p2)

        t1 = _make_task(p1.id, title="A-task")
        t2 = _make_task(p2.id, title="B-task")
        await repository.create_task(t1)
        await repository.create_task(t2)

        summary = await repository.get_task_status_summary()
        assert summary["PENDING"] == 2


class TestRepositoryMethodologyTextSearch:
    """search_methodologies_text() uses FTS5."""

    async def test_finds_matching_methodology(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(
            source_task_id=task.id,
            problem_description="Memory leak in connection pool",
            methodology_notes="Close connections on exit",
        )
        await repository.save_methodology(m)

        results = await repository.search_methodologies_text("memory leak")
        assert len(results) >= 1
        assert results[0].problem_description == "Memory leak in connection pool"

    async def test_returns_empty_for_no_match(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(
            source_task_id=task.id,
            problem_description="Authentication bypass",
        )
        await repository.save_methodology(m)

        results = await repository.search_methodologies_text("nonexistent_xyz_query")
        assert results == []

    async def test_respects_limit(self, repository):
        project, task = await _setup_project_and_task(repository)
        for i in range(5):
            m = _make_methodology(
                source_task_id=task.id,
                problem_description=f"Database connection issue variant {i}",
                methodology_notes=f"Fix database for variant {i}",
            )
            await repository.save_methodology(m)

        results = await repository.search_methodologies_text("database", limit=2)
        assert len(results) <= 2

    async def test_matches_on_tags(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(
            source_task_id=task.id,
            problem_description="Generic issue",
            tags=["caching", "redis"],
        )
        await repository.save_methodology(m)

        results = await repository.search_methodologies_text("caching")
        assert len(results) >= 1

    async def test_matches_on_notes(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(
            source_task_id=task.id,
            problem_description="Slow endpoint",
            methodology_notes="Add pagination to the query results",
        )
        await repository.save_methodology(m)

        results = await repository.search_methodologies_text("pagination")
        assert len(results) >= 1


class TestRepositoryMethodologyByState:
    """get_methodologies_by_state() filters by lifecycle_state."""

    async def test_returns_matching_state(self, repository):
        project, task = await _setup_project_and_task(repository)
        m1 = _make_methodology(source_task_id=task.id, lifecycle_state="viable")
        m2 = _make_methodology(source_task_id=task.id, lifecycle_state="embryonic")
        m3 = _make_methodology(source_task_id=task.id, lifecycle_state="viable")
        await repository.save_methodology(m1)
        await repository.save_methodology(m2)
        await repository.save_methodology(m3)

        results = await repository.get_methodologies_by_state("viable")
        assert len(results) == 2
        for r in results:
            assert r.lifecycle_state == "viable"

    async def test_returns_empty_for_nonexistent_state(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(source_task_id=task.id, lifecycle_state="viable")
        await repository.save_methodology(m)

        results = await repository.get_methodologies_by_state("dead")
        assert results == []

    async def test_respects_limit(self, repository):
        project, task = await _setup_project_and_task(repository)
        for _ in range(10):
            m = _make_methodology(source_task_id=task.id, lifecycle_state="thriving")
            await repository.save_methodology(m)

        results = await repository.get_methodologies_by_state("thriving", limit=3)
        assert len(results) == 3


class TestRepositoryCountMethodologies:
    """count_methodologies() counts all non-dead methodologies."""

    async def test_empty_count(self, repository):
        count = await repository.count_methodologies()
        assert count == 0

    async def test_counts_all_methodologies(self, repository):
        project, task = await _setup_project_and_task(repository)
        for _ in range(3):
            m = _make_methodology(source_task_id=task.id)
            await repository.save_methodology(m)

        count = await repository.count_methodologies()
        assert count == 3


class TestRepositoryUpdateMethodologyLifecycle:
    """update_methodology_lifecycle() changes lifecycle_state."""

    async def test_updates_state(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(source_task_id=task.id, lifecycle_state="embryonic")
        await repository.save_methodology(m)

        await repository.update_methodology_lifecycle(m.id, "viable")

        got = await repository.get_methodology(m.id)
        assert got is not None
        assert got.lifecycle_state == "viable"

    async def test_multiple_transitions(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(source_task_id=task.id, lifecycle_state="embryonic")
        await repository.save_methodology(m)

        await repository.update_methodology_lifecycle(m.id, "viable")
        await repository.update_methodology_lifecycle(m.id, "thriving")
        await repository.update_methodology_lifecycle(m.id, "declining")

        got = await repository.get_methodology(m.id)
        assert got.lifecycle_state == "declining"


class TestRepositoryUpdateMethodologyRetrieval:
    """update_methodology_retrieval() increments retrieval_count and sets last_retrieved_at."""

    async def test_increments_retrieval_count(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(source_task_id=task.id)
        await repository.save_methodology(m)

        await repository.update_methodology_retrieval(m.id)
        got = await repository.get_methodology(m.id)
        assert got.retrieval_count == 1

        await repository.update_methodology_retrieval(m.id)
        got = await repository.get_methodology(m.id)
        assert got.retrieval_count == 2

    async def test_sets_last_retrieved_at(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(source_task_id=task.id)
        await repository.save_methodology(m)

        before = datetime.now(UTC)
        await repository.update_methodology_retrieval(m.id)
        got = await repository.get_methodology(m.id)

        assert got.last_retrieved_at is not None


class TestRepositoryUpdateMethodologyOutcome:
    """update_methodology_outcome() increments success/failure counts."""

    async def test_success_increments_success_count(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(source_task_id=task.id)
        await repository.save_methodology(m)

        await repository.update_methodology_outcome(m.id, success=True)
        got = await repository.get_methodology(m.id)
        assert got.success_count == 1
        assert got.failure_count == 0

    async def test_failure_increments_failure_count(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(source_task_id=task.id)
        await repository.save_methodology(m)

        await repository.update_methodology_outcome(m.id, success=False)
        got = await repository.get_methodology(m.id)
        assert got.success_count == 0
        assert got.failure_count == 1

    async def test_mixed_outcomes(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(source_task_id=task.id)
        await repository.save_methodology(m)

        await repository.update_methodology_outcome(m.id, success=True)
        await repository.update_methodology_outcome(m.id, success=True)
        await repository.update_methodology_outcome(m.id, success=False)

        got = await repository.get_methodology(m.id)
        assert got.success_count == 2
        assert got.failure_count == 1


class TestRepositoryUpdateMethodologyFitness:
    """update_methodology_fitness() updates the fitness_vector JSON."""

    async def test_updates_fitness_vector(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(source_task_id=task.id)
        await repository.save_methodology(m)

        new_fitness = {"accuracy": 0.95, "speed": 0.8, "coverage": 0.7}
        await repository.update_methodology_fitness(m.id, new_fitness)

        got = await repository.get_methodology(m.id)
        assert got.fitness_vector == new_fitness

    async def test_overwrites_previous_fitness(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(source_task_id=task.id)
        await repository.save_methodology(m)

        await repository.update_methodology_fitness(m.id, {"a": 0.5})
        await repository.update_methodology_fitness(m.id, {"b": 0.9})

        got = await repository.get_methodology(m.id)
        assert got.fitness_vector == {"b": 0.9}
        assert "a" not in got.fitness_vector


class TestRepositoryUpsertMethodologyLink:
    """upsert_methodology_link() creates or updates co-retrieval links."""

    async def test_creates_new_link(self, repository):
        project, task = await _setup_project_and_task(repository)
        m1 = _make_methodology(source_task_id=task.id, problem_description="Problem A")
        m2 = _make_methodology(source_task_id=task.id, problem_description="Problem B")
        await repository.save_methodology(m1)
        await repository.save_methodology(m2)

        await repository.upsert_methodology_link(m1.id, m2.id, strength=1.0)

        links = await repository.get_methodology_links(m1.id)
        assert len(links) >= 1
        link = links[0]
        assert link["source_id"] == m1.id
        assert link["target_id"] == m2.id
        assert link["strength"] == 1.0

    async def test_upsert_increments_strength(self, repository):
        project, task = await _setup_project_and_task(repository)
        m1 = _make_methodology(source_task_id=task.id, problem_description="A")
        m2 = _make_methodology(source_task_id=task.id, problem_description="B")
        await repository.save_methodology(m1)
        await repository.save_methodology(m2)

        await repository.upsert_methodology_link(m1.id, m2.id, strength=1.0)
        await repository.upsert_methodology_link(m1.id, m2.id, strength=2.0)

        links = await repository.get_methodology_links(m1.id)
        assert len(links) == 1
        assert links[0]["strength"] == 3.0  # 1.0 + 2.0

    async def test_bidirectional_retrieval(self, repository):
        project, task = await _setup_project_and_task(repository)
        m1 = _make_methodology(source_task_id=task.id, problem_description="X")
        m2 = _make_methodology(source_task_id=task.id, problem_description="Y")
        await repository.save_methodology(m1)
        await repository.save_methodology(m2)

        await repository.upsert_methodology_link(m1.id, m2.id, strength=1.0)

        # Retrievable from target side too
        links_from_m2 = await repository.get_methodology_links(m2.id)
        assert len(links_from_m2) >= 1


class TestRepositoryGetMethodology:
    """get_methodology() returns a single methodology by ID."""

    async def test_returns_existing_methodology(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(
            source_task_id=task.id,
            problem_description="Specific problem",
            solution_code="specific_fix()",
            tags=["auth", "security"],
            language="python",
        )
        await repository.save_methodology(m)

        got = await repository.get_methodology(m.id)
        assert got is not None
        assert got.id == m.id
        assert got.problem_description == "Specific problem"
        assert got.solution_code == "specific_fix()"
        assert got.tags == ["auth", "security"]
        assert got.language == "python"

    async def test_returns_none_for_nonexistent(self, repository):
        got = await repository.get_methodology("nonexistent-id-12345")
        assert got is None


class TestRepositoryFindSimilarMethodologies:
    """find_similar_methodologies() uses sqlite-vec for vector similarity search."""

    async def test_finds_similar_embedding(self, repository):
        project, task = await _setup_project_and_task(repository)
        embedding = [0.3] * 384
        m = _make_methodology(
            source_task_id=task.id,
            problem_description="Connection pool leak",
            problem_embedding=embedding,
        )
        await repository.save_methodology(m)

        results = await repository.find_similar_methodologies([0.3] * 384, limit=3)
        assert len(results) >= 1
        methodology, similarity = results[0]
        assert methodology.id == m.id
        assert similarity > 0.99  # Identical vectors

    async def test_respects_limit(self, repository):
        project, task = await _setup_project_and_task(repository)
        for i in range(5):
            embedding = [0.1 * (i + 1)] * 384
            m = _make_methodology(
                source_task_id=task.id,
                problem_description=f"Problem {i}",
                problem_embedding=embedding,
            )
            await repository.save_methodology(m)

        results = await repository.find_similar_methodologies([0.1] * 384, limit=2)
        assert len(results) <= 2

    async def test_returns_empty_when_no_embeddings(self, repository):
        project, task = await _setup_project_and_task(repository)
        m = _make_methodology(
            source_task_id=task.id,
            problem_description="No embedding set",
            problem_embedding=None,
        )
        await repository.save_methodology(m)

        results = await repository.find_similar_methodologies([0.5] * 384, limit=3)
        # The methodology without an embedding should not appear
        assert len(results) == 0


class TestRepositoryUpdateTaskAgent:
    """update_task_agent() sets assigned_agent on a task."""

    async def test_assigns_agent(self, repository):
        project, task = await _setup_project_and_task(repository)

        await repository.update_task_agent(task.id, "claude")
        got = await repository.get_task(task.id)
        assert got.assigned_agent == "claude"

    async def test_reassigns_agent(self, repository):
        project, task = await _setup_project_and_task(repository)

        await repository.update_task_agent(task.id, "claude")
        await repository.update_task_agent(task.id, "codex")
        got = await repository.get_task(task.id)
        assert got.assigned_agent == "codex"


class TestRepositoryGetFailedApproaches:
    """get_failed_approaches() returns hypothesis entries with FAILURE outcome."""

    async def test_returns_failures_only(self, repository):
        project, task = await _setup_project_and_task(repository)

        success = HypothesisEntry(
            task_id=task.id,
            attempt_number=1,
            approach_summary="Successful approach",
            outcome=HypothesisOutcome.SUCCESS,
            agent_id="claude",
        )
        failure = HypothesisEntry(
            task_id=task.id,
            attempt_number=2,
            approach_summary="Failed approach",
            outcome=HypothesisOutcome.FAILURE,
            error_signature="TypeError",
            agent_id="codex",
        )
        await repository.log_hypothesis(success)
        await repository.log_hypothesis(failure)

        failed = await repository.get_failed_approaches(task.id)
        assert len(failed) == 1
        assert failed[0].approach_summary == "Failed approach"
        assert failed[0].outcome == HypothesisOutcome.FAILURE

    async def test_returns_empty_when_no_failures(self, repository):
        project, task = await _setup_project_and_task(repository)

        success = HypothesisEntry(
            task_id=task.id,
            attempt_number=1,
            approach_summary="Worked",
            outcome=HypothesisOutcome.SUCCESS,
        )
        await repository.log_hypothesis(success)

        failed = await repository.get_failed_approaches(task.id)
        assert failed == []

    async def test_orders_by_attempt_number(self, repository):
        project, task = await _setup_project_and_task(repository)

        for i in [3, 1, 2]:
            h = HypothesisEntry(
                task_id=task.id,
                attempt_number=i,
                approach_summary=f"Attempt {i}",
                outcome=HypothesisOutcome.FAILURE,
                error_signature=f"Error{i}",
            )
            await repository.log_hypothesis(h)

        failed = await repository.get_failed_approaches(task.id)
        assert len(failed) == 3
        assert [f.attempt_number for f in failed] == [1, 2, 3]


class TestRepositoryGetNextHypothesisAttempt:
    """get_next_hypothesis_attempt() returns the next attempt number."""

    async def test_first_attempt(self, repository):
        project, task = await _setup_project_and_task(repository)

        next_attempt = await repository.get_next_hypothesis_attempt(task.id)
        assert next_attempt == 1

    async def test_after_one_hypothesis(self, repository):
        project, task = await _setup_project_and_task(repository)
        h = HypothesisEntry(
            task_id=task.id,
            attempt_number=1,
            approach_summary="First try",
            outcome=HypothesisOutcome.FAILURE,
        )
        await repository.log_hypothesis(h)

        next_attempt = await repository.get_next_hypothesis_attempt(task.id)
        assert next_attempt == 2

    async def test_after_multiple_hypotheses(self, repository):
        project, task = await _setup_project_and_task(repository)
        for i in range(1, 4):
            h = HypothesisEntry(
                task_id=task.id,
                attempt_number=i,
                approach_summary=f"Attempt {i}",
                outcome=HypothesisOutcome.FAILURE,
            )
            await repository.log_hypothesis(h)

        next_attempt = await repository.get_next_hypothesis_attempt(task.id)
        assert next_attempt == 4


class TestRepositoryIncrementTaskAttempt:
    """increment_task_attempt() increments the attempt_count field."""

    async def test_increments_from_zero(self, repository):
        project, task = await _setup_project_and_task(repository)

        await repository.increment_task_attempt(task.id)
        got = await repository.get_task(task.id)
        assert got.attempt_count == 1

    async def test_increments_multiple_times(self, repository):
        project, task = await _setup_project_and_task(repository)

        await repository.increment_task_attempt(task.id)
        await repository.increment_task_attempt(task.id)
        await repository.increment_task_attempt(task.id)
        got = await repository.get_task(task.id)
        assert got.attempt_count == 3


class TestRepositoryIncrementTaskEscalation:
    """increment_task_escalation() increments escalation_count."""

    async def test_increments_escalation(self, repository):
        project, task = await _setup_project_and_task(repository)

        await repository.increment_task_escalation(task.id)
        got = await repository.get_task(task.id)
        assert got.escalation_count == 1

    async def test_increments_escalation_multiple_times(self, repository):
        project, task = await _setup_project_and_task(repository)

        await repository.increment_task_escalation(task.id)
        await repository.increment_task_escalation(task.id)
        got = await repository.get_task(task.id)
        assert got.escalation_count == 2


# ============================================================================
# 2. Cycle — MicroClaw full pipeline
# ============================================================================


class TestMicroClawFullCycleSuccess:
    """Full MicroClaw cycle with a TestAgent that succeeds."""

    async def test_grab_returns_pending_task(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)
        ctx.agents["test"] = LocalAgent(should_succeed=True)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()

        assert grabbed is not None
        assert grabbed.id == task.id
        assert grabbed.title == task.title

    async def test_evaluate_sets_evaluating_status(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)
        ctx.agents["test"] = LocalAgent(should_succeed=True)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)

        db_task = await ctx.repository.get_task(task.id)
        assert db_task.status == TaskStatus.EVALUATING
        assert task_ctx.task.id == task.id
        assert isinstance(task_ctx.forbidden_approaches, list)

    async def test_evaluate_includes_forbidden_approaches(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)
        ctx.agents["test"] = LocalAgent(should_succeed=True)

        # Insert a failed approach first
        h = HypothesisEntry(
            task_id=task.id,
            attempt_number=1,
            approach_summary="Bad approach that failed",
            outcome=HypothesisOutcome.FAILURE,
            error_signature="ImportError",
        )
        await ctx.repository.log_hypothesis(h)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)

        assert len(task_ctx.forbidden_approaches) == 1
        assert "Bad approach that failed" in task_ctx.forbidden_approaches

    async def test_decide_routes_to_test_agent(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)
        ctx.agents["test"] = LocalAgent(should_succeed=True)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        agent_id, decided_ctx = await micro.decide(task_ctx)

        assert agent_id == "test"
        db_task = await ctx.repository.get_task(task.id)
        assert db_task.status == TaskStatus.DISPATCHED
        assert db_task.assigned_agent == "test"

    async def test_decide_uses_recommended_agent(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(
            ctx.repository, recommended_agent="test"
        )
        ctx.agents["test"] = LocalAgent(should_succeed=True)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        agent_id, _ = await micro.decide(task_ctx)

        assert agent_id == "test"

    async def test_act_executes_agent_and_returns_outcome(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)
        agent = LocalAgent(should_succeed=True)
        ctx.agents["test"] = agent

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        decision = await micro.decide(task_ctx)
        agent_id, act_ctx, outcome = await micro.act(decision)

        assert agent_id == "test"
        assert outcome.tests_passed is True
        assert "src/test.py" in outcome.files_changed
        assert agent.execute_call_count == 1

        db_task = await ctx.repository.get_task(task.id)
        assert db_task.status == TaskStatus.CODING
        assert db_task.attempt_count == 1

    async def test_verify_approves_successful_outcome(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)
        ctx.agents["test"] = LocalAgent(should_succeed=True)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        decision = await micro.decide(task_ctx)
        result = await micro.act(decision)
        verified = await micro.verify(result)

        agent_id, v_ctx, outcome, verification = verified
        assert verification.approved is True
        assert len(verification.violations) == 0
        assert verification.quality_score == 1.0

    async def test_learn_completes_task_on_success(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)
        ctx.agents["test"] = LocalAgent(should_succeed=True)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        decision = await micro.decide(task_ctx)
        result = await micro.act(decision)
        verified = await micro.verify(result)
        await micro.learn(verified)

        db_task = await ctx.repository.get_task(task.id)
        assert db_task.status == TaskStatus.DONE

        # Hypothesis was logged
        hypotheses = await ctx.repository.get_failed_approaches(task.id)
        assert len(hypotheses) == 0  # Only failures show up here

        # Agent score was updated
        scores = await ctx.repository.get_agent_scores("test")
        assert len(scores) == 1
        assert scores[0]["successes"] == 1

    async def test_run_cycle_end_to_end_success(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)
        ctx.agents["test"] = LocalAgent(should_succeed=True)

        micro = MicroClaw(ctx, project.id)
        cycle_result = await micro.run_cycle()

        assert cycle_result.success is True
        assert cycle_result.cycle_level == "micro"
        assert cycle_result.duration_seconds > 0

        db_task = await ctx.repository.get_task(task.id)
        assert db_task.status == TaskStatus.DONE


class TestMicroClawFailurePath:
    """MicroClaw cycle when the agent fails."""

    async def test_act_returns_failure_outcome(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)
        ctx.agents["test"] = LocalAgent(should_succeed=False)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        decision = await micro.decide(task_ctx)
        agent_id, act_ctx, outcome = await micro.act(decision)

        assert outcome.tests_passed is False
        assert outcome.failure_reason == "test_failure"

    async def test_verify_rejects_failed_outcome(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)
        ctx.agents["test"] = LocalAgent(should_succeed=False)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        decision = await micro.decide(task_ctx)
        result = await micro.act(decision)
        verified = await micro.verify(result)

        _, _, _, verification = verified
        assert verification.approved is False
        assert len(verification.violations) > 0

    async def test_learn_resets_to_pending_on_failure(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)
        ctx.agents["test"] = LocalAgent(should_succeed=False)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        decision = await micro.decide(task_ctx)
        result = await micro.act(decision)
        verified = await micro.verify(result)
        await micro.learn(verified)

        db_task = await ctx.repository.get_task(task.id)
        assert db_task.status == TaskStatus.PENDING

        # Failure hypothesis logged
        failed = await ctx.repository.get_failed_approaches(task.id)
        assert len(failed) == 1
        assert failed[0].error_signature == "test_failure"

        # Agent score updated with failure
        scores = await ctx.repository.get_agent_scores("test")
        assert len(scores) == 1
        assert scores[0]["failures"] == 1

    async def test_run_cycle_end_to_end_failure(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)
        ctx.agents["test"] = LocalAgent(should_succeed=False)

        micro = MicroClaw(ctx, project.id)
        cycle_result = await micro.run_cycle()

        # Cycle still completes (returns True because it ran to completion)
        assert cycle_result.success is True
        assert cycle_result.cycle_level == "micro"

        # But task is reset to PENDING for retry
        db_task = await ctx.repository.get_task(task.id)
        assert db_task.status == TaskStatus.PENDING


class TestMicroClawNoAgents:
    """MicroClaw when no agents are available."""

    async def test_decide_returns_none_agent(self, claw_context):
        ctx = claw_context
        # No agents in context (default)
        project, task = await _setup_project_and_task(ctx.repository)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        agent_id, decided_ctx = await micro.decide(task_ctx)

        assert agent_id == "none"

    async def test_act_with_no_agent_returns_no_agent_outcome(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        decision = await micro.decide(task_ctx)
        agent_id, act_ctx, outcome = await micro.act(decision)

        assert agent_id == "none"
        assert outcome.failure_reason == "no_agent"


class TestMicroClawNoPendingTasks:
    """MicroClaw when no pending tasks exist."""

    async def test_grab_returns_none(self, claw_context):
        ctx = claw_context
        project = _make_project()
        await ctx.repository.create_project(project)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        assert grabbed is None

    async def test_run_cycle_returns_failure_when_no_tasks(self, claw_context):
        ctx = claw_context
        project = _make_project()
        await ctx.repository.create_project(project)

        micro = MicroClaw(ctx, project.id)
        cycle_result = await micro.run_cycle()

        assert cycle_result.success is False
        assert cycle_result.cycle_level == "micro"


class TestMicroClawVerifyPlaceholderDetection:
    """Verify step detects placeholder markers in output."""

    async def test_detects_todo_in_output(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)

        # Create a task context and outcome directly to test verify
        task_ctx = TaskContext(task=task, forbidden_approaches=[])
        outcome = TaskOutcome(
            agent_id="test",
            approach_summary="Added feature",
            raw_output="Implemented the feature. # TODO: add error handling",
            files_changed=["src/feature.py"],
            tests_passed=True,
        )

        micro = MicroClaw(ctx, project.id)
        micro._current_task = task
        verified = await micro.verify(("test", task_ctx, outcome))
        _, _, _, verification = verified

        assert verification.approved is False
        placeholder_violations = [
            v for v in verification.violations if v["check"] == "placeholder_scan"
        ]
        assert len(placeholder_violations) >= 1

    async def test_detects_fixme_in_output(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)

        task_ctx = TaskContext(task=task, forbidden_approaches=[])
        outcome = TaskOutcome(
            agent_id="test",
            approach_summary="Partial fix",
            raw_output="Fixed the main issue. FIXME: edge case not handled",
            files_changed=["src/fix.py"],
            tests_passed=True,
        )

        micro = MicroClaw(ctx, project.id)
        verified = await micro.verify(("test", task_ctx, outcome))
        _, _, _, verification = verified
        assert verification.approved is False

    async def test_detects_notimplementederror(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)

        task_ctx = TaskContext(task=task, forbidden_approaches=[])
        outcome = TaskOutcome(
            agent_id="test",
            approach_summary="Stub implementation",
            raw_output="raise NotImplementedError('pending')",
            files_changed=["src/stub.py"],
            tests_passed=True,
        )

        micro = MicroClaw(ctx, project.id)
        verified = await micro.verify(("test", task_ctx, outcome))
        _, _, _, verification = verified
        assert verification.approved is False

    async def test_clean_output_passes_verification(self, claw_context):
        ctx = claw_context
        project, task = await _setup_project_and_task(ctx.repository)

        task_ctx = TaskContext(task=task, forbidden_approaches=[])
        outcome = TaskOutcome(
            agent_id="test",
            approach_summary="Clean implementation",
            raw_output="All changes applied correctly. Tests passing.",
            files_changed=["src/clean.py"],
            tests_passed=True,
        )

        micro = MicroClaw(ctx, project.id)
        verified = await micro.verify(("test", task_ctx, outcome))
        _, _, _, verification = verified
        assert verification.approved is True
        assert verification.quality_score == 1.0


# ============================================================================
# 3. Adaptation — AdaptationSignals.from_task and _infer_task_type
# ============================================================================


class TestAdaptationSignalsFromTask:
    """AdaptationSignals.from_task() builds signals from a real Task + Repository."""

    async def test_basic_from_task(self, repository):
        project, task = await _setup_project_and_task(
            repository,
            task_title="Fix authentication bug",
            task_description="Fix the JWT token validation error in auth middleware",
            task_type="bug_fix",
        )

        signals = await AdaptationSignals.from_task(task, repository)

        assert isinstance(signals, AdaptationSignals)
        assert signals.attempt_number == task.attempt_count
        assert signals.escalation_count == task.escalation_count
        assert signals.past_failure_count == 0
        assert signals.task_type_hint == "bug_fix"

    async def test_from_task_with_past_failures(self, repository):
        project, task = await _setup_project_and_task(
            repository,
            task_title="Implement caching layer",
            task_description="Add Redis caching",
        )

        # Insert past failures
        for i in range(3):
            h = HypothesisEntry(
                task_id=task.id,
                attempt_number=i + 1,
                approach_summary=f"Failed approach {i}",
                outcome=HypothesisOutcome.FAILURE,
                error_signature=f"Error{i}",
            )
            await repository.log_hypothesis(h)

        signals = await AdaptationSignals.from_task(task, repository)
        assert signals.past_failure_count == 3

    async def test_from_task_complexity_scoring(self, repository):
        project, task = await _setup_project_and_task(
            repository,
            task_title="Fix typo in readme",
            task_description="correct a spelling error",
        )

        signals = await AdaptationSignals.from_task(task, repository)
        assert signals.complexity_tier == "TRIVIAL"

    async def test_from_task_high_complexity(self, repository):
        project, task = await _setup_project_and_task(
            repository,
            task_title="Refactor authentication system with encryption",
            task_description="Redesign the security architecture to support multi-tenant "
            "authorization with concurrent access and distributed locking",
        )

        signals = await AdaptationSignals.from_task(task, repository)
        assert signals.complexity_tier in ("HIGH", "VERY_HIGH")

    async def test_from_task_with_escalations(self, repository):
        project, task = await _setup_project_and_task(repository)
        await repository.increment_task_escalation(task.id)
        await repository.increment_task_escalation(task.id)

        # Re-fetch the task to get updated escalation_count
        refreshed_task = await repository.get_task(task.id)
        signals = await AdaptationSignals.from_task(refreshed_task, repository)
        assert signals.escalation_count == 2


class TestInferTaskType:
    """_infer_task_type() keyword classifier for task type hints."""

    def test_bug_fix_keywords(self):
        assert _infer_task_type("Fix login bug", "The login crashes when...") == "bug_fix"

    def test_error_keyword(self):
        assert _infer_task_type("Resolve error", "An error occurs during startup") == "bug_fix"

    def test_crash_keyword(self):
        assert _infer_task_type("App crash on load", "The application crashes") == "bug_fix"

    def test_feature_keywords(self):
        assert _infer_task_type("Add user profile", "Implement user profile page") == "feature"

    def test_create_keyword(self):
        assert _infer_task_type("Create new endpoint", "Build a REST endpoint") == "feature"

    def test_testing_keywords(self):
        assert _infer_task_type("Add test coverage", "Improve test coverage for auth module") == "testing"

    def test_coverage_keyword(self):
        assert _infer_task_type("Improve coverage", "Get coverage to 90%") == "testing"

    def test_refactor_keywords(self):
        assert _infer_task_type("Refactor database layer", "Reorganize the DB code") == "refactor"

    def test_cleanup_keyword(self):
        assert _infer_task_type("Code cleanup", "Clean up unused imports") == "refactor"

    def test_rename_keyword(self):
        assert _infer_task_type("Rename variables", "Use better variable names") == "refactor"

    def test_unknown_when_no_keywords(self):
        assert _infer_task_type("Something else entirely", "No relevant keywords here") == "unknown"

    def test_fix_takes_precedence_over_feature(self):
        # "fix" and "add" both present, but fix keywords checked first
        assert _infer_task_type("Fix and add feature", "Fix bug and add logging") == "bug_fix"

    def test_testing_takes_precedence_over_feature(self):
        # "add" and "test" both present, but testing checked before feature
        assert _infer_task_type("Add test suite", "Implement comprehensive tests") == "testing"


# ============================================================================
# 4. HealthMonitor — stuck tasks, cooldown, agent status
# ============================================================================


class TestHealthMonitorStuckTasks:
    """_check_stuck_tasks detects tasks in processing states too long."""

    async def test_no_stuck_tasks(self, repository):
        project, task = await _setup_project_and_task(repository)
        await repository.update_task_status(task.id, TaskStatus.CODING)

        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=repository,
            config=config,
            max_task_age_minutes=30,
        )

        check = await monitor._check_stuck_tasks()
        assert check.passed is True
        assert "No stuck tasks" in check.message

    async def test_detects_stuck_coding_task(self, repository, db_engine):
        project, task = await _setup_project_and_task(repository)
        await repository.update_task_status(task.id, TaskStatus.CODING)

        # Manually backdate the updated_at to simulate an old stuck task
        old_time = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
        await db_engine.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            [old_time, task.id],
        )

        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=repository,
            config=config,
            max_task_age_minutes=30,
        )

        check = await monitor._check_stuck_tasks()
        assert check.passed is False
        assert "stuck" in check.message.lower()
        assert check.remediation is not None

    async def test_detects_stuck_evaluating_task(self, repository, db_engine):
        project, task = await _setup_project_and_task(repository)
        await repository.update_task_status(task.id, TaskStatus.EVALUATING)

        old_time = (datetime.now(UTC) - timedelta(minutes=45)).isoformat()
        await db_engine.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            [old_time, task.id],
        )

        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=repository,
            config=config,
            max_task_age_minutes=30,
        )

        check = await monitor._check_stuck_tasks()
        assert check.passed is False

    async def test_ignores_recent_in_progress_task(self, repository):
        project, task = await _setup_project_and_task(repository)
        await repository.update_task_status(task.id, TaskStatus.CODING)

        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=repository,
            config=config,
            max_task_age_minutes=30,
        )

        check = await monitor._check_stuck_tasks()
        assert check.passed is True

    async def test_multiple_stuck_tasks(self, repository, db_engine):
        project = _make_project()
        await repository.create_project(project)

        t1 = _make_task(project.id, title="Stuck-1")
        t2 = _make_task(project.id, title="Stuck-2")
        await repository.create_task(t1)
        await repository.create_task(t2)

        await repository.update_task_status(t1.id, TaskStatus.CODING)
        await repository.update_task_status(t2.id, TaskStatus.REVIEWING)

        old_time = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
        await db_engine.execute(
            "UPDATE tasks SET updated_at = ? WHERE id IN (?, ?)",
            [old_time, t1.id, t2.id],
        )

        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=repository,
            config=config,
            max_task_age_minutes=30,
        )

        check = await monitor._check_stuck_tasks()
        assert check.passed is False
        assert "2 stuck" in check.message


class TestHealthMonitorCooldownDisplay:
    """Circuit breaker cooldown display and expiry in get_agent_status."""

    def test_circuit_open_shows_cooldown(self):
        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=None,  # Not used for circuit breaker tests
            config=config,
        )

        for _ in range(3):
            monitor.record_agent_failure("claude")

        status = monitor.get_agent_status()
        assert status["claude"]["circuit_open"] is True
        assert status["claude"]["cooldown_remaining_seconds"] is not None
        assert status["claude"]["cooldown_remaining_seconds"] > 0
        assert status["claude"]["circuit_until"] is not None

    def test_cooldown_expiry_resets_in_get_agent_status(self):
        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=None,
            config=config,
        )

        for _ in range(3):
            monitor.record_agent_failure("codex")

        # Manually expire the cooldown
        monitor._agent_circuit_until["codex"] = datetime.now(UTC) - timedelta(
            seconds=10
        )

        status = monitor.get_agent_status()
        assert status["codex"]["circuit_open"] is False
        assert status["codex"]["consecutive_failures"] == 0
        assert status["codex"]["cooldown_remaining_seconds"] is None

    def test_multiple_agents_tracked(self):
        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=None,
            config=config,
        )

        monitor.record_agent_failure("claude")
        monitor.record_agent_failure("codex")
        monitor.record_agent_failure("codex")

        for _ in range(3):
            monitor.record_agent_failure("grok")

        status = monitor.get_agent_status()
        assert "claude" in status
        assert "codex" in status
        assert "grok" in status

        assert status["claude"]["consecutive_failures"] == 1
        assert status["claude"]["circuit_open"] is False
        assert status["codex"]["consecutive_failures"] == 2
        assert status["codex"]["circuit_open"] is False
        assert status["grok"]["consecutive_failures"] == 3
        assert status["grok"]["circuit_open"] is True

    def test_success_after_circuit_open_resets(self):
        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=None,
            config=config,
        )

        for _ in range(3):
            monitor.record_agent_failure("gemini")

        assert monitor.is_agent_circuit_open("gemini") is True

        monitor.record_agent_success("gemini")
        assert monitor.is_agent_circuit_open("gemini") is False

        status = monitor.get_agent_status()
        assert status["gemini"]["consecutive_failures"] == 0
        assert status["gemini"]["circuit_open"] is False


class TestHealthMonitorTokenBudget:
    """check_token_budget both pass and fail scenarios."""

    def test_well_under_budget(self):
        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=None,
            config=config,
            max_tokens_per_task=100_000,
        )
        check = monitor.check_token_budget(10_000)
        assert check.passed is True
        assert "10000/100000" in check.message

    def test_at_budget_limit(self):
        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=None,
            config=config,
            max_tokens_per_task=50_000,
        )
        check = monitor.check_token_budget(50_000)
        assert check.passed is True

    def test_over_budget(self):
        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=None,
            config=config,
            max_tokens_per_task=50_000,
        )
        check = monitor.check_token_budget(50_001)
        assert check.passed is False
        assert "exceeded" in check.message.lower()
        assert check.remediation is not None

    def test_zero_tokens_passes(self):
        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=None,
            config=config,
            max_tokens_per_task=100_000,
        )
        check = monitor.check_token_budget(0)
        assert check.passed is True


class TestHealthMonitorRunChecks:
    """run_checks() integration with stuck tasks and circuit breakers."""

    async def test_run_checks_all_pass(self, repository):
        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=repository,
            config=config,
        )
        checks = await monitor.run_checks()
        assert len(checks) >= 1
        assert all(c.passed for c in checks)

    async def test_run_checks_includes_circuit_breaker(self, repository):
        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=repository,
            config=config,
        )

        for _ in range(3):
            monitor.record_agent_failure("claude")

        checks = await monitor.run_checks()
        circuit_checks = [
            c for c in checks if "circuit_breaker:claude" in c.check_name
        ]
        assert len(circuit_checks) == 1
        assert circuit_checks[0].passed is False

    async def test_run_checks_with_stuck_task(self, repository, db_engine):
        project, task = await _setup_project_and_task(repository)
        await repository.update_task_status(task.id, TaskStatus.DISPATCHED)

        old_time = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
        await db_engine.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            [old_time, task.id],
        )

        config = OrchestratorConfig()
        monitor = HealthMonitor(
            repository=repository,
            config=config,
            max_task_age_minutes=30,
        )

        checks = await monitor.run_checks()
        stuck_checks = [c for c in checks if c.check_name == "stuck_tasks"]
        assert len(stuck_checks) == 1
        assert stuck_checks[0].passed is False


class TestHealthMonitorIsAgentCircuitOpen:
    """is_agent_circuit_open() with auto-reset on cooldown expiry."""

    def test_unknown_agent_is_closed(self):
        config = OrchestratorConfig()
        monitor = HealthMonitor(repository=None, config=config)
        assert monitor.is_agent_circuit_open("nonexistent") is False

    def test_auto_resets_after_cooldown(self):
        config = OrchestratorConfig()
        monitor = HealthMonitor(repository=None, config=config)

        for _ in range(3):
            monitor.record_agent_failure("claude")

        assert monitor.is_agent_circuit_open("claude") is True

        # Manually expire
        monitor._agent_circuit_until["claude"] = datetime.now(UTC) - timedelta(
            seconds=1
        )

        assert monitor.is_agent_circuit_open("claude") is False
        # Internal state should be cleaned up
        assert monitor._agent_failures["claude"] == 0
        assert monitor._agent_circuit_open["claude"] is False


class TestHealthMonitorCircuitBreakerCooldownCalculation:
    """Cooldown uses exponential backoff: 30s * failure_count, capped at 300s."""

    def test_cooldown_at_threshold(self):
        config = OrchestratorConfig()
        monitor = HealthMonitor(repository=None, config=config)

        for _ in range(3):
            monitor.record_agent_failure("test_agent")

        # Cooldown should be 30 * 3 = 90 seconds
        circuit_until = monitor._agent_circuit_until["test_agent"]
        assert circuit_until is not None
        expected_until = datetime.now(UTC) + timedelta(seconds=90)
        # Allow 5 second tolerance
        assert abs((circuit_until - expected_until).total_seconds()) < 5

    def test_cooldown_cap_at_300s(self):
        config = OrchestratorConfig()
        monitor = HealthMonitor(repository=None, config=config)

        # 11 failures would be 30 * 11 = 330, but cap is 300
        for _ in range(11):
            monitor.record_agent_failure("test_agent")
            # Reset the circuit after each set of 3 to keep going
            if monitor.is_agent_circuit_open("test_agent"):
                monitor._agent_circuit_open["test_agent"] = False

        # Now trigger one more to open circuit at current failure count
        # The failure count is 11, but we need to let it open
        monitor._agent_circuit_open["test_agent"] = False
        monitor._agent_failures["test_agent"] = 10
        monitor.record_agent_failure("test_agent")

        circuit_until = monitor._agent_circuit_until.get("test_agent")
        if circuit_until:
            # 30 * 11 = 330, capped at 300
            expected_until = datetime.now(UTC) + timedelta(seconds=300)
            assert abs((circuit_until - expected_until).total_seconds()) < 5


class TestHealthCheckModel:
    """HealthCheck data model basic tests."""

    def test_passed_check(self):
        check = HealthCheck("test_check", passed=True, message="All good")
        assert check.check_name == "test_check"
        assert check.passed is True
        assert check.message == "All good"
        assert check.remediation is None

    def test_failed_check_with_remediation(self):
        check = HealthCheck(
            "test_check",
            passed=False,
            message="Something broke",
            remediation="Restart the service",
        )
        assert check.passed is False
        assert check.remediation == "Restart the service"


# ============================================================================
# 5. Repository — additional coverage for remaining methods
# ============================================================================

from claw.core.models import ContextSnapshot, PeerReview, TokenCostRecord


class TestRepositoryGetTasksByStatus:
    """get_tasks_by_status() filters tasks by project and status."""

    async def test_returns_matching_tasks(self, repository):
        project = _make_project()
        await repository.create_project(project)

        t1 = _make_task(project.id, title="T1", priority=3)
        t2 = _make_task(project.id, title="T2", priority=7)
        t3 = _make_task(project.id, title="T3", priority=5)
        await repository.create_task(t1)
        await repository.create_task(t2)
        await repository.create_task(t3)

        await repository.update_task_status(t1.id, TaskStatus.CODING)
        await repository.update_task_status(t2.id, TaskStatus.CODING)

        result = await repository.get_tasks_by_status(project.id, TaskStatus.CODING)
        assert len(result) == 2
        # Ordered by priority DESC
        assert result[0].priority >= result[1].priority

    async def test_returns_empty_for_no_matching_status(self, repository):
        project = _make_project()
        await repository.create_project(project)
        t = _make_task(project.id)
        await repository.create_task(t)

        result = await repository.get_tasks_by_status(project.id, TaskStatus.DONE)
        assert result == []


class TestRepositoryListTasks:
    """list_tasks() returns tasks for a project with optional filtering."""

    async def test_includes_done_by_default(self, repository):
        project = _make_project()
        await repository.create_project(project)

        t1 = _make_task(project.id, title="Pending")
        t2 = _make_task(project.id, title="Done")
        await repository.create_task(t1)
        await repository.create_task(t2)
        await repository.update_task_status(t2.id, TaskStatus.DONE)

        result = await repository.list_tasks(project.id)
        assert len(result) == 2

    async def test_excludes_done_when_requested(self, repository):
        project = _make_project()
        await repository.create_project(project)

        t1 = _make_task(project.id, title="Pending")
        t2 = _make_task(project.id, title="Done")
        await repository.create_task(t1)
        await repository.create_task(t2)
        await repository.update_task_status(t2.id, TaskStatus.DONE)

        result = await repository.list_tasks(project.id, include_done=False)
        assert len(result) == 1
        assert result[0].title == "Pending"


class TestRepositoryGetHypothesisCount:
    """get_hypothesis_count() counts all hypotheses for a task."""

    async def test_zero_count(self, repository):
        project, task = await _setup_project_and_task(repository)
        count = await repository.get_hypothesis_count(task.id)
        assert count == 0

    async def test_counts_all_outcomes(self, repository):
        project, task = await _setup_project_and_task(repository)

        h1 = HypothesisEntry(
            task_id=task.id, attempt_number=1,
            approach_summary="A1", outcome=HypothesisOutcome.SUCCESS,
        )
        h2 = HypothesisEntry(
            task_id=task.id, attempt_number=2,
            approach_summary="A2", outcome=HypothesisOutcome.FAILURE,
        )
        await repository.log_hypothesis(h1)
        await repository.log_hypothesis(h2)

        count = await repository.get_hypothesis_count(task.id)
        assert count == 2


class TestRepositoryCountErrorSignature:
    """count_error_signature() counts occurrences of a specific error."""

    async def test_zero_for_unseen_error(self, repository):
        project, task = await _setup_project_and_task(repository)
        count = await repository.count_error_signature(task.id, "SomeNewError")
        assert count == 0

    async def test_counts_matching_signatures(self, repository):
        project, task = await _setup_project_and_task(repository)

        for i in range(3):
            h = HypothesisEntry(
                task_id=task.id, attempt_number=i + 1,
                approach_summary=f"Attempt {i}",
                outcome=HypothesisOutcome.FAILURE,
                error_signature="ImportError",
            )
            await repository.log_hypothesis(h)

        # Add one with different signature
        h_other = HypothesisEntry(
            task_id=task.id, attempt_number=4,
            approach_summary="Attempt 4",
            outcome=HypothesisOutcome.FAILURE,
            error_signature="TypeError",
        )
        await repository.log_hypothesis(h_other)

        count = await repository.count_error_signature(task.id, "ImportError")
        assert count == 3


class TestRepositoryGetHypothesisErrorStats:
    """get_hypothesis_error_stats() aggregates error signature statistics."""

    async def test_returns_stats_globally(self, repository):
        project, task = await _setup_project_and_task(repository)

        for i, sig in enumerate(["ImportError", "ImportError", "TypeError"]):
            h = HypothesisEntry(
                task_id=task.id, attempt_number=i + 1,
                approach_summary="approach",
                outcome=HypothesisOutcome.FAILURE,
                error_signature=sig,
            )
            await repository.log_hypothesis(h)

        stats = await repository.get_hypothesis_error_stats()
        assert len(stats) >= 2
        sig_map = {s["error_signature"]: s["cnt"] for s in stats}
        assert sig_map["ImportError"] == 2
        assert sig_map["TypeError"] == 1

    async def test_returns_stats_by_project(self, repository):
        project, task = await _setup_project_and_task(repository)

        h = HypothesisEntry(
            task_id=task.id, attempt_number=1,
            approach_summary="approach",
            outcome=HypothesisOutcome.FAILURE,
            error_signature="ValueError",
        )
        await repository.log_hypothesis(h)

        stats = await repository.get_hypothesis_error_stats(project_id=project.id)
        assert len(stats) >= 1
        assert stats[0]["error_signature"] == "ValueError"

    async def test_excludes_null_signatures(self, repository):
        project, task = await _setup_project_and_task(repository)

        h = HypothesisEntry(
            task_id=task.id, attempt_number=1,
            approach_summary="approach",
            outcome=HypothesisOutcome.FAILURE,
            error_signature=None,
        )
        await repository.log_hypothesis(h)

        stats = await repository.get_hypothesis_error_stats()
        assert len(stats) == 0


class TestRepositoryPeerReviews:
    """save_peer_review() and get_peer_reviews() lifecycle."""

    async def test_save_and_retrieve_peer_review(self, repository):
        project, task = await _setup_project_and_task(repository)

        review = PeerReview(
            task_id=task.id,
            model_used="test-model",
            diagnosis="The code has a race condition in the worker pool",
            recommended_approach="Use asyncio.Lock instead of threading.Lock",
            reasoning="The async context requires async-compatible synchronization",
        )
        saved = await repository.save_peer_review(review)
        assert saved.id == review.id

        reviews = await repository.get_peer_reviews(task.id)
        assert len(reviews) == 1
        assert reviews[0].diagnosis == review.diagnosis
        assert reviews[0].recommended_approach == review.recommended_approach

    async def test_returns_empty_when_no_reviews(self, repository):
        project, task = await _setup_project_and_task(repository)
        reviews = await repository.get_peer_reviews(task.id)
        assert reviews == []

    async def test_multiple_reviews_ordered_by_created_at(self, repository):
        project, task = await _setup_project_and_task(repository)

        for i in range(3):
            r = PeerReview(
                task_id=task.id,
                model_used=f"model-{i}",
                diagnosis=f"Diagnosis {i}",
            )
            await repository.save_peer_review(r)

        reviews = await repository.get_peer_reviews(task.id)
        assert len(reviews) == 3


class TestRepositoryContextSnapshots:
    """save_context_snapshot() and get_latest_snapshot() lifecycle."""

    async def test_save_and_retrieve_snapshot(self, repository):
        project, task = await _setup_project_and_task(repository)

        snapshot = ContextSnapshot(
            task_id=task.id,
            attempt_number=1,
            git_ref="abc123def",
            file_manifest={"src/main.py": "a1b2c3", "tests/test.py": "d4e5f6"},
        )
        saved = await repository.save_context_snapshot(snapshot)
        assert saved.id == snapshot.id

        latest = await repository.get_latest_snapshot(task.id)
        assert latest is not None
        assert latest.git_ref == "abc123def"
        assert latest.file_manifest == {"src/main.py": "a1b2c3", "tests/test.py": "d4e5f6"}

    async def test_returns_latest_by_attempt_number(self, repository):
        project, task = await _setup_project_and_task(repository)

        s1 = ContextSnapshot(
            task_id=task.id, attempt_number=1, git_ref="ref1",
        )
        s2 = ContextSnapshot(
            task_id=task.id, attempt_number=3, git_ref="ref3",
        )
        s3 = ContextSnapshot(
            task_id=task.id, attempt_number=2, git_ref="ref2",
        )
        await repository.save_context_snapshot(s1)
        await repository.save_context_snapshot(s2)
        await repository.save_context_snapshot(s3)

        latest = await repository.get_latest_snapshot(task.id)
        assert latest.git_ref == "ref3"
        assert latest.attempt_number == 3

    async def test_returns_none_when_no_snapshots(self, repository):
        project, task = await _setup_project_and_task(repository)
        latest = await repository.get_latest_snapshot(task.id)
        assert latest is None

    async def test_snapshot_with_no_manifest(self, repository):
        project, task = await _setup_project_and_task(repository)

        snapshot = ContextSnapshot(
            task_id=task.id, attempt_number=1, git_ref="deadbeef",
            file_manifest=None,
        )
        await repository.save_context_snapshot(snapshot)

        latest = await repository.get_latest_snapshot(task.id)
        assert latest is not None
        assert latest.file_manifest is None


class TestRepositoryTokenCostSummaryByTask:
    """get_token_cost_summary() with task_id filter."""

    async def test_summary_for_specific_task(self, repository):
        project, task = await _setup_project_and_task(repository)
        # Create a second task for the unrelated cost record (FK constraint)
        other_task = _make_task(project.id, title="Other task")
        await repository.create_task(other_task)

        tc1 = TokenCostRecord(
            task_id=task.id, agent_id="claude", model_used="model-a",
            input_tokens=1000, output_tokens=500, total_tokens=1500,
            cost_usd=0.05,
        )
        tc2 = TokenCostRecord(
            task_id=task.id, agent_id="codex", model_used="model-b",
            input_tokens=2000, output_tokens=800, total_tokens=2800,
            cost_usd=0.08,
        )
        # Unrelated task cost (different task)
        tc3 = TokenCostRecord(
            task_id=other_task.id, agent_id="claude", model_used="model-a",
            input_tokens=5000, output_tokens=3000, total_tokens=8000,
            cost_usd=0.50,
        )
        await repository.save_token_cost(tc1)
        await repository.save_token_cost(tc2)
        await repository.save_token_cost(tc3)

        summary = await repository.get_token_cost_summary(task_id=task.id)
        assert summary["calls"] == 2
        assert summary["input_tokens"] == 3000
        assert summary["output_tokens"] == 1300
        assert summary["total_tokens"] == 4300
        assert abs(summary["total_cost_usd"] - 0.13) < 0.001


class TestRepositorySavePromptVariant:
    """save_prompt_variant() persists prompt variants."""

    async def test_saves_and_returns_id(self, repository):
        variant_id = await repository.save_prompt_variant(
            prompt_name="deepdive",
            variant_label="v2-concise",
            content="Analyze the codebase deeply focusing on...",
            agent_id="claude",
            is_active=True,
        )
        assert variant_id is not None
        assert isinstance(variant_id, str)
        assert len(variant_id) > 0

    async def test_saves_inactive_variant(self, repository):
        variant_id = await repository.save_prompt_variant(
            prompt_name="claim-gate",
            variant_label="v1-strict",
            content="Verify every claim with evidence...",
            is_active=False,
        )
        assert variant_id is not None


class TestRepositoryGetFleetRepos:
    """get_fleet_repos() queries the fleet_repos table."""

    async def test_returns_empty_when_no_repos(self, repository):
        repos = await repository.get_fleet_repos()
        assert repos == []

    async def test_returns_all_repos(self, repository, db_engine):
        # Insert directly since there's no model method for fleet_repos insert
        await db_engine.execute(
            "INSERT INTO fleet_repos (id, repo_path, repo_name, priority, status) VALUES (?, ?, ?, ?, ?)",
            ["fr1", "/tmp/repo-a", "repo-a", 10, "pending"],
        )
        await db_engine.execute(
            "INSERT INTO fleet_repos (id, repo_path, repo_name, priority, status) VALUES (?, ?, ?, ?, ?)",
            ["fr2", "/tmp/repo-b", "repo-b", 5, "completed"],
        )

        repos = await repository.get_fleet_repos()
        assert len(repos) == 2
        # Ordered by priority DESC
        assert repos[0]["priority"] >= repos[1]["priority"]

    async def test_filters_by_status(self, repository, db_engine):
        await db_engine.execute(
            "INSERT INTO fleet_repos (id, repo_path, repo_name, priority, status) VALUES (?, ?, ?, ?, ?)",
            ["fr1", "/tmp/repo-a", "repo-a", 10, "pending"],
        )
        await db_engine.execute(
            "INSERT INTO fleet_repos (id, repo_path, repo_name, priority, status) VALUES (?, ?, ?, ?, ?)",
            ["fr2", "/tmp/repo-b", "repo-b", 5, "completed"],
        )

        pending = await repository.get_fleet_repos(status="pending")
        assert len(pending) == 1
        assert pending[0]["repo_name"] == "repo-a"


class TestRepositoryGetProject:
    """get_project() retrieves a project by ID."""

    async def test_returns_none_for_nonexistent(self, repository):
        result = await repository.get_project("nonexistent-project-id")
        assert result is None

    async def test_returns_project_with_all_fields(self, repository):
        project = Project(
            name="full-project",
            repo_path="/tmp/full-repo",
            tech_stack={"lang": "rust", "framework": "actix"},
            project_rules="No unsafe blocks",
            banned_dependencies=["libc"],
        )
        await repository.create_project(project)

        got = await repository.get_project(project.id)
        assert got is not None
        assert got.name == "full-project"
        assert got.tech_stack == {"lang": "rust", "framework": "actix"}
        assert got.project_rules == "No unsafe blocks"
        assert got.banned_dependencies == ["libc"]


class TestRepositoryLogEpisode:
    """log_episode() stores event data correctly."""

    async def test_log_episode_with_all_fields(self, repository):
        project = _make_project()
        await repository.create_project(project)

        ep_id = await repository.log_episode(
            session_id="session-123",
            event_type="cycle_started",
            event_data={"step": "grab", "priority": 10},
            project_id=project.id,
            agent_id="claude",
            task_id="task-abc",
            cycle_level="micro",
        )
        assert ep_id is not None
        assert isinstance(ep_id, str)
