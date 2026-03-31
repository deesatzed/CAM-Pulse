# CAG: Cache-Augmented Generation Guide

**Audience**: CAM operators who want to understand and configure CAG — the vectorless, zero-latency knowledge retrieval system.

---

## What CAG Does

CAG eliminates the query-time embedding computation that RAG requires. Instead:

1. **At build time**: Pre-computes top methodologies (sorted by fitness) into a structured text corpus
2. **At startup**: Injects this corpus into every LLM prompt as a stable system message prefix
3. **At query time**: The backend reuses cached KV state for the system message — only the new user message gets processed

Result: zero-latency knowledge retrieval. No vector search, no embedding API call, no retrieval pipeline at query time.

### CAG vs RAG

| | RAG | CAG |
|---|---|---|
| Query-time embedding | Yes (per query) | No |
| Vector search | Yes (per query) | No |
| Knowledge freshness | Real-time | Rebuilt on demand |
| Setup complexity | High (vector DB, embeddings) | Low (one rebuild command) |
| Latency | Variable (depends on retrieval) | Zero (pre-baked into prompt) |
| Best for | Large, dynamic knowledge bases | Focused, stable knowledge |

---

## How It Works

```
cam cag rebuild
      |
      v
CAGRetriever.build_cache()
      |
      v
Read top-N methodologies (sorted by fitness)
      |
      v
CAGSerializer: standard / pointer / compressed format
      |
      v
Write corpus.txt + meta.json to data/cag_caches/<ganglion>/
      |
      v
At startup: factory.py loads corpus
      |
      v
KVCacheManager.build_system_message() → deterministic, byte-identical prefix
      |
      v
All agents receive: set_cag_corpus() + set_kv_cache_manager()
      |
      v
Staleness hooks fire after any methodology mutation
```

Key files:
- `src/claw/memory/cag_retriever.py` — builds/loads/manages caches
- `src/claw/memory/cag_serializer.py` — converts methodologies to text
- `src/claw/memory/cag_compressor.py` — BART/extractive compression
- `src/claw/memory/cag_staleness.py` — marks cache stale on mutations
- `src/claw/memory/kv_cache_manager.py` — manages KV cache prefix

---

## Enabling CAG

Add to your `claw.toml`:

```toml
[cag]
enabled = true
cache_dir = "data/cag_caches"
max_methodologies_per_cache = 2000    # Top N methodologies by fitness
knowledge_budget_chars = 16000        # ~4K tokens, sweet spot for 7-9B models
token_budget_max = 100000             # Hard ceiling on total context tokens
context_pointer_threshold = 2000      # Solutions > 2000 chars get compact pointer format
shorthand_compression = false         # Set true to enable BART compression at build time
```

Then build the cache:

```bash
.venv/bin/cam cag rebuild
```

**Use this when**: You have mined at least one repo and want all future LLM queries to benefit from your knowledge base.

---

## Commands

### Rebuild the Cache

```bash
.venv/bin/cam cag rebuild
# or for a specific ganglion:
.venv/bin/cam cag rebuild --ganglion medical
```

**Use this when**:
- After mining new repos
- After governance sweeps cull methodologies
- When `cam cag status` shows `stale: true`
- After changing `knowledge_budget_chars` or compression settings

### Check Cache Status

```bash
.venv/bin/cam cag status
```

Shows: loaded (true/false), stale (true/false), methodology_count, corpus_tokens_approx, built_at, pointer_count, shorthand_compression.

**Use this when**: You want to verify CAG is active and up-to-date.

---

## The Compression Stack

CAG uses a 4-layer compression stack. Each layer reduces how much context the LLM must process:

| Layer | What | Config Key | Effect |
|-------|------|------------|--------|
| **L4: Token Budget** | Hard cap on total tokens | `token_budget_max` | Prevents context window overflow |
| **L3: Shorthand** | BART or extractive compression | `shorthand_compression = true` | 2-4x text reduction at build time |
| **L2: Pointers** | Compact references for large solutions | `context_pointer_threshold = 2000` | Solutions > threshold become pointer + summary |
| **L1: KV Cache** | Backend prefix caching | See [KV_CACHE_GUIDE.md](KV_CACHE_GUIDE.md) | 2-5x KV memory reduction |

Layers apply in order: L4 caps total budget, L3 compresses text, L2 replaces large solutions with pointers, L1 compresses the KV state in the backend.

---

## Serialization Formats

### Standard Format (default)

When a methodology's solution is shorter than `context_pointer_threshold`:

```
=== METHODOLOGY <id> ===
DOMAIN: error_handling | TAGS: retry, resilience | LIFECYCLE: thriving | FITNESS: 0.82
PROBLEM: API calls fail intermittently under load
SOLUTION:
def retry_with_backoff(fn, max_retries=3):
    for i in range(max_retries):
        try:
            return fn()
        except Exception:
            time.sleep(2 ** i)
    raise RuntimeError("Max retries exceeded")
NOTES: Works with any callable. Exponential backoff prevents thundering herd.
IO: inputs=[callable, max_retries] outputs=[result]
TRIGGERS: api_failure, network_timeout, rate_limit
===
```

### Pointer Format

When a methodology's solution exceeds `context_pointer_threshold` (e.g., 2000 chars):

```
=== METHODOLOGY <id> ===
DOMAIN: data_processing | TAGS: etl, pipeline | LIFECYCLE: viable | FITNESS: 0.71
PROBLEM: Large CSV files cause memory overflow during transformation
CAPABILITY: data_processing, triggers=[csv_overflow, memory_error], outputs=[streaming_pipeline]
SOLUTION: [POINTER -- 4,521 chars -- ref:methodology#<id>]
===
```

The pointer format saves space by summarizing the capability instead of including the full solution. Agents can request the full content on demand.

### Compressed Format

When `shorthand_compression = true`, solutions between `compress_max_chars` and `context_pointer_threshold` are compressed using BART summarization (or extractive fallback if BART is unavailable).

---

## Knowledge Budget Tuning

| Budget | Approx Tokens | Best For | Notes |
|--------|---------------|----------|-------|
| 8,000 chars | ~2K | Tiny models (<1B), tight context | Marginal knowledge injection |
| **16,000 chars** | **~4K** | **7-9B models (recommended)** | **Sweet spot, A/B tested** |
| 32,000 chars | ~8K | 13B+ models with 32K+ context | Good for large context windows |
| 64,000 chars | ~16K | Large models only | Risk of 25% timeouts on smaller models |

A/B tested result (2026-03-31): 16K chars is optimal for qwen2.5:7b and qwen3.5:9b. 8K was marginal, 64K caused 25% timeouts. Needle-in-haystack retrieval accuracy: 92% within the 16K budget.

---

## Ganglion Federation

Each ganglion (specialized brain) gets its own independent CAG cache.

```bash
# Rebuild the default ganglion
.venv/bin/cam cag rebuild

# Rebuild a specialist ganglion
.venv/bin/cam cag rebuild --ganglion medical
```

Cache location: `data/cag_caches/<ganglion>/`

See [CAM_STANDALONE_INSTANCE_GUIDE.md](CAM_STANDALONE_INSTANCE_GUIDE.md) for full ganglion setup.

---

## Eligible Task Types

CAG corpus is only injected into prompts for these task types (to avoid noise in tasks that don't benefit from knowledge):

- `mining_extraction`
- `bulk_classification`
- `pattern_extraction`
- `code_summarization`
- `mining`
- `novelty_detection`
- `synergy_discovery`

Other task types (e.g., `analysis`, `code_generation`) do not receive CAG injection.

---

## Staleness

CAG cache is automatically marked stale when methodologies change:

- After mining new repos (`cam mine`)
- After governance sweeps
- After capability composition
- After any mutation that affects the knowledge base

Check staleness:

```bash
.venv/bin/cam cag status
# Look for: stale: true
```

Rebuild when stale:

```bash
.venv/bin/cam cag rebuild
```

The staleness hook (`maybe_mark_cag_stale`) is a no-op when `cag.enabled = false`, so there is zero overhead if CAG is disabled.

---

## Cache Files on Disk

```
data/cag_caches/general/
  corpus.txt    # Serialized methodology text (the actual knowledge)
  meta.json     # Metadata: ganglion, methodology_count, built_at, stale,
                #           corpus_tokens_approx, pointer_count, shorthand_compression,
                #           methodology_ids
```

---

## Troubleshooting

### "CAG corpus empty"

**Cause**: Cache never built, or no methodologies in KB.

**Fix**:
```bash
.venv/bin/cam mine /path/to/repos    # Populate KB first
.venv/bin/cam cag rebuild             # Then build cache
```

### "stale: true" persists after rebuild

**Cause**: Another process (mining, governance) mutated methodologies after the rebuild.

**Fix**: Wait for the mutation process to complete, then rebuild again.

### CAG not injected into prompts

**Cause**: Task type not in the eligible list (see above), or `cag.enabled = false`.

### Corpus is too large

**Cause**: `max_methodologies_per_cache` is too high for your model's context window.

**Fix**: Reduce `knowledge_budget_chars` (the budget truncates the corpus at injection time) or reduce `max_methodologies_per_cache`.
