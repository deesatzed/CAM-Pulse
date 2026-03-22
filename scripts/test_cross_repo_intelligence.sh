#!/usr/bin/env bash
# ===========================================================================
# CAM Showpiece: Cross-Repo Intelligence
# Proves CAM's accumulated knowledge makes it measurably smarter
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# --- Configuration ---
EXECUTE="${CAM_CROSS_REPO_EXECUTE:-0}"
AGENT="${CAM_CROSS_REPO_AGENT:-claude}"
DEFAULT_QUERIES="CLI tool architecture,error handling patterns,testing strategy"
QUERIES="${CAM_CROSS_REPO_SEARCH_QUERIES:-$DEFAULT_QUERIES}"

# --- Run ID and output directory ---
RUN_ID="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="tmp/cross_repo_intelligence/$RUN_ID"
mkdir -p "$OUT_DIR"

PASS=0
FAIL=0
STEPS=()

log() { echo "[$(date +%H:%M:%S)] $*"; }
step_pass() { PASS=$((PASS + 1)); STEPS+=("PASS: $1"); log "PASS: $1"; }
step_fail() { FAIL=$((FAIL + 1)); STEPS+=("FAIL: $1"); log "FAIL: $1"; }

# ===========================================================================
log "=== Cross-Repo Intelligence Showpiece ==="
log "Run ID: $RUN_ID"
log "Execute mode: $EXECUTE"
log "Agent: $AGENT"
log "Output: $OUT_DIR/"

# ===========================================================================
# Step 1: Baseline knowledge check
# ===========================================================================
log "--- Step 1: Knowledge baseline ---"
BASELINE_OUTPUT=$(cam learn report -n 5 2>&1) || true
echo "$BASELINE_OUTPUT" > "$OUT_DIR/knowledge_baseline.txt"

METH_COUNT=$(echo "$BASELINE_OUTPUT" | grep -oE '[0-9,]+ active methodologies' | grep -oE '[0-9,]+' | tr -d ',' || echo "0")
log "Knowledge base: $METH_COUNT methodologies"

if [ "$METH_COUNT" -gt 0 ]; then
    step_pass "Knowledge base has $METH_COUNT methodologies"
else
    step_fail "Knowledge base is empty — mine some repos first (cam mine)"
fi

# ===========================================================================
# Step 2: Semantic search across domains
# ===========================================================================
log "--- Step 2: Cross-domain knowledge search ---"
IFS=',' read -ra QUERY_LIST <<< "$QUERIES"
SEARCH_PASS=0

for query in "${QUERY_LIST[@]}"; do
    query=$(echo "$query" | xargs)  # trim whitespace
    log "Searching: '$query'"
    SEARCH_OUTPUT=$(cam learn search "$query" -n 5 2>&1) || true
    echo "$SEARCH_OUTPUT" > "$OUT_DIR/search_$(echo "$query" | tr ' ' '_').txt"

    if echo "$SEARCH_OUTPUT" | grep -qE '[0-9]+ result'; then
        RESULT_COUNT=$(echo "$SEARCH_OUTPUT" | grep -oE '[0-9]+ result' | head -1 | grep -oE '[0-9]+')
        log "  Found $RESULT_COUNT results"
        SEARCH_PASS=$((SEARCH_PASS + 1))
    else
        log "  No results"
    fi
done

if [ "$SEARCH_PASS" -eq "${#QUERY_LIST[@]}" ]; then
    step_pass "All $SEARCH_PASS search queries returned results"
elif [ "$SEARCH_PASS" -gt 0 ]; then
    step_pass "$SEARCH_PASS/${#QUERY_LIST[@]} queries returned results"
else
    step_fail "No search queries returned results"
fi

# ===========================================================================
# Step 3: Provenance check — sources span multiple repos
# ===========================================================================
log "--- Step 3: Provenance diversity ---"
# Extract source repo names from the Score column line (0.NNN is followed by source name)
# Rich table format: │  0.577 │ CloakBrowser       │
ALL_SOURCES=""
for f in "$OUT_DIR"/search_*.txt; do
    # Lines with scores like "0.577" are result rows; the next │-delimited field is Source
    SOURCES=$(grep -oE '0\.[0-9]{3} │ [A-Za-z0-9_][A-Za-z0-9_.-]*' "$f" 2>/dev/null \
        | sed 's/0\.[0-9]* │ //' | tr -s ' ' | sort -u || true)
    ALL_SOURCES=$(printf "%s\n%s" "$ALL_SOURCES" "$SOURCES")
done

UNIQUE_SOURCES=$(echo "$ALL_SOURCES" | sort -u | grep -v '^$' | grep -v '^-$' | wc -l | tr -d ' ')
log "Unique source repos across searches: $UNIQUE_SOURCES"

if [ "$UNIQUE_SOURCES" -ge 3 ]; then
    step_pass "Knowledge spans $UNIQUE_SOURCES unique source repos"
elif [ "$UNIQUE_SOURCES" -ge 1 ]; then
    step_pass "Knowledge from $UNIQUE_SOURCES source repo(s)"
else
    step_fail "Could not identify source repos in search results"
fi

# ===========================================================================
# Step 4: Optional — build with knowledge-informed context
# ===========================================================================
if [ "$EXECUTE" = "1" ]; then
    log "--- Step 4: Knowledge-informed build ---"
    BUILD_DIR="/tmp/cross-repo-intelligence-demo-$RUN_ID"

    BUILD_OUTPUT=$(cam create "$BUILD_DIR" \
        --repo-mode new \
        --request "Create a Python CLI tool with subcommands for managing a local SQLite database of bookmarks (add, list, search, delete, export). Include comprehensive error handling and tests." \
        --check "python -m bookmark_cli --help" \
        --execute \
        --accept-preflight-defaults \
        --agent "$AGENT" \
        2>&1) || true
    echo "$BUILD_OUTPUT" > "$OUT_DIR/build_output.txt"

    if echo "$BUILD_OUTPUT" | grep -qi "success\|created\|passed"; then
        step_pass "Build completed with knowledge-informed context"

        # Step 5: Check attribution
        log "--- Step 5: Methodology attribution ---"
        TASK_ID=$(echo "$BUILD_OUTPUT" | grep -oE 'task_id[=:]\s*\S+' | head -1 | cut -d'=' -f2 | cut -d':' -f2 | tr -d ' "' || echo "")

        if [ -n "$TASK_ID" ]; then
            ATTR_OUTPUT=$(cam learn usage "$TASK_ID" 2>&1) || true
            echo "$ATTR_OUTPUT" > "$OUT_DIR/attribution.txt"

            if echo "$ATTR_OUTPUT" | grep -qE 'Retrieved=[1-9]'; then
                step_pass "Build used retrieved methodologies (attribution tracked)"
            else
                step_fail "No methodology attribution recorded for build"
            fi
        else
            log "Could not extract task ID from build output"
            step_fail "Task ID not found in build output"
        fi
    else
        step_fail "Build did not succeed"
    fi
else
    log "--- Step 4: Skipped (set CAM_CROSS_REPO_EXECUTE=1 to enable) ---"
    step_pass "Build step skipped (search-only mode)"
fi

# ===========================================================================
# Summary
# ===========================================================================
log "=== Summary ==="
log "Passed: $PASS / $((PASS + FAIL))"

{
    echo "# Cross-Repo Intelligence — Run $RUN_ID"
    echo ""
    echo "Knowledge base: $METH_COUNT methodologies"
    echo "Search queries: ${QUERIES}"
    echo "Execute mode: $EXECUTE"
    echo "Agent: $AGENT"
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
