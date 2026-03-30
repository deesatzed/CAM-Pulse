# CAM-PULSE Local MLX Integration: Pragmatic Sequenced Plan

## Context

CAM-PULSE runs all LLM inference via OpenRouter cloud APIs ($5-50/day for heavy mining). We want to assess and build a path to local MLX inference via Atomic-Chat's TurboQuant-enabled engine on Apple Silicon (starting with M4 64GB), with modular architecture that extends to other hardware without destructive changes.

**Sequencing: A -> D (A+C) -> B** — each phase is independently valuable and gates the next.

**Primary target**: Mac Mini/Studio M4, 64GB unified memory
**Design constraint**: Every phase must leave existing cloud paths untouched (additive, not destructive)

---

## Expectations Anchor (Drift Detection)

This section defines what each phase WILL and WILL NOT accomplish. Any claim of completion must be checked against this.

### Phase 1: Hybrid Local Backend
**WILL**: `cam mine` runs offline on M4 64GB via local MLX endpoint at $0 cost. Kelly routing treats local as 5th agent competing on quality. `cam doctor` reports local health. Config-only hardware adaptation. All cloud paths untouched.
**WILL NOT**: Match cloud model quality (expect 20-40% lower quality_score on complex tasks). Provide TurboQuant KV-cache benefits (that's Phase 2). Run headless without standalone mlx-server binary. Support concurrent local inference on 64GB.
**GATE**: If A/B quality_score < 0.40 on local, narrow to bulk/low-judgment tasks only — do not proceed to Phase 2 for core pipeline.

### Phase 2: CAG Retrieval Layer
**WILL**: Precompute top-2000 methodologies as KV cache per ganglion. Vectorless retrieval with perfect grounding. "Mining with full knowledge" for novelty/synergy detection. A/B testable vs HybridSearch.
**WILL NOT**: Fit all 3,092 methodologies on 64GB (top-2000 by fitness). Support dynamic/streaming cache updates (batch rebuild only). Work with cloud-only backends (requires `/slots/` API). Guarantee quality improvement (may hit "lost in the middle" on 7B models).
**GATE**: If A/B shows CAG <= HybridSearch on quality_score, Phase 3 does not proceed.

### Phase 3: Standalone Knowledge Workstation
**WILL**: `cam export` produces self-contained bundle. Atomic-Chat extension loads bundle for air-gapped querying.
**WILL NOT**: Provide continuous learning (frozen snapshot). Be a full standalone product. Work cross-platform (Apple Silicon only).
**GATE**: Only proceeds if Phase 2 CAG demonstrably outperforms HybridSearch AND serialized corpus proves standalone value.

---

## What Already Exists (reuse, don't rebuild)

| Capability | Location | Status |
|------------|----------|--------|
| `execute_local()` — OpenAI-compatible local inference | `src/claw/agents/interface.py:347-459` | Working, tested |
| `AgentMode.LOCAL` enum value | `src/claw/core/models.py:76` | Exists |
| `AgentConfig.local_base_url` field | `src/claw/core/config.py:134` | Exists |
| `mode = "local"` in agent config | `src/claw/core/config.py:128` | Recognized |
| MLX embedding engine | `src/claw/db/embeddings.py:68-98` | Implemented, lazy-loads `mlx-embeddings` |
| `mlx-lm` + `mlx-embeddings` optional deps | `pyproject.toml` | Declared but not default |
| Local provider docs in claw.toml | `claw.toml:399-429` | Documented, commented out |
| Bayesian Kelly routing | `src/claw/evolution/kelly.py` | Working, needs $0-cost handling |
| HybridSearch (vector + FTS5 + deepConf) | `src/claw/memory/hybrid_search.py` | Working, production |
| Dispatcher static routing + fallback | `src/claw/dispatcher.py` | Working, 4 agents |
| Ganglion federation | `claw.toml:367-434` | Working, 3 ganglia |

---

## Phase 1: Hybrid Local Backend (Option A)

**Goal**: CAM-PULSE agent slots can route to a local MLX server (Atomic-Chat, mlx-server, or llama.cpp-turboquant) alongside existing cloud backends. User switches via `claw.toml` config only — no code path changes for cloud users.

### 1A. Backend Abstraction Layer

**What**: Create a `BackendProvider` protocol that normalizes local vs cloud differences so the Dispatcher doesn't care which is which.

**Files to modify**:
- `src/claw/core/config.py` — Add `[local_llm]` config section with fields: `provider` (ollama | mlx-server | atomic-chat | llama-cpp), `base_url`, `model`, `ctx_size`, `kv_cache_type` (f16 | q4_0 | turbo3)
- `src/claw/core/models.py` — No change needed; `AgentMode.LOCAL` already exists
- `src/claw/agents/interface.py` — Enhance `execute_local()` with:
  - Health check that distinguishes provider type from `/v1/models` response
  - Context window awareness (local models have hard limits vs cloud's flex)
  - Graceful fallback: if local unreachable, re-route to cloud via Dispatcher

**Hardware adaptation point**: `ctx_size` in config adapts to RAM — 64GB gets 32768 default, 128GB gets 131072. This is config, not code.

### 1B. Kelly Routing Recalibration

**What**: Fix the degenerate payoff ratio when `avg_cost_usd = 0` for local agents.

**File**: `src/claw/evolution/kelly.py:117-120`

**Current behavior** (line 117-120):
```python
if avg_cost_usd > 0.001 and avg_quality_score > 0.0:
    b = avg_quality_score / avg_cost_usd  # explodes at $0
else:
    b = self.payoff_default  # fallback = 2.0
```

**Fix**: Quality-only payoff for local agents: `b = avg_quality_score * quality_multiplier` where `quality_multiplier` is configurable (default 2.0). Local agents compete on quality, not cost/quality ratio. This preserves the Kelly framework while preventing local agents from dominating purely on cost.

### 1C. Local Embedding Activation

**What**: Wire the existing `_embed_with_mlx()` path so fully offline operation is possible.

**File**: `src/claw/db/embeddings.py` — Already implemented! Just needs:
- `claw.toml` change: `model = "mlx-community/bge-small-en-v1.5"` (or similar 384-dim model)
- Verify dimension compatibility with existing `methodology_embeddings` vec0 table (must remain 384)
- Migration note: switching embeddings model requires re-embedding all methodologies (one-time cost)

### 1D. Task-Type Routing Priors for Local

**What**: Configure which task types are suitable for local models vs which need cloud.

**File**: `src/claw/dispatcher.py` STATIC_ROUTING + `claw.toml [routing.static_priors]`

**Principle**: Local models handle volume tasks (mining extraction, bulk classification, quick fixes). Cloud handles judgment tasks (verification, architecture, security analysis).

```toml
# Example: add a 5th agent slot "local" for high-volume tasks
[agents.local]
enabled = true
mode = "local"
model = "mlx-community/Qwen2.5-7B-Instruct-4bit"
local_base_url = "http://localhost:1337/v1"  # Atomic-Chat
max_concurrent = 1
timeout = 300

[routing.static_priors]
mining_extraction = "local"
bulk_classification = "local"
quick_fix = "local"
analysis = "claude"          # keep cloud for judgment
verification = "claude"      # keep cloud for quality checks
```

### 1E. Validation Gate

- `cam doctor` reports local backend status (reachable, model loaded, ctx_size, kv_cache_type)
- A/B test: run 20 mining tasks through local vs cloud, compare `quality_score` distribution
- All 2,624+ existing tests pass unchanged (local is additive, cloud paths untouched)
- Token tracking logs `$0.00` for local tasks with actual tok/s metrics

### Hardware Modularity (Phase 1)

| Hardware | Config changes only | What works |
|----------|-------------------|------------|
| M4 64GB | `ctx_size=32768`, 7B-8B model | Mining, quick fixes, bulk classification |
| M4 Max 128GB | `ctx_size=131072`, 35B model | All local tasks including complex analysis |
| Linux + CUDA | `provider=llama-cpp`, `base_url=http://gpu-box:8080/v1` | Same code, different endpoint |
| Cloud-only (no local) | `[agents.local] enabled = false` | Zero impact, everything works as before |

---

## Phase 2: CAG Retrieval Layer (Option C -> completes D)

**Gate**: Phase 1 local backend works and A/B shows acceptable quality for mining tasks.

**Goal**: Precompute CAM's methodology corpus into TurboQuant-compressed KV cache. Load it instantly on query so the LLM sees the full knowledge base in context — vectorless, perfect-grounding retrieval.

### 2A. Methodology Serialization Format

**What**: Convert `Methodology` objects to a structured text format optimized for LLM comprehension in KV cache.

**New file**: `src/claw/memory/cag_serializer.py`

**Design**: Each methodology becomes a structured block:
```
=== METHODOLOGY [id] ===
DOMAIN: {domain} | TAGS: {tags} | LIFECYCLE: {state} | FITNESS: {score}
PROBLEM: {problem_description}
SOLUTION: {solution_code[:2000] or pointer}
NOTES: {methodology_notes}
CAPABILITIES: inputs={inputs} outputs={outputs} triggers={triggers}
COMPOSABLE_WITH: {composability interfaces}
===
```

**Ganglion-scoped serialization**: Each ganglion (general, drive-ops, agentic-memory) gets its own serialized document. On a 64GB M4 with 7B model:
- general ganglion: ~1,918 methods x ~500 tokens avg = ~960K tokens (fits in TurboQuant 32K-128K effective context)
- Selective serialization: top-N by fitness score if full corpus exceeds ctx_size

### 2B. CAG Retriever

**New file**: `src/claw/memory/cag_retriever.py`

**What**: A retrieval strategy that sits alongside `HybridSearch`. Instead of vector+FTS5 search, it manages precomputed KV cache state.

**Interface** (matches `HybridSearch` contract):
```python
class CAGRetriever:
    def __init__(self, config: CAGConfig, repo: Repository):
        ...

    async def retrieve(self, query: str, ganglion: str = "general") -> list[HybridSearchResult]:
        """Return results from precomputed KV cache context."""
        # If cache is loaded: return ALL methodologies (they're already in context)
        # If cache is stale: rebuild and return
        # If cache unavailable: fall back to HybridSearch

    async def build_cache(self, ganglion: str = "general"):
        """Serialize methodologies -> prefill -> save KV cache to disk."""

    async def load_cache(self, ganglion: str = "general"):
        """Restore KV cache from disk for instant context."""
```

**Non-standard API handling**: KV cache save/restore uses llama.cpp's `/slots/0/save` and `/slots/0/restore` endpoints — NOT OpenAI standard. The CAGRetriever encapsulates this, so the rest of CAM never touches non-standard APIs.

### 2C. Hybrid Routing: CAG vs HybridSearch

**File**: `src/claw/agents/interface.py` `_resolve_knowledge_source()`

**Strategy**: Not either/or — the Dispatcher chooses based on task type:
- **CAG path** (full knowledge in context): mining, novelty detection, synergy discovery, cross-methodology analysis
- **HybridSearch path** (top-K curated): focused fixes, specific pattern retrieval, when context budget is tight
- **Combined**: HybridSearch selects top-K, those K are loaded from CAG cache (best of both)

**A/B testable** via existing `evolution/prompt_evolver.py` framework.

### 2D. Cache Lifecycle

**Triggers** (5 modules that mutate knowledge base):
- `miner.py` — new methodologies mined -> mark cache stale
- `governance.py` — lifecycle transitions, GC sweeps -> mark cache stale
- `self_consumer.py` — self-consumption -> mark cache stale
- `community/importer.py` — community imports -> mark cache stale
- `memory/lifecycle.py` — fitness changes -> mark cache stale (debounced)

**Implementation**: Simple `data/cag_cache_meta.json` with `{ganglion, last_build_timestamp, methodology_count, stale: bool}`. Cache rebuild is explicit: `cam cag rebuild [--ganglion general]`.

### 2E. Config

```toml
[cag]
enabled = false                           # Opt-in
cache_dir = "data/cag_caches"
auto_rebuild_on_stale = false             # Manual rebuild by default
max_methodologies_per_cache = 2000        # Fit in 64GB with 7B model
serialization_format = "structured_text"  # vs "qa_pairs" (future)
```

### 2F. Validation Gate

- `cam cag status` — show cache age, methodology count, staleness per ganglion
- A/B test: 20 mining tasks with CAG vs HybridSearch vs combined, compare quality_score + novelty detection rate
- "Lost in the middle" test: plant a known methodology deep in the cache, verify retrieval
- Memory profiling: measure actual RSS on M4 64GB with model + cache loaded

### Hardware Modularity (Phase 2)

| Hardware | Effective behavior |
|----------|--------------------|
| M4 64GB | Top-2000 methodologies by fitness in cache, 7B model |
| M4 Max 128GB | Full 3,092+ methodologies, 35B model |
| Cloud GPU (L4) | Full corpus, TurboQuant CUDA path |
| Cloud-only (no local) | CAG disabled, HybridSearch continues as-is |

---

## Phase 3: Standalone Knowledge Workstation (Option B)

**Gate**: Phase 2 CAG retrieval demonstrably outperforms HybridSearch in A/B testing AND the serialized methodology corpus proves valuable as a standalone queryable knowledge base.

**Goal**: Package CAM's knowledge + CAG + local inference as a desktop application for compliance-sensitive markets (defense, healthcare, legal, financial).

### 3A. Architecture Decision: Extension vs New Product

Two viable paths (decide after Phase 2 results):

**Path 1 — Atomic-Chat Extension** (lighter):
- Build a CAM knowledge extension for Atomic-Chat
- Extension loads serialized methodology cache on startup
- Chat interface queries knowledge via precomputed KV context
- Atomic-Chat handles UI, model management, inference
- CAM provides: knowledge export, cache building, serialization

**Path 2 — Standalone Tauri App** (heavier):
- Fork/adapt Atomic-Chat's Tauri shell
- Embed CAM's Python knowledge layer via PyO3 or HTTP subprocess
- Custom UI for knowledge exploration, methodology browsing, search
- Full offline installer with bundled model + cache

**Recommendation**: Path 1 (Extension) — dramatically less scope, leverages Atomic-Chat's existing UI and model management, and validates the market before committing to a full product.

### 3B. Knowledge Export Pipeline

**New CLI command**: `cam export --format cag-bundle --ganglion general --output ./cam-knowledge.bundle`

Produces a self-contained directory:
```
cam-knowledge.bundle/
├── manifest.json          # Ganglion name, methodology count, build date
├── corpus.txt             # Serialized methodologies (from 2A)
├── kv_cache.bin           # Precomputed TurboQuant KV cache (from 2B)
├── metadata.json          # Per-methodology IDs, tags, fitness for UI browsing
└── README.md              # What this is, how to use it
```

### 3C. Atomic-Chat Extension Skeleton

```
extensions/cam-knowledge/
├── package.json
├── src/
│   └── index.ts           # Extension entry point
├── manifest.json          # Extension metadata
└── README.md
```

The extension:
- Registers a "CAM Knowledge" assistant in Atomic-Chat
- On load: reads `cam-knowledge.bundle/manifest.json`
- On first query: loads KV cache via Atomic-Chat's slot restore API
- Subsequent queries: instant grounded responses from cached context
- System prompt: "You have access to {N} software engineering methodologies..."

### 3D. Validation Gate

- Install extension in Atomic-Chat, load a knowledge bundle, verify queries work
- Test air-gapped: disable network, verify full operation
- User test: have someone unfamiliar with CAM query the knowledge base
- Compliance checklist: no network calls, no telemetry, no data exfiltration

---

## Modular Architecture Guarantee (Non-Destructive Build)

Each phase adds files/configs — never modifies the core cloud path:

```
Phase 1 adds:
  src/claw/agents/local_provider.py     (NEW — backend abstraction)
  claw.toml [agents.local]              (NEW section)
  claw.toml [local_llm]                 (NEW section)
  kelly.py quality-payoff branch        (ADDITIVE — new elif, doesn't touch existing)

Phase 2 adds:
  src/claw/memory/cag_serializer.py     (NEW)
  src/claw/memory/cag_retriever.py      (NEW)
  claw.toml [cag]                       (NEW section)
  data/cag_caches/                      (NEW directory)

Phase 3 adds:
  cam export CLI command                (NEW)
  extensions/cam-knowledge/             (NEW — separate repo or directory)
```

**Rollback**: Disable any phase by setting `enabled = false` in the relevant `claw.toml` section. Zero code changes to revert.

---

## Critical Files Reference

| File | Phase | What changes |
|------|-------|-------------|
| `src/claw/core/config.py:119-135` | 1 | Add `LocalLLMConfig`, `CAGConfig` sections |
| `src/claw/agents/interface.py:347-459` | 1 | Enhance `execute_local()` with provider awareness |
| `src/claw/evolution/kelly.py:117-120` | 1 | Quality-payoff branch for $0-cost agents |
| `src/claw/dispatcher.py:35-56` | 1 | Add `local` agent to routing table |
| `src/claw/db/embeddings.py:68-98` | 1 | Already implemented — config activation only |
| `src/claw/memory/cag_serializer.py` | 2 | NEW — methodology-to-text conversion |
| `src/claw/memory/cag_retriever.py` | 2 | NEW — KV cache manage + retrieve |
| `src/claw/agents/interface.py:462-466` | 2 | Extend `_resolve_knowledge_source()` for CAG |
| `claw.toml` | 1+2 | New sections: `[local_llm]`, `[agents.local]`, `[cag]` |

---

## Verification Plan

### Phase 1 Verification
1. Start Atomic-Chat (or mlx-server standalone) with a 7B model
2. Configure `claw.toml` with `[agents.local]` pointing to `localhost:1337/v1`
3. Run `cam doctor` — verify local backend detected, model reported
4. Run `cam mine <test-repo>` with local agent — verify task completes with real output
5. Run `cam mine <test-repo>` with cloud agent — compare quality_score
6. Check `data/token_costs.jsonl` — local entries show $0.00 cost
7. Disable local agent (`enabled = false`), verify all cloud paths work unchanged
8. Run full pytest suite — all 2,624+ tests pass

### Phase 2 Verification
1. Run `cam cag rebuild --ganglion general` — verify cache built to `data/cag_caches/`
2. Run `cam cag status` — verify cache metadata (count, size, freshness)
3. Run 20 mining tasks with CAG retrieval vs HybridSearch — A/B compare
4. Plant a "needle" methodology, query for it via CAG — verify found
5. Check RSS memory on M4 64GB with model + cache — verify fits
6. Run `cam mine <repo>`, verify cache marked stale, rebuild works
7. Run full pytest suite — all tests pass

### Phase 3 Verification
1. Run `cam export --format cag-bundle` — verify bundle directory structure
2. Load bundle in Atomic-Chat extension — verify queries return grounded answers
3. Disconnect network — verify full offline operation
4. Test with user unfamiliar with CAM — verify knowledge is accessible
