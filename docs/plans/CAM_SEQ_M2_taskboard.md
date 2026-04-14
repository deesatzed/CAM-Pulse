# CAM-SEQ M2 Task Board

Date: 2026-04-12
Status: Ready for execution planning
Depends on:

- `docs/plans/CAM_SEQ_M0_contract.md`
- `docs/plans/CAM_SEQ_M1_spec.md`
- `docs/plans/CAM_SEQ_M1_taskboard.md`
- `docs/plans/CAM_SEQ_M2_spec.md`

## Usage

This is the execution-facing task board for M2.

Rules:

- Do not begin M2 until M1 is explicitly signed off.
- Prioritize making component memory useful before packet planning begins.
- Do not introduce planning, packet review, or orchestration behavior here.
- Backfill and extraction must preserve explicit provenance precision.
- Backfill must be idempotent.

## Ticket M2-01 — Make Component Extractor Real

Priority: P0
Parallel-safe: No

Files:

- `src/claw/mining/component_extractor.py`

Scope:

- Turn extractor skeleton into a usable component extraction module for Python / TS / JS

Tasks:

- [ ] Define extractor input contract
- [ ] Define extractor output contract
- [ ] Implement Python extraction
- [ ] Implement TypeScript extraction
- [ ] Implement JavaScript extraction
- [ ] Implement AST fingerprint generation
- [ ] Implement file-level fallback behavior
- [ ] Emit provenance precision honestly

Dependencies:

- M1 complete

Acceptance:

- [ ] Extractor imports cleanly
- [ ] Produces symbol-level candidates where feasible
- [ ] Produces file-level fallback where symbol extraction is weak
- [ ] Emits stable enough inputs for source barcode generation

## Ticket M2-02 — Optional SCIP Loader

Priority: P1
Parallel-safe: Yes after M2-01

Files:

- `src/claw/mining/scip_loader.py`

Scope:

- Add optional SCIP ingestion support to improve symbol/reference precision

Tasks:

- [ ] Detect index presence
- [ ] Load definition/reference data
- [ ] Map index data to extractor receipts
- [ ] Upgrade provenance precision where appropriate

Dependencies:

- M2-01

Acceptance:

- [ ] Repos without SCIP still work
- [ ] Indexed repos can improve precision
- [ ] Precision changes are explicit, not implied

## Ticket M2-03 — Backfill Pipeline In Miner

Priority: P0
Parallel-safe: No

Files:

- `src/claw/miner.py`

Scope:

- Add methodology -> component backfill behavior and supporting helpers

Tasks:

- [ ] Read methodologies and capability_data as input
- [ ] Use source_artifacts to derive candidate components
- [ ] Generate source/family/lineage identity
- [ ] Create or upsert component cards
- [ ] Link component cards back to methodologies
- [ ] Seed minimal fit rows where possible
- [ ] Record skip reasons for insufficient evidence

Dependencies:

- M2-01
- M1 repository and barcode work complete

Acceptance:

- [ ] Existing methodology records can generate component cards
- [ ] Backfill avoids duplicate component identities
- [ ] Skip behavior is explicit when evidence is too weak

## Ticket M2-04 — CLI Backfill Command

Priority: P0
Parallel-safe: No

Files:

- `src/claw/cli/_monolith.py`
- possibly `src/claw/cli/__init__.py`

Scope:

- Expose a repeatable backfill command for operators

Tasks:

- [ ] Add `cam learn backfill-components`
- [ ] Add options for workspace / DB selection if needed
- [ ] Emit created / updated / skipped counts
- [ ] Ensure rerun safety

Dependencies:

- M2-03

Acceptance:

- [ ] Command runs successfully on a real CAM DB
- [ ] Command is idempotent on rerun
- [ ] Output is useful for operators

## Ticket M2-05 — Component Search and Detail Repository Helpers

Priority: P0
Parallel-safe: Yes after M2-03

Files:

- `src/claw/db/repository.py`

Scope:

- Add component-memory queries needed by APIs

Tasks:

- [ ] Add text search over components
- [ ] Add list components
- [ ] Add component detail lookup
- [ ] Add lineage lookup
- [ ] Add methodology -> components lookup
- [ ] Add component history lookup scaffolding

Dependencies:

- M2-03

Acceptance:

- [ ] Component summaries can be queried
- [ ] Component detail can be fetched by ID
- [ ] Parent methodology linkage is queryable

## Ticket M2-06 — Component Search and Detail API

Priority: P0
Parallel-safe: No

Files:

- `src/claw/web/dashboard_server.py`

Scope:

- Add component-focused `/api/v2` endpoints

Tasks:

- [ ] `GET /api/v2/components/search`
- [ ] `GET /api/v2/components/{component_id}`
- [ ] `GET /api/v2/components/{component_id}/history`
- [ ] `POST /api/v2/components/backfill`

Dependencies:

- M2-05
- M2-04

Acceptance:

- [ ] Search returns summary payloads
- [ ] Detail returns receipt + lineage + notes + methodology linkage
- [ ] Backfill endpoint can trigger component population

## Ticket M2-07 — Semantic Memory Bridge

Priority: P1
Parallel-safe: Yes after M2-05

Files:

- `src/claw/memory/semantic.py`

Scope:

- Add component-memory bridge helpers without altering methodology retrieval behavior

Tasks:

- [ ] Add component search helper methods
- [ ] Keep methodology search intact
- [ ] Prepare future planning-facing search shape

Dependencies:

- M2-05

Acceptance:

- [ ] Existing methodology retrieval remains unchanged
- [ ] Component search can be accessed through a higher-level memory layer

## Ticket M2-08 — Optional Minimal Frontend Client Support

Priority: P2
Parallel-safe: Yes after M2-06

Files:

- `forge-ui/src/lib/api.ts`

Scope:

- Add typed client support for M2 component APIs if needed for validation

Tasks:

- [ ] Add component summary types
- [ ] Add component detail types
- [ ] Add component search client
- [ ] Add component detail client

Dependencies:

- M2-06

Acceptance:

- [ ] Frontend can consume M2 component APIs with typed payloads

## Ticket M2-09 — M2 Test Coverage

Priority: P0
Parallel-safe: Partial after implementation tickets land

Files:

- `tests/mining/test_component_extractor.py`
- `tests/mining/test_scip_ingestion.py`
- `tests/db/test_component_repository.py`
- `tests/integration/test_component_backfill.py`
- `tests/api/test_component_endpoints.py`

Scope:

- Add tests for extraction, backfill, search, and detail APIs

Tasks:

- [ ] Extractor tests
- [ ] SCIP optional behavior tests
- [ ] Backfill idempotency tests
- [ ] Component search tests
- [ ] Component detail tests
- [ ] Methodology linkage tests

Dependencies:

- M2-01
- M2-03
- M2-05
- M2-06

Acceptance:

- [ ] New tests pass
- [ ] Existing tests remain green or intentionally updated

## Ticket M2-10 — M2 Exit Validation

Priority: P0
Parallel-safe: No

Scope:

- Validate milestone completeness before M3 starts

Checklist:

- [ ] At least one mature DB backfills successfully
- [ ] Backfill is idempotent
- [ ] Component search works through repository and HTTP APIs
- [ ] Component detail returns usable receipts and lineage info
- [ ] Methodology -> component linkage is durable
- [ ] Provenance precision remains explicit
- [ ] No planning or packet logic leaked into M2 implementation

Dependencies:

- M2-09

Acceptance:

- [ ] M2 signed off as complete

## Suggested Execution Order

1. M2-01 Make Component Extractor Real
2. M2-03 Backfill Pipeline In Miner
3. M2-04 CLI Backfill Command
4. M2-05 Component Search and Detail Repository Helpers
5. M2-06 Component Search and Detail API
6. M2-07 Semantic Memory Bridge
7. M2-02 Optional SCIP Loader
8. M2-08 Optional Minimal Frontend Client Support
9. M2-09 M2 Test Coverage
10. M2-10 M2 Exit Validation

## Review Triggers

Trigger explicit review if a ticket touches:

- `src/claw/miner.py`
- `src/claw/memory/semantic.py`
- `src/claw/web/dashboard_server.py`

## Drift Checks During M2

- [ ] Are we preserving explicit provenance precision?
- [ ] Are we backfilling from existing knowledge instead of forcing re-mining?
- [ ] Are we avoiding packet/planning creep in this milestone?
- [ ] Are component cards staying distinct from methodologies?
- [ ] Is backfill safe to rerun without duplicate identities?
