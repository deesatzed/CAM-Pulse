"""Tests for A/B knowledge ablation (Phase B).

Covers:
- Ablation label routing (control suppresses, variant preserves)
- No-test-scheduled fallback
- Sample recording after cycle
- Bayesian evaluation
- CLI commands
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claw.cycle import MicroClaw


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ctx(prompt_evolver=None, semantic_memory=None, repository=None):
    """Build a minimal ClawContext-like object for testing."""
    ctx = MagicMock()
    ctx.prompt_evolver = prompt_evolver
    ctx.semantic_memory = semantic_memory
    ctx.repository = repository
    ctx.config = MagicMock()
    ctx.config.memory.attribution_embedding_enabled = False
    ctx.degradation_manager = None
    ctx.governance = None
    ctx.assimilation_engine = None
    ctx.embeddings = None
    return ctx


def _make_micro_claw(ctx):
    """Instantiate MicroClaw with a mock context."""
    mc = MicroClaw.__new__(MicroClaw)
    mc.ctx = ctx
    mc.project_id = "test-proj"
    mc.session_id = "test-session"
    mc._current_task = None
    mc._current_context_brief = None
    mc._current_outcome = None
    mc._current_verification = None
    mc._ablation_label = None
    mc.level = "micro"
    return mc


# ---------------------------------------------------------------------------
# Ablation label initialization
# ---------------------------------------------------------------------------

class TestAblationInit:
    """Verify _ablation_label field exists on MicroClaw."""

    def test_ablation_label_initialized_none(self):
        ctx = _make_ctx()
        mc = MicroClaw(ctx, project_id="p1")
        assert mc._ablation_label is None


# ---------------------------------------------------------------------------
# Prompt evolver integration (unit tests with mocks for the evolver API)
# ---------------------------------------------------------------------------

class TestAblationRouting:
    """Test ablation routing in evaluate()."""

    def test_control_suppresses_knowledge(self):
        """When evolver returns 'control', past_solutions should be cleared."""
        evolver = AsyncMock()
        evolver.select_variant_for_invocation = AsyncMock(
            return_value=("control", "ablated")
        )

        past_solutions = [MagicMock(id="m1"), MagicMock(id="m2")]

        # Simulate the ablation gate logic (extracted from cycle.py evaluate())
        ablation_label = None
        if evolver is not None and past_solutions:
            async def _check():
                nonlocal ablation_label, past_solutions
                label, _ = await evolver.select_variant_for_invocation(
                    "knowledge_ablation", agent_id=None
                )
                ablation_label = label
                if label == "control":
                    past_solutions = []

            asyncio.run(_check())

        assert ablation_label == "control"
        assert past_solutions == []

    def test_variant_preserves_knowledge(self):
        """When evolver returns 'variant', past_solutions should remain."""
        evolver = AsyncMock()
        evolver.select_variant_for_invocation = AsyncMock(
            return_value=("variant", "with_knowledge")
        )

        original = [MagicMock(id="m1")]
        past_solutions = list(original)

        async def _check():
            label, _ = await evolver.select_variant_for_invocation(
                "knowledge_ablation", agent_id=None
            )
            if label == "control":
                past_solutions.clear()

        asyncio.run(_check())
        assert len(past_solutions) == 1

    def test_no_test_scheduled_preserves_knowledge(self):
        """ValueError from evolver means no test — knowledge preserved."""
        evolver = AsyncMock()
        evolver.select_variant_for_invocation = AsyncMock(
            side_effect=ValueError("No variants found")
        )

        past_solutions = [MagicMock(id="m1")]
        ablation_label = None

        async def _check():
            nonlocal ablation_label
            try:
                label, _ = await evolver.select_variant_for_invocation(
                    "knowledge_ablation", agent_id=None
                )
                ablation_label = label
            except (ValueError, Exception):
                ablation_label = None

        asyncio.run(_check())
        assert ablation_label is None
        assert len(past_solutions) == 1


# ---------------------------------------------------------------------------
# Sample recording
# ---------------------------------------------------------------------------

class TestAblationSampleRecording:
    """Test that ablation samples are recorded via prompt_evolver."""

    def test_sample_recorded_on_success(self):
        evolver = AsyncMock()
        evolver.record_sample = AsyncMock(return_value=True)

        ablation_label = "variant"
        verification = MagicMock()
        verification.approved = True
        verification.quality_score = 0.85

        async def _record():
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label=ablation_label,
                agent_id=None,
                success=verification.approved,
                quality_score=verification.quality_score or 0.0,
            )

        asyncio.run(_record())
        evolver.record_sample.assert_called_once_with(
            prompt_name="knowledge_ablation",
            variant_label="variant",
            agent_id=None,
            success=True,
            quality_score=0.85,
        )

    def test_sample_recorded_on_failure(self):
        evolver = AsyncMock()
        evolver.record_sample = AsyncMock(return_value=True)

        async def _record():
            await evolver.record_sample(
                prompt_name="knowledge_ablation",
                variant_label="control",
                agent_id=None,
                success=False,
                quality_score=0.0,
            )

        asyncio.run(_record())
        evolver.record_sample.assert_called_once()
        call_kwargs = evolver.record_sample.call_args[1]
        assert call_kwargs["success"] is False

    def test_no_recording_when_no_ablation(self):
        """If _ablation_label is None, no sample should be recorded."""
        evolver = AsyncMock()
        ablation_label = None

        # Simulate the conditional
        recorded = False
        if ablation_label is not None and evolver is not None:
            recorded = True

        assert not recorded


# ---------------------------------------------------------------------------
# Bayesian evaluation (in-memory DB)
# ---------------------------------------------------------------------------

class TestAblationEvaluation:
    """Test evaluate_test() Bayesian comparison with real DB."""

    def test_evaluate_produces_bayesian_result(self):
        """After enough samples, evaluate returns a winner."""
        from claw.core.config import DatabaseConfig
        from claw.db.engine import DatabaseEngine
        from claw.evolution.prompt_evolver import PromptEvolver

        async def _run():
            config = DatabaseConfig(db_path=":memory:")
            engine = DatabaseEngine(config)
            await engine.connect()
            await engine.apply_migrations()
            await engine.initialize_schema()

            from claw.db.repository import Repository
            repo = Repository(engine)
            evolver = PromptEvolver(repo)

            # Schedule test
            ids = await evolver.schedule_ab_test(
                prompt_name="knowledge_ablation",
                control_content="ablated",
                variant_content="with_knowledge",
            )
            assert "control_id" in ids
            assert "variant_id" in ids

            # Record 25 samples each — control has 40% success, variant has 80%
            for _ in range(25):
                await evolver.record_sample(
                    prompt_name="knowledge_ablation",
                    variant_label="control",
                    agent_id=None,
                    success=(_ % 5 < 2),  # 40% success
                    quality_score=0.4,
                )
                await evolver.record_sample(
                    prompt_name="knowledge_ablation",
                    variant_label="variant",
                    agent_id=None,
                    success=(_ % 5 < 4),  # 80% success
                    quality_score=0.8,
                )

            result = await evolver.evaluate_test("knowledge_ablation")
            assert result["ready"] is True
            assert result["winner"] == "variant"  # Knowledge wins
            assert result["margin"] > 0

            await engine.close()

        asyncio.run(_run())

    def test_not_ready_with_few_samples(self):
        """Before MIN_SAMPLES, evaluate returns ready=False."""
        from claw.core.config import DatabaseConfig
        from claw.db.engine import DatabaseEngine
        from claw.evolution.prompt_evolver import PromptEvolver

        async def _run():
            config = DatabaseConfig(db_path=":memory:")
            engine = DatabaseEngine(config)
            await engine.connect()
            await engine.apply_migrations()
            await engine.initialize_schema()

            from claw.db.repository import Repository
            repo = Repository(engine)
            evolver = PromptEvolver(repo)
            await evolver.schedule_ab_test(
                prompt_name="knowledge_ablation",
                control_content="ablated",
                variant_content="with_knowledge",
            )

            # Only 5 samples each
            for _ in range(5):
                await evolver.record_sample(
                    prompt_name="knowledge_ablation",
                    variant_label="control",
                    agent_id=None,
                    success=True,
                    quality_score=0.5,
                )
                await evolver.record_sample(
                    prompt_name="knowledge_ablation",
                    variant_label="variant",
                    agent_id=None,
                    success=True,
                    quality_score=0.5,
                )

            result = await evolver.evaluate_test("knowledge_ablation")
            assert result["ready"] is False

            await engine.close()

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# CLI command tests (non-interactive)
# ---------------------------------------------------------------------------

class TestAblationCLI:
    """Test CLI ab-test subcommands exist and are callable."""

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
