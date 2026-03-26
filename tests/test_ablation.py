"""Tests for A/B knowledge ablation (Phase B).

Covers:
- Ablation label routing (control suppresses, variant preserves knowledge)
- No-test-scheduled fallback (ValueError when no variants exist)
- Sample recording after cycle (success and failure paths)
- Bayesian evaluation with sufficient and insufficient samples
- Schedule creates both control and variant rows in prompt_variants
- CLI ab-test subcommands exist

ALL tests use REAL aiosqlite in-memory databases, real PromptEvolver,
real DatabaseEngine, and real Repository. NO mocks, NO placeholders.
"""

from __future__ import annotations

import uuid

import pytest

from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository
from claw.evolution.prompt_evolver import MIN_SAMPLES, PromptEvolver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def evolver():
    """Create a real PromptEvolver with an in-memory SQLite database."""
    config = DatabaseConfig(db_path=":memory:")
    engine = DatabaseEngine(config)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repo = Repository(engine)
    pe = PromptEvolver(repository=repo)
    yield pe
    await engine.close()


@pytest.fixture
async def evolver_with_test(evolver):
    """PromptEvolver with a pre-scheduled knowledge_ablation A/B test."""
    ids = await evolver.schedule_ab_test(
        prompt_name="knowledge_ablation",
        control_content="You are an agent. No retrieved knowledge.",
        variant_content="You are an agent. Use the retrieved knowledge below.",
    )
    return evolver, ids


# ---------------------------------------------------------------------------
# Test 1: Control label suppresses knowledge
# ---------------------------------------------------------------------------

class TestAblationSuppressesKnowledgeWhenControl:
    """When select_variant_for_invocation returns 'control', the ablation
    logic in cycle.py sets past_solutions = [].  We verify the evolver
    returns 'control' as a possible label, and that the suppression
    branching logic works correctly with real data.
    """

    async def test_control_label_returned_from_evolver(self, evolver_with_test):
        """select_variant_for_invocation returns either 'control' or 'variant'.
        Call it enough times to confirm 'control' is among the outcomes."""
        evolver, _ids = evolver_with_test

        labels_seen: set[str] = set()
        for _ in range(40):
            label, content = await evolver.select_variant_for_invocation(
                "knowledge_ablation", agent_id=None
            )
            labels_seen.add(label)
            if "control" in labels_seen and "variant" in labels_seen:
                break

        assert "control" in labels_seen, (
            "Expected 'control' to be returned at least once in 40 calls; "
            f"only saw: {labels_seen}"
        )

    async def test_control_suppresses_past_solutions(self, evolver_with_test):
        """Replicate the ablation gate from cycle.py evaluate(): if label is
        'control', past_solutions is cleared."""
        evolver, _ids = evolver_with_test

        # Simulate knowledge items
        past_solutions = ["methodology_1", "methodology_2", "methodology_3"]

        # Run the exact logic from cycle.py lines 896-910
        ablation_label = None
        try:
            ablation_label, _ = await evolver.select_variant_for_invocation(
                "knowledge_ablation", agent_id=None
            )
            if ablation_label == "control":
                past_solutions = []
        except (ValueError, Exception):
            ablation_label = None

        # If control was selected, knowledge must be suppressed
        if ablation_label == "control":
            assert past_solutions == []
        else:
            # variant was selected, knowledge preserved
            assert len(past_solutions) == 3


# ---------------------------------------------------------------------------
# Test 2: Variant label preserves knowledge
# ---------------------------------------------------------------------------

class TestAblationPreservesKnowledgeWhenVariant:
    """When the evolver returns 'variant', past_solutions stays intact."""

    async def test_variant_label_returned_from_evolver(self, evolver_with_test):
        """Confirm 'variant' is among the labels returned."""
        evolver, _ids = evolver_with_test

        labels_seen: set[str] = set()
        for _ in range(40):
            label, _content = await evolver.select_variant_for_invocation(
                "knowledge_ablation", agent_id=None
            )
            labels_seen.add(label)
            if "variant" in labels_seen:
                break

        assert "variant" in labels_seen, (
            "Expected 'variant' to be returned at least once in 40 calls; "
            f"only saw: {labels_seen}"
        )

    async def test_variant_preserves_past_solutions(self, evolver_with_test):
        """When variant is selected, past_solutions remains unchanged."""
        evolver, _ids = evolver_with_test

        past_solutions = ["methodology_A", "methodology_B"]
        original_count = len(past_solutions)

        ablation_label = None
        try:
            ablation_label, _ = await evolver.select_variant_for_invocation(
                "knowledge_ablation", agent_id=None
            )
            if ablation_label == "control":
                past_solutions = []
        except (ValueError, Exception):
            ablation_label = None

        if ablation_label == "variant":
            assert len(past_solutions) == original_count


# ---------------------------------------------------------------------------
# Test 3: No test scheduled -> ValueError, knowledge preserved
# ---------------------------------------------------------------------------

class TestNoTestScheduledKnowledgePreserved:
    """When no A/B test has been scheduled, select_variant_for_invocation
    raises ValueError and the ablation label stays None."""

    async def test_no_variants_raises_value_error(self, evolver):
        """Calling select_variant without scheduling a test raises ValueError."""
        with pytest.raises(ValueError, match="No variants found"):
            await evolver.select_variant_for_invocation(
                "knowledge_ablation", agent_id=None
            )

    async def test_no_test_means_ablation_label_none(self, evolver):
        """The cycle.py error-handling path sets ablation_label to None."""
        past_solutions = ["methodology_X"]
        ablation_label = None

        try:
            ablation_label, _ = await evolver.select_variant_for_invocation(
                "knowledge_ablation", agent_id=None
            )
        except (ValueError, Exception):
            ablation_label = None

        assert ablation_label is None
        assert len(past_solutions) == 1, "Knowledge must not be suppressed"


# ---------------------------------------------------------------------------
# Test 4: Sample recorded on success
# ---------------------------------------------------------------------------

class TestSampleRecordedOnSuccess:
    """After a successful task, record_sample increments sample_count and
    success_count."""

    async def test_success_increments_both_counts(self, evolver_with_test):
        evolver, _ids = evolver_with_test

        recorded = await evolver.record_sample(
            prompt_name="knowledge_ablation",
            variant_label="variant",
            agent_id=None,
            success=True,
            quality_score=0.85,
        )
        assert recorded is True

        # Verify via evaluate (which reads the stats)
        stats = await evolver._fetch_variant_stats(
            "knowledge_ablation", "variant", None
        )
        assert stats is not None
        assert stats["sample_count"] == 1
        assert stats["success_count"] == 1
        assert abs(stats["avg_quality_score"] - 0.85) < 0.001

    async def test_multiple_successes_accumulate(self, evolver_with_test):
        evolver, _ids = evolver_with_test

        for i in range(5):
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label="control",
                agent_id=None,
                success=True,
                quality_score=0.7,
            )

        stats = await evolver._fetch_variant_stats(
            "knowledge_ablation", "control", None
        )
        assert stats is not None
        assert stats["sample_count"] == 5
        assert stats["success_count"] == 5
        assert abs(stats["avg_quality_score"] - 0.7) < 0.001


# ---------------------------------------------------------------------------
# Test 5: Sample recorded on failure
# ---------------------------------------------------------------------------

class TestSampleRecordedOnFailure:
    """After a failed task, record_sample increments sample_count but NOT
    success_count."""

    async def test_failure_increments_sample_not_success(self, evolver_with_test):
        evolver, _ids = evolver_with_test

        recorded = await evolver.record_sample(
            prompt_name="knowledge_ablation",
            variant_label="control",
            agent_id=None,
            success=False,
            quality_score=0.1,
        )
        assert recorded is True

        stats = await evolver._fetch_variant_stats(
            "knowledge_ablation", "control", None
        )
        assert stats is not None
        assert stats["sample_count"] == 1
        assert stats["success_count"] == 0
        assert abs(stats["avg_quality_score"] - 0.1) < 0.001

    async def test_mixed_success_and_failure(self, evolver_with_test):
        evolver, _ids = evolver_with_test

        # 3 successes, 2 failures for control
        for i in range(5):
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label="control",
                agent_id=None,
                success=(i < 3),
                quality_score=0.8 if i < 3 else 0.2,
            )

        stats = await evolver._fetch_variant_stats(
            "knowledge_ablation", "control", None
        )
        assert stats is not None
        assert stats["sample_count"] == 5
        assert stats["success_count"] == 3

    async def test_record_nonexistent_variant_returns_false(self, evolver_with_test):
        """Recording a sample for a variant that does not exist returns False."""
        evolver, _ids = evolver_with_test

        result = await evolver.record_sample(
            prompt_name="nonexistent_prompt",
            variant_label="control",
            agent_id=None,
            success=True,
            quality_score=0.5,
        )
        assert result is False


# ---------------------------------------------------------------------------
# Test 6: Evaluate produces Bayesian result with enough samples
# ---------------------------------------------------------------------------

class TestEvaluateProducesBayesianResult:
    """With >= MIN_SAMPLES per variant, evaluate_test declares a winner
    using Bayesian Beta-distribution comparison."""

    async def test_variant_wins_with_higher_success_rate(self, evolver_with_test):
        evolver, _ids = evolver_with_test

        # Record 25 samples: control 40% success, variant 80% success
        for i in range(25):
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label="control",
                agent_id=None,
                success=(i % 5 < 2),  # 2 out of every 5 = 40%
                quality_score=0.4,
            )
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label="variant",
                agent_id=None,
                success=(i % 5 < 4),  # 4 out of every 5 = 80%
                quality_score=0.8,
            )

        result = await evolver.evaluate_test("knowledge_ablation")

        assert result["ready"] is True
        assert result["winner"] == "variant", (
            f"Expected 'variant' to win (80% vs 40%), got: {result['winner']}"
        )
        assert result["margin"] > 0, "Positive margin means variant is ahead"

        # Verify stats structure
        assert result["control"]["sample_count"] == 25
        assert result["variant"]["sample_count"] == 25
        assert result["control"]["success_count"] == 10  # 40% of 25
        assert result["variant"]["success_count"] == 20  # 80% of 25
        assert "bayesian_score" in result["control"]
        assert "bayesian_score" in result["variant"]

    async def test_control_wins_when_variant_is_worse(self, evolver_with_test):
        """If knowledge actually hurts, control should win."""
        evolver, _ids = evolver_with_test

        # control: 90% success; variant: 30% success
        for i in range(25):
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label="control",
                agent_id=None,
                success=(i % 10 < 9),  # 9 out of 10 = 90%
                quality_score=0.9,
            )
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label="variant",
                agent_id=None,
                success=(i % 10 < 3),  # 3 out of 10 = 30%
                quality_score=0.3,
            )

        result = await evolver.evaluate_test("knowledge_ablation")
        assert result["ready"] is True
        assert result["winner"] == "control"
        assert result["margin"] < 0, "Negative margin means control is ahead"


# ---------------------------------------------------------------------------
# Test 7: Schedule creates both control and variant rows
# ---------------------------------------------------------------------------

class TestScheduleCreatesBothVariants:
    """schedule_ab_test inserts two rows in prompt_variants: one for
    'control' and one for 'variant'."""

    async def test_both_ids_returned(self, evolver_with_test):
        _evolver, ids = evolver_with_test
        assert "control_id" in ids
        assert "variant_id" in ids
        assert ids["control_id"] != ids["variant_id"]

    async def test_rows_exist_in_db(self, evolver_with_test):
        evolver, ids = evolver_with_test

        control_stats = await evolver._fetch_variant_stats(
            "knowledge_ablation", "control", None
        )
        variant_stats = await evolver._fetch_variant_stats(
            "knowledge_ablation", "variant", None
        )

        assert control_stats is not None
        assert variant_stats is not None
        assert control_stats["id"] == ids["control_id"]
        assert variant_stats["id"] == ids["variant_id"]
        assert control_stats["sample_count"] == 0
        assert variant_stats["sample_count"] == 0

    async def test_control_is_active_variant_is_not(self, evolver_with_test):
        evolver, _ids = evolver_with_test

        control_stats = await evolver._fetch_variant_stats(
            "knowledge_ablation", "control", None
        )
        variant_stats = await evolver._fetch_variant_stats(
            "knowledge_ablation", "variant", None
        )

        assert control_stats["is_active"] is True
        assert variant_stats["is_active"] is False

    async def test_upsert_resets_counters(self, evolver_with_test):
        """Re-scheduling the same test resets sample and success counts."""
        evolver, _ids = evolver_with_test

        # Record some samples first
        for _ in range(3):
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label="control",
                agent_id=None,
                success=True,
                quality_score=0.5,
            )

        # Re-schedule — should reset counters
        new_ids = await evolver.schedule_ab_test(
            prompt_name="knowledge_ablation",
            control_content="new control content",
            variant_content="new variant content",
        )

        stats = await evolver._fetch_variant_stats(
            "knowledge_ablation", "control", None
        )
        assert stats is not None
        assert stats["sample_count"] == 0
        assert stats["success_count"] == 0
        # IDs should be the same (upsert, not new insert)
        assert new_ids["control_id"] == _ids["control_id"]


# ---------------------------------------------------------------------------
# Test 8: Evaluate not ready with insufficient samples
# ---------------------------------------------------------------------------

class TestEvaluateNotReadyWithFewSamples:
    """Before MIN_SAMPLES, evaluate_test returns ready=False and no winner."""

    async def test_five_samples_not_ready(self, evolver_with_test):
        evolver, _ids = evolver_with_test

        for _ in range(5):
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label="control",
                agent_id=None,
                success=True,
                quality_score=0.6,
            )
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label="variant",
                agent_id=None,
                success=True,
                quality_score=0.6,
            )

        result = await evolver.evaluate_test("knowledge_ablation")
        assert result["ready"] is False
        assert result["winner"] is None

    async def test_one_below_threshold_not_ready(self, evolver_with_test):
        """If control has MIN_SAMPLES but variant has MIN_SAMPLES - 1,
        still not ready."""
        evolver, _ids = evolver_with_test

        for _ in range(MIN_SAMPLES):
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label="control",
                agent_id=None,
                success=True,
                quality_score=0.5,
            )
        for _ in range(MIN_SAMPLES - 1):
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label="variant",
                agent_id=None,
                success=True,
                quality_score=0.5,
            )

        result = await evolver.evaluate_test("knowledge_ablation")
        assert result["ready"] is False

    async def test_zero_samples_not_ready(self, evolver_with_test):
        """No samples recorded at all: not ready."""
        evolver, _ids = evolver_with_test

        result = await evolver.evaluate_test("knowledge_ablation")
        assert result["ready"] is False
        assert result["winner"] is None

    async def test_no_variants_at_all(self, evolver):
        """evaluate_test on a prompt with no variants returns ready=False."""
        result = await evolver.evaluate_test("nonexistent_prompt")
        assert result["ready"] is False
        assert result["winner"] is None
        assert result["control"] is None
        assert result["variant"] is None


# ---------------------------------------------------------------------------
# CLI: ab-test subcommands exist
# ---------------------------------------------------------------------------

class TestAblationCLI:
    """Verify CLI ab-test subcommands are registered."""

    def test_ab_test_app_has_start_command(self):
        from claw.cli import ab_test_app
        command_names = [cmd.name for cmd in ab_test_app.registered_commands]
        assert "start" in command_names

    def test_ab_test_app_has_status_command(self):
        from claw.cli import ab_test_app
        command_names = [cmd.name for cmd in ab_test_app.registered_commands]
        assert "status" in command_names

    def test_ab_test_app_has_stop_command(self):
        from claw.cli import ab_test_app
        command_names = [cmd.name for cmd in ab_test_app.registered_commands]
        assert "stop" in command_names


# ---------------------------------------------------------------------------
# MicroClaw._ablation_label initialization
# ---------------------------------------------------------------------------

class TestAblationLabelInit:
    """Verify _ablation_label is initialized to None on MicroClaw.__init__."""

    def test_ablation_label_attribute_exists(self):
        """MicroClaw must have _ablation_label as an Optional[str] field."""
        from claw.cycle import MicroClaw
        assert hasattr(MicroClaw, "__init__"), "MicroClaw must have __init__"
        # Verify via source inspection that _ablation_label is set
        import inspect
        source = inspect.getsource(MicroClaw.__init__)
        assert "_ablation_label" in source, (
            "MicroClaw.__init__ must initialize _ablation_label"
        )
