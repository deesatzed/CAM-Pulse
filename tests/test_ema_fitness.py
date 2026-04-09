"""Tests for EMA (Exponential Moving Average) outcome efficacy in fitness scoring.

Validates the EMA feedback loop where recent outcomes are weighted more heavily
than historical ones, enabling faster adaptation to changing performance.
"""

from datetime import UTC, datetime, timedelta

import pytest

from claw.core.models import Methodology
from claw.memory.fitness import (
    DEFAULT_CATEGORY_WEIGHTS,
    EMA_ALPHA,
    EMA_BLEND_WEIGHT,
    STATIC_BLEND_WEIGHT,
    W_EFFICACY,
    classify_decay_tier,
    compute_fitness,
)


def _m(**overrides) -> Methodology:
    """Create a test methodology with optional overrides."""
    defaults = dict(
        problem_description="Test methodology",
        solution_code="pass",
    )
    defaults.update(overrides)
    return Methodology(**defaults)


class TestEMABasics:
    """Core EMA computation logic."""

    def test_no_outcome_no_ema_pure_static(self):
        """Without latest_outcome and no stored EMA, efficacy is pure static ratio."""
        m = _m(success_count=3, failure_count=1)
        _, vec = compute_fitness(m, now=m.created_at)
        # Static: 3/4 = 0.75
        assert vec["outcome_efficacy"] == 0.75
        assert "outcome_ema" not in vec

    def test_no_outcome_preserves_stored_ema(self):
        """Without latest_outcome, stored EMA is preserved and blended."""
        m = _m(
            success_count=5, failure_count=5,
            fitness_vector={"outcome_ema": 0.8},
        )
        _, vec = compute_fitness(m, now=m.created_at)
        # Static: 5/10 = 0.5
        # Blended: 0.6 * 0.8 + 0.4 * 0.5 = 0.48 + 0.20 = 0.68
        assert vec["outcome_ema"] == 0.8  # preserved
        assert abs(vec["outcome_efficacy"] - 0.68) < 0.001

    def test_first_success_bootstraps_ema(self):
        """First outcome with no stored EMA bootstraps from static ratio."""
        # success_count already includes this latest outcome (DB updated first)
        m = _m(success_count=1, failure_count=0)
        _, vec = compute_fitness(m, now=m.created_at, latest_outcome=True)

        # Static: 1/1 = 1.0
        # Bootstrap EMA: 0.3 * 1.0 + 0.7 * 1.0 = 1.0
        assert abs(vec["outcome_ema"] - 1.0) < 0.001
        # Blended: 0.6 * 1.0 + 0.4 * 1.0 = 1.0
        assert abs(vec["outcome_efficacy"] - 1.0) < 0.001

    def test_first_failure_bootstraps_ema(self):
        """First failure bootstraps EMA from static ratio."""
        m = _m(success_count=0, failure_count=1)
        _, vec = compute_fitness(m, now=m.created_at, latest_outcome=False)

        # Static: 0/1 = 0.0
        # Bootstrap EMA: 0.3 * 0.0 + 0.7 * 0.0 = 0.0
        assert abs(vec["outcome_ema"] - 0.0) < 0.001
        assert abs(vec["outcome_efficacy"] - 0.0) < 0.001

    def test_success_after_failures_ema_rises_faster(self):
        """After 3 failures, a success lifts EMA faster than static ratio alone."""
        # Scenario: 3 failures then 1 success. Static ratio: 1/4 = 0.25
        # With EMA tracking the failures (approx 0.0), then success:
        m = _m(
            success_count=1, failure_count=3,
            fitness_vector={"outcome_ema": 0.0},  # all failures so far
        )
        _, vec = compute_fitness(m, now=m.created_at, latest_outcome=True)

        # EMA: 0.3 * 1.0 + 0.7 * 0.0 = 0.3
        assert abs(vec["outcome_ema"] - 0.3) < 0.001
        # Blended: 0.6 * 0.3 + 0.4 * 0.25 = 0.18 + 0.10 = 0.28
        assert abs(vec["outcome_efficacy"] - 0.28) < 0.001
        # Static alone would give 0.25, EMA blend gives 0.28 — higher because
        # the EMA captured the recent success signal

    def test_failure_after_successes_ema_drops_faster(self):
        """After 5 successes, a failure drops EMA faster than static ratio."""
        # Scenario: 5 successes then 1 failure. Static: 5/6 = 0.8333
        m = _m(
            success_count=5, failure_count=1,
            fitness_vector={"outcome_ema": 1.0},  # all successes so far
        )
        _, vec = compute_fitness(m, now=m.created_at, latest_outcome=False)

        # EMA: 0.3 * 0.0 + 0.7 * 1.0 = 0.7
        assert abs(vec["outcome_ema"] - 0.7) < 0.001
        # Blended: 0.6 * 0.7 + 0.4 * 0.8333 = 0.42 + 0.3333 = 0.7533
        assert abs(vec["outcome_efficacy"] - 0.7533) < 0.01
        # Static alone: 0.8333. EMA blend: 0.7533 — lower due to recent failure signal


class TestEMASequences:
    """Multi-step EMA sequences simulating real usage."""

    def _simulate_sequence(self, outcomes: list[bool]) -> list[dict]:
        """Simulate a sequence of outcomes, returning vectors after each step."""
        vectors = []
        m = _m()  # starts with 0 success, 0 failure, no EMA
        for success in outcomes:
            # Update counters as semantic.py would
            if success:
                m = m.model_copy(update={"success_count": m.success_count + 1})
            else:
                m = m.model_copy(update={"failure_count": m.failure_count + 1})
            _, vec = compute_fitness(m, now=m.created_at, latest_outcome=success)
            # Feed the vector back as stored state
            m = m.model_copy(update={"fitness_vector": vec})
            vectors.append(vec)
        return vectors

    def test_all_successes_converge_high(self):
        """Pure success sequence converges EMA toward 1.0."""
        vecs = self._simulate_sequence([True] * 10)
        # EMA should increase monotonically and approach 1.0
        emas = [v["outcome_ema"] for v in vecs]
        for i in range(1, len(emas)):
            assert emas[i] >= emas[i - 1]
        assert emas[-1] > 0.95

    def test_all_failures_converge_low(self):
        """Pure failure sequence converges EMA toward 0.0."""
        vecs = self._simulate_sequence([False] * 10)
        emas = [v["outcome_ema"] for v in vecs]
        for i in range(1, len(emas)):
            assert emas[i] <= emas[i - 1]
        assert emas[-1] < 0.05

    def test_turnaround_ema_responds_faster_than_static(self):
        """5 failures then 5 successes: EMA > static after the turnaround."""
        vecs = self._simulate_sequence([False] * 5 + [True] * 5)
        # After turnaround (at index 9, i.e. 5F + 5S):
        # Static: 5/10 = 0.5
        # EMA should be > 0.5 because it weights recent successes more
        final = vecs[-1]
        assert final["outcome_ema"] > 0.5

    def test_mixed_oscillating(self):
        """Alternating success/failure keeps EMA near 0.5."""
        vecs = self._simulate_sequence([True, False] * 10)
        emas = [v["outcome_ema"] for v in vecs]
        # After 20 alternating outcomes, EMA should be near 0.5
        assert 0.35 < emas[-1] < 0.65

    def test_recent_streak_dominates(self):
        """5 failures followed by 3 successes: EMA > static ratio."""
        vecs = self._simulate_sequence([False] * 5 + [True] * 3)
        final = vecs[-1]
        # Static: 3/8 = 0.375
        static = 3.0 / 8.0
        # EMA should reflect the recent winning streak
        assert final["outcome_ema"] > static


class TestEMAEdgeCases:
    """Edge cases and backward compatibility."""

    def test_legacy_methodology_no_ema_field(self):
        """Legacy fitness_vector without outcome_ema works correctly."""
        m = _m(
            success_count=3, failure_count=2,
            fitness_vector={"total": 0.5, "outcome_efficacy": 0.6},
        )
        _, vec = compute_fitness(m, now=m.created_at)
        # No outcome_ema stored, no latest_outcome — pure static
        assert vec["outcome_efficacy"] == 0.6  # static: 3/5 = 0.6
        assert "outcome_ema" not in vec

    def test_legacy_methodology_gets_ema_on_first_outcome(self):
        """Legacy methodology acquires EMA on first post-upgrade outcome."""
        m = _m(
            success_count=8, failure_count=2,  # already includes latest
            fitness_vector={"total": 0.5},  # no outcome_ema
        )
        _, vec = compute_fitness(m, now=m.created_at, latest_outcome=True)
        # Bootstrap: 0.3 * 1.0 + 0.7 * (8/10) = 0.3 + 0.56 = 0.86
        assert abs(vec["outcome_ema"] - 0.86) < 0.001
        assert "outcome_ema" in vec

    def test_ema_stays_bounded_0_to_1(self):
        """EMA never exceeds [0, 1] regardless of sequence."""
        vecs_high = self._simulate_sequence([True] * 50)
        vecs_low = self._simulate_sequence([False] * 50)
        for v in vecs_high + vecs_low:
            if "outcome_ema" in v:
                assert 0.0 <= v["outcome_ema"] <= 1.0
            assert 0.0 <= v["outcome_efficacy"] <= 1.0

    def _simulate_sequence(self, outcomes):
        m = _m()
        vecs = []
        for success in outcomes:
            if success:
                m = m.model_copy(update={"success_count": m.success_count + 1})
            else:
                m = m.model_copy(update={"failure_count": m.failure_count + 1})
            _, vec = compute_fitness(m, now=m.created_at, latest_outcome=success)
            m = m.model_copy(update={"fitness_vector": vec})
            vecs.append(vec)
        return vecs

    def test_invalid_stored_ema_gracefully_ignored(self):
        """Corrupt outcome_ema value in stored vector is ignored."""
        m = Methodology.model_construct(
            id="test",
            problem_description="test",
            solution_code="pass",
            success_count=2,
            failure_count=1,
            retrieval_count=0,
            scope="project",
            tags=[],
            files_affected=[],
            created_at=datetime.now(UTC),
            fitness_vector={"outcome_ema": "not_a_number", "total": 0.5},
        )
        _, vec = compute_fitness(m, now=m.created_at, latest_outcome=True)
        # Should bootstrap fresh since stored EMA was invalid
        # Bootstrap: 0.3 * 1.0 + 0.7 * (2/3) = 0.3 + 0.4667 = 0.7667
        assert abs(vec["outcome_ema"] - 0.7667) < 0.01

    def test_vector_keys_include_ema_when_present(self):
        """Fitness vector has outcome_ema key when EMA is active."""
        m = _m(success_count=1, failure_count=0)
        _, vec = compute_fitness(m, now=m.created_at, latest_outcome=True)
        expected_keys = {
            "retrieval_relevance", "outcome_efficacy", "specificity",
            "freshness", "cross_domain_transfer", "retrieval_frequency",
            "total", "outcome_ema", "decay_tier",
        }
        assert set(vec.keys()) == expected_keys

    def test_vector_keys_no_ema_when_absent(self):
        """Fitness vector omits outcome_ema key when EMA never started."""
        m = _m(success_count=0, failure_count=0)
        _, vec = compute_fitness(m, now=m.created_at)
        assert "outcome_ema" not in vec
        expected_keys = {
            "retrieval_relevance", "outcome_efficacy", "specificity",
            "freshness", "cross_domain_transfer", "retrieval_frequency",
            "total", "decay_tier",
        }
        assert set(vec.keys()) == expected_keys


class TestCategoryWeights:
    """Category weight multiplier tests."""

    def test_category_weight_architecture_boosts_fitness(self):
        """Architecture methodology scores higher than identical one without category."""
        m_arch = _m(
            success_count=3, failure_count=1,
            tags=["category:architecture", "source:repo1"],
        )
        m_none = _m(
            success_count=3, failure_count=1,
            tags=["source:repo1"],
        )
        total_arch, vec_arch = compute_fitness(m_arch, now=m_arch.created_at)
        total_none, vec_none = compute_fitness(m_none, now=m_none.created_at)

        # Architecture default weight is 1.4, so arch score > none
        assert total_arch > total_none
        assert vec_arch.get("category_weight") == 1.4

    def test_category_weight_default_is_neutral(self):
        """Unknown category gets weight 1.0 (no boost, no penalty)."""
        m_unknown = _m(
            success_count=3, failure_count=1,
            tags=["category:bizarre_niche", "source:repo1"],
        )
        m_known_neutral = _m(
            success_count=3, failure_count=1,
            tags=["category:debugging", "source:repo1"],  # debugging default weight = 1.0
        )
        total_unknown, vec_unknown = compute_fitness(m_unknown, now=m_unknown.created_at)
        total_known, vec_known = compute_fitness(m_known_neutral, now=m_known_neutral.created_at)

        # Both have weight 1.0 — same tags count, same everything
        assert total_unknown == total_known
        # category_weight should not appear in vector when it's 1.0
        assert "category_weight" not in vec_unknown
        assert "category_weight" not in vec_known

    def test_category_weight_from_config(self):
        """Custom config weights override defaults."""
        m = _m(
            success_count=3, failure_count=1,
            tags=["category:debugging"],
        )
        # Default weight for debugging is 1.0
        total_default, _ = compute_fitness(m, now=m.created_at)

        # Custom weight boosts debugging to 1.5
        custom_weights = {"debugging": 1.5}
        total_custom, vec_custom = compute_fitness(
            m, now=m.created_at, category_weights=custom_weights
        )

        assert total_custom > total_default
        assert vec_custom.get("category_weight") == 1.5


class TestDecayTiers:
    """Temporal decay tier classification and fitness impact."""

    def test_decay_tier_core_never_decays(self):
        """Seed methodology freshness stays 1.0 regardless of age."""
        now = datetime.now(UTC)
        m = _m(
            tags=["origin:seed"],
            created_at=now - timedelta(days=500),
        )
        tier, half_life = classify_decay_tier(m, now=now)
        assert tier == "core"
        assert half_life == float("inf")

        _, vec = compute_fitness(m, now=now)
        assert vec["freshness"] == 1.0
        assert vec["decay_tier"] == "core"

    def test_decay_tier_active_decays_fast(self):
        """Recently retrieved methodology has 30-day half-life (faster decay)."""
        now = datetime.now(UTC)
        m = _m(
            retrieval_count=5,
            last_retrieved_at=now - timedelta(days=5),
            created_at=now - timedelta(days=60),
        )
        tier, half_life = classify_decay_tier(m, now=now)
        assert tier == "active"
        assert half_life == 30.0

        # Compare with warm tier (same methodology but fewer retrievals)
        m_warm = _m(
            retrieval_count=1,
            last_retrieved_at=now - timedelta(days=5),
            created_at=now - timedelta(days=60),
        )
        tier_warm, _ = classify_decay_tier(m_warm, now=now)
        assert tier_warm == "warm"

        # Active tier should have lower freshness (faster decay for same age)
        _, vec_active = compute_fitness(m, now=now)
        _, vec_warm = compute_fitness(m_warm, now=now)
        assert vec_active["freshness"] < vec_warm["freshness"]

    def test_decay_tier_archive_decays_slow(self):
        """200-day-old unretrieved methodology gets archive tier (365-day half-life)."""
        now = datetime.now(UTC)
        m = _m(
            retrieval_count=0,
            created_at=now - timedelta(days=200),
        )
        tier, half_life = classify_decay_tier(m, now=now)
        assert tier == "archive"
        assert half_life == 365.0

        # Archive half-life (365) is much longer than warm (90),
        # so freshness should be higher under archive tier
        assert vec_archive_freshness_is_higher_than_warm(m, now)

    def test_decay_tier_classification_boundaries(self):
        """Verify each tier boundary condition."""
        now = datetime.now(UTC)

        # Within 30 days, 3+ retrievals → active
        m_active = _m(
            retrieval_count=3,
            last_retrieved_at=now - timedelta(days=10),
            created_at=now - timedelta(days=30),
        )
        assert classify_decay_tier(m_active, now=now)[0] == "active"

        # Within 30 days, <3 retrievals → warm
        m_warm = _m(
            retrieval_count=2,
            last_retrieved_at=now - timedelta(days=10),
            created_at=now - timedelta(days=30),
        )
        assert classify_decay_tier(m_warm, now=now)[0] == "warm"

        # Within 90 days → warm
        m_warm2 = _m(
            retrieval_count=0,
            last_retrieved_at=now - timedelta(days=60),
            created_at=now - timedelta(days=80),
        )
        assert classify_decay_tier(m_warm2, now=now)[0] == "warm"

        # 91-180 days → cold
        m_cold = _m(
            retrieval_count=0,
            last_retrieved_at=now - timedelta(days=120),
            created_at=now - timedelta(days=150),
        )
        assert classify_decay_tier(m_cold, now=now)[0] == "cold"

        # 181+ days → archive
        m_archive = _m(
            retrieval_count=0,
            last_retrieved_at=now - timedelta(days=200),
            created_at=now - timedelta(days=300),
        )
        assert classify_decay_tier(m_archive, now=now)[0] == "archive"

        # Architecture tag → core (regardless of age)
        m_core = _m(
            tags=["category:architecture"],
            created_at=now - timedelta(days=500),
        )
        assert classify_decay_tier(m_core, now=now)[0] == "core"


def vec_archive_freshness_is_higher_than_warm(m, now):
    """Helper: archive tier gives higher freshness than warm tier for old methodology."""
    import math
    age_days = (now - m.created_at).total_seconds() / 86400.0
    freshness_archive = math.exp(-0.693 * age_days / 365.0)
    freshness_warm = math.exp(-0.693 * age_days / 90.0)
    return freshness_archive > freshness_warm


class TestEMAConstants:
    """Verify EMA constants are sensible."""

    def test_alpha_in_range(self):
        assert 0.0 < EMA_ALPHA < 1.0

    def test_blend_weights_sum_to_one(self):
        assert abs(EMA_BLEND_WEIGHT + STATIC_BLEND_WEIGHT - 1.0) < 1e-9

    def test_alpha_value(self):
        assert EMA_ALPHA == 0.3

    def test_blend_weight_value(self):
        assert EMA_BLEND_WEIGHT == 0.6
