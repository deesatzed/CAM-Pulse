# CAM-SEQ M3 Task Board

Date: 2026-04-12
Status: Ready for execution planning
Depends on:

- `docs/plans/CAM_SEQ_M0_contract.md`
- `docs/plans/CAM_SEQ_M1_spec.md`
- `docs/plans/CAM_SEQ_M2_spec.md`
- `docs/plans/CAM_SEQ_M3_spec.md`

## Usage

This is the execution-facing task board for M3.

Rules:

- Do not begin M3 execution work until M1 is complete.
- M2 should at least provide usable component memory before M3 packet logic relies on it.
- M3 is planning-only and review-only. Do not integrate runtime mutation here.
- No nontrivial interactive CAM-SEQ task should write before packet review exists.

## Ticket M3-01 — Taskome Module

Priority: P0
Parallel-safe: No

Files:

- `src/claw/planning/taskome.py`

Scope:

- Build archetype inference and slot decomposition baseline

Tasks:

- [ ] Create module
- [ ] Implement archetype inference
- [ ] Implement slot decomposition
- [ ] Implement critical-slot classification baseline
- [ ] Implement proof expectation scaffolding
- [ ] Emit stable slot IDs and slot barcodes

Dependencies:

- M1 complete
- M2 component memory available

Acceptance:

- [ ] Nontrivial benchmark-style tasks produce slot structures
- [ ] Archetype confidence is returned
- [ ] Critical slots are labeled
- [ ] Slot fields match M0/M3 contracts

## Ticket M3-02 — Component Ranker

Priority: P0
Parallel-safe: No

Files:

- `src/claw/memory/component_ranker.py`

Scope:

- Build per-slot candidate ranking and labeling

Tasks:

- [ ] Implement family/component/stack/constraint scoring
- [ ] Implement applicability and non-applicability handling
- [ ] Implement receipt precision contribution
- [ ] Implement fit bucket assignment
- [ ] Implement transfer mode assignment
- [ ] Implement confidence basis output
- [ ] Enforce no-help exclusion
- [ ] Enforce no silent stretch for critical slots

Dependencies:

- M3-01
- M2 repository/component APIs

Acceptance:

- [ ] Each slot can produce ranked candidates
- [ ] `fit_bucket` and `transfer_mode` are both populated
- [ ] `no_help` is never auto-selected
- [ ] Critical slots do not auto-select `stretch`

## Ticket M3-03 — Application Packet Builder

Priority: P0
Parallel-safe: No

Files:

- `src/claw/planning/application_packet.py`

Scope:

- Build packet summary/detail generation from slot + ranked candidates

Tasks:

- [ ] Build packet summary shape
- [ ] Build packet detail shape
- [ ] Populate selected candidate
- [ ] Populate runner-ups
- [ ] Add no viable runner-up reason support
- [ ] Build why-selected and why-runner-up-lost
- [ ] Build adaptation plan scaffold
- [ ] Build proof plan scaffold
- [ ] Add coverage state
- [ ] Add review-required reasons

Dependencies:

- M3-02

Acceptance:

- [ ] Each nontrivial slot produces a packet
- [ ] Packet includes selected candidate and runner-up or explicit no-runner-up reason
- [ ] Packet compactness remains sane
- [ ] Weak evidence is explicit

## Ticket M3-04 — Plan Persistence and APIs

Priority: P0
Parallel-safe: No

Files:

- `src/claw/web/dashboard_server.py`
- possibly repository layer extensions if needed

Scope:

- Add `/api/v2/plans` and packet retrieval endpoints

Tasks:

- [ ] `POST /api/v2/plans`
- [ ] `GET /api/v2/plans/{plan_id}`
- [ ] `POST /api/v2/plans/{plan_id}/approve`
- [ ] `POST /api/v2/plans/{plan_id}/execute`
- [ ] slot swap endpoint
- [ ] mine-gap endpoint
- [ ] packet detail endpoint if separated

Dependencies:

- M3-03

Acceptance:

- [ ] Plan creation returns slot summaries and coverage summary
- [ ] Plan detail returns packet review data
- [ ] Approval endpoints change plan state only
- [ ] Plan APIs do not mutate workspace files

## Ticket M3-05 — Typed Frontend Client For Plans

Priority: P0
Parallel-safe: Yes after M3-04

Files:

- `forge-ui/src/lib/api.ts`

Scope:

- Add typed plan and packet client calls

Tasks:

- [ ] Add plan summary types
- [ ] Add packet summary/detail types
- [ ] Add create plan client
- [ ] Add get plan client
- [ ] Add slot swap client
- [ ] Add mine-gap client
- [ ] Add approve/execute client

Dependencies:

- M3-04

Acceptance:

- [ ] Frontend can consume plan APIs without untyped payloads

## Ticket M3-06 — Playground Plan Handoff

Priority: P1
Parallel-safe: No

Files:

- `forge-ui/src/app/playground/page.tsx`

Scope:

- Add plan creation entrypoint from the existing Playground route

Tasks:

- [ ] Add task submission path that creates a plan
- [ ] Preserve legacy execution route for flags-off behavior
- [ ] Redirect or link to plan review route

Dependencies:

- M3-05

Acceptance:

- [ ] Creating a plan from Playground does not mutate files
- [ ] Legacy Playground flow still works when CAM-SEQ is off

## Ticket M3-07 — Plan Review Route

Priority: P0
Parallel-safe: No

Files:

- `forge-ui/src/app/playground/plan/[planId]/page.tsx`
- possibly new shared components

Scope:

- Build the pre-mutation packet review UI

Tasks:

- [ ] Add header strip
- [ ] Add slot list rail
- [ ] Add packet detail view
- [ ] Add decision summary rail
- [ ] Add footer action bar
- [ ] Add critical-lane styling
- [ ] Add weak-evidence state
- [ ] Add blocked state

Dependencies:

- M3-05

Acceptance:

- [ ] User can review packetized plan before mutation
- [ ] Critical slots are visibly distinct
- [ ] Weak evidence is visible
- [ ] Slot-level actions are available

## Ticket M3-08 — Plan Review Safety and Validation Tests

Priority: P0
Parallel-safe: Partial after tickets land

Files:

- `tests/planning/test_taskome.py`
- `tests/planning/test_component_ranker.py`
- `tests/planning/test_application_packet.py`
- `tests/api/test_plan_endpoints.py`
- `tests/integration/test_plan_review_non_mutating.py`

Scope:

- Add tests for planning and review safety

Tasks:

- [ ] Archetype inference tests
- [ ] Slot decomposition tests
- [ ] Ranker tests
- [ ] Packet validation tests
- [ ] Plan endpoint tests
- [ ] Review route non-mutation tests

Dependencies:

- M3-01
- M3-02
- M3-03
- M3-04

Acceptance:

- [ ] New tests pass
- [ ] Plan review is proven non-mutating
- [ ] Explicit runner-up / no-runner-up rules are enforced

## Ticket M3-09 — M3 Exit Validation

Priority: P0
Parallel-safe: No

Scope:

- Validate milestone completeness before M4

Checklist:

- [ ] Interactive planning produces slot decomposition before any write
- [ ] Plan review route is usable
- [ ] Each slot has a selected packet artifact
- [ ] Weak evidence, criticality, and runner-up state are explicit
- [ ] Plan APIs and typed client are stable
- [ ] No legacy execution behavior regresses with flags off

Dependencies:

- M3-08

Acceptance:

- [ ] M3 signed off as complete

## Suggested Execution Order

1. M3-01 Taskome Module
2. M3-02 Component Ranker
3. M3-03 Application Packet Builder
4. M3-04 Plan Persistence and APIs
5. M3-05 Typed Frontend Client For Plans
6. M3-06 Playground Plan Handoff
7. M3-07 Plan Review Route
8. M3-08 Plan Review Safety and Validation Tests
9. M3-09 M3 Exit Validation

## Review Triggers

Trigger explicit review if a ticket touches:

- `src/claw/cycle.py` (should generally not happen in M3)
- `src/claw/web/dashboard_server.py`
- `forge-ui/src/app/playground/page.tsx`

## Drift Checks During M3

- [ ] Did any M3 work start mutating runtime execution rather than planning/review?
- [ ] Did fit bucket and transfer mode remain distinct?
- [ ] Did any packet state become implicit instead of explicit?
- [ ] Did any route become dependent on raw agent text instead of structured packet data?
- [ ] Did any implementation bypass the review-before-mutation contract?
