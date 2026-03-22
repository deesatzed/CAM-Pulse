# CAM Showpiece: PULSE Knowledge Loop

This showpiece demonstrates the autonomous discovery-to-application pipeline that only CAM-PULSE provides.

No other agentic coding tool does this: discover repos from live social feeds, mine them for patterns, store knowledge with provenance, and use that knowledge in future builds — all autonomously.

## What This Proves

1. PULSE discovers GitHub repos mentioned on X (Twitter) without human curation
2. Discovered repos are filtered for novelty (semantic distance from existing knowledge)
3. Novel repos are cloned, analyzed by LLM, and stored as searchable methodologies
4. The knowledge is immediately available via `cam learn search`
5. When CAM builds something new, it retrieves relevant PULSE-discovered knowledge

This is the full loop: **discover → filter → mine → store → retrieve → apply**.

## Prerequisites

```bash
# Required API keys in .env
XAI_API_KEY=...        # xAI Responses API for Grok x_search
OPENROUTER_API_KEY=... # For mining LLM (any agent)
GOOGLE_API_KEY=...     # For embedding vectors (novelty + search)
```

Verify setup:
```bash
cam pulse preflight
```

## Run It

### Step 1: Baseline Knowledge Check

See what CAM already knows:

```bash
cam learn report -n 5
cam learn search "your domain of interest" -n 5
```

Record the methodology count — this is your baseline.

### Step 2: Run a PULSE Scan

```bash
cam pulse scan \
  --keywords "github.com new AI agent repo" \
  --from-date $(date -v-3d +%Y-%m-%d) \
  --to-date $(date +%Y-%m-%d) \
  --verbose
```

Expected output:
```
Scanning X via Grok with 1 keyword(s)...
  → github.com new AI agent repo
=== PULSE Scan Report [abc123] ===
Discovered: N
Novel: M
Assimilated: K
```

### Step 3: Verify What Was Learned

```bash
# Check discovery log
cam pulse discoveries

# Check what new methodologies were added
cam learn delta --since-hours 1

# Search for knowledge from the newly discovered repos
cam learn search "pattern from discovered repo"
```

### Step 4: Use the Knowledge in a Build

Now create something new. CAM will automatically retrieve relevant PULSE-discovered knowledge:

```bash
cam create /tmp/pulse-demo-app \
  --repo-mode new \
  --request "Create a CLI tool that monitors GitHub repos for new releases" \
  --check "python -m app --help" \
  --execute \
  --accept-preflight-defaults
```

After the build:
```bash
# See which methodologies were used
cam task results
# Pick the task ID from the output, then:
cam learn usage <task-id>
```

If the build used knowledge from a PULSE-discovered repo, you'll see it in the attribution table with a `source:` tag matching a repo found by X-Scout.

## Automated Harness

```bash
chmod +x scripts/test_pulse_knowledge_loop.sh
OPENROUTER_API_KEY=... GOOGLE_API_KEY=... XAI_API_KEY=... \
  ./scripts/test_pulse_knowledge_loop.sh
```

The script:
1. Records baseline methodology count
2. Runs a PULSE scan with configurable keywords
3. Verifies discoveries > 0
4. Verifies new methodologies were stored (delta > 0)
5. Runs `cam learn search` against a discovered repo's domain
6. Reports pass/fail for each step

## What Makes This Different

| Feature | CAM-PULSE | Other Claws | ChatGPT/Cursor |
|---------|-----------|-------------|----------------|
| Discovers repos autonomously | Yes (X-Scout) | No | No |
| Filters by semantic novelty | Yes (embedding distance) | No | No |
| Mines and stores patterns | Yes (methodology DB) | No | No |
| Uses discovered knowledge later | Yes (hybrid search) | No | No |
| Tracks provenance | Yes (source tags) | No | No |
| Budget-controlled | Yes (3-layer caps) | N/A | N/A |

## Controls

- `CAM_PULSE_KEYWORDS` — Override default scan keywords
- `CAM_PULSE_LOOKBACK_DAYS` — How far back to search (default 3)
- `CAM_PULSE_DRY_RUN` — Set to 1 to discover + filter only (no mining)
- `CAM_PULSE_MAX_ASSIMILATE` — Cap repos to mine per scan

## Outputs

The script writes artifacts under:

```text
tmp/pulse_knowledge_loop/<RUN_ID>/
```

Key files:
- `baseline.txt` — methodology count before scan
- `scan_output.txt` — full scan log
- `discoveries.txt` — list of discovered repos
- `delta.txt` — new methodologies added
- `search_results.txt` — knowledge search verification
- `summary.md` — pass/fail per step

## Cost

A typical scan costs:
- x_search: $0.005 per search call
- Model tokens (grok-4-1-fast): ~$0.01-0.10 per keyword
- Mining tokens (per repo): ~$0.05-0.20
- Total for a 3-keyword scan with 5 repos mined: ~$0.50-1.50
