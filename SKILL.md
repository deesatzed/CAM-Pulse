---
name: 'cam-enhance'
description: 'Invoke CAM-PULSE to inspect, mine, ideate, create, validate, and benchmark a codebase with real, verifiable changes.'
measurable_outcome: 'Execute cam evaluate + cam create --execute + cam validate on a target repo and produce a passing validation report.'
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
  - Grep
---

# CAM Codebase Enhancer

Use this skill when you need an AI to **actually improve and verify** a codebase — not just talk about it. CAM is the only Claw variant with a validation-first architecture that rejects hallucinated success.

## When to Use This Skill

- Legacy codebase modernization (e.g., Python 2 to 3.12+, jQuery to React)
- Monorepo refactoring across multiple packages
- Test suite generation and coverage improvement
- Dependency upgrades with breaking change resolution
- Research repository to production conversion
- Cross-repo pattern mining and knowledge transfer
- Any task where you need **proof** the agent's changes actually work

## Core Capabilities

CAM operates as a 7-step workflow, each step producing verifiable artifacts:

1. **Inspect** — `cam evaluate <repo>` analyzes a repository and produces structured findings
2. **Mine** — `cam mine <dir>` extracts reusable patterns from external repos into persistent knowledge (`claw.db`)
3. **Ideate** — `cam ideate <dir>` generates novel app or improvement concepts from stored knowledge + repo inputs
4. **Spec** — `cam create <repo>` generates an explicit, reviewable creation spec before execution
5. **Execute** — `cam create <repo> --execute` writes real code changes, verified by workspace diff (not agent narration)
6. **Validate** — `cam validate --spec-file <spec>` checks the result against the saved spec and acceptance rules
7. **Benchmark** — `cam forge-benchmark` measures output quality with a deterministic harness

## Invocation Examples

### Evaluate a repo before touching it
```bash
cam evaluate /path/to/repo --mode quick
cam doctor audit --limit 10
```

### Mine patterns from external repos
```bash
cam mine /path/to/source-repos --target /path/to/target --max-repos 5 --depth 2
```

### Create and execute improvements
```bash
cam create /path/to/target \
  --repo-mode fixed \
  --request "Modernize auth module to use JWT, add tests" \
  --check "pytest -q" \
  --execute \
  --namespace-safe-retry
```

### Validate the result
```bash
cam validate --spec-file data/create_specs/<spec>.json
```

### Export knowledge for standalone consumption
```bash
cam forge-export --out knowledge.jsonl --max-methodologies 200
```

### CAM-PULSE: Autonomous X-powered discovery
```bash
# Check configuration and API key
cam pulse preflight

# One-shot scan: search X for new GitHub repos, filter for novelty, assimilate
cam pulse scan --keywords "AI agent framework,new repo github.com" --from-date 2026-03-21

# Dry run (scan + filter only, no cloning/mining)
cam pulse scan --dry-run

# Start perpetual polling daemon
cam pulse daemon --interval 15

# View discovery stats
cam pulse status

# List recent discoveries
cam pulse discoveries --limit 20

# Scan history
cam pulse scans

# Daily report
cam pulse report --date 2026-03-21
```

### Guided interactive mode (no flags to memorize)
```bash
cam chat
```

## Safety Notes

- **Validation-first**: CAM checks actual workspace diffs — if no files changed, execution is marked as failed
- **Namespace guards**: In fixed mode, CAM rejects changes that introduce new top-level source namespaces
- **Preflight gates**: Risky or ambiguous tasks trigger automatic preflight with must-clarify questions
- **Budget caps**: Per-agent and per-day cost limits enforced via `claw.toml`
- **Honest failure**: CAM documents its limits explicitly and does not overstate benchmark results

## Prerequisites

- Python 3.12+
- `git`
- API keys for configured LLM providers (set via `cam setup` or environment variables)
- Install: `pip install -e ".[dev]"`

## References

- [README](README.md) — Full project overview, proven capabilities, honest limits
- [Command Guide](docs/CAM_COMMAND_GUIDE.md) — Complete CLI reference
- [Operator Cheatsheet](docs/CAM_OPERATOR_CHEATSHEET.md) — Quick reference card
- [Proven Capabilities](docs/CAM_PROVEN_CAPABILITIES.md) — Evidence-backed claims
- [Project Charter](docs/CAM_PROJECT_CHARTER.md) — Anti-drift expectations
