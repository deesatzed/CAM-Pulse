# Assimilation-Powered Repo Upgrade Advisor Showpiece

## What This Proves

This showpiece demonstrates the CAM loop that actually matters:

1. repos were mined into CAM memory
2. that assimilated knowledge was exported as a neutral knowledge pack
3. a standalone app consumed that knowledge pack without importing CAM runtime code
4. the app analyzed a real target repo
5. the app produced ranked recommendations with provenance to assimilated items

This is a better public artifact than the earlier opportunity-engine run because it visibly uses CAM's learned material instead of only proving generic code scaffolding.

## Standalone App

Location:
- [apps/assimilation_repo_upgrade_advisor](/Users/o2satz/multiclaw/apps/assimilation_repo_upgrade_advisor)

Key files:
- [cli.py](/Users/o2satz/multiclaw/apps/assimilation_repo_upgrade_advisor/advisor_app/cli.py)
- [knowledge_pack.py](/Users/o2satz/multiclaw/apps/assimilation_repo_upgrade_advisor/advisor_app/knowledge_pack.py)
- [repo_scan.py](/Users/o2satz/multiclaw/apps/assimilation_repo_upgrade_advisor/advisor_app/repo_scan.py)
- [recommender.py](/Users/o2satz/multiclaw/apps/assimilation_repo_upgrade_advisor/advisor_app/recommender.py)
- [report.py](/Users/o2satz/multiclaw/apps/assimilation_repo_upgrade_advisor/advisor_app/report.py)

The app reads a CAM knowledge-pack JSONL file, scans a target repository, and outputs:
- a markdown upgrade plan
- a JSON recommendation bundle
- assimilated provenance for each recommendation

## Assimilation Input Used

Knowledge pack export command:

```bash
.venv/bin/cam forge export \
  --out data/showpiece_repo_upgrade_knowledge_pack.jsonl \
  --max-methodologies 120 \
  --max-tasks 40 \
  --max-minutes 5
```

Observed result:

```text
Knowledge pack exported.
  Total: 160
  Methodologies: 120
  Tasks: 40
  File: data/showpiece_repo_upgrade_knowledge_pack.jsonl
```

That means the showpiece is grounded in real assimilated CAM output, not a mocked pack.

## Real Target Repo Used

Demo target:
- [embedding_forge](/Users/o2satz/multiclaw/apps/embedding_forge)

Why this target was chosen:
- it is small enough to inspect deterministically
- it has real gaps the advisor can detect
- the output is clearer than running against the full CAM repo root

## Exact Run

```bash
cd /Users/o2satz/multiclaw/apps/assimilation_repo_upgrade_advisor
python -m advisor_app.cli \
  --knowledge-pack ../../data/showpiece_repo_upgrade_knowledge_pack.jsonl \
  --repo ../embedding_forge \
  --output demo_embedding_forge_report.md \
  --json-output demo_embedding_forge_report.json
```

Observed result:

```text
Wrote report to demo_embedding_forge_report.md
Recommendations: 4
```

## What The App Recommended

For `apps/embedding_forge`, the standalone app produced 4 ranked recommendations:

1. add automated tests before expanding features
2. add package metadata and repeatable developer entrypoints
3. strengthen operator-facing documentation
4. add continuous verification checks

Those recommendations were backed by assimilated provenance from mined repos such as:
- `xplay`
- `whs112625`
- `Anthropic-Cybersecurity-Skills`
- `autoresearch-macos`
- `workspace`

## Verification

Standalone app tests:

```bash
cd /Users/o2satz/multiclaw/apps/assimilation_repo_upgrade_advisor
pytest -q
```

Observed result:

```text
6 passed in 0.03s
```

Artifact checks:

```bash
python -m advisor_app.cli \
  --knowledge-pack ../../data/showpiece_repo_upgrade_knowledge_pack.jsonl \
  --repo ../embedding_forge \
  --output demo_embedding_forge_report.md \
  --json-output demo_embedding_forge_report.json

test -f demo_embedding_forge_report.md
test -f demo_embedding_forge_report.json
rg -n "Ranked Recommendations|Assimilated provenance|Implementation Order" demo_embedding_forge_report.md
```

Observed result:

```text
Wrote report to demo_embedding_forge_report.md
Recommendations: 4
14:## Ranked Recommendations
28:- Assimilated provenance:
83:## Implementation Order
```

## Why This Is The Better Showpiece

This artifact is much closer to the real identity of CAM.

It proves:
- CAM can learn from outside repos
- CAM can package that learning for outside use
- a standalone tool can use the packaged learning directly
- the resulting output is actionable, evidence-backed, and attributable to assimilated sources

It does not rely on pretending first-pass autonomous code generation is already flawless.

## Limitations

This showpiece is real, but not final-state perfection.

Current limitations:
- recommendation quality still depends on heuristic repo scanning
- provenance ranking is lexical plus metadata-based, not semantic retrieval over embeddings
- the strongest demo target so far is a smaller repo, not a very large production codebase

## Artifact

Demo markdown artifact:
- [docs/showpieces/repo-upgrade-advisor-demo-report.md](docs/showpieces/repo-upgrade-advisor-demo-report.md)
