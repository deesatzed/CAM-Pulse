# CAM-SEQ M4 Implementation Spec

Date: 2026-04-12
Status: Draft
Depends on:

- `docs/plans/CAM_SEQ_M0_contract.md`
- `docs/plans/CAM_SEQ_M1_spec.md`
- `docs/plans/CAM_SEQ_M2_spec.md`
- `docs/plans/CAM_SEQ_M3_spec.md`

## Scope

M4 covers:

- packet-aware execution handoff
- pair event persistence during execution
- landing event persistence during execution
- outcome event writeback baseline
- run connectome persistence
- run status and event APIs
- in-flight sequencing console UX

M4 does not cover:

- retrograde diagnosis logic
- recipe compilation
- critical-slot policy lane hardening
- federation packet exchange

The purpose of M4 is to turn the reviewed plan into a causally observable run.

## 1. Design Goals

### 1.1 Reviewed plans become executable plans

M4 must connect pre-mutation planning to execution without losing packet identity.

Every selected packet that is approved for execution must remain identifiable throughout the run.

### 1.2 Runtime events must be causal, not chat-like

The runtime event model is not a transcript.

It must capture:

- what slot is active
- what packet is selected
- what changed after retry
- where code landed
- what proof failed or passed

### 1.3 Novel synthesis must be allowed

Not every change will cleanly descend from one selected component.

M4 must support explicit `novel_synthesis` and `mixed_ancestry` landing classifications.

### 1.4 Execution observability before diagnosis

M4 should make runs observable before attempting full retrograde diagnosis.

The user should be able to supervise what happened during a run even if the system cannot yet fully explain why later.

## 2. Execution Integration Contract

Primary execution integration point:

- `src/claw/cycle.py`

M4 should not replace the current correction loop.
It should layer packet-aware execution on top of it.

### 2.1 Execution inputs

M4 execution starts from:

- approved plan ID
- approved slot IDs
- selected packet IDs per slot

### 2.2 Execution outputs

M4 execution must persist:

- run ID
- pair events
- landing events
- outcome events
- run connectome record
- run summary state

## 3. Pair Event Contract In Practice

At execution start for a slot:

- create one pair event tying slot to selected component through the selected packet

On swap or retry candidate replacement:

- create a new pair event
- link to the replaced pair event via `replacement_of_pair_id`

Rule:

- pair events are about runtime choices, not ranked candidate lists

## 4. Landing Event Contract In Practice

Landing events should be written when CAM can attribute a write to:

- file
- symbol when known
- diff hunk when known
- packet
- slot

### 4.1 Landing origin values for M4

Allowed:

- `adapted_component`
- `novel_synthesis`
- `mixed_ancestry`
- `manual_override`

### 4.2 Minimum viable landing

M4 minimum landing support:

- file path required
- slot required
- packet required
- origin required

Nice-to-have in M4:

- symbol
- diff hunk ID

## 5. Outcome Event Contract In Practice

Outcome events should be written per slot once proof concludes.

They must include:

- slot success/failure
- verifier findings
- test references when available
- negative memory updates placeholder
- recipe eligibility placeholder

Rule:

- one completed slot should always yield an outcome event, even if proof fails

## 6. Run Connectome Contract

M4 should persist one run connectome per execution.

### 6.1 Nodes

M4 minimum node kinds:

- task
- slot
- component
- landing
- outcome

### 6.2 Edges

M4 minimum edge kinds:

- `paired`
- `landed`
- `verified`
- `replaced_by` when a retry swaps candidates

### 6.3 M4 goal

The connectome does not need to be “smart” yet.
It needs to be complete and inspectable.

## 7. Runtime API Contract

Add under `/api/v2`:

- `GET /api/v2/runs/{run_id}`
- `GET /api/v2/runs/{run_id}/connectome`
- `GET /api/v2/runs/{run_id}/landings`
- `GET /api/v2/runs/{run_id}/events/stream`
- slot control endpoints for:
  - pause
  - resume
  - swap-candidate
  - reverify

### 7.1 Run summary response

Must include:

- run ID
- status
- current slot ID
- retry count
- completed slot count
- total slot count
- failed gate count

### 7.2 Connectome response

Must include:

- nodes
- edges
- node kinds
- edge types

### 7.3 Landings response

Must include:

- locus identity
- file path
- symbol when known
- diff hunk ID when known
- slot ID
- packet ID
- origin

### 7.4 Event stream response

Use SSE first.

Required event types:

- `packet_selected`
- `adaptation_applied`
- `landing_recorded`
- `proof_gate_failed`
- `candidate_swapped`
- `retry_started`
- `retry_resolved`
- `run_completed`

## 8. Forge Run UX Contract

Primary route:

- `/forge/run/[runId]`

M4 should turn this route into the sequencing console rather than creating a parallel route.

### 8.1 Required tabs

- `Sequence`
- `Connectome`
- `Landings`
- `Events`

### 8.2 Sequence tab

Must show:

- current slot
- slot status
- selected packet
- retry count
- blocked reason
- verifier status
- what changed since last attempt

### 8.3 Connectome tab

Must show:

- task -> slot -> component -> landing -> outcome graph

Click behavior must open detail about:

- formation time
- packet ID
- prior pair history if available
- replacement lineage if any

### 8.4 Landings tab

Must show:

- file path
- symbol when known
- slot
- packet
- selected component
- ancestry label
- linked tests when available

### 8.5 Events tab

Must show:

- compact causal event stream

Rule:

- do not display generic assistant transcript as the primary event feed

## 9. Runtime Control Contract

M4 should allow limited slot-level control:

- pause one slot
- resume one slot
- swap selected candidate for runner-up
- re-run verification for a slot

These controls are supervisory actions, not arbitrary workflow edits.

## 10. Frontend Typed Client Contract

Extend:

- `forge-ui/src/lib/api.ts`

to add:

- run summary types
- connectome types
- landing types
- SSE event envelope types
- slot-control request/response types

## 11. M4 Tests

Suggested files:

- `tests/integration/test_create_with_packets.py`
- `tests/integration/test_connectome_persistence.py`
- `tests/integration/test_run_event_stream.py`
- `tests/api/test_run_connectome_endpoints.py`

### Required assertions

- approved plans can hand off to execution
- each executed slot emits pair events
- completed slots emit outcome events
- changed landings map to packet or explicit novel synthesis
- retries emit delta-bearing events
- run connectome can be retrieved through API
- SSE event stream reconnects cleanly

## 12. M4 Exit Criteria

M4 is complete only when:

- approved plans execute through packet-aware flow
- each executed slot yields pair and outcome records
- landings are persisted with ancestry labels
- `/forge/run/[runId]` acts as a useful sequencing console
- operator can supervise runs without relying on raw logs

## 13. Deferred To M5+

These are explicitly out of M4:

- retrograde cause-chain analysis
- recipe promotion
- gap backlog creation from failures
- component history learning UI
- full critical-slot policy hard blocking
