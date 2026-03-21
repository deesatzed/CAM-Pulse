# Clawamorphosis (CAM) — Codebase Assimilation Machine

**The only Claw variant that ships real, verifiable code changes — because it never trusts its own narration.**

CAM is a multi-agent autonomous codebase engineering system. It inspects, learns from, transforms, and validates entire repositories — then proves what it did with actual workspace diffs, not agent storytelling.

---

## At a Glance

| Metric | Value |
|---|---|
| Automated tests | **1,735 passing**, 6 skipped |
| Agent backends | 4 (Claude, Codex, Gemini, Grok) |
| Execution modes | 5 (CLI, API, Cloud, OpenRouter, **Local**) |
| Knowledge base | 59 MB SQLite, 1,469+ mined methodologies |
| Deployment | `pip install`, Docker, or Ollama local-only |
| Install weight | Full (torch) **or** lightweight (API-only, no torch) |
| Apple Silicon | Native MLX-LM + mlx-embeddings support |
| Proven showpieces | 3 end-to-end (repo upgrade, medCSS modernizer, expectation ladder) |

---

## Why Clawamorphosis Stands Out

Most AI coding agents generate text about code. CAM generates code, then *checks whether it actually worked*.

- **Validation-first architecture** — `cam validate` checks real workspace diffs, build output, and test results against a saved spec. If nothing changed, execution is marked as **failed**. No other Claw variant does this.
- **Persistent cross-repo learning** — `cam mine` extracts reusable patterns into a growing SQLite knowledge base. Unchanged repos are skipped automatically. Knowledge compounds across projects over time.
- **Honest failure by design** — CAM documents its limits explicitly. The benchmark harness reports "0% lift" when the fixture corpus doesn't beat baseline. Preflight gates block execution when must-clarify questions remain unanswered.
- **1,735 automated tests** — Not a toy, not a demo. The test suite covers CLI surface, database operations, mining behavior, spec generation, validation logic, embedding engine, local mode routing, and forge benchmarks.
- **Local-first / zero-cloud option** — Run entirely on your machine with Ollama or MLX-LM. No API keys needed for local mode. Apple Silicon users get native MLX acceleration.

---

## What No Other Claw Does

These are the capabilities that exist in CAM and do not exist in nanobot, ZeroClaw, NemoClaw, NanoClaw, PicoClaw, or any other known Claw variant:

1. **Rejects hallucinated success** — Other agents say "I updated the files." CAM checks the actual diff. If no files changed, the run is explicitly failed. This is not a wrapper — it is a core architectural decision in the execution pipeline.

2. **Learns and remembers across repositories** — `cam mine` builds a persistent methodology database from any folder of repos. Each methodology tracks its lifecycle state (stored, enriched, retrieved, operationalized, proven). `cam learn reassess` reactivates old knowledge when a new task matches.

3. **Preflight contract system** — Before attempting risky execution, `cam preflight` asks the high-value questions, produces a reusable task contract, and blocks unsafe work. Answers persist across reruns.

4. **Namespace-safe execution** — In fixed-mode, CAM rejects agent output that introduces new top-level source namespaces. `--namespace-safe-retry` auto-retries with hardened constraints. This prevents the most common agent drift pattern.

5. **Deterministic standalone benchmarks** — `cam forge-benchmark` runs a repeatable regression harness on fixture data with no external dependencies. The result is a pass/fail with measured lift, not a subjective quality score.

---

## Current Status (March 2026)

- **Phase 1 complete**: SKILL.md wrapper, GitHub issue templates, namespace fix, reliability pipeline
- **Phase 2 complete**: Docker deployment, Ollama/MLX-LM local mode, torch-free lightweight install, 1,735 tests
- Battle-tested locally across 3 end-to-end showpieces
- Not yet fully autonomous — `--execute` mode is gated behind preflight checks
- Coverage at 79% (target: >90%, action plan in progress)

---

## Quick Start

### Option A: Full install (includes ML dependencies)

```bash
git clone https://github.com/deesatzed/clawamorphosis.git
cd clawamorphosis
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Option B: Lightweight install (no torch, API-only embeddings)

```bash
git clone https://github.com/deesatzed/clawamorphosis.git
cd clawamorphosis
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Uses Gemini API for embeddings instead of local sentence-transformers. Requires `GOOGLE_API_KEY`.

### Option C: Docker

```bash
git clone https://github.com/deesatzed/clawamorphosis.git
cd clawamorphosis
docker compose up --build
```

### Option D: Local-only with Ollama (no cloud API keys needed)

```bash
# Terminal 1: start Ollama
ollama serve
ollama pull llama3.2

# Terminal 2: run CAM
pip install -e ".[local]"
cam setup   # select mode=local, point to http://localhost:11434/v1
```

For Apple Silicon with MLX-LM (faster than Ollama on M-series):

```bash
pip install -e ".[mlx]"
mlx_lm.server --model mlx-community/Llama-3.2-3B-Instruct-4bit
# CAM auto-detects MLX-LM at http://localhost:8080/v1
```

### Smoke test

```bash
cam --help
cam govern stats
cam chat
```

What this proves:
- the CLI is installed
- the database can initialize on a fresh clone
- the local runtime is basically healthy
- the conversational front door starts cleanly

Example output from `cam govern stats`:

```text
Memory Governance Stats
  Total methodologies:  1469
  Active (non-dead):    1469
  Quota: 1469/2000 (73.5%)
  DB size: 50.25 MB
  Episodes: 3
```

Your numbers will differ. The point is that the command should complete cleanly and print memory/database stats instead of crashing.

---

## The 7-Step Workflow

CAM operates as a pipeline. Each step produces verifiable artifacts, not just text.

```
inspect → mine → ideate → spec → execute → validate → benchmark
```

1. **Inspect** any repo (local, zip, Git) — `cam evaluate`
2. **Mine** reusable patterns/methodologies into persistent SQLite + vector knowledge — `cam mine`
3. **Ideate** new apps or improvements from stored knowledge — `cam ideate`
4. **Generate** explicit, structured specs (not just prompts) — `cam create`
5. **Execute** changes safely with workspace diff verification — `cam create --execute`
6. **Validate rigorously** against the saved spec — `cam validate`
7. **Export** neutral JSONL knowledge packs for reuse — `cam forge-export`

---

## What Is Novel About CAM

CAM is not just a wrapper around a chat model. The distinctive parts are the workflow and the safety checks around it.

- `mine` turns outside repos into reusable CAM memory instead of one-off notes.
- `ideate` combines stored CAM knowledge with candidate repos to propose new standalone app concepts.
- `create` writes a real creation spec, not just a prompt, so the requested outcome is explicit and reviewable.
- `preflight` examines a requested task before build execution, asks the missing high-value questions, and writes a reusable task contract.
- `validate` checks the created repo against the saved spec and acceptance rules.
- `create --execute` no longer trusts an agent saying "I changed files". CAM now checks the actual workspace diff and marks the run as failed if nothing changed.
- `create` now auto-runs preflight for risky or ambiguous work, blocks unsafe execution when must-clarify questions remain, and lets the operator reuse recorded answers across reruns.
- execution workflows now refuse to pretend they can build when no executable build path exists in the current runtime.
- `chat` provides a guided conversational front door for common workflows instead of forcing the operator to memorize flags.
- `forge-export` lets CAM hand off what it knows as a neutral JSONL knowledge pack, so a standalone app can consume CAM's knowledge without importing CAM itself.
- `mine` can detect extracted source trees even when they are not full `.git` clones, which matters when you are evaluating zip-downloaded repos.
- `mine` now keeps a persistent scan ledger, so unchanged repos are skipped by default and only changed repos are rescanned unless you force a refresh.

The practical result is that CAM is designed to help with real repo work, not just repo discussion.

---

## What CAM Can Do Right Now

Today CAM can:

- evaluate one repo and decide what looks worth improving
- mine a folder of repos and store transferable patterns in CAM memory
- avoid re-spending tokens on unchanged repos that CAM already mined
- report which repos are new, changed, or unchanged before you rescan them
- search and inspect what CAM has already learned
- report where a methodology sits on the learning continuum: stored, enriched, retrieved, operationalized, or proven
- actively reassess old methodologies against a new task and recommend which ones should be reactivated now
- ideate novel app concepts using both stored CAM knowledge and candidate repos
- preflight a task, estimate what it will take, and ask for the missing contract details before execution
- create a spec-backed task for a fixed repo, augmented repo, or new repo
- reuse prior preflight answers so repeated create runs do not start from scratch
- report whether the current runtime actually satisfies CAM's builder expectations
- validate whether a created repo actually changed and whether executable checks passed
- reject `repo-mode fixed` executions that introduce a new top-level source namespace unless explicitly requested
- export CAM knowledge into a standalone knowledge pack
- run a deterministic standalone Forge benchmark on fixture data
- run all 4 agents via Ollama or MLX-LM in local-only mode (no cloud API keys)
- run with zero torch/ML dependencies using Gemini API embeddings
- deploy via Docker with one command

---

## What Has Been Proven, Not Just Claimed

The items below are backed either by direct command runs in this repo or by targeted automated tests.

### Proven by direct command execution

As of March 15, 2026, these commands were run successfully in this repo:

- fresh-clone smoke test path:
  - `.venv/bin/cam --help`
  - `.venv/bin/cam govern stats`
- source-tree scan path:
  - `.venv/bin/cam mine tests/fixtures/embedding_forge --scan-only --depth 3 --max-repos 5`
- standalone benchmark path:
  - `.venv/bin/cam forge-benchmark --max-minutes 1`
- medCSS showpiece execution path (March 17, 2026):
  - `OPENROUTER_API_KEY=... GOOGLE_API_KEY=... ./scripts/test_medcss_modernizer.sh`
  - outcome: create/validate/postcheck all passed in one run (`create=0`, `validate=0`, `postcheck=0`, `Checks run: 6`)
- reliability pipeline path (March 18, 2026):
  - `OPENROUTER_API_KEY=... GOOGLE_API_KEY=... ./scripts/run_cam_reliability_pipeline.sh`
  - outcome: full 1-7 operator workflow (test, mine, reassess, create, validate, showpiece) in one harness

### Proven by automated test suite

Full test suite as of March 21, 2026:

```text
1735 passed, 6 skipped
```

This covers:

- CLI command surface and UX (all commands, flags, error paths)
- Fresh-database bootstrap and migrations
- Source-tree mining behavior (incremental, ledger, dedup)
- Create-spec generation and validation logic
- Rejection of unchanged repo executions
- Standalone Forge regression benchmark
- Resilient JSON parsing for `cam ideate`
- Preflight artifact generation and answer capture
- Auto-preflight and execution gating
- Reusable `--preflight-file` behavior
- Fixed-mode namespace guardrails
- LOCAL mode routing for all 4 agents (health check + execute)
- Torch-free embedding paths (Gemini API + MLX)
- MLX embedding detection and routing
- Workspace executor access control
- Agent config with local_base_url

---

## What CAM Has Explicitly Been Hardened Against

These are important because they are easy places for agent systems to become fake.

- False success reports from agents with no real file changes
  - CAM now detects this and marks the execution as failed.
- Fresh-clone DB bootstrap failures
  - fixed and retested from a clean clone.
- `ideate` crashing on imperfect JSON-like model output
  - parser hardened to recover from raw control characters inside JSON strings.
- Zip-downloaded repo folders being invisible to `mine`
  - CAM can now discover source-tree style repos without `.git` metadata.
- Fixed-mode create drift via new source namespaces
  - CAM now offers `--namespace-safe-retry` on `cam create` to auto-retry once with hardened fixed-mode constraints after a namespace-guard rejection.

---

## Honest Limits

CAM is strong as an operator and orchestrator, but it is not magic.

- `cam create --execute` is safer than before, but it is not yet a guaranteed autonomous app-builder.
- if all configured agents are reasoning-only, CAM now treats create/enhance execution as planning/spec workflows instead of pretending they can write a repo.
- `validate` proves basic correctness against the saved spec and checks; it does not prove product quality by itself.
- `benchmark` is only as strong as the benchmark corpus and metrics you feed it.
- standalone Forge currently has a real benchmark harness, but not yet a proven positive retrieval lift on the fixture corpus. The current best fixture run matches baseline rather than beating it.
- local mode (Ollama/MLX-LM) is functional but new — it has not been battle-tested at the same depth as OpenRouter mode.

That last point matters. CAM is built to fail honestly instead of pretending the benchmark improved when it did not.

---

## Requirements

- Python 3.12+
- `git`
- API access for the models you plan to use (or Ollama/MLX-LM for local-only mode)
- enough local disk for `data/claw.db`

## Install

### Standard (full ML dependencies)

```bash
git clone https://github.com/deesatzed/clawamorphosis.git
cd clawamorphosis
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Lightweight (no torch)

```bash
pip install -e .
```

Uses Gemini API for embeddings. Requires `GOOGLE_API_KEY`.

### With local LLM support

```bash
pip install -e ".[local]"    # Ollama
pip install -e ".[mlx]"      # MLX-LM (Apple Silicon)
```

### Docker

```bash
docker compose up --build
```

Notes:
- if shell activation is unreliable in your environment, you can run CAM directly as `.venv/bin/cam`

## Configure

Use the interactive setup first:

```bash
.venv/bin/cam setup
```

Or export the keys you need before running CAM:

```bash
export OPENROUTER_API_KEY=...
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...
```

For local-only mode, no API keys are required — just a running Ollama or MLX-LM server.

---

## Practical Workflows

### 0. Start with guided chat if you do not want to memorize flags

```bash
.venv/bin/cam chat
```

Example prompt inside chat:

```text
I want to mine the folder ./folderx
```

CAM chat then asks the missing workflow questions, builds the underlying command, and offers to run it.

### 1. Review one repo before touching it

```bash
.venv/bin/cam evaluate /path/to/repo --mode quick
.venv/bin/cam doctor expectations
.venv/bin/cam doctor audit --limit 10
.venv/bin/cam enhance /path/to/repo --dry-run
```

Use this when you want CAM to tell you what it would change before it tries to change anything.
`doctor audit` shows whether CAM's highest-trust methodologies are backed by attributed, expectation-matched evidence or are still relying on legacy/raw-success counters.

For CI or scripts:

```bash
.venv/bin/cam doctor audit --limit 10 --json-out doctor_audit.json --fail-on-flags
```

### 2. Learn from outside repos

```bash
.venv/bin/cam doctor keycheck --for mine --live
.venv/bin/cam mine /path/to/source-repos \
  --target /path/to/target-repo \
  --max-repos 2 \
  --depth 2 \
  --max-minutes 15
```

Use this when you want CAM to extract reusable patterns from outside repos and make that knowledge available to a target project.

By default, `mine` now behaves incrementally:
- unchanged repos are skipped before any model call
- changed repos are rescanned automatically
- `--force-rescan` overrides the ledger and rescans selected repos anyway
- before live mining starts, CAM now validates the required provider keys with tiny real calls unless you explicitly pass `--no-live-keycheck`

To inspect the folder state before mining:

```bash
.venv/bin/cam mine-report /path/to/source-repos --depth 2
```

### 3. Run an expectation-to-reality ladder (increasing complexity)

```bash
OPENROUTER_API_KEY=... GOOGLE_API_KEY=... ./scripts/test_expectation_ladder.sh
```

This staged harness proves CAM behavior across escalating levels:
- health/expectation preflight
- standalone build + validate
- workflow UX build + validate
- mine + reassess transfer quality
- CAM self-improvement contract (and optional guarded self-execution)

Guide:
- [docs/CAM_SHOWPIECE_EXPECTATION_LADDER.md](docs/CAM_SHOWPIECE_EXPECTATION_LADDER.md)

To verify keys/providers before a live run without starting mining:

```bash
.venv/bin/cam doctor keycheck --for mine --live
```

To inspect whether prior methodologies are just stored versus actually becoming useful:

```bash
.venv/bin/cam learn report --limit 10
```

To ask CAM which old methodologies should matter for a new task right now:

```bash
.venv/bin/cam learn reassess --task "repair broken tests with ast-based refactoring" --limit 10
```

### 4. Invent new app ideas from CAM memory plus repo inputs

```bash
.venv/bin/cam ideate /path/to/source-repos \
  --focus "Invent useful standalone apps that build, troubleshoot, or create" \
  --ideas 3 \
  --max-repos 4 \
  --max-minutes 10
```

Use this when you want CAM to propose new product directions, not just summarize repos.

### 5. Create or modify a target repo from that context

```bash
.venv/bin/cam create /path/to/target-repo \
  --repo-mode new \
  --request "Build the app I described" \
  --spec "Must be standalone" \
  --check "pytest -q" \
  --max-minutes 20
```

If you want CAM to attempt execution immediately:

```bash
.venv/bin/cam create /path/to/target-repo \
  --repo-mode new \
  --request "Build the app I described" \
  --check "pytest -q" \
  --execute \
  --max-minutes 20

# for fixed-mode reliability hardening loops
.venv/bin/cam create /path/to/target-repo \
  --repo-mode fixed \
  --request "Improve create+validate reliability" \
  --namespace-safe-retry \
  --execute
```

### 6. Validate the result before trusting it

```bash
.venv/bin/cam validate --spec-file data/create_specs/<spec-file>.json --max-minutes 5
```

This is the line between "the agent said it did it" and "the repo actually matches the requested spec closely enough to pass checks".

### 7. Benchmark only after validation passes

```bash
.venv/bin/cam benchmark --max-minutes 5
```

### 8. Export learned knowledge for a standalone app

```bash
.venv/bin/cam forge-export \
  --out data/cam_knowledge_pack.jsonl \
  --max-methodologies 200 \
  --max-tasks 200 \
  --max-minutes 5
```

---

## Reproducible Example Outputs

### Example: scan-only repo discovery without spending model calls

Command:

```bash
.venv/bin/cam mine tests/fixtures/embedding_forge --scan-only --depth 3 --max-repos 5
```

Observed output:

```text
CLAW Repo Scanner (scan-only)
  Directory: /Users/o2satz/multiclaw/tests/fixtures/embedding_forge
  Depth: 3
  Dedup: True

Scanning for repos...
Discovered Repos (1 total, 1 selected)
...
Summary
  Total discovered: 1
  Selected: 1
  Skipped (dedup): 0
  Will mine: 1

Remove --scan-only to mine these repos.
```

What this proves:
- CAM can discover a source-tree style repo from fixture data
- you can preview repo discovery before spending tokens

### Example: standalone Forge benchmark

Command:

```bash
.venv/bin/cam forge-benchmark --max-minutes 1
```

Observed output:

```text
CAM Forge Benchmark
  Repo: tests/fixtures/embedding_forge/repo
  Note: tests/fixtures/embedding_forge/note.md
  Knowledge pack: tests/fixtures/embedding_forge/knowledge_pack.jsonl
  Out: data/forge_benchmark_fixture
  Time guardrail: 1 minute(s)

Benchmark complete.
  Status: pass
  Docs: 7
  Best lift: 0.00%
  Best config: anchor_dim=8 residual_dim=8 anchor_weight=1.2 residual_weight=0.8
  Summary: data/forge_benchmark_fixture/benchmark_summary.json
```

What this proves:
- the benchmark harness runs locally on repo-contained fixture data
- the current best fixture configuration passes the catastrophic regression floor
- CAM is not overstating results: on this fixture run, best lift matched baseline rather than beating it

---

## Why This Matters

A lot of agent systems can talk about repos. CAM is trying to be useful in a harder way:

- learn from repo fleets
- turn that learning into explicit tasks and specs
- create or modify codebases against those specs
- fail honestly when execution did not really happen
- export what it learned so a separate app can consume it
- run entirely locally without sending code to any cloud

That is the core build.

---

## Core Commands

| Command | Purpose |
| --- | --- |
| `cam setup` | Configure agent keys, models, budgets, and defaults |
| `cam evaluate <repo>` | Inspect one repository and produce findings |
| `cam enhance <repo>` | Run the full improve-and-verify loop on one repository |
| `cam mine <dir>` | Learn from repositories in a directory |
| `cam ideate <dir>` | Generate novel standalone app concepts from CAM memory plus repo inputs |
| `cam create <repo>` | Create, augment, or fix a repository from a task request |
| `cam validate` | Check the created result against its saved spec |
| `cam benchmark` | Measure output quality after validation |
| `cam status` | Inspect system and budget status |
| `cam chat` | Guided conversational front door for all workflows |

## Advanced Command Groups

These are the preferred expert paths. The older flat commands still work as compatibility aliases.

| Group | Use it for | Examples |
| --- | --- | --- |
| `cam doctor ...` | Preflight and diagnostics | `cam doctor keycheck --for mine --live`, `cam doctor status` |
| `cam learn ...` | Assimilation visibility and reassessment | `cam learn delta Repo2Eval`, `cam learn report`, `cam learn reassess --task "..."` |
| `cam task ...` | Manual task setup and inspection | `cam task add ...`, `cam task quickstart ...`, `cam task runbook <id>`, `cam task results` |
| `cam forge ...` | Standalone Forge export/benchmark work | `cam forge export ...`, `cam forge benchmark ...` |
| `cam kb ...` | Low-level knowledge browsing | `cam kb insights`, `cam kb search "repo repair"` |
| `cam govern ...` | Memory governance and stats | `cam govern stats`, `cam govern quota` |

---

## Roadmap

| Phase | Status | Focus |
|---|---|---|
| Phase 1: Drop-In Skill | **Complete** | SKILL.md, issue templates, namespace fix, reliability pipeline |
| Phase 2: Local-First | **Complete** | Docker, Ollama/MLX-LM, torch-free mode, 1,735 tests |
| Phase 3: Autonomy | Planned | Git-native PR automation, swarm orchestration, LanceDB upgrade |
| Phase 4: Enterprise | Planned | Sandbox enforcement, audit logs, budget hardening, benchmark leaderboard |
| Phase 5: Premier | Planned | Python2-to-FastAPI showpiece, self-evolving maintainer mode, community rollout |

---

## Documentation Map

- Full command-by-command reference: [docs/CAM_COMMAND_GUIDE.md](docs/CAM_COMMAND_GUIDE.md)
- Which command to use first: [docs/CAM_COMMAND_DECISION_TREE.md](docs/CAM_COMMAND_DECISION_TREE.md)
- Beginner assimilation walkthrough: [docs/CAM_BEGINNER_ASSIMILATION_GUIDE.md](docs/CAM_BEGINNER_ASSIMILATION_GUIDE.md)
- Proven capabilities and example transcripts: [docs/CAM_PROVEN_CAPABILITIES.md](docs/CAM_PROVEN_CAPABILITIES.md)
- Project charter and anti-drift expectations: [docs/CAM_PROJECT_CHARTER.md](docs/CAM_PROJECT_CHARTER.md)
- Short operator quick-reference: [docs/CAM_OPERATOR_CHEATSHEET.md](docs/CAM_OPERATOR_CHEATSHEET.md)
- End-to-end example workflows and outputs: [docs/CAM_EXAMPLE_WORKFLOWS.md](docs/CAM_EXAMPLE_WORKFLOWS.md)
- Current public showpiece: [docs/CAM_SHOWPIECE_REPO_UPGRADE_ADVISOR.md](docs/CAM_SHOWPIECE_REPO_UPGRADE_ADVISOR.md)
- medCSS website modernizer showpiece: [docs/CAM_SHOWPIECE_MEDCSS_MODERNIZER.md](docs/CAM_SHOWPIECE_MEDCSS_MODERNIZER.md)
- expectation ladder showpiece: [docs/CAM_SHOWPIECE_EXPECTATION_LADDER.md](docs/CAM_SHOWPIECE_EXPECTATION_LADDER.md)
- one-command reliability pipeline harness: [scripts/run_cam_reliability_pipeline.sh](scripts/run_cam_reliability_pipeline.sh)
- versioned medCSS CLI showpiece app: [apps/medcss_modernizer_showpiece](apps/medcss_modernizer_showpiece)
- Blog-style writeup of the showpiece run: [docs/blog/2026-03-16-assimilation-repo-upgrade-advisor.md](docs/blog/2026-03-16-assimilation-repo-upgrade-advisor.md)
- OpenClaw skill wrapper: [SKILL.md](SKILL.md)

## Development

Run the full test suite:

```bash
.venv/bin/pytest
```

Full suite as of March 21, 2026:

```text
1735 passed, 6 skipped
```

Show CLI help:

```bash
.venv/bin/cam --help
```

License: MIT
