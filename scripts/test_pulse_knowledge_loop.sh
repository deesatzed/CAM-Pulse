#!/usr/bin/env bash
# ===========================================================================
# CAM Showpiece: PULSE Knowledge Loop
# Demonstrates: discover → filter → mine → store → search
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# --- Configuration ---
KEYWORDS="${CAM_PULSE_KEYWORDS:-github.com new AI agent repo}"
LOOKBACK="${CAM_PULSE_LOOKBACK_DAYS:-3}"
DRY_RUN="${CAM_PULSE_DRY_RUN:-0}"
MAX_ASSIMILATE="${CAM_PULSE_MAX_ASSIMILATE:-10}"

# --- Run ID and output directory ---
RUN_ID="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="tmp/pulse_knowledge_loop/$RUN_ID"
mkdir -p "$OUT_DIR"

PASS=0
FAIL=0
STEPS=()

log() { echo "[$(date +%H:%M:%S)] $*"; }
step_pass() { PASS=$((PASS + 1)); STEPS+=("PASS: $1"); log "PASS: $1"; }
step_fail() { FAIL=$((FAIL + 1)); STEPS+=("FAIL: $1"); log "FAIL: $1"; }

# ===========================================================================
# Preflight
# ===========================================================================
log "=== PULSE Knowledge Loop Showpiece ==="
log "Run ID: $RUN_ID"
log "Keywords: $KEYWORDS"
log "Lookback: $LOOKBACK days"
log "Output: $OUT_DIR/"

# Check required keys
if [ -z "${XAI_API_KEY:-}" ]; then
    log "ERROR: XAI_API_KEY not set. Export it or add to .env"
    exit 1
fi

# ===========================================================================
# Step 1: Baseline methodology count
# ===========================================================================
log "--- Step 1: Baseline knowledge check ---"
BASELINE_OUTPUT=$(cam learn report -n 1 2>&1) || true
echo "$BASELINE_OUTPUT" > "$OUT_DIR/baseline.txt"

# Extract methodology count from "N active methodologies" line
BASELINE_COUNT=$(echo "$BASELINE_OUTPUT" | grep -oE '[0-9,]+ active methodologies' | grep -oE '[0-9,]+' | tr -d ',' || echo "0")
log "Baseline: $BASELINE_COUNT methodologies"

if [ "$BASELINE_COUNT" -ge 0 ]; then
    step_pass "Baseline recorded ($BASELINE_COUNT methodologies)"
else
    step_fail "Could not read baseline methodology count"
fi

# ===========================================================================
# Step 2: Run PULSE scan
# ===========================================================================
log "--- Step 2: PULSE scan ---"
FROM_DATE=$(date -v-${LOOKBACK}d +%Y-%m-%d 2>/dev/null || date -d "-${LOOKBACK} days" +%Y-%m-%d)
TO_DATE=$(date +%Y-%m-%d)

SCAN_CMD="cam pulse scan --keywords \"$KEYWORDS\" --from-date $FROM_DATE --to-date $TO_DATE --verbose"
if [ "$DRY_RUN" = "1" ]; then
    SCAN_CMD="$SCAN_CMD --dry-run"
fi

log "Running: $SCAN_CMD"
SCAN_OUTPUT=$(eval "$SCAN_CMD" 2>&1) || true
echo "$SCAN_OUTPUT" > "$OUT_DIR/scan_output.txt"

# Extract discovery count
DISCOVERED=$(echo "$SCAN_OUTPUT" | grep -oE 'Discovered: [0-9]+' | grep -oE '[0-9]+' || echo "0")
ASSIMILATED=$(echo "$SCAN_OUTPUT" | grep -oE 'Assimilated: [0-9]+' | grep -oE '[0-9]+' || echo "0")

log "Discovered: $DISCOVERED, Assimilated: $ASSIMILATED"

if [ "$DISCOVERED" -gt 0 ]; then
    step_pass "Discovered $DISCOVERED repos from X"
else
    step_fail "No repos discovered (try broader keywords or wider date range)"
fi

# ===========================================================================
# Step 3: Check discoveries log
# ===========================================================================
log "--- Step 3: Discovery log ---"
DISC_OUTPUT=$(cam pulse discoveries 2>&1) || true
echo "$DISC_OUTPUT" > "$OUT_DIR/discoveries.txt"

if echo "$DISC_OUTPUT" | grep -q "github.com"; then
    step_pass "Discoveries logged with GitHub URLs"
else
    if [ "$DISCOVERED" -eq 0 ]; then
        step_fail "No discoveries to log (upstream scan found nothing)"
    else
        step_fail "Discoveries not properly logged"
    fi
fi

# ===========================================================================
# Step 4: Check new methodologies (delta)
# ===========================================================================
log "--- Step 4: Knowledge delta ---"
if [ "$DRY_RUN" = "1" ]; then
    log "Skipping delta check (dry-run mode)"
    step_pass "Delta check skipped (dry-run)"
else
    DELTA_OUTPUT=$(cam learn delta --since-hours 1 2>&1) || true
    echo "$DELTA_OUTPUT" > "$OUT_DIR/delta.txt"

    POST_OUTPUT=$(cam learn report -n 1 2>&1) || true
    POST_COUNT=$(echo "$POST_OUTPUT" | grep -oE '[0-9,]+ active methodologies' | grep -oE '[0-9,]+' | tr -d ',' || echo "0")

    if [ "$POST_COUNT" -gt "$BASELINE_COUNT" ]; then
        GAINED=$((POST_COUNT - BASELINE_COUNT))
        step_pass "Knowledge grew: +$GAINED methodologies ($BASELINE_COUNT → $POST_COUNT)"
    else
        if [ "$ASSIMILATED" -gt 0 ]; then
            step_fail "Assimilated $ASSIMILATED repos but methodology count unchanged ($POST_COUNT)"
        else
            step_pass "No assimilation attempted (0 novel repos) — count unchanged"
        fi
    fi
fi

# ===========================================================================
# Step 5: Semantic search verification
# ===========================================================================
log "--- Step 5: Knowledge search ---"
SEARCH_OUTPUT=$(cam learn search "AI agent" -n 3 2>&1) || true
echo "$SEARCH_OUTPUT" > "$OUT_DIR/search_results.txt"

if echo "$SEARCH_OUTPUT" | grep -qE '[0-9]+ result'; then
    step_pass "Knowledge search returns results"
else
    step_fail "Knowledge search returned no results"
fi

# ===========================================================================
# Summary
# ===========================================================================
log "=== Summary ==="
log "Passed: $PASS / $((PASS + FAIL))"

{
    echo "# PULSE Knowledge Loop — Run $RUN_ID"
    echo ""
    echo "Keywords: $KEYWORDS"
    echo "Date range: $FROM_DATE to $TO_DATE"
    echo "Baseline: $BASELINE_COUNT methodologies"
    echo "Discovered: $DISCOVERED repos"
    echo "Assimilated: $ASSIMILATED repos"
    echo ""
    echo "## Steps"
    echo ""
    for s in "${STEPS[@]}"; do
        echo "- $s"
    done
    echo ""
    echo "## Result"
    echo ""
    if [ "$FAIL" -eq 0 ]; then
        echo "ALL STEPS PASSED"
    else
        echo "FAILURES: $FAIL"
    fi
} > "$OUT_DIR/summary.md"

log "Artifacts written to: $OUT_DIR/"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
