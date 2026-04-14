# CAM-SEQ M3 Implementation Spec

Date: 2026-04-12
Status: Draft
Depends on:

- `docs/plans/CAM_SEQ_M0_contract.md`
- `docs/plans/CAM_SEQ_M1_spec.md`
- `docs/plans/CAM_SEQ_M2_spec.md`

## Scope

M3 covers:

- task archetype inference
- slot decomposition
- per-slot candidate retrieval and ranking
- application packet construction
- plan and packet APIs
- pre-mutation review UX

M3 does not cover:

- packet-aware execution integration in `cycle.py`
- live run sequencing UI
- retrograde tracing
- recipe compilation

The purpose of M3 is to make pre-write decision review real before any runtime mutation work is changed.

## 1. Design Goals

### 1.1 No mutation before review

In interactive CAM-SEQ mode, no nontrivial task should begin writing until:

- task archetype is inferred
- slots exist
- each slot has a selected candidate or explicit blocked state
- the packet review artifact exists

### 1.2 Packet-first supervision

The Application Packet is the primary artifact in M3.

M3 should prove that CAM can compress:

- decomposition
- retrieval
- selection
- adaptation
- proof requirements
- risk state

into one reviewable object per slot.

### 1.3 Deterministic baseline first

Taskome planning in M3 should start with deterministic heuristics plus optional later enrichment.

Do not make slot planning depend entirely on an LLM in v1.

### 1.4 Weak evidence must be explicit

If a slot is weakly covered, missing direct-fit candidates, or missing a meaningful runner-up, that must be represented in the plan.

### 1.5 Fit bucket and transfer mode must stay distinct

This is frozen by M0 and must be enforced in M3 implementation:

- `fit_bucket` answers expected utility
- `transfer_mode` answers directness of transfer

## 2. Planning Module Contract

Create these modules:

- `src/claw/planning/taskome.py`
- `src/claw/memory/component_ranker.py`
- `src/claw/planning/application_packet.py`

These modules should remain usable without execution integration.

## 3. Taskome Contract

Implement in `src/claw/planning/taskome.py`.

### 3.1 Inputs

Taskome generation should accept:

- task text
- workspace path
- target language if known
- target stack hints if known
- optional user check commands

### 3.2 Outputs

Taskome generation should produce:

- task archetype
- archetype confidence
- list of slots
- critical-slot labels
- constraints per slot
- proof expectations per slot
- coverage summary

### 3.3 Archetype baseline

M3 should support at least these archetype families:

- `oauth_session_management`
- `async_ingestion`
- `rate_limited_external_sync`
- `webhook_reliability_pipeline`
- `parser_transform_pipeline`
- `storage_test_scaffolding`
- `mcp_registry_scaffold`
- `cross_language_pattern_transfer`

### 3.4 Slot baseline

Slots should be concrete and reusable across tasks.

Examples:

- `auth_flow`
- `session_store`
- `token_refresh`
- `middleware_integration`
- `file_intake`
- `parser`
- `validation`
- `queue_worker`
- `retry_logic`
- `progress_persistence`
- `error_reporting`
- `tests`

### 3.5 Slot fields

Each slot must include:

- stable `slot_id`
- stable `slot_barcode`
- name
- abstract job
- risk
- constraints
- target stack
- proof expectations

## 4. Ranking Contract

Implement in `src/claw/memory/component_ranker.py`.

### 4.1 Inputs

Ranker inputs should include:

- slot spec
- candidate component cards
- optional existing fit rows
- optional target language / stack hints

### 4.2 Ranking signals

M3 ranker should support these baseline signals:

- family barcode match
- component-type match
- language compatibility
- framework compatibility
- constraint compatibility
- receipt precision
- applicability text overlap
- non-applicability penalties
- deduped lineage support
- test evidence presence

Future signals may be added later, but M3 should not require live pair history to be useful.

### 4.3 Ranking outputs

Each ranked candidate must include:

- fit bucket
- transfer mode
- numeric confidence
- confidence basis
- adaptation burden
- why-fit bullets
- known failure modes if present

### 4.4 Hard rules

- `no_help` candidates are never auto-selected
- critical slots cannot auto-select `stretch`
- weak evidence state is explicit if no strong candidate exists

## 5. Application Packet Contract

Implement in `src/claw/planning/application_packet.py`.

### 5.1 Packet summary

Must support:

- packet ID
- plan ID
- slot summary
- selected candidate summary
- fit bucket
- transfer mode
- confidence
- review-required state
- coverage state

### 5.2 Packet detail

Must support:

- schema version `cam.packet.v1`
- packet ID
- plan ID
- task archetype
- slot spec
- packet status
- selected candidate
- runner-ups
- no viable runner-up reason when applicable
- why selected
- why runner-up lost
- adaptation plan
- proof plan
- expected landing sites
- negative memory notes
- risk notes
- reviewer required flag
- review required reasons
- confidence basis
- coverage state

### 5.3 Compactness rule

M3 packet construction must support a compact default rendering.

The packet builder should avoid uncontrolled growth of:

- why-fit bullets
- adaptation steps
- proof gates
- failure notes

This is a product artifact, not a dump of all intermediate reasoning.

## 6. Plan API Contract

Add under `/api/v2` in `src/claw/web/dashboard_server.py`.

### 6.1 Required endpoints

- `POST /api/v2/plans`
- `GET /api/v2/plans/{plan_id}`
- `POST /api/v2/plans/{plan_id}/approve`
- `POST /api/v2/plans/{plan_id}/execute`
- `POST /api/v2/plans/{plan_id}/slots/{slot_id}/swap-candidate`
- `POST /api/v2/plans/{plan_id}/slots/{slot_id}/mine-gap`

### 6.2 Plan creation response

Must include:

- plan ID
- task archetype
- archetype confidence
- plan status
- slot summaries
- coverage summary

### 6.3 Plan detail response

Must include:

- packet summaries for all slots
- full packet details for selected slot or retrievable via packet endpoint
- global summary:
  - total slots
  - critical slots
  - weak evidence slots

### 6.4 Approval behavior

Plan approval in M3 is about state transition only.

It does not yet need full runtime mutation support beyond returning a valid handoff target for future execution integration.

## 7. Frontend UX Contract

### 7.1 Main route

Use:

- `/playground/plan/[planId]`

as the pre-mutation packet review route.

### 7.2 Existing route integration

`/playground` should:

- create plans
- route to plan review
- preserve the current task execution surface for legacy flows

### 7.3 Layout

Pre-mutation review should have:

- header strip
- slot list rail
- packet detail panel
- decision summary rail
- footer actions

### 7.4 Required visible states

The UI must visibly distinguish:

- ready
- blocked
- weak evidence
- critical review required
- no mutation yet

### 7.5 Slot-level actions

The user must be able to:

- approve selected slots
- approve all safe slots
- swap to runner-up
- ask federation
- trigger mine-gap
- block mutation
- execute approved plan

## 8. Backend / Frontend Typed Client Contract

Extend:

- `forge-ui/src/lib/api.ts`

to include:

- plan summary types
- packet summary/detail types
- slot action request/response types

Do not use untyped ad hoc JSON in the plan UI.

## 9. M3 Tests

Add tests for:

- archetype inference
- slot decomposition
- candidate ranking
- packet construction
- plan API validation
- plan route safety

Suggested files:

- `tests/planning/test_taskome.py`
- `tests/planning/test_component_ranker.py`
- `tests/planning/test_application_packet.py`
- `tests/api/test_plan_endpoints.py`
- `tests/integration/test_plan_review_non_mutating.py`

### Required assertions

- plan creation does not mutate workspace files
- each nontrivial slot has a selected candidate
- runner-up exists or explicit reason is present
- critical slots are marked
- weak evidence state is explicit
- fit bucket and transfer mode are both present and distinct
- no-help is never auto-selected

## 10. M3 Exit Criteria

M3 is complete only when:

- interactive CAM-SEQ planning produces slot decomposition before any write
- packet review route is usable
- each slot has a selected packet artifact
- weak evidence, criticality, and runner-up states are explicit
- plan APIs and typed frontend client are stable
- no legacy execution behavior regresses with flags off

## 11. Deferred To M4+

These are explicitly out of M3:

- runtime pair event persistence during execution
- landing tracking during execution
- run SSE sequencing console
- retrograde tracing
- recipe compiler
