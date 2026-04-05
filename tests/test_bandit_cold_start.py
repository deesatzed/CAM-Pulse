"""Cold-start behavior validation for MethodologyBandit.

Validates that when all candidates have 0 successes and 0 failures,
the bandit falls back to selecting the candidate with the highest
hybrid_score (retrieval/combined score) rather than random selection.

Also validates that Thompson sampling uses Beta(1,1) as the uniform prior
when there are no observations, and that Beta(1,1) is only reachable
once the thompson_threshold is met.
"""

from __future__ import annotations

import statistics

import pytest

from claw.memory.bandit import (
    BanditCandidate,
    MethodologyBandit,
)


def _make_cold_candidate(
    mid: str,
    hybrid_score: float,
    fitness: float = 0.5,
) -> BanditCandidate:
    """Create a candidate with zero observations (cold-start state)."""
    return BanditCandidate(
        methodology_id=mid,
        hybrid_score=hybrid_score,
        fitness=fitness,
        successes=0,
        failures=0,
        total_outcomes=0,
        bandit_score=0.0,
    )


class TestColdStartScoreFallback:
    """When all candidates have 0 successes / 0 failures, the bandit
    must compute bandit_score = hybrid_score (no Thompson draw)
    so that the highest hybrid_score candidate is deterministically
    selected on the exploit path."""

    def test_cold_start_score_equals_hybrid_score(self):
        """_compute_score with 0/0 observations must return hybrid_score exactly."""
        bandit = MethodologyBandit(seed=42)
        for hs in [0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
            c = _make_cold_candidate("test", hybrid_score=hs)
            score = bandit._compute_score(c)
            assert score == hs, (
                f"Expected bandit_score={hs} for cold candidate, got {score}"
            )

    def test_cold_start_exploit_picks_highest_hybrid(self):
        """With epsilon=0 (always exploit), the cold-start bandit must
        pick the candidate with the highest hybrid_score."""
        bandit = MethodologyBandit(epsilon=0.0, cold_start_epsilon=0.0, seed=42)
        candidates = [
            _make_cold_candidate("low", hybrid_score=0.30),
            _make_cold_candidate("mid", hybrid_score=0.55),
            _make_cold_candidate("high", hybrid_score=0.92),
            _make_cold_candidate("med", hybrid_score=0.60),
        ]
        result = bandit.select(candidates)
        assert result is not None
        assert result.methodology_id == "high"
        assert result.bandit_score == 0.92

    def test_cold_start_exploit_deterministic_across_seeds(self):
        """Exploit selection at cold start is not random --
        it must always select the highest hybrid_score regardless of seed."""
        candidates_data = [
            ("alpha", 0.40),
            ("beta", 0.85),
            ("gamma", 0.60),
            ("delta", 0.70),
        ]
        for seed in [0, 1, 7, 42, 99, 123, 999, 2026]:
            bandit = MethodologyBandit(
                epsilon=0.0, cold_start_epsilon=0.0, seed=seed
            )
            candidates = [
                _make_cold_candidate(mid, hybrid_score=hs)
                for mid, hs in candidates_data
            ]
            result = bandit.select(candidates)
            assert result is not None
            assert result.methodology_id == "beta", (
                f"Seed {seed}: expected beta (highest hybrid=0.85), "
                f"got {result.methodology_id} (score={result.bandit_score})"
            )

    def test_cold_start_rank_all_ordered_by_hybrid(self):
        """rank_all() at cold start must order by hybrid_score descending."""
        bandit = MethodologyBandit(seed=42)
        candidates = [
            _make_cold_candidate("c", hybrid_score=0.3),
            _make_cold_candidate("a", hybrid_score=0.9),
            _make_cold_candidate("d", hybrid_score=0.1),
            _make_cold_candidate("b", hybrid_score=0.6),
        ]
        ranked = bandit.rank_all(candidates)
        ids = [c.methodology_id for c in ranked]
        scores = [c.bandit_score for c in ranked]
        assert ids == ["a", "b", "c", "d"]
        assert scores == [0.9, 0.6, 0.3, 0.1]

    def test_cold_start_rank_all_deterministic_across_seeds(self):
        """rank_all() ordering at cold start must not vary with seed."""
        candidates_data = [("x", 0.2), ("y", 0.8), ("z", 0.5)]
        expected_order = ["y", "z", "x"]
        for seed in [0, 42, 100, 777]:
            bandit = MethodologyBandit(seed=seed)
            candidates = [
                _make_cold_candidate(mid, hybrid_score=hs)
                for mid, hs in candidates_data
            ]
            ranked = bandit.rank_all(candidates)
            assert [c.methodology_id for c in ranked] == expected_order

    def test_cold_start_single_candidate(self):
        """A single cold-start candidate must be returned even with exploration enabled."""
        bandit = MethodologyBandit(
            epsilon=1.0, cold_start_epsilon=1.0, seed=42
        )
        c = _make_cold_candidate("solo", hybrid_score=0.75)
        result = bandit.select([c])
        assert result is not None
        assert result.methodology_id == "solo"
        assert result.bandit_score == 0.75

    def test_empty_candidates_returns_none(self):
        """Empty candidate list returns None."""
        bandit = MethodologyBandit(seed=42)
        assert bandit.select([]) is None


class TestColdStartExploration:
    """Cold-start exploration behavior: when total_outcomes < threshold,
    the exploration probability is elevated."""

    def test_cold_start_explore_probability(self):
        """All zero-outcome candidates should yield cold_start_epsilon."""
        bandit = MethodologyBandit(
            epsilon=0.10,
            cold_start_epsilon=0.20,
            cold_start_threshold=3,
        )
        cold = _make_cold_candidate("cold", hybrid_score=0.8)
        assert bandit._explore_probability(cold) == 0.20

    def test_warm_start_explore_probability(self):
        """Candidates with outcomes >= threshold use regular epsilon."""
        bandit = MethodologyBandit(
            epsilon=0.10,
            cold_start_epsilon=0.20,
            cold_start_threshold=3,
        )
        warm = BanditCandidate(
            methodology_id="warm",
            hybrid_score=0.8,
            fitness=0.5,
            successes=2,
            failures=1,
            total_outcomes=5,
        )
        assert bandit._explore_probability(warm) == 0.10

    def test_cold_start_exploration_rate_statistical(self):
        """Over many trials, cold-start explore rate matches cold_start_epsilon."""
        bandit = MethodologyBandit(
            epsilon=0.10,
            cold_start_epsilon=0.20,
            cold_start_threshold=3,
            seed=42,
        )
        candidates = [
            _make_cold_candidate("top", hybrid_score=0.9),
            _make_cold_candidate("other", hybrid_score=0.5),
        ]
        explore_count = 0
        n = 2000
        for _ in range(n):
            result = bandit.select(candidates)
            if result and result.methodology_id == "other":
                explore_count += 1
        rate = explore_count / n
        # Should be ~20% +/- 5%
        assert 0.15 < rate < 0.27, (
            f"Cold-start explore rate {rate:.2%} outside expected ~20% range"
        )

    def test_cold_start_explore_never_returns_none(self):
        """Exploration should never return None -- it picks a non-top candidate."""
        bandit = MethodologyBandit(
            epsilon=1.0, cold_start_epsilon=1.0, seed=42
        )
        candidates = [
            _make_cold_candidate("a", hybrid_score=0.9),
            _make_cold_candidate("b", hybrid_score=0.1),
        ]
        for _ in range(100):
            result = bandit.select(candidates)
            assert result is not None

    def test_explore_at_boundary_outcomes(self):
        """At total_outcomes == cold_start_threshold - 1, still cold start.
        At total_outcomes == cold_start_threshold, transitions to warm."""
        bandit = MethodologyBandit(
            epsilon=0.10,
            cold_start_epsilon=0.30,
            cold_start_threshold=3,
        )
        # Just below threshold
        at_boundary = BanditCandidate(
            methodology_id="boundary",
            hybrid_score=0.7,
            fitness=0.5,
            successes=1,
            failures=1,
            total_outcomes=2,  # < 3
        )
        assert bandit._explore_probability(at_boundary) == 0.30

        # At threshold
        at_threshold = BanditCandidate(
            methodology_id="threshold",
            hybrid_score=0.7,
            fitness=0.5,
            successes=2,
            failures=1,
            total_outcomes=3,  # == 3, NOT < 3
        )
        assert bandit._explore_probability(at_threshold) == 0.10


class TestThompsonBetaPrior:
    """Validate that Thompson sampling uses Beta(1,1) as the uniform prior
    (i.e., Beta(successes+1, failures+1) with add-one smoothing)."""

    def test_beta_1_1_prior_unreachable_at_zero_observations(self):
        """With 0 successes and 0 failures, the thompson_threshold guard
        prevents Thompson sampling from being used. The fallback
        returns hybrid_score directly."""
        bandit = MethodologyBandit(
            epsilon=0.0, thompson_threshold=5, seed=42
        )
        c = _make_cold_candidate("zero-obs", hybrid_score=0.65)
        score = bandit._compute_score(c)
        assert score == 0.65

    def test_beta_prior_applied_at_threshold(self):
        """When successes=0, failures=0 but we force thompson_threshold=0,
        Thompson sampling draws from Beta(0+1, 0+1) = Beta(1,1),
        which has mean=0.5. Over many draws, the average blended score
        should be approximately 0.5*0.6 + hybrid*0.4."""
        bandit = MethodologyBandit(
            epsilon=0.0, thompson_threshold=0, seed=42
        )
        c = _make_cold_candidate("forced-thompson", hybrid_score=0.5)
        draws = [bandit._compute_score(c) for _ in range(5000)]
        mean_score = statistics.mean(draws)
        # Beta(1,1) mean = 0.5; blended = 0.5*0.6 + 0.5*0.4 = 0.50
        assert 0.45 < mean_score < 0.55, (
            f"Mean Thompson score {mean_score:.4f} outside Beta(1,1) expected range"
        )

    def test_beta_prior_variance_is_uniform(self):
        """Beta(1,1) is the uniform distribution on [0,1] with variance=1/12.
        The blended score = draw*0.6 + hybrid*0.4, so its variance around
        the mean should reflect uniform-like spread from the Thompson draw."""
        bandit = MethodologyBandit(
            epsilon=0.0, thompson_threshold=0, seed=42
        )
        c = _make_cold_candidate("variance-test", hybrid_score=0.5)
        draws = [bandit._compute_score(c) for _ in range(5000)]
        stdev = statistics.stdev(draws)
        # Beta(1,1) stdev = sqrt(1/12) ~ 0.289; after 0.6 scaling: ~0.173
        assert 0.12 < stdev < 0.22, (
            f"Thompson stdev {stdev:.4f} doesn't match Beta(1,1) uniform prior"
        )

    def test_strong_posterior_concentrates_scores(self):
        """With many successes, Beta(s+1, f+1) concentrates near s/(s+f),
        confirming the +1 add-one smoothing is applied correctly."""
        bandit = MethodologyBandit(
            epsilon=0.0, thompson_threshold=5, seed=42
        )
        c = BanditCandidate(
            methodology_id="strong",
            hybrid_score=0.5,
            fitness=0.7,
            successes=50,
            failures=5,
            total_outcomes=55,
        )
        draws = [bandit._compute_score(c) for _ in range(2000)]
        mean_score = statistics.mean(draws)
        stdev = statistics.stdev(draws)
        # Beta(51, 6) mean = 51/57 ~ 0.895
        # Blended mean ~ 0.895*0.6 + 0.5*0.4 = 0.737
        assert 0.70 < mean_score < 0.78, (
            f"Strong posterior mean {mean_score:.4f} outside expected range"
        )
        assert stdev < 0.05, (
            f"Strong posterior stdev {stdev:.4f} too wide for 55 observations"
        )


class TestColdStartTieBreaking:
    """When cold-start candidates have identical hybrid_scores,
    the bandit must still return one (not None) and it should be
    deterministic for a given seed (sorted-order stable)."""

    def test_tied_hybrid_scores_returns_one(self):
        """All candidates at same hybrid_score: bandit returns a candidate."""
        bandit = MethodologyBandit(epsilon=0.0, cold_start_epsilon=0.0, seed=42)
        candidates = [
            _make_cold_candidate("a", hybrid_score=0.7),
            _make_cold_candidate("b", hybrid_score=0.7),
            _make_cold_candidate("c", hybrid_score=0.7),
        ]
        result = bandit.select(candidates)
        assert result is not None
        assert result.bandit_score == 0.7

    def test_tied_hybrid_scores_deterministic_for_seed(self):
        """Tied candidates with the same seed always produce the same pick."""
        candidates_data = [("x", 0.5), ("y", 0.5), ("z", 0.5)]
        picks = []
        for _ in range(50):
            bandit = MethodologyBandit(
                epsilon=0.0, cold_start_epsilon=0.0, seed=42
            )
            candidates = [
                _make_cold_candidate(mid, hybrid_score=hs)
                for mid, hs in candidates_data
            ]
            result = bandit.select(candidates)
            picks.append(result.methodology_id)
        assert len(set(picks)) == 1


class TestColdStartToWarmTransition:
    """Validate the transition from cold-start to warm-start to Thompson."""

    def test_progression_cold_warm_thompson(self):
        """Track a candidate through the full progression:
        cold (0 outcomes) -> warm (3 outcomes) -> Thompson (5+ outcomes)."""
        bandit = MethodologyBandit(
            epsilon=0.10,
            cold_start_epsilon=0.20,
            cold_start_threshold=3,
            thompson_threshold=5,
            seed=42,
        )

        # Phase 1: Cold start (0 outcomes)
        c = BanditCandidate(
            methodology_id="progressing",
            hybrid_score=0.7,
            fitness=0.6,
            successes=0,
            failures=0,
            total_outcomes=0,
        )
        assert bandit._explore_probability(c) == 0.20
        assert bandit._compute_score(c) == 0.7  # Pure hybrid

        # Phase 2: Warm start (3 outcomes, below Thompson threshold)
        c.successes = 2
        c.failures = 1
        c.total_outcomes = 3
        assert bandit._explore_probability(c) == 0.10  # Regular epsilon
        assert bandit._compute_score(c) == 0.7  # Still pure hybrid (3 < 5)

        # Phase 3: Thompson (5 outcomes)
        c.successes = 4
        c.failures = 1
        c.total_outcomes = 5
        assert bandit._explore_probability(c) == 0.10
        scores = [bandit._compute_score(c) for _ in range(100)]
        unique_scores = set(round(s, 10) for s in scores)
        assert len(unique_scores) > 1, (
            "Thompson phase should produce varied scores, got all identical"
        )

    def test_at_exact_thompson_threshold(self):
        """At exactly thompson_threshold observations, Thompson kicks in."""
        bandit = MethodologyBandit(
            epsilon=0.0, thompson_threshold=5, seed=42
        )
        c = BanditCandidate(
            methodology_id="exact",
            hybrid_score=0.5,
            fitness=0.6,
            successes=3,
            failures=2,
            total_outcomes=5,
        )
        scores = [bandit._compute_score(c) for _ in range(100)]
        unique_scores = set(round(s, 10) for s in scores)
        assert len(unique_scores) > 1, (
            "At exact threshold, Thompson should be active (varied scores)"
        )

    def test_just_below_thompson_threshold(self):
        """At thompson_threshold - 1, still uses hybrid_score."""
        bandit = MethodologyBandit(
            epsilon=0.0, thompson_threshold=5, seed=42
        )
        c = BanditCandidate(
            methodology_id="below",
            hybrid_score=0.65,
            fitness=0.6,
            successes=3,
            failures=1,
            total_outcomes=4,
        )
        scores = [bandit._compute_score(c) for _ in range(100)]
        assert all(s == 0.65 for s in scores), (
            "Below Thompson threshold, score must always equal hybrid_score"
        )
