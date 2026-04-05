"""RL-based methodology selection using epsilon-greedy with Thompson sampling.

The MethodologyBandit sits between HybridSearch retrieval and agent dispatch.
It decides which retrieved methodology to present as the primary recommendation,
balancing exploitation (use what has worked) with exploration (try under-tested
methods to learn their value).

Progression:
  - Cold start (<3 total outcomes): 20% explore probability
  - Warm start (3-4 per task_type): epsilon-greedy (10% explore)
  - Data-rich (≥5 per task_type): Thompson sampling from Beta posterior
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("claw.memory.bandit")

# Exploration probabilities
EPSILON_DEFAULT = 0.10       # 10% exploration for warm-start methods
EPSILON_COLD_START = 0.20    # 20% exploration for under-tested methods
COLD_START_THRESHOLD = 3     # Total outcomes below which cold-start applies
THOMPSON_THRESHOLD = 5       # Per-task_type observations needed for Thompson


@dataclass
class BanditCandidate:
    """A methodology candidate with bandit metadata."""

    methodology_id: str
    hybrid_score: float       # Original score from HybridSearch
    fitness: float            # Global fitness score
    successes: int = 0        # Task-type-specific successes
    failures: int = 0         # Task-type-specific failures
    total_outcomes: int = 0   # Global total outcomes (across all task types)
    bandit_score: float = 0.0 # Final score after bandit adjustment


class MethodologyBandit:
    """Epsilon-greedy → Thompson sampling methodology selector.

    Usage:
        bandit = MethodologyBandit()
        selected = bandit.select(candidates, task_type)
    """

    def __init__(
        self,
        epsilon: float = EPSILON_DEFAULT,
        cold_start_epsilon: float = EPSILON_COLD_START,
        cold_start_threshold: int = COLD_START_THRESHOLD,
        thompson_threshold: int = THOMPSON_THRESHOLD,
        seed: Optional[int] = None,
    ) -> None:
        self.epsilon = epsilon
        self.cold_start_epsilon = cold_start_epsilon
        self.cold_start_threshold = cold_start_threshold
        self.thompson_threshold = thompson_threshold
        self._rng = random.Random(seed)

    def select(
        self,
        candidates: list[BanditCandidate],
        task_type: str = "general",
    ) -> Optional[BanditCandidate]:
        """Select the best methodology from candidates using bandit logic.

        Returns the selected candidate with bandit_score set, or None if
        candidates is empty.
        """
        if not candidates:
            return None

        # Score all candidates
        for c in candidates:
            c.bandit_score = self._compute_score(c)

        # Sort by bandit_score descending
        ranked = sorted(candidates, key=lambda c: c.bandit_score, reverse=True)

        # Determine exploration probability
        top = ranked[0]
        explore_prob = self._explore_probability(top)

        # Explore or exploit
        if len(ranked) > 1 and self._rng.random() < explore_prob:
            # Explore: pick uniformly from candidates other than the top
            selected = self._rng.choice(ranked[1:])
            logger.debug(
                "Bandit EXPLORE: skipped %s (score=%.3f), picked %s (score=%.3f)",
                top.methodology_id[:8], top.bandit_score,
                selected.methodology_id[:8], selected.bandit_score,
            )
        else:
            selected = top
            logger.debug(
                "Bandit EXPLOIT: picked %s (score=%.3f)",
                selected.methodology_id[:8], selected.bandit_score,
            )

        return selected

    def _compute_score(self, candidate: BanditCandidate) -> float:
        """Compute bandit-adjusted score for a candidate.

        Uses Thompson sampling when enough data exists, otherwise
        falls back to hybrid_score (which already includes fitness).
        """
        s, f = candidate.successes, candidate.failures
        total_task_type = s + f

        if total_task_type >= self.thompson_threshold:
            # Thompson sampling: draw from Beta posterior
            # Beta(successes + 1, failures + 1) — add-one smoothing
            thompson_draw = self._rng.betavariate(s + 1, f + 1)
            # Blend Thompson with hybrid score (60% Thompson, 40% hybrid)
            return thompson_draw * 0.6 + candidate.hybrid_score * 0.4
        else:
            # Not enough task-type data: use hybrid score directly
            # (hybrid_score already includes global fitness at 40% weight)
            return candidate.hybrid_score

    def _explore_probability(self, candidate: BanditCandidate) -> float:
        """Return exploration probability based on data richness."""
        if candidate.total_outcomes < self.cold_start_threshold:
            return self.cold_start_epsilon
        return self.epsilon

    def rank_all(
        self,
        candidates: list[BanditCandidate],
    ) -> list[BanditCandidate]:
        """Score and rank all candidates without selection randomness.

        Useful for getting a deterministic ranking for context methods.
        """
        for c in candidates:
            c.bandit_score = self._compute_score(c)
        return sorted(candidates, key=lambda c: c.bandit_score, reverse=True)


async def build_bandit_candidates(
    search_results: list[Any],
    repository: Any,
    task_type: str = "general",
) -> list[BanditCandidate]:
    """Convert HybridSearch results to BanditCandidates with stats.

    Args:
        search_results: List of HybridSearchResult from semantic memory.
        repository: ClawRepository for fetching bandit stats.
        task_type: The task type for task-specific bandit stats.

    Returns:
        List of BanditCandidate with bandit stats populated.
    """
    if not search_results:
        return []

    methodology_ids = [
        s.methodology.id for s in search_results
        if s.methodology is not None
    ]

    # Batch fetch bandit stats
    bandit_stats = await repository.get_bandit_stats_batch(methodology_ids, task_type)

    candidates = []
    for s in search_results:
        if s.methodology is None:
            continue
        meth = s.methodology
        meth_id = meth.id
        successes, failures = bandit_stats.get(meth_id, (0, 0))

        # Total outcomes across all task types: use success_count + failure_count
        # from the methodology itself (already tracked in the methodologies table)
        total_outcomes = getattr(meth, "success_count", 0) + getattr(meth, "failure_count", 0)

        candidates.append(BanditCandidate(
            methodology_id=meth_id,
            hybrid_score=getattr(s, "combined_score", 0.0),
            fitness=getattr(meth, "fitness_score", 0.0) or 0.0,
            successes=successes,
            failures=failures,
            total_outcomes=total_outcomes,
        ))

    return candidates
