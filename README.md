# CLAW — Codebase Learning & Autonomous Workforce

CLAW is a multi-model autonomous system that evaluates, plans, executes, and verifies codebase improvements using four AI coding agents. It learns from every outcome to improve routing, prompts, and patterns over time.

Unlike single-agent tools, CLAW orchestrates **Claude Code, Codex, Gemini, and Grok** through a unified pipeline — each agent receives tasks matched to its strengths, verified by an independent audit gate, and scored so routing improves with every run.

```
┌─────────────────────────────────────────────────────────────┐
│                    The Claw Cycle                            │
│                                                             │
│   grab → evaluate → decide → act → verify → learn          │
│                                                             │
│   ┌──────────┐  ┌───────────┐  ┌──────────┐               │
│   │ Evaluator│→ │ Dispatcher │→ │  Agent   │               │
│   │ 17-prompt│  │  Bayesian  │  │  Pool    │               │
│   │ battery  │  │  routing   │  │ 4 agents │               │
│   └──────────┘  └───────────┘  └────┬─────┘               │
│                                      │                      │
│   ┌──────────┐  ┌───────────┐  ┌────▼─────┐               │
│   │ Memory   │← │  Learner  │← │ Verifier │               │
│   │ 7 stores │  │  scores + │  │ 7-check  │               │
│   │          │  │  patterns  │  │ audit    │               │
│   └──────────┘  └───────────┘  └──────────┘               │
└─────────────────────────────────────────────────────────────┘
```

## What Makes CLAW Different

**Multi-model orchestration.** One agent writes tests, another refactors, a third audits security — each routed to what it does best, not what's cheapest or most familiar.

**Learned routing.** CLAW starts with static priors (Claude for analysis, Codex for bulk refactoring, Gemini for full-repo comprehension, Grok for quick fixes) and updates them via Bayesian scoring after every task. After 20+ tasks, routing diverges from the initial table based on real outcomes.

**7-check verification gate.** No agent output ships without passing: dependency jail, style match, chaos resistance, placeholder scan, drift alignment, claim validation, and optional LLM deep review. Failed verification triggers retry with a different agent.

**Cross-project memory.** Successful patterns propagate from project to local scope to global scope. Error patterns are tracked so agents never repeat the same failed approach twice.

**Self-improving prompts.** The prompt evolution engine mutates instructions, runs A/B tests (20-sample minimum), and promotes winning variants. Agents get better instructions over time without manual tuning.

## Quickstart

```bash
# Install
git clone https://github.com/yourusername/multiclaw.git
cd multiclaw
pip install -e ".[dev]"

# Configure (interactive — walks through API keys, models, budgets)
claw setup

# Or set API keys manually
export ANTHROPIC_API_KEY=sk-ant-...
# Optional: export OPENAI_API_KEY=... GOOGLE_API_KEY=... XAI_API_KEY=...

# Evaluate a repository
claw evaluate /path/to/your/repo

# Add specific goals
claw add-goal /path/to/repo -t "Add unit tests for auth module" -d "Write pytest tests for login, logout, token refresh" -p high --type testing

# Run the full pipeline
claw enhance /path/to/repo --mode attended

# View results
claw results
```

## Commands

| Command | Purpose |
|---------|---------|
| `claw setup` | Interactive first-run configuration (API keys, models, budgets per agent) |
| `claw evaluate <repo>` | Structural analysis + 17-prompt evaluation battery |
| `claw enhance <repo>` | Full pipeline: evaluate → plan → dispatch → verify → learn |
| `claw add-goal <repo>` | Manually add a task/goal for an agent to work on |
| `claw results` | View past task outcomes from the database |
| `claw status` | Show system status, agent health, task summary |

### Modes

- **`--mode attended`** — human approves each task result before continuing
- **`--mode supervised`** — autonomous with periodic pause/summary
- **`--mode autonomous`** — fleet processing with budget caps only

## Architecture

### The NanoClaw Hierarchy

CLAW operates at four nested scales, each running the same 6-step cycle:

| Scale | Scope | What It Does |
|-------|-------|-------------|
| **MacroClaw** | Fleet | Scans repo fleet, ranks by enhancement potential, allocates budgets |
| **MesoClaw** | Project | Runs 17-prompt evaluation battery, produces enhancement plan |
| **MicroClaw** | Task | Routes one task to best-fit agent, monitors, verifies |
| **NanoClaw** | Self | Updates agent scores, routing table, prompt variants |

Learning propagates upward: task outcomes inform routing, which informs planning, which informs fleet scheduling.

### Agent Pool

| Agent | Strengths | Modes |
|-------|-----------|-------|
| **Claude Code** | Analysis, documentation, architecture, security review | CLI, API |
| **Codex** | Parallel refactoring, bulk test generation, CI/CD | CLI, API, Cloud |
| **Gemini** | Full-repo comprehension (1M context), dependency analysis | CLI, API |
| **Grok** | Fast fixes, web lookup, multi-agent reasoning | CLI, API |

Routing starts with static priors and evolves via Thompson sampling with 10% exploration.

### Memory System (7 Types)

| Type | Purpose | Storage |
|------|---------|---------|
| **Working** | Current cycle state | In-process Python objects |
| **Episodic** | Session event log | SQLite (90-day retention) |
| **Semantic** | Cross-project patterns | SQLite + sqlite-vec embeddings |
| **Procedural** | Versioned prompt arsenal | SQLite + A/B test tracking |
| **Error** | Cross-project error KB | SQLite (error → root cause → fix) |
| **Meta** | Agent scores, routing accuracy | SQLite (Bayesian Beta distributions) |
| **Hybrid Search** | Vector + text retrieval | sqlite-vec + FTS5 with MMR re-ranking |

### Verification Gate (7 Checks)

Every agent output passes through:

1. **Dependency jail** — no banned packages introduced
2. **Style match** — consistent with existing codebase patterns
3. **Chaos resistance** — handles edge cases, not just happy path
4. **Placeholder scan** — catches TODO, FIXME, NotImplementedError, mock
5. **Drift alignment** — output matches task intent (cosine similarity)
6. **Claim validation** — rejects "production ready" and similar unsupported claims
7. **LLM deep review** — optional second-opinion analysis

Failed verification → retry with different agent + forbidden approach list.

### Evaluation Battery (17 Prompts)

Organized into 6 phases, each dispatched to the best-fit agent:

| Phase | Prompts | Purpose |
|-------|---------|---------|
| Orientation | project-context, workspace-scan | Understand what exists |
| Deep Analysis | deepdive, agonyofdefeatures, driftx | Find everything wrong |
| Truth Verification | claim-gate, outcome-audit, assumption-registry | Separate fact from fiction |
| Quality Assessment | debt-tracker, endUXRedo, regression-scan | Measure quality gaps |
| Documentation | docsRedo, handoff | Audit and fix docs |
| Remediation | app__mitigen | Prioritized fix roadmap |

Additional: ironclad (architecture), sotappr (SOTA comparison), ultrathink (4-perspective), interview (requirements discovery).

## The Showpiece: CLAW Enhances Itself

The definitive test of any autonomous coding system: can it improve its own codebase?

```bash
# CLAW analyzes its own 18,000-line codebase
claw evaluate .

# CLAW plans and executes improvements on itself
claw enhance . --mode attended --max-tasks 5
```

CLAW's own codebase is a real, complex Python project — 58 source files, async throughout, SQLite + vector search, 4 agent integrations, 7 memory systems, an evolution engine, and 1,123 tests. It is exactly the kind of project that takes a human days to audit.

When CLAW runs against itself, it:
- Evaluates its own architecture using the 17-prompt battery
- Identifies gaps (missing tests, documentation drift, security hardening)
- Dispatches tasks to Claude (or other enabled agents)
- Verifies each change against its own test suite
- Records what worked so future runs are smarter

This is not a demo on a toy project. This is a production-grade system recursively improving itself.

## Configuration

All configuration lives in `claw.toml`:

```toml
[agents.claude]
enabled = true
mode = "cli"
api_key_env = "ANTHROPIC_API_KEY"
max_budget_usd = 5.0
# model = "claude-sonnet-4-6"  # User-selected, never hardcoded

[agents.codex]
enabled = false
mode = "cli"
api_key_env = "OPENAI_API_KEY"

[agents.gemini]
enabled = false
mode = "api"
api_key_env = "GOOGLE_API_KEY"

[agents.grok]
enabled = false
mode = "api"
api_key_env = "XAI_API_KEY"

[routing.static_priors]
analysis = "claude"
documentation = "claude"
refactoring = "codex"
bulk_tests = "codex"
dependency_analysis = "gemini"
full_repo_comprehension = "gemini"
quick_fixes = "grok"
web_lookup = "grok"
```

Model versions are **never hardcoded** — they change weekly. Set them via `claw setup` or directly in `claw.toml`.

## Budget Controls

CLAW enforces 4 levels of budget caps to prevent cost spirals:

| Level | Default | Purpose |
|-------|---------|---------|
| Per-task | $5.00 | No single task burns the budget |
| Per-project | $50.00 | Project-level spending limit |
| Per-day | $100.00 | Daily hard cap across all projects |
| Per-agent | $25.00 | No single agent dominates spending |

When any cap is hit, the task is paused (not failed) and the system either routes to a cheaper agent or waits for the next budget window.

## Tech Stack

- **Python 3.12** — asyncio throughout
- **SQLite 3.45+** — WAL mode, single `data/claw.db` for all state
- **sqlite-vec** — 384-dimensional vector search for semantic memory
- **FTS5** — full-text search for hybrid retrieval
- **Typer + Rich** — CLI with live progress, tables, colored output
- **Pydantic v2** — data contracts and config validation
- **Agent SDKs** — anthropic, openai, google-genai, xai (via OpenAI-compatible)

## Project Stats

| Metric | Value |
|--------|-------|
| Source files | 58 Python files |
| Source LOC | 17,935 lines |
| Test files | 22 files |
| Tests | 1,123 passing |
| Coverage | 79% (action plan for gaps) |
| Database tables | 30+ |
| Evaluation prompts | 18 files |
| Memory subsystems | 7 |
| Agent integrations | 4 |

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Run with coverage
pytest tests/ --cov=src/claw

# Lint
ruff check src/ tests/
```

## License

MIT
