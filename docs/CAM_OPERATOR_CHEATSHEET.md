# CAM Operator Cheat Sheet

This is the short version.

Use this when you do not want the full command reference and just need the commands that matter most in normal operation.

## Start Here

```bash
cd CAM-Pulse
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
.venv/bin/cam --help
.venv/bin/cam govern stats
```

Preferred mental split:
- core workflow verbs stay top-level: `chat`, `evaluate`, `enhance`, `mine`, `ideate`, `preflight`, `create`, `validate`
- advanced workflow support is grouped:
  - `cam doctor ...`
  - `cam learn ...`
  - `cam task ...`
  - `cam forge ...`
  - `cam security ...`

## 1. Check That CAM Is Healthy

```bash
.venv/bin/cam govern stats
.venv/bin/cam status
.venv/bin/cam chat
```

Use this when:
- you just cloned the repo
- you are not sure the DB/runtime is healthy
- you want to verify the guided front door starts cleanly

## 2. Let CAM Guide The Command Choice

```bash
.venv/bin/cam chat
```

Example prompt inside chat:

```text
I want to mine the folder ./folderx
```

Use this when:
- you know the goal but not the exact flags
- you want CAM to ask the missing questions before it builds the command

## 3. Study One Repo Before Changing It

```bash
.venv/bin/cam evaluate /path/to/repo --mode quick
.venv/bin/cam enhance /path/to/repo --dry-run
```

Use this when:
- you want CAM to inspect before acting
- you want a safe first pass

## 4. Mine Outside Repos For Reusable Patterns

Preview only, no model calls:

```bash
.venv/bin/cam mine /path/to/repo-folder --scan-only --depth 3 --max-repos 5
```

Default behavior:
- unchanged repos are skipped automatically
- changed repos are rescanned automatically
- use `--force-rescan` when you want to ignore the ledger and mine them again anyway
- live mining now validates required provider keys before it starts unless you explicitly use `--no-live-keycheck`

Inspect the folder first:

```bash
.venv/bin/cam mine-report /path/to/repo-folder --depth 3
```

Preflight the real provider path first:

```bash
.venv/bin/cam doctor keycheck --for mine --live
```

Real mining:

```bash
.venv/bin/cam mine /path/to/repo-folder \
  --target /path/to/target-project \
  --max-repos 4 \
  --max-minutes 20
```

Use this when:
- you want CAM to learn from other repos
- you want CAM memory enriched before building something new

## 5. Ask CAM For New App Ideas

```bash
.venv/bin/cam ideate /path/to/repo-folder \
  --focus "Invent useful standalone apps that build, troubleshoot, or create" \
  --ideas 3 \
  --max-repos 4 \
  --max-minutes 10
```

Use this when:
- you want new product directions from CAM memory plus source repos
- you do not want just a summary of the repos

## 6. Preflight An Ambiguous Build Before Execution

```bash
.venv/bin/cam preflight /path/to/target-repo \
  --repo-mode new \
  --request "Apply everything repo-A does to a related workflow" \
  --answer "Delivery surface: web app"
```

Use this when:
- the request is still vague
- you want CAM to state blockers, questions, time, and budget before execution
- you want a reusable task contract under `data/preflights/`

## 7. Turn A Request Into A Real Spec And Task

```bash
.venv/bin/cam create /path/to/target-repo \
  --repo-mode new \
  --request "Build the selected app" \
  --spec "Must be standalone" \
  --check "pytest -q" \
  --max-minutes 20
```

Use this when:
- you want a spec-backed creation task
- you want the requested outcome written down explicitly

Important behavior:
- `create` now auto-runs preflight for risky or ambiguous work
- execution stops if hard blockers remain
- execution also stops if must-clarify questions remain, unless you explicitly pass `--accept-preflight-defaults`
- `--answer` and `--preflight-file` let you reuse answers across reruns

If you want CAM to attempt execution immediately:

```bash
.venv/bin/cam create /path/to/target-repo \
  --repo-mode new \
  --request "Build the selected app" \
  --check "pytest -q" \
  --execute \
  --max-minutes 20
```

For fixed-mode reliability loops, use namespace-safe retry:

```bash
.venv/bin/cam create /path/to/target-repo \
  --repo-mode fixed \
  --request "Improve CAM reliability for create+validate loops" \
  --check "pytest -q tests/test_create_benchmark_spec.py tests/test_cycle.py tests/test_openrouter.py tests/test_cli_ux.py tests/test_preflight_cli.py tests/test_config.py tests/test_miner.py" \
  --namespace-safe-retry \
  --accept-preflight-defaults \
  --execute \
  --max-minutes 30
```

## 8. Validate Before You Trust

```bash
.venv/bin/cam validate --spec-file data/create_specs/<spec-file>.json --max-minutes 5
```

Use this when:
- CAM said it created something
- you want to know whether the repo actually changed and checks passed

## 9. Benchmark After Validation

```bash
.venv/bin/cam benchmark --max-minutes 5
```

Use this when:
- you already validated correctness
- now you want a quality/performance measure

## 10. Export CAM Knowledge For A Standalone App

```bash
.venv/bin/cam forge export \
  --out data/cam_knowledge_pack.jsonl \
  --max-methodologies 200 \
  --max-tasks 200 \
  --max-minutes 5
```

Use this when:
- you want a non-CAM app to consume CAM’s learned knowledge
- you want a clean bridge instead of importing CAM internals

## 11. Inspect What CAM Already Knows

```bash
.venv/bin/cam kb insights
.venv/bin/cam kb search "repo repair"
.venv/bin/cam kb domains
.venv/bin/cam kb synergies --limit 15
.venv/bin/cam learn report --limit 10
.venv/bin/cam learn delta /path/to/repo-folder --since-hours 24 --latest 10
.venv/bin/cam learn reassess --task "repair broken tests with ast-based refactoring" --limit 10
```

Use this when:
- you want to see whether mining actually produced useful knowledge
- you want to inspect CAM memory before creating something new

## 12. Most Common Real Workflows

### Improve CAM using outside repos

```bash
.venv/bin/cam doctor keycheck --for mine --live
.venv/bin/cam mine /path/to/repo-folder --target /Users/o2satz/multiclaw --max-repos 4 --max-minutes 20
.venv/bin/cam kb insights
```

### Build a new standalone app using outside repos

```bash
.venv/bin/cam doctor keycheck --for mine --live
.venv/bin/cam mine /path/to/repo-folder --target /path/to/new-app --max-repos 4 --max-minutes 20
.venv/bin/cam ideate /path/to/repo-folder --ideas 3 --max-repos 4
.venv/bin/cam preflight /path/to/new-app --repo-mode new --request "Build the selected concept"
.venv/bin/cam create /path/to/new-app --repo-mode new --request "Build the selected concept"
.venv/bin/cam validate --spec-file data/create_specs/<spec-file>.json
```

### Run the medCSS showpiece harness end-to-end

```bash
OPENROUTER_API_KEY=... GOOGLE_API_KEY=... ./scripts/test_medcss_modernizer.sh
```

Use this when:
- you want one command that enforces `create --execute` plus `validate` plus direct postchecks
- you need a concrete showpiece proof path for CAM website-generation workflows

### Run the expectation ladder harness (increasing complexity)

```bash
OPENROUTER_API_KEY=... GOOGLE_API_KEY=... ./scripts/test_expectation_ladder.sh
```

Use this when:
- you want staged proof from expectation to reality, not one isolated demo
- you want CAM to mine/reassess and then produce a self-improvement contract for CAM itself
- you want optional guarded CAM self-execution (`CAM_LADDER_SELF_EXECUTE=1`)

### Run the full 1-7 reliability pipeline harness

```bash
OPENROUTER_API_KEY=... GOOGLE_API_KEY=... ./scripts/run_cam_reliability_pipeline.sh
```

Use this when:
- you want one command that runs baseline test + mine + reassess + fixed-mode create + validate + showpiece generation
- you want one summary artifact under `tmp/reliability_pipeline/<run-id>/summary.md`

### Safe first-contact workflow for a single repo

```bash
.venv/bin/cam evaluate /path/to/repo --mode quick
.venv/bin/cam doctor audit --limit 10
.venv/bin/cam enhance /path/to/repo --dry-run
```

### Evidence audit after learning or execution

```bash
.venv/bin/cam doctor audit --limit 10
```

Use this when you need to know whether CAM's highest-trust methodologies are actually backed by attributed, expectation-matched outcomes instead of legacy/raw-success counters.

## 13. Scan For Secrets Before Assimilation

```bash
# Check if TruffleHog is installed and configured
.venv/bin/cam security status

# Scan a directory for hardcoded secrets
.venv/bin/cam security scan /path/to/repo

# JSON output for CI pipelines
.venv/bin/cam security scan /path/to/repo --json
```

Use this when:
- you are about to ingest a repo and want to verify it is free of leaked credentials
- you want to audit your own codebase for accidental secret exposure
- you want to check TruffleHog availability before running PULSE ingestion

Note: PULSE ingestion (`cam pulse ingest`) runs this scan automatically as Gate 1 — repos with CRITICAL findings are blocked from assimilation. This command lets you run the scan manually outside of PULSE.

## Rules Of Thumb

- `mine` learns from repos. It does not itself build the new app.
- `chat` is the easiest way in if you do not already know the exact command shape.
- `ideate` proposes app concepts.
- `preflight` clarifies the task contract before expensive execution.
- `create` turns a requested outcome into a spec and task.
- `validate` should happen before `benchmark`.
- `cam forge export` is the clean handoff from CAM into a standalone app.
- if CAM claims success but validation says the repo did not change, trust validation.
