# Multimodal Embedding Forge (Legacy Demo)

This directory is a legacy CAM-coupled demo.

For the standalone app (decoupled from CAM internals), use:
- `apps/embedding_forge/forge_standalone.py`
- `apps/embedding_forge/README.md`

Legacy demo ingests:
- `autoresearch-macos` (code + markdown)
- `googembed.md` (research note)
- CLAW learned memory from `data/claw.db` (`methodologies`, `tasks`)

It builds a novel **Forge-32** embedding variant using
Google's Gemini embedding model (`gemini-embedding-2-preview`) as the base encoder:
- 16-dim anchor channel (cross-modal concept anchors)
- 16-dim residual channel (deterministic compressed signal)

Outputs are written to `data/forge_showpiece` by default:
- `forge_report.md`
- `forge_metrics.json`
- `forge_device_spec.json`
- `forge_index.json`

## Run

```bash
export GOOGLE_API_KEY=...  # required

python demos/multimodal_embedding_forge/forge.py \
  --repo autoresearch-macos \
  --note googembed.md \
  --db data/claw.db \
  --out data/forge_showpiece
```
