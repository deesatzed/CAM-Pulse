# CAM Showpiece: Expectation Ladder

This showpiece is a staged proof path from baseline expectations to harder, real execution outcomes.

The harness is:
- [scripts/test_expectation_ladder.sh](/Users/o2satz/multiclaw/scripts/test_expectation_ladder.sh)

## Why this exists

A single pass/fail demo is not enough. This ladder verifies CAM at increasing complexity levels:

1. runtime health and expectation preflight
2. deterministic standalone build + validate
3. workflow UX build + validate
4. mining + reassessment against a CAM reliability task
5. CAM-on-CAM self-improvement contract generation
6. optional guarded self-execution

This moves from "can CAM run at all?" to "can CAM use mined knowledge to improve itself safely?"

## Run it

From repo root:

```bash
chmod +x scripts/test_expectation_ladder.sh
```

Safe default (no self-execute):

```bash
OPENROUTER_API_KEY=... GOOGLE_API_KEY=... ./scripts/test_expectation_ladder.sh
```

Enable guarded CAM self-execution:

```bash
OPENROUTER_API_KEY=... GOOGLE_API_KEY=... \
CAM_LADDER_SELF_EXECUTE=1 \
./scripts/test_expectation_ladder.sh
```

## Useful controls

- `CAM_LADDER_MAX_LEVEL`
  - cap the run at a specific stage, default `4`
- `CAM_LADDER_SOURCE_DIR`
  - source directory for mining transfer stage, default `repoTST`
- `CAM_LADDER_CHANGED_ONLY`
  - mine only changed/new repos in stage 3, default `1`
- `CAM_LADDER_STOP_ON_FAIL`
  - stop immediately on first failure, default `0` (continue to collect full ladder evidence)
- `CAM_LADDER_AGENT`
  - choose `claude|codex|gemini|grok`, default `claude`

Example partial run:

```bash
OPENROUTER_API_KEY=... GOOGLE_API_KEY=... \
CAM_LADDER_MAX_LEVEL=2 \
./scripts/test_expectation_ladder.sh
```

## Outputs

Every run writes artifacts under:

```text
tmp/ladder_logs/<RUN_ID>/
```

Key files:
- `results.tsv` per-step pass/fail
- `summary.md` run summary
- `level*.log` full command logs

## Safety model

- level `4.1` is spec-only for CAM self-improvement (no execute)
- level `4.2` executes only when `CAM_LADDER_SELF_EXECUTE=1`
- quickstart namespace drift guardrails and fixed-mode namespace constraints remain active

This keeps self-improvement explicit and auditable rather than implicit.
