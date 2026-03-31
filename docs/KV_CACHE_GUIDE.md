# KV Cache and TurboQuant Guide

**Audience**: CAM operators who want to understand and optimize KV cache compression for local inference.

---

## What KV Cache Is

When a transformer model processes text, it stores intermediate results (keys and values) for every token in every attention layer. This is the "KV cache." For a 7B model at 32K context, the KV cache alone uses 1.8 GB of memory.

KV cache quantization compresses these intermediate results, reducing memory usage at the cost of (usually negligible) quality loss.

---

## Compression Tiers

| Type | Compression | KV Memory (7B, 32K) | KV Memory (7B, 64K) | Quality Loss | Provider |
|------|-------------|---------------------|---------------------|--------------|----------|
| f16 | 1.0x (baseline) | 1,792 MiB | 3,584 MiB | None | Any |
| q8_0 | 2.0x | 896 MiB | 1,792 MiB | Negligible | Ollama |
| q4_0 | 4.0x | 448 MiB | 896 MiB | Small | llama.cpp |
| **turbo3** | **4.9x** | **350 MiB** | **731 MiB** | **Near-zero** | **TurboQuant** |
| turbo4 | 6.0x | 299 MiB | 597 MiB | Near-zero | TurboQuant |

turbo3 is the recommended tier: 80% memory savings vs f16 with near-zero quality loss (Google Research, March 2026).

---

## How Prefix Caching Works

Prefix caching is the mechanism that makes repeated queries fast:

1. CAG builds a **deterministic system message** from the knowledge corpus
2. This message is **byte-identical** across all requests (no timestamps, no UUIDs, no dynamic content)
3. The backend processes this system message once and **caches the KV state**
4. Subsequent requests skip recomputing the system message — only the new user message is processed
5. Result: first request is slow (cold start), all following requests are fast

### Requirements for Prefix Caching

- `keep_alive = -1` in config (prevents model and cache eviction between requests)
- CAG enabled and loaded (`cam cag rebuild` + `[cag] enabled = true`)
- Stable system message (the KVCacheManager ensures this by design)

---

## Config

```toml
[local_llm]
provider = "ollama"                    # or "turboq"
kv_cache_quantization = "q8_0"        # f16 | q8_0 | q4_0 | turbo3 | turbo4
keep_alive = -1                        # -1 = never evict (required for prefix caching)
turboq_binary = "llama-server-turboq"  # Path to turboq binary (only for provider=turboq)
```

---

## A/B Test Results (2026-03-31)

Tested on Apple M4 Pro 64GB with qwen2.5:7b (Q4_K_M, 4.4GB), 4 test prompts with 16K char CAG corpus:

| Metric | Ollama 0.19 (MLX engine) | TurboQuant turbo3 (llama.cpp) |
|--------|--------------------------|-------------------------------|
| Throughput | 44.3 tok/s | 19.2 tok/s |
| Avg latency | 9.3s | 24.4s |
| KV memory (32K) | ~896 MiB (q8_0) | 350 MiB (turbo3) |
| Quality score | 0.83 | 0.71 |
| Compression overhead | N/A | <7% vs f16 baseline |

### Key Finding

The speed difference (44 vs 19 tok/s) is the **inference engine** (Ollama's MLX vs llama.cpp's Metal shaders), **not** the compression. Running turboq with f16 KV cache gave 20.6 tok/s — confirming turbo3 adds less than 7% overhead on the same engine.

**Verdict**: TurboQuant's value is **memory efficiency**, not speed. Use Ollama for speed-first workloads, TurboQuant for memory-constrained scenarios.

Full test report: `/Volumes/WS4TB/turboq/ab_test_report.md`

---

## When to Use Each

| Scenario | Recommended | Why |
|----------|-------------|-----|
| General mining, quick tasks | Ollama q8_0 | 2.3x faster throughput |
| 64K+ context window | TurboQuant turbo3 | 80% less KV memory |
| 13B+ model on 64GB Mac | TurboQuant turbo3 | More headroom for model weights |
| Multi-slot serving (4+ concurrent) | TurboQuant turbo3 | 4 slots x 350 MiB = 1.4 GB vs 4 x 896 MiB = 3.6 GB |
| Maximum memory savings | TurboQuant turbo4 | 6x compression |
| Testing and development | Ollama f16 | No quality loss, fast iteration |

---

## Monitoring

The KV cache manager tracks these metrics at runtime:

| Metric | Description |
|--------|-------------|
| `corpus_chars` | Size of the injected corpus |
| `corpus_tokens_approx` | Estimated token count (~4 chars/token) |
| `corpus_hash` | SHA hash of the corpus (detects when rebuild needed) |
| `requests_sent` | Total requests through the cache |
| `cache_hits_estimated` | Requests where prompt tokens dropped (indicating prefix cache reuse) |
| `hit_rate` | `hits / (requests - 1)` (first request is always cold) |
| `compression_ratio` | KV compression factor (e.g., 4.9x for turbo3) |
| `provider` | Active backend (ollama, turboq, etc.) |

These are logged at startup:

```
KV cache manager enabled: provider=ollama, quant=q8_0 (2.0x), keep_alive=-1, system_msg=16249 chars
```

---

## Memory Planning

Use this table to plan your memory budget:

### 64GB Apple Silicon (M4 Pro/Max)

| Model | Weights | KV (f16, 32K) | KV (turbo3, 32K) | Free (f16) | Free (turbo3) |
|-------|---------|---------------|-------------------|------------|---------------|
| qwen2.5:7b | 4.4 GB | 1.8 GB | 0.35 GB | 57.8 GB | 59.2 GB |
| qwen2.5:7b (64K) | 4.4 GB | 3.6 GB | 0.7 GB | 56.0 GB | 58.9 GB |
| 13B model | ~8 GB | 3.5 GB | 0.7 GB | 52.5 GB | 55.3 GB |
| 13B (64K) | ~8 GB | 7.0 GB | 1.4 GB | 49.0 GB | 54.6 GB |

turbo3 becomes critical for 13B+ models at 64K+ context where f16 KV cache would consume too much memory.

---

## Troubleshooting

### "turbo3 using 4-mag LUT (pre-M5 hardware)"

Normal informational message on M4 Pro. TurboQuant uses a 4-magnitude lookup table on pre-M5 hardware. M5+ will use native tensor operations for even better performance.

### "TurboQuant rotation matrices initialized (128x128)"

Normal message confirming turbo3 KV cache is active for the model's head dimension.

### Speed is much slower than Ollama

Expected behavior. See A/B test results above. The speed gap is the inference engine (MLX vs llama.cpp Metal), not compression overhead.

### KV cache not being reused (hit rate = 0)

Possible causes:
- `keep_alive` is not set to `-1` (model/cache being evicted between requests)
- CAG corpus is empty (no system message prefix to cache)
- System message is changing between requests (should not happen if CAG is properly configured)

### "Out of memory"

Options:
- Reduce `ctx_size` (e.g., 16384 instead of 32768)
- Switch to turbo3 or turbo4 compression
- Use a smaller model
