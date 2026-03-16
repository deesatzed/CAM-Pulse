# CAM Symbol-Aware Assimilation Plan

## Goal

Make mined knowledge more retrievable and more reusable across future tasks by storing:
- concrete provenance
- applicability and non-applicability hints
- activation triggers
- dependencies and risks
- enough structure for later symbol-aware expansion

## Current Backbone Reused

This design deliberately reuses existing CAM components instead of adding a new storage layer immediately:

- `methodologies`
- `capability_data`
- `action_templates`
- `methodology_links`
- `cam learn report`
- `cam learn delta`
- `cam learn reassess`
- `cam forge export`

## Exact Capability Data Shape

`capability_data` now supports these fields without a DB migration because it is already stored as JSON in `methodologies.capability_data`.

### Core fields

- `schema_version`
- `enrichment_status`
- `inputs`
- `outputs`
- `domain`
- `composability`
- `capability_type`

### New retrieval-focused fields

- `source_repos`
- `source_artifacts`
- `applicability`
- `non_applicability`
- `activation_triggers`
- `dependencies`
- `risks`
- `composition_candidates`
- `evidence`

### Source artifact structure

Each `source_artifacts` item can carry:
- `file_path`
- `symbol_name`
- `symbol_kind`
- `note`

This is the bridge to future symbol-aware mining.

## What Was Implemented Now

### 1. Mining-time capability seeding

`cam mine` now seeds capability metadata immediately when it stores a finding.

That seed contains:
- source repo provenance
- source file references
- activation trigger hints by finding category
- applicability from the finding description and implementation sketch
- non-applicability warning when adaptation is required
- dependencies from mining preconditions
- risks from augmentation notes

This means mined knowledge is useful before the LLM enrichment step even runs.

### 2. Merge-on-enrich assimilation

The assimilation engine no longer treats any existing `capability_data` as a reason to skip enrichment.

Instead:
- seeded metadata is preserved
- LLM-derived inputs/outputs/domain/composability are merged in
- `enrichment_status` becomes `merged`

This avoids losing mined provenance when enrichment happens later.

### 3. Trigger-aware retrieval support

`cam learn reassess` and capability detail views now read richer trigger/applicability metadata, not just domain and IO fields.

That improves later retrieval for task-conditioned reuse.

## Why This Matters

Before this change, mining mainly produced repo-level methodologies that were useful, but often too thin for broad future reuse.

After this change, a methodology can answer more important questions:
- where did this come from?
- when is it useful?
- when should it not be applied?
- what should activate it later?
- what risk or dependency comes with it?

That makes `cam learn reassess` materially better as CAM accumulates more mined knowledge.

## Immediate Improvements That Needed No DB Migration

These were possible because `capability_data` is already JSON-backed:

1. extend the `CapabilityData` model
2. seed richer metadata in `RepoMiner.store_finding()`
3. merge seed metadata with LLM-enriched capability data
4. expose richer fields in CLI detail/reassessment logic

This is the fastest path to better future retrieval.

## Remaining Work

### Phase 2: symbol-aware mining

Current mining is still mostly repo-level summarization.

Next improvement:
- extract symbol-level artifacts from files
- attach `symbol_name` and `symbol_kind` when possible
- keep one reusable methodology linked to multiple concrete artifacts

This is the piece that improves recall for “one brilliant function in a large repo.”

### Phase 3: explicit trigger-to-signal matching

Current activation triggers are helpful, but still category-heavy.

Next improvement:
- map repo scan signals directly to trigger names
- prefer methodologies whose triggers explicitly match those signals
- log which triggers caused retrieval

### Phase 4: outcome feedback into capability metadata

Next improvement:
- record which methodologies were actually used in successful tasks
- promote those methodologies for similar future tasks
- demote noisy methodologies that are retrieved but ineffective

### Phase 5: dedicated mined artifact table

Longer-term clean architecture:
- add `mined_artifacts`
- link artifacts to methodologies
- keep `methodologies` as reusable normalized capability nodes

That is better long-term, but not required to gain immediate value.

## Focused Self-Improvement Task List

### P0
Add symbol-aware mining extraction.

Done when:
- mined findings can store `symbol_name` and `symbol_kind`
- at least module/class/function/file provenance can be preserved
- `cam learn delta` can show newly mined artifacts, not just methodologies

### P0
Log actual methodology usage during execution.

Done when:
- CAM can record which methodologies were retrieved for a task
- successful execution increments use evidence on those methodologies
- failed use can be attributed too

### P1
Improve reassessment ranking with explicit trigger matching.

Done when:
- repo signals and task descriptions activate matching methodologies more precisely
- explanations show which triggers caused selection

### P1
Expose richer capability metadata in `cam kb capability` and `cam learn report`.

Done when:
- source repos, applicability, risks, dependencies, and triggers are shown directly

### P2
Add `mined_artifacts` table and artifact-to-methodology links.

Done when:
- CAM can distinguish raw discovered artifacts from normalized reusable methods
- one methodology can cite multiple source symbols cleanly

## Proof Of Current Step

Focused verification for the immediate implementation:

```bash
pytest -q tests/test_assimilation.py tests/test_miner.py
python -m py_compile src/claw/core/models.py src/claw/evolution/assimilation.py src/claw/miner.py src/claw/cli.py
```

Observed result during implementation:
- `171 passed in 0.51s`
- Python compile checks passed
