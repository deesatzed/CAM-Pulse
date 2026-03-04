# CLAW

**The AI coding agent that proved it works — by rewriting itself.**

CLAW is an 18,000-line Python system. It pointed four AI agents at its own source code, identified 47 improvements, executed them, verified every change against 1,123 tests, and recorded what worked so the next run would be smarter. No human touched the code.

That's the pitch. Here's why it matters.

---

## The Problem Nobody Solved

Every AI coding tool does the same thing: you give it a task, it writes code, you hope it's correct.

**Hope is not engineering.**

Single-agent tools have no verification. They claim the bug is fixed — did they run the tests? They refactored your auth module — did they check they didn't break session handling? They "improved" your API — did they verify the response contracts still match?

Multi-agent orchestrators got closer. CrewAI assigns roles. LangGraph chains steps. AutoGen coordinates conversations. But they all share the same blind spot: **nobody checks the work.**

CLAW checks the work. Every time. With seven independent verification checks. And when verification fails, it doesn't retry with the same agent and the same approach — it routes to a *different* agent with the failed approach on a forbidden list.

## What Makes CLAW Different (Honestly)

Most AI coding tools are wrappers. A prompt template, an API call, and some string parsing. CLAW is 58 Python files of infrastructure that exists for one reason: **make AI agents reliably improve real codebases.**

Here's what that infrastructure does that others don't:

### 1. Learned Routing (Not Hardcoded Assignment)

Other orchestrators assign agents to tasks with static rules. "Claude does analysis. Codex does refactoring." Forever. Regardless of outcomes.

CLAW starts with those priors, then **measures what actually works.** Every task outcome updates a Bayesian scoring model per agent per task type. After 20+ tasks, routing diverges from the starting table based on real data. Thompson sampling with 10% exploration ensures the system keeps discovering — it doesn't just exploit what worked before.

If Claude starts outperforming Codex at refactoring for *your* codebase, CLAW notices and adjusts. Automatically.

### 2. Seven-Check Verification Gate

No agent output reaches your codebase without passing:

| Check | What It Catches |
|-------|----------------|
| **Dependency jail** | Banned/unlicensed packages sneaking in |
| **Style match** | Code that doesn't look like your codebase |
| **Chaos resistance** | Happy-path-only implementations with no error handling |
| **Placeholder scan** | TODO, FIXME, NotImplementedError, mock stubs left behind |
| **Drift alignment** | Output that wandered from the original task intent |
| **Claim validation** | "Production ready" and other unsupported assertions |
| **LLM deep review** | A second AI opinion on correctness and completeness |

**Failed verification doesn't mean "try again."** It means: try a *different agent*, add the failed approach to a forbidden list, and route around the failure. This is how CLAW avoids the retry-loop death spiral that burns API credits in every other tool.

### 3. Cross-Project Memory That Actually Works

Most AI tools are amnesiac. Every session starts from zero. CLAW maintains **seven memory systems:**

- **Working memory** — current task state (discarded after)
- **Episodic memory** — what happened in each session (90-day retention)
- **Semantic memory** — successful patterns as 384-dimensional embeddings, decaying unless reinforced
- **Procedural memory** — versioned prompt templates with A/B test tracking
- **Error KB** — cross-project database mapping errors to root causes to verified fixes
- **Meta memory** — agent performance scores via Bayesian Beta distributions
- **Hybrid search** — vector similarity + full-text search with MMR re-ranking

The first time CLAW encounters a new error pattern, it fumbles. The second time — even in a *different project* — it retrieves the solution and applies it immediately. Patterns that work get reinforced. Patterns that fail get suppressed. This isn't RAG-over-docs. This is learned behavior.

### 4. Self-Improving Prompts

Every agent receives instructions through prompt templates. CLAW's evolution engine:

1. **Mutates** existing prompts (adds constraints, changes structure, sharpens focus)
2. **A/B tests** mutations against the original (20-sample minimum, Bayesian comparison)
3. **Promotes** winners
4. **Retires** losers

The instructions agents receive get better over time without manual tuning. The system discovers what phrasing works best for each agent on each task type.

### 5. Four-Level Budget Enforcement

One stuck task can burn $50 of API credits in a retry loop. CLAW prevents this with hard caps at four levels:

| Level | What It Protects |
|-------|-----------------|
| Per-task | No single task exceeds its budget |
| Per-project | Total project spending stays bounded |
| Per-day | Daily hard cap across everything |
| Per-agent | No single agent dominates spending |

When any cap is hit, the task **pauses** (not fails) and the system either routes to a cheaper agent or waits for the next budget window.

---

## The Showpiece: CLAW Rewrites Itself

The definitive test: point CLAW at its own 18,000-line codebase and say "make it better."

```bash
claw evaluate .          # CLAW analyzes itself
claw enhance . --mode attended   # CLAW improves itself
```

This is not a demo on a TODO app. CLAW's own codebase is:
- 58 Python source files, async throughout
- SQLite with WAL mode + vector search + full-text search
- 4 agent integrations with health monitoring and circuit breakers
- 7 memory systems with embedding-based retrieval
- A prompt evolution engine with Bayesian A/B testing
- 1,123 passing tests

When CLAW runs against itself:
1. The **18-prompt evaluation battery** analyzes its own architecture, detects drift, verifies claims, scans for debt
2. The **Planner** converts findings into prioritized tasks with dependency ordering
3. The **Dispatcher** routes each task to the best-fit agent using learned scores
4. Each agent reads CLAW's own source code and produces changes
5. The **Verifier** runs CLAW's own `pytest` suite against every change
6. The **Learner** records what worked so the next self-improvement cycle is smarter

The recursion is real. CLAW's drift detector compares its own documentation against its own implementation. CLAW's claim validator rejects assertions in its own README that aren't backed by evidence.

---

## How It Compares

| Capability | CLAW | CrewAI | LangGraph | AutoGen | Single-Agent Tools |
|-----------|------|--------|-----------|---------|-------------------|
| Multi-model orchestration | 4 agents (Claude, Codex, Gemini, Grok) | Role-based agents, single LLM | Graph nodes, any LLM | Multi-agent chat | 1 agent |
| Learned routing | Bayesian + Thompson sampling | No | No | No | N/A |
| Independent verification | 7-check gate | No built-in | No built-in | No built-in | Trust the output |
| Cross-project memory | 7 typed stores + vector search | Short-term only | Checkpointers | No | Per-session |
| Prompt evolution | A/B tested mutations | No | No | No | No |
| Budget enforcement | 4-level hard caps | No | No | No | Varies |
| Self-improvement test | Rewrites its own 18K-line codebase | N/A | N/A | N/A | N/A |

---

## Quickstart

```bash
git clone https://github.com/deesatzed/clawamorphosis.git
cd clawamorphosis
pip install -e ".[dev]"

# Interactive setup — walks through API keys, models, budgets per agent
claw setup

# Evaluate any repository
claw evaluate /path/to/your/repo

# Add specific goals
claw add-goal /path/to/repo -t "Add unit tests for auth module" \
  -d "Write pytest tests for login, logout, token refresh" \
  -p high --type testing

# Run the full pipeline
claw enhance /path/to/repo --mode attended

# View results
claw results
```

Only Claude (Anthropic) is required. Codex, Gemini, and Grok are optional — enable any combination via `claw setup`.

## Commands

| Command | What It Does |
|---------|-------------|
| `claw setup` | Interactive configuration: API keys, models, budgets, modes per agent |
| `claw evaluate <repo>` | 18-prompt analysis battery across 6 phases |
| `claw enhance <repo>` | Full pipeline: evaluate, plan, dispatch, verify, learn |
| `claw add-goal <repo>` | Add a manual task/goal for agents to work on |
| `claw results` | View past task outcomes with agent, cost, and verification status |
| `claw status` | System status: agent health, task summary, budget usage |

### Modes

- **`--mode attended`** — you approve each change before it's applied
- **`--mode supervised`** — autonomous with periodic pause and summary
- **`--mode autonomous`** — fleet processing, budget caps are the only guardrail

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     The Claw Cycle                                │
│                                                                  │
│   ┌───────────┐   ┌────────────┐   ┌───────────┐               │
│   │ Evaluator │ → │ Dispatcher │ → │  Agent    │               │
│   │ 18-prompt │   │  Bayesian  │   │  Pool     │               │
│   │ battery   │   │  routing   │   │  4 agents │               │
│   └───────────┘   └────────────┘   └─────┬─────┘               │
│                                           │                      │
│   ┌───────────┐   ┌────────────┐   ┌─────▼─────┐               │
│   │ Memory    │ ← │  Learner   │ ← │ Verifier  │               │
│   │ 7 stores  │   │  scores +  │   │ 7-check   │               │
│   │           │   │  patterns  │   │ audit     │               │
│   └───────────┘   └────────────┘   └───────────┘               │
│                                                                  │
│   grab → evaluate → decide → act → verify → learn → repeat      │
└──────────────────────────────────────────────────────────────────┘
```

This cycle runs at four nested scales:

| Scale | Scope | Purpose |
|-------|-------|---------|
| **MacroClaw** | Fleet | Scan hundreds of repos, rank by potential, allocate budgets |
| **MesoClaw** | Project | Run 18-prompt battery on one repo, produce task plan |
| **MicroClaw** | Task | Route one task to best agent, monitor, verify |
| **NanoClaw** | Self | Update scores, routing, prompt variants after every task |

Learning propagates upward. A task failure informs routing, which informs planning, which informs fleet scheduling.

## Configuration

All configuration in `claw.toml`:

```toml
[agents.claude]
enabled = true
mode = "cli"
api_key_env = "ANTHROPIC_API_KEY"
max_budget_usd = 5.0

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
```

Model versions are **never hardcoded** — they change weekly. Set them via `claw setup` or directly in `claw.toml`.

## Tech Stack

- **Python 3.12** — asyncio throughout, no sync code paths
- **SQLite 3.45+** — WAL mode, single `data/claw.db` for all state
- **sqlite-vec** — 384-dimensional vector search for semantic memory
- **FTS5** — full-text search for hybrid retrieval with MMR re-ranking
- **Typer + Rich** — CLI with live progress, tables, colored output
- **Pydantic v2** — data contracts and config validation
- **Agent SDKs** — anthropic, openai, google-genai, xai (OpenAI-compatible)

## Project

58 source files. 17,935 lines. 1,123 tests. 18 evaluation prompts. 7 memory systems. 4 agent integrations. 30+ database tables. One `pip install`.

## License

MIT
