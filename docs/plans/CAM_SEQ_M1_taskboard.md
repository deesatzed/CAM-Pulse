# CAM-SEQ M1 Task Board

Date: 2026-04-12
Status: Ready for execution planning
Depends on:

- `docs/plans/CAM_SEQ_M0_contract.md`
- `docs/plans/CAM_SEQ_M1_spec.md`

## Usage

This is the execution-facing task board for M1.

Rules:

- Work tickets in order unless explicitly marked parallel-safe.
- Do not begin a ticket until its dependencies are complete.
- Do not mark a ticket complete until all acceptance checks pass.
- If a ticket requires a protected-file change, call that out explicitly in review.

## Ticket M1-01 — Add Core Models

Priority: P0
Parallel-safe: No

Files:

- `src/claw/core/models.py`

Scope:

- Add all M1 core model classes and enums/literals

Tasks:

- [ ] Add FitBucket
- [ ] Add TransferMode
- [ ] Add ProvenancePrecision
- [ ] Add SlotRisk
- [ ] Add CoverageState
- [ ] Add AdaptationBurden
- [ ] Add LandingOrigin
- [ ] Add Receipt
- [ ] Add ComponentCard
- [ ] Add ComponentLineage
- [ ] Add ComponentFit
- [ ] Add ComponentCardSummary
- [ ] Add SlotSpec
- [ ] Add CandidateSummary
- [ ] Add ApplicationPacketSummary
- [ ] Add minimal PairEvent
- [ ] Add minimal LandingEvent
- [ ] Add minimal OutcomeEvent
- [ ] Add minimal RunConnectome
- [ ] Add minimal CompiledRecipe

Dependencies:

- M0 frozen

Acceptance:

- [ ] New models import cleanly
- [ ] No existing tests break from import/type errors
- [ ] Required/optional field boundaries match M1 spec
- [ ] `fit_bucket` and `transfer_mode` are distinct types
- [ ] Packet summary type exists separately from detail packet contracts

## Ticket M1-02 — Add Additive Schema

Priority: P0
Parallel-safe: No

Files:

- `src/claw/db/schema.sql`

Scope:

- Add all M1 additive tables and indexes

Tasks:

- [ ] Add `component_lineages`
- [ ] Add `component_cards`
- [ ] Add `component_fit`
- [ ] Add `slot_instances`
- [ ] Add `application_packets`
- [ ] Add `pair_events`
- [ ] Add `landing_events`
- [ ] Add `outcome_events`
- [ ] Add `run_connectomes`
- [ ] Add `run_connectome_edges`
- [ ] Add `compiled_recipes`
- [ ] Add indexes for barcode columns and FK-heavy lookups

Dependencies:

- M1-01

Acceptance:

- [ ] Fresh DB init succeeds
- [ ] Existing DB upgrade succeeds
- [ ] Existing methodology tables remain untouched
- [ ] New tables appear in `.tables`
- [ ] No syntax or migration regression in DB startup

Review note:

- Protected file change

## Ticket M1-03 — Repository CRUD and Query Layer

Priority: P0
Parallel-safe: No

Files:

- `src/claw/db/repository.py`

Scope:

- Add repository methods for lineages, components, fits, packets, events, connectomes

Tasks:

- [ ] Add lineage CRUD/query methods
- [ ] Add component CRUD/query methods
- [ ] Add component fit CRUD/query methods
- [ ] Add packet persistence/query methods
- [ ] Add pair/landing/outcome persistence/query methods
- [ ] Add run connectome persistence/query methods

Dependencies:

- M1-02

Acceptance:

- [ ] Each entity round-trips model -> DB -> model
- [ ] JSON fields are serialized/deserialized correctly
- [ ] Repository methods preserve precision and coverage fields
- [ ] No existing repository behavior regresses

## Ticket M1-04 — Barcode Utilities

Priority: P0
Parallel-safe: Yes after M1-01

Files:

- `src/claw/connectome/barcodes.py`

Scope:

- Implement deterministic source/family/slot barcode helpers and derived ID helpers

Tasks:

- [ ] Implement source barcode helper
- [ ] Implement family barcode helper
- [ ] Implement slot barcode helper
- [ ] Implement derived pair/locus/outcome helper IDs
- [ ] Document normalized inputs in code comments or module docstring

Dependencies:

- M1-01

Acceptance:

- [ ] Same exact input yields same barcode
- [ ] Missing optional fields do not break stability
- [ ] Line numbers are not required for source identity

## Ticket M1-05 — Lineage Utilities

Priority: P0
Parallel-safe: Yes after M1-01 and M1-04

Files:

- `src/claw/connectome/lineage.py`

Scope:

- Implement baseline lineage clustering and dedup helpers

Tasks:

- [ ] Exact-content lineage lookup
- [ ] Canonical lineage creation helper
- [ ] Dedup support counter helper
- [ ] Clone-inflation baseline flag logic

Dependencies:

- M1-01
- M1-04

Acceptance:

- [ ] Exact duplicates map to one lineage family
- [ ] Distinct receipts can still exist under one lineage
- [ ] Baseline dedup support count is lineage-aware

## Ticket M1-06 — Feature Flag Config

Priority: P0
Parallel-safe: Yes after M0

Files:

- `src/claw/core/config.py`
- `src/claw/core/factory.py`

Scope:

- Add CAM-SEQ feature flags and expose them to runtime

Tasks:

- [ ] Add `camseq` config group
- [ ] Add `component_cards`
- [ ] Add `application_packets`
- [ ] Add `connectome_seq`
- [ ] Add `critical_slot_policy`
- [ ] Add `a2a_packets`
- [ ] Default all to false
- [ ] Make flags reachable from runtime state

Dependencies:

- M0 frozen

Acceptance:

- [ ] Config loads with defaults
- [ ] Flags can be overridden by config
- [ ] Flags-off path preserves old behavior

Review note:

- Protected file changes likely

## Ticket M1-07 — Component Extractor Skeleton

Priority: P1
Parallel-safe: Yes after M1-01

Files:

- `src/claw/mining/component_extractor.py`

Scope:

- Create initial extractor skeleton with language dispatch and placeholder extraction contracts

Tasks:

- [ ] Create module
- [ ] Define extractor output structure
- [ ] Add Python dispatch
- [ ] Add TS/JS dispatch
- [ ] Add AST fingerprint placeholder or initial implementation

Dependencies:

- M1-01

Acceptance:

- [ ] Module imports cleanly
- [ ] Output structure is usable by later M2 work
- [ ] No mining flow is changed yet

## Ticket M1-08 — Test Coverage for M1

Priority: P0
Parallel-safe: Partial after tickets land

Files:

- `tests/connectome/test_barcodes.py`
- `tests/connectome/test_lineage_dedup.py`
- `tests/db/test_component_schema.py`
- `tests/db/test_component_repository.py`
- `tests/config/test_camseq_flags.py`

Scope:

- Add tests for all M1 foundations

Tasks:

- [ ] Barcode determinism tests
- [ ] Lineage dedup baseline tests
- [ ] Model validation tests
- [ ] Schema migration/init tests
- [ ] Repository round-trip tests
- [ ] Flag defaults and override tests

Dependencies:

- M1-02
- M1-03
- M1-04
- M1-05
- M1-06

Acceptance:

- [ ] New tests pass
- [ ] Relevant existing tests still pass

## Ticket M1-09 — M1 Exit Validation

Priority: P0
Parallel-safe: No

Scope:

- Validate milestone completeness before moving to M2

Checklist:

- [ ] New models validate cleanly
- [ ] New tables migrate cleanly
- [ ] Repository methods round-trip entities correctly
- [ ] Source/family barcodes are stable
- [ ] Lineage baseline works for exact duplicates
- [ ] Flags default off
- [ ] No legacy flows change behavior with flags off
- [ ] M1 artifacts align with M0 contract

Dependencies:

- M1-08

Acceptance:

- [ ] M1 signed off as complete

## Suggested Execution Order

1. M1-01 Add Core Models
2. M1-02 Add Additive Schema
3. M1-03 Repository CRUD and Query Layer
4. M1-04 Barcode Utilities
5. M1-05 Lineage Utilities
6. M1-06 Feature Flag Config
7. M1-07 Component Extractor Skeleton
8. M1-08 Test Coverage for M1
9. M1-09 M1 Exit Validation

## Review Triggers

Trigger explicit review if a ticket touches:

- `src/claw/core/config.py`
- `src/claw/core/factory.py`
- `src/claw/db/schema.sql`
- `src/claw/db/engine.py`
- `src/claw/verifier.py`

## Drift Checks During M1

- [ ] Did any model blur methodology memory with sequenced event memory?
- [ ] Did any field silently imply precision instead of declaring it?
- [ ] Did any ticket change runtime behavior instead of only adding data foundations?
- [ ] Did any implementation remove the summary/detail split?
