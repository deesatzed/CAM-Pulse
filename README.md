# CAM-PULSE

### Scans X for new GitHub repos via Grok, mines reusable patterns with LLM, stores them forever, and injects them into your builds — with passing tests and full provenance.

**1,881 tests** | **1,750+ learned patterns** | **8 proven showpieces** | **4 agent backends** | **$0 — MIT licensed**

> **No other tool closes this loop:** discover → mine → store → retrieve → build → verify → attribute

<p align="center">
  <img src="demos/cam-pulse-demo.gif" alt="CAM-PULSE demo: cam mine-self --quick showing language breakdown, domain signals, and test results" width="700">
</p>

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
                    |  SQLite + Vectors  |  1,750+ methodologies with
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
                    |  Verification      |  Real diffs checked. Tests
                    |  & Attribution     |  run. Token overlap tracks
                    +---------+----------+  which pattern → which code
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

Then 9 prescreened repos (bytedance/deer-flow, github/spec-kit, heroui-inc/heroui, Kludex/starlette, pascalorg/editor, and more) added **52 more methodologies** via `cam pulse ingest`.

---

## How It Compares

| | CAM-PULSE | Copilot | Cursor | Windsurf | Aider |
|---|:---:|:---:|:---:|:---:|:---:|
| **Discovers new repos autonomously** | X-Scout via Grok | -- | -- | -- | -- |
| **Persistent cross-session memory** | 1,750+ patterns | -- | Workspace | Session | -- |
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

### Budget Controls (3 Layers)
- **Per-scan**: `max_cost_per_scan_usd = 0.50`
- **Per-day**: `max_cost_per_day_usd = 10.0`
- **Per-agent**: `max_budget_usd` in each agent section

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

**Verified**: Fresh clone → install → 1,881 tests passing in under 12 seconds.

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

For **local-only mode** (Ollama/MLX-LM), no API keys are required.

---

## What You Can Do

### Discover and Learn
```bash
# Scan X for repos developers are sharing
cam pulse scan --keywords "AI agent framework"

# Ingest a specific repo directly
cam pulse ingest https://github.com/bytedance/deer-flow

# Search what CAM has learned
cam learn search "middleware chain" -v -n 10

# View discovery stats
cam pulse status
cam pulse discoveries --limit 20
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
# → 1881 passed, 6 skipped
```

---

## 8 Proven Showpieces

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
  cli.py              # Typer CLI — cam evaluate, mine, create, validate, pulse ...
  miner.py            # 3-pass mining pipeline + _repair_json()
  agents/
    interface.py      # Multi-agent routing via OpenRouter (Claude/Codex/Gemini/Grok)
    cycle.py          # Knowledge injection + build cycle
  pulse/
    scout.py          # X-Scout: xAI Responses API + x_search
    novelty.py        # Embedding-based novelty filter
    orchestrator.py   # Scan orchestration + circuit breaker
    assimilator.py    # Clone → serialize → mine → store pipeline
    models.py         # Pydantic models for PULSE data
  db/
    engine.py         # SQLite + sqlite-vec (WAL mode)
  evolution/
    assimilation.py   # Methodology lifecycle management
  embeddings/
    engine.py         # Gemini API / sentence-transformers / MLX fallback
```

**Database**: SQLite with `sqlite-vec` extension for vector similarity search. WAL mode for concurrent reads. Stores methodologies, embeddings (384-dim), provenance, lifecycle state, usage logs, scan history, and discovery records.

---

## The Validation-First Difference

Most AI coding tools say "I updated the files" and you trust them. CAM doesn't.

- `cam create --execute` checks the **actual workspace diff**. If no files changed, the run is marked **FAILED**.
- `cam validate` runs your acceptance checks (`pytest`, build commands) against the saved spec.
- `cam forge-benchmark` reports "0% lift" when that's the truth — not a dressed-up number.
- Every methodology tracks its lifecycle: `stored → enriched → retrieved → operationalized → proven`
- Infrastructure failures (API timeouts, rate limits) are logged but **never penalize** methodology fitness.

---

## Honest Limits

- `cam create --execute` is gated behind preflight checks — not yet fully autonomous
- Local mode (Ollama/MLX-LM) works but hasn't been battle-tested as deeply as OpenRouter mode
- Code coverage at 79% (target: >90%, action plan in progress)
- Knowledge retrieval quality depends on the diversity of mined repos
- Mined methodologies record source repo URL and discovery date. License-aware mining (pre-mine license detection and compatibility gating) is on the roadmap

---

## Roadmap

| Phase | Status |
|-------|--------|
| **Phase 1**: Core Engine — evaluate, mine, create, validate, benchmark | **Complete** |
| **Phase 2**: Local-First — Docker, Ollama, MLX-LM, torch-free install | **Complete** |
| **Phase 3**: PULSE — X-Scout discovery, multi-pass mining, knowledge injection, attribution | **Complete** |
| **Phase 4**: Enterprise — Sandbox enforcement, audit logs, webhook notifications | Planned |
| **Phase 5**: Premier — Self-evolving maintainer mode, community rollout | Planned |

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
| [Blog: First Live Scan](docs/blog/2026-03-22-pulse-first-live-scan.md) | Full writeup with results |

---

## Development

```bash
# Run tests
pytest tests/ -q
# → 1881 passed, 6 skipped (< 12 seconds)

# CLI help
cam --help
cam pulse --help
cam learn --help
```

---

**License**: MIT

**Created by** [deesatzed](https://github.com/deesatzed)
