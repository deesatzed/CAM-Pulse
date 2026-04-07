"""Knowledge Gap Analyzer — category x brain coverage matrix and repo prioritization.

Computes a live coverage matrix across all CAM Ganglia (primary + siblings),
identifies sparse and empty cells, scores repos by gap-filling potential,
and persists periodic snapshots for trend tracking.

Usage:
    analyzer = GapAnalyzer(repository, instances_config, primary_db_path)
    matrix = await analyzer.compute_coverage_matrix()
    sparse = analyzer.get_sparse_domains(matrix)
    score = analyzer.score_repo_for_gaps("some-repo", {"language": "go", "categories": ["security"]})
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from claw.core.config import GapAnalyzerConfig, InstanceRegistryConfig
from claw.core.models import CoverageMatrix
from claw.db.repository import Repository

logger = logging.getLogger("claw.community.gap_analyzer")


class GapAnalyzer:
    """Coverage matrix computation, sparse cell detection, and repo gap scoring."""

    def __init__(
        self,
        repository: Repository,
        instances_config: InstanceRegistryConfig,
        primary_db_path: str,
        gap_config: Optional[GapAnalyzerConfig] = None,
    ) -> None:
        self.repository = repository
        self.instances_config = instances_config
        self.primary_db_path = primary_db_path
        self.config = gap_config or GapAnalyzerConfig()

    async def compute_coverage_matrix(self) -> CoverageMatrix:
        """Build category x brain matrix across all ganglia.

        Queries the primary DB via repository, then each sibling DB
        via read-only aiosqlite.
        """
        # Primary DB — use the repository (already connected)
        primary_matrix = await self.repository.get_coverage_matrix()

        # Determine primary brain name
        primary_name = (
            getattr(self.instances_config, "instance_name", None) or "general"
        )

        # Aggregate: matrix[category][brain] = count
        matrix: dict[str, dict[str, int]] = {}
        for cat, lang_counts in primary_matrix.items():
            matrix.setdefault(cat, {})[primary_name] = sum(lang_counts.values())

        # Sibling ganglia — read-only queries
        if self.instances_config.enabled:
            for sibling in self.instances_config.siblings:
                brain_name = sibling.name
                sibling_counts = await self._query_sibling_coverage(sibling.db_path)
                for cat, count in sibling_counts.items():
                    matrix.setdefault(cat, {})[brain_name] = count

        # Collect all brain names
        all_brains: set[str] = {primary_name}
        if self.instances_config.enabled:
            for sib in self.instances_config.siblings:
                all_brains.add(sib.name)
        for cat_data in matrix.values():
            all_brains.update(cat_data.keys())

        all_categories = set(matrix.keys())

        # Classify cells
        threshold = self.config.sparse_cell_threshold
        sparse_cells: list[tuple[str, str]] = []
        empty_cells: list[tuple[str, str]] = []
        total_by_category: dict[str, int] = {}
        total_by_brain: dict[str, int] = {}

        for cat in sorted(all_categories):
            cat_total = 0
            for brain in sorted(all_brains):
                count = matrix.get(cat, {}).get(brain, 0)
                cat_total += count
                total_by_brain[brain] = total_by_brain.get(brain, 0) + count
                if count == 0:
                    empty_cells.append((cat, brain))
                elif count < threshold:
                    sparse_cells.append((cat, brain))
            total_by_category[cat] = cat_total

        return CoverageMatrix(
            matrix=matrix,
            sparse_cells=sparse_cells,
            empty_cells=empty_cells,
            total_by_category=total_by_category,
            total_by_brain=total_by_brain,
        )

    def get_sparse_domains(
        self, coverage: CoverageMatrix
    ) -> list[tuple[str, str]]:
        """Return (category, brain) pairs below threshold, sorted by count ASC."""
        result = []
        for cat, brain in coverage.sparse_cells + coverage.empty_cells:
            count = coverage.matrix.get(cat, {}).get(brain, 0)
            result.append((cat, brain, count))
        result.sort(key=lambda x: x[2])
        return [(cat, brain) for cat, brain, _ in result]

    def score_repo_for_gaps(
        self,
        repo_name: str,
        domain_info: dict[str, Any],
        coverage: CoverageMatrix,
    ) -> float:
        """Score how much mining this repo would fill coverage gaps.

        Args:
            repo_name: Name of the repo.
            domain_info: Dict with optional 'language' and 'categories' keys.
            coverage: Current coverage matrix.

        Returns:
            Float score 0.0-1.0 where higher means more gap-filling potential.
        """
        if not coverage.sparse_cells and not coverage.empty_cells:
            return 0.0

        repo_lang = (domain_info.get("language") or "").lower()
        repo_categories = [
            c.lower() for c in domain_info.get("categories", [])
        ]

        # Build set of sparse (cat, brain) pairs for fast lookup
        sparse_set = set(coverage.sparse_cells) | set(coverage.empty_cells)

        # Score: count how many sparse cells this repo could fill
        matches = 0
        total_sparse = len(sparse_set)
        if total_sparse == 0:
            return 0.0

        for cat, brain in sparse_set:
            # Brain match: repo's language matches the brain name
            brain_match = repo_lang == brain.lower() if repo_lang else False
            # Category match: repo's detected categories overlap
            cat_match = cat.lower() in repo_categories if repo_categories else False

            if brain_match and cat_match:
                matches += 3  # Strong match: both brain and category
            elif brain_match:
                matches += 1  # Partial: right language
            elif cat_match:
                matches += 1  # Partial: right domain

        # Normalize to 0.0-1.0 range
        max_possible = total_sparse * 3
        return min(matches / max_possible, 1.0)

    async def take_snapshot(self) -> CoverageMatrix:
        """Compute coverage matrix and persist as a snapshot."""
        matrix = await self.compute_coverage_matrix()

        snapshot_id = str(uuid.uuid4())
        snapshot_data = json.dumps(matrix.matrix)
        sparse_cells_json = json.dumps(
            matrix.sparse_cells + matrix.empty_cells
        )
        total = sum(matrix.total_by_brain.values())

        await self.repository.save_coverage_snapshot(
            snapshot_id=snapshot_id,
            snapshot_data=snapshot_data,
            sparse_cells=sparse_cells_json,
            total_methodologies=total,
        )

        logger.info(
            "Coverage snapshot saved: id=%s, total=%d, sparse=%d, empty=%d",
            snapshot_id[:8],
            total,
            len(matrix.sparse_cells),
            len(matrix.empty_cells),
        )
        return matrix

    async def get_trend_summary(self) -> str:
        """Compare latest 2 snapshots and return natural-language delta."""
        trend = await self.repository.get_coverage_trend(limit=2)
        if len(trend) < 2:
            if trend:
                data = json.loads(trend[0]["snapshot_data"])
                total = trend[0]["total_methodologies"]
                sparse = json.loads(trend[0]["sparse_cells"])
                return (
                    f"Latest snapshot: {total} methodologies, "
                    f"{len(sparse)} sparse/empty cells, "
                    f"{len(data)} categories. No prior snapshot for comparison."
                )
            return "No coverage snapshots available. Run `cam gaps --snapshot` to create one."

        current = trend[0]
        previous = trend[1]

        cur_data = json.loads(current["snapshot_data"])
        prev_data = json.loads(previous["snapshot_data"])
        cur_sparse = set(
            tuple(c) for c in json.loads(current["sparse_cells"])
        )
        prev_sparse = set(
            tuple(c) for c in json.loads(previous["sparse_cells"])
        )

        total_delta = current["total_methodologies"] - previous["total_methodologies"]
        filled = prev_sparse - cur_sparse
        new_sparse = cur_sparse - prev_sparse

        lines = [
            f"Coverage trend ({previous['created_at'][:10]} -> {current['created_at'][:10]}):",
            f"  Total methodologies: {current['total_methodologies']} ({total_delta:+d})",
            f"  Sparse/empty cells: {len(cur_sparse)} (was {len(prev_sparse)})",
        ]

        if filled:
            lines.append(f"  Filled gaps ({len(filled)}):")
            for cat, brain in sorted(filled):
                lines.append(f"    + {cat} / {brain}")

        if new_sparse:
            lines.append(f"  New gaps ({len(new_sparse)}):")
            for cat, brain in sorted(new_sparse):
                lines.append(f"    - {cat} / {brain}")

        if not filled and not new_sparse:
            lines.append("  No coverage changes detected.")

        return "\n".join(lines)

    async def _query_sibling_coverage(
        self, db_path_str: str
    ) -> dict[str, int]:
        """Query a sibling ganglion for category counts via read-only connection."""
        db_path = Path(db_path_str)
        if not db_path.exists():
            return {}

        counts: dict[str, int] = {}
        try:
            async with aiosqlite.connect(
                f"file:{db_path}?mode=ro", uri=True
            ) as conn:
                conn.row_factory = aiosqlite.Row
                rows = await conn.execute_fetchall(
                    """SELECT SUBSTR(je.value, 10) AS category,
                              COUNT(*) AS cnt
                       FROM methodologies m, json_each(m.tags) je
                       WHERE m.lifecycle_state NOT IN ('dead', 'dormant')
                         AND je.value LIKE 'category:%'
                       GROUP BY category"""
                )
                for r in rows:
                    counts[r["category"]] = r["cnt"]
        except Exception as e:
            logger.warning("Failed to query sibling %s: %s", db_path_str, e)

        return counts
