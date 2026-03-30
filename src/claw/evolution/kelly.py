"""Bayesian Kelly Criterion position-sizing for agent routing.

Implements Sukhov (2026) equation 13 for optimal agent allocation:

    f* = (p_bar - (1 - p_bar) / b) * n_eff / (n_eff + kappa)

Where:
    p_bar = alpha / (alpha + beta)   -- posterior win rate (Beta conjugate)
    n_eff = alpha + beta             -- effective sample count
    b     = quality payoff ratio     -- reward vs risk
    kappa = robustness shrinkage     -- higher = more conservative
    f_max = hard position cap        -- prevents over-concentration

The shrinkage term n_eff / (n_eff + kappa) ensures conservative fractions
when evidence is scarce, naturally widening as observations accumulate.

Reference:
    Sukhov, S. (2026). Bayesian Kelly Criterion with Parameter Uncertainty:
    A Robust Framework for Position Sizing Under Estimation Risk. Working Paper.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("claw.evolution.kelly")


@dataclass
class KellyResult:
    """Result of a Bayesian Kelly position-sizing computation."""

    fraction: float       # f* clamped to [0, f_max]
    p_bar: float          # posterior mean win rate
    n_eff: float          # effective sample count (alpha + beta)
    posterior_std: float   # uncertainty of posterior estimate
    payoff_ratio: float    # b — quality reward per unit risk
    raw_fraction: float    # f* before clamping


class BayesianKellySizer:
    """Bayesian Kelly Criterion for adaptive agent routing weights.

    Each agent accumulates successes/failures per task type.  This sizer
    computes Kelly fractions that determine what proportion of tasks to
    route to each agent, replacing the static exploration_rate.

    Parameters
    ----------
    kappa : float
        Robustness shrinkage parameter (Sukhov eq. 13).  Higher values
        are more conservative (slower to trust observed win rates).
    f_max : float
        Hard cap on any single agent's routing fraction.
    min_exploration_floor : float
        Minimum sampling probability per agent, preventing starvation.
    payoff_default : float
        Default payoff ratio when cost data is unavailable.
    prior_alpha : float
        Beta prior alpha (1.0 = uniform / uninformative).
    prior_beta : float
        Beta prior beta (1.0 = uniform / uninformative).
    """

    def __init__(
        self,
        kappa: float = 10.0,
        f_max: float = 0.40,
        min_exploration_floor: float = 0.02,
        payoff_default: float = 2.0,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ) -> None:
        self.kappa = kappa
        self.f_max = f_max
        self.min_exploration_floor = min_exploration_floor
        self.payoff_default = payoff_default
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta

    def compute_fraction(
        self,
        successes: int,
        failures: int,
        avg_quality_score: float = 0.5,
        avg_cost_usd: float = 0.0,
    ) -> KellyResult:
        """Compute the Bayesian Kelly fraction for a single agent.

        Parameters
        ----------
        successes : int
            Number of successful task completions.
        failures : int
            Number of failed task completions.
        avg_quality_score : float
            Average quality score on successes (0.0 - 1.0).
        avg_cost_usd : float
            Average cost per task in USD.

        Returns
        -------
        KellyResult with the optimal fraction and diagnostic values.
        """
        alpha = self.prior_alpha + successes
        beta = self.prior_beta + failures
        n_eff = alpha + beta

        p_bar = alpha / n_eff

        # Payoff ratio: quality per unit cost.  When cost is negligible
        # (common with cheap API models), use the default payoff.
        if avg_cost_usd > 0.001 and avg_quality_score > 0.0:
            b = avg_quality_score / avg_cost_usd
        else:
            b = self.payoff_default

        # Clamp b to avoid extreme fractions
        b = max(b, 0.01)

        # Sukhov (2026) eq. 13
        f_base = p_bar - (1.0 - p_bar) / b
        phi = n_eff / (n_eff + self.kappa)  # confidence weight
        raw_fraction = f_base * phi

        fraction = max(0.0, min(self.f_max, raw_fraction))

        std = self._posterior_std(alpha, beta)

        return KellyResult(
            fraction=fraction,
            p_bar=round(p_bar, 6),
            n_eff=round(n_eff, 4),
            posterior_std=round(std, 6),
            payoff_ratio=round(b, 4),
            raw_fraction=round(raw_fraction, 6),
        )

    def compute_routing_weights(
        self,
        agent_scores: list[dict[str, Any]],
        available_agents: list[str],
    ) -> dict[str, float]:
        """Compute normalized routing weights for all agents.

        Parameters
        ----------
        agent_scores : list[dict]
            Score rows from the agent_scores table, each with at least:
            agent_id, successes, failures, avg_quality_score, avg_cost_usd.
        available_agents : list[str]
            All agent IDs that are currently available.

        Returns
        -------
        dict mapping agent_id -> routing probability (sums to 1.0).
        """
        # Index scores by agent_id for fast lookup
        score_by_agent: dict[str, dict[str, Any]] = {}
        for row in agent_scores:
            aid = row.get("agent_id")
            if aid and aid in available_agents:
                score_by_agent[aid] = row

        # Compute Kelly fraction for each agent
        fractions: dict[str, float] = {}
        for agent_id in available_agents:
            row = score_by_agent.get(agent_id)
            if row and (row.get("successes", 0) + row.get("failures", 0)) > 0:
                result = self.compute_fraction(
                    successes=row.get("successes", 0),
                    failures=row.get("failures", 0),
                    avg_quality_score=row.get("avg_quality_score", 0.5),
                    avg_cost_usd=row.get("avg_cost_usd", 0.0),
                )
                fractions[agent_id] = max(result.fraction, self.min_exploration_floor)
            else:
                # No data — assign floor
                fractions[agent_id] = self.min_exploration_floor

        # Normalize to probability distribution
        total = sum(fractions.values())
        if total <= 0:
            # All zeros — uniform
            n = len(available_agents)
            return {aid: 1.0 / n for aid in available_agents}

        return {aid: f / total for aid, f in fractions.items()}

    def sample_agent(
        self,
        weights: dict[str, float],
    ) -> str:
        """Sample an agent from Kelly-weighted distribution.

        Parameters
        ----------
        weights : dict[str, float]
            Agent routing weights (from compute_routing_weights).

        Returns
        -------
        Selected agent_id.
        """
        agents = list(weights.keys())
        probs = [weights[a] for a in agents]
        return random.choices(agents, weights=probs, k=1)[0]

    def adaptive_margin(
        self,
        total_samples: int,
        base_margin: float = 0.15,
    ) -> float:
        """Compute adaptive A/B test win margin using kappa-shrinkage.

        With few samples, the effective margin is high (conservative,
        harder to declare a winner).  As samples grow, the margin
        approaches base_margin.

        Parameters
        ----------
        total_samples : int
            Total samples across both A/B variants.
        base_margin : float
            Asymptotic maximum margin when data is plentiful.

        Returns
        -------
        Adaptive margin for A/B test winner declaration.
        """
        if self.kappa <= 0:
            return base_margin
        n_eff = float(total_samples)
        return base_margin * n_eff / (n_eff + self.kappa)

    @staticmethod
    def _posterior_std(alpha: float, beta: float) -> float:
        """Posterior standard deviation of p ~ Beta(alpha, beta)."""
        n = alpha + beta
        if n <= 0:
            return 0.5  # Maximum uncertainty
        return math.sqrt((alpha * beta) / (n * n * (n + 1)))

    def get_posterior_std(self, successes: int, failures: int) -> float:
        """Compute posterior std for an agent's track record.

        Convenience method for external callers (fitness enrichment).
        """
        alpha = self.prior_alpha + successes
        beta = self.prior_beta + failures
        return self._posterior_std(alpha, beta)
