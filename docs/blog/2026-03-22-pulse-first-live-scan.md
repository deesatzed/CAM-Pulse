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

## Try It

```bash
# Clone and install
git clone https://github.com/deesatzed/clawamorphosis.git
cd clawamorphosis && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Set your keys
cp .env.example .env
# Edit .env with your XAI_API_KEY and OPENROUTER_API_KEY

# Run a scan
cam pulse scan --keywords "AI agent framework"

# Search what CAM learned
cam learn search "multi-agent routing" -v -n 10
cam learn search "error handling patterns" -v -n 10
```

---

## Current Test Suite

```text
1840 passed, 6 skipped
```

Includes 14 new tests added for `_repair_json` and retryable discoveries.
