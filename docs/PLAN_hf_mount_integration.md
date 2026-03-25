# CAM + hf-mount Integration Plan — Goals, Expectations, Phases

**Date:** 2026-03-25
**Status:** Draft — Awaiting review
**Mandate:** hf-mount integration is required. This plan defines HOW, not WHETHER.
**Hardware Reference:** `/Volumes/WS4TB/Agent_Pidgeon/HF_MOUNT_GUIDE.md` — tested 2026-03-25 on macOS 26.3, M4 64GB

---

## The Core Problem

CAM is a closed-loop knowledge system: mine repos → extract patterns → inject into agents → measure outcomes → improve. Today this loop has three bottlenecks:

1. **Knowledge acquisition is manual** — repos must be explicitly ingested via `cam pulse ingest <url>` or discovered via X-Scout. Once mined, knowledge fossilizes.
2. **Knowledge scope is limited** — only GitHub repos that get cloned. The entire HF ecosystem (models, datasets, tools) is invisible to CAM.
3. **Knowledge quality is static** — embeddings use one model (`gemini-embedding-2-preview`, 384D). Confidence scoring is 2-factor. No domain-specific intelligence.

hf-mount solves all three by giving CAM zero-cost, lazy-loading filesystem access to any HF repository.

---

## What hf-mount Actually Is (Grounded Facts)

| Fact | Evidence |
|------|----------|
| Rust-based FUSE/NFS tool that mounts HF Hub repos as local filesystems | github.com/huggingface/hf-mount |
| v0.0.1 released March 23, 2026 — brand new | HF changelog |
| macOS Apple Silicon supported via NFS backend (zero dependencies) | Native arm64-apple-darwin binaries |
| Installed and working on this machine (M4 64GB) | `HF_MOUNT_GUIDE.md` — verified 2026-03-25 |
| Files lazy-loaded on first read — only bytes touched hit the network | README: "adaptive prefetch" |
| On-disk chunk cache, default ~10 GB | `--cache-size` flag |
| Background polling detects remote changes (default 30s) | `--poll-interval-secs` flag |
| Can pin to specific revision via `--revision <sha>` | CLI flag |
| No Python API — CLI only, wrap with subprocess | No `import hf_mount` exists |
| HF Skills (SKILL.md) is a separate system, not related to hf-mount | Different repos, different purpose |
| `os.walk()` + `open()` + `os.path.getsize()` work on mounted paths | `HF_MOUNT_GUIDE.md` §5 — tested with serialize_repo pattern |
| statvfs fingerprint: `f_blocks=2147483648, f_bavail=2147483648, f_files=1073741824` | `HF_MOUNT_GUIDE.md` §6 — hardcoded in hf-mount, unique |
| `/tmp` → `/private/tmp` symlink on macOS — both work for unmount | `HF_MOUNT_GUIDE.md` §10 |
| HF tokens at `/Volumes/WS4TB/a_aSatzClaw/.envHF` | `HF_MOUNT_GUIDE.md` §2 — workspace-specific |
| Multiple simultaneous mounts work (tested with 2) | `HF_MOUNT_GUIDE.md` §3 |
| Memory impact negligible on 64GB | `HF_MOUNT_GUIDE.md` §10 verified tests |

### Risk: hf-mount is v0.0.1

This is day-3 software. Our integration must:
- **Wrap, not couple** — all hf-mount interaction behind an adapter that can fall back to `huggingface_hub` Python library
- **Pin revisions** — use `--revision <sha>` for deterministic mining
- **Test without hf-mount** — unit tests never require a live mount

### Verified on This Machine (from HF_MOUNT_GUIDE.md)

| Test | Result |
|------|--------|
| Install via curl script on M4 | Passed |
| Mount public repo (NFS, no token) | Passed |
| Mount with HF_ALL_TOKEN | Passed |
| Multiple simultaneous mounts | Passed |
| Lazy file read (config.json) | Passed |
| `os.walk()` + `open()` (serialize_repo pattern) | Passed |
| statvfs fingerprint detection | Passed |
| Device ID detection (st_dev) | Passed |
| PID file tracking | Passed |
| Unmount cleanup | Passed |

---

## Goals

### G1: CAM can mine any HF repository without cloning it
- Mount via `hf-mount start repo <id> <path> --read-only`
- `serialize_repo()` works unchanged against the mount path
- After mining, unmount — zero persistent storage

**Verification:** `cam pulse ingest --hf-repo d4data/biomedical-ner-all` produces methodologies stored in claw.db.

### G2: CAM detects when previously-mined repos (GitHub or HF) have significant changes
- GitHub repos: ETag/304 conditional requests (per freshness monitor plan)
- HF repos: `huggingface_hub` API checks `last_modified` / commit SHA
- Significance scoring prevents re-mining on trivial changes

**Verification:** `cam pulse freshness` shows a table of tracked repos with staleness scores.

### G3: CAM can hot-swap embedding models from HF
- Mount domain-specific embedding models on demand
- `EmbeddingEngine` gains a `model_id` parameter — mount, load, encode, unmount
- OS page cache keeps recently-used models fast
- LEANN-style selective recomputation prevents re-embedding the entire KB on model swap

**Verification:** Switch from default embeddings to a biomedical model for clinical methodology search; measure retrieval quality difference.

### G4: Confidence scoring becomes multi-factor (deepConf)
- Replace 2-factor `_derive_memory_signals()` with 6-factor scoring
- Factors: retrieval_confidence, source_authority (lifecycle state), historical_accuracy (success_rate), novelty_signal, provenance_strength, verification_history
- Conservative minimum gating: suppress results below calibrated threshold

**Verification:** HybridSearch results include per-factor confidence breakdown; low-quality matches are suppressed.

### G5: Context budget enforcement prevents prompt overflow
- Enforce the existing `ExecutionState.token_budget_remaining = 100_000`
- Context pointers for large methodologies: summary + pointer, lazy-load on demand
- Thrash detection: if same methodology loaded/released >2x in a session, pin it

**Verification:** Agent prompts never exceed token budget; large methodologies are summarized with pointers.

### G6: Knowledge stays fresh automatically
- Repo Freshness Monitor (already planned in `docs/PLAN_repo_freshness_monitor.md`)
- hf-mount revision tracking for HF repos
- Stale methodologies transition to `declining`; re-mined repos produce updated replacements

**Verification:** After a tracked repo receives a major update, `cam pulse freshness --auto-refresh` detects the change and updates methodologies.

---

## Expectations (What Success Looks Like)

### For Every Enhancement:

| Expectation | Non-Negotiable? |
|-------------|-----------------|
| All code uses real APIs and data — no mock/placeholder | Yes |
| Each phase is validated before the next begins | Yes |
| Tests written alongside code, targeting 100% of new paths | Yes |
| Full test suite (`pytest tests/ -q`) passes with zero regressions | Yes |
| Config-driven — all new behavior behind feature flags in `claw.toml` | Yes |
| Follows existing patterns (Pydantic config, idempotent migrations, httpx async) | Yes |
| hf-mount interaction wrapped in an adapter (fallback if hf-mount unavailable) | Yes |
| No new external Python dependencies without approval | Yes |

### For the Overall Integration:

| Expectation | Detail |
|-------------|--------|
| Incremental delivery | Each phase produces a working, tested, committable unit |
| hf-mount is optional | CAM works without hf-mount installed — adapter degrades gracefully |
| No architectural sprawl | Reuse existing tables and patterns (Option C spirit) before creating new packages |
| Measurable improvement | After integration, knowledge retrieval should be demonstrably better (more relevant, more current, more confident) |

---

## Phases

### Phase 1: Foundation — hf-mount Adapter + Freshness Monitor

**What:** Build the adapter layer and the repo freshness system.

**Deliverables:**

**1a. `src/claw/pulse/hf_adapter.py` — hf-mount Adapter**

Built on tested Python code from `HF_MOUNT_GUIDE.md` §4 and §6:

```python
# Core functions (async, following CAM's httpx/asyncio patterns):
async def mount_repo(repo_id, mount_path, token=None, revision="main") -> bool
async def unmount(mount_path) -> bool
async def list_mounts() -> list[MountInfo]
def hf_mount_available() -> bool           # from Guide §10
def is_hf_mount(path) -> bool              # statvfs fingerprint from Guide §6
def detect_hf_mount_robust(path) -> bool   # multi-heuristic from Guide §6
```

**Mount detection strategy** (from Guide §6, cheapest first):
1. statvfs fingerprint — syscall, zero cost: `f_blocks==2147483648 and f_bavail==2147483648 and f_files==1073741824`
2. Device ID comparison — `os.stat(path).st_dev != os.stat(parent).st_dev`
3. PID file check — `~/.hf-mount/pids/{encoded_path}.pid`

**Fallback** when hf-mount unavailable: `huggingface_hub.snapshot_download(repo_id, revision=revision)` to a temp directory.

**Token loading**: Read from `/Volumes/WS4TB/a_aSatzClaw/.envHF` (Guide §2) via `hf_token_env` config, not hardcoded.

**Config addition** to `HFMountConfig` in `config.py`:
```python
class HFMountConfig(BaseModel):
    enabled: bool = True
    binary_path: str = "~/.local/bin/hf-mount"
    mount_base: str = "data/hf_mounts"
    cache_size_bytes: int = 1_073_741_824  # 1GB per mount
    cache_dir: str = "/tmp/hf-mount-cache"
    hf_token_env: str = "HF_TOKEN"
    poll_interval_secs: int = 0            # disabled for mining (pin revision)
    mount_timeout_secs: int = 30
    fallback_to_download: bool = True
```

**1b. Repo Freshness Monitor** — as designed in `docs/PLAN_repo_freshness_monitor.md`:
- `FreshnessConfig` in config.py
- Migration 11: freshness columns on `pulse_discoveries`
- `src/claw/pulse/freshness.py` — Phase 1 (ETag/304) + Phase 2 (significance scoring)
- CLI: `cam pulse freshness`, `cam pulse refresh`

**1c. HF repo freshness** — extend freshness monitor to check HF repos via `huggingface_hub` API (`repo_info()` for `last_modified`, `sha`)

**1d. Tests:**
- Adapter: unit tests with subprocess mocking for hf-mount CLI calls
- statvfs detection: unit test with mocked `os.statvfs` return values
- Freshness: real tests against GitHub API (conditional requests)
- Integration (requires hf-mount): marked `@pytest.mark.skipif(not hf_mount_available())`

**Dependencies:** None — this is the base layer.

**Validation gate:** `cam pulse freshness` shows tracked repos with accurate staleness data. Adapter mounts/unmounts an HF repo successfully (manual verification on your machine).

---

### Phase 2: Knowledge Expansion — Mine HF Repos

**What:** CAM can discover and mine HF repositories.

**Key evidence:** `HF_MOUNT_GUIDE.md` §5 proves `serialize_repo()` pattern works unchanged on mounted paths — `os.walk()`, `open()`, `os.path.getsize()` all return expected results. The guide's `serialize_mounted_repo()` function mirrors CAM's `miner.py` exactly.

**Deliverables:**
1. `cam pulse ingest --hf-repo <repo_id>` — mount via adapter, run `serialize_repo()` against mount path, extract methodologies, unmount
2. `RepoScanLedger` extended with `source_kind` field (`github`, `hf_repo`) and `hf_repo_id` for dedup
3. `PulseDiscovery` model extended for HF repos (status tracking, last_mined_sha)
4. HF-specific serialization hints in `serialize_repo()`:
   - Prioritize README.md and model card (same as miner's README-first ordering)
   - Skip binary files (`.bin`, `.safetensors`, `.gguf`, `.onnx`) — these are model weights, not minable text
   - Respect HF directory conventions (`src/`, `examples/`, `tests/`)
   - Conservative `max_file_size=500_000` for mounted paths (Guide §7 recommendation for streaming reads)
5. **Three-tier mining strategy** (from Guide §7):
   - `PHANTOM`: metadata only — skip serialization
   - `MOUNTED`: mine via hf-mount with conservative file size limits
   - `MATERIALIZED`: mine normally (full 900KB budget)
6. Tests: end-to-end ingestion test with a real public HF repo (e.g., `d4data/biomedical-ner-all`)

**Dependencies:** Phase 1 (adapter).

**Validation gate:** `cam pulse ingest --hf-repo d4data/biomedical-ner-all` produces stored methodologies. `cam pulse freshness` shows the HF repo in its tracking table.

---

### Phase 3: Embedding Hot-Swap

**What:** EmbeddingEngine can use domain-specific models from HF.

**Deliverables:**
1. `EmbeddingsConfig` extended with `domain_models: dict[str, str]` — maps domain tags to HF model repo IDs
2. `EmbeddingEngine` gains `encode(text, domain=None)` — if domain specified and model configured, mount the model via adapter, load with sentence-transformers or MLX, encode, cache
3. LEANN-style embedding cache — SQLite table `embedding_cache` (text_hash, model_id, vector, created_at). Selective recomputation: only re-embed when model changes or KB grows >10%
4. Dimension handling — different models produce different dimensions. Cache stores dimension alongside vector. Search normalizes dimensions at query time.
5. Tests: unit tests for cache hit/miss/invalidation. Integration test with a real HF embedding model.

**Dependencies:** Phase 1 (adapter for mounting models).

**Validation gate:** `EmbeddingEngine.encode("clinical text", domain="medical")` uses a mounted biomedical model and returns valid embeddings. Cache prevents redundant computation.

---

### Phase 4: Confidence + Budget Enforcement

**What:** Multi-factor confidence scoring and context budget management.

**Deliverables:**
1. Replace `_derive_memory_signals()` in `hybrid_search.py` with 6-factor deepConf scoring using existing DB fields:
   - `retrieval_confidence`: existing combined_score
   - `source_authority`: lifecycle state (thriving=1.0, viable=0.7, embryonic=0.4)
   - `historical_accuracy`: success_count / max(1, success + failure) from usage stats
   - `novelty_signal`: novelty_score from methodology
   - `provenance_strength`: len(source_repos) normalized
   - `verification_history`: from capability_data enrichment_status
   Conservative minimum gating: suppress results where min(factors) < threshold
2. Enforce `ExecutionState.token_budget_remaining` in `cycle.py` context assembly:
   - Calculate total context size before dispatch
   - Context pointers for large methodologies — using the pattern from `HF_MOUNT_GUIDE.md` §5:
     ```
     [TRUNCATED. Full content: methodology_id#solution_code]
     ```
     For HF-sourced methodologies with active mounts:
     ```
     [TRUNCATED. Full content: hf://repo_id/path/to/file]
     ```
     Pointer resolution: `resolve_pointer()` reads from mount path or DB on demand
   - Track thrash: pin methodologies loaded >2x in same session
3. Tests: deepConf scoring with known inputs. Budget enforcement with oversized context. Pointer resolution (both DB-backed and mount-backed).

**Dependencies:** None (uses existing DB fields), but logically follows Phase 3 for full value.

**Validation gate:** `HybridSearch.search()` returns results with per-factor confidence. Agent prompts respect token budget. Pointers appear for large methodologies.

---

### Phase 5: Freshness Automation + Re-mine

**What:** Close the loop — stale knowledge gets automatically refreshed.

**Deliverables:**
1. `cam pulse freshness --auto-refresh` — check all tracked repos, re-mine those above significance threshold
2. Re-mine flow as designed: mark refreshing → assimilate → compare old vs new methodologies → retire stale → update metadata
3. SHA capture hook in assimilator (store HEAD SHA after clone)
4. Methodology lifecycle integration: old methodologies from refreshed repos transition to `declining` with `superseded_by` link
5. Tests: methodology lifecycle after re-mine. Significance scoring with known inputs. Full re-mine flow with in-memory DB.

**Dependencies:** Phase 1 (freshness monitor), Phase 2 (HF repo mining).

**Validation gate:** A repo that has been updated since last mine triggers re-mine. Old methodologies marked declining. New methodologies stored. Full test suite passes.

---

## What Is NOT In This Plan

| Excluded | Why |
|----------|-----|
| SkillMount public registry | Brainstorm status — schema questions unresolved |
| `skill_compiler/` package | Depends on SkillMount schema decisions |
| Composability graph traversal | Requires skill registry (future) |
| Agent model rotation via hf-mount | High risk — hf-mount v0.0.1, local inference infra not in place |
| Domain-specific eval prompts | Valuable but independent of hf-mount — can be added later |
| AJPack structured mining output | Medium effort, medium impact — candidate for future phase |
| Synthetic golden set generation | Depends on local LLM availability |
| PageIndex synthesis | Lowest priority from NewRagCity analysis |

These are not rejected — they're deferred until this plan's phases are validated and the SkillMount brainstorm resolves its open questions.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation | Status |
|------|-----------|--------|------------|--------|
| hf-mount v0.0.1 has breaking changes | High | Medium | Adapter wraps all interaction; fallback to `huggingface_hub` | Open |
| hf-mount NFS flaky on macOS | ~~Low~~ **Minimal** | High | ~~Test early~~ **Tested 2026-03-25 on M4** — mount/unmount/read all passed (Guide §10) | **De-risked** |
| `serialize_repo()` fails on FUSE/NFS paths | ~~Medium~~ **None** | High | **Verified** — `os.walk()`, `open()`, `getsize()` all work on mounts (Guide §5) | **De-risked** |
| Mount detection unreliable | ~~Medium~~ **None** | Medium | **Verified** — statvfs fingerprint is hardcoded in hf-mount, unique and reliable (Guide §6) | **De-risked** |
| Embedding hot-swap produces incompatible dimensions | Medium | Medium | Store dimension with cached vectors; normalize at query time | Open |
| deepConf factors poorly calibrated initially | Medium | Low | Start with equal weights; tune from `methodology_usage_log` data | Open |
| Freshness GitHub API rate limits | Low | Low | ETag/304 costs 0 for unchanged; `rate_limit_buffer` config | Open |
| Re-mine produces worse methodologies than original | Low | Medium | Compare before retiring; keep old if new scores lower | Open |
| Test suite regression from schema changes | Low | High | Idempotent migrations; all changes additive (new columns, not modified constraints) | Open |
| `/tmp` vs `/private/tmp` path mismatch on macOS | Low | Low | Both work for unmount; adapter normalizes via `os.path.realpath()` (Guide §10) | **De-risked** |
| Stale mount after daemon crash | Low | Medium | PID file cleanup procedure documented in Guide §10; adapter checks PID liveness | Open |

---

## Phase Dependencies (Build Order)

```
Phase 1: Foundation (adapter + freshness)
    |
    ├── Phase 2: Mine HF Repos (needs adapter)
    |       |
    |       └── Phase 5: Auto-refresh (needs freshness + HF mining)
    |
    └── Phase 3: Embedding Hot-Swap (needs adapter)
            |
            └── Phase 4: Confidence + Budget (enhanced by Phase 3, but can build independently)
```

Phases 2 and 3 can run in parallel after Phase 1. Phase 4 can start anytime. Phase 5 requires 1+2.

---

## Appendix: Connection to SkillMount Vision

This plan is the **Option C (BoostClaw) layer** from the SkillMount brainstorm — proving concepts inline with minimal new files. Once validated:

- The hf-mount adapter becomes the substrate for SkillMount's resolver
- deepConf becomes the trust engine for mounted skills
- Embedding hot-swap enables domain-specific skill matching
- Freshness monitor feeds model staleness detection (gain #10)
- Context pointers evolve into SkillMount's lazy skill loading

The path from here to SkillMount is: validate these phases → extract patterns → build the schema → publish the registry. But that's a future plan, not this one.

---

## Appendix: Reference Documents

| Document | Location | Role |
|----------|----------|------|
| **HF_MOUNT_GUIDE.md** | `/Volumes/WS4TB/Agent_Pidgeon/HF_MOUNT_GUIDE.md` | Ground truth for hf-mount behavior on this machine. Tested code patterns for adapter. |
| **PLAN_repo_freshness_monitor.md** | `docs/PLAN_repo_freshness_monitor.md` | Detailed design for GitHub repo freshness (Phase 1b + Phase 5) |
| **SkillMount brainstorm** | `/Users/o2satz/.claude/plans/splendid-roaming-prism.md` | Architectural north star — informs but does not drive this plan |
| **NewRagCity method mapping** | SkillMount brainstorm §NewRagCity | Source for deepConf (Phase 4), LEANN (Phase 3), context pointers (Phase 4), token budget (Phase 4) |

### Key Code from HF_MOUNT_GUIDE.md Used in This Plan

| Guide Section | What It Provides | Used In |
|---------------|-----------------|---------|
| §4 Python Integration | `mount_repo()`, `unmount()`, `list_mounts()`, async variants | Phase 1a adapter |
| §5 CAM Mining | `serialize_mounted_repo()`, `serialize_with_pointers()`, `resolve_pointer()` | Phase 2 mining, Phase 4 context pointers |
| §6 Detection | `is_hf_mount()` (statvfs), `detect_hf_mount_robust()` (multi-heuristic), PID file check | Phase 1a adapter |
| §7 Three-Tier | `MountTier` enum, `classify_tier()`, `mining_strategy()` | Phase 2 mining strategy |
| §8 Config Reference | CLI flags, cache control, polling intervals | Phase 1a `HFMountConfig` |
| §10 Troubleshooting | Error patterns, stale mount recovery, `hf_mount_available()` | Phase 1a graceful degradation |
