"""Novelty filter for CAM-PULSE discoveries.

Scores discoveries against existing claw.db knowledge to determine
if a repo is genuinely novel or already known.
"""

from __future__ import annotations

import logging
from typing import Optional

from claw.core.config import PulseConfig
from claw.db.embeddings import EmbeddingEngine
from claw.db.engine import DatabaseEngine
from claw.pulse.models import PulseDiscovery

logger = logging.getLogger("claw.pulse.novelty")


class NoveltyFilter:
    """Filters discoveries against existing claw.db knowledge."""

    def __init__(
        self,
        engine: DatabaseEngine,
        embedding_engine: Optional[EmbeddingEngine] = None,
        config: Optional[PulseConfig] = None,
    ):
        self.engine = engine
        self.embedding_engine = embedding_engine
        self._threshold = config.novelty_threshold if config else 0.70
        self._config = config

    async def score(self, discovery: PulseDiscovery) -> float:
        """Score novelty: 0.0 = already known, 1.0 = completely novel.

        Two signals combined:
        1. URL dedup (0.5 weight): Is the canonical URL already in pulse_discoveries or fleet_repos?
        2. Semantic distance (0.5 weight): How different is this repo from existing methodologies?
        """
        url_novel = not await self.is_already_known(discovery.canonical_url)

        if not url_novel:
            return 0.0  # Already in DB — definitely not novel

        # URL is new — check semantic similarity if embedding engine available
        semantic_score = 1.0
        if self.embedding_engine and discovery.x_post_text:
            semantic_score = await self._semantic_novelty(discovery.x_post_text)

        # Combined: URL novelty (binary) + semantic distance
        # Since URL is novel (1.0), weight the semantic component
        combined = 0.5 + (0.5 * semantic_score)

        # Apply domain bias from profile if configured
        combined = self._apply_domain_bias(combined, discovery)

        return round(min(1.0, combined), 3)

    async def is_already_known(self, canonical_url: str) -> bool:
        """Fast URL-based check against pulse_discoveries and fleet_repos."""
        # Check pulse_discoveries
        row = await self.engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM pulse_discoveries WHERE canonical_url = ?",
            [canonical_url],
        )
        if row and row["cnt"] > 0:
            return True

        # Check fleet_repos (might have been registered via other paths)
        row = await self.engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM fleet_repos WHERE repo_path = ?",
            [canonical_url],
        )
        if row and row["cnt"] > 0:
            return True

        return False

    async def _semantic_novelty(self, text: str) -> float:
        """Measure how semantically different text is from existing methodologies.

        Returns 1.0 if completely novel (no similar methodologies),
        0.0 if very similar to existing knowledge.
        """
        if not self.embedding_engine:
            return 1.0

        try:
            vec = self.embedding_engine.encode(text[:500])
            packed = EmbeddingEngine.to_sqlite_vec(vec)

            # Find nearest neighbor in methodology_embeddings
            rows = await self.engine.fetch_all(
                """SELECT distance FROM methodology_embeddings
                   WHERE embedding MATCH ? ORDER BY distance LIMIT 1""",
                [packed],
            )
            if not rows:
                return 1.0  # No methodologies at all — completely novel

            # distance is cosine distance (0 = identical, 2 = opposite)
            # Convert to novelty: high distance = high novelty
            nearest_distance = rows[0]["distance"]
            # Normalize: 0.0 distance → 0.0 novelty, 1.0+ distance → 1.0 novelty
            novelty = min(1.0, nearest_distance)
            return novelty

        except Exception as e:
            logger.warning("Semantic novelty check failed: %s", e)
            return 0.8  # Assume somewhat novel on error

    def _apply_domain_bias(self, score: float, discovery: "PulseDiscovery") -> float:
        """Boost score if discovery text matches profile domain biases.

        Checks discovery text (x_post_text + keywords_matched) against
        profile.novelty_bias domain→weight mapping. Applies the highest
        matching bias (not cumulative) to avoid over-boosting.
        """
        if not self._config:
            return score
        profile = getattr(self._config, "profile", None)
        if not profile:
            return score
        bias_map = getattr(profile, "novelty_bias", {})
        if not bias_map:
            return score

        # Build text corpus to match against
        text = (discovery.x_post_text or "").lower()
        text += " " + " ".join(kw.lower() for kw in (discovery.keywords_matched or []))

        max_bias = 0.0
        for domain, weight in bias_map.items():
            if domain.lower() in text:
                max_bias = max(max_bias, weight)

        if max_bias > 0:
            logger.debug(
                "Domain bias +%.2f for %s", max_bias, discovery.canonical_url
            )
        return score + max_bias

    async def filter_discoveries(
        self,
        discoveries: list[PulseDiscovery],
    ) -> list[PulseDiscovery]:
        """Score and filter discoveries, keeping only those above threshold.

        Updates each discovery's novelty_score in-place.
        """
        novel = []
        for disc in discoveries:
            disc.novelty_score = await self.score(disc)
            if disc.novelty_score >= self._threshold:
                novel.append(disc)
                logger.info(
                    "Novel: %s (score=%.2f)", disc.canonical_url, disc.novelty_score
                )
            else:
                logger.debug(
                    "Skipped (not novel): %s (score=%.2f)",
                    disc.canonical_url, disc.novelty_score,
                )
        return novel
