# Standalone Multimodal Embedding Forge

This app is intentionally separate from CAM runtime internals.

## What it is
- A standalone embedding-forge app that ingests:
  - repository files (`.py`, `.md`)
  - an external note file
  - optional knowledge packs (`.jsonl`) exported from CAM
- It builds a `Forge-32` embedding variant and writes artifacts:
  - `forge_metrics.json`
  - `forge_device_spec.json`
  - `forge_index.json`
  - `forge_report.md`

## Hard requirement
- Uses `gemini-embedding-2-preview`.
- Fails fast if a different model is supplied.

## Why this mitigates the gap
- CAM can still assimilate repos using CAM flows.
- CAM knowledge is exported into a neutral format (`knowledge pack`).
- Forge consumes that neutral format without importing CAM code.

## Bridge from CAM to Forge
1. Export CAM memory:
```bash
python scripts/export_cam_knowledge_pack.py \
  --db data/claw.db \
  --out data/cam_knowledge_pack.jsonl \
  --max-methodologies 300 \
  --max-tasks 300
```

2. Run standalone Forge:
```bash
export GOOGLE_API_KEY=...

python apps/embedding_forge/forge_standalone.py \
  --repo autoresearch-macos \
  --note googembed.md \
  --knowledge-pack data/cam_knowledge_pack.jsonl \
  --out data/forge_showpiece_standalone
```

## Transitional compatibility
- `--cam-db data/claw.db` is supported for direct read during migration.
- Preferred long-term path is `--knowledge-pack` only.

## Regression benchmark
Run the deterministic fixture benchmark to score Forge configs without network access:

```bash
python apps/embedding_forge/benchmark_regression.py \
  --out data/forge_benchmark_fixture
```

This writes `benchmark_summary.json` with candidate configs, the best config,
and whether the result stayed above the catastrophic regression floor.
