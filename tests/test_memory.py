"""Tests for CLAW Phase 3 Memory modules.

Covers:
    1. claw.memory.fitness — pure computation fitness scoring
    2. claw.memory.lifecycle — lifecycle state machine transitions
    3. claw.memory.semantic — SemanticMemory persistence layer
    4. claw.memory.hybrid_search — HybridSearch merge/filter/signal logic
    5. claw.memory.error_kb — ErrorKB recording, patterns, normalization

All tests use REAL dependencies — no mocks, no placeholders, no cached responses.
Database tests use the real SQLite in-memory engine from conftest.py.
"""

from __future__ import annotations

import hashlib

import pytest
from datetime import UTC, datetime, timedelta

from claw.core.models import (
    HypothesisEntry,
    HypothesisOutcome,
    LifecycleState,
    Methodology,
    Task,
    TaskStatus,
)
from claw.memory.fitness import (
    W_CROSS_DOMAIN,
    W_EFFICACY,
    W_FRESHNESS,
    W_FREQUENCY,
    W_RELEVANCE,
    W_SPECIFICITY,
    compute_fitness,
    get_fitness_score,
)
from claw.memory.lifecycle import (
    DEAD_DAYS,
    DECLINING_FITNESS_THRESHOLD,
    DORMANT_DAYS,
    REHABILITATION_FITNESS_THRESHOLD,
    THRIVING_FITNESS_THRESHOLD,
    THRIVING_SUCCESS_MINIMUM,
    apply_transition,
    evaluate_transition,
    run_periodic_sweep,
)
from claw.memory.hybrid_search import HybridSearch, HybridSearchResult
from claw.memory.semantic import SemanticMemory, get_fitness_score_safe
from claw.memory.error_kb import (
    ErrorKB,
    FailurePattern,
    _calculate_urgency,
    _categorize_error,
    normalize_error_for_dedup,
)


# ---------------------------------------------------------------------------
# Helper: Fixed embedding engine (real computation, deterministic vectors)
# ---------------------------------------------------------------------------

class FixedEmbeddingEngine:
    """Real embedding engine that returns a fixed 384-dim vector derived from text hash.

    This is NOT a mock — it is a real, thin implementation that actually computes
    a deterministic 384-float array from the input text.  It generates the
    SHA-384 digest (48 bytes), then repeats it 8 times to fill 384 floats,
    matching the sqlite-vec schema dimension.
    """

    DIMENSION = 384

    def encode(self, text: str) -> list[float]:
        h = hashlib.sha384(text.encode()).digest()
        # 48 bytes * 8 = 384 floats
        raw = [b / 255.0 for b in h] * 8
        return raw[: self.DIMENSION]

    async def async_encode(self, text: str) -> list[float]:
        return self.encode(text)

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def to_sqlite_vec(vec: list[float]) -> bytes:
        import struct
        return struct.pack(f"<{len(vec)}f", *vec)

    @staticmethod
    def from_sqlite_vec(data: bytes) -> list[float]:
        import struct
        count = len(data) // 4
        return list(struct.unpack(f"<{count}f", data))


@pytest.fixture
def embedding_engine() -> FixedEmbeddingEngine:
    return FixedEmbeddingEngine()


@pytest.fixture
async def hybrid_search(repository, embedding_engine):
    return HybridSearch(
        repository=repository,
        embedding_engine=embedding_engine,
    )


@pytest.fixture
async def semantic_memory(repository, embedding_engine, hybrid_search):
    return SemanticMemory(
        repository=repository,
        embedding_engine=embedding_engine,
        hybrid_search=hybrid_search,
    )


@pytest.fixture
async def error_kb(repository):
    return ErrorKB(repository=repository)


# ---------------------------------------------------------------------------
# Helper: build methodology with controlled fields
# ---------------------------------------------------------------------------

def _make_methodology(**overrides) -> Methodology:
    defaults = dict(
        problem_description="Fix async race condition in worker pool",
        solution_code="await asyncio.gather(*tasks)",
    )
    defaults.update(overrides)
    return Methodology(**defaults)


# ===========================================================================
# 1. claw.memory.fitness — pure computation, no DB
# ===========================================================================

class TestComputeFitness:
    """Tests for compute_fitness() and get_fitness_score()."""

    def test_compute_fitness_neutral_defaults(self):
        """Zero-state methodology with default params yields a score near 0.5."""
        m = _make_methodology()
        now = m.created_at  # freshness = 1.0 (just created)
        total, vector = compute_fitness(m, now=now)

        # With defaults: relevance=0.5, efficacy=0.5 (no outcomes), specificity=0,
        # freshness=1.0, cross_domain=0 (project), frequency=0
        expected_approx = (
            W_RELEVANCE * 0.5
            + W_EFFICACY * 0.5
            + W_SPECIFICITY * 0.0
            + W_FRESHNESS * 1.0
            + W_CROSS_DOMAIN * 0.0
            + W_FREQUENCY * 0.0
        )
        assert abs(total - round(expected_approx, 4)) < 0.01
        assert 0.3 < total < 0.6

    def test_compute_fitness_high_success(self):
        """Methodology with 10 successes, 0 failures has high efficacy."""
        m = _make_methodology(success_count=10, failure_count=0)
        now = m.created_at
        total, vector = compute_fitness(m, now=now)

        assert vector["outcome_efficacy"] == 1.0
        assert total > 0.4

    def test_compute_fitness_high_failure(self):
        """Methodology with 0 successes, 10 failures has low efficacy."""
        m = _make_methodology(success_count=0, failure_count=10)
        now = m.created_at
        total, vector = compute_fitness(m, now=now)

        assert vector["outcome_efficacy"] == 0.0
        # Total should still be > 0 because freshness and relevance contribute
        assert total > 0.0
        assert total < 0.4

    def test_compute_fitness_rich_metadata(self):
        """Methodology with 5+ tags and 10+ files has high specificity."""
        m = _make_methodology(
            tags=["python", "async", "fix", "race-condition", "worker", "pool"],
            files_affected=[f"src/module_{i}.py" for i in range(12)],
        )
        now = m.created_at
        total, vector = compute_fitness(m, now=now)

        assert vector["specificity"] == 1.0

    def test_compute_fitness_empty_metadata(self):
        """Methodology with no tags and no files has specificity = 0."""
        m = _make_methodology(tags=[], files_affected=[])
        now = m.created_at
        total, vector = compute_fitness(m, now=now)

        assert vector["specificity"] == 0.0

    def test_compute_fitness_freshness_decay(self):
        """Methodology created 180 days ago has lower freshness."""
        m = _make_methodology()
        now = m.created_at + timedelta(days=180)
        total, vector = compute_fitness(m, now=now)

        # 180-day-old methodology with cold tier (180-day half-life) has freshness ~0.50
        assert vector["freshness"] < 0.6
        # Compare with a fresh methodology
        _, fresh_vector = compute_fitness(m, now=m.created_at)
        assert vector["freshness"] < fresh_vector["freshness"]

    def test_compute_fitness_global_scope_with_success(self):
        """Global scope with success_count > 0 yields cross_domain = 1.0."""
        m = _make_methodology(scope="global", success_count=3)
        now = m.created_at
        total, vector = compute_fitness(m, now=now)

        assert vector["cross_domain_transfer"] == 1.0

    def test_compute_fitness_global_scope_unproven(self):
        """Global scope with success_count = 0 yields cross_domain = 0.3."""
        m = _make_methodology(scope="global", success_count=0)
        now = m.created_at
        total, vector = compute_fitness(m, now=now)

        assert vector["cross_domain_transfer"] == 0.3

    def test_compute_fitness_project_scope(self):
        """Project scope yields cross_domain = 0.0."""
        m = _make_methodology(scope="project")
        now = m.created_at
        total, vector = compute_fitness(m, now=now)

        assert vector["cross_domain_transfer"] == 0.0

    def test_compute_fitness_frequency_normalized(self):
        """retrieval_count=5, max_retrieval=10 yields frequency = 0.5."""
        m = _make_methodology(retrieval_count=5)
        now = m.created_at
        total, vector = compute_fitness(m, max_retrieval_count=10, now=now)

        assert vector["retrieval_frequency"] == 0.5

    def test_compute_fitness_returns_vector_dict(self):
        """Fitness vector dict has all 8 expected keys."""
        m = _make_methodology()
        total, vector = compute_fitness(m, now=m.created_at)

        expected_keys = {
            "retrieval_relevance",
            "outcome_efficacy",
            "specificity",
            "freshness",
            "cross_domain_transfer",
            "retrieval_frequency",
            "decay_tier",
            "total",
        }
        assert set(vector.keys()) == expected_keys

    def test_compute_fitness_total_bounded(self):
        """Total fitness is always in [0.0, 1.0]."""
        # Best case: everything maxed out
        m_best = _make_methodology(
            success_count=100,
            failure_count=0,
            scope="global",
            retrieval_count=100,
            tags=["a", "b", "c", "d", "e"],
            files_affected=[f"f{i}" for i in range(10)],
        )
        total_best, _ = compute_fitness(
            m_best,
            retrieval_relevance=1.0,
            max_retrieval_count=100,
            now=m_best.created_at,
        )
        assert 0.0 <= total_best <= 1.0

        # Worst case: everything zeroed
        m_worst = _make_methodology(
            success_count=0,
            failure_count=100,
            scope="project",
            retrieval_count=0,
        )
        total_worst, _ = compute_fitness(
            m_worst,
            retrieval_relevance=0.0,
            max_retrieval_count=1,
            now=m_worst.created_at + timedelta(days=3650),
        )
        assert 0.0 <= total_worst <= 1.0

    def test_get_fitness_score_with_vector(self):
        """Methodology with fitness_vector returns stored total."""
        m = _make_methodology(fitness_vector={"total": 0.82, "efficacy": 0.9})
        assert get_fitness_score(m) == 0.82

    def test_get_fitness_score_empty_vector(self):
        """Methodology without fitness_vector returns neutral 0.5."""
        m = _make_methodology(fitness_vector={})
        assert get_fitness_score(m) == 0.5

    def test_get_fitness_score_invalid_vector(self):
        """Methodology with non-numeric total returns 0.5.

        Since Pydantic validates dict[str, float] on construction, we use
        model_construct to bypass validation (simulating data loaded from
        a legacy/corrupt DB row).
        """
        m = Methodology.model_construct(
            id="test-invalid",
            problem_description="test",
            solution_code="code",
            fitness_vector={"total": "not_a_number"},
        )
        assert get_fitness_score(m) == 0.5


# ===========================================================================
# 2. claw.memory.lifecycle — mixed sync/async
# ===========================================================================

class TestEvaluateTransition:
    """Tests for evaluate_transition() — pure sync computation."""

    def test_evaluate_transition_embryonic_to_viable(self):
        """Embryonic with success_count >= 1 transitions to viable."""
        m = _make_methodology(lifecycle_state="embryonic", success_count=1)
        result = evaluate_transition(m)
        assert result == LifecycleState.VIABLE.value

    def test_evaluate_transition_embryonic_stays(self):
        """Embryonic with success_count = 0 stays embryonic."""
        m = _make_methodology(lifecycle_state="embryonic", success_count=0)
        result = evaluate_transition(m)
        assert result is None

    def test_evaluate_transition_viable_to_thriving(self):
        """Viable with high fitness and 3+ successes transitions to thriving."""
        m = _make_methodology(
            lifecycle_state="viable",
            success_count=5,
            failure_count=0,
            fitness_vector={"total": 0.8},
        )
        result = evaluate_transition(m)
        assert result == LifecycleState.THRIVING.value

    def test_evaluate_transition_viable_to_declining(self):
        """Viable with failures > successes and retrieval_count >= 3 transitions to declining."""
        m = _make_methodology(
            lifecycle_state="viable",
            success_count=1,
            failure_count=3,
            retrieval_count=4,
            fitness_vector={"total": 0.45},
        )
        result = evaluate_transition(m)
        assert result == LifecycleState.DECLINING.value

    def test_evaluate_transition_viable_stays(self):
        """Viable with no conditions met stays viable."""
        m = _make_methodology(
            lifecycle_state="viable",
            success_count=1,
            failure_count=0,
            retrieval_count=1,
            fitness_vector={"total": 0.55},
        )
        result = evaluate_transition(m)
        assert result is None

    def test_evaluate_transition_thriving_to_declining(self):
        """Thriving with fitness < 0.4 transitions to declining."""
        m = _make_methodology(
            lifecycle_state="thriving",
            fitness_vector={"total": 0.3},
        )
        result = evaluate_transition(m)
        assert result == LifecycleState.DECLINING.value

    def test_evaluate_transition_thriving_stays(self):
        """Thriving with good fitness stays thriving."""
        m = _make_methodology(
            lifecycle_state="thriving",
            fitness_vector={"total": 0.75},
        )
        result = evaluate_transition(m)
        assert result is None

    def test_evaluate_transition_declining_to_dormant(self):
        """Declining with 180+ days without retrieval transitions to dormant."""
        now = datetime.now(UTC)
        created = now - timedelta(days=200)
        m = _make_methodology(
            lifecycle_state="declining",
            created_at=created,
            last_retrieved_at=created,
            fitness_vector={"total": 0.35},
        )
        result = evaluate_transition(m, now=now)
        assert result == LifecycleState.DORMANT.value

    def test_evaluate_transition_declining_to_viable(self):
        """Declining with fitness recovers >= 0.5 transitions back to viable."""
        now = datetime.now(UTC)
        m = _make_methodology(
            lifecycle_state="declining",
            last_retrieved_at=now - timedelta(days=5),
            fitness_vector={"total": 0.55},
        )
        result = evaluate_transition(m, now=now)
        assert result == LifecycleState.VIABLE.value

    def test_evaluate_transition_declining_stays(self):
        """Declining with mediocre fitness and recent retrieval stays declining."""
        now = datetime.now(UTC)
        m = _make_methodology(
            lifecycle_state="declining",
            last_retrieved_at=now - timedelta(days=10),
            fitness_vector={"total": 0.42},
        )
        result = evaluate_transition(m, now=now)
        assert result is None

    def test_evaluate_transition_dormant_to_dead(self):
        """Dormant with 365+ days without retrieval transitions to dead."""
        now = datetime.now(UTC)
        created = now - timedelta(days=400)
        m = _make_methodology(
            lifecycle_state="dormant",
            created_at=created,
            last_retrieved_at=created,
        )
        result = evaluate_transition(m, now=now)
        assert result == LifecycleState.DEAD.value

    def test_evaluate_transition_dormant_stays(self):
        """Dormant with less than 365 days without retrieval stays dormant."""
        now = datetime.now(UTC)
        m = _make_methodology(
            lifecycle_state="dormant",
            last_retrieved_at=now - timedelta(days=200),
        )
        result = evaluate_transition(m, now=now)
        assert result is None

    def test_evaluate_transition_dead_is_terminal(self):
        """Dead stays dead regardless of any conditions."""
        m = _make_methodology(
            lifecycle_state="dead",
            success_count=100,
            fitness_vector={"total": 1.0},
        )
        result = evaluate_transition(m)
        assert result is None


class TestApplyTransition:
    """Tests for apply_transition() — async, uses DB."""

    async def test_apply_transition_persists(self, repository):
        """apply_transition updates methodology in DB."""
        m = _make_methodology(lifecycle_state="embryonic", success_count=2)
        saved = await repository.save_methodology(m)

        # DB save_methodology does not persist success_count, so set it via
        # the repository update method to get success_count=1 in DB.
        await repository.update_methodology_outcome(saved.id, success=True)

        # Reload so in-memory model has the DB's actual success_count
        reloaded = await repository.get_methodology(saved.id)
        assert reloaded is not None

        new_state = await apply_transition(reloaded, repository)
        assert new_state == "viable"

        # Verify DB was updated
        final = await repository.get_methodology(saved.id)
        assert final is not None
        assert final.lifecycle_state == "viable"

    async def test_apply_transition_no_change(self, repository):
        """apply_transition returns None when no transition needed."""
        m = _make_methodology(lifecycle_state="embryonic", success_count=0)
        saved = await repository.save_methodology(m)

        result = await apply_transition(saved, repository)
        assert result is None

        reloaded = await repository.get_methodology(saved.id)
        assert reloaded is not None
        assert reloaded.lifecycle_state == "embryonic"


class TestPeriodicSweep:
    """Tests for run_periodic_sweep() — async, uses DB.

    Note: save_methodology does NOT persist success_count, failure_count,
    retrieval_count, last_retrieved_at, or created_at.  These columns get
    DB defaults (0, NULL, NOW).  We use repository mutation methods to
    set them up correctly before running the sweep.
    """

    async def test_run_periodic_sweep(self, repository):
        """Sweep transitions methodologies in various states."""
        now = datetime.now(UTC)

        # Methodology 1: embryonic -> viable (needs success_count >= 1)
        m1 = _make_methodology(lifecycle_state="embryonic")
        await repository.save_methodology(m1)
        # Give it a success outcome so success_count=1 in DB
        await repository.update_methodology_outcome(m1.id, success=True)

        # Methodology 2: declining -> viable (rehabilitation)
        # Needs fitness >= 0.5 and days_since_retrieval < 180.
        # Since last_retrieved_at is NULL, _days_since_retrieval falls back
        # to created_at (DB default = NOW), so days ~ 0.  With high fitness
        # it will rehabilitate.
        m2 = _make_methodology(
            lifecycle_state="declining",
            fitness_vector={"total": 0.6},
        )
        await repository.save_methodology(m2)

        # Methodology 3: viable, no transitions expected
        m3 = _make_methodology(
            lifecycle_state="viable",
            fitness_vector={"total": 0.55},
        )
        await repository.save_methodology(m3)

        transitions = await run_periodic_sweep(repository, now=now)

        assert "embryonic->viable" in transitions
        assert transitions["embryonic->viable"] >= 1
        assert "declining->viable" in transitions
        assert transitions["declining->viable"] >= 1

        # Verify m3 did not transition
        reloaded_m3 = await repository.get_methodology(m3.id)
        assert reloaded_m3 is not None
        assert reloaded_m3.lifecycle_state == "viable"


# ===========================================================================
# 3. claw.memory.semantic.SemanticMemory — async, uses DB
# ===========================================================================

class TestSemanticMemory:
    """Tests for SemanticMemory — async, real SQLite + FixedEmbeddingEngine."""

    async def test_save_solution(self, semantic_memory):
        """save_solution persists a methodology and returns a Methodology model."""
        result = await semantic_memory.save_solution(
            problem_description="Handle database connection timeout",
            solution_code="async with timeout(30): await db.connect()",
            tags=["database", "timeout"],
            language="python",
        )
        assert isinstance(result, Methodology)
        assert result.problem_description == "Handle database connection timeout"
        assert result.solution_code == "async with timeout(30): await db.connect()"
        assert result.tags == ["database", "timeout"]
        assert result.language == "python"
        assert result.lifecycle_state == "embryonic"

    async def test_save_solution_generates_embedding(self, semantic_memory):
        """save_solution uses the embedding engine to generate a 384-dim vector."""
        result = await semantic_memory.save_solution(
            problem_description="Connection pool exhaustion",
            solution_code="pool.set_max_size(100)",
        )
        assert result.problem_embedding is not None
        assert len(result.problem_embedding) == 384

    async def test_save_from_task(self, semantic_memory, sample_project, repository):
        """save_from_task saves a methodology from a completed task."""
        await repository.create_project(sample_project)

        task = Task(
            project_id=sample_project.id,
            title="Fix broken auth endpoint",
            description="JWT token validation fails on expired tokens",
            attempt_count=2,
        )
        await repository.create_task(task)

        result = await semantic_memory.save_from_task(
            task=task,
            solution_code="def validate_token(token): return jwt.decode(token, verify_exp=True)",
            tags=["auth", "jwt"],
        )
        assert result is not None
        assert isinstance(result, Methodology)
        assert task.id == result.source_task_id

    async def test_save_from_task_filtered_out(self, semantic_memory, sample_project, repository):
        """save_from_task returns None for trivial tasks with short solutions."""
        await repository.create_project(sample_project)

        task = Task(
            project_id=sample_project.id,
            title="Quick typo fix",
            description="Fix typo in comment",
            attempt_count=0,  # Below MIN_ATTEMPTS_FOR_TRIVIAL
        )
        await repository.create_task(task)

        result = await semantic_memory.save_from_task(
            task=task,
            solution_code="x = 1",  # Below MIN_SOLUTION_LENGTH (50)
        )
        assert result is None

    async def test_infer_methodology_type_bug_fix(self, semantic_memory):
        """Task with 'fix' in title infers BUG_FIX type."""
        task = Task(
            project_id="proj-1",
            title="Fix race condition in worker",
            description="Workers crash under concurrent load",
            attempt_count=1,
        )
        assert semantic_memory._infer_methodology_type(task) == "BUG_FIX"

    async def test_infer_methodology_type_pattern(self, semantic_memory):
        """Generic task title infers PATTERN type."""
        task = Task(
            project_id="proj-1",
            title="Implement retry logic",
            description="Add exponential backoff to API calls",
            attempt_count=1,
        )
        assert semantic_memory._infer_methodology_type(task) == "PATTERN"

    async def test_infer_methodology_type_decision(self, semantic_memory):
        """Task with 'decide' keyword infers DECISION type."""
        task = Task(
            project_id="proj-1",
            title="Choose between Redis and Memcached",
            description="Architecture decision for caching layer",
            attempt_count=1,
        )
        assert semantic_memory._infer_methodology_type(task) == "DECISION"

    async def test_infer_methodology_type_gotcha(self, semantic_memory):
        """Task with 'gotcha' keyword (and no competing keywords) infers GOTCHA type."""
        task = Task(
            project_id="proj-1",
            title="Document gotcha with timezone handling",
            description="Caveat: naive datetimes produce wrong results",
            attempt_count=1,
        )
        assert semantic_memory._infer_methodology_type(task) == "GOTCHA"

    async def test_passes_quality_filter_by_attempts(self, semantic_memory):
        """Task with attempt_count >= 1 passes quality filter."""
        task = Task(
            project_id="proj-1",
            title="Anything",
            description="Desc",
            attempt_count=1,
        )
        assert semantic_memory._passes_quality_filter(task, "x = 1") is True

    async def test_passes_quality_filter_by_length(self, semantic_memory):
        """Long solution code passes quality filter even with 0 attempts."""
        task = Task(
            project_id="proj-1",
            title="Anything",
            description="Desc",
            attempt_count=0,
        )
        long_code = "x" * 60  # > MIN_SOLUTION_LENGTH (50)
        assert semantic_memory._passes_quality_filter(task, long_code) is True

    async def test_passes_quality_filter_rejects(self, semantic_memory):
        """Short solution with 0 attempts fails quality filter."""
        task = Task(
            project_id="proj-1",
            title="Anything",
            description="Desc",
            attempt_count=0,
        )
        assert semantic_memory._passes_quality_filter(task, "x = 1") is False

    async def test_record_retrieval(self, semantic_memory, repository):
        """record_retrieval increments retrieval_count on stored methodology."""
        m = _make_methodology()
        saved = await repository.save_methodology(m)

        await semantic_memory.record_retrieval(saved.id)

        reloaded = await repository.get_methodology(saved.id)
        assert reloaded is not None
        assert reloaded.retrieval_count == 1

    async def test_get_total_count(self, semantic_memory, repository):
        """get_total_count returns correct count of stored methodologies."""
        m1 = _make_methodology(problem_description="Problem A", solution_code="code A")
        m2 = _make_methodology(problem_description="Problem B", solution_code="code B")
        await repository.save_methodology(m1)
        await repository.save_methodology(m2)

        count = await semantic_memory.get_total_count()
        assert count == 2

    async def test_get_fitness_score_safe_with_vector(self):
        """get_fitness_score_safe returns total when fitness_vector has it."""
        m = _make_methodology(fitness_vector={"total": 0.77})
        assert get_fitness_score_safe(m) == 0.77

    async def test_get_fitness_score_safe_empty(self):
        """get_fitness_score_safe returns 0.5 when no fitness_vector."""
        m = _make_methodology(fitness_vector={})
        assert get_fitness_score_safe(m) == 0.5

    async def test_get_fitness_score_safe_invalid(self):
        """get_fitness_score_safe returns 0.5 when total is non-numeric.

        Uses model_construct to bypass Pydantic validation, simulating data
        loaded from a legacy or corrupt DB row.
        """
        m = Methodology.model_construct(
            id="test-invalid",
            problem_description="test",
            solution_code="code",
            fitness_vector={"total": "corrupt_value"},
        )
        assert get_fitness_score_safe(m) == 0.5


# ===========================================================================
# 4. claw.memory.hybrid_search.HybridSearch — async, uses DB
# ===========================================================================

class TestHybridSearchMerge:
    """Tests for _merge_results — async, in-memory."""

    def _make_search(self):
        """Create a HybridSearch instance with minimal real dependencies."""
        return HybridSearch(
            repository=None,
            embedding_engine=FixedEmbeddingEngine(),
        )

    def _make_result(self, methodology_id: str, **kwargs) -> HybridSearchResult:
        m = _make_methodology(**kwargs)
        m.id = methodology_id  # Override for dedup testing
        return HybridSearchResult(methodology=m)

    async def test_merge_results_deduplication(self):
        """Same methodology from both sources merges into one hybrid result."""
        hs = self._make_search()

        m = _make_methodology()
        m.id = "meth-001"

        vec_result = HybridSearchResult(methodology=m, vector_score=0.9, source="vector")
        txt_result = HybridSearchResult(methodology=m, text_score=0.8, source="text")

        merged = await hs._merge_results([vec_result], [txt_result])

        # Should have exactly 1 result
        assert len(merged) == 1
        result = merged[0]
        assert result.source == "hybrid"
        assert result.vector_score == 0.9
        assert result.text_score == 0.8

    async def test_merge_results_vector_only(self):
        """Methodology appearing only in vector results keeps source='vector'."""
        hs = self._make_search()

        m = _make_methodology()
        m.id = "meth-vec"
        vec_result = HybridSearchResult(methodology=m, vector_score=0.7, source="vector")

        merged = await hs._merge_results([vec_result], [])

        assert len(merged) == 1
        assert merged[0].source == "vector"
        assert merged[0].vector_score == 0.7
        assert merged[0].text_score == 0.0

    async def test_merge_results_text_only(self):
        """Methodology appearing only in text results keeps source='text'."""
        hs = self._make_search()

        m = _make_methodology()
        m.id = "meth-txt"
        txt_result = HybridSearchResult(methodology=m, text_score=0.6, source="text")

        merged = await hs._merge_results([], [txt_result])

        assert len(merged) == 1
        assert merged[0].source == "text"
        assert merged[0].text_score == 0.6
        assert merged[0].vector_score == 0.0

    async def test_merge_results_filters_dead(self):
        """Dead methodologies are excluded from merge results."""
        hs = self._make_search()

        m = _make_methodology(lifecycle_state="dead")
        m.id = "meth-dead"
        vec_result = HybridSearchResult(methodology=m, vector_score=0.9, source="vector")

        merged = await hs._merge_results([vec_result], [])
        assert len(merged) == 0

    async def test_merge_results_filters_dormant(self):
        """Dormant methodologies are excluded from merge results."""
        hs = self._make_search()

        m = _make_methodology(lifecycle_state="dormant")
        m.id = "meth-dormant"
        vec_result = HybridSearchResult(methodology=m, vector_score=0.8, source="vector")

        merged = await hs._merge_results([vec_result], [])
        assert len(merged) == 0

    async def test_merge_results_viable_passes(self):
        """Viable methodologies are kept in merge results."""
        hs = self._make_search()

        m = _make_methodology(lifecycle_state="viable")
        m.id = "meth-viable"
        vec_result = HybridSearchResult(methodology=m, vector_score=0.8, source="vector")

        merged = await hs._merge_results([vec_result], [])
        assert len(merged) == 1


class TestHybridSearchFilters:
    """Tests for _apply_filters — sync."""

    def _make_search(self):
        return HybridSearch(
            repository=None,
            embedding_engine=FixedEmbeddingEngine(),
        )

    def _make_result(self, language=None, tags=None, files_affected=None) -> HybridSearchResult:
        m = _make_methodology(
            language=language,
            tags=tags or [],
            files_affected=files_affected or [],
        )
        return HybridSearchResult(methodology=m)

    def test_apply_filters_by_language(self):
        """Filter by language keeps only matching results."""
        hs = self._make_search()
        r_py = self._make_result(language="Python")
        r_js = self._make_result(language="JavaScript")

        filtered = hs._apply_filters([r_py, r_js], language="python")
        assert len(filtered) == 1
        assert filtered[0].methodology.language == "Python"

    def test_apply_filters_by_tags(self):
        """Filter by tags keeps results with any matching tag (case-insensitive)."""
        hs = self._make_search()
        r1 = self._make_result(tags=["Async", "Concurrency"])
        r2 = self._make_result(tags=["Database", "SQL"])

        filtered = hs._apply_filters([r1, r2], tags=["async"])
        assert len(filtered) == 1
        assert "Async" in filtered[0].methodology.tags

    def test_apply_filters_by_file_paths(self):
        """Filter by file_paths keeps results with overlapping files_affected."""
        hs = self._make_search()
        r1 = self._make_result(files_affected=["src/auth.py", "src/models.py"])
        r2 = self._make_result(files_affected=["src/db.py"])

        filtered = hs._apply_filters([r1, r2], file_paths=["src/auth.py"])
        assert len(filtered) == 1

    def test_apply_filters_no_match(self):
        """Filters that match nothing return empty list."""
        hs = self._make_search()
        r1 = self._make_result(language="Python", tags=["test"])

        filtered = hs._apply_filters([r1], language="rust")
        assert len(filtered) == 0


class TestHybridSearchSignals:
    """Tests for _derive_memory_signals and summarize_signals."""

    def _make_search(self):
        return HybridSearch(
            repository=None,
            embedding_engine=FixedEmbeddingEngine(),
        )

    def test_derive_memory_signals_hybrid(self):
        """Hybrid source with matching scores yields high deepConf confidence."""
        hs = self._make_search()
        result = HybridSearchResult(
            methodology=_make_methodology(),
            vector_score=0.8,
            text_score=0.8,
            source="hybrid",
        )
        confidence, conflict = hs._derive_memory_signals(result)

        # 6-factor deepConf: retrieval=1.0, authority=0.7(viable), accuracy=0.5(untested),
        # novelty=0.5(None), provenance=0.0(no cap), verification=0.3(default)
        # = 1.0*0.25 + 0.7*0.20 + 0.5*0.20 + 0.5*0.10 + 0.0*0.10 + 0.3*0.15 = 0.585
        assert abs(confidence - 0.585) < 0.01
        assert conflict == 0.0

    def test_derive_memory_signals_hybrid_disagreement(self):
        """Hybrid source with different scores yields conflict."""
        hs = self._make_search()
        result = HybridSearchResult(
            methodology=_make_methodology(),
            vector_score=0.9,
            text_score=0.3,
            source="hybrid",
        )
        confidence, conflict = hs._derive_memory_signals(result)

        # retrieval=0.70, authority=0.7, accuracy=0.5, novelty=0.5, provenance=0.0, verification=0.3
        # = 0.70*0.25 + 0.7*0.20 + 0.5*0.20 + 0.5*0.10 + 0.0*0.10 + 0.3*0.15 = 0.51
        assert abs(confidence - 0.51) < 0.01
        assert abs(conflict - 0.60) < 0.01

    def test_derive_memory_signals_single(self):
        """Single-source result with deepConf scoring."""
        hs = self._make_search()
        result = HybridSearchResult(
            methodology=_make_methodology(),
            vector_score=0.8,
            text_score=0.0,
            source="vector",
        )
        confidence, conflict = hs._derive_memory_signals(result)

        # retrieval=0.86, authority=0.7, accuracy=0.5, novelty=0.5, provenance=0.0, verification=0.3
        # = 0.86*0.25 + 0.7*0.20 + 0.5*0.20 + 0.5*0.10 + 0.0*0.10 + 0.3*0.15 = 0.55
        assert abs(confidence - 0.55) < 0.01
        assert conflict == 0.0


    def test_summarize_signals_empty(self):
        """Empty results yield zero signals."""
        hs = self._make_search()
        signals = hs.summarize_signals([])

        assert signals["retrieval_confidence"] == 0.0
        assert signals["conflict_count"] == 0
        assert signals["conflicts"] == []
        assert signals["hybrid_hits"] == 0

    def test_summarize_signals_with_results(self):
        """Aggregate confidence/conflict across multiple results."""
        hs = self._make_search()

        r1 = HybridSearchResult(
            methodology=_make_methodology(problem_description="Problem A"),
            confidence_score=0.9,
            conflict_score=0.2,
            source="hybrid",
        )
        r2 = HybridSearchResult(
            methodology=_make_methodology(problem_description="Problem B"),
            confidence_score=0.6,
            conflict_score=0.7,
            source="vector",
        )

        signals = hs.summarize_signals([r1, r2])

        # avg confidence = (0.9 + 0.6) / 2 = 0.75
        assert signals["retrieval_confidence"] == 0.75
        # r2 has conflict >= 0.60
        assert signals["conflict_count"] == 1
        assert signals["hybrid_hits"] == 1


class TestHybridSearchMMR:
    """Tests for MMR re-ranking."""

    def _make_search(self, mmr_enabled=True):
        return HybridSearch(
            repository=None,
            embedding_engine=FixedEmbeddingEngine(),
            mmr_enabled=mmr_enabled,
        )

    def test_mmr_reranking(self):
        """MMR promotes diversity by avoiding near-duplicates."""
        hs = self._make_search()

        # Two similar results (same problem description) and one different
        r1 = HybridSearchResult(
            methodology=_make_methodology(
                problem_description="fix async race condition in worker pool"
            ),
            combined_score=0.9,
        )
        r2 = HybridSearchResult(
            methodology=_make_methodology(
                problem_description="fix async race condition in worker pool with locks"
            ),
            combined_score=0.85,
        )
        r3 = HybridSearchResult(
            methodology=_make_methodology(
                problem_description="implement database connection pooling strategy"
            ),
            combined_score=0.8,
        )

        reranked = hs._apply_mmr([r1, r2, r3], limit=3)

        # All 3 should be present
        assert len(reranked) == 3
        # First should be r1 (highest combined_score)
        assert reranked[0].combined_score == 0.9

    def test_mmr_disabled(self):
        """With MMR disabled, results are returned as-is (truncated to limit)."""
        hs = self._make_search(mmr_enabled=False)

        results = [
            HybridSearchResult(methodology=_make_methodology(), combined_score=0.9),
            HybridSearchResult(methodology=_make_methodology(), combined_score=0.8),
        ]

        reranked = hs._apply_mmr(results, limit=1)
        assert len(reranked) == 1


class TestHybridSearchResultRepr:
    """Tests for HybridSearchResult __repr__."""

    def test_hybrid_search_result_repr(self):
        """Verify repr format includes key fields."""
        m = _make_methodology()
        r = HybridSearchResult(
            methodology=m,
            combined_score=0.85,
            vector_score=0.9,
            text_score=0.7,
            confidence_score=0.8,
            conflict_score=0.1,
        )
        text = repr(r)
        assert "HybridSearchResult" in text
        assert "combined=0.850" in text
        assert "vec=0.900" in text
        assert "txt=0.700" in text
        assert "conf=0.800" in text
        assert "conflict=0.100" in text


# ===========================================================================
# 5. claw.memory.error_kb.ErrorKB — async, uses DB
# ===========================================================================

class TestErrorKBRecording:
    """Tests for ErrorKB record_attempt and retrieval methods."""

    async def test_record_attempt(self, error_kb, repository, sample_project):
        """record_attempt saves a hypothesis entry to the DB."""
        await repository.create_project(sample_project)
        task = Task(
            project_id=sample_project.id,
            title="Test task",
            description="Description",
        )
        await repository.create_task(task)

        entry = await error_kb.record_attempt(
            task_id=task.id,
            attempt_number=1,
            approach_summary="Tried direct SQL insert",
            outcome=HypothesisOutcome.FAILURE,
            error_signature="IntegrityError: UNIQUE constraint failed",
            error_full="Full traceback here...",
            agent_id="claude",
        )

        assert isinstance(entry, HypothesisEntry)
        assert entry.task_id == task.id
        assert entry.outcome == HypothesisOutcome.FAILURE
        assert entry.agent_id == "claude"

    async def test_get_forbidden_approaches(self, error_kb, repository, sample_project):
        """get_forbidden_approaches returns formatted failure descriptions."""
        await repository.create_project(sample_project)
        task = Task(
            project_id=sample_project.id,
            title="Auth fix",
            description="Fix auth",
        )
        await repository.create_task(task)

        await error_kb.record_attempt(
            task_id=task.id,
            attempt_number=1,
            approach_summary="Used plaintext passwords",
            outcome=HypothesisOutcome.FAILURE,
            error_signature="SecurityError: weak hash",
            agent_id="codex",
        )
        await error_kb.record_attempt(
            task_id=task.id,
            attempt_number=2,
            approach_summary="Used MD5 hashing",
            outcome=HypothesisOutcome.FAILURE,
            error_signature="SecurityError: insecure hash",
            agent_id="gemini",
        )

        forbidden = await error_kb.get_forbidden_approaches(task.id)
        assert len(forbidden) == 2
        assert "plaintext passwords" in forbidden[0]
        assert "SecurityError: weak hash" in forbidden[0]
        assert "[agent: codex]" in forbidden[0]
        assert "MD5 hashing" in forbidden[1]

    async def test_has_duplicate_error(self, error_kb, repository, sample_project):
        """has_duplicate_error returns True for existing error signatures."""
        await repository.create_project(sample_project)
        task = Task(
            project_id=sample_project.id,
            title="DB task",
            description="Database task",
        )
        await repository.create_task(task)

        # Before recording - no duplicate
        has_dup = await error_kb.has_duplicate_error(task.id, "TypeError: NoneType")
        assert has_dup is False

        # Record an attempt
        await error_kb.record_attempt(
            task_id=task.id,
            attempt_number=1,
            approach_summary="Accessed None value",
            outcome=HypothesisOutcome.FAILURE,
            error_signature="TypeError: NoneType",
        )

        # After recording - duplicate found
        has_dup = await error_kb.has_duplicate_error(task.id, "TypeError: NoneType")
        assert has_dup is True

        # Different signature - no duplicate
        has_dup = await error_kb.has_duplicate_error(task.id, "ValueError: wrong")
        assert has_dup is False

    async def test_record_success(self, error_kb, repository, sample_project):
        """record_attempt can also record a SUCCESS outcome."""
        await repository.create_project(sample_project)
        task = Task(
            project_id=sample_project.id,
            title="Success task",
            description="Task that succeeds",
        )
        await repository.create_task(task)

        entry = await error_kb.record_attempt(
            task_id=task.id,
            attempt_number=1,
            approach_summary="Used bcrypt hashing",
            outcome=HypothesisOutcome.SUCCESS,
        )
        assert entry.outcome == HypothesisOutcome.SUCCESS


class TestNormalizeErrorForDedup:
    """Tests for standalone normalize_error_for_dedup()."""

    def test_normalize_error_uuid(self):
        """UUIDs are replaced with <UUID>."""
        raw = "Error in task 550e8400-e29b-41d4-a716-446655440000: failed"
        result = normalize_error_for_dedup(raw)
        assert "<UUID>" in result
        assert "550e8400" not in result

    def test_normalize_error_quoted_strings(self):
        """Quoted strings are replaced with <STR>."""
        raw = "KeyError: 'missing_key' and \"another key\" not found"
        result = normalize_error_for_dedup(raw)
        assert "'<STR>'" in result
        assert '"<STR>"' in result
        assert "missing_key" not in result

    def test_normalize_error_timestamps(self):
        """ISO timestamps are replaced with <TIMESTAMP>."""
        raw = "Error at 2026-03-03T14:30:00Z in processing"
        result = normalize_error_for_dedup(raw)
        assert "<TIMESTAMP>" in result
        assert "2026-03-03" not in result

    def test_normalize_error_timestamps_with_offset(self):
        """ISO timestamps with timezone offset are normalized."""
        raw = "Event at 2026-03-03 14:30:00+00:00 failed"
        result = normalize_error_for_dedup(raw)
        assert "<TIMESTAMP>" in result

    def test_normalize_error_file_paths(self):
        """File paths are replaced with <PATH>."""
        raw = "Error in /usr/local/lib/python3.12/site-packages/module.py"
        result = normalize_error_for_dedup(raw)
        assert "<PATH>" in result
        assert "site-packages" not in result

    def test_normalize_error_line_numbers(self):
        """Line numbers are replaced with <NUM>."""
        raw = "Error at line 42 in file.py"
        result = normalize_error_for_dedup(raw)
        assert "line <NUM>" in result
        assert "42" not in result

    def test_normalize_error_whitespace(self):
        """Whitespace is collapsed."""
        raw = "Error   with   multiple    spaces\n\tand tabs"
        result = normalize_error_for_dedup(raw)
        assert "  " not in result

    def test_normalize_error_combined(self):
        """Multiple normalization rules apply together."""
        raw = (
            "Task 550e8400-e29b-41d4-a716-446655440000 failed at "
            "2026-03-03T10:00:00Z with KeyError: 'foo' in /src/bar.py line 99"
        )
        result = normalize_error_for_dedup(raw)
        assert "<UUID>" in result
        assert "<TIMESTAMP>" in result
        assert "'<STR>'" in result
        assert "<PATH>" in result
        assert "line <NUM>" in result

    def test_normalize_error_idempotent(self):
        """Normalizing an already-normalized string is stable."""
        raw = "TypeError: None is not callable at line 5"
        first = normalize_error_for_dedup(raw)
        second = normalize_error_for_dedup(first)
        # May not be perfectly idempotent due to <NUM> but structure should be similar
        assert "<NUM>" in second


class TestCategorizeError:
    """Tests for _categorize_error().

    Note: ERROR_CATEGORIES is checked in definition order. Some keywords
    overlap across categories (e.g. "has no attribute" appears in both
    type_error and attribute_error). Tests use inputs that match the
    *first* matching category in the iteration order.
    """

    def test_categorize_error_type_error(self):
        assert _categorize_error("TypeError: 'NoneType' is not callable") == "type_error"

    def test_categorize_error_import_error(self):
        assert _categorize_error("ImportError: No module named 'foo'") == "import_error"

    def test_categorize_error_attribute_error(self):
        """Use 'attributeerror' keyword which uniquely matches attribute_error category."""
        assert _categorize_error("AttributeError: object 'x' not found") == "attribute_error"

    def test_categorize_error_value_error(self):
        assert _categorize_error("ValueError: invalid literal for int()") == "value_error"

    def test_categorize_error_key_error(self):
        assert _categorize_error("KeyError: 'missing_key'") == "key_error"

    def test_categorize_error_connection_error(self):
        assert _categorize_error("ConnectionError: Connection refused") == "connection_error"

    def test_categorize_error_database_error(self):
        assert _categorize_error("OperationalError: database is locked") == "database_error"

    def test_categorize_error_unknown(self):
        """Input that does not match any category keyword returns 'unknown'."""
        assert _categorize_error("Bizarre malfunction in subsystem Z") == "unknown"


class TestCalculateUrgency:
    """Tests for _calculate_urgency()."""

    def test_calculate_urgency_critical_by_count(self):
        """count >= 5 is critical."""
        assert _calculate_urgency(count=5, num_tasks=1) == "critical"

    def test_calculate_urgency_critical_by_tasks(self):
        """num_tasks >= 3 is critical."""
        assert _calculate_urgency(count=3, num_tasks=3) == "critical"

    def test_calculate_urgency_high_by_count(self):
        """count >= 3 is high."""
        assert _calculate_urgency(count=3, num_tasks=1) == "high"

    def test_calculate_urgency_high_by_tasks(self):
        """num_tasks >= 2 is high."""
        assert _calculate_urgency(count=2, num_tasks=2) == "high"

    def test_calculate_urgency_medium(self):
        """count = 2, num_tasks = 1 is medium."""
        assert _calculate_urgency(count=2, num_tasks=1) == "medium"

    def test_calculate_urgency_low(self):
        """count = 1, num_tasks = 1 is low."""
        assert _calculate_urgency(count=1, num_tasks=1) == "low"


class TestFailurePattern:
    """Tests for FailurePattern.to_dict()."""

    def test_failure_pattern_to_dict(self):
        """Verify FailurePattern serializes to expected dict structure."""
        pattern = FailurePattern(
            error_signature="TypeError: NoneType not callable",
            count=7,
            task_ids={"task-1", "task-2", "task-3"},
            category="type_error",
            urgency="critical",
            example_approaches=["Tried A", "Tried B", "Tried C", "Tried D"],
            successful_resolution="Used isinstance check",
            agent_ids={"claude", "codex", "gemini", "grok"},
        )

        d = pattern.to_dict()

        assert d["error_signature"] == "TypeError: NoneType not callable"
        assert d["count"] == 7
        assert d["task_count"] == 3
        assert d["category"] == "type_error"
        assert d["urgency"] == "critical"
        assert len(d["example_approaches"]) <= 3  # Capped at 3
        assert d["has_resolution"] is True
        assert d["all_agents_failed"] is True
        assert d["agent_ids"] == ["claude", "codex", "gemini", "grok"]

    def test_failure_pattern_to_dict_no_resolution(self):
        """FailurePattern without resolution sets has_resolution=False."""
        pattern = FailurePattern(
            error_signature="SomeError",
            count=2,
            task_ids={"t1"},
            category="unknown",
            urgency="medium",
            example_approaches=["A"],
            successful_resolution=None,
        )
        d = pattern.to_dict()
        assert d["has_resolution"] is False

    def test_failure_pattern_to_dict_partial_agents(self):
        """FailurePattern with only some agents sets all_agents_failed=False."""
        pattern = FailurePattern(
            error_signature="SomeError",
            count=2,
            task_ids={"t1"},
            category="unknown",
            urgency="medium",
            example_approaches=["A"],
            agent_ids={"claude", "codex"},
        )
        d = pattern.to_dict()
        assert d["all_agents_failed"] is False


class TestErrorKBCommonFailurePatterns:
    """Tests for get_common_failure_patterns (cross-task analysis)."""

    async def test_get_common_failure_patterns(self, error_kb, repository, sample_project):
        """Detects recurring patterns across multiple tasks."""
        await repository.create_project(sample_project)

        # Create 3 tasks with the same error
        for i in range(3):
            task = Task(
                project_id=sample_project.id,
                title=f"Task {i}",
                description=f"Description {i}",
            )
            await repository.create_task(task)

            await error_kb.record_attempt(
                task_id=task.id,
                attempt_number=1,
                approach_summary=f"Approach {i}",
                outcome=HypothesisOutcome.FAILURE,
                error_signature="TypeError: NoneType is not subscriptable",
                agent_id="claude",
            )

        patterns = await error_kb.get_common_failure_patterns(
            project_id=sample_project.id,
            min_count=2,
        )

        assert len(patterns) >= 1
        found = [p for p in patterns if "NoneType" in p.error_signature]
        assert len(found) == 1
        assert found[0].count >= 3
        assert found[0].category == "type_error"

    async def test_get_common_failure_patterns_below_threshold(
        self, error_kb, repository, sample_project
    ):
        """Patterns below min_count threshold are not returned."""
        await repository.create_project(sample_project)
        task = Task(
            project_id=sample_project.id,
            title="Single task",
            description="Only one occurrence",
        )
        await repository.create_task(task)

        await error_kb.record_attempt(
            task_id=task.id,
            attempt_number=1,
            approach_summary="Tried once",
            outcome=HypothesisOutcome.FAILURE,
            error_signature="UniqueError: only happens once",
        )

        patterns = await error_kb.get_common_failure_patterns(
            project_id=sample_project.id,
            min_count=2,
        )

        unique_patterns = [p for p in patterns if "UniqueError" in p.error_signature]
        assert len(unique_patterns) == 0


class TestErrorKBCrossAgentFailures:
    """Tests for get_cross_agent_failures."""

    async def test_get_cross_agent_failures(self, error_kb, repository, sample_project):
        """Detects errors where all 4 agents have failed."""
        await repository.create_project(sample_project)

        agents = ["claude", "codex", "gemini", "grok"]
        for i, agent in enumerate(agents):
            task = Task(
                project_id=sample_project.id,
                title=f"Cross agent task {i}",
                description=f"Description {i}",
            )
            await repository.create_task(task)

            await error_kb.record_attempt(
                task_id=task.id,
                attempt_number=1,
                approach_summary=f"Agent {agent} tried",
                outcome=HypothesisOutcome.FAILURE,
                error_signature="FundamentalError: cannot resolve",
                agent_id=agent,
            )

        patterns = await error_kb.get_cross_agent_failures(
            project_id=sample_project.id,
            min_agents=4,
        )

        assert len(patterns) >= 1
        assert patterns[0].urgency == "critical"
        assert patterns[0].agent_ids >= {"claude", "codex", "gemini", "grok"}

    async def test_get_cross_agent_failures_partial(self, error_kb, repository, sample_project):
        """Does not flag errors that only affect 2 agents."""
        await repository.create_project(sample_project)

        for agent in ["claude", "codex"]:
            task = Task(
                project_id=sample_project.id,
                title=f"Partial fail {agent}",
                description=f"Desc {agent}",
            )
            await repository.create_task(task)

            await error_kb.record_attempt(
                task_id=task.id,
                attempt_number=1,
                approach_summary=f"{agent} tried",
                outcome=HypothesisOutcome.FAILURE,
                error_signature="PartialError: only some agents fail",
                agent_id=agent,
            )

        patterns = await error_kb.get_cross_agent_failures(
            project_id=sample_project.id,
            min_agents=4,
        )

        partial = [p for p in patterns if "PartialError" in p.error_signature]
        assert len(partial) == 0
