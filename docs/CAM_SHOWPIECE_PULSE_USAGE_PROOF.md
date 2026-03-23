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

## Proven Results (Live Run 2026-03-23)

### The Definitive Proof: Working Code + Passing Tests

**Task ID**: `b1d4edef-d4f1-43f0-8968-196236c29b4d`

**Task**: "Add scoped peer discovery with signal-0 process liveness checks to the broker. Add enum-constrained message schemas for peer communication and auto-summary generation for completed sessions. Include tests."

**Result**:
```
Retrieved=3 | Used=2 | Attributed=2 | Success=1
Verification: approved=True | Quality: 0.82 | Expectation Match: 1.00
Files written: 4 (README.md, src/peer_mesh/__init__.py, src/peer_mesh/broker.py, tests/test_broker.py)
Tests: 4/4 passing
```

**What the agent produced** (159 lines of working code):

| Pattern | Code Evidence | Methodology Source |
|---------|--------------|-------------------|
| Signal-0 liveness | `os.kill(pid, 0)` with ProcessLookupError/PermissionError handling | Mined from `louislva/claude-peers-mcp` |
| Scoped peer discovery | `discover(scope=...)` filters by scope + liveness | Mined from `louislva/claude-peers-mcp` |
| Enum-constrained schemas | `PeerMessageType(str, Enum)` with `from_dict()` validation | Mined from `louislva/claude-peers-mcp` |
| Auto-summary generation | `summarize_session()` / `complete_session()` | Mined from `louislva/claude-peers-mcp` |

**Test verification** (`pytest tests/ -v`):
```
tests/test_broker.py::test_scoped_discovery_filters_by_scope_and_liveness PASSED
tests/test_broker.py::test_is_alive_uses_signal_zero PASSED
tests/test_broker.py::test_enum_constrained_peer_message_schema PASSED
tests/test_broker.py::test_completed_session_generates_summary PASSED
4 passed
```

### What This Proves vs. What It Doesn't

**Proves**:
- PULSE-mined methodologies are retrieved from the knowledge base during `cam create --execute`
- The agent receives methodology hints in its prompt via `past_solutions`
- The agent produces working code with passing tests (not just a text plan)
- The code demonstrates patterns that match mined methodology descriptions
- The verification pipeline approves the output (quality score 0.82)

**Honest limitations**:
- Attribution uses token overlap between agent output and methodology metadata. This is a lexical signal, not a causal proof that the agent "read and applied" the methodology.
- The semantic search returns the top 3 most similar methodologies. Not all ingested repos will appear in every run — it depends on the task description and competition from 100+ other methodologies.
- The `Success=1` flag indicates the overall task succeeded AND the methodology was used in the output — but the specific causal contribution of each methodology to each line of code is not tracked.

### Prescreened Ingestion Context

Three repos were ingested via `cam pulse ingest` (bypassing X-Scout):
- `0xK3vin/MegaMemory` — 4 methodologies mined (knowledge graph, embeddings, timeline, merge)
- `heroui-inc/heroui` — 6 methodologies mined (CSS variables, compound components, deferred value, sub-agents, env validation, URL-state)
- `louislva/claude-peers-mcp` — 6 methodologies mined (auto-summary, MCP tool schema, non-blocking startup, process liveness, scoped peer discovery, singleton broker)

The proof run targeted vocabulary from `louislva/claude-peers-mcp` patterns. The agent produced code that implements signal-0 liveness, scoped discovery, enum schemas, and auto-summaries — all patterns mined from that repo.

## Outputs

```text
tmp/pulse_usage_proof/<RUN_ID>/
  step1_search.txt         -- cam learn search results
  step2_build.txt          -- cam create --execute output
  step3_usage.txt          -- cam learn usage attribution
  step4_changed_files.txt  -- files produced by the build
  summary.md               -- pass/fail per step
```
