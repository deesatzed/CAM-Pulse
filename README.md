# CAM-PULSE

### Scans X for new GitHub repos via Grok, mines reusable patterns with LLM, stores them forever, and injects them into your builds — with passing tests and full provenance.

**2,577 tests** | **1,848 learned methodologies** | **273 source repos** | **11 languages** | **4 agent backends** | **$0 — MIT licensed**

> **No other tool closes this loop:** discover → mine → store → retrieve → build → verify → attribute → learn

<p align="center">
  <img src="demos/cam-pulse-demo.gif" alt="CAM-PULSE demo: cam mine-self --quick showing language breakdown, domain signals, and test results" width="700">
</p>

---

## How CAM Thinks: The Brain Transplant Analogy

Every other AI coding tool is **stateless** — it forgets everything when you close the tab. CAM-PULSE is different. Think of it as a **brain transplant hospital for coding knowledge**:

```
┌─────────────────────────────────────────────────────────────────┐
│  THE CODE (public, on GitHub)                                    │
│  44K lines of Python, 2,577 tests, CLI, prompts, schema         │
│  = the body — same for every CAM instance                        │
├─────────────────────────────────────────────────────────────────┤
│  THE BRAIN (local only, never pushed)                            │
│  data/claw.db — 1,848 methodologies, agent scores,               │
│  task history, 384-dim embeddings, lifecycle states               │
│  = unique to YOUR instance — YOUR learned experience             │
├─────────────────────────────────────────────────────────────────┤
│  THE KEYS (local only)                                           │
│  .env — API keys for OpenRouter, Google, xAI                     │
│  = credentials — never shared                                    │
├─────────────────────────────────────────────────────────────────┤
│  THE CONFIG (public, with your model picks)                      │
│  claw.toml — model choices, thresholds, feature flags            │
│  = personality — how this instance behaves                        │
└─────────────────────────────────────────────────────────────────┘
```

**When you clone CAM from GitHub, you get an empty brain.** Zero methodologies, zero agent scores, zero task history. The schema creates the empty tables on first run.

**This instance's brain has learned from experience:**

| Metric | This Instance | Fresh Clone |
|--------|:------------:|:-----------:|
| Learned methodologies | 1,848 | 0 |
| Source repos mined | 273 | 0 |
| Tasks executed | 1,668 | 0 |
| Lifecycle promotions (embryonic → viable) | 18 | 0 |
| Languages covered | 11 | 0 |
| Agent quality scores | Bayesian-tracked | Uniform prior (0.5) |

**The knowledge evolves through use.** When CAM retrieves a methodology and uses it for a task:
- **Success** → methodology's fitness increases, lifecycle advances (embryonic → viable → thriving)
- **Failure** → fitness decreases, lifecycle may decline, routing shifts to other methodologies
- **Retrieval patterns** → co-retrieval stigmergic links strengthen synergistic knowledge pairs

This is not a static lookup table. The knowledge base is a **living system** that rewards what works and deprioritizes what doesn't.

### Specialist Team: Run Multiple CAM Instances

Why have one generalist brain when you can have a **team of domain experts**?

```
┌──────────────────────────────────────────────────────────────────┐
│  Same Code (GitHub)  →  Multiple Brains (local claw.db each)     │
│                                                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ quantum.db  │  │ webdesign.db│  │ memory.db   │              │
│  │ 200 methods │  │ 150 methods │  │ 180 methods │              │
│  │ python,rust │  │ ts,css,html │  │ python,go   │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
│         └────────────────┼────────────────┘                      │
│                          ▼                                       │
│                 ┌─────────────────┐                              │
│                 │ Brain Manifests │ ← lightweight JSON indexes   │
│                 │ (what I know)   │                              │
│                 └────────┬────────┘                              │
│                          ▼                                       │
│                 ┌─────────────────┐                              │
│                 │   Federation    │ ← cross-query when local     │
│                 │   (read-only)   │   knowledge is sparse        │
│                 └─────────────────┘                              │
└──────────────────────────────────────────────────────────────────┘
```

Each instance generates a **brain manifest** — a compact JSON index summarizing its expertise. When one instance works on a task outside its domain, it reads sibling manifests, scores relevance, and queries the best match via read-only FTS5 search. No data is copied — the sibling's brain stays intact.

**Use cases:**
- **Quantum computing researcher** with a CAM that knows qubits, error correction, and circuit optimization — while also querying a sibling that knows Python packaging patterns
- **Web agency** with separate instances for React/Next.js, accessibility, and backend API design — each specialist deepens its own domain while sharing patterns laterally
- **ML team** with one instance focused on training pipelines and another on deployment/inference — when a task spans both, federation bridges the gap
- **Solo developer** with one general-purpose instance plus a specialized one for your most complex project — switch via `CLAW_DB_PATH=data/myproject.db cam create ...`

```bash
# Generate this instance's brain manifest
cam kb instances manifest

# Register a sibling
cam kb instances add "quantum-physics" /path/to/quantum/data/claw.db \
    --description "Quantum computing, qubits, error correction"

# Test cross-instance retrieval
cam kb instances query "quantum error correction for stabilizer codes"

# List all siblings
cam kb instances list
```

### Community Knowledge Sharing (Coming Soon)

CAM instances will be able to share their brain safely via HuggingFace datasets:

```
cam kb community publish     # Export proven knowledge (7-gate validated)
cam kb community browse      # Preview others' knowledge before importing
cam kb community import      # Pull through 7 validation gates + quarantine
cam kb community approve     # Review quarantined imports before activation
```

The infrastructure is built and tested (44 tests) — imports go through 7 validation gates (schema, field allowlist, content safety, manifest hash, dedup, niche collision, lifecycle reset). All imported knowledge starts as **embryonic** regardless of the source. The community hub HuggingFace dataset will be published when the first wave of users establishes diverse knowledge bases worth sharing.

---

## The Knowledge Loop

This is what makes CAM-PULSE different from every other AI coding tool. It's not a chat wrapper. It's a closed-loop learning system:

```
                          X / Twitter
                              |
                    +---------v----------+
                    |    X-Scout         |  Grok x_search scans for
                    |    (xAI API)       |  GitHub repos developers
                    +---------+----------+  are sharing
                              |
                    +---------v----------+
                    |  Novelty Filter    |  URL dedup + Google Gemini
                    |  (384-dim vectors) |  embedding distance scoring
                    +---------+----------+
                              |
                    +---------v----------+
                    |  3-Pass Mining     |  1. Rule-based domain classify
                    |  Pipeline          |  2. KB overlap assessment
                    |                    |  3. Focused LLM extraction
                    +---------+----------+
                              |
                    +---------v----------+
                    |  SQLite + Vectors  |  1,848 methodologies with
                    |  Knowledge Base    |  provenance, lifecycle state,
                    |  (claw.db)         |  and 384-dim embeddings
                    +---------+----------+
                              |
                    +---------v----------+
                    |  Hybrid Search     |  BM25 text + cosine vector
                    |  & Retrieval       |  similarity, cross-domain
                    +---------+----------+  synergy scoring
                              |
                    +---------v----------+
                    |  Knowledge         |  Full patterns injected as
                    |  Injection         |  ## Retrieved Knowledge in
                    +---------+----------+  agent prompts
                              |
                    +---------v----------+
                    |  Multi-Agent       |  Claude, Codex, Gemini, Grok
                    |  Build             |  via OpenRouter (or Ollama
                    +---------+----------+  / MLX-LM locally)
                              |
                    +---------v----------+
                    |  Verification      |  7 checks + metric gates:
                    |  & Attribution     |  tests, coverage, drift,
                    +---------+----------+  placeholders, claims, style,
                              |             MetricExpectation enforcement
                              |
                     fails?───┘
                       │ yes
                    +---------v----------+
                    |  Inner Correction  |  Workspace restored, agent
                    |  Loop (up to 3x)   |  re-prompted with violations
                    +---------+----------+  + test output as feedback
                              |
                     passes or budget exhausted
                              |
              enough new knowledge accumulated?
                              │ yes
                    +---------v----------+
                    |  Self-Enhancement  |  Clone → enhance copy →
                    |  Pipeline          |  7-gate validation →
                    +---------+----------+  atomic swap + backup
                              |
              repo knowledge going stale?
                              │ yes
                    +---------v----------+
                    |  Freshness Monitor |  ETag caching, significance
                    |  (Phase 1 + 2)     |  scoring, auto re-mine
                    +--------------------+
```

We haven't found another tool that does all of this. Copilot, Cursor, Windsurf, and Aider generate code — but they don't discover new repos, don't remember patterns across sessions, and don't prove which pattern influenced which output.

---

## Proof: Cross-Repo Knowledge Synthesis

CAM retrieved patterns from **3 different mined repos** and synthesized them into one working module:

```
Task: "Build a plugin event system with typed event bus, middleware
       chain, plugin loader with lifecycle hooks, and loop detection."

What happened:
  1. Semantic search retrieved 3 methodologies from 3 repos
  2. Agent built 258 lines of working code across 5 modules
  3. All 5 tests passed
  4. CLI demo runs with visible output

Results:
  Retrieved=3 | Used=3 | Attributed=3 | Quality=0.82
```

| Module | Lines | Pattern Source |
|--------|------:|----------------|
| `event_bus.py` | 71 | Priority ordering + fnmatch wildcards from **pascalorg/editor** |
| `middleware.py` | 56 | Inspect/modify/block chain from **bytedance/deer-flow** |
| `plugin_loader.py` | 56 | Directory discovery + lifecycle hooks from **heroui-inc/heroui** |
| `loop_detector.py` | 22 | Infinite re-emission prevention from **bytedance/deer-flow** |
| `core.py` | 53 | Event dataclass, Plugin protocol, type definitions |

```
$ python -m pytest tests/ -v
tests/test_events.py::test_priority_and_wildcard_delivery_order     PASSED
tests/test_events.py::test_middleware_can_modify_and_block           PASSED
tests/test_events.py::test_loop_detection_prevents_re_emission      PASSED
tests/test_events.py::test_plugin_loader_lifecycle                  PASSED
tests/test_events.py::test_cli_help_version_and_invalid_args        PASSED
5 passed
```

Every module traces back to a specific mined methodology. This isn't code generation — it's **knowledge application with provenance**.

---

## First Live Scan: 16/16 Repos Assimilated

```
$ cam pulse scan --keywords "AI agent framework"

=== PULSE Scan Report ===
  Keywords:     github.com new AI agent repo
  Discovered:   18
  Novel:        16  (2 already known)
  Assimilated:  16
  Failed:       0
  New patterns: 86
  JSON repair:  100%  (every repo's LLM output was malformed; all recovered)
```

| Repo | Patterns | What CAM Learned |
|------|:--------:|------------------|
| `7abar/nastar-protocol` | 8 | On-chain reputation scoring, AI dispute judge, 8-state deal machine |
| `cronusl-1141/ai-company` | 8 | Multi-agent role system, versioned prompt registry, failure alchemy |
| `devwebxyn/securemcp-lite` | 7 | Sliding window rate limiter, protocol error classification |
| `bug-ops/zeph` | 5 | Thompson sampling for agent routing, BM25+cosine hybrid RAG |
| `egeuysall/brain` | 6 | Atomic write pattern, tiered knowledge retrieval |
| + 11 more repos | 52 | Various patterns across middleware, auth, state machines |

Then prescreened repos (bytedance/deer-flow, github/spec-kit, heroui-inc/heroui, Kludex/starlette, pascalorg/editor, claude-peers-mcp, MegaMemory) added **36 more methodologies** via `cam pulse ingest`.

---

## How It Compares

| | CAM-PULSE | Copilot | Cursor | Windsurf | Aider |
|---|:---:|:---:|:---:|:---:|:---:|
| **Discovers new repos autonomously** | X-Scout via Grok | -- | -- | -- | -- |
| **Persistent cross-session memory** | 1,848 methodologies + lifecycle | -- | Workspace | Session | -- |
| **Applies learned knowledge to builds** | Inject + attribute | -- | -- | -- | -- |
| **Verifies diffs actually happened** | Fails if nothing changed | -- | -- | -- | -- |
| **Multi-agent routing** | 4 backends | 1 | 1 | 1 | 1 |
| **Runs 100% local (zero cloud)** | Ollama + MLX-LM | -- | -- | -- | Partial |
| **Reports honest failures** | 0% lift = 0% lift | Silent | Silent | Silent | Partial |
| **Cost** | **Free + MIT** | $19/mo | $20/mo | $0-40/mo | Free + API |

---

## Novel Technology

### Autonomous X-Scout Discovery
CAM-PULSE uses xAI's Responses API with Grok's native `x_search` tool to find GitHub repos that developers are sharing on X/Twitter. No scraping, no RSS — native server-side search through Grok. Results are filtered by semantic novelty (embedding distance via Google's `gemini-embedding-2-preview`, 384 dimensions) so CAM only assimilates what it doesn't already know.

### 3-Pass Mining Pipeline
Repos aren't mined with a single monolithic LLM call. CAM uses three passes:

1. **Domain Classification** (rule-based, zero cost) — Keyword matching across 10 categories to determine what kind of repo this is
2. **Knowledge Overlap Assessment** (embedding search) — Compares against existing knowledge base to find what's novel vs. already known, computes overlap score and suggested focus areas
3. **Focused LLM Extraction** (adaptive budget) — Sends only the novel parts to the LLM with domain-specific directives. Token budget adapts: small repos get 2K, medium 4K, large 6K. README-first file ordering ensures the LLM sees project context before code.

### Multi-Model Architecture
CAM routes tasks to 4 different AI backends through OpenRouter. Each agent slot is independently configurable — swap models weekly as new ones launch without changing code:

```bash
# .env — you pick the models
CAM_MODEL_CLAUDE=anthropic/claude-sonnet-4-6      # Analysis, reasoning
CAM_MODEL_CODEX=openai/gpt-4.1-mini               # Code generation
CAM_MODEL_GEMINI=google/gemini-2.5-flash           # Repo comprehension
CAM_MODEL_GROK=x-ai/grok-4-1-fast-non-reasoning   # Quick fixes, web lookup
```

### Google Gemini Embeddings
All semantic search uses `gemini-embedding-2-preview` (384 dimensions) via Google API. This powers novelty scoring, knowledge retrieval, and cross-domain synergy detection. For local-only mode, CAM falls back to sentence-transformers or MLX embeddings — no cloud needed.

### Self-Healing JSON Parser
LLM mining output is malformed ~75% of the time. CAM's 3-stage `_repair_json()` achieves **100% repair rate**:
1. Strip trailing commas (regex: `,}` and `,]`)
2. Truncation recovery (find last complete `]` bracket)
3. Individual object extraction (character-by-character `{...}` walking)

Without this, 12 out of 16 repos in the first scan would have been lost.

### Knowledge Injection with Attribution
When you run `cam create --execute`, CAM doesn't just generate code from scratch. It:
1. Searches the knowledge base for relevant patterns (hybrid BM25 + cosine)
2. Retrieves full methodology content (implementation sketch, solution code, activation triggers)
3. Injects it into the agent prompt as a `## Retrieved Knowledge` section
4. After the build, traces which patterns influenced which output via token overlap

Proven result: `Retrieved=3 | Used=3 | Attributed=3 | Tests: 5/5 passing`

### Mission Profiles
Focus your CAM instance on a specific domain. Profile-enriched keywords boost relevance:

```toml
[pulse.profile]
name = "agent-memory"
mission = "Discover repos that enhance agent memory, RAG, and knowledge persistence"
domains = ["memory", "RAG", "vector-db", "embeddings"]

[pulse.profile.novelty_bias]
memory = 0.15
RAG = 0.10
```

### Self-Enhancement Pipeline
CAM can improve itself. After mining or PULSE ingestion accumulates enough new knowledge (configurable thresholds: methodology count, novelty score), CAM:

1. **Clones** its own live install (excluding data, caches, evaluation artifacts)
2. **Enhances** the copy using its own multi-agent system with knowledge injection
3. **Validates** through 7 gates: Python syntax → config compatibility → import smoke → DB schema → CLI smoke → full pytest suite → diff summary
4. **Swaps** atomically — renames live to backup, enhanced copy becomes live
5. **Rolls back** automatically if post-swap verification fails

Protected files (`verifier.py`, `factory.py`, `engine.py`, `schema.sql`, `config.py`) require human review even when all gates pass. Cooldown period prevents runaway self-modification.

Proven end-to-end: clone → enhance (1 task, quality 0.97) → all 7 gates PASS → all tests pass on enhanced copy.

### Inner Correction Loop
When verification catches correctable failures (test failures, insufficient coverage, placeholder code), CAM doesn't just log the failure — it retries with full context:

1. **Snapshot** — Full byte-level workspace backup before each attempt (`cycle.py:_snapshot_workspace_content()`)
2. **Verify** — Run all checks (tests, drift, coverage, metric expectations)
3. **Diagnose** — Classify failure: correctable (test failures, placeholders, drift) vs. infrastructure (API timeout, budget)
4. **Restore** — Byte-level workspace rollback to pre-attempt state
5. **Re-prompt** — Agent receives a `## Correction Required` section with specific violations, test output, and failure reasons
6. **Retry** — Up to `max_correction_attempts` (default 3) before learning from the failure

Proven: Run 1 triggered correction 3x (workspace restore + feedback injection working). Run 2 succeeded first attempt: 10/10 tests, drift 0.868, quality 0.76, 2 PULSE patterns injected, lifecycle transition embryonic→viable.

### Metric Expectations Enforcement
The verifier auto-extracts structured metric targets from natural language specs:

- `"greater than 90 percent coverage"` → `MetricExpectation(min_coverage_pct, gte, 90, hard=True)`
- `"at least 20 tests"` → `MetricExpectation(min_test_count, gte, 20, hard=True)`
- Hard expectations block approval; soft expectations generate recommendations

Supported metrics: `min_coverage_pct`, `min_test_count`, `min_files_changed`, `max_files_changed`. Operators: `gte/gt/lte/lt/eq`. Coverage extraction parses `TOTAL` line from `pytest --cov` output.

### HuggingFace Model Repository Mining

**Why this matters:** HuggingFace is where the ML community publishes models, datasets, and spaces — not just weights, but training configs, architecture code, and README documentation that encode design decisions. Without HF integration, CAM was blind to half the AI ecosystem.

**How fast this shipped:** HF mining went from concept to production-tested in 2 days — `hf-mount` FUSE adapter, tiered size classification, fallback to `snapshot_download()`, URL routing (`huggingface.co/` auto-detected), and full test coverage. CAM's own knowledge injection pipeline accelerated the build: retrieved patterns from previously-mined repos informed the adapter architecture.

CAM mines HuggingFace model repos alongside GitHub using `hf-mount` (lazy FUSE filesystem) with automatic fallback to `huggingface_hub.snapshot_download()`. The `HFMountAdapter` classifies repos into 3 tiers to avoid downloading multi-GB weight files:

| Tier | Size | Strategy | What's Mined |
|------|------|----------|-------------|
| **micro** | < 100 MB | Full clone | README, config, code — complete extraction |
| **standard** | 100 MB – 2 GB | Metadata-only | README + config.json via HF Hub API (no weights downloaded) |
| **large** | > 2 GB | Metadata-only | Same API approach, avoids multi-GB weight downloads |

The `hf-mount` integration streams files on-demand over FUSE — CAM reads what it needs without materializing the full repo. Falls back gracefully to `snapshot_download()` when `hf-mount` isn't installed.

```bash
# Ingest a HuggingFace model repo — same command, different URL
cam pulse ingest https://huggingface.co/microsoft/phi-3-mini-4k-instruct
cam pulse ingest https://github.com/bytedance/deer-flow

# Configure in claw.toml:
# [pulse.hf_mount]
# enabled = true
# mount_base = "data/hf_mounts"
# cache_size_bytes = 1073741824  # 1GB per mount
# fallback_to_download = true
```

### Repo Freshness Monitor
Previously-mined repos go stale when they ship major rewrites. CAM detects this automatically:

**Phase 1 — Cheap metadata check** (1 GitHub API call per repo, 0 if ETag-cached):
- `GET /repos/{owner}/{repo}` with `If-None-Match: {stored_etag}` — 304s cost 0 rate limit
- Compare `pushed_at` timestamp against stored value

**Phase 2 — Significance scoring** (only for changed repos):
- Commit count since last mine (`/compare/{stored_sha}...HEAD` → `ahead_by`)
- New releases (`/releases/latest`)
- README changes (`/commits?path=README.md&since=...`)
- Repo size delta (stored `size_at_mine` vs. current)

```
significance = commits * 0.3 + new_release * 0.4 + readme_changed * 0.2 + size_delta * 0.1
```

Only repos with `significance >= 0.4` trigger re-mine. Old methodologies transition to `declining`; new ones are stored normally.

```bash
cam pulse freshness           # Check all tracked repos
cam pulse freshness --verbose # Show significance scores
cam pulse refresh <URL>       # Re-mine a specific repo
cam pulse refresh --all       # Re-mine all stale repos
```

### deepConf 6-Factor Confidence Scoring
Every methodology retrieval gets a confidence score beyond simple cosine similarity:

| Factor | Weight | What It Measures |
|--------|--------|-----------------|
| Cosine similarity | 0.30 | Semantic match to query |
| BM25 text match | 0.20 | Keyword relevance |
| Fitness score | 0.20 | Methodology track record (outcomes, lifecycle state) |
| Freshness | 0.10 | Recency of the methodology |
| Cross-domain synergy | 0.10 | Bonus for applying patterns across domains |
| Source diversity | 0.10 | Bonus for patterns from underrepresented repos |

Configurable via `[deep_conf]` in `claw.toml`. Weights sum to 1.0.

### Co-Retrieval Stigmergic Links
When multiple methodologies are retrieved together and the build succeeds, CAM records stigmergic links between them (`memory/semantic.py:record_co_retrieval_outcome()`). Future retrievals boost co-proven methodology pairs — patterns that work together surface together.

### Safety Mitigations
- **`--dry-run`** on all destructive PULSE commands — preview without executing
- **Auto-backup** before self-enhancement swaps
- **Confirmation prompts** before re-mining (which retires old methodologies)
- **Infrastructure failure isolation** — API timeouts and rate limits never penalize methodology fitness scores
- **Pre-assimilation secret scanning** — TruffleHog (800+ detectors) blocks repos with critical credentials; regex fallback when binary absent

### Budget Controls (3 Layers)
- **Per-scan**: `max_cost_per_scan_usd = 0.50`
- **Per-day**: `max_cost_per_day_usd = 10.0`
- **Per-agent**: `max_budget_usd` in each agent section

### Multi-Instance Federation
Run multiple specialized CAM instances (quantum physics, web design, agentic memory — whatever domains you work in), each with its own `claw.db` and brain manifest. When one instance encounters a task outside its domain, it automatically queries sibling instances via read-only FTS5 search. No data is mutated in sibling databases.

The system works in three steps:
1. **Manifest generation** — Each instance summarizes its expertise (categories, languages, source repos, lifecycle distribution) into a lightweight JSON manifest
2. **Relevance scoring** — Keyword overlap (60%), language match (20%), and maturity (20%) determine which siblings to query
3. **FTS5 cross-query** — Read-only full-text search against relevant siblings, results tagged with source instance

```toml
# claw.toml
[instances]
enabled = true
instance_name = "general"
instance_description = "General-purpose AI development patterns"

[[instances.siblings]]
name = "quantum-physics"
db_path = "/data/quantum/claw.db"
description = "Quantum computing, qubits, error correction"
```

### Community Knowledge Hub Infrastructure
Full 7-gate validation pipeline for cross-instance knowledge sharing via HuggingFace datasets. Records are packed with provenance metadata, sanitized (API keys stripped, secrets redacted), hashed for integrity, and quarantined until human approval.

The **7 validation gates** (in order):
1. **Schema** — Required fields, format version, instance ID length, text size limit (32KB)
2. **Field allowlist** — Strips unknown metadata keys, redacts remaining secrets
3. **Content safety** — Blocks `exec`, `eval`, `__import__`, `subprocess`, `os.system`, shell injection
4. **Manifest hash** — Recomputes SHA-256 content hash, rejects on mismatch (tamper detection)
5. **Dedup** — Checks against existing knowledge base by content hash
6. **Niche collision** — Soft warning when imported knowledge overlaps existing domain
7. **Lifecycle reset** — Forces embryonic state, zeroes counters, sets project scope (trust must be earned)

### Fitness History Tracking
Every fitness recomputation is logged with its full 6-dimensional vector and trigger event (`outcome_success`, `outcome_failure`, `lifecycle_transition`). This enables analysis of how specific methodologies evolved over time — which ones improved with use and which declined.

### License-Aware Mining
Before mining a repository, CAM detects its license from LICENSE/COPYING files and classifies it as `permissive`, `copyleft`, `unknown`, or `none`. The license type is stored in both `pulse_discoveries` and methodology `capability_data`, so downstream consumers can filter by license compatibility.

### Pre-Assimilation Secret Scanning (TruffleHog + Regex Fallback)
Before any repository enters the mining pipeline, CAM scans it for hardcoded secrets using a two-gate architecture:

**Gate 1 — TruffleHog filesystem scan** (in `assimilator.py`, before `mine_repo()`):
- Runs `trufflehog filesystem <path> --json --no-verification` on the cloned/mounted repo
- CRITICAL findings (private keys, verified credentials, Stripe live keys) → assimilation blocked, status = `blocked_secrets`
- Non-critical findings → logged, assimilation continues with Gate 2 filtering
- Falls back to built-in regex scanner (11 patterns: AWS AKIA, GitHub PAT, Slack tokens, Stripe keys, PEM private keys, GCP service accounts, OpenAI keys, etc.) when TruffleHog is not installed

**Gate 2 — Serializer file filtering** (in `miner.py:serialize_repo()`):
- Files with any secret findings are excluded from the serialized content sent to the LLM
- Prevents leaked credentials from entering methodology `solution_code` or agent prompts

Both GitHub and HuggingFace ingestion paths are protected. Configurable via `[security]` in `claw.toml`:

```toml
[security]
secret_scan_enabled = true
secret_scan_fail_on_critical = true
secret_scan_timeout_seconds = 60
```

```bash
# Manual scan — check any directory
cam security scan /path/to/repo

# Check scanner status
cam security status
```

---

## Quick Start

```bash
git clone https://github.com/deesatzed/CAM-Pulse.git
cd CAM-Pulse
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env    # Fill in your API keys
cam --help
```

**Verified**: Fresh clone → install → 2,577 tests passing. Zero skips with API keys configured.

### Other Install Options

| Method | Command | Notes |
|--------|---------|-------|
| **Lightweight** (no torch) | `pip install -e .` | Uses Gemini API for embeddings |
| **Docker** | `docker compose up --build` | Full containerized deployment |
| **Ollama** (zero cloud) | `pip install -e ".[local]"` | No API keys needed |
| **MLX-LM** (Apple Silicon) | `pip install -e ".[mlx]"` | Native M-series acceleration |

### API Keys

| Key | What For | Get It |
|-----|----------|--------|
| `OPENROUTER_API_KEY` | Multi-agent LLM routing | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `GOOGLE_API_KEY` | Embeddings (gemini-embedding-2-preview) | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `XAI_API_KEY` | X-Scout scanning via Grok | [console.x.ai](https://console.x.ai/) |
| `GITHUB_TOKEN` | Freshness monitor (higher rate limits) | [github.com/settings/tokens](https://github.com/settings/tokens) |
| `HF_TOKEN` | HuggingFace model repo mining | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |

For **local-only mode** (Ollama/MLX-LM), no API keys are required.

---

## What You Can Do

### Discover and Learn
```bash
# Scan X for repos developers are sharing
cam pulse scan --keywords "AI agent framework"

# Ingest a specific repo directly
cam pulse ingest https://github.com/bytedance/deer-flow

# Ingest a HuggingFace model repo (tiered mining: micro/standard/large)
cam pulse ingest https://huggingface.co/microsoft/phi-3-mini-4k-instruct

# Search what CAM has learned
cam learn search "middleware chain" -v -n 10

# View discovery stats
cam pulse status
cam pulse discoveries --limit 20

# Check repo freshness — detect stale knowledge
cam pulse freshness --verbose

# Re-mine repos with significant changes
cam pulse refresh --all
```

### Build with Knowledge
```bash
# Create a new project using learned patterns
cam create /path/to/repo --execute \
  --request "Build a plugin event system with middleware chain" \
  --check "pytest -q"

# Evaluate a repo before modifying it
cam evaluate /path/to/repo --mode quick

# Mine patterns from a folder of repos
cam mine /path/to/repos --max-repos 10 --depth 2
```

### Mine Your Own Code

Most AI tools only learn from the internet. CAM learns from **your own forgotten codebases,
unfinished builds, and archived projects** sitting on your drives.

```bash
# Quick preview: see what CAM finds in your own project (no LLM calls)
cam mine-self --quick

# Full self-mining: extract reusable patterns from your own code
cam mine-self

# Scan multiple directories at once — your entire workspace
cam mine-workspace /Volumes/Projects /Volumes/Archive --scan-only    # preview first
cam mine-workspace /Volumes/Projects /Volumes/Archive --max-repos 15 # mine them

# Search patterns mined from your own code
cam learn search "multiclaw-self"
```

**What makes this different:**
- **`mine-workspace`** scans multiple directories, deduplicates across paths (handles symlinks/overlapping roots), and uses higher defaults for workspace-scale scanning
- **`mine-self`** mines the current project and tags findings with `[self]` for filtering
- **`--quick`** mode shows file stats, language breakdown, and domain signals — zero LLM cost
- Cross-path dedup means `project-v1` in `/old/` and `project-v2` in `/new/` collapse to the best version

### Run Perpetual Discovery
```bash
# Start the daemon — scans X every 30 minutes, mines new repos automatically
cam pulse daemon

# Custom interval
cam pulse daemon --interval 15

# View scan history
cam pulse scans
cam pulse report

# Docker swarm deployment with multiple scouts
docker compose -f pulse/docker-compose.pulse.yml up -d
```

### Self-Enhancement
```bash
# Check if enough new knowledge has accumulated to justify self-enhancement
cam self-enhance status

# Run the full pipeline: clone → enhance → validate (7 gates) → swap
cam self-enhance start

# Validate an enhanced copy without swapping
cam self-enhance validate /path/to/enhanced-copy

# Manually swap a validated copy into production
cam self-enhance swap /path/to/enhanced-copy

# Roll back to the most recent backup
cam self-enhance rollback /path/to/backup
```

### Verify and Audit
```bash
# Validate that changes actually happened
cam validate --spec-file data/create_specs/latest.json

# Check methodology trust levels
cam doctor audit --limit 10

# See knowledge lifecycle state
cam learn report --limit 10

# Run the full test suite
pytest tests/ -q
# → 2488 passed, 0 skipped (with API keys configured)

# Scan for secrets before ingestion
cam security scan /path/to/repo
cam security status
```

---

## 12 Proven Showpieces

Not demos. Not mockups. Each has a harness script you can run yourself.

| # | Showpiece | What It Proves |
|---|-----------|----------------|
| 1 | **Repo Upgrade Advisor** | Ranked recommendations with confidence scores from mined knowledge |
| 2 | **medCSS Modernizer** | End-to-end create → validate → postcheck on a real CSS codebase |
| 3 | **Expectation Ladder** | 5-level escalating complexity (health → build → validate → mine → self-improve) |
| 4 | **PULSE Knowledge Loop** | 16/16 repos discovered, cloned, mined, stored. Zero failures. |
| 5 | **Cross-Repo Intelligence** | Semantic search across repos from different domains finding shared patterns |
| 6 | **PULSE Usage Proof** | Retrieved=3, Used=3, Attributed=3 — knowledge applied with full provenance |
| 7 | **Multi-Pass Mining** | 3-pass pipeline: classify → overlap → extract with adaptive token budget |
| 8 | **Plugin Event System** | 3 repos → 1 cohesive module. 258 lines. 5/5 tests. Full attribution chain. |
| 9 | **Inner Correction Loop** | Workspace restore + agent re-prompt with violations. Proven: 3 retries → success on next run. |
| 10 | **Metric Expectations** | Natural language → structured gates. "90% coverage" auto-extracted and enforced. 51 tests. |
| 11 | **Repo Freshness Monitor** | ETag caching + significance scoring. Phase 1 costs 0 rate limit for unchanged repos. |
| 12 | **Pre-Assimilation Secret Scanner** | Two-gate TruffleHog + regex fallback blocks secrets before they reach the LLM. 73 tests. |

Run any showpiece:
```bash
# Example: Plugin Event System (cross-repo synthesis)
./scripts/test_plugin_event_showpiece.sh

# Example: Full reliability pipeline
./scripts/run_cam_reliability_pipeline.sh
```

---

## Architecture

```
src/claw/
  cli.py              # Typer CLI — 80+ commands across 10 subapps (10,300+ lines)
  miner.py            # 3-pass mining pipeline + _repair_json()
  cycle.py            # 4-level orchestration + inner correction loop + federation integration
  verifier.py         # 7 checks + MetricExpectation enforcement (coverage, test count, file count)
  reconstruct.py      # Self-enhancement: clone → enhance → validate → swap
  validation_gate.py  # 7-gate validation (syntax, config, import, DB, CLI, pytest, diff)
  budget.py           # 3-layer budget enforcement (per-scan, per-day, per-agent)
  agents/
    interface.py      # Multi-agent routing via OpenRouter (Claude/Codex/Gemini/Grok)
  pulse/
    scout.py          # X-Scout: xAI Responses API + x_search
    novelty.py        # Embedding-based novelty filter
    orchestrator.py   # Scan orchestration + circuit breaker
    assimilator.py    # Clone → license detect → mine → store pipeline
    freshness.py      # Repo freshness monitor: ETag caching + significance scoring + auto re-mine
    hf_adapter.py     # HuggingFace model repo mining (hf-mount FUSE + fallback)
    pr_bridge.py      # PR-based fleet registration and enhancement queuing
    models.py         # Pydantic models for PULSE data
  security/
    scanner.py        # TruffleHog + regex fallback secret scanner (Gate 1 + Gate 2)
  community/
    manifest.py       # Brain manifest generation + relevance scoring
    federation.py     # Cross-instance FTS5 search with read-only sibling queries
    packer.py         # Export methodologies to JSONL with provenance + hash integrity
    validator.py      # 7-gate import validation (schema, safety, dedup, lifecycle reset)
    importer.py       # Quarantine-first import with approve/reject workflow
    hub.py            # HuggingFace dataset push/pull operations
  memory/
    hybrid_search.py  # BM25 text + cosine vector + deepConf 6-factor confidence scoring
    semantic.py       # Semantic memory, co-retrieval stigmergic links, outcome feedback
    fitness.py        # 6-dimensional fitness scoring + history logging
    lifecycle.py      # Gause competitive exclusion state machine
  db/
    engine.py         # SQLite + sqlite-vec (WAL mode), 15 migrations
  evolution/
    assimilation.py   # Methodology lifecycle management + synergy discovery
    prompt_evolver.py # Bayesian A/B testing + deterministic prompt mutations
```

**Database**: SQLite with `sqlite-vec` extension for vector similarity search. WAL mode for concurrent reads. Stores methodologies, embeddings (384-dim), provenance, lifecycle state, fitness history, community imports, usage logs, scan history, and discovery records. 15 migrations applied automatically.

---

## The Validation-First Difference

Most AI coding tools say "I updated the files" and you trust them. CAM doesn't.

- `cam create --execute` checks the **actual workspace diff**. If no files changed, the run is marked **FAILED**.
- `cam validate` runs your acceptance checks (`pytest`, build commands) against the saved spec.
- **Metric enforcement**: The verifier extracts test count and coverage targets from your spec text ("at least 20 tests", ">90% coverage") and rejects builds that don't meet them. Structured `MetricExpectation` objects support `gte/gt/lte/lt/eq` operators with hard (blocks approval) or soft (recommendation) enforcement.
- **Self-correction**: When verification fails with correctable issues (test failures, insufficient test count, low coverage, placeholder code), the workspace is byte-level restored and the agent is re-prompted with the violations and test output. Up to 3 correction attempts before learning from failure.
- `cam forge-benchmark` reports "0% lift" when that's the truth — not a dressed-up number.
- Every methodology tracks its lifecycle: `stored → enriched → retrieved → operationalized → proven`
- Infrastructure failures (API timeouts, rate limits) are logged but **never penalize** methodology fitness.

---

## Honest Limits

- `cam create --execute` is gated behind preflight checks — not yet fully autonomous
- Local mode (Ollama/MLX-LM) works but hasn't been battle-tested as deeply as OpenRouter mode
- Knowledge retrieval quality depends on the diversity of mined repos
- Mined methodologies record source repo URL, discovery date, and license type (permissive/copyleft/unknown/none)

---

## Roadmap

| Phase | Status |
|-------|--------|
| **Phase 1**: Core Engine — evaluate, mine, create, validate, benchmark | **Complete** |
| **Phase 2**: Local-First — Docker, Ollama, MLX-LM, torch-free install | **Complete** |
| **Phase 3**: PULSE — X-Scout discovery, multi-pass mining, knowledge injection, attribution | **Complete** |
| **Phase 3.5**: Self-Enhancement — Clone → enhance → 7-gate validate → atomic swap | **Complete** |
| **Phase 3.75**: Resilience — Inner correction loop, metric expectations, HF-mount, freshness monitor, deepConf scoring, co-retrieval links, safety mitigations | **Complete** |
| **Phase 3.9**: Knowledge Infrastructure — License-aware mining, A/B knowledge ablation, fitness history, community sharing (7-gate validated), multi-instance federation with brain manifests, pre-assimilation secret scanning (TruffleHog + regex) | **Complete** |
| **Phase 4**: Enterprise — Sandbox enforcement, audit logs, webhook notifications | Planned |
| **Phase 5**: Premier — Community hub launch, fleet-scale self-enhancement, embedding hot-swap | Planned |

---

## Documentation

**Landing page**: [deesatzed.github.io/CAM-Pulse](https://deesatzed.github.io/CAM-Pulse/)

| Doc | Purpose |
|-----|---------|
| [Command Guide](docs/CAM_COMMAND_GUIDE.md) | Every command, every flag |
| [Decision Tree](docs/CAM_COMMAND_DECISION_TREE.md) | Which command to use first |
| [Operator Cheatsheet](docs/CAM_OPERATOR_CHEATSHEET.md) | Quick reference |
| [Proven Capabilities](docs/CAM_PROVEN_CAPABILITIES.md) | Evidence-backed claims |
| [Plugin Event System](docs/CAM_SHOWPIECE_PLUGIN_EVENT_SYSTEM.md) | Cross-repo synthesis proof |
| [PULSE Knowledge Loop](docs/CAM_SHOWPIECE_PULSE_KNOWLEDGE_LOOP.md) | 16/16 scan proof |
| [PULSE Usage Proof](docs/CAM_SHOWPIECE_PULSE_USAGE_PROOF.md) | Knowledge application proof |
| [Standalone Instance Guide](docs/CAM_STANDALONE_INSTANCE_GUIDE.md) | Clone CAM, create a domain specialist |
| [Blog: First Live Scan](docs/blog/2026-03-22-pulse-first-live-scan.md) | Full writeup with results |

---

## Development

```bash
# Run tests (2,577 passing, 0 skipped with API keys)
pytest tests/ -q

# CLI help
cam --help
cam pulse --help
cam learn --help
```

---

**License**: MIT

**Created by** [deesatzed](https://github.com/deesatzed)
