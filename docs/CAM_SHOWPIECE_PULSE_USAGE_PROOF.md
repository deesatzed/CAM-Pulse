# CAM Showpiece: PULSE Usage Proof

This showpiece proves that PULSE-mined methodologies are not just stored -- they are **retrieved, presented to agents, and attributed** when CAM builds something new.

## What This Proves

The criticism: "You proved CAM can discover and store patterns, but not that it actually uses them."

This showpiece closes the loop:

1. PULSE discovers repos from X and mines 86 methodologies
2. `cam learn search` confirms the methodologies are retrievable by semantic search
3. `cam create --execute` builds a new module -- the MicroClaw cycle retrieves PULSE-mined methodologies as context hints
4. `cam learn usage <task-id>` shows the full attribution chain: `retrieved_presented` -> `used_in_outcome` -> `outcome_attributed`

## The Full Knowledge Loop

```
DISCOVER (X-Scout)          INGEST (prescreened URLs)
    |                            |
    v                            v
FILTER (novelty)            PRESET (high novelty)
    \                          /
     v                        v
MINE (LLM extracts patterns)
    |
    v
STORE (claw.db with embeddings)
    |
    v
SEARCH (hybrid vector + text)        <-- Step 1 proves this
    |
    v
RETRIEVE (MicroClaw.evaluate())      <-- Step 3 proves this
    |
    v
PRESENT (hints injected to agent)    <-- Step 3 proves this
    |
    v
BUILD (agent produces code)          <-- Step 2 proves this
    |
    v
ATTRIBUTE (token overlap inference)  <-- Step 3 proves this
```

## How It Works

### The Task Description

The task is deliberately worded to match PULSE-mined methodologies:

> "Add a sliding window rate limiter module that enforces per-provider call rate limiting with an injectable clock for testability. Include provider failover with per-key cooldown tracking when providers return 429 errors."

This targets:
- **`devwebxyn/securemcp-lite`**: "Sliding Window Rate Limiter with Injected Clock"
- **`gizmax/sandcastle`**: "Provider Failover with Per-Key Cooldown Tracking"
- **`gizmax/sandcastle`**: "SLO-Based Dynamic Model Routing with Confidence Scaling"

### The Attribution Pipeline

When `cam create --execute` runs:

1. **Evaluate phase** (`MicroClaw.evaluate()`): Hybrid search retrieves the top 3 methodologies matching the task description. Each is logged as `stage=retrieved_presented`.

2. **Act phase** (`MicroClaw.act()`): The agent receives the task context with methodology notes as hints. The agent builds the module informed by these patterns.

3. **Learn phase** (`MicroClaw.learn()`): `_infer_used_methodology_ids()` tokenizes the build output and computes overlap with each retrieved methodology. Matches above threshold are logged as `stage=used_in_outcome` and `stage=outcome_attributed`.

4. **Verify** (`cam learn usage <task-id>`): Shows the complete attribution chain with methodology IDs, stages, scores, and provenance.

## Run It

### Prerequisites

- XAI_API_KEY, OPENROUTER_API_KEY, GOOGLE_API_KEY set
- PULSE knowledge base populated (run `cam pulse scan` first)
- A target repo (the script creates one if needed)

### Quick Run

```bash
# From the CAM repo root with populated knowledge base:
./scripts/test_pulse_usage_proof.sh
```

### From Test Clone

```bash
cd /tmp/cam-pulse-test
source .venv/bin/activate && source .env
export CAM_PULSE_DIR=/tmp/cam-pulse-test
export CAM_PULSE_TARGET=/tmp/pulse-usage-proof
bash scripts/test_pulse_usage_proof.sh
```

## Verification Steps

The script checks 4 steps:

| Step | What | Pass Criteria |
|------|------|---------------|
| 1 | Pre-check: `cam learn search` | PULSE methodology found with score > 0 |
| 2 | Execute: `cam create --execute` | Build completes without error |
| 3 | Attribution: `cam learn usage` | Retrieved > 0, Used > 0, Attributed > 0 |
| 4 | Code produced: `git diff` | Files changed in target repo |

The critical step is **Step 3**. If `Retrieved > 0`, the PULSE-mined methodology was pulled from the knowledge base and presented to the agent. If `Used > 0`, the agent's output contains vocabulary matching the methodology. If `Attributed > 0`, the methodology gets credit for influencing the build.

## What No Other Tool Does

No other AI coding tool:
1. Discovers patterns from live social feeds
2. Mines them into persistent, searchable knowledge
3. Automatically retrieves them when building new code
4. Tracks attribution (which pattern influenced which build)
5. Feeds outcomes back to improve retrieval (fitness scoring)

This showpiece proves the complete loop, not just storage.

## Proven Results

### Phase 1: X-Scout Discovery (2026-03-22)

Two runs confirmed the full attribution chain for X-Scout-discovered repos:

**Run 1** (manual, task ID `a1408905-14b2-4455-840b-9419a746220c`):
```
Retrieved=3 | Used=3 | Attributed=3
```
Attributed methodologies from: `bug-ops/zeph`, `jackwener/opencli`, `cronusl-1141/ai-company`

**Run 2** (automated script, task ID `fcaa1748-ff04-49dc-a902-e175b3dca2bb`):
```
Retrieved=3 | Used=3 | Attributed=3
```
Attributed methodologies from: `sbhooley/ainativelang`, `cronusl-1141/ai-company` (2 methodologies)

### Phase 2: Prescreened Ingestion via `cam pulse ingest` (2026-03-23)

Three repos were ingested directly using `cam pulse ingest` (bypassing X-Scout):
- `0xK3vin/MegaMemory` — 4 methodologies mined
- `heroui-inc/heroui` — 6 methodologies mined
- `louislva/claude-peers-mcp` — 6 methodologies mined

Three additional runs proved the newly ingested methodologies are retrieved and attributed:

**Run 3** (task ID `0e3f6f8d-34cc-4bc3-97fa-8b0026c6463a`):
```
Retrieved=3 | Used=3 | Attributed=3
```
Task: Agent mesh coordinator with deferred value, heartbeat monitoring, scheduled tasks.
Attributed: `egeuysall/brain`, **`heroui-inc/heroui`** (Deferred Value Pattern), `devwebxyn/securemcp-lite`

**Run 4** (task ID `c61e0000-daf3-4a48-a4ff-2e3ee1c397ae`):
```
Retrieved=3 | Used=3 | Attributed=3
```
Task: Singleton broker with scoped peer discovery, signal-0 liveness, knowledge graph.
Attributed: `devwebxyn/securemcp-lite`, **`louislva/claude-peers-mcp`** (Process Liveness), `jackwener/opencli`

**Run 5** (task ID `07b75456-b4bb-4e04-a682-940a4d5e4769`):
```
Retrieved=3 | Used=3 | Attributed=3
```
Task: Knowledge graph with typed concepts, timeline logging, merge conflict detection.
Attributed: **`heroui-inc/heroui`** (URL-State Persistence + Compound Component), `cronusl-1141/ai-company`

### Summary

5 runs, 15 retrievals, 15 attributions. Two newly ingested repos (`heroui-inc/heroui`, `louislva/claude-peers-mcp`) were independently retrieved and attributed — proving that `cam pulse ingest` feeds directly into the active knowledge loop. The complete pipeline works for both X-Scout discovery and prescreened ingestion.

## Outputs

```text
tmp/pulse_usage_proof/<RUN_ID>/
  step1_search.txt         -- cam learn search results
  step2_build.txt          -- cam create --execute output
  step3_usage.txt          -- cam learn usage attribution
  step4_changed_files.txt  -- files produced by the build
  summary.md               -- pass/fail per step
```
