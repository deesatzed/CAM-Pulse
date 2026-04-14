# CAM-SEQ M0 Contract

Date: 2026-04-11
Status: Frozen draft for implementation start
Scope: Milestone M0 contract for CAM-SEQ

## Purpose

This document freezes the minimum contract required to begin implementation without semantic drift.

It defines:

- the canonical object chain
- the vocabulary that must remain stable through v1
- the feature-flag contract
- the API and schema versioning contract
- the route and MCP extension boundary
- the states that must be explicit everywhere

Anything not fixed here should be treated as intentionally deferred, not loosely assumed.

## 1. Product Contract

CAM-SEQ is an additive extension to CAM-Pulse.

It is not:

- a replacement for methodology memory
- a replacement for the existing orchestration loop
- a replacement for federation
- a replacement for the current MCP surface
- a second frontend application

It is:

- an autonomous engineering control plane with causal memory
- centered on inspectable pre-write decisions, causal execution events, and post-run learning

The product standard for v1 is:

- before mutation, a reviewer can approve the decision
- during mutation, an operator can supervise the causality
- after mutation, the system can explain what it learned

## 2. Canonical Object Chain

The entire CAM-SEQ system is organized around this canonical chain:

1. Component Card
2. Slot
3. Application Packet
4. Pair Event
5. Landing Event
6. Outcome Event
7. Recipe

No new route, endpoint, or UI surface should be added unless it clearly inspects or acts on one or more objects in this chain.

### 2.1 Object Roles

#### Component Card

Purpose:

- a precise reusable implementation unit with receipts

Must represent:

- where reusable knowledge came from
- what family it belongs to
- how precise its provenance is

#### Slot

Purpose:

- a concrete part of the current task that must be solved

Must represent:

- what the task needs
- its constraints
- its criticality
- its proof expectations

#### Application Packet

Purpose:

- the primary pre-mutation decision artifact

Must represent:

- what component CAM plans to apply to a slot
- what runner-up was considered
- why the choice was made
- what adaptation is expected
- what proof is required

#### Pair Event

Purpose:

- the runtime record that a slot was paired with a selected component

Must represent:

- actual runtime choice, not just a candidate list

#### Landing Event

Purpose:

- the runtime record of where a selected component’s influence landed in the target repo

Must represent:

- target file/symbol/hunk when known
- ancestry classification of the landing

#### Outcome Event

Purpose:

- the sequenced result of proof and verification

Must represent:

- pass/fail
- verifier findings
- test linkage
- memory updates

#### Recipe

Purpose:

- distilled reusable build pattern learned from repeated success

Must represent:

- archetype-specific slot order, preferred families, proof expectations, and disallowed conditions

## 3. Memory Layer Separation

The following concepts must remain separate in code, API, and UI:

### Methodologies

Role:

- conceptual theories
- narrative patterns
- higher-level reusable problem/solution memory

### Component Cards

Role:

- precise implementation units with receipts

### Sequenced Events

Role:

- witnessed proof that a component was actually used for a slot in a real run

Rule:

- methodology memory must never be silently treated as witnessed application memory

## 4. Stable Vocabulary

These terms are fixed for v1.

### 4.1 Fit Bucket

Allowed values:

- `will_help`
- `may_help`
- `stretch`
- `no_help`

Meaning:

- expected utility for a slot under current constraints

### 4.2 Transfer Mode

Allowed values:

- `direct_fit`
- `pattern_transfer`
- `heuristic_fallback`

Meaning:

- how direct the transfer is

Rule:

- fit bucket and transfer mode are distinct and must never be conflated

### 4.3 Provenance Precision

Allowed values:

- `precise_symbol`
- `symbol`
- `file`
- `chunk`

Meaning:

- how precise the receipt and landing attribution are

Rule:

- provenance precision must always be explicit

### 4.4 Slot Risk

Allowed values:

- `normal`
- `critical`

### 4.5 Packet Status

Allowed values:

- `draft`
- `review_required`
- `approved`
- `blocked`
- `executing`
- `verified`
- `failed`
- `quarantined`

## 5. Explicit States Required Everywhere

These conditions must never be implicit:

- weak evidence
- no viable runner-up
- novel synthesis
- critical slot
- review required
- provenance precision
- confidence basis

### 5.1 Weak Evidence

Represents:

- low coverage
- weak family support
- weak or sparse receipts
- low-confidence direct-fit evidence

### 5.2 No Viable Runner-Up

Represents:

- the system could not find a meaningful alternative candidate

This must be represented explicitly, not as a missing field.

### 5.3 Novel Synthesis

Represents:

- a changed hunk or symbol that cannot be honestly attributed to a selected component lineage

This must be allowed as a first-class ancestry label.

## 6. Canonical Packet Contract

The Application Packet is the primary supervision artifact.

It must exist in two forms:

- summary
- detail

### 6.1 Application Packet Summary

Purpose:

- lightweight object for slot lists and overviews

Must include:

- packet ID
- slot summary
- selected candidate summary
- fit bucket
- transfer mode
- confidence
- packet completeness state
- review required state

### 6.2 Application Packet Detail

Purpose:

- full review artifact for a slot before mutation

Must include:

- schema version
- packet ID
- plan ID
- task archetype
- full slot spec
- packet status
- selected candidate
- runner-ups or explicit no viable runner-up reason
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

## 7. Canonical Event Contract

### 7.1 Pair Event

Must include:

- pair identity
- slot ID / slot barcode
- selected component ID / source barcode
- packet ID
- timestamp
- confidence snapshot
- replacement history reference when applicable

### 7.2 Landing Event

Must include:

- locus identity
- run ID
- slot ID
- packet ID
- file path
- symbol when known
- diff hunk ID when known
- ancestry classification

Allowed ancestry classifications:

- `adapted_component`
- `novel_synthesis`
- `mixed_ancestry`
- `manual_override`

### 7.3 Outcome Event

Must include:

- outcome identity
- run ID
- slot ID
- packet ID
- pass/fail state
- verifier findings
- test linkage
- negative memory updates
- recipe candidacy signal

## 8. Confidence Contract

Confidence values are allowed, but confidence alone is insufficient.

Every packet and retrograde explanation must include `confidence_basis`.

Allowed confidence basis categories for v1:

- `heuristic_match`
- `family_match`
- `component_type_match`
- `stack_match`
- `constraint_match`
- `prior_pair_history`
- `deduped_lineage_support`
- `precise_receipt`
- `file_level_fallback`
- `critical_slot_penalty`

Rule:

- a numeric confidence without basis is invalid for CAM-SEQ objects

## 9. Coverage State Contract

Coverage state must be explicit in plans and post-run analysis.

Allowed values:

- `covered`
- `weak`
- `uncovered`
- `quarantined`
- `clone_inflated`

## 10. Feature Flag Contract

The following flags are frozen for v1:

- `component_cards`
- `application_packets`
- `connectome_seq`
- `critical_slot_policy`
- `a2a_packets`

### 10.1 Flag Semantics

#### component_cards

Enables:

- component storage
- component search
- component detail
- methodology-to-component backfill

#### application_packets

Enables:

- taskome planning
- slot decomposition
- packet review
- plan APIs and routes

#### connectome_seq

Enables:

- pair events
- landing events
- outcome events
- run connectome APIs and UI

#### critical_slot_policy

Enables:

- critical-slot classifier
- policy lane
- no-silent-stretch rules
- proof gate enforcement

#### a2a_packets

Enables:

- optional packet exchange with specialist ganglia or external agents

### 10.2 Flags-Off Compatibility Rule

With all CAM-SEQ flags off:

- current mine behavior remains unchanged
- current create behavior remains unchanged
- current verify behavior remains unchanged
- current federate behavior remains unchanged
- current MCP tools retain existing semantics

This rule is non-negotiable.

## 11. API Versioning Contract

### 11.1 HTTP API Namespace

All new CAM-SEQ APIs must live under:

- `/api/v2/...`

Legacy `/api/...` routes remain valid and unchanged unless explicitly migrated later.

### 11.2 Payload Versioning

All durable packet and event payloads must include a schema version field when the object is serialized as a durable record.

Frozen v1 packet version:

- `cam.packet.v1`

### 11.3 Summary vs Detail Rule

Do not reuse detail payloads as list payloads.

There must be separate summary contracts for:

- packet lists
- component lists
- run summaries

## 12. Route Contract

The v1 route plan is frozen at this level:

Existing extended:

- `/playground`
- `/forge/run/[runId]`
- `/evolution`
- `/mining`
- `/knowledge`

New:

- `/playground/plan/[planId]`
- `/evolution/run/[runId]`
- `/knowledge/components/[componentId]`
- `/knowledge/packets/[packetId]`

Rule:

- do not add additional top-level nav categories for CAM-SEQ in v1

## 13. MCP Contract

The MCP extension model is additive.

Do not change the semantics of existing tools.

New CAM-SEQ tools are allowed to be added alongside the existing surface.

Frozen v1 tool names:

- `claw_decompose_task`
- `claw_build_application_packet`
- `claw_get_run_connectome`
- `claw_trace_failure`
- `claw_promote_recipe`
- `claw_queue_mining_mission`

Rule:

- MCP responses should return machine-usable packet/event payloads, not decorative UI prose

## 14. Mutation Boundary Contract

The boundary between planning and mutation is first-class.

Required states:

- no mutation yet
- review required
- approved for mutation
- executing

Rule:

- in interactive CAM-SEQ mode, no nontrivial task begins writing until slot decomposition and packet review exist

## 15. Deferred Questions

The following are intentionally not frozen in M0:

- exact lineage clustering algorithm details
- exact slot archetype taxonomy breadth
- exact recipe promotion thresholds
- exact benchmark suite composition beyond pilot direction
- exact visual presentation details inside each route
- exact A2A transport implementation

These may evolve later without violating M0 as long as they respect the frozen object contract.

## 16. M0 Exit Criteria

M0 is complete only when:

- the canonical object chain is stable
- the vocabulary above is accepted
- feature flags are fixed
- `/api/v2` boundary is fixed
- packet and event versioning rules are fixed
- the mutation boundary rule is accepted
- all future implementation work can be traced back to this contract
