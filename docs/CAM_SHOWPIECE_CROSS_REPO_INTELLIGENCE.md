# CAM Showpiece: Cross-Repo Intelligence

This showpiece proves that CAM's accumulated knowledge makes it measurably smarter than a blank agent.

## What This Proves

1. CAM has a knowledge base of 1,700+ methodologies mined from real repositories
2. When given a new task, CAM searches this knowledge for relevant patterns
3. The retrieved patterns are cited with provenance (which repo, when mined, confidence)
4. The build output is informed by cross-repo knowledge — not just the LLM's training data
5. You can trace exactly which learned patterns influenced the result

This is what makes CAM different: **every repo it mines makes it better at the next one.**

## The Differentiator

Other agentic coding tools start blank every time. They have the LLM's training data and nothing else.

CAM starts with:
- Patterns from dozens of real repos (architecture, testing, CLI, security, data processing)
- Semantic search across all stored knowledge (vector + text hybrid)
- Provenance for every piece of knowledge (source repo, mined date, quality score)
- Synergy edges between related patterns
- Lifecycle tracking (stored → enriched → retrieved → operationalized → proven)

## Run It

### Step 1: See What CAM Knows

```bash
# Total knowledge
cam learn report -n 5

# Search for specific domains
cam learn search "CLI tool architecture" -v -n 10
cam learn search "error handling patterns" -v -n 10
cam learn search "testing strategy" -v -n 10
```

Each result shows:
- **Description** — What the pattern is
- **Score** — Combined vector + text relevance
- **Source** — Which repo it came from
- **Domains** — What categories it belongs to
- **Stage** — Where it is in the lifecycle (viable/embryonic/proven)

### Step 2: Build Something That Uses the Knowledge

```bash
cam create /tmp/cross-repo-demo \
  --repo-mode new \
  --request "Create a Python CLI tool with subcommands for managing a local SQLite database of bookmarks (add, list, search, delete, export). Include comprehensive error handling and tests." \
  --check "python -m bookmark_cli --help" \
  --check "python -m pytest tests/ -q" \
  --execute \
  --accept-preflight-defaults
```

### Step 3: Check What Knowledge Was Used

```bash
# Get the task ID
cam task results

# See which methodologies were retrieved and used
cam learn usage <task-id>
```

The attribution table shows which mined patterns influenced the build:
- **Retrieved** — CAM found this pattern relevant to your task
- **Used** — The pattern was included in the agent's context
- **Success** — The build succeeded with this pattern applied
- **Source** — The original repo the pattern came from

### Step 4: Compare — Search vs Build

Run the search for the same domain as the build:

```bash
cam learn search "CLI bookmark database" -v -n 5
```

You should see overlap between what the search returns and what was used in the build. This proves the pipeline: **search → retrieve → apply → attribute**.

## Automated Harness

```bash
chmod +x scripts/test_cross_repo_intelligence.sh
OPENROUTER_API_KEY=... GOOGLE_API_KEY=... \
  ./scripts/test_cross_repo_intelligence.sh
```

The script:
1. Confirms knowledge base has methodologies (baseline > 0)
2. Runs `cam learn search` for 3 different domains — verifies results returned
3. Optionally runs a `cam create` build (set `CAM_CROSS_REPO_EXECUTE=1`)
4. Checks methodology attribution for the build task
5. Reports pass/fail per step

## What No Other Tool Does

| Capability | CAM | Aider | Cursor | AutoGPT | Generic Claw |
|------------|-----|-------|--------|---------|-------------|
| Persistent cross-repo memory | 1,700+ methodologies | None | None | None | None |
| Semantic search over knowledge | Hybrid vec+text | N/A | N/A | N/A | N/A |
| Provenance tracking | Source repo + date | N/A | N/A | N/A | N/A |
| Knowledge lifecycle | 5 stages | N/A | N/A | N/A | N/A |
| Uses mined knowledge in builds | Automatic retrieval | No | No | No | No |
| Methodology attribution | Per-task tracking | No | No | No | No |

## Controls

- `CAM_CROSS_REPO_EXECUTE` — Set to 1 to run the full create + build cycle (default: search-only)
- `CAM_CROSS_REPO_AGENT` — Choose agent: claude, codex, gemini, grok (default: claude)
- `CAM_CROSS_REPO_SEARCH_QUERIES` — Comma-separated search queries to test

## Outputs

```text
tmp/cross_repo_intelligence/<RUN_ID>/
```

Key files:
- `knowledge_baseline.txt` — methodology count and top results
- `search_*.txt` — search results per query
- `build_output.txt` — cam create output (if execute mode)
- `attribution.txt` — methodology usage for the build task
- `summary.md` — pass/fail per step
