"""Cross-language pattern synthesis across CAM Ganglia.

Queries multiple language-specific ganglia (Rust, Go, TypeScript, etc.) via
FTS5 and synthesizes results into universal patterns, unique innovations,
transferable insights, and composition layers.

This is the analytical layer above Federation — Federation finds individual
methodologies from siblings, CrossLanguageAnalyzer finds cross-brain *patterns*.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from claw.core.config import InstanceRegistryConfig
from claw.core.models import (
    CompositionLayer,
    CrossBrainMetrics,
    CrossLanguageReport,
    TransferableInsight,
    UniqueInnovation,
    UniversalPattern,
)

logger = logging.getLogger("claw.community.cross_language")

# ---------------------------------------------------------------------------
# Domain mapping — maps category tags to high-level domains
# ---------------------------------------------------------------------------

CATEGORY_DOMAIN_MAP: dict[str, str] = {
    "security": "security",
    "authentication": "security",
    "authorization": "security",
    "encryption": "security",
    "crypto": "security",
    "taint": "security",
    "architecture": "architecture",
    "design_pattern": "architecture",
    "composition": "architecture",
    "middleware": "architecture",
    "modular": "architecture",
    "testing": "testing",
    "test": "testing",
    "coverage": "testing",
    "validation": "testing",
    "performance": "performance",
    "optimization": "performance",
    "caching": "performance",
    "concurrency": "performance",
    "error_handling": "reliability",
    "logging": "reliability",
    "monitoring": "reliability",
    "resilience": "reliability",
    "ai_integration": "ai_integration",
    "ml": "ai_integration",
    "inference": "ai_integration",
    "neural": "ai_integration",
    "database": "data",
    "storage": "data",
    "query": "data",
    "migration": "data",
    "api": "api",
    "rest": "api",
    "graphql": "api",
    "grpc": "api",
}

# Stop words for keyword extraction
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again",
    "over", "further", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "and", "but", "or", "if", "this", "that",
    "these", "those", "it", "its", "we", "our", "they", "them", "their",
    "what", "which", "who", "whom", "about", "up", "out", "just", "also",
})


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _extract_category_from_tags(tags: list[str]) -> str:
    """Extract the category from a tag list (e.g., 'category:security' -> 'security')."""
    for tag in tags:
        if tag.startswith("category:"):
            return tag[len("category:"):]
    return "uncategorized"


def _keyword_set_from_text(text: str) -> set[str]:
    """Extract a set of meaningful keywords from text."""
    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return {t for t in tokens if len(t) >= 3 and t not in _STOP_WORDS}


def _keyword_overlap_score(a: set[str], b: set[str]) -> float:
    """Compute Jaccard-like overlap between two keyword sets.

    Returns intersection/min(|a|, |b|) so that a subset scores 1.0.
    """
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    denominator = min(len(a), len(b))
    return intersection / denominator if denominator > 0 else 0.0


def _build_safe_fts5_query(keywords: list[str]) -> str:
    """Build an FTS5 query from keywords using OR logic."""
    safe = []
    for kw in keywords:
        cleaned = re.sub(r"[^a-zA-Z0-9_]", "", kw)
        if cleaned and len(cleaned) >= 3:
            safe.append(f'"{cleaned}"')
    return " OR ".join(safe) if safe else ""


# ---------------------------------------------------------------------------
# CrossLanguageAnalyzer
# ---------------------------------------------------------------------------

class CrossLanguageAnalyzer:
    """Analyze patterns across multiple language-specific CAM Ganglia.

    Queries each ganglion's FTS5, collects methodologies, and synthesizes
    cross-brain patterns (universal, unique, transferable, composition layers).
    """

    def __init__(
        self,
        config: InstanceRegistryConfig,
        *,
        primary_db_path: str | None = None,
    ) -> None:
        self.config = config
        self.primary_db_path = primary_db_path

    async def analyze(
        self,
        query: str,
        domains: list[str] | None = None,
        max_per_brain: int = 10,
    ) -> CrossLanguageReport:
        """Run cross-brain pattern analysis.

        1. Extract keywords, infer domains
        2. Query each sibling ganglion via FTS5
        3. Detect universal patterns (across 2+ brains)
        4. Detect unique innovations (brain-specific)
        5. Generate transferable insights
        6. Build composition layers
        7. Count novelty against primary DB
        """
        keywords = list(_keyword_set_from_text(query))
        if not keywords:
            return CrossLanguageReport(
                query=query,
                metrics=CrossBrainMetrics(query=query, brains_queried=0),
            )

        inferred_domains = self._infer_domains(keywords)
        if domains:
            inferred_domains = list(set(inferred_domains + domains))

        # Query brains — include primary DB as the richest knowledge source
        results_by_brain: dict[str, list[dict[str, Any]]] = {}
        ids_by_brain: dict[str, list[str]] = {}

        # Primary DB first (3,000+ methodologies)
        if self.primary_db_path and Path(self.primary_db_path).exists():
            primary_name = getattr(self.config, "instance_name", "general") or "general"
            primary_results = await self._query_brain_by_path(
                self.primary_db_path, primary_name, keywords, max_per_brain
            )
            if primary_results:
                results_by_brain[primary_name] = primary_results
                ids_by_brain[primary_name] = [r["id"] for r in primary_results]

        # Then sibling ganglia
        for sibling in self.config.siblings:
            brain_name = sibling.name
            results = await self._query_brain(sibling, keywords, max_per_brain)
            if results:
                results_by_brain[brain_name] = results
                ids_by_brain[brain_name] = [r["id"] for r in results]

        brains_queried = (1 if self.primary_db_path else 0) + len(self.config.siblings)
        brains_with_results = len(results_by_brain)
        total_results = sum(len(rs) for rs in results_by_brain.values())

        # Detect universal patterns
        universal_patterns = self._detect_universal_patterns(results_by_brain)

        # Detect unique innovations
        unique_innovations = self._detect_unique_innovations(results_by_brain)

        # Generate transferable insights
        transferable_insights = self._generate_transferable_insights(
            results_by_brain, unique_innovations
        )

        # Build composition layers
        composition_layers = self._build_composition_layers(results_by_brain)

        # Count novelty against primary
        novelty_count = 0
        if self.primary_db_path:
            novelty_count = await self._count_novelty(results_by_brain)

        metrics = CrossBrainMetrics(
            query=query,
            brains_queried=brains_queried,
            brains_with_results=brains_with_results,
            total_results=total_results,
            cross_brain_coverage=(
                brains_with_results / brains_queried if brains_queried > 0 else 0.0
            ),
            universal_pattern_count=len(universal_patterns),
            novelty_count=novelty_count,
            unique_innovations_per_brain={
                brain: sum(1 for u in unique_innovations if u.brain == brain)
                for brain in results_by_brain
            },
        )

        return CrossLanguageReport(
            query=query,
            domains_queried=inferred_domains,
            universal_patterns=universal_patterns,
            unique_innovations=unique_innovations,
            transferable_insights=transferable_insights,
            composition_layers=composition_layers,
            metrics=metrics,
            raw_results_by_brain=ids_by_brain,
        )

    def _infer_domains(self, keywords: list[str]) -> list[str]:
        """Infer domains from query keywords using CATEGORY_DOMAIN_MAP."""
        domains: set[str] = set()
        for kw in keywords:
            if kw in CATEGORY_DOMAIN_MAP:
                domains.add(CATEGORY_DOMAIN_MAP[kw])
        return sorted(domains)

    async def _query_brain(
        self,
        sibling: Any,
        keywords: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Query a single brain's FTS5 index for matching methodologies."""
        db_path = Path(sibling.db_path)
        if not db_path.exists():
            logger.debug("Brain DB not found: %s", db_path)
            return []

        fts_query = _build_safe_fts5_query(keywords)
        if not fts_query:
            return []

        results: list[dict[str, Any]] = []

        try:
            async with aiosqlite.connect(
                f"file:{db_path}?mode=ro", uri=True
            ) as conn:
                conn.row_factory = aiosqlite.Row

                rows = await conn.execute_fetchall(
                    """SELECT methodology_id, rank
                       FROM methodology_fts
                       WHERE methodology_fts MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    [fts_query, limit * 2],
                )

                for row in rows:
                    if len(results) >= limit:
                        break
                    mid = row["methodology_id"] if isinstance(row, dict) else row[0]

                    meth_rows = await conn.execute_fetchall(
                        "SELECT * FROM methodologies WHERE id = ?", [mid]
                    )
                    if not meth_rows:
                        continue

                    meth = dict(meth_rows[0])

                    # Skip dead/dormant
                    state = meth.get("lifecycle_state", "")
                    if state in ("dead", "dormant"):
                        continue

                    # Parse JSON fields
                    for field in ("tags", "tech_stack"):
                        val = meth.get(field)
                        if isinstance(val, str):
                            try:
                                meth[field] = json.loads(val)
                            except (json.JSONDecodeError, TypeError):
                                meth[field] = []
                        elif val is None:
                            meth[field] = []

                    results.append(meth)

        except Exception as e:
            logger.warning("Failed to query brain %s: %s", sibling.name, e)

        return results

    async def _query_brain_by_path(
        self,
        db_path_str: str,
        brain_name: str,
        keywords: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Query a brain DB by path (used for primary DB)."""
        db_path = Path(db_path_str)
        if not db_path.exists():
            return []

        fts_query = _build_safe_fts5_query(keywords)
        if not fts_query:
            return []

        results: list[dict[str, Any]] = []
        try:
            async with aiosqlite.connect(
                f"file:{db_path}?mode=ro", uri=True
            ) as conn:
                conn.row_factory = aiosqlite.Row
                rows = await conn.execute_fetchall(
                    """SELECT methodology_id, rank
                       FROM methodology_fts
                       WHERE methodology_fts MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    [fts_query, limit * 2],
                )
                for row in rows:
                    if len(results) >= limit:
                        break
                    mid = row["methodology_id"] if isinstance(row, dict) else row[0]

                    meth_rows = await conn.execute_fetchall(
                        "SELECT id, problem_description, solution_code, tags, language, "
                        "lifecycle_state, methodology_type "
                        "FROM methodologies WHERE id = ?",
                        [mid],
                    )
                    if not meth_rows:
                        continue
                    meth = dict(meth_rows[0])
                    state = meth.get("lifecycle_state", "")
                    if state in ("dead", "dormant"):
                        continue
                    # Parse tags JSON
                    tags_raw = meth.get("tags")
                    if isinstance(tags_raw, str):
                        try:
                            import json as _json
                            meth["tags"] = _json.loads(tags_raw)
                        except (ValueError, TypeError):
                            meth["tags"] = []
                    elif tags_raw is None:
                        meth["tags"] = []
                    results.append(meth)
        except Exception as e:
            logger.warning("Failed to query brain %s at %s: %s", brain_name, db_path, e)

        logger.info(
            "Queried brain %s (by path): %d results for %d keywords",
            brain_name, len(results), len(keywords),
        )
        return results

    def _detect_universal_patterns(
        self,
        results_by_brain: dict[str, list[dict[str, Any]]],
    ) -> list[UniversalPattern]:
        """Detect patterns that appear in 2+ brains based on keyword overlap."""
        if len(results_by_brain) < 2:
            return []

        patterns: list[UniversalPattern] = []
        brains = list(results_by_brain.keys())

        # Compare methodologies across brain pairs
        matched_ids: set[str] = set()

        for i, brain_a in enumerate(brains):
            for brain_b in brains[i + 1:]:
                for meth_a in results_by_brain[brain_a]:
                    if meth_a["id"] in matched_ids:
                        continue
                    kw_a = _keyword_set_from_text(
                        f"{meth_a.get('problem_description', '')} "
                        f"{meth_a.get('methodology_notes', '')}"
                    )
                    for meth_b in results_by_brain[brain_b]:
                        if meth_b["id"] in matched_ids:
                            continue
                        kw_b = _keyword_set_from_text(
                            f"{meth_b.get('problem_description', '')} "
                            f"{meth_b.get('methodology_notes', '')}"
                        )
                        overlap = _keyword_overlap_score(kw_a, kw_b)
                        if overlap >= 0.3:
                            cat_a = _extract_category_from_tags(
                                meth_a.get("tags", [])
                            )
                            patterns.append(UniversalPattern(
                                pattern_name=(
                                    meth_a.get("problem_description", "")[:80]
                                ),
                                implementations={
                                    brain_a: meth_a.get("solution_code", "")[:200],
                                    brain_b: meth_b.get("solution_code", "")[:200],
                                },
                                evidence_ids={
                                    brain_a: [meth_a["id"]],
                                    brain_b: [meth_b["id"]],
                                },
                                domain_overlap=overlap,
                                source_categories=[cat_a],
                            ))
                            matched_ids.add(meth_a["id"])
                            matched_ids.add(meth_b["id"])
                            break

        return patterns

    def _detect_unique_innovations(
        self,
        results_by_brain: dict[str, list[dict[str, Any]]],
    ) -> list[UniqueInnovation]:
        """Detect methodologies unique to a single brain."""
        if len(results_by_brain) < 2:
            return []

        innovations: list[UniqueInnovation] = []

        for brain_name, methodologies in results_by_brain.items():
            other_brains = {
                b: ms for b, ms in results_by_brain.items() if b != brain_name
            }
            if not other_brains:
                continue

            for meth in methodologies:
                kw_self = _keyword_set_from_text(
                    f"{meth.get('problem_description', '')} "
                    f"{meth.get('methodology_notes', '')}"
                )

                is_unique = True
                for other_brain, other_meths in other_brains.items():
                    for other_meth in other_meths:
                        kw_other = _keyword_set_from_text(
                            f"{other_meth.get('problem_description', '')} "
                            f"{other_meth.get('methodology_notes', '')}"
                        )
                        if _keyword_overlap_score(kw_self, kw_other) >= 0.3:
                            is_unique = False
                            break
                    if not is_unique:
                        break

                if is_unique:
                    category = _extract_category_from_tags(meth.get("tags", []))
                    other_brain_names = list(other_brains.keys())
                    innovations.append(UniqueInnovation(
                        brain=brain_name,
                        methodology_id=meth["id"],
                        problem_summary=meth.get("problem_description", "")[:200],
                        solution_summary=meth.get("solution_code", "")[:200],
                        why_unique=(
                            f"No equivalent in {', '.join(other_brain_names)}"
                        ),
                        category=category,
                    ))

        return innovations

    def _generate_transferable_insights(
        self,
        results_by_brain: dict[str, list[dict[str, Any]]],
        unique_innovations: list[UniqueInnovation],
    ) -> list[TransferableInsight]:
        """Generate insights about what one brain could teach another."""
        insights: list[TransferableInsight] = []
        all_brains = list(results_by_brain.keys())

        for innovation in unique_innovations:
            for target_brain in all_brains:
                if target_brain == innovation.brain:
                    continue
                insights.append(TransferableInsight(
                    source_brain=innovation.brain,
                    target_brain=target_brain,
                    source_methodology_id=innovation.methodology_id,
                    rationale=(
                        f"{innovation.brain}'s approach to "
                        f"{innovation.problem_summary[:80]} has no equivalent "
                        f"in {target_brain}"
                    ),
                    pattern_name=innovation.problem_summary[:80],
                ))

        return insights

    def _build_composition_layers(
        self,
        results_by_brain: dict[str, list[dict[str, Any]]],
    ) -> list[CompositionLayer]:
        """Build composition layers from multi-brain results.

        Each brain's top result becomes a layer in a composed architecture.
        """
        layers: list[CompositionLayer] = []
        layer_num = 1

        # Group by category, pick best per category per brain
        category_results: dict[str, list[tuple[str, dict[str, Any]]]] = {}

        for brain_name, methodologies in results_by_brain.items():
            for meth in methodologies:
                cat = _extract_category_from_tags(meth.get("tags", []))
                category_results.setdefault(cat, []).append((brain_name, meth))

        for category, entries in sorted(category_results.items()):
            if not entries:
                continue
            # Take the first entry per category (already sorted by FTS rank)
            brain_name, meth = entries[0]
            layers.append(CompositionLayer(
                layer_number=layer_num,
                layer_name=f"{category} ({brain_name})",
                contributing_brain=brain_name,
                methodology_id=meth["id"],
                methodology_summary=meth.get("problem_description", "")[:200],
            ))
            layer_num += 1

        return layers

    async def _count_novelty(
        self,
        results_by_brain: dict[str, list[dict[str, Any]]],
    ) -> int:
        """Count cross-brain unique results (appear in only 1 brain).

        Now that primary DB is included as a brain, novelty means a result
        whose problem description has no high-overlap match in any OTHER brain.
        """
        if len(results_by_brain) < 2:
            return 0

        # Build keyword sets per brain
        brain_keywords: dict[str, list[tuple[str, set[str]]]] = {}
        for brain_name, methodologies in results_by_brain.items():
            entries = []
            for meth in methodologies:
                kw = _keyword_set_from_text(
                    meth.get("problem_description", "")
                )
                if kw:
                    entries.append((meth["id"], kw))
            brain_keywords[brain_name] = entries

        # Count results unique to a single brain
        novel = 0
        for brain_name, entries in brain_keywords.items():
            other_keywords: list[set[str]] = []
            for other_brain, other_entries in brain_keywords.items():
                if other_brain != brain_name:
                    other_keywords.extend(kw for _, kw in other_entries)

            for _mid, kw in entries:
                is_unique = True
                for okw in other_keywords:
                    if _keyword_overlap_score(kw, okw) >= 0.4:
                        is_unique = False
                        break
                if is_unique:
                    novel += 1

        return novel
