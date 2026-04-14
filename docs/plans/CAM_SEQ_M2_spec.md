# CAM-SEQ M2 Implementation Spec

Date: 2026-04-12
Status: Draft
Depends on:

- `docs/plans/CAM_SEQ_M0_contract.md`
- `docs/plans/CAM_SEQ_M1_spec.md`
- `docs/plans/CAM_SEQ_M1_taskboard.md`

## Scope

M2 covers:

- component extraction becoming usable
- methodology -> component backfill
- component detail/history APIs
- initial text/search access to component memory

M2 does not cover:

- task planning and slot decomposition
- packet review UI
- packet execution integration
- run sequencing UI
- retrograde tracing
- recipes

The purpose of M2 is to make component memory real and queryable before planning logic depends on it.

## 1. Design Goals

### 1.1 Use existing CAM knowledge first

M2 should prioritize backfilling existing methodologies and capability metadata into component cards before requiring large re-mining passes.

### 1.2 Precision ladder, not false precision

M2 should support this precision ladder:

- exact symbol-level extraction when available
- symbol-level heuristic extraction when reliable
- file-level fallback when symbol extraction is weak

If a repo lacks precision, M2 must preserve that honestly in `provenance_precision`.

### 1.3 Component memory must already be useful without packets

By the end of M2, a user or service should be able to:

- inspect a component
- search components
- see lineages
- see provenance precision
- see applicability / non-applicability
- see adaptation and risk notes

### 1.4 Keep mining additive

Existing mining should still work with flags off.
M2 adds component sequencing capability, not a replacement mining path.

## 2. New / Extended Modules

### 2.1 src/claw/mining/component_extractor.py

This becomes a real implementation in M2.

Required capabilities:

- Python extraction
- TypeScript extraction
- JavaScript extraction
- AST fingerprint generation
- component grouping heuristics

Expected outputs:

- title
- component_type candidate
- symbol name when available
- file path
- line range when available
- language
- AST fingerprint
- extraction confidence or provenance precision basis

### 2.2 src/claw/mining/scip_loader.py

Optional but supported.

Required capabilities:

- detect precomputed SCIP index
- load symbol/reference data
- improve precision where available

Rule:

- SCIP is an enhancement, not a dependency

### 2.3 src/claw/miner.py

Extend to:

- call component extractor
- map extracted components to component cards
- link component cards back to methodologies
- avoid duplicate component creation through source barcode + lineage checks

### 2.4 src/claw/memory/semantic.py

Extend to:

- expose component search helpers
- keep methodology search intact
- provide a bridge layer for future packet planning

## 3. Extraction Contract

### 3.1 First-language targets

M2 required:

- Python
- TypeScript
- JavaScript

M2 optional:

- reuse current file-level metadata for other languages without pretending symbol extraction

### 3.2 Candidate kinds to extract

M2 should attempt to extract these reusable shapes:

- function
- class
- module-level helper cluster
- route handler
- validator
- queue worker
- API client
- test fixture
- config helper

Do not attempt full semantic coverage in M2.
Bias toward stable, reusable units.

### 3.3 Grouping heuristic

If a file has several related helpers that form one reusable unit, M2 may emit one grouped component when:

- helpers are adjacent or tightly related
- they share one clear purpose
- a single-family label is more honest than several tiny fragments

Rule:

- grouped component still needs one receipt anchor; use the strongest symbol anchor or file-level fallback

## 4. Backfill Contract

### 4.1 Source of truth for backfill

Backfill should use existing:

- methodologies
- `capability_data`
- `source_artifacts`
- applicability / non-applicability
- dependencies
- risks
- evidence

### 4.2 Backfill strategy

For each methodology:

1. inspect `capability_data.source_artifacts`
2. create one or more component cards when source artifacts are concrete enough
3. attach `methodology_id` to every derived component
4. derive source barcode and family barcode
5. attach lineage using content hash baseline
6. seed component fit heuristics when possible

### 4.3 Backfill command

Add CLI support for:

- `cam learn backfill-components`

M2 command behavior:

- idempotent
- safe to rerun
- emits counts of created / updated / skipped components

## 5. Family and Type Labeling Contract

M2 should start with deterministic heuristics first.

### 5.1 component_type baseline examples

Allowed examples:

- `api_client`
- `retry_helper`
- `queue_worker`
- `validator`
- `repository`
- `auth_handler`
- `test_fixture`
- `route_handler`
- `config_helper`
- `parser`

### 5.2 abstract_jobs baseline examples

Allowed examples:

- `authenticated_api_client`
- `idempotent_event_processor`
- `retry_with_backoff`
- `tempdir_test_fixture`
- `token_refresh_serialization`
- `streaming_response_normalization`

### 5.3 Labeling approach

Use:

- deterministic heuristics first
- existing `capability_data` text and evidence
- LLM assistance only for long-tail fallback, not as the primary first-pass system

## 6. Search and API Contract

M2 should expose useful component memory through HTTP before packet planning exists.

### 6.1 Required APIs

Add under `/api/v2`:

- `GET /api/v2/components/{component_id}`
- `GET /api/v2/components/{component_id}/history`
- `GET /api/v2/components/search?q=...`
- `POST /api/v2/components/backfill`

Optional:

- `GET /api/v2/components/lineages/{lineage_id}`

### 6.2 Search response shape

Use summary payloads.

Search results should include:

- component ID
- title
- component_type
- family_barcode
- repo
- file_path
- symbol if available
- provenance_precision
- language
- coverage_state
- success/failure counts

### 6.3 Component detail response shape

Use detail payloads.

Must include:

- receipt
- abstract jobs
- type
- lineage
- applicability / non-applicability
- adaptation notes
- risk notes
- dependencies
- test evidence
- fit rows if present
- methodology parent link if present

## 7. Frontend Expectations For M2

M2 should avoid large new UI surfaces.

Minimal frontend expectation:

- existing Knowledge surface can consume component detail if needed later
- typed client additions may begin, but M2 does not require the full packet UI

Optional M2 UI work:

- a minimal component detail route stub if it helps validate APIs

Not required in M2:

- packet review route
- Forge sequencing tabs
- Evolution run route

## 8. Repository Method Additions Needed In M2

These build on M1 repository work.

### 8.1 Component search methods

- `search_component_cards_text(query, limit, language=None)`
- `list_component_cards(...)`
- `list_components_for_methodology(methodology_id)`

### 8.2 Backfill helpers

- `find_component_by_source_barcode(source_barcode)`
- `upsert_component_card(...)`
- `upsert_component_lineage(...)`

### 8.3 History helpers

- `list_component_fit(component_id)`
- `list_component_packet_history(component_id, limit=50)` if packet table exists but is mostly empty in M2

## 9. M2 Tests

Add or expand:

- `tests/mining/test_component_extractor.py`
- `tests/mining/test_scip_ingestion.py`
- `tests/db/test_component_repository.py`
- `tests/integration/test_component_backfill.py`
- `tests/api/test_component_endpoints.py`

### 9.1 Required assertions

- extractor emits stable source barcodes
- exact duplicate extraction reuses lineage
- backfill is idempotent
- component search returns summaries
- component detail returns receipts and lineage
- methodology parent linkage is preserved
- flags-off behavior for unrelated flows is unchanged

## 10. M2 Exit Criteria

M2 is complete only when:

- at least one mature knowledge DB can be backfilled successfully
- component detail APIs return usable receipts and lineage info
- component search works through HTTP and repository layers
- extracted components preserve explicit provenance precision
- methodology -> component linkage is durable
- rerunning backfill does not create duplicate component identities

## 11. Deferred To M3+

These are explicitly out of M2:

- slot decomposition
- packet review
- plan APIs
- packet execution integration
- run connectome surfaces
- retrograde tracing
- recipes
