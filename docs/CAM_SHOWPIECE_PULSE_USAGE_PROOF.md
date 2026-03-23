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

### Full Knowledge Injection Proof (v7 — 2026-03-23)

**Task ID**: `1441f72c-95e4-49ae-b670-5412b6976704`

**Task**: "Build a pre-tool-call guardrail system with pluggable policy checks, a runtime-configurable middleware chain, and loop detection that force-stops repeated tool calls."

**What changed vs. earlier runs**: The agent now receives FULL methodology content in its prompt — not just a 500-char hint. The prompt includes:
- `problem_description` — what the methodology solves
- `implementation_sketch` — how to apply it (from capability_data)
- `solution_code` — the actual pattern code (up to 1500 chars)
- `activation_triggers` — when to apply this pattern

**Log evidence**: `Injected 2 PULSE methodology pattern(s) into agent prompt`

**Result**:
```
Retrieved=3 | Used=3 | Attributed=3 | Success=1
Verification: approved=True | Quality: 0.85 | Expectation Match: 1.00
Files written: 4 (README.md, src/guardrails/__init__.py, src/guardrails/core.py, tests/test_guardrails.py)
Tests: 4/4 passing
```

**Code produced** (157 lines) mapped to mined patterns:

| Pattern | Code Evidence | Mined From |
|---------|--------------|------------|
| Pre-tool-call guardrails | `GuardrailEngine.process()` evaluates policies before handler | `bytedance/deer-flow` |
| Pluggable policy checks | `GuardrailPolicy = Callable[[ToolCallRequest], GuardrailPolicyResult]` | `bytedance/deer-flow` |
| Runtime-configurable middleware | `MiddlewareChain` with composable `add()` | `bytedance/deer-flow` |
| Loop detection force-stop | `detect_repeated_tool_calls(max_repeats=2)` tracks call signatures | `bytedance/deer-flow` |

**Tests** (`pytest tests/ -v`):
```
tests/test_guardrails.py::test_policy_blocks_tool_call PASSED
tests/test_guardrails.py::test_middleware_can_modify_tool_call_before_policy PASSED
tests/test_guardrails.py::test_loop_detection_force_stops_repeated_identical_calls PASSED
tests/test_guardrails.py::test_runtime_configurable_chain_can_be_extended PASSED
4 passed
```

### Smart Mining: README-First + Domain-Aware

As of this version, mining no longer dumps files alphabetically. Files are serialized in priority order:

1. **README** — the repo's self-description (so the LLM understands context first)
2. **Config files** (pyproject.toml, package.json, etc.) — project structure
3. **Core source** (src/, lib/, top-level modules) — the actual patterns
4. **Tests, docs, examples** — lower priority (may be truncated for large repos)

Additionally, the mining prompt now includes **existing knowledge context** — both from the same repo (dedup) and from semantically similar methodologies across all repos (domain awareness). This tells the LLM "focus on what's NOVEL, not what we already know."

### What This Proves vs. What It Doesn't

**Proves**:
- Full methodology content (description, implementation sketch, solution code, triggers) is injected into the agent's prompt
- The agent receives this as a `## Retrieved Knowledge` section with structured pattern details
- The agent produces working code with passing tests that demonstrates the retrieved patterns
- The knowledge feedback loop is complete: mine → store → retrieve → inject → build → verify → learn
- Mining now uses intelligent file ordering (README-first) and domain-aware context

**Honest limitations**:
- Attribution still uses token overlap (lexical signal, not causal proof)
- Semantic search returns the top 3 most similar methodologies — not all repos appear in every run
- The `Success=1` flag means the task succeeded and methodology was used, but specific causal contribution per line is not tracked
- The agent may have produced similar code without the hints — we cannot A/B test this yet

### Prescreened Ingestion Context

Nine repos ingested via `cam pulse ingest`:
- `0xK3vin/MegaMemory` — 4 methodologies (knowledge graph, embeddings, timeline, merge)
- `heroui-inc/heroui` — 6 methodologies (CSS variables, compound components, deferred value, sub-agents, env validation, URL-state)
- `louislva/claude-peers-mcp` — 6 methodologies (auto-summary, MCP tool schema, non-blocking startup, process liveness, scoped peer discovery, singleton broker)
- `pascalorg/editor` — 9 methodologies (event bus, dirty-node recomputation, scene registry, spatial index, etc.)
- `bytedance/deer-flow` — 9 methodologies (pre-tool guardrails, middleware chain, progressive skill loading, loop detection, sandbox lifecycle, etc.)
- `github/spec-kit` — 10 methodologies (agent registry, preset templates, catalog stack, ZIP path traversal guards, etc.)
- `Kludex/starlette` — 8 methodologies (ASGI middleware, typed lifespan state, route mounting, path convertors, etc.)
- `K-Dense-AI/k-dense-byok` — 0 (model returned null content; handled gracefully)
- `joewinke/jat` — 0 (nothing novel found; legitimate outcome)

## Outputs

```text
tmp/pulse_usage_proof/<RUN_ID>/
  step1_search.txt         -- cam learn search results
  step2_build.txt          -- cam create --execute output
  step3_usage.txt          -- cam learn usage attribution
  step4_changed_files.txt  -- files produced by the build
  summary.md               -- pass/fail per step
```
