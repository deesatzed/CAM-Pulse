"""A/B Test Statistical Analyzer for SWE quality experiments.

Computes:
- Mann-Whitney U test on composite scores (primary)
- Per-dimension Mann-Whitney U (diagnostic)
- Bootstrap 95% CI for mean difference
- Cohen's d effect size
- Wilcoxon signed-rank for paired comparisons
"""

from __future__ import annotations

import logging
import math
import random
from typing import Any, Optional

logger = logging.getLogger("claw.evolution.ab_analyzer")

# Dimension names matching ab_quality_samples columns
DIMENSIONS = [
    "d_functional_correctness",
    "d_structural_compliance",
    "d_intent_alignment",
    "d_correction_efficiency",
    "d_token_economy",
    "d_expectation_match",
]

DIMENSION_LABELS = {
    "d_functional_correctness": "Functional Correctness (D1, w=0.30)",
    "d_structural_compliance": "Structural Compliance (D2, w=0.15)",
    "d_intent_alignment": "Intent Alignment (D3, w=0.20)",
    "d_correction_efficiency": "Correction Efficiency (D4, w=0.15)",
    "d_token_economy": "Token Economy (D5, w=0.10)",
    "d_expectation_match": "Expectation Match (D6, w=0.10)",
}


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _std(vals: list[float], ddof: int = 1) -> float:
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / (len(vals) - ddof))


def _cohens_d(a: list[float], b: list[float]) -> float:
    """Compute Cohen's d effect size for independent samples."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0
    sa, sb = _std(a), _std(b)
    pooled = math.sqrt(((na - 1) * sa**2 + (nb - 1) * sb**2) / (na + nb - 2))
    if pooled < 1e-9:
        return 0.0
    return (_mean(b) - _mean(a)) / pooled


def _bootstrap_ci(
    a: list[float],
    b: list[float],
    n_bootstrap: int = 10000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float]:
    """Bootstrap 95% CI for difference in means (b - a)."""
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_bootstrap):
        sa = [rng.choice(a) for _ in range(len(a))]
        sb = [rng.choice(b) for _ in range(len(b))]
        diffs.append(_mean(sb) - _mean(sa))
    diffs.sort()
    lo = diffs[int(alpha / 2 * n_bootstrap)]
    hi = diffs[int((1 - alpha / 2) * n_bootstrap)]
    return lo, hi


class ABAnalyzer:
    """Statistical analysis for A/B quality experiments.

    Reads from the ab_quality_samples table and computes
    comprehensive statistics comparing control vs variant.
    """

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    async def fetch_samples(self, project_id: str) -> dict[str, list[dict]]:
        """Fetch all samples grouped by variant_label."""
        rows = await self.repository.engine.fetch_all(
            """SELECT * FROM ab_quality_samples
               WHERE project_id = ?
               ORDER BY created_at""",
            [project_id],
        )
        groups: dict[str, list[dict]] = {"control": [], "variant": []}
        for row in rows:
            label = row["variant_label"]
            if label in groups:
                groups[label].append(dict(row))
        return groups

    async def analyze(self, project_id: str) -> dict[str, Any]:
        """Run full statistical analysis on A/B samples.

        Returns a structured report with:
        - sample_counts: per variant
        - composite_comparison: Mann-Whitney U, Cohen's d, bootstrap CI
        - per_dimension: individual dimension analysis
        - correction_comparison: correction attempts and efficiency
        - verdict: human-readable summary
        """
        groups = await self.fetch_samples(project_id)
        control = groups.get("control", [])
        variant = groups.get("variant", [])

        result: dict[str, Any] = {
            "project_id": project_id,
            "control_n": len(control),
            "variant_n": len(variant),
        }

        if len(control) < 2 or len(variant) < 2:
            result["verdict"] = (
                f"Insufficient samples (control={len(control)}, variant={len(variant)}). "
                f"Need at least 2 per arm."
            )
            return result

        # Composite score comparison
        ctrl_scores = [s["composite_score"] for s in control]
        var_scores = [s["composite_score"] for s in variant]

        result["composite"] = self._compare_metric(ctrl_scores, var_scores, "composite_score")

        # Per-dimension comparison
        result["dimensions"] = {}
        for dim in DIMENSIONS:
            ctrl_dim = [s[dim] for s in control]
            var_dim = [s[dim] for s in variant]
            result["dimensions"][dim] = self._compare_metric(ctrl_dim, var_dim, dim)

        # Correction efficiency comparison
        ctrl_corrections = [s["correction_attempts"] for s in control]
        var_corrections = [s["correction_attempts"] for s in variant]
        result["corrections"] = {
            "control_mean": _mean(ctrl_corrections),
            "variant_mean": _mean(var_corrections),
            "delta": _mean(var_corrections) - _mean(ctrl_corrections),
        }

        # Success rate comparison
        ctrl_success = sum(1 for s in control if s["success"])
        var_success = sum(1 for s in variant if s["success"])
        result["success_rate"] = {
            "control": ctrl_success / len(control) if control else 0,
            "variant": var_success / len(variant) if variant else 0,
        }

        # Overall verdict
        composite = result["composite"]
        d = composite.get("cohens_d", 0)
        p = composite.get("mann_whitney_p", 1.0)

        if p < 0.01 and d > 0:
            verdict = f"KB SIGNIFICANTLY IMPROVES composite quality (p={p:.4f}, d={d:.2f})"
        elif p < 0.05 and d > 0:
            verdict = f"KB IMPROVES composite quality (p={p:.4f}, d={d:.2f})"
        elif p < 0.10 and d > 0:
            verdict = f"KB shows MARGINAL improvement (p={p:.4f}, d={d:.2f})"
        elif d > 0:
            verdict = f"KB shows positive trend but NOT significant (p={p:.4f}, d={d:.2f})"
        else:
            verdict = f"KB shows NO improvement or regression (p={p:.4f}, d={d:.2f})"

        result["verdict"] = verdict
        return result

    def _compare_metric(
        self,
        control: list[float],
        variant: list[float],
        metric_name: str,
    ) -> dict[str, Any]:
        """Compare a single metric between control and variant."""
        comparison: dict[str, Any] = {
            "metric": metric_name,
            "control_mean": _mean(control),
            "control_std": _std(control),
            "variant_mean": _mean(variant),
            "variant_std": _std(variant),
            "delta_mean": _mean(variant) - _mean(control),
            "cohens_d": _cohens_d(control, variant),
        }

        # Bootstrap CI
        ci_lo, ci_hi = _bootstrap_ci(control, variant)
        comparison["bootstrap_ci_95"] = [round(ci_lo, 6), round(ci_hi, 6)]

        # Mann-Whitney U (requires scipy)
        try:
            from scipy.stats import mannwhitneyu
            u_stat, p_value = mannwhitneyu(variant, control, alternative="greater")
            comparison["mann_whitney_u"] = float(u_stat)
            comparison["mann_whitney_p"] = float(p_value)
        except ImportError:
            logger.warning("scipy not available -- skipping Mann-Whitney U test")
            comparison["mann_whitney_p"] = 1.0

        return comparison

    def format_report(self, analysis: dict[str, Any]) -> str:
        """Format analysis dict as human-readable report."""
        lines = [
            "=" * 70,
            "A/B QUALITY ANALYSIS: Knowledge Ablation Test",
            "=" * 70,
            f"Samples: control={analysis['control_n']}, variant={analysis['variant_n']}",
            "",
        ]

        if "composite" in analysis:
            c = analysis["composite"]
            lines.append("COMPOSITE SCORE (primary metric)")
            lines.append(f"  Control:  {c['control_mean']:.4f} +/- {c['control_std']:.4f}")
            lines.append(f"  Variant:  {c['variant_mean']:.4f} +/- {c['variant_std']:.4f}")
            lines.append(f"  Delta:    {c['delta_mean']:+.4f}")
            lines.append(f"  Cohen's d: {c['cohens_d']:.3f}")
            lines.append(f"  Mann-Whitney p: {c.get('mann_whitney_p', 'N/A')}")
            lines.append(f"  Bootstrap 95% CI: {c.get('bootstrap_ci_95', 'N/A')}")
            lines.append("")

        if "dimensions" in analysis:
            lines.append("PER-DIMENSION ANALYSIS")
            for dim, data in analysis["dimensions"].items():
                label = DIMENSION_LABELS.get(dim, dim)
                delta = data["delta_mean"]
                p = data.get("mann_whitney_p", 1.0)
                sig = "*" if p < 0.05 else "~" if p < 0.10 else ""
                lines.append(f"  {label}: delta={delta:+.4f} p={p:.4f} {sig}")
            lines.append("")

        if "corrections" in analysis:
            c = analysis["corrections"]
            lines.append("CORRECTION EFFICIENCY")
            lines.append(f"  Control avg attempts: {c['control_mean']:.2f}")
            lines.append(f"  Variant avg attempts: {c['variant_mean']:.2f}")
            lines.append(f"  Delta: {c['delta']:+.2f}")
            lines.append("")

        if "success_rate" in analysis:
            s = analysis["success_rate"]
            lines.append("SUCCESS RATE")
            lines.append(f"  Control: {s['control']:.1%}")
            lines.append(f"  Variant: {s['variant']:.1%}")
            lines.append("")

        lines.append("VERDICT")
        lines.append(f"  {analysis.get('verdict', 'N/A')}")
        lines.append("=" * 70)

        return "\n".join(lines)
