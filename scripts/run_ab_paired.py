#!/usr/bin/env python3
"""A/B Paired Within-Subject Experiment — Eliminates Agent & Task Confounding.

Design:
  For each (task, agent) pair, run the task TWICE:
    1. Control: knowledge suppressed (past_solutions=[], _cag_corpus="")
    2. Variant: full knowledge injected

  This paired design eliminates:
    - Agent confounding (same agent for both arms)
    - Task difficulty confounding (same task for both arms)
    - Requires ~4x fewer samples than unpaired design

  Statistical tests: Wilcoxon signed-rank (composite), McNemar (success),
  paired t-test, bootstrap CI on mean paired difference.

Only uses tasks with >50% historical success rate from the first trial.

Usage:
    PYTHONUNBUFFERED=1 PYTHONPATH=src python -u scripts/run_ab_paired.py --max-pairs 40
    PYTHONUNBUFFERED=1 PYTHONPATH=src python -u scripts/run_ab_paired.py --agent codex --max-pairs 20
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

logger = logging.getLogger("ab_paired")

# ---------------------------------------------------------------------------
# Curated tasks: only tasks that achieved >=50% success in the first trial
# These are calibrated to be achievable so the KB signal can emerge.
# ---------------------------------------------------------------------------

PAIRED_TASKS = [
    # 100% success rate in trial 1
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
        "description": "In tests/test_cache.py, add a test for the clear_cache() function. Save a cached result, call clear_cache(), then verify load_cached() returns None for the same file. Use tmp_path.",
        "task_type": "testing",
    },
    {
        "title": "Add test for validate_url with ftp scheme",
        "description": "In tests/test_security.py, add a test that calls validate_url('ftp://example.com/file.txt') and verifies it raises ValueError with a message about unsupported scheme.",
        "task_type": "testing",
    },
    {
        "title": "Add test for detect with empty directory",
        "description": "In tests/test_detect.py, add a test that calls detect() on an empty tmp_path directory and verifies the result has total_files=0 and needs_graph=False.",
        "task_type": "testing",
    },
    {
        "title": "Add test for classify_file with Python extension",
        "description": "In tests/test_detect.py, add a test that calls classify_file() with a .py file path and verifies it returns 'code' as the file type.",
        "task_type": "testing",
    },
    {
        "title": "Add test for classify_file with markdown extension",
        "description": "In tests/test_detect.py, add a test that calls classify_file() with a .md file path and verifies it returns 'document' as the file type.",
        "task_type": "testing",
    },
    {
        "title": "Add test for god_nodes with single-node graph",
        "description": "In tests/test_analyze.py, add a test that creates a graph with one node and calls god_nodes(). Verify it returns an empty list since a single node can't dominate.",
        "task_type": "testing",
    },
    {
        "title": "Add test for to_wiki with single community",
        "description": "In tests/test_wiki.py, add a test that calls to_wiki() with a graph that has one community. Verify the markdown output contains the community label.",
        "task_type": "testing",
    },
    {
        "title": "Add test for hooks status when not installed",
        "description": "In tests/test_hooks.py, add a test that calls hooks_status() on a fresh tmp_path (no .git/hooks). Verify it returns an empty dict or indicates not installed.",
        "task_type": "testing",
    },
    {
        "title": "Add type hints to validate module",
        "description": "In graphify/validate.py, add return type annotations to all public functions. Use appropriate types from typing module.",
        "task_type": "enhancement",
    },
    {
        "title": "Add type hints to cache module functions",
        "description": "In graphify/cache.py, add type annotations to all public functions: load_cached, save_cached, clear_cache, cached_files, file_hash. Use Path, Optional, etc.",
        "task_type": "enhancement",
    },
    {
        "title": "Add return type hint to report generate function",
        "description": "In graphify/report.py, add a return type hint to the generate() function. It should return str (the generated report text).",
        "task_type": "enhancement",
    },
    {
        "title": "Add test for validate assert_valid raises on bad data",
        "description": "In tests/test_validate.py, add a test that calls assert_valid() with data missing required keys and verifies it raises ValueError.",
        "task_type": "testing",
    },
    {
        "title": "Add test for file_hash determinism",
        "description": "In tests/test_cache.py, add a test that calls file_hash() on the same file twice and verifies both calls return the identical hash string. Use tmp_path to create a temp file.",
        "task_type": "testing",
    },
    {
        "title": "Add test for cohesion_score returns float between 0 and 1",
        "description": "In tests/test_cluster.py, add a test that creates a small graph with a community of 3 connected nodes and verifies cohesion_score() returns a float in [0.0, 1.0].",
        "task_type": "testing",
    },
    {
        "title": "Add test for sanitize_label with HTML entities",
        "description": "In tests/test_security.py, add a test that calls sanitize_label('<script>alert(1)</script>') and verifies the HTML tags are stripped or escaped.",
        "task_type": "testing",
    },
    # 50% success rate in trial 1 — still viable
    {
        "title": "Add test for cached_files listing",
        "description": "In tests/test_cache.py, add a test for cached_files() that saves two different files to the cache and verifies cached_files() returns a set with both hashes.",
        "task_type": "testing",
    },
    {
        "title": "Add test for sanitize_label with control characters",
        "description": "In tests/test_security.py, add a test that calls sanitize_label() with a string containing control characters (e.g., '\\x00hello\\x1f') and verifies they are stripped from the output.",
        "task_type": "testing",
    },
    {
        "title": "Add test for graph_diff with identical graphs",
        "description": "In tests/test_analyze.py, add a test that creates two identical graphs and calls graph_diff(). Verify the diff has zero additions, zero removals.",
        "task_type": "testing",
    },
    {
        "title": "Add test for build with duplicate node IDs",
        "description": "In tests/test_build.py, add a test that calls build() with extraction data containing two nodes with the same ID. Verify the graph has only one node (deduplication).",
        "task_type": "testing",
    },
    {
        "title": "Add test for cluster with disconnected graph",
        "description": "In tests/test_cluster.py, add a test that creates a graph with two disconnected components (A-B, C-D) and verifies cluster() returns at least 2 communities.",
        "task_type": "testing",
    },
]

REPO_PATH = "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify"

# Agents to cycle through — in order of observed success rate
AGENT_POOL = ["codex", "local", "grok", "claude", "gemini"]


def _reset_repo():
    """Hard reset target repo to clean state."""
    subprocess.run(["git", "checkout", "."], cwd=REPO_PATH, capture_output=True, timeout=10)
    subprocess.run(["git", "clean", "-fd"], cwd=REPO_PATH, capture_output=True, timeout=10)


async def _force_variant(ctx, label: str):
    """Force the next A/B selection to return the specified label.

    Strategy: temporarily DELETE the other arm from prompt_variants so
    select_variant_for_invocation() only finds one row and returns it.
    We stash the deleted row and restore it after the cycle.
    """
    other = "variant" if label == "control" else "control"

    # Stash the other arm's row
    row = await ctx.repository.engine.fetch_one(
        "SELECT * FROM prompt_variants WHERE prompt_name='knowledge_ablation' AND variant_label=?",
        [other],
    )

    # Delete the other arm temporarily
    await ctx.repository.engine.execute(
        "DELETE FROM prompt_variants WHERE prompt_name='knowledge_ablation' AND variant_label=?",
        [other],
    )

    return row  # Caller must restore this


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
    """Set all tasks except keep_id to DONE so the cycle only picks the one we want."""
    await ctx.repository.engine.execute(
        "UPDATE tasks SET status='DONE' WHERE project_id=? AND id != ? AND status != 'DONE'",
        [project_id, keep_id],
    )


async def _run_one_arm(
    ctx,
    cycle: MicroClaw,
    project_id: str,
    task_def: dict,
    arm_label: str,
    agent_id: str,
) -> dict:
    """Run a single arm (control or variant) for a paired experiment."""
    _reset_repo()

    # Seed a fresh task for this arm
    suffix = f" [{arm_label}]"
    task_id = await _seed_single_task(ctx, project_id, task_def, suffix)

    # Retire everything else so cycle picks this task
    await _retire_all_except(ctx, project_id, task_id)

    # Force the variant assignment by temporarily removing the other arm
    stashed = await _force_variant(ctx, arm_label)

    # Force agent assignment by setting recommended_agent
    # (dispatcher is disabled so this will be honored)
    await ctx.repository.engine.execute(
        "UPDATE tasks SET recommended_agent=? WHERE id=?",
        [agent_id, task_id],
    )

    # Run cycle
    try:
        result = await cycle.run_cycle()

        # Read back the ab_quality_sample for this task
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
                "arm": str(sample["variant_label"]),
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
            return {"task_id": task_id, "arm": arm_label, "agent": agent_id,
                    "composite": 0.0, "success": 0, "error": "no_sample_recorded"}
    except Exception as e:
        logger.error("Arm %s failed: %s", arm_label, e)
        return {"task_id": task_id, "arm": arm_label, "agent": agent_id,
                "composite": 0.0, "success": 0, "error": str(e)}
    finally:
        # ALWAYS restore the stashed variant row
        await _restore_variant(ctx, stashed)


async def main(
    max_pairs: int = 40,
    fixed_agent: str = "",
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    ctx = await ClawFactory.create()

    # Disable dispatcher so recommended_agent is honored (not overridden by Kelly)
    ctx.dispatcher = None

    # Point all agents at graphify
    for agent in ctx.agents.values():
        agent.workspace_dir = REPO_PATH

    project_id = str(uuid.uuid4())
    proj = Project(id=project_id, name="ab-paired-graphify", repo_path=REPO_PATH)
    await ctx.repository.engine.execute(
        "INSERT OR IGNORE INTO projects (id, name, repo_path) VALUES (?, ?, ?)",
        [proj.id, proj.name, proj.repo_path],
    )

    print(f"\n{'='*60}")
    print(f"  PAIRED A/B EXPERIMENT")
    print(f"  Design: Same task × same agent × both arms")
    print(f"  Tasks: {len(PAIRED_TASKS)} curated (>=50% historical success)")
    print(f"  Max pairs: {max_pairs}")
    print(f"  Agent: {fixed_agent or 'round-robin ' + str(AGENT_POOL)}")
    print(f"  Project: {project_id[:12]}...")
    print(f"{'='*60}\n")

    # Shuffle tasks so we don't always run the same order
    tasks_to_run = list(PAIRED_TASKS)
    random.shuffle(tasks_to_run)
    tasks_to_run = tasks_to_run[:max_pairs]

    pairs = []
    start = time.monotonic()

    for i, task_def in enumerate(tasks_to_run):
        # Select agent for this pair
        if fixed_agent:
            agent_id = fixed_agent
        else:
            agent_id = AGENT_POOL[i % len(AGENT_POOL)]

        # Randomize arm order to avoid order effects
        arms = ["control", "variant"]
        random.shuffle(arms)

        print(f"\n--- Pair {i+1}/{len(tasks_to_run)}: {task_def['title'][:50]}... (agent={agent_id}) ---")

        pair_results = {}
        for arm in arms:
            cycle = MicroClaw(ctx, project_id=project_id)
            print(f"  Running {arm}...", end=" ", flush=True)
            arm_start = time.monotonic()
            result = _run_one_arm(ctx, cycle, project_id, task_def, arm, agent_id)
            result = await result
            arm_dur = time.monotonic() - arm_start
            pair_results[arm] = result

            status = "OK" if result["success"] else "FAIL"
            print(f"[{status}] composite={result['composite']:.3f} ({arm_dur:.0f}s)")

        ctrl = pair_results.get("control", {})
        var = pair_results.get("variant", {})
        diff = var.get("composite", 0) - ctrl.get("composite", 0)
        pairs.append({
            "task": task_def["title"],
            "agent": agent_id,
            "control": ctrl,
            "variant": var,
            "diff": diff,
            "ctrl_success": ctrl.get("success", 0),
            "var_success": var.get("success", 0),
        })

        # Running tally
        diffs = [p["diff"] for p in pairs]
        wins = sum(1 for d in diffs if d > 0.01)
        ties = sum(1 for d in diffs if abs(d) <= 0.01)
        losses = sum(1 for d in diffs if d < -0.01)
        import numpy as np
        mean_d = np.mean(diffs)
        print(f"  Pair diff: {diff:+.3f} | Running: mean={mean_d:+.3f}, W/T/L={wins}/{ties}/{losses}")

    # ===================================================================
    # Final Statistical Analysis
    # ===================================================================
    elapsed = time.monotonic() - start
    import numpy as np
    from scipy import stats

    ctrl_comps = [p["control"]["composite"] for p in pairs]
    var_comps = [p["variant"]["composite"] for p in pairs]
    diffs = [v - c for c, v in zip(ctrl_comps, var_comps)]

    ctrl_succs = [p["ctrl_success"] for p in pairs]
    var_succs = [p["var_success"] for p in pairs]

    print(f"\n{'='*60}")
    print(f"  PAIRED A/B EXPERIMENT RESULTS")
    print(f"  Duration: {elapsed/60:.1f} minutes")
    print(f"  Pairs: {len(pairs)}")
    print(f"  Project: {project_id}")
    print(f"{'='*60}")

    print(f"\n  COMPOSITE SCORES:")
    print(f"    Control mean: {np.mean(ctrl_comps):.3f} (std={np.std(ctrl_comps):.3f})")
    print(f"    Variant mean: {np.mean(var_comps):.3f} (std={np.std(var_comps):.3f})")
    print(f"    Mean diff:    {np.mean(diffs):+.3f}")
    print(f"    Median diff:  {np.median(diffs):+.3f}")

    print(f"\n  SUCCESS RATES:")
    print(f"    Control: {sum(ctrl_succs)}/{len(ctrl_succs)} ({100*np.mean(ctrl_succs):.1f}%)")
    print(f"    Variant: {sum(var_succs)}/{len(var_succs)} ({100*np.mean(var_succs):.1f}%)")

    # Win/Tie/Loss
    wins = sum(1 for d in diffs if d > 0.01)
    ties = sum(1 for d in diffs if abs(d) <= 0.01)
    losses = sum(1 for d in diffs if d < -0.01)
    print(f"    Win/Tie/Loss: {wins}/{ties}/{losses}")

    print(f"\n  STATISTICAL TESTS:")

    # 1. Paired t-test
    if len(diffs) >= 5:
        t_stat, t_pval = stats.ttest_1samp(diffs, 0, alternative='greater')
        print(f"    Paired t-test (one-sided): t={t_stat:.3f}, p={t_pval:.4f}")

    # 2. Wilcoxon signed-rank (non-parametric paired)
    non_zero_diffs = [d for d in diffs if abs(d) > 0.001]
    if len(non_zero_diffs) >= 5:
        w_stat, w_pval = stats.wilcoxon(
            [v for v, d in zip(var_comps, diffs) if abs(d) > 0.001],
            [c for c, d in zip(ctrl_comps, diffs) if abs(d) > 0.001],
            alternative='greater',
        )
        print(f"    Wilcoxon signed-rank (one-sided): W={w_stat:.0f}, p={w_pval:.4f}")

    # 3. McNemar test for success rates (paired binary)
    # Concordant: both succeed or both fail
    # Discordant: one succeeds, other fails
    b = sum(1 for c, v in zip(ctrl_succs, var_succs) if c == 1 and v == 0)  # ctrl wins
    c_disc = sum(1 for c, v in zip(ctrl_succs, var_succs) if c == 0 and v == 1)  # var wins
    if b + c_disc > 0:
        # McNemar exact (binomial test)
        mcnemar_p = stats.binomtest(c_disc, b + c_disc, 0.5, alternative='greater').pvalue
        print(f"    McNemar (success, one-sided): discordant={c_disc} var_wins vs {b} ctrl_wins, p={mcnemar_p:.4f}")

    # 4. Bootstrap CI for mean paired difference
    np.random.seed(42)
    boot_diffs = []
    for _ in range(10000):
        idx = np.random.choice(len(diffs), size=len(diffs), replace=True)
        boot_diffs.append(np.mean([diffs[i] for i in idx]))
    ci_lo, ci_hi = np.percentile(boot_diffs, [2.5, 97.5])
    print(f"    Bootstrap 95% CI for mean diff: [{ci_lo:.3f}, {ci_hi:.3f}]")

    # 5. Cohen's dz (paired effect size)
    if np.std(diffs) > 0:
        dz = np.mean(diffs) / np.std(diffs)
        print(f"    Cohen's dz (paired): {dz:.3f}")

    # Per-agent breakdown
    print(f"\n  PER-AGENT BREAKDOWN:")
    agent_pairs = {}
    for p in pairs:
        ag = p["agent"]
        if ag not in agent_pairs:
            agent_pairs[ag] = []
        agent_pairs[ag].append(p["diff"])
    for ag, ag_diffs in sorted(agent_pairs.items()):
        print(f"    {ag:8s}: n={len(ag_diffs)}, mean_diff={np.mean(ag_diffs):+.3f}, "
              f"W/T/L={sum(1 for d in ag_diffs if d>0.01)}/{sum(1 for d in ag_diffs if abs(d)<=0.01)}/{sum(1 for d in ag_diffs if d<-0.01)}")

    # Raw pair data for review
    print(f"\n  RAW PAIR DATA:")
    print(f"  {'Task':<45s} {'Agent':<8s} {'Ctrl':>6s} {'Var':>6s} {'Diff':>7s} {'C_OK':>4s} {'V_OK':>4s}")
    print(f"  {'-'*45} {'-'*8} {'-'*6} {'-'*6} {'-'*7} {'-'*4} {'-'*4}")
    for p in pairs:
        print(f"  {p['task'][:45]:<45s} {p['agent']:<8s} "
              f"{p['control']['composite']:6.3f} {p['variant']['composite']:6.3f} "
              f"{p['diff']:+7.3f} "
              f"{'Y' if p['ctrl_success'] else 'N':>4s} "
              f"{'Y' if p['var_success'] else 'N':>4s}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A/B Paired Within-Subject Experiment")
    parser.add_argument("--max-pairs", type=int, default=26, help="Max task pairs to run")
    parser.add_argument("--agent", default="", help="Fix to single agent (e.g., codex). Default: round-robin")
    args = parser.parse_args()

    asyncio.run(main(
        max_pairs=args.max_pairs,
        fixed_agent=args.agent,
    ))
