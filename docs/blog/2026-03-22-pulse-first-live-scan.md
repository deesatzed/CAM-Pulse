# PULSE First Live Scan: 16/16 Repos Assimilated, 86 New Methodologies

**Date**: March 22, 2026

---

## The Result

CAM-PULSE ran its first full end-to-end scan today. The numbers:

| Metric | Value |
|---|---|
| Repos discovered on X | 18 |
| Novel (not already known) | 16 |
| Successfully assimilated | **16** |
| Failed | **0** |
| New methodologies stored | **86** |
| JSON repair rate | **100%** |

Every single repo that passed the novelty filter was cloned, serialized, mined via LLM, parsed, and stored in `claw.db` with full provenance. Zero failures.

---

## What Happened

`cam pulse scan` searched X (Twitter) via Grok's `x_search` tool using the keyword `"github.com new AI agent repo"`. The mission profile automatically enriched this with domain terms (`AI`, `agents`, `developer-tools`).

Grok returned 18 GitHub URLs that developers were sharing. The novelty filter scored each one:
- 2 were already in the knowledge base (score 0.0, skipped)
- 16 were novel (score 0.94, passed threshold)

For each novel repo, the assimilation pipeline:
1. Cloned the repo to a temp directory
2. Serialized the source tree (up to 920KB)
3. Sent the serialized code to an LLM via OpenRouter for methodology extraction
4. Parsed the LLM's JSON response (with repair when needed)
5. Stored each methodology with embeddings for future semantic search

---

## The JSON Repair Story

This was the critical fix that made the scan possible. In earlier testing, LLM mining output was malformed ~75% of the time (15 out of 20 repos). The LLM would return JSON with:
- Trailing commas before `}` or `]`
- Truncated arrays (output cut off mid-token)
- Unterminated strings

The `_repair_json()` function handles this with three progressive stages:

1. **Strip trailing commas** — regex removes `,}` and `,]` patterns
2. **Truncation recovery** — finds the last complete `]` bracket and truncates
3. **Individual object extraction** — if all else fails, walks the text character by character extracting complete `{...}` objects

In this scan, **every single repo** triggered the repair path. All 16 were recovered successfully. The most common error was `Expecting ',' delimiter` (15 repos), with one `Unterminated string`.

Before `_repair_json()`: ~25% assimilation rate (3-4 out of 20 repos)
After `_repair_json()`: **100% assimilation rate** (16 out of 16 repos)

---

## The Retryable Discoveries Fix

The first scan attempt actually found 9 repos but assimilated 0. Why? All 9 had failed during an earlier run (API key limit exceeded), and the novelty filter was permanently blocking them.

The bug: `is_already_known()` checked for ANY URL in `pulse_discoveries`, regardless of status. A repo that failed with a 403 error was treated the same as one that was fully assimilated.

The fix: only `status='assimilated'` counts as "known." Failed and discovered repos are retried on the next scan. This is the correct behavior — transient failures (rate limits, network issues, API errors) should not permanently block a discovery.

---

## What CAM Learned

86 new methodologies from 16 repos. Here are some of the patterns CAM now knows:

**From `7abar/nastar-protocol`** (8 methodologies):
- Composite on-chain reputation scoring with multi-signal aggregation
- AI dispute judge pattern: LLM-as-arbitrator with structured verdicts
- 8-state deal state machine with explicit state transitions
- FAQ cache + per-IP rate limiting for LLM chatbots

**From `cronusl-1141/ai-company`** (8 methodologies):
- Structured multi-agent role system with typed capabilities
- Hook-based event bridge between AI tool and UI layer
- Versioned prompt registry with template variables
- Failure alchemy: antibody/vaccine/catalyst pattern for error recovery

**From `devwebxyn/securemcp-lite`** (7 methodologies):
- Sliding window rate limiter with injected clock
- Protocol error classification with typed error codes
- Transport abstraction with symmetric callbacks
- Half-close handling: drain pending requests before shutdown

**From `bug-ops/zeph`** (5 methodologies):
- Thompson sampling for multi-agent Bayesian routing
- Skill-based RAG with BM25+cosine hybrid retrieval
- Adversarial critic agent with 8-dimension review framework

Every methodology is stored with:
- Source repo URL and clone date
- Embedding vector (384 dimensions) for semantic search
- Lifecycle state (all start as `viable`, promoted through enriched/operationalized/proven)
- Domain tags for cross-repo pattern matching

---

## What This Proves

1. **The full PULSE pipeline works end-to-end**: X-Scout discovery -> novelty filter -> clone -> serialize -> mine -> parse -> store
2. **`_repair_json()` is essential**: Without it, 75% of repos would fail silently
3. **Retryable discoveries matter**: Transient API errors should never permanently block knowledge acquisition
4. **CAM gets smarter with every scan**: 86 new patterns from a single scan, searchable via `cam learn search`

---

## Update: Knowledge Application Proven (March 23, 2026)

The follow-up question was: "You proved CAM can discover and store patterns, but does it actually USE them?"

### Prescreened Ingestion: 9 Repos, 52 More Methodologies

Beyond X-Scout discovery, we ingested 9 curated repos via `cam pulse ingest`:

| Repo | Methodologies | Highlights |
|---|---|---|
| `heroui-inc/heroui` | 6 | CSS variables, compound components, deferred value |
| `louislva/claude-peers-mcp` | 6 | Signal-0 liveness, scoped peer discovery, auto-summary |
| `pascalorg/editor` | 9 | Event bus, dirty-node recomputation, spatial index |
| `bytedance/deer-flow` | 9 | Pre-tool guardrails, middleware chain, loop detection |
| `github/spec-kit` | 10 | Agent registry, preset templates, ZIP path guards |
| `Kludex/starlette` | 8 | ASGI middleware, typed lifespan state, route mounting |
| `0xK3vin/MegaMemory` | 4 | Knowledge graph, embeddings, timeline merge |
| `K-Dense-AI/k-dense-byok` | 0 | Null content handled gracefully |
| `joewinke/jat` | 0 | Nothing novel (legitimate) |

### The Proof: Knowledge Injection + Working Code

**Task**: "Build a pre-tool-call guardrail system with pluggable policy checks, a runtime-configurable middleware chain, and loop detection that force-stops repeated tool calls."

**What happened**:
1. `MicroClaw.evaluate()` searched the knowledge base and retrieved 3 methodologies from `bytedance/deer-flow`
2. Full methodology content (implementation sketch, solution code, activation triggers) was injected into the agent prompt as a `## Retrieved Knowledge` section
3. The agent built 157 lines of working code: `GuardrailEngine`, `MiddlewareChain`, `detect_repeated_tool_calls()`
4. All 4 tests passed
5. Attribution: 3 patterns traced to mined source

**Result**: `Retrieved=3 | Used=3 | Attributed=3 | Success=1 | Quality=0.85 | Tests: 4/4 passing`

This closes the loop: **mine -> store -> retrieve -> inject -> build -> verify -> attribute**

### Multi-Pass Mining Pipeline

Mining is no longer a single monolithic LLM call. The new 3-pass approach:

- **Pass 1**: Rule-based domain classification (10 categories, keyword matching, zero cost)
- **Pass 2**: Knowledge overlap assessment (embedding search, identifies what we already know)
- **Pass 3**: Focused LLM mining with domain-specific context and adaptive token budget

README-first file ordering ensures the LLM sees the project's self-description before diving into code.

### Cross-Repo Knowledge Synthesis: Plugin Event System

The strongest proof yet: CAM retrieves patterns from **3 different mined repos** and synthesizes them into one working module.

**Task**: "Build a plugin event system with typed event bus, middleware chain, plugin loader with lifecycle hooks, and loop detection."

**What happened**:
1. Semantic search retrieved 3 methodologies (knowledge compounds across builds)
2. Agent built 258 lines of working code across 5 modules
3. Event bus with priority ordering + wildcards (from `pascalorg/editor` patterns)
4. Middleware chain that inspects/modifies/blocks events (from `bytedance/deer-flow` patterns)
5. Plugin loader with directory discovery + lifecycle hooks (from `heroui-inc/heroui` patterns)
6. Loop detection preventing infinite re-emission cycles (from `bytedance/deer-flow` patterns)
7. All 5 tests passed
8. CLI demo runs with visible output

**Result**: `Retrieved=3 | Used=3 | Attributed=3 | Quality=0.82 | Tests: 5/5 passing`

**Key insight**: Knowledge compounds. Patterns mined from external repos feed into Build A, Build A gets stored, then Build B benefits from both the original patterns and Build A's output. The system gets smarter across generations.

---

## Try It

```bash
# Clone and install
git clone https://github.com/deesatzed/CAM-Pulse.git
cd CAM-Pulse && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Set your keys
cp .env.example .env
# Edit .env with your XAI_API_KEY, OPENROUTER_API_KEY, GOOGLE_API_KEY

# Run a scan
cam pulse scan --keywords "AI agent framework"

# Ingest a specific repo
cam pulse ingest https://github.com/bytedance/deer-flow

# Search what CAM learned
cam learn search "middleware chain" -v -n 10
cam learn search "guardrail pattern" -v -n 10

# Build something using the knowledge
cam create /tmp/my-project --execute --agent claude \
  --request "Build a pre-tool-call guardrail system with pluggable policy checks"
```

---

## Current Test Suite

```text
1881 passed, 6 skipped
```

Includes 133 new tests since Phase 2: multi-pass mining (13), `_repair_json` (12), PULSE discoveries (2), knowledge injection, infrastructure protection, null content handling, and more.
