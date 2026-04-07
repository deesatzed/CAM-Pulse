#!/usr/bin/env python3
"""A/B Knowledge Ablation Experiment Runner.

Pre-seeds realistic SWE tasks across multiple repos, then runs MicroClaw
cycles to collect A/B quality samples. Each task gets randomly assigned
to control (knowledge suppressed) or variant (full KB) by cycle.py.

Usage:
    PYTHONPATH=src python scripts/run_ab_experiment.py [--max-tasks 40]
"""

import asyncio
import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claw.core.factory import ClawFactory
from claw.core.models import Project, Task, TaskStatus
from claw.cycle import MicroClaw

logger = logging.getLogger("ab_experiment")

# ---------------------------------------------------------------------------
# Task definitions — real SWE tasks targeting actual repos on disk
# ---------------------------------------------------------------------------

EXPERIMENT_TASKS = [
    # --- multiclaw tasks (Python, well-tested) ---
    {
        "title": "Add input validation to CAG compressor max_tokens parameter",
        "description": "The cag_compressor.py compress() method accepts max_tokens but does not validate it is positive. Add a guard that raises ValueError for non-positive values and a unit test.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add docstring to MiningModelSelector.get_eligible_agents",
        "description": "The get_eligible_agents() method in miner.py lacks a docstring. Add a clear docstring explaining the filtering logic (excludes local agents, respects context_window_tokens).",
        "task_type": "documentation",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add retry count logging to LLM client",
        "description": "In src/claw/llm/client.py, when a retry occurs after a transient error, log the retry attempt number and the error. Currently only the final success/failure is logged.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add type hints to dispatcher.py select_agent return value",
        "description": "The Dispatcher.select_agent method returns a tuple but lacks return type annotation. Add proper type hint: tuple[str, dict[str, float]].",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Extract magic numbers in budget enforcer to constants",
        "description": "In src/claw/budget.py, the default budget limits (5.0, 50.0, 100.0, 25.0) are hardcoded. Extract them to module-level constants with descriptive names.",
        "task_type": "refactoring",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add edge case test for empty methodology list in bandit",
        "description": "In tests/test_bandit.py, add a test case that verifies MethodologyBandit.select() handles an empty methodology list gracefully (returns None or empty list).",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Improve error message when OpenRouter returns 403",
        "description": "When OpenRouter returns HTTP 403, the current error message is generic. Improve it to suggest checking API key validity and credit balance.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add __repr__ to ClawConfig for debugging",
        "description": "The ClawConfig class in src/claw/core/config.py lacks a __repr__. Add one that shows key fields: db_path, agents count, evolution settings.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add connection timeout to Ollama health check",
        "description": "The Ollama health check in kv_cache_manager.py does not specify a connection timeout. Add a 5-second timeout to prevent hanging when Ollama is down.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add test for FTS5 query with special characters",
        "description": "Add a test in test_semantic_memory.py that verifies FTS5 search handles queries with special characters (parentheses, quotes, hyphens) without crashing.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    # --- mcp-troubleshooter tasks (Python) ---
    {
        "title": "Add logging to MCP troubleshooter connection handler",
        "description": "The connection handler in the MCP troubleshooter lacks structured logging for connection attempts and failures. Add INFO/ERROR level logging.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/mcp-troubleshooter",
    },
    {
        "title": "Add input sanitization for MCP tool arguments",
        "description": "MCP tool dispatch does not sanitize incoming arguments. Add basic validation to prevent injection via tool arguments.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/mcp-troubleshooter",
    },
    # --- dram-quest tasks (TypeScript/Next.js) ---
    {
        "title": "Add loading state to recommendation component",
        "description": "The whiskey recommendation component does not show a loading indicator while the API call is in progress. Add a loading spinner using existing UI primitives.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/dram-quest",
    },
    {
        "title": "Add error boundary to recommendation page",
        "description": "The recommendation page lacks an error boundary. Add a React error boundary component that displays a user-friendly error message instead of crashing.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/dram-quest",
    },
    {
        "title": "Add type safety to API response parsing",
        "description": "The API response from the recommendation endpoint is parsed with 'as any'. Add proper TypeScript interfaces and runtime validation using zod or manual checks.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/dram-quest",
    },
    # --- More multiclaw tasks to reach 40+ ---
    {
        "title": "Add graceful shutdown handler to dashboard server",
        "description": "The dashboard server in src/claw/web/dashboard_server.py does not handle SIGTERM gracefully. Add a signal handler that closes DB connections before exiting.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add rate limiting to MCP server tool dispatch",
        "description": "The ClawMCPServer.dispatch_tool() has no rate limiting. Add a simple token bucket rate limiter (10 calls per second) to prevent abuse.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add cache invalidation timestamp to CAG retriever",
        "description": "The CAG retriever caches methodologies but has no staleness check. Add a last_refreshed timestamp and a method to check if the cache is older than 1 hour.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Improve Thompson sampling prior in methodology bandit",
        "description": "The methodology bandit uses Beta(1,1) uniform prior. Consider using an informative prior based on methodology lifecycle_state (e.g., thriving methods get Beta(3,1)).",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add composite score breakdown to hypothesis log",
        "description": "The hypothesis log entry in cycle.py records error_signature but not the 6 quality dimension scores. Add these to the error_full field as JSON for post-hoc analysis.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add test for Kelly sizer edge case with zero wins",
        "description": "Add a test that verifies KellySizer handles an agent with zero wins and zero attempts gracefully (should return minimum bet, not divide by zero).",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add max retries configuration to OpenRouter client",
        "description": "The OpenRouter client hardcodes max_retries=3. Make this configurable via claw.toml under [agents.openrouter] section.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add memory usage logging to factory startup",
        "description": "During ClawFactory.create(), log the process memory usage at key points (after DB init, after CAG load, after KV cache). Use tracemalloc or psutil.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add validation for embedding dimension mismatch",
        "description": "When inserting embeddings via sqlite-vec, there is no check that the vector dimension matches the table's configured dimension (384). Add a validation check.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add configurable relevance threshold to semantic memory",
        "description": "The semantic memory search uses a hardcoded relevance threshold of 0.3. Make this configurable via claw.toml [memory] section.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add test for concurrent DB writes in repository",
        "description": "Add a test that verifies the repository handles concurrent task creation without SQLite locking errors. Use asyncio.gather to simulate 10 parallel inserts.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add cleanup of expired tasks in governance sweep",
        "description": "The governance sweep does not clean up tasks stuck in EVALUATING/DISPATCHED status for more than 1 hour. Add a cleanup step that resets them to PENDING.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add JSON schema validation for claw.toml configuration",
        "description": "The claw.toml parser does not validate the configuration schema. Add pydantic model validation that catches typos in section names and invalid field types.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add agent performance summary to enhance output",
        "description": "After cam enhance completes, display a per-agent performance table showing: tasks assigned, success rate, average duration, total tokens used.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add deduplication check before mining insertion",
        "description": "The miner inserts findings without checking for near-duplicates. Add a check that computes cosine similarity against existing methodologies and skips if >0.95.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Fix potential None dereference in prompt evolver evaluate_test",
        "description": "In prompt_evolver.py evaluate_test(), if one variant has zero samples, the division for avg_quality raises. Add a guard for zero sample counts.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add environment variable override for database path",
        "description": "Allow setting CLAW_DB_PATH environment variable to override the db_path in claw.toml. Useful for testing and CI environments.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add test for pattern learner with empty task history",
        "description": "Add a test that verifies PatternLearner.detect_patterns() handles a project with zero completed tasks (should return empty patterns, not crash).",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add context window utilization metric to token tracker",
        "description": "The token tracker logs total tokens used but not what percentage of the model's context window was consumed. Add a utilization_pct field.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Improve seed pack discovery error handling",
        "description": "If the seed pack directory is missing or unreadable, the seeder logs a warning but does not explain what seed packs are. Improve the message with a brief explanation.",
        "task_type": "documentation",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add batch processing support to embedding generation",
        "description": "The Gemini embedding client sends one text at a time. Add batch support to send up to 20 texts per API call using batchEmbedContents.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add health check endpoint to dashboard server",
        "description": "The dashboard server lacks a /health endpoint. Add one that returns {status: ok, db: connected, uptime_seconds: N} for monitoring.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add test for degradation manager circuit breaker",
        "description": "Add a test that verifies the DegradationManager trips the circuit breaker after 3 consecutive failures for an agent and prevents further dispatches.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add git branch info to project metadata",
        "description": "When creating a project in cam enhance, capture the current git branch and HEAD commit SHA. Store them in the project metadata for traceability.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add log rotation configuration to logging_config",
        "description": "The logging_config.py sets up file handlers without rotation. Add RotatingFileHandler support with configurable max_bytes and backup_count.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
    {
        "title": "Add task dependency tracking to planner",
        "description": "The Planner generates tasks independently. Add a simple dependency field so tasks that logically depend on each other are ordered correctly.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/multiclaw",
    },
]


async def main(max_tasks: int = 40, project_id: str = "", skip_seed: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    print(f"\n{'='*60}")
    print("  A/B KNOWLEDGE ABLATION EXPERIMENT")
    print(f"  Tasks: {min(max_tasks, len(EXPERIMENT_TASKS))}")
    print(f"  Repos: multiclaw, mcp-troubleshooter, dram-quest")
    print(f"{'='*60}\n")

    # Use multiclaw as the workspace (where claw.toml lives)
    workspace = Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw")
    ctx = await ClawFactory.create(workspace_dir=workspace)

    try:
        if project_id:
            print(f"  Reusing project: {project_id}")
        else:
            # Create experiment project
            project = Project(
                name="ab-experiment-v2",
                repo_path=str(workspace),
            )
            await ctx.repository.create_project(project)
            project_id = project.id
            print(f"  Project: {project_id}")

        if not skip_seed:
            # Phase 1: Pre-seed tasks
            print(f"\n[Phase 1] Pre-seeding {min(max_tasks, len(EXPERIMENT_TASKS))} tasks...")
            tasks_to_seed = EXPERIMENT_TASKS[:max_tasks]
            for i, task_def in enumerate(tasks_to_seed):
                task = Task(
                    project_id=project_id,
                    title=task_def["title"],
                    description=task_def["description"],
                    task_type=task_def.get("task_type", "enhancement"),
                    status=TaskStatus.PENDING,
                    priority=8,
                )
                await ctx.repository.create_task(task)
                print(f"  [{i+1}/{len(tasks_to_seed)}] {task.title[:60]}")
        else:
            print(f"\n[Phase 1] Skipping seed (--skip-seed)")

        # Verify pre-seeded tasks
        engine = ctx.repository.engine
        row = await engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND status = 'PENDING'",
            [project_id],
        )
        pending = row["cnt"] if row else 0
        print(f"\n  Pre-seeded {pending} PENDING tasks")

        # Check A/B test status
        row = await engine.fetch_one(
            "SELECT variant_label, sample_count FROM prompt_variants WHERE prompt_name='knowledge_ablation' AND variant_label='control'",
        )
        if row:
            print(f"  A/B status: control samples={row['sample_count']}")
        row = await engine.fetch_one(
            "SELECT variant_label, sample_count FROM prompt_variants WHERE prompt_name='knowledge_ablation' AND variant_label='variant'",
        )
        if row:
            print(f"  A/B status: variant samples={row['sample_count']}")

        # Phase 2: Run MicroClaw cycles
        # Mark any tasks with too many prior attempts as DONE to prevent infinite retries
        MAX_TASK_ATTEMPTS = 3
        stuck = await engine.fetch_all(
            "SELECT id FROM tasks WHERE project_id = ? AND attempt_count >= ? AND status IN ('PENDING','EVALUATING','CODING','REVIEWING')",
            [project_id, MAX_TASK_ATTEMPTS],
        )
        for s in stuck:
            await engine.execute(
                "UPDATE tasks SET status = 'DONE' WHERE id = ?",
                [s["id"]],
            )
        if stuck:
            print(f"  Retired {len(stuck)} tasks with {MAX_TASK_ATTEMPTS}+ attempts")

        # Re-check pending count
        row = await engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND status = 'PENDING'",
            [project_id],
        )
        pending = row["cnt"] if row else 0
        print(f"\n[Phase 2] Running up to {pending} MicroClaw cycles...")
        micro = MicroClaw(ctx=ctx, project_id=project_id)

        completed = 0
        failed = 0
        skipped = 0
        seen_tasks: dict[str, int] = {}  # task_id -> attempt count in this session
        start_time = time.monotonic()

        for i in range(pending):
            task_num = i + 1
            print(f"\n  --- Cycle {task_num}/{pending} ---")

            try:
                result = await micro.run_cycle()

                # Track task-level attempts within this session
                task_id = getattr(result, 'task_id', None) or 'unknown'
                seen_tasks[task_id] = seen_tasks.get(task_id, 0) + 1

                if result.success:
                    completed += 1
                    dur = result.duration_seconds or 0
                    print(f"  [OK] Completed in {dur:.1f}s (task: {task_id[:8]})")
                else:
                    failed += 1
                    print(f"  [FAIL] {getattr(result.outcome, 'failure_reason', 'unknown')} (task: {task_id[:8]})")

                    # If this task has failed too many times in this session, mark it DONE
                    if seen_tasks[task_id] >= MAX_TASK_ATTEMPTS:
                        await engine.execute(
                            "UPDATE tasks SET status = 'DONE' WHERE id = ?",
                            [task_id],
                        )
                        print(f"  [RETIRED] Task {task_id[:8]} after {MAX_TASK_ATTEMPTS} failures")

                # Show A/B assignment
                label = getattr(micro, '_ablation_label', None)
                if label:
                    print(f"  [A/B] Assigned to: {label}")

            except Exception as e:
                failed += 1
                logger.error("Cycle %d failed: %s", task_num, e)
                print(f"  [ERROR] {e}")

            # Check if there are any PENDING tasks left
            row = await engine.fetch_one(
                "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND status = 'PENDING'",
                [project_id],
            )
            remaining = row["cnt"] if row else 0
            if remaining == 0:
                print(f"\n  No more PENDING tasks — stopping early at cycle {task_num}")
                break

            # Progress summary every 5 tasks
            if task_num % 5 == 0:
                elapsed = time.monotonic() - start_time
                rate = task_num / elapsed * 60 if elapsed > 0 else 0
                # Query current A/B counts
                rows = await engine.fetch_all(
                    "SELECT variant_label, COUNT(*) as n, ROUND(AVG(composite_score),4) as avg "
                    "FROM ab_quality_samples WHERE project_id = ? GROUP BY variant_label",
                    [project_id],
                )
                print(f"\n  === Progress: {task_num}/{pending} cycles, {rate:.1f}/min, {remaining} remaining ===")
                for r in rows:
                    print(f"      {r['variant_label']}: n={r['n']}, avg_composite={r['avg']}")

        # Phase 3: Final summary
        elapsed = time.monotonic() - start_time
        print(f"\n{'='*60}")
        print(f"  EXPERIMENT COMPLETE")
        print(f"  Duration: {elapsed/60:.1f} minutes")
        print(f"  Completed: {completed}, Failed: {failed}")
        print(f"{'='*60}")

        # Final A/B counts
        rows = await engine.fetch_all(
            "SELECT variant_label, COUNT(*) as n, "
            "ROUND(AVG(composite_score),4) as avg_composite, "
            "ROUND(AVG(d_functional_correctness),4) as avg_fc, "
            "ROUND(AVG(d_intent_alignment),4) as avg_ia "
            "FROM ab_quality_samples WHERE project_id = ? GROUP BY variant_label",
            [project_id],
        )
        print(f"\n  A/B Quality Samples:")
        for r in rows:
            print(f"    {r['variant_label']}: n={r['n']}, "
                  f"composite={r['avg_composite']}, "
                  f"func_correct={r['avg_fc']}, "
                  f"intent_align={r['avg_ia']}")

        # All-time A/B counts
        rows = await engine.fetch_all(
            "SELECT variant_label, COUNT(*) as n, ROUND(AVG(composite_score),4) as avg "
            "FROM ab_quality_samples GROUP BY variant_label",
        )
        print(f"\n  All-time A/B totals:")
        for r in rows:
            print(f"    {r['variant_label']}: n={r['n']}, avg_composite={r['avg']}")

    finally:
        await ctx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A/B Knowledge Ablation Experiment")
    parser.add_argument("--max-tasks", type=int, default=40, help="Maximum tasks to run")
    parser.add_argument("--project-id", type=str, default="", help="Reuse existing project ID")
    parser.add_argument("--skip-seed", action="store_true", help="Skip task pre-seeding")
    args = parser.parse_args()
    asyncio.run(main(max_tasks=args.max_tasks, project_id=args.project_id, skip_seed=args.skip_seed))
