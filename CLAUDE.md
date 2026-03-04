# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CLAW (Codebase Learning & Autonomous Workforce) is a multi-model autonomous codebase enhancement system. It coordinates four AI coding agents (Claude Code, Codex, Gemini, Grok) to evaluate, plan, execute, and verify improvements across a fleet of 390+ repositories. The system learns from outcomes to improve routing, prompts, and patterns over time.

**Status:** Pre-implementation (blueprint in `clawpre.md`). No code exists yet — only the architecture document.

**Target runtime:** Mac Mini M4, 64GB RAM (local coordinator) + cloud agent APIs.

## Architecture (The NanoClaw Hierarchy)

The core abstraction is the **Claw Cycle** — a six-step `grab → evaluate → decide → act → verify → learn` loop that operates at four nested scales:

- **Macro Claw** (Fleet) — scans repo fleet, ranks by enhancement potential, allocates budgets
- **Meso Claw** (Project) — runs the 17-prompt evaluation battery on one repo, produces enhancement plan
- **Micro Claw** (Module) — takes one task from the plan, routes to best-fit agent, monitors/verifies
- **Nano Claw** (Self-improvement) — after each task, updates agent scores and routing table

Learning propagates upward: task-level outcomes inform module routing, which informs project planning, which informs fleet scheduling.

## Key Subsystems

| Subsystem | Purpose | Entry Point |
|-----------|---------|-------------|
| **Coordinator** | Async orchestrator (Python 3.12 + asyncio) | `src/claw/cli.py` (typer) |
| **Agent Pool** | Uniform interface to 4 agents via CLI/API | `src/claw/agents/interface.py` (ABC) |
| **Evaluator** | Runs 17-prompt battery (deepdive, driftx, etc.) | `src/claw/evaluator.py` |
| **Dispatcher** | Bayesian agent routing with 10% exploration | `src/claw/dispatcher.py` |
| **Verifier** | claim-gate + tests + regression-scan gate | `src/claw/verifier.py` |
| **Memory System** | 6 typed stores (working, episodic, semantic, procedural, error, meta) | `src/claw/memory/` |
| **Evolution Engine** | Prompt A/B testing, routing optimization, pattern learning | `src/claw/evolution/` |
| **MCP Server** | Exposes CLAW tools to agents mid-task (query memory, request specialist, escalate) | `src/claw/mcp_server.py` |

## Technology Stack

- **Language:** Python 3.12, asyncio throughout
- **CLI:** `typer` + `rich`
- **Database:** SQLite 3.45+ with WAL mode (all memory in one `data/claw.db`)
- **Vector search:** `sqlite-vec` for semantic memory embeddings
- **Agent SDKs:** `anthropic`, `openai`, `google-genai`, `xai-sdk`
- **Git operations:** `gitpython`
- **Config:** `pydantic-settings` + TOML (`claw.toml`)
- **MCP:** `mcp` Python SDK

## Agent Integration

Each agent wraps a CLI subprocess or API client behind `AgentInterface` (ABC):

| Agent | Instruction File | Best For | Modes |
|-------|-----------------|----------|-------|
| Claude Code | `CLAUDE.md` | Analysis, docs, architecture, security | CLI, API |
| Codex | `AGENTS.md` | Parallel refactoring, bulk tests, CI/CD | CLI, API, Cloud |
| Gemini | `GEMINI.md` | Full-repo comprehension (1M context), dependency analysis | CLI, API |
| Grok | `.grok/GROK.md` | Fast fixes, web lookup, multi-agent reasoning | CLI, API |

Routing is learned via Bayesian scoring (`agent_scores` table), not hardcoded. The initial routing table in the blueprint is starting priors only.

## Memory System (6 Types)

- **Working** — in-process Python objects for the current cycle; archived after cycle
- **Episodic** — SQLite event log per project/session (90-day detail retention)
- **Semantic** — cross-project patterns + `sqlite-vec` embeddings (confidence-decaying)
- **Procedural** — versioned prompt arsenal with A/B testing and per-agent adaptations
- **Error** — cross-project error KB: error → root cause → verified fix
- **Meta** — agent scores, routing accuracy, throughput, fleet statistics

## Evaluation Battery (17-Prompt Arsenal)

Stored in `prompts/` directory. Executed in six phases:

1. **Orientation** — `project-context`, `workspace-scan`
2. **Deep Analysis** — `deepdive`, `agonyofdefeatures`, `driftx`
3. **Truth Verification** — `claim-gate`, `outcome-audit`, `assumption-registry`
4. **Quality Assessment** — `debt-tracker`, `endUXRedo`, `regression-scan`
5. **Documentation** — `docsRedo`, `handoff`
6. **Remediation Planning** — `app__mitigen`

Additional prompts: `ironclad`, `sotappr`, `ultrathink`, `interview`, `error-reference`, `critique/*`

## Operational Modes

- **Attended** (`--mode attended`) — human approves plan and each diff
- **Supervised** (`--mode supervised --checkin 30m`) — autonomous with periodic pause/summary
- **Autonomous** (`claw fleet-enhance ... --mode autonomous`) — fleet processing with budget caps, enhancement branches only

## Build Commands

Once implementation begins (not yet started):

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the CLI
claw evaluate ./some-repo
claw enhance ./some-repo --mode attended
claw fleet-enhance /path/to/repos/ --mode autonomous

# Run tests
pytest tests/
pytest tests/test_routing.py -k "test_bayesian_update"

# Database is auto-created at data/claw.db on first run
```

## Implementation Phases

Per the blueprint, build order is:

1. **Foundation** — coordinator skeleton + Claude agent + single claw cycle end-to-end
2. **Multi-Agent + Dispatch** — all 4 agents, routing, verification gates
3. **Memory & Learning** — semantic memory, pattern learning, agent scoring, error KB
4. **Self-Improvement + Fleet** — prompt evolution, capability boundaries, fleet mode, MCP server
5. **Polish** — budget system, resilience, documentation, self-evaluation test

## Critical Rules

- **Never commit to main.** All agent work goes to enhancement branches (`claw/enhancement`).
- **Never skip verification.** Every change must pass: claim-gate, tests, regression-scan.
- **10% exploration rate** in routing — always try non-optimal agents to gather data.
- **A/B test before replacing** — prompt mutations run 20-sample A/B tests before activation.
- **Capability boundaries are honest** — when all agents fail, escalate to human, don't hallucinate through it.
- **No mocks, no placeholders, no cached responses** — only real agent calls and real verification.
- **AI model versions are user-selected** — never hardcode model versions; they change weekly. Use OpenRouter for model selection.
- **Token budgets are enforced** — per-task, per-project, per-day hard caps with auto-pause.
