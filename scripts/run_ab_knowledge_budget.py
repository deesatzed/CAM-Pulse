#!/usr/bin/env python3
"""A/B Paired Experiment — Knowledge Budget: 24K vs 32K chars.

Design:
  For each (task, agent) pair, run the task TWICE:
    1. Arm A: knowledge_budget_chars = 24000
    2. Arm B: knowledge_budget_chars = 32000

  Both arms receive full knowledge — only the BUDGET SIZE differs.
  This tests whether more context helps or hurts (context window pressure
  vs richer knowledge).

  Same paired design as run_ab_paired.py — eliminates agent and task
  confounding.

  Statistical tests: Wilcoxon signed-rank (composite), McNemar (success),
  paired t-test, bootstrap CI on mean paired difference.

Usage:
    PYTHONUNBUFFERED=1 PYTHONPATH=src python -u scripts/run_ab_knowledge_budget.py --max-pairs 26
    PYTHONUNBUFFERED=1 PYTHONPATH=src python -u scripts/run_ab_knowledge_budget.py --agent codex --max-pairs 20
    PYTHONUNBUFFERED=1 PYTHONPATH=src python -u scripts/run_ab_knowledge_budget.py --budget-a 16000 --budget-b 32000
"""

import asyncio
import argparse
import logging
import random
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claw.core.factory import ClawFactory
from claw.core.models import Project, Task, TaskStatus
from claw.cycle import MicroClaw

logger = logging.getLogger("ab_budget")

# ---------------------------------------------------------------------------
# Curated tasks: same calibrated set as run_ab_paired.py
# ---------------------------------------------------------------------------

PAIRED_TASKS = [
    {
        "title": "Fix rationale extraction for function docstrings",
        "description": "tests/test_rationale.py::test_function_docstring_extracted is failing. The rationale module should extract Python function docstrings as design rationale. Investigate the rationale extractor in graphify/ and fix the extraction logic so the test passes.",
        "task_type": "bug_fix",
    },
    {
        "title": "Fix rationale extraction for class docstrings",
        "description": "tests/test_rationale.py::test_class_docstring_extracted is failing. The rationale module should extract Python class docstrings as design rationale. Fix the class docstring extraction so the test passes.",
        "task_type": "bug_fix",
    },
    {
        "title": "Fix rationale comment extraction",
        "description": "tests/test_rationale.py::test_rationale_comment_extracted is failing. The rationale module should extract inline comments marked as design rationale. Fix the comment extraction logic.",
        "task_type": "bug_fix",
    },
    {
        "title": "Add docstring to graph export functions",
        "description": "In graphify/export.py, the to_json() and to_html() functions need better docstrings. Add clear docstrings explaining the parameters (G: nx.Graph, communities: dict, path: Path) and what each function outputs.",
        "task_type": "documentation",
    },
    {
        "title": "Add type hints to cluster module public API",
        "description": "In graphify/cluster.py, the cluster() function and cohesion_score() function lack complete type annotations. Add proper type hints: cluster(G: nx.Graph) -> dict[int, list[str]], cohesion_score(G: nx.Graph, community: list[str]) -> float.",
        "task_type": "enhancement",
    },
    {
        "title": "Fix edge rationale presence assertion",
        "description": "tests/test_rationale.py::test_rationale_for_edges_present is failing with 'assert 0 >= 1'. The rationale module should detect design rationale on graph edges (e.g., why a dependency exists). Fix the edge rationale detection.",
        "task_type": "bug_fix",
    },
    {
        "title": "Add test for cache clear function",
        "description": "graphify/cache.py has a clear_cache() function with no test coverage. Add a test in tests/test_cache.py that calls clear_cache() and verifies the cache directory is empty afterwards.",
        "task_type": "testing",
    },
    {
        "title": "Add README section for graph export formats",
        "description": "The graphify README.md needs a section explaining the available export formats (JSON, HTML). Document the to_json() and to_html() functions, including example output structure and usage.",
        "task_type": "documentation",
    },
    {
        "title": "Fix graph builder missing file handling",
        "description": "graphify/builder.py should gracefully handle missing files when building the dependency graph. If a file path doesn't exist, log a warning and skip it instead of raising an exception. Add a test case for this behavior.",
        "task_type": "bug_fix",
    },
    {
        "title": "Add test for empty graph clustering",
        "description": "graphify/cluster.py's cluster() function should handle an empty graph (no nodes) without error. Add a test in tests/test_cluster.py that verifies cluster(nx.Graph()) returns an empty dict.",
        "task_type": "testing",
    },
    {
        "title": "Fix cohesion score for single-node communities",
        "description": "graphify/cluster.py's cohesion_score() should return 1.0 for a community with only one node (trivially cohesive). Currently it may return 0.0 or raise an error. Fix the edge case.",
        "task_type": "bug_fix",
    },
    {
        "title": "Add graph statistics summary function",
        "description": "Add a get_summary(G: nx.Graph) -> dict function to graphify/stats.py that returns: node_count, edge_count, density, average_degree, connected_components_count. Include a test.",
        "task_type": "enhancement",
    },
    {
        "title": "Fix import order in graphify __init__.py",
        "description": "graphify/__init__.py has inconsistent import ordering. Reorder imports to follow PEP 8: standard library, third-party, local. Also ensure all public functions are listed in __all__.",
        "task_type": "enhancement",
    },
    {
        "title": "Add test for graph cycle detection",
        "description": "Add a test in tests/test_builder.py that builds a graph with a known cycle (A->B->C->A) and verifies the cycle is correctly represented in the graph structure.",
        "task_type": "testing",
    },
    {
        "title": "Fix HTML export template escaping",
        "description": "graphify/export.py's to_html() doesn't escape node labels that contain HTML special characters (<, >, &). Fix by applying html.escape() to node labels and edge labels.",
        "task_type": "bug_fix",
    },
    {
        "title": "Add filter parameter to graph builder",
        "description": "Add an optional exclude_patterns parameter to graphify/builder.py's build_graph() function that accepts a list of glob patterns to exclude from the graph (e.g., ['test_*', '__pycache__']). Include a test.",
        "task_type": "enhancement",
    },
    {
        "title": "Fix JSON export with numpy types",
        "description": "graphify/export.py's to_json() fails when graph attributes contain numpy types (int64, float64). Add a custom JSON encoder that converts numpy types to native Python types.",
        "task_type": "bug_fix",
    },
    {
        "title": "Add graph diff function for change detection",
        "description": "Add a diff_graphs(old: nx.Graph, new: nx.Graph) -> dict function to graphify/diff.py that returns added_nodes, removed_nodes, added_edges, removed_edges. Include a test.",
        "task_type": "enhancement",
    },
    {
        "title": "Fix cache directory creation race condition",
        "description": "graphify/cache.py may fail if two processes try to create the cache directory simultaneously. Use os.makedirs(exist_ok=True) instead of checking os.path.exists() first.",
        "task_type": "bug_fix",
    },
    {
        "title": "Add test for large graph performance",
        "description": "Add a performance test that creates a graph with 1000 nodes and 5000 edges, runs cluster() and cohesion_score(), and asserts completion within 5 seconds.",
        "task_type": "testing",
    },
    {
        "title": "Add graph visualization color mapping",
        "description": "Add a community_colors(communities: dict) -> dict function to graphify/visualize.py that assigns a distinct color to each community using matplotlib's tab20 colormap. Include a test.",
        "task_type": "enhancement",
    },
    {
        "title": "Fix rationale extraction for multi-line docstrings",
        "description": "The rationale extractor in graphify/ fails to capture multi-line docstrings (triple-quote across multiple lines). Fix the regex or parser to handle multi-line docstrings correctly.",
        "task_type": "bug_fix",
    },
    {
        "title": "Add CLI entry point for graph analysis",
        "description": "Add a __main__.py to graphify/ that provides a basic CLI: python -m graphify /path/to/project --format json --output graph.json. Use argparse.",
        "task_type": "enhancement",
    },
    {
        "title": "Fix builder handling of circular imports",
        "description": "graphify/builder.py should detect and label circular import edges in the dependency graph with a 'circular' attribute. Add a test with known circular imports.",
        "task_type": "bug_fix",
    },
    {
        "title": "Add graph serialization roundtrip test",
        "description": "Add a test that creates a graph with mixed attribute types (str, int, float, list), serializes to JSON, deserializes, and verifies all attributes are preserved.",
        "task_type": "testing",
    },
    {
        "title": "Fix cluster module import of optional dependency",
        "description": "graphify/cluster.py directly imports community_louvain at the top level, causing ImportError when python-louvain isn't installed. Move to a lazy import inside cluster() with a helpful error message.",
        "task_type": "bug_fix",
    },
]

# Agents to round-robin (exclude local — it can't modify workspace via CLI)
AGENT_POOL = ["claude", "codex", "gemini", "grok", "codex"]

# Repository used for all tasks
REPO_PATH = str(Path(__file__).resolve().parent.parent / "src" / "graphify")


def _reset_repo():
    """Hard-reset the graphify workspace to HEAD."""
    try:
        subprocess.run(
            ["git", "checkout", "--", "src/graphify/"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass


async def _set_knowledge_budget(ctx, budget_chars: int):
    """Dynamically adjust the knowledge budget on all agents."""
    for agent in ctx.agents.values():
        if hasattr(agent, "_cag_knowledge_budget"):
            agent._cag_knowledge_budget = budget_chars


async def _seed_single_task(ctx, project_id: str, task_def: dict, suffix: str = "") -> str:
    """Seed a single task and return its ID."""
    task = Task(
        id=str(uuid.uuid4()),
        project_id=project_id,
        title=task_def["title"] + suffix,
        description=task_def["description"],
        task_type=task_def.get("task_type", "enhancement"),
        status=TaskStatus.PENDING,
    )
    await ctx.repository.engine.execute(
        """INSERT INTO tasks (id, project_id, title, description, task_type, status, priority)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [task.id, task.project_id, task.title, task.description,
         task.task_type, task.status.value, task.priority],
    )
    return task.id


async def _retire_all_except(ctx, project_id: str, keep_id: str):
    """Set all tasks except keep_id to DONE."""
    await ctx.repository.engine.execute(
        "UPDATE tasks SET status='DONE' WHERE project_id=? AND id != ? AND status != 'DONE'",
        [project_id, keep_id],
    )


async def _force_variant(ctx, label: str):
    """Force the A/B variant selection to return the specified label."""
    other = "variant" if label == "control" else "control"
    row = await ctx.repository.engine.fetch_one(
        "SELECT * FROM prompt_variants WHERE prompt_name='knowledge_ablation' AND variant_label=?",
        [other],
    )
    await ctx.repository.engine.execute(
        "DELETE FROM prompt_variants WHERE prompt_name='knowledge_ablation' AND variant_label=?",
        [other],
    )
    return row


async def _restore_variant(ctx, stashed_row):
    """Restore a previously stashed variant row."""
    if stashed_row is None:
        return
    await ctx.repository.engine.execute(
        """INSERT OR IGNORE INTO prompt_variants
           (id, prompt_name, variant_label, content, agent_id, is_active,
            sample_count, success_count, avg_quality_score, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [stashed_row["id"], stashed_row["prompt_name"], stashed_row["variant_label"],
         stashed_row["content"], stashed_row.get("agent_id"),
         stashed_row["is_active"], stashed_row["sample_count"],
         stashed_row["success_count"], stashed_row["avg_quality_score"],
         stashed_row.get("created_at", ""), stashed_row.get("updated_at", "")],
    )


async def _run_one_arm(
    ctx,
    cycle: MicroClaw,
    project_id: str,
    task_def: dict,
    arm_label: str,
    agent_id: str,
    budget_chars: int,
) -> dict:
    """Run a single arm with a specific knowledge budget."""
    _reset_repo()

    # Set the knowledge budget for all agents
    await _set_knowledge_budget(ctx, budget_chars)

    suffix = f" [budget={budget_chars}]"
    task_id = await _seed_single_task(ctx, project_id, task_def, suffix)
    await _retire_all_except(ctx, project_id, task_id)

    # Force variant to 'variant' (both arms get full knowledge, just different budgets)
    stashed = await _force_variant(ctx, "variant")

    # Force agent assignment
    await ctx.repository.engine.execute(
        "UPDATE tasks SET recommended_agent=? WHERE id=?",
        [agent_id, task_id],
    )

    try:
        await cycle.run_cycle()

        sample = await ctx.repository.engine.fetch_one(
            """SELECT composite_score, success, d_functional_correctness,
                      d_structural_compliance, d_intent_alignment,
                      d_correction_efficiency, d_token_economy, d_expectation_match,
                      correction_attempts, variant_label, agent_id
               FROM ab_quality_samples
               WHERE task_id=? ORDER BY created_at DESC LIMIT 1""",
            [task_id],
        )
        if sample:
            return {
                "task_id": task_id,
                "arm": arm_label,
                "budget": budget_chars,
                "agent": str(sample["agent_id"]),
                "composite": float(sample["composite_score"]),
                "success": int(sample["success"]),
                "fc": float(sample["d_functional_correctness"]),
                "sc": float(sample["d_structural_compliance"]),
                "ia": float(sample["d_intent_alignment"]),
                "ce": float(sample["d_correction_efficiency"]),
                "te": float(sample["d_token_economy"]),
                "em": float(sample["d_expectation_match"]),
                "attempts": int(sample["correction_attempts"]),
            }
        else:
            return {"task_id": task_id, "arm": arm_label, "budget": budget_chars,
                    "agent": agent_id, "composite": 0.0, "success": 0,
                    "error": "no_sample_recorded"}
    except Exception as e:
        logger.error("Arm %s (budget=%d) failed: %s", arm_label, budget_chars, e)
        return {"task_id": task_id, "arm": arm_label, "budget": budget_chars,
                "agent": agent_id, "composite": 0.0, "success": 0, "error": str(e)}
    finally:
        await _restore_variant(ctx, stashed)


async def main(
    max_pairs: int = 26,
    fixed_agent: str = "",
    budget_a: int = 24000,
    budget_b: int = 32000,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    ctx = await ClawFactory.create()
    ctx.dispatcher = None  # Disable dispatcher so recommended_agent is honored

    for agent in ctx.agents.values():
        agent.workspace_dir = REPO_PATH

    project_id = str(uuid.uuid4())
    proj = Project(id=project_id, name="ab-budget-graphify", repo_path=REPO_PATH)
    await ctx.repository.engine.execute(
        "INSERT OR IGNORE INTO projects (id, name, repo_path) VALUES (?, ?, ?)",
        [proj.id, proj.name, proj.repo_path],
    )

    print(f"\n{'='*60}")
    print(f"  KNOWLEDGE BUDGET A/B EXPERIMENT")
    print(f"  Design: Same task x same agent x two budget sizes")
    print(f"  Arm A: {budget_a:,} chars")
    print(f"  Arm B: {budget_b:,} chars")
    print(f"  Tasks: {len(PAIRED_TASKS)} curated (>=50% historical success)")
    print(f"  Max pairs: {max_pairs}")
    print(f"  Agent: {fixed_agent or 'round-robin ' + str(AGENT_POOL)}")
    print(f"  Project: {project_id[:12]}...")
    print(f"{'='*60}\n")

    tasks_to_run = list(PAIRED_TASKS)
    random.shuffle(tasks_to_run)
    tasks_to_run = tasks_to_run[:max_pairs]

    pairs = []
    start = time.monotonic()

    for i, task_def in enumerate(tasks_to_run):
        if fixed_agent:
            agent_id = fixed_agent
        else:
            agent_id = AGENT_POOL[i % len(AGENT_POOL)]

        # Randomize arm order to avoid order effects
        arms = [("arm_a", budget_a), ("arm_b", budget_b)]
        random.shuffle(arms)

        print(f"\n--- Pair {i+1}/{len(tasks_to_run)}: {task_def['title'][:50]}... (agent={agent_id}) ---")

        pair_results = {}
        for arm_label, budget in arms:
            cycle = MicroClaw(ctx, project_id=project_id)
            print(f"  Running {arm_label} (budget={budget:,})...", end=" ", flush=True)
            arm_start = time.monotonic()
            result = await _run_one_arm(ctx, cycle, project_id, task_def, arm_label, agent_id, budget)
            arm_dur = time.monotonic() - arm_start
            pair_results[arm_label] = result

            status = "OK" if result["success"] else "FAIL"
            print(f"[{status}] composite={result['composite']:.3f} ({arm_dur:.0f}s)")

        a_result = pair_results.get("arm_a", {})
        b_result = pair_results.get("arm_b", {})
        diff = b_result.get("composite", 0) - a_result.get("composite", 0)
        pairs.append({
            "task": task_def["title"],
            "agent": agent_id,
            "arm_a": a_result,
            "arm_b": b_result,
            "diff": diff,
            "a_success": a_result.get("success", 0),
            "b_success": b_result.get("success", 0),
        })

        # Running tally
        diffs = [p["diff"] for p in pairs]
        import numpy as np
        wins = sum(1 for d in diffs if d > 0.01)
        ties = sum(1 for d in diffs if abs(d) <= 0.01)
        losses = sum(1 for d in diffs if d < -0.01)
        mean_d = np.mean(diffs)
        print(f"  Pair diff (B-A): {diff:+.3f} | Running: mean={mean_d:+.3f}, W/T/L={wins}/{ties}/{losses}")

    # ===================================================================
    # Final Statistical Analysis
    # ===================================================================
    elapsed = time.monotonic() - start
    import numpy as np
    from scipy import stats

    a_comps = [p["arm_a"]["composite"] for p in pairs]
    b_comps = [p["arm_b"]["composite"] for p in pairs]
    diffs = [b - a for a, b in zip(a_comps, b_comps)]

    a_succs = [p["a_success"] for p in pairs]
    b_succs = [p["b_success"] for p in pairs]

    print(f"\n{'='*60}")
    print(f"  KNOWLEDGE BUDGET A/B RESULTS")
    print(f"  Arm A: {budget_a:,} chars | Arm B: {budget_b:,} chars")
    print(f"  Duration: {elapsed/60:.1f} minutes")
    print(f"  Pairs: {len(pairs)}")
    print(f"  Project: {project_id}")
    print(f"{'='*60}")

    print(f"\n  COMPOSITE SCORES:")
    print(f"    Arm A ({budget_a:,}): mean={np.mean(a_comps):.3f} (std={np.std(a_comps):.3f})")
    print(f"    Arm B ({budget_b:,}): mean={np.mean(b_comps):.3f} (std={np.std(b_comps):.3f})")
    print(f"    Mean diff (B-A): {np.mean(diffs):+.3f}")
    print(f"    Median diff:     {np.median(diffs):+.3f}")

    print(f"\n  SUCCESS RATES:")
    print(f"    Arm A ({budget_a:,}): {sum(a_succs)}/{len(a_succs)} ({100*np.mean(a_succs):.1f}%)")
    print(f"    Arm B ({budget_b:,}): {sum(b_succs)}/{len(b_succs)} ({100*np.mean(b_succs):.1f}%)")

    wins = sum(1 for d in diffs if d > 0.01)
    ties = sum(1 for d in diffs if abs(d) <= 0.01)
    losses = sum(1 for d in diffs if d < -0.01)
    print(f"    Win/Tie/Loss (B vs A): {wins}/{ties}/{losses}")

    print(f"\n  STATISTICAL TESTS:")

    # 1. Paired t-test (two-sided — we don't know which budget is better)
    if len(diffs) >= 5:
        t_stat, t_pval = stats.ttest_1samp(diffs, 0)
        print(f"    Paired t-test (two-sided): t={t_stat:.3f}, p={t_pval:.4f}")

    # 2. Wilcoxon signed-rank (non-parametric paired, two-sided)
    non_zero_diffs = [d for d in diffs if abs(d) > 0.001]
    if len(non_zero_diffs) >= 5:
        w_stat, w_pval = stats.wilcoxon(
            [b for b, d in zip(b_comps, diffs) if abs(d) > 0.001],
            [a for a, d in zip(a_comps, diffs) if abs(d) > 0.001],
        )
        print(f"    Wilcoxon signed-rank (two-sided): W={w_stat:.0f}, p={w_pval:.4f}")

    # 3. McNemar test for success rates (paired binary)
    ctrl_wins = sum(1 for a, b in zip(a_succs, b_succs) if a == 1 and b == 0)
    var_wins = sum(1 for a, b in zip(a_succs, b_succs) if a == 0 and b == 1)
    if ctrl_wins + var_wins > 0:
        mcnemar_p = stats.binomtest(var_wins, ctrl_wins + var_wins, 0.5).pvalue
        print(f"    McNemar (success, two-sided): B_wins={var_wins} vs A_wins={ctrl_wins}, p={mcnemar_p:.4f}")

    # 4. Bootstrap CI for mean paired difference
    np.random.seed(42)
    boot_diffs = []
    for _ in range(10000):
        idx = np.random.choice(len(diffs), size=len(diffs), replace=True)
        boot_diffs.append(np.mean([diffs[i] for i in idx]))
    ci_lo, ci_hi = np.percentile(boot_diffs, [2.5, 97.5])
    print(f"    Bootstrap 95% CI for mean diff (B-A): [{ci_lo:.3f}, {ci_hi:.3f}]")

    # 5. Cohen's dz (paired effect size)
    if np.std(diffs) > 0:
        dz = np.mean(diffs) / np.std(diffs)
        print(f"    Cohen's dz (paired): {dz:.3f}")

    # 6. Dimension-level analysis
    dims = ["fc", "sc", "ia", "ce", "te", "em"]
    dim_names = {
        "fc": "Functional Correctness",
        "sc": "Structural Compliance",
        "ia": "Intent Alignment",
        "ce": "Correction Efficiency",
        "te": "Token Economy",
        "em": "Expectation Match",
    }
    print(f"\n  DIMENSION-LEVEL ANALYSIS (B - A):")
    for dim in dims:
        a_vals = [p["arm_a"].get(dim, 0.0) for p in pairs]
        b_vals = [p["arm_b"].get(dim, 0.0) for p in pairs]
        dim_diffs = [b - a for a, b in zip(a_vals, b_vals)]
        mean_dd = np.mean(dim_diffs)
        if len(dim_diffs) >= 5 and np.std(dim_diffs) > 0:
            t_s, t_p = stats.ttest_1samp(dim_diffs, 0)
            sig = "*" if t_p < 0.05 else " "
            print(f"    {dim_names[dim]:30s}: {mean_dd:+.3f} (p={t_p:.3f}) {sig}")
        else:
            print(f"    {dim_names[dim]:30s}: {mean_dd:+.3f}")

    # Conclusion
    print(f"\n  CONCLUSION:")
    mean_diff = np.mean(diffs)
    if len(non_zero_diffs) >= 5:
        if w_pval < 0.05:
            if mean_diff > 0:
                print(f"    SIGNIFICANT: {budget_b:,} chars BETTER than {budget_a:,} (p={w_pval:.4f})")
            else:
                print(f"    SIGNIFICANT: {budget_a:,} chars BETTER than {budget_b:,} (p={w_pval:.4f})")
        else:
            print(f"    NO SIGNIFICANT DIFFERENCE between {budget_a:,} and {budget_b:,} (p={w_pval:.4f})")
    else:
        print(f"    INSUFFICIENT DATA for significance testing (need >= 5 non-zero diffs)")

    await ctx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A/B Knowledge Budget Experiment")
    parser.add_argument("--max-pairs", type=int, default=26)
    parser.add_argument("--agent", type=str, default="")
    parser.add_argument("--budget-a", type=int, default=24000, help="Budget for arm A (chars)")
    parser.add_argument("--budget-b", type=int, default=32000, help="Budget for arm B (chars)")
    args = parser.parse_args()

    asyncio.run(main(
        max_pairs=args.max_pairs,
        fixed_agent=args.agent,
        budget_a=args.budget_a,
        budget_b=args.budget_b,
    ))
