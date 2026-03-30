"""6-dimensional fitness scoring for methodology memories.

Adapted from xplurx's arena/scoring.py pattern: composite scoring with
weighted dimensions. Each methodology's fitness determines its competitive
standing in the memory ecosystem -- high-fitness memories survive and
reproduce, low-fitness memories decline and die.

Dimensions:
    1. Retrieval Relevance (0.20) -- how relevant this memory is at retrieval time
    2. Outcome Efficacy (0.30) -- EMA-blended success ratio (most important)
    3. Specificity (0.15) -- richness of tags + files metadata
    4. Freshness (0.15) -- exponential decay from creation time
    5. Cross-Domain Transfer (0.10) -- global scope with proven success
    6. Retrieval Frequency (0.10) -- how often this memory is used

Outcome Efficacy uses an Exponential Moving Average (EMA) blended with
the static success ratio. The EMA gives more weight to recent outcomes,
so a methodology that was failing but recently started succeeding sees
its efficacy rise faster than the static ratio alone.  The EMA value
persists in the fitness_vector as ``outcome_ema`` between calls.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Optional

from claw.core.models import Methodology

logger = logging.getLogger("claw.memory.fitness")

# Dimension weights (sum = 1.0)
W_RELEVANCE = 0.20
W_EFFICACY = 0.30
W_SPECIFICITY = 0.15
W_FRESHNESS = 0.15
W_CROSS_DOMAIN = 0.10
W_FREQUENCY = 0.10

# Freshness half-life in days
FRESHNESS_HALF_LIFE_DAYS = 90.0

# EMA smoothing factor for outcome efficacy.
# Alpha=0.3 means 30% weight on the latest outcome, 70% on the running average.
# Higher alpha = faster adaptation to recent performance changes.
EMA_ALPHA = 0.3

# Blend weights: how much of efficacy comes from EMA vs static ratio.
# Once an EMA is established, efficacy = 60% EMA + 40% static ratio.
# This prevents a single lucky/unlucky outcome from dominating.
EMA_BLEND_WEIGHT = 0.6
STATIC_BLEND_WEIGHT = 1.0 - EMA_BLEND_WEIGHT


def compute_fitness(
    methodology: Methodology,
    retrieval_relevance: float = 0.5,
    max_retrieval_count: int = 1,
    now: Optional[datetime] = None,
    latest_outcome: Optional[bool] = None,
    kelly_posterior_std: Optional[float] = None,
) -> tuple[float, dict[str, float]]:
    """Compute the 6-dimensional fitness score for a methodology.

    Args:
        methodology: The methodology to score.
        retrieval_relevance: The combined_score from the most recent retrieval
            (hybrid search). Defaults to 0.5 (neutral) when not available.
        max_retrieval_count: The maximum retrieval_count across all active
            methodologies in the same scope. Used to normalize frequency.
        now: Current time for freshness calculation. Defaults to utcnow.
        latest_outcome: The most recent outcome (True=success, False=failure).
            When provided, updates the EMA.  When None (e.g. during bulk
            recomputation), the stored EMA is preserved as-is.
        kelly_posterior_std: Optional posterior std from Bayesian Kelly sizer.
            When provided, applies an uncertainty discount to efficacy:
            agents with high posterior variance (unreliable) reduce the
            efficacy credit of their methodologies.  Capped at 30%.

    Returns:
        Tuple of (total_fitness_score, fitness_vector_dict).
        total_fitness_score is a float in [0.0, 1.0].
        fitness_vector_dict maps dimension names to individual scores.
    """
    if now is None:
        now = datetime.now(UTC)

    # 1. Retrieval Relevance -- from the search engine
    d_relevance = max(0.0, min(1.0, retrieval_relevance))

    # 2. Outcome Efficacy -- EMA-blended success ratio
    #
    # Static ratio: lifetime success_count / total_outcomes (all outcomes equal)
    # EMA: exponential moving average giving 30% weight to latest outcome
    # Final efficacy: 60% EMA + 40% static ratio (when EMA available)
    total_outcomes = methodology.success_count + methodology.failure_count
    if total_outcomes > 0:
        static_efficacy = methodology.success_count / total_outcomes
    else:
        static_efficacy = 0.5  # Unknown: assume neutral

    # Read stored EMA from previous fitness vector (if any)
    prev_ema: Optional[float] = None
    fv = methodology.fitness_vector
    if fv and "outcome_ema" in fv:
        try:
            prev_ema = float(fv["outcome_ema"])
        except (TypeError, ValueError):
            pass

    # Update EMA with latest outcome
    if latest_outcome is not None:
        outcome_val = 1.0 if latest_outcome else 0.0
        if prev_ema is not None:
            outcome_ema = EMA_ALPHA * outcome_val + (1.0 - EMA_ALPHA) * prev_ema
        else:
            # Bootstrap: first outcome seeds the EMA from static ratio
            # blended with the new outcome to avoid a cold-start jump
            outcome_ema = EMA_ALPHA * outcome_val + (1.0 - EMA_ALPHA) * static_efficacy
    else:
        outcome_ema = prev_ema  # preserve stored value (may be None)

    # Blend EMA with static ratio for final efficacy
    if outcome_ema is not None:
        d_efficacy = EMA_BLEND_WEIGHT * outcome_ema + STATIC_BLEND_WEIGHT * static_efficacy
    else:
        d_efficacy = static_efficacy  # no EMA yet, pure static

    # Kelly uncertainty discount: high posterior_std reduces efficacy credit
    if kelly_posterior_std is not None and kelly_posterior_std > 0:
        discount = min(kelly_posterior_std, 0.30)  # cap at 30%
        d_efficacy = d_efficacy * (1.0 - discount)

    # 3. Specificity -- metadata richness
    tag_score = min(1.0, len(methodology.tags) / 5.0)
    files_score = min(1.0, len(methodology.files_affected) / 10.0)
    d_specificity = (tag_score + files_score) / 2.0

    # 4. Freshness -- exponential decay
    age_days = (now - methodology.created_at).total_seconds() / 86400.0
    d_freshness = math.exp(-0.693 * age_days / FRESHNESS_HALF_LIFE_DAYS)

    # 5. Cross-Domain Transfer -- global + successful
    if methodology.scope == "global" and methodology.success_count > 0:
        d_cross_domain = 1.0
    elif methodology.scope == "global":
        d_cross_domain = 0.3  # Global but unproven
    else:
        d_cross_domain = 0.0

    # 6. Retrieval Frequency -- normalized
    safe_max = max(1, max_retrieval_count)
    d_frequency = min(1.0, methodology.retrieval_count / safe_max)

    # Weighted sum
    total = (
        W_RELEVANCE * d_relevance
        + W_EFFICACY * d_efficacy
        + W_SPECIFICITY * d_specificity
        + W_FRESHNESS * d_freshness
        + W_CROSS_DOMAIN * d_cross_domain
        + W_FREQUENCY * d_frequency
    )

    vector = {
        "retrieval_relevance": round(d_relevance, 4),
        "outcome_efficacy": round(d_efficacy, 4),
        "specificity": round(d_specificity, 4),
        "freshness": round(d_freshness, 4),
        "cross_domain_transfer": round(d_cross_domain, 4),
        "retrieval_frequency": round(d_frequency, 4),
        "total": round(total, 4),
    }

    # Persist EMA state for next computation
    if outcome_ema is not None:
        vector["outcome_ema"] = round(outcome_ema, 4)

    # Persist Kelly uncertainty for observability
    if kelly_posterior_std is not None:
        vector["kelly_posterior_std"] = round(kelly_posterior_std, 4)

    return round(total, 4), vector


def get_fitness_score(methodology: Methodology) -> float:
    """Extract the stored total fitness score, with neutral fallback.

    Used by retrieval to read cached fitness without recomputation.
    """
    fv = methodology.fitness_vector
    if fv and "total" in fv:
        try:
            return float(fv["total"])
        except (TypeError, ValueError):
            pass
    return 0.5  # Neutral fallback for legacy/unscored entries


async def log_fitness_change(
    engine: "DatabaseEngine",
    methodology_id: str,
    fitness_total: float,
    fitness_vector: dict[str, float],
    trigger_event: str = "recompute",
) -> None:
    """Persist a fitness computation to the history log.

    Args:
        engine: The DatabaseEngine instance for DB access.
        methodology_id: Which methodology was scored.
        fitness_total: The computed total fitness score.
        fitness_vector: Full dimension breakdown dict.
        trigger_event: What caused this recomputation (e.g. 'recompute',
            'outcome_success', 'outcome_failure', 'lifecycle_transition').
    """
    import json
    import uuid

    try:
        await engine.execute(
            "INSERT INTO methodology_fitness_log (id, methodology_id, fitness_total, fitness_vector, trigger_event) VALUES (?, ?, ?, ?, ?)",
            [str(uuid.uuid4()), methodology_id, fitness_total, json.dumps(fitness_vector), trigger_event],
        )
    except Exception as e:
        logger.warning("Failed to log fitness change for %s: %s", methodology_id, e)
