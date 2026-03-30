"""Tests for Bayesian Kelly Criterion position-sizing integration.

Covers:
- BayesianKellySizer pure computation (fractions, routing weights, posterior std)
- Dispatcher integration (Kelly routing, fallback, disabled)
- PromptEvolver adaptive margin (kappa-shrinkage)
- Fitness uncertainty discount (kelly_posterior_std)
- Config parsing
"""

from __future__ import annotations

import asyncio
import math
import random
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from claw.evolution.kelly import BayesianKellySizer, KellyResult


# ---------------------------------------------------------------------------
# A. Pure computation tests — BayesianKellySizer
# ---------------------------------------------------------------------------

class TestKellyFractionComputation:
    """Test Sukhov (2026) eq. 13 implementation."""

    def test_uniform_prior_positive_payoff(self):
        """Beta(1,1) with b > 1 yields a positive fraction."""
        sizer = BayesianKellySizer(kappa=10.0)
        result = sizer.compute_fraction(successes=0, failures=0)
        # p_bar = 1/(1+1) = 0.5, f_base = 0.5 - 0.5/2.0 = 0.25
        # phi = 2/(2+10) = 0.167, f = 0.25 * 0.167 = 0.042
        assert result.fraction > 0
        assert result.p_bar == pytest.approx(0.5, abs=0.01)
        assert result.n_eff == pytest.approx(2.0, abs=0.01)

    def test_strong_positive_record(self):
        """Agent with 30 successes and 5 failures gets high fraction."""
        sizer = BayesianKellySizer(kappa=10.0)
        result = sizer.compute_fraction(successes=30, failures=5)
        # p_bar ~ 31/37 = 0.838, high phi
        assert result.fraction > 0.15
        assert result.p_bar > 0.8

    def test_strong_negative_record(self):
        """Agent with 5 successes and 30 failures gets zero fraction."""
        sizer = BayesianKellySizer(kappa=10.0)
        result = sizer.compute_fraction(successes=5, failures=30)
        # p_bar ~ 6/37 = 0.162, f_base is negative
        assert result.fraction == 0.0

    def test_high_kappa_shrinks_fraction(self):
        """Same data with kappa=1000 yields heavily shrunk fraction."""
        sizer_normal = BayesianKellySizer(kappa=10.0)
        sizer_high = BayesianKellySizer(kappa=1000.0)
        normal = sizer_normal.compute_fraction(successes=30, failures=5)
        high = sizer_high.compute_fraction(successes=30, failures=5)
        # phi = 37/(37+1000) = 0.036 → heavy shrinkage vs normal
        assert high.fraction < normal.fraction * 0.3
        assert high.fraction < 0.05

    def test_f_max_cap(self):
        """Extremely strong signal capped at f_max."""
        sizer = BayesianKellySizer(kappa=0.1, f_max=0.25)
        result = sizer.compute_fraction(successes=1000, failures=1)
        assert result.fraction <= 0.25

    def test_no_data(self):
        """No successes and no failures — minimal fraction from prior."""
        sizer = BayesianKellySizer(kappa=10.0)
        result = sizer.compute_fraction(successes=0, failures=0)
        # Small but positive due to uniform prior and positive payoff
        assert 0.0 <= result.fraction <= 0.15

    def test_payoff_ratio_from_quality_and_cost(self):
        """Verify payoff ratio computation from quality/cost."""
        sizer = BayesianKellySizer(payoff_default=2.0)
        result = sizer.compute_fraction(
            successes=10, failures=5,
            avg_quality_score=0.8, avg_cost_usd=0.4,
        )
        assert result.payoff_ratio == pytest.approx(2.0, abs=0.01)

    def test_payoff_default_when_no_cost(self):
        """When cost is negligible, use payoff_default."""
        sizer = BayesianKellySizer(payoff_default=3.0)
        result = sizer.compute_fraction(
            successes=10, failures=5,
            avg_quality_score=0.8, avg_cost_usd=0.0,
        )
        assert result.payoff_ratio == 3.0

    def test_raw_fraction_vs_clamped(self):
        """Raw fraction can exceed f_max, but fraction is clamped."""
        sizer = BayesianKellySizer(kappa=0.01, f_max=0.10)
        result = sizer.compute_fraction(successes=100, failures=5)
        assert result.raw_fraction > result.fraction or result.fraction == 0.10
        assert result.fraction <= 0.10


class TestPosteriorStd:
    """Test Beta posterior standard deviation."""

    def test_uniform_prior(self):
        """Beta(1,1) has known std = 1/(2*sqrt(3)) ≈ 0.2887."""
        sizer = BayesianKellySizer()
        std = sizer.get_posterior_std(successes=0, failures=0)
        assert std == pytest.approx(0.2887, abs=0.001)

    def test_strong_evidence_reduces_std(self):
        """Beta(100,100) has std ≈ 0.0353."""
        sizer = BayesianKellySizer()
        std = sizer.get_posterior_std(successes=99, failures=99)
        # alpha=100, beta=100
        expected = math.sqrt(100 * 100 / (200**2 * 201))
        assert std == pytest.approx(expected, abs=0.001)

    def test_asymmetric_prior(self):
        """Beta(91,11) posterior std is small."""
        sizer = BayesianKellySizer()
        std = sizer.get_posterior_std(successes=90, failures=10)
        assert std < 0.05


# ---------------------------------------------------------------------------
# B. Routing weight tests
# ---------------------------------------------------------------------------

class TestRoutingWeights:
    """Test compute_routing_weights normalization and distribution."""

    def test_single_agent_gets_full_weight(self):
        sizer = BayesianKellySizer()
        weights = sizer.compute_routing_weights(
            [{"agent_id": "claude", "successes": 10, "failures": 2,
              "avg_quality_score": 0.8, "avg_cost_usd": 0.01}],
            ["claude"],
        )
        assert weights["claude"] == pytest.approx(1.0)

    def test_two_equal_agents_get_equal_weights(self):
        sizer = BayesianKellySizer()
        weights = sizer.compute_routing_weights(
            [
                {"agent_id": "a", "successes": 20, "failures": 5,
                 "avg_quality_score": 0.8, "avg_cost_usd": 0.01},
                {"agent_id": "b", "successes": 20, "failures": 5,
                 "avg_quality_score": 0.8, "avg_cost_usd": 0.01},
            ],
            ["a", "b"],
        )
        assert weights["a"] == pytest.approx(weights["b"], abs=0.01)

    def test_strong_agent_gets_higher_weight(self):
        sizer = BayesianKellySizer()
        weights = sizer.compute_routing_weights(
            [
                {"agent_id": "strong", "successes": 40, "failures": 5,
                 "avg_quality_score": 0.9, "avg_cost_usd": 0.01},
                {"agent_id": "weak", "successes": 5, "failures": 20,
                 "avg_quality_score": 0.3, "avg_cost_usd": 0.01},
            ],
            ["strong", "weak"],
        )
        assert weights["strong"] > weights["weak"]

    def test_cold_start_uniform(self):
        """No score data — all agents get equal weight."""
        sizer = BayesianKellySizer()
        weights = sizer.compute_routing_weights([], ["a", "b", "c"])
        assert weights["a"] == pytest.approx(1.0 / 3, abs=0.01)
        assert weights["b"] == pytest.approx(1.0 / 3, abs=0.01)
        assert weights["c"] == pytest.approx(1.0 / 3, abs=0.01)

    def test_min_exploration_floor(self):
        """Weak agent gets at least min_exploration_floor."""
        sizer = BayesianKellySizer(min_exploration_floor=0.05)
        weights = sizer.compute_routing_weights(
            [
                {"agent_id": "strong", "successes": 100, "failures": 1,
                 "avg_quality_score": 0.95, "avg_cost_usd": 0.01},
                {"agent_id": "weak", "successes": 1, "failures": 50,
                 "avg_quality_score": 0.1, "avg_cost_usd": 0.01},
            ],
            ["strong", "weak"],
        )
        # weak's raw Kelly = 0, but floor gives it 0.05 pre-normalization
        assert weights["weak"] > 0

    def test_weights_sum_to_one(self):
        sizer = BayesianKellySizer()
        weights = sizer.compute_routing_weights(
            [
                {"agent_id": "a", "successes": 30, "failures": 10,
                 "avg_quality_score": 0.7, "avg_cost_usd": 0.02},
                {"agent_id": "b", "successes": 15, "failures": 20,
                 "avg_quality_score": 0.5, "avg_cost_usd": 0.01},
                {"agent_id": "c", "successes": 50, "failures": 5,
                 "avg_quality_score": 0.9, "avg_cost_usd": 0.03},
            ],
            ["a", "b", "c"],
        )
        assert sum(weights.values()) == pytest.approx(1.0, abs=0.001)

    def test_sample_agent_returns_valid(self):
        """sample_agent returns one of the agents in the weights dict."""
        sizer = BayesianKellySizer()
        weights = {"a": 0.5, "b": 0.3, "c": 0.2}
        for _ in range(20):
            agent = sizer.sample_agent(weights)
            assert agent in weights


# ---------------------------------------------------------------------------
# C. Dispatcher integration tests
# ---------------------------------------------------------------------------

class TestDispatcherKelly:
    """Test Dispatcher with Kelly routing enabled."""

    def _make_dispatcher(self, kelly_sizer=None, repository=None):
        from claw.dispatcher import Dispatcher
        agents = {"claude": object(), "codex": object(), "grok": object()}
        return Dispatcher(
            agents=agents,
            exploration_rate=0.10,
            repository=repository,
            kelly_sizer=kelly_sizer,
        )

    def _make_task(self, task_type="testing", recommended_agent=None):
        from claw.core.models import Task
        return Task(
            id="test-task-1",
            project_id="test-project",
            title="Test task",
            description="A test task",
            task_type=task_type,
            recommended_agent=recommended_agent,
        )

    @pytest.mark.asyncio
    async def test_kelly_routes_to_best_agent(self):
        """With Kelly active and score data, routes based on Kelly weights."""
        sizer = BayesianKellySizer(kappa=5.0)
        repo = AsyncMock()
        repo.get_agent_scores = AsyncMock(return_value=[
            {"agent_id": "claude", "task_type": "testing", "successes": 50, "failures": 2,
             "avg_quality_score": 0.9, "avg_cost_usd": 0.01, "total_attempts": 52},
            {"agent_id": "codex", "task_type": "testing", "successes": 5, "failures": 20,
             "avg_quality_score": 0.3, "avg_cost_usd": 0.01, "total_attempts": 25},
        ])
        dispatcher = self._make_dispatcher(kelly_sizer=sizer, repository=repo)
        task = self._make_task(task_type="testing")

        # Run many times — claude should be selected much more often
        counts = {"claude": 0, "codex": 0, "grok": 0}
        for _ in range(100):
            agent = await dispatcher.route_task(task)
            counts[agent] += 1

        assert counts["claude"] > counts["codex"]

    @pytest.mark.asyncio
    async def test_kelly_falls_through_when_no_data(self):
        """With no score data, Kelly falls through to classic routing."""
        sizer = BayesianKellySizer()
        repo = AsyncMock()
        repo.get_agent_scores = AsyncMock(return_value=[])
        dispatcher = self._make_dispatcher(kelly_sizer=sizer, repository=repo)
        task = self._make_task(task_type="testing")

        # Should not raise; falls through to exploration/static/fallback
        agent = await dispatcher.route_task(task)
        assert agent in ("claude", "codex", "grok")

    @pytest.mark.asyncio
    async def test_kelly_disabled_uses_old_behavior(self):
        """When kelly_sizer is None, classic routing is used."""
        repo = AsyncMock()
        repo.get_agent_scores = AsyncMock(return_value=[])
        dispatcher = self._make_dispatcher(kelly_sizer=None, repository=repo)
        task = self._make_task(task_type="testing")

        agent = await dispatcher.route_task(task)
        assert agent in ("claude", "codex", "grok")

    @pytest.mark.asyncio
    async def test_recommended_agent_overrides_kelly(self):
        """recommended_agent takes priority even with Kelly enabled."""
        sizer = BayesianKellySizer()
        repo = AsyncMock()
        repo.get_agent_scores = AsyncMock(return_value=[
            {"agent_id": "claude", "task_type": "testing", "successes": 100,
             "failures": 0, "avg_quality_score": 1.0, "avg_cost_usd": 0.01,
             "total_attempts": 100},
        ])
        dispatcher = self._make_dispatcher(kelly_sizer=sizer, repository=repo)
        task = self._make_task(task_type="testing", recommended_agent="grok")

        agent = await dispatcher.route_task(task)
        assert agent == "grok"

    def test_routing_info_includes_kelly(self):
        """get_routing_info reports kelly_enabled."""
        sizer = BayesianKellySizer()
        dispatcher = self._make_dispatcher(kelly_sizer=sizer)
        info = dispatcher.get_routing_info("testing")
        assert info["kelly_enabled"] is True

        dispatcher2 = self._make_dispatcher(kelly_sizer=None)
        info2 = dispatcher2.get_routing_info("testing")
        assert info2["kelly_enabled"] is False


# ---------------------------------------------------------------------------
# D. PromptEvolver adaptive margin tests
# ---------------------------------------------------------------------------

class TestAdaptiveMargin:
    """Test Kelly kappa-shrinkage for A/B test win margins."""

    def test_adaptive_margin_low_samples(self):
        """20 samples + kappa=10 → margin should be ~0.10."""
        sizer = BayesianKellySizer(kappa=10.0)
        m = sizer.adaptive_margin(total_samples=20, base_margin=0.15)
        # 20/(20+10) * 0.15 = 0.667 * 0.15 = 0.10
        assert m == pytest.approx(0.10, abs=0.01)

    def test_adaptive_margin_high_samples(self):
        """200 samples + kappa=10 → margin approaches 0.15."""
        sizer = BayesianKellySizer(kappa=10.0)
        m = sizer.adaptive_margin(total_samples=200, base_margin=0.15)
        # 200/210 * 0.15 = 0.952 * 0.15 = 0.143
        assert m == pytest.approx(0.143, abs=0.01)

    def test_adaptive_margin_zero_kappa(self):
        """kappa=0 gives full base_margin immediately."""
        sizer = BayesianKellySizer(kappa=0.0)
        m = sizer.adaptive_margin(total_samples=5, base_margin=0.15)
        assert m == pytest.approx(0.15)

    def test_adaptive_margin_very_high_kappa(self):
        """kappa=1000 keeps margin very low even with moderate samples."""
        sizer = BayesianKellySizer(kappa=1000.0)
        m = sizer.adaptive_margin(total_samples=40, base_margin=0.15)
        # 40/1040 * 0.15 = 0.038 * 0.15 = 0.006
        assert m < 0.01


# ---------------------------------------------------------------------------
# E. Fitness uncertainty discount tests
# ---------------------------------------------------------------------------

class TestFitnessKellyDiscount:
    """Test kelly_posterior_std uncertainty discount in fitness scoring."""

    def _make_methodology(self, successes=10, failures=2):
        from claw.core.models import Methodology
        return Methodology(
            id="test-m-1",
            problem_description="Test methodology",
            solution_code="pass",
            tags=["test", "unit"],
            files_affected=["a.py"],
            scope="global",
            success_count=successes,
            failure_count=failures,
            retrieval_count=5,
            created_at=datetime.now(UTC),
        )

    def test_high_uncertainty_reduces_efficacy(self):
        from claw.memory.fitness import compute_fitness
        m = self._make_methodology()
        _, vec_no_kelly = compute_fitness(m, latest_outcome=True)
        _, vec_kelly = compute_fitness(m, latest_outcome=True, kelly_posterior_std=0.25)

        assert vec_kelly["outcome_efficacy"] < vec_no_kelly["outcome_efficacy"]

    def test_no_kelly_std_backward_compatible(self):
        from claw.memory.fitness import compute_fitness
        m = self._make_methodology()
        score1, vec1 = compute_fitness(m, latest_outcome=True)
        score2, vec2 = compute_fitness(m, latest_outcome=True, kelly_posterior_std=None)

        assert score1 == score2
        assert "kelly_posterior_std" not in vec2

    def test_kelly_std_persists_in_vector(self):
        from claw.memory.fitness import compute_fitness
        m = self._make_methodology()
        _, vec = compute_fitness(m, latest_outcome=True, kelly_posterior_std=0.15)
        assert "kelly_posterior_std" in vec
        assert vec["kelly_posterior_std"] == pytest.approx(0.15, abs=0.01)

    def test_discount_capped_at_30_percent(self):
        """Even with posterior_std > 0.3, discount is capped."""
        from claw.memory.fitness import compute_fitness
        m = self._make_methodology()
        _, vec_30 = compute_fitness(m, latest_outcome=True, kelly_posterior_std=0.30)
        _, vec_50 = compute_fitness(m, latest_outcome=True, kelly_posterior_std=0.50)

        # Both should produce the same efficacy since 0.50 is capped to 0.30
        assert vec_30["outcome_efficacy"] == vec_50["outcome_efficacy"]


# ---------------------------------------------------------------------------
# F. Config tests
# ---------------------------------------------------------------------------

class TestKellyConfig:
    """Test KellyConfig Pydantic model and TOML parsing."""

    def test_defaults(self):
        from claw.core.config import KellyConfig
        cfg = KellyConfig()
        assert cfg.enabled is False
        assert cfg.kappa == 10.0
        assert cfg.f_max == 0.40
        assert cfg.min_exploration_floor == 0.02
        assert cfg.payoff_default == 2.0
        assert cfg.prior_alpha == 1.0
        assert cfg.prior_beta == 1.0

    def test_disabled_by_default(self):
        from claw.core.config import KellyConfig
        cfg = KellyConfig()
        assert cfg.enabled is False

    def test_custom_values(self):
        from claw.core.config import KellyConfig
        cfg = KellyConfig(enabled=True, kappa=30.0, f_max=0.5)
        assert cfg.enabled is True
        assert cfg.kappa == 30.0
        assert cfg.f_max == 0.5

    def test_kelly_on_clawconfig(self):
        from claw.core.config import ClawConfig
        cfg = ClawConfig()
        assert hasattr(cfg, "kelly")
        assert cfg.kelly.enabled is False

    def test_evolution_ab_test_kappa(self):
        from claw.core.config import EvolutionConfig
        cfg = EvolutionConfig()
        assert cfg.ab_test_kappa == 10.0

    def test_load_from_toml(self):
        """Load config from the actual claw.toml to verify parsing."""
        from pathlib import Path
        from claw.core.config import load_config
        toml_path = Path(__file__).parent.parent / "claw.toml"
        if toml_path.exists():
            cfg = load_config(toml_path)
            assert hasattr(cfg, "kelly")
            assert cfg.kelly.kappa == 10.0
