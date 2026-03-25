#!/usr/bin/env bash
# =============================================================================
# CAM Self-Enhancement Validation Gate Script
# =============================================================================
#
# Purpose: Verify an enhanced copy of CAM at $COPY_DIR before swapping it
#          into the live location at $LIVE_DIR.
#
# Usage:
#   ./scripts/validate_enhanced_copy.sh /tmp/cam-self-enhance
#
# Exit codes:
#   0 = all gates passed
#   1 = gate failure (DO NOT SWAP)
#   2 = usage error
#
# The script runs gates in order from fastest to slowest. It stops at the
# first failure. No gate modifies the live DB or live source.
# =============================================================================

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
LIVE_DIR="/Volumes/WS4TB/a_aSatzClaw/multiclaw"
LIVE_DB="${LIVE_DIR}/data/claw.db"
LIVE_CONFIG="${LIVE_DIR}/claw.toml"
LIVE_ENV="${LIVE_DIR}/.env"
BASELINE_TEST_COUNT=1966          # known passing test count from live
ALLOWED_NEW_FAILURES=0            # zero tolerance for regressions
MIN_PASS_RATE=100                 # percentage — we want 100% pass rate on existing tests
PYTHON_BIN="${PYTHON_BIN:-python}"

# ── Argument Parsing ─────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "USAGE: $0 <copy-dir> [--skip-venv]"
    echo ""
    echo "  <copy-dir>    Path to the enhanced copy (e.g. /tmp/cam-self-enhance)"
    echo "  --skip-venv   Reuse current environment instead of creating an isolated venv"
    exit 2
fi

COPY_DIR="$(cd "$1" && pwd)"
SKIP_VENV=false
if [[ "${2:-}" == "--skip-venv" ]]; then
    SKIP_VENV=true
fi

# ── Logging Helpers ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

GATE_NUM=0
TOTAL_GATES=8
LOG_FILE="${COPY_DIR}/validation_gate.log"

gate_start() {
    GATE_NUM=$((GATE_NUM + 1))
    echo ""
    echo -e "${CYAN}=== GATE ${GATE_NUM}/${TOTAL_GATES}: $1 ===${NC}"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] GATE ${GATE_NUM}: $1" >> "${LOG_FILE}"
}

gate_pass() {
    echo -e "${GREEN}  PASS: $1${NC}"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]   PASS: $1" >> "${LOG_FILE}"
}

gate_fail() {
    echo -e "${RED}  FAIL: $1${NC}"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]   FAIL: $1" >> "${LOG_FILE}"
    echo ""
    echo -e "${RED}VALIDATION FAILED at Gate ${GATE_NUM}. DO NOT SWAP.${NC}"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] VALIDATION FAILED at Gate ${GATE_NUM}" >> "${LOG_FILE}"
    exit 1
}

gate_warn() {
    echo -e "${YELLOW}  WARN: $1${NC}"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]   WARN: $1" >> "${LOG_FILE}"
}

# ── Pre-flight ───────────────────────────────────────────────────────────────
echo "============================================================"
echo "  CAM Enhanced Copy Validation"
echo "============================================================"
echo "  Live dir:    ${LIVE_DIR}"
echo "  Copy dir:    ${COPY_DIR}"
echo "  Live DB:     ${LIVE_DB}"
echo "  Baseline tests: ${BASELINE_TEST_COUNT}"
echo "  Log file:    ${LOG_FILE}"
echo "============================================================"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Validation started" > "${LOG_FILE}"
echo "  COPY_DIR=${COPY_DIR}" >> "${LOG_FILE}"
echo "  LIVE_DIR=${LIVE_DIR}" >> "${LOG_FILE}"

# Verify the copy directory has the expected structure
if [[ ! -f "${COPY_DIR}/pyproject.toml" ]]; then
    echo -e "${RED}ERROR: ${COPY_DIR}/pyproject.toml not found. Is this a CAM copy?${NC}"
    exit 2
fi
if [[ ! -d "${COPY_DIR}/src/claw" ]]; then
    echo -e "${RED}ERROR: ${COPY_DIR}/src/claw/ not found. Missing source package.${NC}"
    exit 2
fi
if [[ ! -d "${COPY_DIR}/tests" ]]; then
    echo -e "${RED}ERROR: ${COPY_DIR}/tests/ not found. Missing test directory.${NC}"
    exit 2
fi

# =============================================================================
# GATE 1: Syntax Check (fastest — pure static, no imports)
# =============================================================================
gate_start "Python Syntax Check"

SYNTAX_ERRORS=0
while IFS= read -r pyfile; do
    if ! "${PYTHON_BIN}" -c "
import ast, sys
try:
    ast.parse(open('${pyfile}', 'r').read())
except SyntaxError as e:
    print(f'SYNTAX ERROR in ${pyfile}: {e}', file=sys.stderr)
    sys.exit(1)
" 2>>"${LOG_FILE}"; then
        gate_warn "Syntax error in: ${pyfile}"
        SYNTAX_ERRORS=$((SYNTAX_ERRORS + 1))
    fi
done < <(find "${COPY_DIR}/src" -name "*.py" -type f)

if [[ ${SYNTAX_ERRORS} -gt 0 ]]; then
    gate_fail "${SYNTAX_ERRORS} file(s) have syntax errors"
fi
gate_pass "All .py files in src/ parse without syntax errors"

# =============================================================================
# GATE 2: Config Compatibility
# =============================================================================
gate_start "Config Compatibility"

# The copy needs its own claw.toml for testing. Use the live one.
if [[ ! -f "${COPY_DIR}/claw.toml" ]]; then
    gate_warn "No claw.toml in copy — linking from live"
    cp "${LIVE_CONFIG}" "${COPY_DIR}/claw.toml"
fi

# Also copy .env if present (needed for API key loading)
if [[ -f "${LIVE_ENV}" ]] && [[ ! -f "${COPY_DIR}/.env" ]]; then
    cp "${LIVE_ENV}" "${COPY_DIR}/.env"
fi

# Test that load_config works with the copy's source
PYTHONPATH="${COPY_DIR}/src" "${PYTHON_BIN}" -c "
import sys, os
os.chdir('${COPY_DIR}')
from claw.core.config import load_config
from pathlib import Path
config = load_config(Path('${COPY_DIR}/claw.toml'))
# Validate critical config sections exist
assert hasattr(config, 'database'), 'Missing database config'
assert hasattr(config, 'llm'), 'Missing llm config'
assert hasattr(config, 'embeddings'), 'Missing embeddings config'
assert hasattr(config, 'orchestrator'), 'Missing orchestrator config'
assert hasattr(config, 'agents'), 'Missing agents config'
assert len(config.agents) >= 1, 'No agents configured'
print(f'Config loaded: {len(config.agents)} agents, db_path={config.database.db_path}')
" 2>>"${LOG_FILE}" || gate_fail "Enhanced code cannot load claw.toml"

gate_pass "claw.toml loads correctly with enhanced code"

# =============================================================================
# GATE 3: Import Smoke Test (all modules importable)
# =============================================================================
gate_start "Import Smoke Test"

# Build list of all Python modules in the copy's source tree
IMPORT_SCRIPT=$(cat <<'PYEOF'
import importlib
import pkgutil
import sys
import os

src_dir = sys.argv[1]
sys.path.insert(0, src_dir)

# Remove any cached claw imports from the live install
to_remove = [k for k in sys.modules if k.startswith("claw")]
for k in to_remove:
    del sys.modules[k]

os.chdir(os.path.dirname(src_dir))  # cd to copy root

failures = []
count = 0

def import_recursive(package_name, package_path):
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

import_recursive("claw", os.path.join(src_dir, "claw"))

if failures:
    print(f"IMPORT FAILURES ({len(failures)}/{count + len(failures)}):")
    for mod_name, err in failures:
        print(f"  {mod_name}: {err}")
    sys.exit(1)
else:
    print(f"All {count} modules imported successfully")
PYEOF
)

"${PYTHON_BIN}" -c "${IMPORT_SCRIPT}" "${COPY_DIR}/src" 2>>"${LOG_FILE}" \
    || gate_fail "One or more modules failed to import"

gate_pass "All claw.* modules import without error"

# =============================================================================
# GATE 4: DB Schema Compatibility (read-only against a COPY of the live DB)
# =============================================================================
gate_start "DB Schema Compatibility"

# CRITICAL: Never touch the live DB. Make a read-only copy.
DB_TEST_DIR="${COPY_DIR}/_validation_db_test"
mkdir -p "${DB_TEST_DIR}"
cp "${LIVE_DB}" "${DB_TEST_DIR}/claw_readonly_copy.db"
# Also copy WAL/SHM if they exist (for consistent snapshot)
[[ -f "${LIVE_DB}-wal" ]] && cp "${LIVE_DB}-wal" "${DB_TEST_DIR}/claw_readonly_copy.db-wal"
[[ -f "${LIVE_DB}-shm" ]] && cp "${LIVE_DB}-shm" "${DB_TEST_DIR}/claw_readonly_copy.db-shm"

DB_COMPAT_SCRIPT=$(cat <<'PYEOF'
import asyncio
import sys
import os

src_dir = sys.argv[1]
db_path = sys.argv[2]

sys.path.insert(0, src_dir)
# Purge cached claw modules
for k in list(sys.modules):
    if k.startswith("claw"):
        del sys.modules[k]

os.chdir(os.path.dirname(src_dir))

async def test_db_compat():
    from claw.core.config import DatabaseConfig
    from claw.db.engine import DatabaseEngine

    config = DatabaseConfig(db_path=db_path)
    engine = DatabaseEngine(config)
    await engine.connect()

    # Test 1: Can open and read all tables
    tables = await engine.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [dict(r)["name"] for r in tables]
    print(f"  Tables found: {len(table_names)}")

    expected_tables = [
        "projects", "tasks", "hypothesis_log", "methodologies",
        "methodology_links", "token_costs", "agent_scores",
        "prompt_variants", "capability_boundaries", "fleet_repos",
        "episodes", "peer_reviews", "context_snapshots",
        "pulse_discoveries", "pulse_scan_log", "governance_log",
        "synergy_exploration_log", "action_templates",
        "methodology_usage_log",
    ]
    missing = [t for t in expected_tables if t not in table_names]
    if missing:
        print(f"  MISSING TABLES: {missing}")
        sys.exit(1)

    # Test 2: Can query each critical table without error
    for tbl in expected_tables:
        try:
            rows = await engine.fetch_all(f"SELECT COUNT(*) as cnt FROM {tbl}")
            cnt = dict(rows[0])["cnt"]
            print(f"  {tbl}: {cnt} rows")
        except Exception as e:
            print(f"  ERROR querying {tbl}: {e}")
            sys.exit(1)

    # Test 3: Schema matches — check column names on critical tables
    for tbl in ["methodologies", "tasks", "projects"]:
        cols = await engine.fetch_all(f"PRAGMA table_info({tbl})")
        col_names = [dict(c)["name"] for c in cols]
        print(f"  {tbl} columns: {col_names}")

    # Test 4: Repository layer works
    from claw.db.repository import Repository
    repo = Repository(engine)
    # Attempt a read-only query via the repository layer
    try:
        projects = await repo.list_projects()
        print(f"  Repository.list_projects(): {len(projects)} projects")
    except Exception as e:
        print(f"  Repository layer error: {e}")
        sys.exit(1)

    await engine.close()
    print("  DB compatibility verified")

asyncio.run(test_db_compat())
PYEOF
)

PYTHONPATH="${COPY_DIR}/src" "${PYTHON_BIN}" -c "${DB_COMPAT_SCRIPT}" \
    "${COPY_DIR}/src" \
    "${DB_TEST_DIR}/claw_readonly_copy.db" \
    2>>"${LOG_FILE}" || gate_fail "Enhanced code cannot open/query the live DB schema"

# Clean up DB copy
rm -rf "${DB_TEST_DIR}"

gate_pass "Enhanced code reads live DB schema and queries all tables"

# =============================================================================
# GATE 5: CLI Smoke Test
# =============================================================================
gate_start "CLI Smoke Test"

# We must run the CLI from the copy's source. Since the copy is not pip-installed,
# we invoke the typer app directly via python -m or by importing it.

CLI_SMOKE_SCRIPT=$(cat <<'PYEOF'
import sys
import os

src_dir = sys.argv[1]
copy_dir = sys.argv[2]

sys.path.insert(0, src_dir)
for k in list(sys.modules):
    if k.startswith("claw"):
        del sys.modules[k]

os.chdir(copy_dir)

from typer.testing import CliRunner
from claw.cli import app

runner = CliRunner()

# Test 1: --help
result = runner.invoke(app, ["--help"])
if result.exit_code != 0:
    print(f"cam --help failed (exit {result.exit_code}): {result.output}")
    sys.exit(1)
print(f"  cam --help: exit_code=0, output_length={len(result.output)}")

# Test 2: status
result = runner.invoke(app, ["status"])
if result.exit_code != 0:
    print(f"cam status failed (exit {result.exit_code}): {result.output}")
    # status may fail if DB isn't at expected path — log but check carefully
    if "Config file not found" in result.output or "Config file not found" in str(result.exception):
        print("  (Expected: no claw.toml at default path in test context)")
    else:
        sys.exit(1)
else:
    print(f"  cam status: exit_code=0")

# Test 3: doctor status
result = runner.invoke(app, ["doctor", "status"])
if result.exit_code != 0:
    print(f"cam doctor status failed (exit {result.exit_code}): {result.output}")
    if "Config file not found" in str(result.exception or result.output):
        print("  (Expected: config path issue in test context)")
    else:
        sys.exit(1)
else:
    print(f"  cam doctor status: exit_code=0")

print("  CLI smoke tests passed")
PYEOF
)

PYTHONPATH="${COPY_DIR}/src" "${PYTHON_BIN}" -c "${CLI_SMOKE_SCRIPT}" \
    "${COPY_DIR}/src" \
    "${COPY_DIR}" \
    2>>"${LOG_FILE}" || gate_fail "CLI smoke tests failed"

gate_pass "cam --help, cam status, cam doctor status all run"

# =============================================================================
# GATE 6: Isolated venv + pip install test
# =============================================================================
gate_start "Package Install Test"

if [[ "${SKIP_VENV}" == "true" ]]; then
    gate_warn "Skipping isolated venv install (--skip-venv flag)"
    gate_pass "(skipped by user request)"
    PYTEST_PYTHON="${PYTHON_BIN}"
    PYTEST_PREFIX=""
else
    VENV_DIR="${COPY_DIR}/_validation_venv"
    # Clean up any leftover venv
    rm -rf "${VENV_DIR}"

    "${PYTHON_BIN}" -m venv "${VENV_DIR}" 2>>"${LOG_FILE}" \
        || gate_fail "Failed to create venv"

    # Install the copy in editable mode inside the isolated venv
    "${VENV_DIR}/bin/pip" install --quiet --upgrade pip 2>>"${LOG_FILE}"
    "${VENV_DIR}/bin/pip" install --quiet -e "${COPY_DIR}[dev]" 2>>"${LOG_FILE}" \
        || gate_fail "pip install -e .[dev] failed for enhanced copy"

    # Verify the installed package resolves to the copy
    INSTALLED_LOC=$("${VENV_DIR}/bin/python" -c "import claw; print(claw.__file__)" 2>&1)
    if [[ "${INSTALLED_LOC}" != *"${COPY_DIR}"* ]]; then
        gate_fail "Installed claw resolves to wrong location: ${INSTALLED_LOC}"
    fi

    gate_pass "pip install -e .[dev] succeeded in isolated venv"
    PYTEST_PYTHON="${VENV_DIR}/bin/python"
    PYTEST_PREFIX="${VENV_DIR}/bin/"
fi

# =============================================================================
# GATE 7: Full Test Suite
# =============================================================================
gate_start "Full Test Suite (pytest)"

# Copy test fixtures and data that tests might reference
# Tests use conftest.py which loads .env from project root
if [[ ! -f "${COPY_DIR}/.env" ]] && [[ -f "${LIVE_ENV}" ]]; then
    cp "${LIVE_ENV}" "${COPY_DIR}/.env"
fi

# Run pytest from within the copy directory, capturing results in JUnit XML
PYTEST_XML="${COPY_DIR}/_validation_pytest_results.xml"
PYTEST_STDOUT="${COPY_DIR}/_validation_pytest_stdout.txt"

# If we have an isolated venv, use it; otherwise use PYTHONPATH override
if [[ "${SKIP_VENV}" == "true" ]]; then
    PYTHONPATH="${COPY_DIR}/src" "${PYTHON_BIN}" -m pytest \
        "${COPY_DIR}/tests" \
        --tb=short \
        --junitxml="${PYTEST_XML}" \
        -v \
        2>&1 | tee "${PYTEST_STDOUT}" || true
else
    cd "${COPY_DIR}"
    "${PYTEST_PREFIX}pytest" \
        "${COPY_DIR}/tests" \
        --tb=short \
        --junitxml="${PYTEST_XML}" \
        -v \
        2>&1 | tee "${PYTEST_STDOUT}" || true
    cd "${LIVE_DIR}"
fi

# Parse pytest results from the JUnit XML
if [[ ! -f "${PYTEST_XML}" ]]; then
    gate_fail "pytest did not produce results XML"
fi

PARSE_RESULTS_SCRIPT=$(cat <<'PYEOF'
import xml.etree.ElementTree as ET
import sys
import json

xml_path = sys.argv[1]
baseline_count = int(sys.argv[2])

tree = ET.parse(xml_path)
root = tree.getroot()

# JUnit XML: <testsuite tests="N" errors="E" failures="F" skipped="S">
# or <testsuites><testsuite ...>
if root.tag == "testsuites":
    suites = root.findall("testsuite")
else:
    suites = [root]

total_tests = 0
total_failures = 0
total_errors = 0
total_skipped = 0

for suite in suites:
    total_tests += int(suite.get("tests", 0))
    total_failures += int(suite.get("failures", 0))
    total_errors += int(suite.get("errors", 0))
    total_skipped += int(suite.get("skipped", 0))

passed = total_tests - total_failures - total_errors - total_skipped
pass_rate = (passed / total_tests * 100) if total_tests > 0 else 0

results = {
    "total": total_tests,
    "passed": passed,
    "failed": total_failures,
    "errors": total_errors,
    "skipped": total_skipped,
    "pass_rate": round(pass_rate, 2),
    "baseline": baseline_count,
    "new_tests": max(0, total_tests - baseline_count),
    "regression_candidates": total_failures + total_errors,
}

print(json.dumps(results))

# Determine exit code
# Regressions: if tests that existed in baseline now fail
# We allow NEW tests to exist (test count can increase)
# We do NOT allow the passed count to drop below baseline (minus skipped)
if total_failures > 0 or total_errors > 0:
    sys.exit(1)
elif total_tests < baseline_count:
    # Tests were REMOVED — this is suspicious
    print(f"WARNING: Test count dropped from {baseline_count} to {total_tests}", file=sys.stderr)
    sys.exit(2)
else:
    sys.exit(0)
PYEOF
)

RESULTS_JSON=$("${PYTHON_BIN}" -c "${PARSE_RESULTS_SCRIPT}" "${PYTEST_XML}" "${BASELINE_TEST_COUNT}" 2>>"${LOG_FILE}") || true
PARSE_EXIT=$?

echo "  Test Results: ${RESULTS_JSON}"
echo "[$(date '+%Y-%m-%d %H:%M:%S')]   Test Results: ${RESULTS_JSON}" >> "${LOG_FILE}"

# Extract values from JSON for shell logic
TOTAL_TESTS=$(echo "${RESULTS_JSON}" | "${PYTHON_BIN}" -c "import sys,json; print(json.load(sys.stdin)['total'])")
PASSED=$(echo "${RESULTS_JSON}" | "${PYTHON_BIN}" -c "import sys,json; print(json.load(sys.stdin)['passed'])")
FAILED=$(echo "${RESULTS_JSON}" | "${PYTHON_BIN}" -c "import sys,json; print(json.load(sys.stdin)['failed'])")
ERRORS=$(echo "${RESULTS_JSON}" | "${PYTHON_BIN}" -c "import sys,json; print(json.load(sys.stdin)['errors'])")
SKIPPED=$(echo "${RESULTS_JSON}" | "${PYTHON_BIN}" -c "import sys,json; print(json.load(sys.stdin)['skipped'])")
NEW_TESTS=$(echo "${RESULTS_JSON}" | "${PYTHON_BIN}" -c "import sys,json; print(json.load(sys.stdin)['new_tests'])")

if [[ "${FAILED}" -gt 0 ]] || [[ "${ERRORS}" -gt 0 ]]; then
    gate_fail "${FAILED} failures + ${ERRORS} errors out of ${TOTAL_TESTS} tests. Zero regressions allowed."
fi

if [[ "${TOTAL_TESTS}" -lt "${BASELINE_TEST_COUNT}" ]]; then
    gate_fail "Test count DECREASED from ${BASELINE_TEST_COUNT} to ${TOTAL_TESTS}. Tests may have been deleted."
fi

if [[ "${NEW_TESTS}" -gt 0 ]]; then
    gate_warn "Enhanced copy added ${NEW_TESTS} new tests (total: ${TOTAL_TESTS}, baseline: ${BASELINE_TEST_COUNT}). This is acceptable."
fi

gate_pass "${PASSED} passed, ${SKIPPED} skipped, ${FAILED} failed, ${ERRORS} errors (total: ${TOTAL_TESTS})"

# =============================================================================
# GATE 8: Diff Summary (informational — not a pass/fail gate)
# =============================================================================
gate_start "Diff Summary"

DIFF_SCRIPT=$(cat <<'PYEOF'
import sys
import os
from pathlib import Path

live_src = Path(sys.argv[1]) / "src"
copy_src = Path(sys.argv[2]) / "src"

# Find all .py files in both trees
live_files = {p.relative_to(live_src) for p in live_src.rglob("*.py")}
copy_files = {p.relative_to(copy_src) for p in copy_src.rglob("*.py")}

added = copy_files - live_files
removed = live_files - copy_files
common = live_files & copy_files

modified = []
for f in sorted(common):
    live_content = (live_src / f).read_text(errors="replace")
    copy_content = (copy_src / f).read_text(errors="replace")
    if live_content != copy_content:
        # Count changed lines
        import difflib
        diff = list(difflib.unified_diff(
            live_content.splitlines(),
            copy_content.splitlines(),
            lineterm="",
        ))
        additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
        modified.append((str(f), additions, deletions))

print(f"  Files added:    {len(added)}")
for f in sorted(added):
    print(f"    + {f}")

print(f"  Files removed:  {len(removed)}")
for f in sorted(removed):
    print(f"    - {f}")

print(f"  Files modified: {len(modified)}")
for f, a, d in modified:
    print(f"    ~ {f} (+{a} -{d})")

print(f"  Files unchanged: {len(common) - len(modified)}")

# Also check test files
live_tests = Path(sys.argv[1]) / "tests"
copy_tests = Path(sys.argv[2]) / "tests"
live_test_files = {p.relative_to(live_tests) for p in live_tests.rglob("*.py")}
copy_test_files = {p.relative_to(copy_tests) for p in copy_tests.rglob("*.py")}
new_test_files = copy_test_files - live_test_files
if new_test_files:
    print(f"  New test files: {len(new_test_files)}")
    for f in sorted(new_test_files):
        print(f"    + tests/{f}")
PYEOF
)

"${PYTHON_BIN}" -c "${DIFF_SCRIPT}" "${LIVE_DIR}" "${COPY_DIR}" 2>>"${LOG_FILE}" || true

gate_pass "Diff summary generated (informational only)"

# =============================================================================
# FINAL VERDICT
# =============================================================================
echo ""
echo "============================================================"
echo -e "${GREEN}  ALL ${TOTAL_GATES} VALIDATION GATES PASSED${NC}"
echo "============================================================"
echo "  The enhanced copy at ${COPY_DIR} is safe to swap."
echo ""
echo "  Swap commands (run manually after review):"
echo ""
echo "    # 1. Back up the live source"
echo "    cp -a ${LIVE_DIR}/src/claw ${LIVE_DIR}/src/claw.bak.\$(date +%Y%m%d%H%M%S)"
echo ""
echo "    # 2. Copy enhanced source into live"
echo "    rsync -a --delete ${COPY_DIR}/src/claw/ ${LIVE_DIR}/src/claw/"
echo ""
echo "    # 3. Copy any new test files"
echo "    rsync -a ${COPY_DIR}/tests/ ${LIVE_DIR}/tests/"
echo ""
echo "    # 4. Verify the swap"
echo "    cd ${LIVE_DIR} && pytest tests/ --tb=short -q"
echo ""
echo "    # 5. If tests fail, rollback:"
echo "    # rsync -a --delete ${LIVE_DIR}/src/claw.bak.<timestamp>/ ${LIVE_DIR}/src/claw/"
echo ""
echo "  Full log: ${LOG_FILE}"
echo "  JUnit XML: ${PYTEST_XML}"
echo "  Stdout capture: ${PYTEST_STDOUT}"
echo "============================================================"

# Clean up venv if we created one
if [[ "${SKIP_VENV}" == "false" ]] && [[ -d "${COPY_DIR}/_validation_venv" ]]; then
    echo ""
    echo "  Cleanup: removing validation venv..."
    rm -rf "${COPY_DIR}/_validation_venv"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ALL GATES PASSED" >> "${LOG_FILE}"
exit 0
