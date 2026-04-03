#!/usr/bin/env python3
"""SkyDate KB A/B Test — measures domain knowledge injection effect on SWE code generation.

Orchestrates 'cam enhance' on the SkyDate repo in attended mode with knowledge ablation.
50/50 blind routing assigns each task to control (no KB) or variant (full KB).
Human approves each task execution via attended mode.

Usage:
    python scripts/run_skydate_ab.py preflight          # Check prerequisites
    python scripts/run_skydate_ab.py dry-run             # Preview planned tasks
    python scripts/run_skydate_ab.py execute             # Run full experiment (attended)
    python scripts/run_skydate_ab.py analyze             # Analyze results
    python scripts/run_skydate_ab.py report              # Generate showpiece document
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SKYDATE_REPO = "/Volumes/WS4TB/a_aSatzClaw/skydate"
CAM_ROOT = Path(__file__).resolve().parent.parent
CAM_BIN = "cam"  # Assumes cam is on PATH


def run_cmd(cmd: list[str], check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return result."""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        cwd=str(CAM_ROOT),
    )
    if check and result.returncode != 0:
        print(f"  ERROR: {result.stderr[:500] if result.stderr else 'unknown'}")
    return result


def preflight() -> bool:
    """Check all prerequisites for the experiment."""
    print("=" * 60)
    print("PREFLIGHT CHECKS")
    print("=" * 60)

    checks_passed = True

    # 1. SkyDate repo exists
    skydate_path = Path(SKYDATE_REPO)
    if skydate_path.exists():
        print(f"  [PASS] SkyDate repo exists: {SKYDATE_REPO}")
    else:
        print(f"  [FAIL] SkyDate repo not found: {SKYDATE_REPO}")
        checks_passed = False

    # 2. CAM binary available
    result = run_cmd([CAM_BIN, "--version"], check=False)
    if result.returncode == 0:
        print(f"  [PASS] CAM binary available: {result.stdout.strip()}")
    else:
        print(f"  [FAIL] CAM binary not available")
        checks_passed = False

    # 3. SkyDate KB exists
    kb_path = CAM_ROOT / "knowledge" / "skydate_kb.md"
    if kb_path.exists():
        print(f"  [PASS] SkyDate KB exists ({kb_path.stat().st_size} bytes)")
    else:
        print(f"  [FAIL] SkyDate KB not found: {kb_path}")
        checks_passed = False

    # 4. Check git status of SkyDate (should be clean or manageable)
    result = run_cmd(["git", "-C", SKYDATE_REPO, "status", "--porcelain"], check=False)
    if result.returncode == 0:
        dirty_count = len([l for l in result.stdout.strip().split("\n") if l.strip()]) if result.stdout.strip() else 0
        if dirty_count == 0:
            print(f"  [PASS] SkyDate git status: clean")
        else:
            print(f"  [WARN] SkyDate has {dirty_count} uncommitted changes")

    # 5. CAM DB initialized
    result = run_cmd([CAM_BIN, "status"], check=False)
    if result.returncode == 0:
        print(f"  [PASS] CAM status OK")
    else:
        print(f"  [WARN] CAM status check returned non-zero")

    print()
    if checks_passed:
        print("  All critical checks passed. Ready to proceed.")
    else:
        print("  Some checks FAILED. Fix issues before proceeding.")

    return checks_passed


def mine_kb() -> bool:
    """Mine the SkyDate KB into CAM's methodology store."""
    print("\n" + "=" * 60)
    print("MINING SKYDATE KB")
    print("=" * 60)

    kb_dir = str(CAM_ROOT / "knowledge")

    # Mine knowledge
    result = run_cmd([CAM_BIN, "mine", kb_dir, "--focus", "skydate"], check=False)
    if result.returncode == 0:
        print(f"  [PASS] KB mined successfully")
        if result.stdout:
            print(f"  {result.stdout.strip()[:200]}")
    else:
        print(f"  [WARN] Mining returned non-zero: {result.stderr[:200] if result.stderr else ''}")

    # Rebuild CAG cache
    result = run_cmd([CAM_BIN, "cag", "rebuild"], check=False)
    if result.returncode == 0:
        print(f"  [PASS] CAG cache rebuilt")
    else:
        print(f"  [WARN] CAG rebuild returned non-zero: {result.stderr[:200] if result.stderr else ''}")

    return True


def schedule_ab_test() -> bool:
    """Schedule the knowledge ablation A/B test."""
    print("\n" + "=" * 60)
    print("SCHEDULING A/B TEST")
    print("=" * 60)

    result = run_cmd([CAM_BIN, "ab-test", "start"], check=False)
    if result.returncode == 0:
        print(f"  [PASS] A/B test scheduled")
        if result.stdout:
            print(f"  {result.stdout.strip()[:200]}")
    else:
        # May already be scheduled
        print(f"  [INFO] A/B test may already be active: {result.stderr[:200] if result.stderr else ''}")

    return True


def dry_run() -> None:
    """Preview planned tasks without executing."""
    print("\n" + "=" * 60)
    print("DRY RUN — Planned Tasks")
    print("=" * 60)

    result = run_cmd(
        [CAM_BIN, "enhance", SKYDATE_REPO, "--dry-run", "--max-tasks", "30"],
        check=False,
        capture=True,
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr[:500])

    print("\n  Review the tasks above.")
    response = input("  Proceed with execution? [y/n]: ").strip().lower()
    if response != "y":
        print("  Aborted by user.")
        sys.exit(0)


def execute() -> dict:
    """Execute the full experiment in attended mode.

    Calls 'cam enhance' with --mode attended which provides
    human approval gates after every single task.
    50/50 blind routing is handled by CAM's built-in ablation.
    """
    print("\n" + "=" * 60)
    print("EXECUTING EXPERIMENT (attended mode)")
    print("=" * 60)
    print("  Each task will prompt for human approval.")
    print("  Type 'y' to approve, 'n' to reject, 'q' to stop.\n")

    start_time = time.time()

    # Run cam enhance in attended mode (interactive — don't capture output)
    cmd = [
        CAM_BIN, "enhance", SKYDATE_REPO,
        "--mode", "attended",
        "--max-tasks", "40",
    ]
    print(f"  $ {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=str(CAM_ROOT))

    elapsed = time.time() - start_time

    print(f"\n  Experiment completed in {elapsed:.1f}s ({elapsed/60:.1f}m)")

    return {"elapsed_seconds": round(elapsed, 2), "returncode": result.returncode}


def analyze() -> dict:
    """Collect and analyze A/B test results."""
    print("\n" + "=" * 60)
    print("ANALYZING RESULTS")
    print("=" * 60)

    # Get A/B test status
    result = run_cmd([CAM_BIN, "ab-test", "status"], check=False)
    if result.stdout:
        print(f"\n  A/B Test Status:\n{result.stdout}")

    # Try to use the ABAnalyzer
    try:
        sys.path.insert(0, str(CAM_ROOT / "src"))
        from claw.evolution.ab_analyzer import ABAnalyzer
        from claw.db.engine import SQLiteEngine

        db_path = CAM_ROOT / "data" / "claw.db"
        if not db_path.exists():
            print(f"  [WARN] Database not found at {db_path}")
            return {}

        import asyncio

        async def _analyze():
            engine = SQLiteEngine(str(db_path))
            await engine.initialize()
            analyzer = ABAnalyzer(engine)
            # Fetch all project IDs from samples
            rows = await engine.fetch_all(
                "SELECT DISTINCT project_id FROM ab_quality_samples"
            )
            if not rows:
                print("  No quality samples found yet.")
                return {}

            project_id = rows[0]["project_id"]
            report = await analyzer.analyze(project_id)
            formatted = analyzer.format_report(report)
            print(formatted)

            # Save results
            out_path = CAM_ROOT / "data" / "skydate_ab_results.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as f:
                json.dump(report, f, indent=2, default=str)
            print(f"\n  Results saved to {out_path}")

            await engine.close()
            return report

        return asyncio.run(_analyze())
    except Exception as e:
        print(f"  [ERROR] Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return {}


def generate_report(results: dict) -> None:
    """Generate the showpiece document from results."""
    print("\n" + "=" * 60)
    print("GENERATING SHOWPIECE DOCUMENT")
    print("=" * 60)

    doc_path = CAM_ROOT / "docs" / "SKYDATE_KB_SHOWPIECE.md"

    if not results:
        print("  No results to generate report from.")
        print("  Run 'execute' first, then 'analyze', then 'report'.")
        return

    print(f"  Report will be generated at: {doc_path}")
    print("  (Report generation requires real experimental data)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SkyDate KB A/B Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "phase",
        choices=["preflight", "mine", "schedule", "dry-run", "execute", "analyze", "report", "full"],
        help="Phase to run",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("SKYDATE x CAM KB INJECTION A/B TEST")
    print("=" * 60)

    if args.phase == "preflight":
        preflight()

    elif args.phase == "mine":
        mine_kb()

    elif args.phase == "schedule":
        schedule_ab_test()

    elif args.phase == "dry-run":
        if not preflight():
            sys.exit(1)
        dry_run()

    elif args.phase == "execute":
        if not preflight():
            sys.exit(1)
        mine_kb()
        schedule_ab_test()
        execute()

    elif args.phase == "analyze":
        analyze()

    elif args.phase == "report":
        results = analyze()
        generate_report(results)

    elif args.phase == "full":
        # Full pipeline with human gates
        if not preflight():
            sys.exit(1)
        mine_kb()
        schedule_ab_test()
        dry_run()  # Human gate
        exec_result = execute()  # Human gate per task
        results = analyze()

        print("\n" + "=" * 60)
        print("HUMAN REVIEW")
        print("=" * 60)
        response = input("  Accept results? [y/n/rerun]: ").strip().lower()
        if response == "y":
            generate_report(results)
        elif response == "rerun":
            print("  Re-running experiment...")
            exec_result = execute()
            results = analyze()
            generate_report(results)
        else:
            print("  Results not accepted.")


if __name__ == "__main__":
    main()
