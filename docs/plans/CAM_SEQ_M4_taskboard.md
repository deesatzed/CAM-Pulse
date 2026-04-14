# CAM-SEQ M4 Task Board

Date: 2026-04-12
Status: Ready for execution planning
Depends on:

- `docs/plans/CAM_SEQ_M0_contract.md`
- `docs/plans/CAM_SEQ_M3_spec.md`
- `docs/plans/CAM_SEQ_M4_spec.md`

## Usage

This is the execution-facing task board for M4.

Rules:

- Do not begin M4 until M3 is signed off.
- M4 is execution observability work, not retrograde diagnosis work.
- Do not replace the legacy correction loop.
- Packet identity must survive through runtime execution.

## Ticket M4-01 — Packet-Aware Execution Handoff

Priority: P0
Parallel-safe: No

Files:

- `src/claw/cycle.py`

Scope:

- Accept approved plans and selected packets as execution inputs

Tasks:

- [ ] Add approved-plan execution handoff
- [ ] Preserve selected packet identity through slot execution
- [ ] Preserve flags-off legacy path
- [ ] Preserve correction loop behavior

Dependencies:

- M3 complete

Acceptance:

- [ ] Approved plan can start execution
- [ ] Selected packet is available throughout run state
- [ ] Legacy non-CAM-SEQ path still works

Review note:

- High-risk orchestration change

## Ticket M4-02 — Pair Event Persistence

Priority: P0
Parallel-safe: No

Files:

- `src/claw/connectome/sequencer.py`
- `src/claw/cycle.py`
- `src/claw/db/repository.py`

Scope:

- Persist runtime slot-to-component pairing decisions

Tasks:

- [ ] Create initial pair event on slot execution
- [ ] Create replacement pair event on candidate swap
- [ ] Link replacement history

Dependencies:

- M4-01

Acceptance:

- [ ] Each executed slot emits a pair event
- [ ] Swapped candidates emit a new pair event with replacement linkage

## Ticket M4-03 — Landing Event Persistence

Priority: P0
Parallel-safe: No

Files:

- `src/claw/connectome/landing.py`
- `src/claw/cycle.py`
- `src/claw/db/repository.py`

Scope:

- Persist where packet-guided changes land in the target repo

Tasks:

- [ ] Record file-level landings
- [ ] Record symbol when known
- [ ] Record diff hunk ID when known
- [ ] Record ancestry origin

Dependencies:

- M4-01

Acceptance:

- [ ] Each changed landing maps to packet or explicit novel synthesis
- [ ] Landing origin is explicit

## Ticket M4-04 — Outcome Event Persistence

Priority: P0
Parallel-safe: No

Files:

- `src/claw/cycle.py`
- `src/claw/db/repository.py`

Scope:

- Persist per-slot outcome events after proof

Tasks:

- [ ] Write outcome event on success
- [ ] Write outcome event on failure
- [ ] Include verifier findings
- [ ] Include test refs when available

Dependencies:

- M4-01

Acceptance:

- [ ] Every completed slot produces an outcome event
- [ ] Success/failure is explicit

## Ticket M4-05 — Run Connectome Persistence

Priority: P0
Parallel-safe: No

Files:

- `src/claw/connectome/sequencer.py`
- `src/claw/db/repository.py`

Scope:

- Persist a run connectome and its edges

Tasks:

- [ ] Create run connectome record
- [ ] Add task/slot/component/landing/outcome nodes
- [ ] Add paired/landed/verified/replaced_by edges

Dependencies:

- M4-02
- M4-03
- M4-04

Acceptance:

- [ ] Completed runs have retrievable connectome records

## Ticket M4-06 — Run APIs and SSE

Priority: P0
Parallel-safe: No

Files:

- `src/claw/web/dashboard_server.py`

Scope:

- Add run summary, connectome, landings, and event-stream endpoints

Tasks:

- [ ] `GET /api/v2/runs/{id}`
- [ ] `GET /api/v2/runs/{id}/connectome`
- [ ] `GET /api/v2/runs/{id}/landings`
- [ ] `GET /api/v2/runs/{id}/events/stream`
- [ ] add pause endpoint
- [ ] add resume endpoint
- [ ] add swap-candidate endpoint
- [ ] add reverify endpoint

Dependencies:

- M4-05

Acceptance:

- [ ] Run APIs return typed, usable runtime data
- [ ] SSE emits causal event types

## Ticket M4-07 — Typed Frontend Run Client

Priority: P0
Parallel-safe: Yes after M4-06

Files:

- `forge-ui/src/lib/api.ts`

Scope:

- Add typed run, connectome, landing, event, and control clients

Tasks:

- [ ] Add run summary types
- [ ] Add connectome node/edge types
- [ ] Add landing types
- [ ] Add SSE envelope type
- [ ] Add run control request types

Dependencies:

- M4-06

Acceptance:

- [ ] Frontend can consume all run APIs with typed payloads

## Ticket M4-08 — Forge Run Sequencing Console

Priority: P0
Parallel-safe: No

Files:

- `forge-ui/src/app/forge/run/[id]/page.tsx`
- possibly new shared UI components

Scope:

- Turn Forge Run into a sequencing console

Tasks:

- [ ] Add Sequence tab
- [ ] Add Connectome tab
- [ ] Add Landings tab
- [ ] Add Events tab
- [ ] Add slot status strip
- [ ] Add retry delta display
- [ ] Add event feed
- [ ] Add slot control actions

Dependencies:

- M4-07

Acceptance:

- [ ] Operator can supervise run causality without reading raw logs
- [ ] Tab views expose packet/landing/outcome state clearly

## Ticket M4-09 — Runtime Sequencing Tests

Priority: P0
Parallel-safe: Partial after implementation tickets land

Files:

- `tests/integration/test_create_with_packets.py`
- `tests/integration/test_connectome_persistence.py`
- `tests/integration/test_run_event_stream.py`
- `tests/api/test_run_connectome_endpoints.py`

Scope:

- Validate packet-aware execution and sequencing APIs

Tasks:

- [ ] execution handoff test
- [ ] pair event persistence test
- [ ] landing event persistence test
- [ ] outcome event persistence test
- [ ] connectome retrieval test
- [ ] SSE event stream test

Dependencies:

- M4-01 through M4-08

Acceptance:

- [ ] New runtime sequencing tests pass
- [ ] Existing execution tests remain green or intentionally updated

## Ticket M4-10 — M4 Exit Validation

Priority: P0
Parallel-safe: No

Scope:

- Validate milestone completeness before M5

Checklist:

- [ ] Approved plans execute through packet-aware flow
- [ ] Executed slots yield pair and outcome records
- [ ] Landings are persisted with ancestry labels
- [ ] Run APIs expose connectome and events
- [ ] Forge Run is usable as sequencing console
- [ ] Operators can supervise runs without raw logs

Dependencies:

- M4-09

Acceptance:

- [ ] M4 signed off as complete

## Suggested Execution Order

1. M4-01 Packet-Aware Execution Handoff
2. M4-02 Pair Event Persistence
3. M4-03 Landing Event Persistence
4. M4-04 Outcome Event Persistence
5. M4-05 Run Connectome Persistence
6. M4-06 Run APIs and SSE
7. M4-07 Typed Frontend Run Client
8. M4-08 Forge Run Sequencing Console
9. M4-09 Runtime Sequencing Tests
10. M4-10 M4 Exit Validation

## Review Triggers

Trigger explicit review if a ticket touches:

- `src/claw/cycle.py`
- `src/claw/web/dashboard_server.py`
- `forge-ui/src/app/forge/run/[id]/page.tsx`

## Drift Checks During M4

- [ ] Did runtime events stay causal rather than transcript-like?
- [ ] Did packet identity survive through execution?
- [ ] Are landings explicit about ancestry and uncertainty?
- [ ] Did M4 avoid turning into retrograde analysis work?
- [ ] Are operators able to supervise without raw logs?
