# Assimilation-Powered Repo Upgrade Advisor

A standalone Python CLI that reads a CAM knowledge pack, scans a target repository, and produces an evidence-backed markdown upgrade plan with provenance to assimilated methodologies and tasks.

## Run

```bash
python -m advisor_app.cli \
  --knowledge-pack ../../data/showpiece_repo_upgrade_knowledge_pack.jsonl \
  --repo ../../tests/fixtures/embedding_forge/repo \
  --output demo_report.md
```

## What it outputs

- executive summary of the target repo
- ranked upgrade recommendations
- evidence from the repo scan
- assimilated provenance for each recommendation
- implementation sequence

The app does not import CAM runtime code.
