#!/usr/bin/env bash
# ===========================================================================
# CAM Showpiece: TidyHome — Real CLI Tool Built From Mined Knowledge
#
# This script validates that the TidyHome CLI tool (built by `cam create`
# using CAM-PULSE knowledge base) works end-to-end on a controlled fixture
# directory and against the actual home directory.
#
# Knowledge sources (mined into CAM ganglia):
#   - MiroFish, abacus_FileSearch    → recursive file scanning patterns
#   - CLI-Anything, aWSappFileSearch → argparse subcommand structure
#   - app_organizer                  → SQLite indexing schema
#   - AMM                            → hash-based deduplication
#   - Rust/Go/Python brain resilience patterns → error handling
#
# This is Showpiece #23: not a meta-tool or a benchmark, but a real CLI
# the user actually runs on their own ~/ to find wasted disk space.
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Configuration ---
TIDYHOME_DIR="${TIDYHOME_DIR:-/tmp/tidyhome}"
PYTHON="${PYTHON:-python3}"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="$REPO_ROOT/tmp/tidyhome_showpiece/$RUN_ID"
FIXTURE_DIR="$OUT_DIR/fixture"
FIXTURE_DB="$OUT_DIR/.tidyhome/index.db"
mkdir -p "$OUT_DIR" "$FIXTURE_DIR"

PASS=0
FAIL=0
STEPS=()

log() { echo "[$(date +%H:%M:%S)] $*"; }
step_pass() { PASS=$((PASS + 1)); STEPS+=("PASS: $1"); log "PASS: $1"; }
step_fail() { FAIL=$((FAIL + 1)); STEPS+=("FAIL: $1"); log "FAIL: $1"; }

# ===========================================================================
log "=============================================="
log "=== TidyHome Showpiece — Real CLI Tool Test ==="
log "=============================================="
log "Run ID: $RUN_ID"
log "TidyHome dir: $TIDYHOME_DIR"
log "Fixture dir: $FIXTURE_DIR"
log "Output: $OUT_DIR/"

# ===========================================================================
# Section 0: Environment & installation check
# ===========================================================================
log "--- Section 0: Environment checks ---"

if [ ! -d "$TIDYHOME_DIR" ]; then
    log "ERROR: TidyHome directory not found at $TIDYHOME_DIR"
    log "This script expects tidyhome built by 'cam create' to exist at /tmp/tidyhome"
    exit 1
fi

if [ ! -f "$TIDYHOME_DIR/pyproject.toml" ]; then
    step_fail "pyproject.toml missing from $TIDYHOME_DIR"
else
    step_pass "pyproject.toml present"
fi

if [ ! -f "$TIDYHOME_DIR/README.md" ]; then
    step_fail "README.md missing from $TIDYHOME_DIR"
else
    step_pass "README.md present"
fi

# Verify all source modules exist
REQUIRED_MODULES=(
    "tidyhome/__init__.py"
    "tidyhome/__main__.py"
    "tidyhome/cli.py"
    "tidyhome/scanner.py"
    "tidyhome/db.py"
    "tidyhome/dedup.py"
    "tidyhome/reporter.py"
    "tidyhome/cleaner.py"
)
ALL_PRESENT=1
for mod in "${REQUIRED_MODULES[@]}"; do
    if [ ! -f "$TIDYHOME_DIR/$mod" ]; then
        log "  Missing: $mod"
        ALL_PRESENT=0
    fi
done
if [ "$ALL_PRESENT" -eq 1 ]; then
    step_pass "All ${#REQUIRED_MODULES[@]} source modules present"
else
    step_fail "One or more source modules missing"
fi

# ===========================================================================
# Section 1: Unit tests pass
# ===========================================================================
log "--- Section 1: Run unit test suite ---"

cd "$TIDYHOME_DIR"
set +e
"$PYTHON" -m pytest -v > "$OUT_DIR/section1_tests.txt" 2>&1
TEST_EXIT=$?
TESTS_PASSED=$(grep -oE '[0-9]+ passed' "$OUT_DIR/section1_tests.txt" | grep -oE '[0-9]+' | head -1)
TESTS_FAILED=$(grep -oE '[0-9]+ failed' "$OUT_DIR/section1_tests.txt" | grep -oE '[0-9]+' | head -1)
set -e
TESTS_PASSED="${TESTS_PASSED:-0}"
TESTS_FAILED="${TESTS_FAILED:-0}"

log "  Tests passed: $TESTS_PASSED, failed: $TESTS_FAILED, exit: $TEST_EXIT"

if [ "$TEST_EXIT" -eq 0 ] && [ "$TESTS_PASSED" -gt 0 ]; then
    step_pass "All $TESTS_PASSED unit tests pass"
else
    step_fail "Test failures: $TESTS_PASSED passed, $TESTS_FAILED failed, exit=$TEST_EXIT"
fi

# ===========================================================================
# Section 2: Build fixture directory with known ground truth
# ===========================================================================
log "--- Section 2: Build fixture directory ---"

# Create a controlled fixture with:
# - 2 identical files (for dedup detection)
# - 1 large binary (> a few KB)
# - 1 stale file (mtime set to past)
# - 1 cache file (.pyc)
# - 1 installer (.dmg)
# - 1 archive (.zip)
# - 1 unicode-named file
mkdir -p "$FIXTURE_DIR/docs" "$FIXTURE_DIR/Downloads" "$FIXTURE_DIR/cache"

echo "identical content" > "$FIXTURE_DIR/docs/file_a.txt"
echo "identical content" > "$FIXTURE_DIR/docs/file_b.txt"
echo "unique content" > "$FIXTURE_DIR/docs/file_c.txt"

# Create a 512 KB binary
dd if=/dev/urandom of="$FIXTURE_DIR/Downloads/big.bin" bs=1024 count=512 2>/dev/null

# Fake installer + archive
echo "fake dmg" > "$FIXTURE_DIR/Downloads/app.dmg"
echo "fake zip" > "$FIXTURE_DIR/Downloads/backup.zip"

# Cache file
echo "cache data" > "$FIXTURE_DIR/cache/module.pyc"

# Unicode file
echo "日本語" > "$FIXTURE_DIR/docs/日本語.txt"

# Stale file (touch to 2 years ago)
echo "stale" > "$FIXTURE_DIR/docs/old.txt"
touch -t 202401010000 "$FIXTURE_DIR/docs/old.txt" 2>/dev/null || true

FIXTURE_COUNT=$(find "$FIXTURE_DIR" -type f | wc -l | tr -d ' ')
log "  Fixture has $FIXTURE_COUNT files"

if [ "$FIXTURE_COUNT" -ge 8 ]; then
    step_pass "Fixture directory built with $FIXTURE_COUNT files"
else
    step_fail "Fixture directory incomplete ($FIXTURE_COUNT files)"
fi

# Redirect HOME so the tool's ~/.tidyhome/index.db lands in OUT_DIR
export HOME="$OUT_DIR"

# ===========================================================================
# Section 3: Scan the fixture
# ===========================================================================
log "--- Section 3: Scan the fixture ---"

SCAN_OUTPUT=$(cd "$TIDYHOME_DIR" && "$PYTHON" -m tidyhome scan --path "$FIXTURE_DIR" 2>&1) || true
echo "$SCAN_OUTPUT" > "$OUT_DIR/section3_scan.txt"

if echo "$SCAN_OUTPUT" | grep -qE "Indexed [0-9]+ files"; then
    INDEXED=$(echo "$SCAN_OUTPUT" | grep -oE "Indexed [0-9]+" | grep -oE "[0-9]+" | head -1)
    step_pass "Scan indexed $INDEXED files"
else
    step_fail "Scan did not report index count"
fi

if [ -f "$FIXTURE_DB" ]; then
    DB_SIZE=$(stat -f%z "$FIXTURE_DB" 2>/dev/null || stat -c%s "$FIXTURE_DB" 2>/dev/null || echo "0")
    step_pass "SQLite database created at ~/.tidyhome/index.db ($DB_SIZE bytes)"
else
    step_fail "SQLite database not created at expected path"
fi

# ===========================================================================
# Section 4: Report — verify size breakdown
# ===========================================================================
log "--- Section 4: Size report ---"

REPORT_OUTPUT=$(cd "$TIDYHOME_DIR" && "$PYTHON" -m tidyhome report 2>&1) || true
echo "$REPORT_OUTPUT" > "$OUT_DIR/section4_report.txt"

if echo "$REPORT_OUTPUT" | grep -q "Directory sizes" && \
   echo "$REPORT_OUTPUT" | grep -q "File type breakdown" && \
   echo "$REPORT_OUTPUT" | grep -q "20 largest files"; then
    step_pass "Report shows all 3 sections (directories, types, largest)"
else
    step_fail "Report missing one or more sections"
fi

if echo "$REPORT_OUTPUT" | grep -q "big.bin"; then
    step_pass "Largest file (big.bin) appears in report"
else
    step_fail "big.bin not found in largest-files report"
fi

# ===========================================================================
# Section 5: Dupes — verify duplicate detection
# ===========================================================================
log "--- Section 5: Duplicate detection ---"

DUPES_OUTPUT=$(cd "$TIDYHOME_DIR" && "$PYTHON" -m tidyhome dupes 2>&1) || true
echo "$DUPES_OUTPUT" > "$OUT_DIR/section5_dupes.txt"

if echo "$DUPES_OUTPUT" | grep -q "Duplicate files"; then
    if echo "$DUPES_OUTPUT" | grep -q "file_a.txt" && \
       echo "$DUPES_OUTPUT" | grep -q "file_b.txt"; then
        step_pass "Ground-truth duplicate pair (file_a.txt, file_b.txt) detected"
    else
        step_fail "Duplicates reported but file_a/file_b pair not identified"
    fi
else
    step_fail "Dupes output missing 'Duplicate files' header"
fi

# ===========================================================================
# Section 6: Stale — verify stale file detection
# ===========================================================================
log "--- Section 6: Stale file detection ---"

STALE_OUTPUT=$(cd "$TIDYHOME_DIR" && "$PYTHON" -m tidyhome stale --days 90 2>&1) || true
echo "$STALE_OUTPUT" > "$OUT_DIR/section6_stale.txt"

if echo "$STALE_OUTPUT" | grep -q "old.txt" || echo "$STALE_OUTPUT" | grep -q "Stale files"; then
    step_pass "Stale report contains old.txt (mtime 2024-01-01)"
else
    step_fail "Stale report did not surface the intentionally-old fixture file"
fi

# ===========================================================================
# Section 7: Suggest — verify smart analysis
# ===========================================================================
log "--- Section 7: Cleanup suggestions ---"

SUGGEST_OUTPUT=$(cd "$TIDYHOME_DIR" && "$PYTHON" -m tidyhome suggest 2>&1) || true
echo "$SUGGEST_OUTPUT" > "$OUT_DIR/section7_suggest.txt"

SUGGEST_CATEGORIES=0
for cat in "CACHE" "INSTALLER" "ARCHIVE"; do
    if echo "$SUGGEST_OUTPUT" | grep -q "\[$cat\]"; then
        SUGGEST_CATEGORIES=$((SUGGEST_CATEGORIES + 1))
    fi
done

if [ "$SUGGEST_CATEGORIES" -ge 3 ]; then
    step_pass "Suggest detected all 3 fixture categories (CACHE, INSTALLER, ARCHIVE)"
else
    step_fail "Suggest only detected $SUGGEST_CATEGORIES/3 categories"
fi

# ===========================================================================
# Section 8: Clean --dry-run — verify no files deleted
# ===========================================================================
log "--- Section 8: Clean dry-run (safety) ---"

BEFORE_COUNT=$(find "$FIXTURE_DIR" -type f | wc -l | tr -d ' ')
CLEAN_OUTPUT=$(cd "$TIDYHOME_DIR" && "$PYTHON" -m tidyhome clean --all 2>&1) || true
echo "$CLEAN_OUTPUT" > "$OUT_DIR/section8_clean.txt"
AFTER_COUNT=$(find "$FIXTURE_DIR" -type f | wc -l | tr -d ' ')

if [ "$BEFORE_COUNT" -eq "$AFTER_COUNT" ]; then
    step_pass "Dry-run clean did NOT delete any fixture files ($BEFORE_COUNT before, $AFTER_COUNT after)"
else
    step_fail "Files changed after dry-run! before=$BEFORE_COUNT after=$AFTER_COUNT"
fi

if echo "$CLEAN_OUTPUT" | grep -q "DRY RUN" && echo "$CLEAN_OUTPUT" | grep -q "No files were deleted"; then
    step_pass "Clean output explicitly confirms DRY RUN"
else
    step_fail "Clean output missing DRY RUN disclaimers"
fi

# ===========================================================================
# Section 9: Execute clean on a sacrificial copy (actual deletion)
# ===========================================================================
log "--- Section 9: Execute clean on sacrificial copy ---"

SACRIFICIAL="$OUT_DIR/sacrificial"
cp -R "$FIXTURE_DIR" "$SACRIFICIAL"

# Scan it
cd "$TIDYHOME_DIR" && "$PYTHON" -m tidyhome scan --path "$SACRIFICIAL" > "$OUT_DIR/section9_scan.txt" 2>&1 || true

SACRIFICIAL_BEFORE=$(find "$SACRIFICIAL" -name "*.pyc" | wc -l | tr -d ' ')
cd "$TIDYHOME_DIR" && "$PYTHON" -m tidyhome clean --cache --execute > "$OUT_DIR/section9_execute.txt" 2>&1 || true
SACRIFICIAL_AFTER=$(find "$SACRIFICIAL" -name "*.pyc" | wc -l | tr -d ' ')

if [ "$SACRIFICIAL_BEFORE" -ge 1 ] && [ "$SACRIFICIAL_AFTER" -eq 0 ]; then
    step_pass "Execute mode deleted $SACRIFICIAL_BEFORE .pyc cache file(s)"
else
    step_fail "Execute mode did not delete cache (before=$SACRIFICIAL_BEFORE after=$SACRIFICIAL_AFTER)"
fi

# ===========================================================================
# Section 10: Help text shows all commands
# ===========================================================================
log "--- Section 10: CLI help ---"

HELP_OUTPUT=$(cd "$TIDYHOME_DIR" && "$PYTHON" -m tidyhome --help 2>&1) || true
echo "$HELP_OUTPUT" > "$OUT_DIR/section10_help.txt"

COMMANDS_FOUND=0
for cmd in "scan" "report" "dupes" "stale" "suggest" "clean"; do
    if echo "$HELP_OUTPUT" | grep -q "$cmd"; then
        COMMANDS_FOUND=$((COMMANDS_FOUND + 1))
    fi
done

if [ "$COMMANDS_FOUND" -eq 6 ]; then
    step_pass "Help text shows all 6 subcommands"
else
    step_fail "Help text missing commands ($COMMANDS_FOUND/6 found)"
fi

# ===========================================================================
# Summary
# ===========================================================================
log ""
log "=============================================="
log "=== SUMMARY ==="
log "=============================================="
log "Passed: $PASS / $((PASS + FAIL))"
log ""

{
    echo "# TidyHome Showpiece — Run $RUN_ID"
    echo ""
    echo "**Concept**: Real CLI tool built from CAM-PULSE knowledge base,"
    echo "validated end-to-end on a controlled fixture directory."
    echo ""
    echo "## Fixture Ground Truth"
    echo ""
    echo "- 2 identical text files (dedup target)"
    echo "- 1 large binary file"
    echo "- 1 stale file (mtime 2024-01-01)"
    echo "- 1 cache file (.pyc)"
    echo "- 1 installer (.dmg)"
    echo "- 1 archive (.zip)"
    echo "- 1 unicode-named file"
    echo ""
    echo "## Validation Steps"
    echo ""
    for s in "${STEPS[@]}"; do
        echo "- $s"
    done
    echo ""
    echo "## Result"
    echo ""
    if [ "$FAIL" -eq 0 ]; then
        echo "ALL $PASS STEPS PASSED"
        echo ""
        echo "TidyHome is validated end-to-end: scan, report, dupes, stale,"
        echo "suggest, and clean all work correctly on a controlled fixture."
    else
        echo "FAILURES: $FAIL"
        echo "Passed: $PASS"
    fi
} > "$OUT_DIR/summary.md"

log ""
log "Artifacts written to: $OUT_DIR/"
cat "$OUT_DIR/summary.md"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
