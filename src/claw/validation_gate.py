"""CAM Self-Enhancement Validation Gate.

Programmatic validation of an enhanced copy before swapping into production.
Called by the self-enhancement pipeline after an enhanced copy is produced.

Each gate returns a GateResult. The orchestrator runs gates in order (fast
to slow) and aborts on the first hard failure.

Usage:
    from claw.validation_gate import run_all_gates, ValidationConfig

    config = ValidationConfig(
        copy_dir=Path("/tmp/cam-self-enhance"),
        live_dir=Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw"),
        baseline_test_count=1966,
    )
    report = await run_all_gates(config)
    if report.passed:
        # safe to swap
    else:
        # report.failed_gate, report.error_detail
"""

from __future__ import annotations

import ast
import asyncio
import difflib
import importlib
import json
import logging
import os
import pkgutil
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("claw.validation_gate")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ValidationConfig:
    """Configuration for the validation run."""
    copy_dir: Path
    live_dir: Path = field(default_factory=lambda: Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw"))
    baseline_test_count: int = 1966
    allowed_new_failures: int = 0
    skip_venv: bool = True  # default True for programmatic use (venv is slow)
    python_bin: str = sys.executable


@dataclass
class GateResult:
    """Result of a single validation gate."""
    gate_number: int
    gate_name: str
    passed: bool
    message: str
    detail: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class PytestSuiteResults:
    """Parsed pytest results."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    new_tests: int = 0

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total * 100) if self.total > 0 else 0.0


@dataclass
class DiffSummary:
    """Source diff between live and copy."""
    files_added: list[str] = field(default_factory=list)
    files_removed: list[str] = field(default_factory=list)
    files_modified: list[tuple[str, int, int]] = field(default_factory=list)
    files_unchanged: int = 0
    new_test_files: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Complete validation report."""
    passed: bool
    gate_results: list[GateResult] = field(default_factory=list)
    failed_gate: Optional[str] = None
    error_detail: Optional[str] = None
    test_results: Optional[PytestSuiteResults] = None
    diff_summary: Optional[DiffSummary] = None
    log_lines: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        for gr in self.gate_results:
            status = "PASS" if gr.passed else "FAIL"
            lines.append(f"Gate {gr.gate_number}: [{status}] {gr.gate_name} - {gr.message}")
            for w in gr.warnings:
                lines.append(f"  WARN: {w}")
        if self.test_results:
            tr = self.test_results
            lines.append(
                f"Tests: {tr.passed} passed, {tr.failed} failed, "
                f"{tr.errors} errors, {tr.skipped} skipped (total {tr.total})"
            )
        verdict = "ALL GATES PASSED" if self.passed else f"FAILED at {self.failed_gate}"
        lines.append(f"Verdict: {verdict}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gate implementations
# ---------------------------------------------------------------------------

def _gate_syntax_check(config: ValidationConfig) -> GateResult:
    """Gate 1: Verify all .py files parse without syntax errors."""
    src_dir = config.copy_dir / "src"
    failures = []
    count = 0

    for pyfile in src_dir.rglob("*.py"):
        count += 1
        try:
            source = pyfile.read_text(encoding="utf-8", errors="replace")
            ast.parse(source, filename=str(pyfile))
        except SyntaxError as e:
            failures.append(f"{pyfile.relative_to(config.copy_dir)}: {e}")

    if failures:
        return GateResult(
            gate_number=1,
            gate_name="Python Syntax Check",
            passed=False,
            message=f"{len(failures)} file(s) have syntax errors",
            detail="\n".join(failures),
        )

    return GateResult(
        gate_number=1,
        gate_name="Python Syntax Check",
        passed=True,
        message=f"All {count} .py files parse without syntax errors",
    )


def _gate_config_compatibility(config: ValidationConfig) -> GateResult:
    """Gate 2: Verify enhanced code can load claw.toml."""
    copy_toml = config.copy_dir / "claw.toml"
    live_toml = config.live_dir / "claw.toml"
    live_env = config.live_dir / ".env"
    copy_env = config.copy_dir / ".env"

    warnings = []

    # Ensure copy has a claw.toml
    if not copy_toml.exists():
        if live_toml.exists():
            shutil.copy2(live_toml, copy_toml)
            warnings.append("Copied claw.toml from live (was missing in copy)")
        else:
            return GateResult(
                gate_number=2,
                gate_name="Config Compatibility",
                passed=False,
                message="No claw.toml found in copy or live",
            )

    # Ensure copy has .env
    if not copy_env.exists() and live_env.exists():
        shutil.copy2(live_env, copy_env)
        warnings.append("Copied .env from live (was missing in copy)")

    # Run config loading in a subprocess to avoid polluting this process
    script = f"""
import sys, os
sys.path.insert(0, '{config.copy_dir / "src"}')
os.chdir('{config.copy_dir}')
from claw.core.config import load_config
from pathlib import Path
config = load_config(Path('{copy_toml}'))
assert hasattr(config, 'database'), 'Missing database config'
assert hasattr(config, 'llm'), 'Missing llm config'
assert hasattr(config, 'embeddings'), 'Missing embeddings config'
assert hasattr(config, 'orchestrator'), 'Missing orchestrator config'
assert hasattr(config, 'agents'), 'Missing agents config'
assert len(config.agents) >= 1, f'No agents configured: {{list(config.agents.keys())}}'
print(f'OK: {{len(config.agents)}} agents, db_path={{config.database.db_path}}')
"""
    result = subprocess.run(
        [config.python_bin, "-c", script],
        capture_output=True, text=True, timeout=30,
    )

    if result.returncode != 0:
        return GateResult(
            gate_number=2,
            gate_name="Config Compatibility",
            passed=False,
            message="Enhanced code cannot load claw.toml",
            detail=result.stderr + result.stdout,
            warnings=warnings,
        )

    return GateResult(
        gate_number=2,
        gate_name="Config Compatibility",
        passed=True,
        message=result.stdout.strip(),
        warnings=warnings,
    )


def _gate_import_smoke(config: ValidationConfig) -> GateResult:
    """Gate 3: Verify all claw.* modules import without error."""
    script = f"""
import importlib, pkgutil, sys, os, json

src_dir = '{config.copy_dir / "src"}'
sys.path.insert(0, src_dir)
for k in list(sys.modules):
    if k.startswith("claw"):
        del sys.modules[k]
os.chdir('{config.copy_dir}')

failures = []
count = 0

def import_recursive(package_name):
    global count
    try:
        mod = importlib.import_module(package_name)
        count += 1
    except Exception as e:
        failures.append((package_name, str(e)))
        return
    if hasattr(mod, "__path__"):
        for importer, modname, ispkg in pkgutil.walk_packages(
            mod.__path__, prefix=mod.__name__ + "."
        ):
            try:
                importlib.import_module(modname)
                count += 1
            except Exception as e:
                failures.append((modname, str(e)))

import_recursive("claw")
print(json.dumps({{"count": count, "failures": failures}}))
sys.exit(1 if failures else 0)
"""
    result = subprocess.run(
        [config.python_bin, "-c", script],
        capture_output=True, text=True, timeout=60,
    )

    try:
        data = json.loads(result.stdout.strip().split("\n")[-1])
    except (json.JSONDecodeError, IndexError):
        data = {"count": 0, "failures": [("parse_error", result.stdout + result.stderr)]}

    if result.returncode != 0 or data.get("failures"):
        fail_details = "\n".join(f"  {m}: {e}" for m, e in data.get("failures", []))
        return GateResult(
            gate_number=3,
            gate_name="Import Smoke Test",
            passed=False,
            message=f"{len(data.get('failures', []))} module(s) failed to import",
            detail=fail_details,
        )

    return GateResult(
        gate_number=3,
        gate_name="Import Smoke Test",
        passed=True,
        message=f"All {data['count']} modules imported successfully",
    )


async def _gate_db_compatibility(config: ValidationConfig) -> GateResult:
    """Gate 4: Verify enhanced code can open and query a copy of the live DB."""
    live_db = config.live_dir / "data" / "claw.db"
    if not live_db.exists():
        return GateResult(
            gate_number=4,
            gate_name="DB Schema Compatibility",
            passed=True,
            message="No live DB found — skipping (fresh install scenario)",
            warnings=["Live DB not found at expected path"],
        )

    # Copy DB to a temp location (never touch the live DB)
    db_test_dir = config.copy_dir / "_validation_db_test"
    db_test_dir.mkdir(exist_ok=True)
    db_copy = db_test_dir / "claw_readonly_copy.db"
    shutil.copy2(live_db, db_copy)
    # Copy WAL/SHM for consistent snapshot
    for suffix in ["-wal", "-shm"]:
        wal_file = live_db.parent / f"{live_db.name}{suffix}"
        if wal_file.exists():
            shutil.copy2(wal_file, db_test_dir / f"{db_copy.name}{suffix}")

    script = f"""
import asyncio, sys, os, json
sys.path.insert(0, '{config.copy_dir / "src"}')
for k in list(sys.modules):
    if k.startswith("claw"):
        del sys.modules[k]
os.chdir('{config.copy_dir}')

async def check():
    from claw.core.config import DatabaseConfig
    from claw.db.engine import DatabaseEngine
    from claw.db.repository import Repository

    engine = DatabaseEngine(DatabaseConfig(db_path='{db_copy}'))
    await engine.connect()

    tables = await engine.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [dict(r)["name"] for r in tables]

    expected = [
        "projects", "tasks", "hypothesis_log", "methodologies",
        "methodology_links", "token_costs", "agent_scores",
        "prompt_variants", "capability_boundaries", "fleet_repos",
        "episodes", "peer_reviews", "context_snapshots",
        "pulse_discoveries", "pulse_scan_log", "governance_log",
        "synergy_exploration_log", "action_templates",
        "methodology_usage_log",
    ]
    missing = [t for t in expected if t not in table_names]

    # Query each table
    table_counts = {{}}
    errors = []
    for tbl in expected:
        if tbl in table_names:
            try:
                rows = await engine.fetch_all(f"SELECT COUNT(*) as cnt FROM {{tbl}}")
                table_counts[tbl] = dict(rows[0])["cnt"]
            except Exception as e:
                errors.append(f"{{tbl}}: {{e}}")

    # Test repository layer
    repo_ok = False
    repo_err = ""
    try:
        repo = Repository(engine)
        projects = await repo.list_projects()
        repo_ok = True
    except Exception as e:
        repo_err = str(e)

    await engine.close()
    print(json.dumps({{
        "tables_found": len(table_names),
        "missing": missing,
        "table_counts": table_counts,
        "query_errors": errors,
        "repo_ok": repo_ok,
        "repo_err": repo_err,
    }}))
    sys.exit(1 if missing or errors or not repo_ok else 0)

asyncio.run(check())
"""
    result = subprocess.run(
        [config.python_bin, "-c", script],
        capture_output=True, text=True, timeout=60,
    )

    # Cleanup
    shutil.rmtree(db_test_dir, ignore_errors=True)

    try:
        data = json.loads(result.stdout.strip().split("\n")[-1])
    except (json.JSONDecodeError, IndexError):
        return GateResult(
            gate_number=4,
            gate_name="DB Schema Compatibility",
            passed=False,
            message="Failed to parse DB compatibility check output",
            detail=result.stdout + result.stderr,
        )

    issues = []
    if data.get("missing"):
        issues.append(f"Missing tables: {data['missing']}")
    if data.get("query_errors"):
        issues.append(f"Query errors: {data['query_errors']}")
    if not data.get("repo_ok"):
        issues.append(f"Repository layer error: {data.get('repo_err')}")

    if issues:
        return GateResult(
            gate_number=4,
            gate_name="DB Schema Compatibility",
            passed=False,
            message="DB compatibility issues found",
            detail="\n".join(issues),
        )

    total_rows = sum(data.get("table_counts", {}).values())
    return GateResult(
        gate_number=4,
        gate_name="DB Schema Compatibility",
        passed=True,
        message=f"{data['tables_found']} tables, {total_rows} total rows, repository layer OK",
    )


def _gate_cli_smoke(config: ValidationConfig) -> GateResult:
    """Gate 5: Verify CLI commands run without error."""
    script = f"""
import sys, os, json
sys.path.insert(0, '{config.copy_dir / "src"}')
for k in list(sys.modules):
    if k.startswith("claw"):
        del sys.modules[k]
os.chdir('{config.copy_dir}')

from typer.testing import CliRunner
from claw.cli import app

runner = CliRunner()
results = {{}}

# Test --help
r = runner.invoke(app, ["--help"])
results["help"] = {{"exit_code": r.exit_code, "output_len": len(r.output)}}

# Test status
r = runner.invoke(app, ["status"])
results["status"] = {{"exit_code": r.exit_code, "output_len": len(r.output)}}

# Test doctor status
r = runner.invoke(app, ["doctor", "status"])
results["doctor_status"] = {{"exit_code": r.exit_code, "output_len": len(r.output)}}

print(json.dumps(results))

# --help must work. status/doctor may fail if config path is wrong in test context.
if results["help"]["exit_code"] != 0:
    sys.exit(1)
sys.exit(0)
"""
    result = subprocess.run(
        [config.python_bin, "-c", script],
        capture_output=True, text=True, timeout=30,
    )

    try:
        data = json.loads(result.stdout.strip().split("\n")[-1])
    except (json.JSONDecodeError, IndexError):
        return GateResult(
            gate_number=5,
            gate_name="CLI Smoke Test",
            passed=False,
            message="Failed to parse CLI smoke test output",
            detail=result.stdout + result.stderr,
        )

    warnings = []
    for cmd in ["status", "doctor_status"]:
        if data.get(cmd, {}).get("exit_code", 1) != 0:
            warnings.append(f"cam {cmd.replace('_', ' ')}: exit_code={data[cmd]['exit_code']}")

    if data.get("help", {}).get("exit_code", 1) != 0:
        return GateResult(
            gate_number=5,
            gate_name="CLI Smoke Test",
            passed=False,
            message="cam --help failed",
            detail=result.stderr,
        )

    return GateResult(
        gate_number=5,
        gate_name="CLI Smoke Test",
        passed=True,
        message="cam --help runs, CLI entry point functional",
        warnings=warnings,
    )


def _gate_test_suite(config: ValidationConfig) -> tuple[GateResult, Optional[PytestSuiteResults]]:
    """Gate 6: Run full pytest suite against the enhanced copy."""
    pytest_xml = config.copy_dir / "_validation_pytest_results.xml"

    # Ensure .env is available
    live_env = config.live_dir / ".env"
    copy_env = config.copy_dir / ".env"
    if not copy_env.exists() and live_env.exists():
        shutil.copy2(live_env, copy_env)

    # Run pytest in subprocess with PYTHONPATH pointing to copy's source
    env = os.environ.copy()
    env["PYTHONPATH"] = str(config.copy_dir / "src")

    cmd = [
        config.python_bin, "-m", "pytest",
        str(config.copy_dir / "tests"),
        "--tb=short",
        f"--junitxml={pytest_xml}",
        "-v",
    ]

    result = subprocess.run(
        cmd,
        capture_output=True, text=True,
        timeout=600,  # 10 minute max for full suite
        cwd=str(config.copy_dir),
        env=env,
    )

    # Save stdout for inspection
    stdout_file = config.copy_dir / "_validation_pytest_stdout.txt"
    stdout_file.write_text(result.stdout + result.stderr, encoding="utf-8")

    if not pytest_xml.exists():
        return (
            GateResult(
                gate_number=6,
                gate_name="Full Test Suite",
                passed=False,
                message="pytest did not produce JUnit XML output",
                detail=result.stderr[-2000:] if result.stderr else "No stderr",
            ),
            None,
        )

    # Parse JUnit XML
    tree = ET.parse(str(pytest_xml))
    root = tree.getroot()
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]

    tr = PytestSuiteResults()
    for suite in suites:
        tr.total += int(suite.get("tests", 0))
        tr.failed += int(suite.get("failures", 0))
        tr.errors += int(suite.get("errors", 0))
        tr.skipped += int(suite.get("skipped", 0))
    tr.passed = tr.total - tr.failed - tr.errors - tr.skipped
    tr.new_tests = max(0, tr.total - config.baseline_test_count)

    warnings = []
    if tr.new_tests > 0:
        warnings.append(
            f"Enhanced copy added {tr.new_tests} new tests "
            f"(total: {tr.total}, baseline: {config.baseline_test_count})"
        )

    # Failure conditions
    if tr.failed > 0 or tr.errors > 0:
        # Extract failing test names from XML for diagnostics
        failing_tests = []
        for suite in suites:
            for tc in suite.findall("testcase"):
                if tc.find("failure") is not None or tc.find("error") is not None:
                    name = f"{tc.get('classname', '')}.{tc.get('name', '')}"
                    msg_elem = tc.find("failure") or tc.find("error")
                    msg = msg_elem.get("message", "")[:200] if msg_elem is not None else ""
                    failing_tests.append(f"{name}: {msg}")

        detail = "\n".join(failing_tests[:50])  # cap at 50 entries
        return (
            GateResult(
                gate_number=6,
                gate_name="Full Test Suite",
                passed=False,
                message=(
                    f"{tr.failed} failures + {tr.errors} errors out of {tr.total} tests. "
                    f"Zero regressions allowed."
                ),
                detail=detail,
                warnings=warnings,
            ),
            tr,
        )

    if tr.total < config.baseline_test_count:
        return (
            GateResult(
                gate_number=6,
                gate_name="Full Test Suite",
                passed=False,
                message=(
                    f"Test count DECREASED from {config.baseline_test_count} to {tr.total}. "
                    f"Tests may have been deleted."
                ),
                warnings=warnings,
            ),
            tr,
        )

    return (
        GateResult(
            gate_number=6,
            gate_name="Full Test Suite",
            passed=True,
            message=(
                f"{tr.passed} passed, {tr.skipped} skipped, "
                f"{tr.failed} failed, {tr.errors} errors (total: {tr.total})"
            ),
            warnings=warnings,
        ),
        tr,
    )


def _gate_diff_summary(config: ValidationConfig) -> tuple[GateResult, DiffSummary]:
    """Gate 7 (informational): Summarize source differences."""
    live_src = config.live_dir / "src" / "claw"
    copy_src = config.copy_dir / "src" / "claw"

    ds = DiffSummary()

    live_files = {p.relative_to(live_src) for p in live_src.rglob("*.py")}
    copy_files = {p.relative_to(copy_src) for p in copy_src.rglob("*.py")}

    ds.files_added = sorted(str(f) for f in (copy_files - live_files))
    ds.files_removed = sorted(str(f) for f in (live_files - copy_files))

    common = live_files & copy_files
    for f in sorted(common):
        live_content = (live_src / f).read_text(encoding="utf-8", errors="replace")
        copy_content = (copy_src / f).read_text(encoding="utf-8", errors="replace")
        if live_content != copy_content:
            diff = list(difflib.unified_diff(
                live_content.splitlines(),
                copy_content.splitlines(),
                lineterm="",
            ))
            additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
            deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
            ds.files_modified.append((str(f), additions, deletions))

    ds.files_unchanged = len(common) - len(ds.files_modified)

    # Check test files
    live_tests = config.live_dir / "tests"
    copy_tests = config.copy_dir / "tests"
    if live_tests.exists() and copy_tests.exists():
        live_test_files = {p.relative_to(live_tests) for p in live_tests.rglob("*.py")}
        copy_test_files = {p.relative_to(copy_tests) for p in copy_tests.rglob("*.py")}
        ds.new_test_files = sorted(str(f) for f in (copy_test_files - live_test_files))

    detail_lines = []
    if ds.files_added:
        detail_lines.append(f"Added ({len(ds.files_added)}):")
        for f in ds.files_added:
            detail_lines.append(f"  + {f}")
    if ds.files_removed:
        detail_lines.append(f"Removed ({len(ds.files_removed)}):")
        for f in ds.files_removed:
            detail_lines.append(f"  - {f}")
    if ds.files_modified:
        detail_lines.append(f"Modified ({len(ds.files_modified)}):")
        for f, a, d in ds.files_modified:
            detail_lines.append(f"  ~ {f} (+{a} -{d})")
    detail_lines.append(f"Unchanged: {ds.files_unchanged}")

    warnings = []
    if ds.files_removed:
        warnings.append(f"{len(ds.files_removed)} source file(s) were REMOVED")

    return (
        GateResult(
            gate_number=7,
            gate_name="Diff Summary",
            passed=True,  # informational only
            message=(
                f"{len(ds.files_modified)} modified, {len(ds.files_added)} added, "
                f"{len(ds.files_removed)} removed, {ds.files_unchanged} unchanged"
            ),
            detail="\n".join(detail_lines),
            warnings=warnings,
        ),
        ds,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def run_all_gates(config: ValidationConfig) -> ValidationReport:
    """Run all validation gates in order, abort on first failure.

    Returns a ValidationReport with full details.
    """
    report = ValidationReport(passed=False)

    # Validate copy directory structure
    for required in ["pyproject.toml", "src/claw", "tests"]:
        path = config.copy_dir / required
        if not path.exists():
            report.error_detail = f"Missing required path in copy: {path}"
            report.failed_gate = "Pre-flight"
            return report

    # Gate 1: Syntax check
    g1 = _gate_syntax_check(config)
    report.gate_results.append(g1)
    if not g1.passed:
        report.failed_gate = g1.gate_name
        report.error_detail = g1.detail
        return report

    # Gate 2: Config compatibility
    g2 = _gate_config_compatibility(config)
    report.gate_results.append(g2)
    if not g2.passed:
        report.failed_gate = g2.gate_name
        report.error_detail = g2.detail
        return report

    # Gate 3: Import smoke test
    g3 = _gate_import_smoke(config)
    report.gate_results.append(g3)
    if not g3.passed:
        report.failed_gate = g3.gate_name
        report.error_detail = g3.detail
        return report

    # Gate 4: DB schema compatibility
    g4 = await _gate_db_compatibility(config)
    report.gate_results.append(g4)
    if not g4.passed:
        report.failed_gate = g4.gate_name
        report.error_detail = g4.detail
        return report

    # Gate 5: CLI smoke test
    g5 = _gate_cli_smoke(config)
    report.gate_results.append(g5)
    if not g5.passed:
        report.failed_gate = g5.gate_name
        report.error_detail = g5.detail
        return report

    # Gate 6: Full test suite (slowest)
    g6, test_results = _gate_test_suite(config)
    report.gate_results.append(g6)
    report.test_results = test_results
    if not g6.passed:
        report.failed_gate = g6.gate_name
        report.error_detail = g6.detail
        return report

    # Gate 7: Diff summary (informational — always passes)
    g7, diff_summary = _gate_diff_summary(config)
    report.gate_results.append(g7)
    report.diff_summary = diff_summary

    report.passed = True
    return report


# ---------------------------------------------------------------------------
# CLI entry point (for testing the validator itself)
# ---------------------------------------------------------------------------

def main() -> None:
    """Run validation from command line."""
    import argparse

    parser = argparse.ArgumentParser(description="CAM Self-Enhancement Validation Gate")
    parser.add_argument("copy_dir", type=Path, help="Path to enhanced copy")
    parser.add_argument(
        "--live-dir", type=Path,
        default=Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw"),
        help="Path to live CAM installation",
    )
    parser.add_argument(
        "--baseline-tests", type=int, default=1966,
        help="Expected number of passing tests from live",
    )
    parser.add_argument(
        "--skip-venv", action="store_true",
        help="Skip isolated venv creation",
    )
    args = parser.parse_args()

    config = ValidationConfig(
        copy_dir=args.copy_dir.resolve(),
        live_dir=args.live_dir.resolve(),
        baseline_test_count=args.baseline_tests,
        skip_venv=args.skip_venv,
    )

    report = asyncio.run(run_all_gates(config))
    print(report.summary())

    if not report.passed:
        print(f"\nFAILED: {report.failed_gate}")
        if report.error_detail:
            print(f"Detail:\n{report.error_detail[:3000]}")
        sys.exit(1)
    else:
        print("\nAll gates passed. Safe to swap.")
        sys.exit(0)


if __name__ == "__main__":
    main()
