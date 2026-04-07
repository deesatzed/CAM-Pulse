#!/usr/bin/env python3
"""A/B Quality Analysis v3: Comprehensive per-project and cross-project statistics.

Reads all ab_quality_samples from data/claw.db, filters out agent_id='local'
(Ollama agent), and computes:
  - Mann-Whitney U test (control vs variant composite scores)
  - Cohen's d effect size
  - Bootstrap 95% CI for mean difference
  - Per-dimension comparison across all 6 quality dimensions
  - Success rate comparison with Fisher's exact test
  - Combined "OpenRouter-only" analysis pooling all non-local samples

Results saved to data/ab_test_v3_results.json.

Usage:
    PYTHONPATH=src /Users/o2satz/miniforge3/envs/mlx13/bin/python scripts/analyze_ab_v3.py
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.stats import fisher_exact, mannwhitneyu

# ── Configuration ─────────────────────────────────────────────────────

DB_PATH = Path("data/claw.db")
OUTPUT_PATH = Path("data/ab_test_v3_results.json")
BOOTSTRAP_ITERATIONS = 10_000
BOOTSTRAP_SEED = 42
CONFIDENCE_LEVEL = 0.95

DIMENSION_COLS = [
    "d_functional_correctness",
    "d_structural_compliance",
    "d_intent_alignment",
    "d_correction_efficiency",
    "d_token_economy",
    "d_expectation_match",
]


# ── Statistical helpers ───────────────────────────────────────────────


def cohens_d(group_a: np.ndarray, group_b: np.ndarray) -> float:
    """Compute Cohen's d effect size between two groups.

    Uses the pooled standard deviation. Returns 0.0 if both groups have
    zero variance.
    """
    n_a, n_b = len(group_a), len(group_b)
    if n_a < 2 or n_b < 2:
        return float("nan")
    mean_a, mean_b = np.mean(group_a), np.mean(group_b)
    var_a, var_b = np.var(group_a, ddof=1), np.var(group_b, ddof=1)
    pooled_var = ((n_a - 1) * var_a + (n_b - 1) * var_b) / (n_a + n_b - 2)
    pooled_sd = math.sqrt(pooled_var)
    if pooled_sd == 0.0:
        return 0.0
    return float((mean_b - mean_a) / pooled_sd)


def interpret_cohens_d(d: float) -> str:
    """Return a human-readable interpretation of Cohen's d."""
    if math.isnan(d):
        return "insufficient_data"
    abs_d = abs(d)
    if abs_d < 0.2:
        return "negligible"
    elif abs_d < 0.5:
        return "small"
    elif abs_d < 0.8:
        return "medium"
    else:
        return "large"


def bootstrap_mean_diff_ci(
    group_a: np.ndarray,
    group_b: np.ndarray,
    n_iterations: int = BOOTSTRAP_ITERATIONS,
    confidence: float = CONFIDENCE_LEVEL,
    seed: int = BOOTSTRAP_SEED,
) -> Tuple[float, float, float]:
    """Bootstrap 95% CI for the difference in means (group_b - group_a).

    Returns (lower, point_estimate, upper).
    """
    rng = np.random.RandomState(seed)
    observed_diff = float(np.mean(group_b) - np.mean(group_a))

    if len(group_a) < 2 or len(group_b) < 2:
        return (float("nan"), observed_diff, float("nan"))

    diffs = np.empty(n_iterations)
    for i in range(n_iterations):
        sample_a = rng.choice(group_a, size=len(group_a), replace=True)
        sample_b = rng.choice(group_b, size=len(group_b), replace=True)
        diffs[i] = np.mean(sample_b) - np.mean(sample_a)

    alpha = 1.0 - confidence
    lower = float(np.percentile(diffs, 100 * alpha / 2))
    upper = float(np.percentile(diffs, 100 * (1 - alpha / 2)))
    return (lower, observed_diff, upper)


def mann_whitney_test(
    group_a: np.ndarray, group_b: np.ndarray
) -> Tuple[float, float]:
    """Perform Mann-Whitney U test. Returns (U_statistic, p_value).

    Returns (nan, nan) if either group has fewer than 2 observations.
    """
    if len(group_a) < 2 or len(group_b) < 2:
        return (float("nan"), float("nan"))
    try:
        u_stat, p_val = mannwhitneyu(
            group_a, group_b, alternative="two-sided"
        )
        return (float(u_stat), float(p_val))
    except ValueError:
        return (float("nan"), float("nan"))


def fisher_exact_test(
    success_a: int, total_a: int, success_b: int, total_b: int
) -> Tuple[float, float]:
    """Fisher's exact test on 2x2 contingency table.

    Returns (odds_ratio, p_value).
    """
    table = [
        [success_a, total_a - success_a],
        [success_b, total_b - success_b],
    ]
    try:
        odds_ratio, p_val = fisher_exact(table, alternative="two-sided")
        return (float(odds_ratio), float(p_val))
    except ValueError:
        return (float("nan"), float("nan"))


# ── Data loading ──────────────────────────────────────────────────────


def load_samples(db_path: Path) -> List[Dict[str, Any]]:
    """Load all ab_quality_samples excluding agent_id='local'."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            id, project_id, task_id, variant_label, agent_id,
            composite_score, success,
            d_functional_correctness, d_structural_compliance,
            d_intent_alignment, d_correction_efficiency,
            d_token_economy, d_expectation_match,
            correction_attempts, created_at
        FROM ab_quality_samples
        WHERE agent_id != 'local'
        ORDER BY project_id, variant_label, created_at
        """
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


# ── Analysis engine ───────────────────────────────────────────────────


def analyze_group(
    control_rows: List[Dict[str, Any]],
    variant_rows: List[Dict[str, Any]],
    label: str,
) -> Optional[Dict[str, Any]]:
    """Run full statistical comparison for a control vs variant group.

    Returns None if either group is empty.
    """
    n_control = len(control_rows)
    n_variant = len(variant_rows)

    if n_control == 0 and n_variant == 0:
        return None

    result: Dict[str, Any] = {
        "label": label,
        "n_control": n_control,
        "n_variant": n_variant,
        "n_total": n_control + n_variant,
    }

    # Agent composition
    control_agents = defaultdict(int)
    for r in control_rows:
        control_agents[r["agent_id"]] += 1
    variant_agents = defaultdict(int)
    for r in variant_rows:
        variant_agents[r["agent_id"]] += 1
    result["control_agents"] = dict(control_agents)
    result["variant_agents"] = dict(variant_agents)

    # Extract arrays
    ctrl_scores = np.array([r["composite_score"] for r in control_rows])
    var_scores = np.array([r["composite_score"] for r in variant_rows])

    # Descriptive stats
    result["control_composite"] = {
        "mean": float(np.mean(ctrl_scores)) if n_control > 0 else None,
        "std": float(np.std(ctrl_scores, ddof=1)) if n_control > 1 else None,
        "median": float(np.median(ctrl_scores)) if n_control > 0 else None,
        "min": float(np.min(ctrl_scores)) if n_control > 0 else None,
        "max": float(np.max(ctrl_scores)) if n_control > 0 else None,
    }
    result["variant_composite"] = {
        "mean": float(np.mean(var_scores)) if n_variant > 0 else None,
        "std": float(np.std(var_scores, ddof=1)) if n_variant > 1 else None,
        "median": float(np.median(var_scores)) if n_variant > 0 else None,
        "min": float(np.min(var_scores)) if n_variant > 0 else None,
        "max": float(np.max(var_scores)) if n_variant > 0 else None,
    }

    # Mann-Whitney U test
    if n_control >= 2 and n_variant >= 2:
        u_stat, u_pval = mann_whitney_test(ctrl_scores, var_scores)
        result["mann_whitney_u"] = {
            "U_statistic": u_stat,
            "p_value": u_pval,
            "significant_at_005": u_pval < 0.05 if not math.isnan(u_pval) else None,
        }
    else:
        result["mann_whitney_u"] = {
            "U_statistic": None,
            "p_value": None,
            "significant_at_005": None,
            "note": f"Skipped: need >=2 in each group (control={n_control}, variant={n_variant})",
        }

    # Cohen's d
    if n_control >= 2 and n_variant >= 2:
        d = cohens_d(ctrl_scores, var_scores)
        result["cohens_d"] = {
            "d": d,
            "interpretation": interpret_cohens_d(d),
            "direction": "variant > control" if d > 0 else "control > variant" if d < 0 else "equal",
        }
    else:
        result["cohens_d"] = {
            "d": None,
            "interpretation": "insufficient_data",
            "direction": None,
        }

    # Bootstrap 95% CI for mean difference
    if n_control >= 2 and n_variant >= 2:
        lower, point, upper = bootstrap_mean_diff_ci(ctrl_scores, var_scores)
        result["bootstrap_ci_95"] = {
            "lower": lower,
            "point_estimate": point,
            "upper": upper,
            "ci_excludes_zero": (lower > 0 or upper < 0)
            if not (math.isnan(lower) or math.isnan(upper))
            else None,
        }
    else:
        mean_diff = None
        if n_control > 0 and n_variant > 0:
            mean_diff = float(np.mean(var_scores) - np.mean(ctrl_scores))
        result["bootstrap_ci_95"] = {
            "lower": None,
            "point_estimate": mean_diff,
            "upper": None,
            "ci_excludes_zero": None,
            "note": "Insufficient data for bootstrap",
        }

    # Per-dimension comparison
    dimensions = {}
    for dim in DIMENSION_COLS:
        ctrl_dim = np.array([r[dim] for r in control_rows])
        var_dim = np.array([r[dim] for r in variant_rows])

        dim_result: Dict[str, Any] = {
            "control_mean": float(np.mean(ctrl_dim)) if n_control > 0 else None,
            "variant_mean": float(np.mean(var_dim)) if n_variant > 0 else None,
            "control_std": float(np.std(ctrl_dim, ddof=1)) if n_control > 1 else None,
            "variant_std": float(np.std(var_dim, ddof=1)) if n_variant > 1 else None,
        }

        if n_control >= 2 and n_variant >= 2:
            d_dim = cohens_d(ctrl_dim, var_dim)
            u_dim, p_dim = mann_whitney_test(ctrl_dim, var_dim)
            dim_result["cohens_d"] = d_dim
            dim_result["interpretation"] = interpret_cohens_d(d_dim)
            dim_result["mann_whitney_p"] = p_dim
        else:
            dim_result["cohens_d"] = None
            dim_result["interpretation"] = "insufficient_data"
            dim_result["mann_whitney_p"] = None

        # Mean difference
        if n_control > 0 and n_variant > 0:
            dim_result["mean_diff"] = float(np.mean(var_dim) - np.mean(ctrl_dim))
        else:
            dim_result["mean_diff"] = None

        dimensions[dim] = dim_result

    result["per_dimension"] = dimensions

    # Success rate comparison + Fisher's exact
    ctrl_success = sum(1 for r in control_rows if r["success"] == 1)
    var_success = sum(1 for r in variant_rows if r["success"] == 1)
    ctrl_rate = ctrl_success / n_control if n_control > 0 else None
    var_rate = var_success / n_variant if n_variant > 0 else None

    result["success_rate"] = {
        "control_successes": ctrl_success,
        "control_total": n_control,
        "control_rate": ctrl_rate,
        "variant_successes": var_success,
        "variant_total": n_variant,
        "variant_rate": var_rate,
    }

    if n_control > 0 and n_variant > 0:
        odds, fisher_p = fisher_exact_test(
            ctrl_success, n_control, var_success, n_variant
        )
        result["success_rate"]["fisher_exact"] = {
            "odds_ratio": odds,
            "p_value": fisher_p,
            "significant_at_005": fisher_p < 0.05 if not math.isnan(fisher_p) else None,
        }
    else:
        result["success_rate"]["fisher_exact"] = {
            "odds_ratio": None,
            "p_value": None,
            "significant_at_005": None,
            "note": "One or both groups empty",
        }

    # Correction attempts summary
    ctrl_attempts = [r["correction_attempts"] for r in control_rows]
    var_attempts = [r["correction_attempts"] for r in variant_rows]
    result["correction_attempts"] = {
        "control_mean": float(np.mean(ctrl_attempts)) if ctrl_attempts else None,
        "variant_mean": float(np.mean(var_attempts)) if var_attempts else None,
    }

    return result


# ── Main ──────────────────────────────────────────────────────────────


def main() -> None:
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading samples from {DB_PATH} (excluding agent_id='local')...")
    samples = load_samples(DB_PATH)
    print(f"  Loaded {len(samples)} samples")

    # Group by project
    by_project: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
        lambda: {"control": [], "variant": []}
    )
    for row in samples:
        by_project[row["project_id"]][row["variant_label"]].append(row)

    # Per-project analysis
    project_results: List[Dict[str, Any]] = []
    for pid in sorted(by_project.keys()):
        groups = by_project[pid]
        ctrl = groups["control"]
        var = groups["variant"]
        n_total = len(ctrl) + len(var)
        print(
            f"\n  Project {pid[:12]}... "
            f"control={len(ctrl)}, variant={len(var)}"
        )
        result = analyze_group(ctrl, var, label=f"project:{pid}")
        if result is not None:
            result["project_id"] = pid
            project_results.append(result)

    # Combined OpenRouter-only analysis
    print("\n--- Combined OpenRouter-only analysis (all projects pooled) ---")
    all_control = [r for r in samples if r["variant_label"] == "control"]
    all_variant = [r for r in samples if r["variant_label"] == "variant"]
    print(f"  Pooled: control={len(all_control)}, variant={len(all_variant)}")

    combined_result = analyze_group(
        all_control, all_variant, label="combined:openrouter_only"
    )

    # Projects with both arms (for focused analysis)
    dual_arm_projects = [
        pid
        for pid, groups in by_project.items()
        if len(groups["control"]) > 0 and len(groups["variant"]) > 0
    ]
    dual_arm_control = [
        r for r in samples
        if r["variant_label"] == "control" and r["project_id"] in dual_arm_projects
    ]
    dual_arm_variant = [
        r for r in samples
        if r["variant_label"] == "variant" and r["project_id"] in dual_arm_projects
    ]
    print(f"\n--- Dual-arm projects only ({len(dual_arm_projects)} projects) ---")
    print(f"  Pooled: control={len(dual_arm_control)}, variant={len(dual_arm_variant)}")

    dual_arm_result = analyze_group(
        dual_arm_control,
        dual_arm_variant,
        label="combined:dual_arm_projects_only",
    )

    # Build final output
    output: Dict[str, Any] = {
        "analysis_version": "v3",
        "description": (
            "A/B quality analysis excluding Ollama local agent. "
            "Tests: Mann-Whitney U, Cohen's d, bootstrap 95% CI, "
            "Fisher's exact on success rates, per-dimension breakdowns."
        ),
        "filters": {
            "excluded_agent_ids": ["local"],
            "total_samples_after_filter": len(samples),
        },
        "projects_analyzed": len(project_results),
        "dual_arm_project_count": len(dual_arm_projects),
        "per_project": project_results,
        "combined_openrouter_only": combined_result,
        "combined_dual_arm_only": dual_arm_result,
    }

    # Print summary
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)

    if combined_result:
        cr = combined_result
        print(f"\nCombined (all projects, OpenRouter only):")
        print(f"  N: control={cr['n_control']}, variant={cr['n_variant']}")
        cc = cr["control_composite"]
        vc = cr["variant_composite"]
        if cc["mean"] is not None:
            print(f"  Control composite:  mean={cc['mean']:.4f}  std={cc['std']:.4f}" if cc['std'] else f"  Control composite:  mean={cc['mean']:.4f}")
        if vc["mean"] is not None:
            print(f"  Variant composite:  mean={vc['mean']:.4f}  std={vc['std']:.4f}" if vc['std'] else f"  Variant composite:  mean={vc['mean']:.4f}")

        mw = cr["mann_whitney_u"]
        if mw["p_value"] is not None:
            print(f"  Mann-Whitney U: U={mw['U_statistic']:.1f}, p={mw['p_value']:.6f}"
                  f"  {'*** SIGNIFICANT' if mw['significant_at_005'] else '(not significant)'}")

        cd = cr["cohens_d"]
        if cd["d"] is not None:
            print(f"  Cohen's d: {cd['d']:.4f} ({cd['interpretation']}, {cd['direction']})")

        bs = cr["bootstrap_ci_95"]
        if bs["lower"] is not None:
            print(f"  Bootstrap 95% CI: [{bs['lower']:.4f}, {bs['upper']:.4f}]"
                  f"  point={bs['point_estimate']:.4f}"
                  f"  {'excludes zero' if bs['ci_excludes_zero'] else 'includes zero'}")

        sr = cr["success_rate"]
        if sr["control_rate"] is not None and sr["variant_rate"] is not None:
            print(f"  Success rate: control={sr['control_rate']:.3f} ({sr['control_successes']}/{sr['control_total']})"
                  f"  variant={sr['variant_rate']:.3f} ({sr['variant_successes']}/{sr['variant_total']})")
            fe = sr["fisher_exact"]
            if fe["p_value"] is not None:
                print(f"  Fisher's exact: OR={fe['odds_ratio']:.3f}, p={fe['p_value']:.6f}"
                      f"  {'*** SIGNIFICANT' if fe['significant_at_005'] else '(not significant)'}")

        print(f"\n  Per-dimension (variant - control mean diff):")
        for dim, dv in cr["per_dimension"].items():
            short = dim.replace("d_", "")
            md = dv["mean_diff"]
            cd_val = dv["cohens_d"]
            interp = dv["interpretation"]
            p_val = dv["mann_whitney_p"]
            parts = [f"    {short:30s}"]
            if md is not None:
                parts.append(f"diff={md:+.4f}")
            if cd_val is not None:
                parts.append(f"d={cd_val:+.4f} ({interp})")
            if p_val is not None:
                parts.append(f"p={p_val:.4f}")
            print("  ".join(parts))

    # Per-project summary table
    print(f"\nPer-project results ({len(project_results)} projects):")
    print(f"  {'Project':14s} {'Ctrl':>5s} {'Var':>5s} {'Ctrl_M':>8s} {'Var_M':>8s} {'d':>8s} {'MW_p':>10s} {'SR_ctrl':>8s} {'SR_var':>8s}")
    print(f"  {'-'*14} {'-'*5} {'-'*5} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*8} {'-'*8}")
    for pr in project_results:
        pid_short = pr["project_id"][:12] + ".."
        nc = pr["n_control"]
        nv = pr["n_variant"]
        cm = pr["control_composite"]["mean"]
        vm = pr["variant_composite"]["mean"]
        d_val = pr["cohens_d"]["d"]
        mw_p = pr["mann_whitney_u"]["p_value"]
        sr_c = pr["success_rate"]["control_rate"]
        sr_v = pr["success_rate"]["variant_rate"]
        print(
            f"  {pid_short:14s} "
            f"{nc:5d} {nv:5d} "
            f"{cm:8.4f} " if cm is not None else f"  {pid_short:14s} {nc:5d} {nv:5d}      N/A ",
            end="",
        )
        print(f"{vm:8.4f} " if vm is not None else "     N/A ", end="")
        print(f"{d_val:8.4f} " if d_val is not None else "     N/A ", end="")
        print(f"{mw_p:10.6f} " if mw_p is not None else "       N/A ", end="")
        print(f"{sr_c:8.3f} " if sr_c is not None else "     N/A ", end="")
        print(f"{sr_v:8.3f}" if sr_v is not None else "     N/A")

    # Save results
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Convert numpy/nan to JSON-serializable values
    def sanitize(obj: Any) -> Any:
        if isinstance(obj, float) and math.isnan(obj):
            return None
        if isinstance(obj, float) and math.isinf(obj):
            return None
        if isinstance(obj, (np.floating, np.integer)):
            return float(obj)
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [sanitize(v) for v in obj]
        return obj

    output = sanitize(output)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
