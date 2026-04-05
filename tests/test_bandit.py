"""Tests for MethodologyBandit — RL-based methodology selection."""

from __future__ import annotations

import pytest

from claw.memory.bandit import (
    BanditCandidate,
    MethodologyBandit,
)


def _make_candidate(
    mid: str = "meth-001",
    hybrid_score: float = 0.8,
    fitness: float = 0.7,
    successes: int = 0,
    failures: int = 0,
    total_outcomes: int = 0,
) -> BanditCandidate:
    return BanditCandidate(
        methodology_id=mid,
        hybrid_score=hybrid_score,
        fitness=fitness,
        successes=successes,
        failures=failures,
        total_outcomes=total_outcomes,
    )


class TestBanditExploitExplore:
    """Test exploitation vs exploration behavior."""

    def test_single_candidate_returns_it(self):
        bandit = MethodologyBandit(seed=42)
        c = _make_candidate("only-one", hybrid_score=0.9)
        result = bandit.select([c])
        assert result is not None
        assert result.methodology_id == "only-one"

    def test_empty_candidates_returns_none(self):
        bandit = MethodologyBandit(seed=42)
        assert bandit.select([]) is None

    def test_exploit_picks_highest_score(self):
        """With seed that avoids exploration, top scorer should be picked."""
        bandit = MethodologyBandit(epsilon=0.0, seed=42)  # 0% explore = always exploit
        candidates = [
            _make_candidate("low", hybrid_score=0.3, total_outcomes=5),
            _make_candidate("high", hybrid_score=0.9, total_outcomes=5),
            _make_candidate("mid", hybrid_score=0.6, total_outcomes=5),
        ]
        result = bandit.select(candidates)
        assert result is not None
        assert result.methodology_id == "high"

    def test_explore_picks_non_top(self):
        """With epsilon=1.0, should always explore (pick non-top)."""
        bandit = MethodologyBandit(epsilon=1.0, seed=42)
        candidates = [
            _make_candidate("top", hybrid_score=0.95, total_outcomes=5),
            _make_candidate("second", hybrid_score=0.5, total_outcomes=5),
            _make_candidate("third", hybrid_score=0.3, total_outcomes=5),
        ]
        result = bandit.select(candidates)
        assert result is not None
        assert result.methodology_id != "top"

    def test_exploration_rate_approximately_correct(self):
        """Over many trials, explore ~10% of the time."""
        bandit = MethodologyBandit(epsilon=0.10, seed=123)
        candidates = [
            _make_candidate("top", hybrid_score=0.95, total_outcomes=5),
            _make_candidate("other", hybrid_score=0.5, total_outcomes=5),
        ]
        explore_count = 0
        n = 1000
        for _ in range(n):
            result = bandit.select(candidates)
            if result and result.methodology_id == "other":
                explore_count += 1
        # Should be roughly 10% ± 3% (generous tolerance for randomness)
        rate = explore_count / n
        assert 0.05 < rate < 0.18, f"Explore rate {rate:.2%} outside expected range"


class TestBanditColdStart:
    """Test cold-start protection for under-tested methods."""

    def test_cold_start_higher_explore(self):
        """Methods with <3 total outcomes should use higher explore probability."""
        bandit = MethodologyBandit(
            epsilon=0.10,
            cold_start_epsilon=0.50,
            cold_start_threshold=3,
            seed=99,
        )
        # Cold-start candidate (0 outcomes)
        cold = _make_candidate("cold", hybrid_score=0.9, total_outcomes=0)
        prob = bandit._explore_probability(cold)
        assert prob == 0.50

        # Warm candidate (5 outcomes)
        warm = _make_candidate("warm", hybrid_score=0.9, total_outcomes=5)
        prob = bandit._explore_probability(warm)
        assert prob == 0.10


class TestThompsonSampling:
    """Test Thompson sampling when enough data exists."""

    def test_thompson_with_strong_success_wins(self):
        """A method with many successes should score high via Thompson."""
        bandit = MethodologyBandit(epsilon=0.0, thompson_threshold=5, seed=42)
        candidates = [
            _make_candidate(
                "good", hybrid_score=0.5, successes=20, failures=2, total_outcomes=22
            ),
            _make_candidate(
                "bad", hybrid_score=0.5, successes=2, failures=20, total_outcomes=22
            ),
        ]
        # Run multiple times — "good" should win most
        good_wins = sum(
            1 for _ in range(100)
            if bandit.select(candidates).methodology_id == "good"
        )
        assert good_wins > 80, f"Good won only {good_wins}/100"

    def test_thompson_not_used_below_threshold(self):
        """Below threshold, score should equal hybrid_score."""
        bandit = MethodologyBandit(epsilon=0.0, thompson_threshold=5, seed=42)
        c = _make_candidate(
            "sparse", hybrid_score=0.75, successes=2, failures=1, total_outcomes=3
        )
        score = bandit._compute_score(c)
        # Below threshold: should return hybrid_score directly
        assert score == 0.75

    def test_thompson_used_above_threshold(self):
        """Above threshold, score should differ from pure hybrid_score."""
        bandit = MethodologyBandit(epsilon=0.0, thompson_threshold=5, seed=42)
        c = _make_candidate(
            "rich", hybrid_score=0.5, successes=10, failures=2, total_outcomes=12
        )
        score = bandit._compute_score(c)
        # Thompson blend: 60% Beta draw + 40% hybrid = different from 0.5
        # With 10 successes, 2 failures, Beta(11, 3) mean ~0.79
        # Blended: 0.79*0.6 + 0.5*0.4 = ~0.67
        assert score != 0.5


class TestRankAll:
    """Test deterministic ranking (no exploration randomness)."""

    def test_rank_all_ordered_by_score(self):
        bandit = MethodologyBandit(seed=42)
        candidates = [
            _make_candidate("low", hybrid_score=0.3),
            _make_candidate("high", hybrid_score=0.9),
            _make_candidate("mid", hybrid_score=0.6),
        ]
        ranked = bandit.rank_all(candidates)
        assert [c.methodology_id for c in ranked] == ["high", "mid", "low"]

    def test_rank_all_sets_bandit_scores(self):
        bandit = MethodologyBandit(seed=42)
        candidates = [_make_candidate("a", hybrid_score=0.7)]
        ranked = bandit.rank_all(candidates)
        assert ranked[0].bandit_score > 0


class TestBanditCandidateDataclass:
    """Test BanditCandidate initialization."""

    def test_defaults(self):
        c = BanditCandidate(
            methodology_id="test",
            hybrid_score=0.5,
            fitness=0.4,
        )
        assert c.successes == 0
        assert c.failures == 0
        assert c.total_outcomes == 0
        assert c.bandit_score == 0.0


class TestBuildBanditCandidates:
    """Test build_bandit_candidates async helper."""

    @pytest.mark.asyncio
    async def test_empty_results(self):
        from claw.memory.bandit import build_bandit_candidates

        result = await build_bandit_candidates([], None, "general")
        assert result == []

    @pytest.mark.asyncio
    async def test_builds_from_search_results(self):
        from claw.memory.bandit import build_bandit_candidates
        from unittest.mock import AsyncMock, MagicMock

        # Create mock search result
        methodology = MagicMock()
        methodology.id = "meth-123"
        methodology.success_count = 5
        methodology.failure_count = 2
        methodology.fitness_score = 0.75

        search_result = MagicMock()
        search_result.methodology = methodology
        search_result.combined_score = 0.85

        # Create mock repository
        repo = AsyncMock()
        repo.get_bandit_stats_batch.return_value = {
            "meth-123": (3, 1)
        }

        candidates = await build_bandit_candidates(
            [search_result], repo, "architecture"
        )

        assert len(candidates) == 1
        assert candidates[0].methodology_id == "meth-123"
        assert candidates[0].hybrid_score == 0.85
        assert candidates[0].fitness == 0.75
        assert candidates[0].successes == 3
        assert candidates[0].failures == 1
        assert candidates[0].total_outcomes == 7  # 5 + 2
        repo.get_bandit_stats_batch.assert_called_once_with(
            ["meth-123"], "architecture"
        )
