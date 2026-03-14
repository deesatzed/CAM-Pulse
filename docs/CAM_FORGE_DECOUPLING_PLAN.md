# CAM ↔ Forge Decoupling Plan

## Critical gap
- Desired state:
  - CAM continues assimilation/routing/execution in its own system.
  - New embedding Forge app is standalone and not CAM-runtime-coupled.
- Previous state:
  - Forge imported CAM modules directly and read CAM DB directly.

## Mitigation strategy
1. Create a standalone Forge runtime with no `claw.*` imports.
2. Introduce a neutral exchange format (`knowledge pack` JSONL).
3. Provide a CAM exporter that writes this exchange format.
4. Keep optional direct DB ingestion only as transitional fallback.

## Implemented now
- Standalone Forge app:
  - `apps/embedding_forge/forge_standalone.py`
  - Enforces `gemini-embedding-2-preview`.
  - Uses Google Gemini embeddings API directly.
- Deterministic benchmark harness:
  - `apps/embedding_forge/benchmark_regression.py`
  - Scores fixture corpora without network access.
- CAM bridge exporter:
  - `scripts/export_cam_knowledge_pack.py`
  - Exports methodologies + tasks to JSONL.
- Documentation:
  - `apps/embedding_forge/README.md`
  - Legacy demo README marked as CAM-coupled.

## Acceptance criteria
- A run succeeds with only:
  - `python scripts/export_cam_knowledge_pack.py ...`
  - `python apps/embedding_forge/forge_standalone.py --knowledge-pack ...`
- `forge_standalone.py` has no import of CAM runtime modules.
- Standalone run fails fast if embedding model is not `gemini-embedding-2-preview`.

## Remaining hardening tasks
1. Add live Gemini smoke test to release checklist or gated CI.
2. Add schema versioning to knowledge pack format.
3. Add optional compression and chunking for large packs.
4. Add provenance labels per source repo in exporter metadata.
