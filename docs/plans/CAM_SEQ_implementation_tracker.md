# CAM-SEQ Implementation Tracker

Date: 2026-04-11
Status: Draft execution tracker
Source context: Derived from the CAM-SEQ roadmap and brainstorming notes in `docs/plans/CAM_SEQ_brainstorm_2026-04-11.md`

Current milestone ledger:
- `docs/plans/CAM_SEQ_milestone_table.md`

## Usage Rules

This tracker is the execution source of truth.

Rules:

- Do not start a task until all listed dependencies are complete.
- Do not mark a task done unless its definition of done is met.
- Do not open a new frontend surface before its API payload contract is stable.
- Do not change legacy CAM behavior when feature flags are off.
- Do not merge protected-file changes without explicit review.
- Do not introduce a route or endpoint that is not tied to the canonical object chain:
  Component Card -> Slot -> Application Packet -> Pair Event -> Landing Event -> Outcome Event -> Recipe

## Global Invariants

- [ ] Flags-off behavior for legacy `mine`, `create`, `validate`, `federate`, and MCP remains unchanged
- [ ] Packet and event schemas are versioned from day one
- [ ] Provenance precision is always explicit, never implied
- [ ] Critical-slot handling is visibly different from normal-slot handling
- [ ] Weak evidence, no viable runner-up, and novel synthesis are explicit states
- [ ] Methodology memory and witnessed application memory remain distinct concepts in code and UI

## Milestone M0 — Contracts Frozen

Goal:

- Freeze the object model, payload contracts, and rollout rules before implementation drift begins.

### M0.1 Canonical object contract

- [ ] Finalize object chain and names
- [ ] Finalize summary vs detail object split
- [ ] Finalize barcode vocabulary
- [ ] Finalize provenance precision vocabulary
- [ ] Finalize transfer mode vocabulary
- [ ] Finalize critical-slot vocabulary

Dependencies:

- none

Definition of done:

- one stable object chain exists
- packet, event, and recipe terms are used consistently across docs

### M0.2 Feature flag contract

- [ ] Define flags: component_cards, application_packets, connectome_seq, critical_slot_policy, a2a_packets
- [ ] Define which routes and endpoints are gated by which flags
- [ ] Define flags-off compatibility expectation

Dependencies:

- M0.1

Definition of done:

- flag behavior documented and stable before code changes begin

### M0.3 API and schema versioning contract

- [ ] Freeze `cam.packet.v1`
- [ ] Freeze `/api/v2` namespace boundary
- [ ] Freeze MCP additive-extension rule

Dependencies:

- M0.1

Definition of done:

- every new payload has a clear version strategy

Milestone gate:

- [ ] M0 approved

## Milestone M1 — Foundation and Data Layer

Goal:

- Create additive storage and typed models without changing runtime behavior.

### M1.1 Core Pydantic models

Files:

- `src/claw/core/models.py`

Tasks:

- [ ] Add Receipt
- [ ] Add ComponentCard
- [ ] Add ComponentFit
- [ ] Add ComponentLineage
- [ ] Add SlotSpec
- [ ] Add CandidateSummary
- [ ] Add ApplicationPacketSummary
- [ ] Add ApplicationPacket
- [ ] Add PairEvent
- [ ] Add LandingEvent
- [ ] Add OutcomeEvent
- [ ] Add RunConnectome
- [ ] Add CompiledRecipe

Dependencies:

- M0

Definition of done:

- all new models validate cleanly
- summary/detail models are separate
- no viable runner-up reason is representable

### M1.2 Additive schema

Files:

- `src/claw/db/schema.sql`

Tasks:

- [ ] Add component_cards
- [ ] Add component_fit
- [ ] Add component_lineages
- [ ] Add slot_instances
- [ ] Add packet persistence table if needed
- [ ] Add pair_events
- [ ] Add landing_events
- [ ] Add outcome_events
- [ ] Add run_connectomes
- [ ] Add run_connectome_edges
- [ ] Add compiled_recipes
- [ ] Add indexes for barcode columns and foreign keys

Dependencies:

- M1.1

Definition of done:

- fresh init works
- upgrade path works
- legacy methodology retrieval remains unchanged

### M1.3 Repository APIs

Files:

- `src/claw/db/repository.py`

Tasks:

- [ ] Add component CRUD/query methods
- [ ] Add lineage CRUD/query methods
- [ ] Add slot CRUD/query methods
- [ ] Add packet CRUD/query methods
- [ ] Add pair/landing/outcome persistence methods
- [ ] Add connectome query methods
- [ ] Add recipe query methods

Dependencies:

- M1.2

Definition of done:

- every new entity round-trips model -> DB -> model

### M1.4 Barcode utilities

Files:

- `src/claw/connectome/barcodes.py`

Tasks:

- [ ] Implement source barcode
- [ ] Implement family barcode
- [ ] Implement slot barcode
- [ ] Implement derived pair/locus/outcome IDs
- [ ] Document exact input fields for each ID

Dependencies:

- M1.1

Definition of done:

- stable deterministic IDs
- same component mined twice yields same stable identity

### M1.5 Lineage utilities

Files:

- `src/claw/connectome/lineage.py`

Tasks:

- [ ] Implement lineage clustering baseline
- [ ] Implement dedup counters
- [ ] Implement clone-inflation guard helpers

Dependencies:

- M1.4

Definition of done:

- near-duplicate components can map to one lineage family without hiding source receipts

### M1.6 Feature flags in config/runtime

Files:

- `src/claw/core/config.py`
- `src/claw/core/factory.py`

Tasks:

- [ ] Add feature flags to config model
- [ ] Wire flags into factory/runtime
- [ ] Ensure flags default off

Dependencies:

- M0.2

Definition of done:

- new behavior is unreachable unless enabled

Milestone gate:

- [ ] M1 approved

## Milestone M2 — Component Memory and Backfill

Goal:

- Populate component memory from existing knowledge before changing create flow.

### M2.1 Tree-sitter component extractor

Files:

- `src/claw/mining/component_extractor.py`

Tasks:

- [ ] Python extraction
- [ ] TypeScript extraction
- [ ] JavaScript extraction
- [ ] AST fingerprint generation
- [ ] File-level fallback support

Dependencies:

- M1

Definition of done:

- repos produce symbol-level component candidates where feasible

### M2.2 Optional SCIP ingestion

Files:

- `src/claw/mining/scip_loader.py`

Tasks:

- [ ] Detect optional indexes
- [ ] Ingest definition/reference data
- [ ] Upgrade provenance precision when available

Dependencies:

- M2.1

Definition of done:

- indexed repos can expose better symbol/reference precision without being required

### M2.3 Methodology -> component backfill

Files:

- `src/claw/miner.py`
- `src/claw/cli/_monolith.py`
- possibly `src/claw/cli/__init__.py`

Tasks:

- [ ] Backfill command implementation
- [ ] Link component cards to source methodologies
- [ ] Seed receipts from capability_data/source_artifacts
- [ ] Seed family labels and keywords

Dependencies:

- M2.1

Definition of done:

- current mature DB content is available through component APIs without re-mining everything

### M2.4 Component detail APIs

Files:

- `src/claw/web/dashboard_server.py`

Tasks:

- [ ] Add `/api/v2/components/{id}`
- [ ] Add `/api/v2/components/{id}/history`

Dependencies:

- M2.3

Definition of done:

- component detail and history are available to frontend and MCP

Milestone gate:

- [ ] M2 approved

## Milestone M3 — Planning and Application Packets

Goal:

- Introduce slot-aware planning and packet review before any mutation.

### M3.1 Taskome module

Files:

- `src/claw/planning/taskome.py`

Tasks:

- [ ] Archetype inference
- [ ] Slot decomposition
- [ ] Slot criticality classification
- [ ] Slot proof expectation scaffolding

Dependencies:

- M1

Definition of done:

- nontrivial tasks produce deterministic slot structures with confidence

### M3.2 Per-slot ranker

Files:

- `src/claw/memory/component_ranker.py`

Tasks:

- [ ] Ranking score inputs
- [ ] Fit bucket assignment
- [ ] Transfer mode assignment
- [ ] No-help exclusion logic
- [ ] Critical-slot anti-stretch logic

Dependencies:

- M2.3
- M3.1

Definition of done:

- each slot can produce ranked candidates with explicit fit and transfer labels

### M3.3 Application packet builder

Files:

- `src/claw/planning/application_packet.py`

Tasks:

- [ ] Packet summary builder
- [ ] Packet detail builder
- [ ] Runner-up reason builder
- [ ] Adaptation plan scaffold
- [ ] Proof plan scaffold
- [ ] Weak evidence state
- [ ] No-runner-up state

Dependencies:

- M3.2

Definition of done:

- every slot can produce a valid packet payload

### M3.4 Plans and packets API

Files:

- `src/claw/web/dashboard_server.py`

Tasks:

- [ ] `POST /api/v2/plans`
- [ ] `GET /api/v2/plans/{id}`
- [ ] `POST /api/v2/plans/{id}/approve`
- [ ] `POST /api/v2/plans/{id}/execute`
- [ ] slot swap endpoint
- [ ] mine-gap endpoint
- [ ] packet detail endpoint

Dependencies:

- M3.3

Definition of done:

- plan review can happen entirely through typed APIs with no mutation before approval

### M3.5 TS client contracts

Files:

- `forge-ui/src/lib/api.ts`

Tasks:

- [ ] Add TS types matching packet/plan contracts
- [ ] Add plan creation client calls
- [ ] Add packet retrieval calls
- [ ] Add slot action calls

Dependencies:

- M3.4

Definition of done:

- frontend can consume packet APIs without `any` types

### M3.6 Pre-mutation review UI

Files:

- `forge-ui/src/app/playground/page.tsx`
- `forge-ui/src/app/playground/plan/[planId]/page.tsx`
- possibly new shared components

Tasks:

- [ ] Add plan creation flow
- [ ] Add plan review page
- [ ] Add slot list
- [ ] Add packet detail panel
- [ ] Add decision summary rail
- [ ] Add slot-level actions
- [ ] Add critical-lane styling

Dependencies:

- M3.5

Definition of done:

- user can review and approve packetized plan before mutation

Milestone gate:

- [ ] M3 approved

## Milestone M4 — Packet-Aware Execution and Sequencing

Goal:

- Make execution slot-aware and observable as a causal sequence.

### M4.1 Cycle integration

Files:

- `src/claw/cycle.py`

Tasks:

- [ ] Integrate approved plan handoff
- [ ] Use packets in prompt assembly
- [ ] Preserve flags-off legacy path
- [ ] Record selected packet at execution start

Dependencies:

- M3

Definition of done:

- reviewed plan can execute through packet-aware flow

### M4.2 Run event and connectome persistence

Files:

- `src/claw/connectome/sequencer.py`
- `src/claw/connectome/landing.py`
- maybe `src/claw/observability/tracing.py`
- `src/claw/cycle.py`

Tasks:

- [ ] Persist pair events
- [ ] Persist landing events
- [ ] Persist outcome events
- [ ] Persist run connectome records
- [ ] Label novel synthesis explicitly

Dependencies:

- M4.1

Definition of done:

- completed runs yield packet -> landing -> outcome data

### M4.3 Run APIs and SSE

Files:

- `src/claw/web/dashboard_server.py`

Tasks:

- [ ] `GET /api/v2/runs/{id}`
- [ ] `GET /api/v2/runs/{id}/connectome`
- [ ] `GET /api/v2/runs/{id}/landings`
- [ ] `GET /api/v2/runs/{id}/events/stream`
- [ ] slot pause/resume/swap/reverify endpoints

Dependencies:

- M4.2

Definition of done:

- frontend can observe execution and subscribe to causal events

### M4.4 Forge Run sequencing console

Files:

- `forge-ui/src/app/forge/run/[id]/page.tsx`
- `forge-ui/src/lib/api.ts`

Tasks:

- [ ] Sequence tab
- [ ] Connectome tab
- [ ] Landings tab
- [ ] Events tab
- [ ] slot control actions

Dependencies:

- M4.3

Definition of done:

- operator can supervise causality during execution without reading raw logs

Milestone gate:

- [ ] M4 approved

## Milestone M5 — Retrograde, Distill, and Knowledge History

Goal:

- Turn run outcomes into diagnosis, negative memory, and reusable history.

### M5.1 Retrograde engine

Files:

- `src/claw/connectome/retrograde.py`

Tasks:

- [ ] failure-root analysis
- [ ] cause chain generation
- [ ] runner-up comparison
- [ ] confidence scoring

Dependencies:

- M4

Definition of done:

- seeded failures produce candidate cause chains with slot/component linkage

### M5.2 Distill and negative memory writeback

Files:

- `src/claw/connectome/recipes.py`
- `src/claw/cycle.py`
- `src/claw/db/repository.py`

Tasks:

- [ ] negative memory updates
- [ ] fit updates
- [ ] recipe candidate generation
- [ ] gap backlog generation

Dependencies:

- M5.1

Definition of done:

- completed runs update durable memory beyond pass/fail

### M5.3 Evolution run APIs

Files:

- `src/claw/web/dashboard_server.py`

Tasks:

- [ ] `GET /api/v2/runs/{id}/retrograde`
- [ ] `GET /api/v2/runs/{id}/distill`
- [ ] mining-mission creation endpoint from gaps

Dependencies:

- M5.2

Definition of done:

- frontend can fetch post-run diagnosis and distillation

### M5.4 Evolution run UI

Files:

- `forge-ui/src/app/evolution/page.tsx`
- `forge-ui/src/app/evolution/run/[runId]/page.tsx`
- `forge-ui/src/lib/api.ts`

Tasks:

- [ ] overview links from `/evolution`
- [ ] Retrograde tab
- [ ] Distill tab
- [ ] Gaps tab

Dependencies:

- M5.3

Definition of done:

- user can inspect what failed, what changed, and what should be learned

### M5.5 Knowledge history routes

Files:

- `forge-ui/src/app/knowledge/components/[componentId]/page.tsx`
- `forge-ui/src/app/knowledge/packets/[packetId]/page.tsx`
- `forge-ui/src/lib/api.ts`
- `src/claw/web/dashboard_server.py`

Tasks:

- [ ] component detail route
- [ ] packet detail route
- [ ] packet reuse history
- [ ] component pair/landing history

Dependencies:

- M5.2

Definition of done:

- durable memory objects are navigable across runs

Milestone gate:

- [ ] M5 approved

## Milestone M6 — Critical-Slot Policy Lane

Goal:

- Make high-risk work governed and auditable.

### M6.1 Critical-slot classifier

- [ ] classify auth/session
- [ ] classify migrations
- [ ] classify sandboxing
- [ ] classify secret handling
- [ ] classify permissioning
- [ ] classify deserialization
- [ ] classify external execution

Dependencies:

- M3.1

Definition of done:

- critical slots are labeled at planning time

### M6.2 Policy engine

Files:

- `src/claw/security/policy.py`
- `src/claw/cycle.py`
- `src/claw/verifier.py`

Tasks:

- [ ] no silent stretch enforcement
- [ ] review-required reasons
- [ ] waiver path
- [ ] unresolved severity blocking

Dependencies:

- M6.1

Definition of done:

- risky slots behave differently from normal slots

### M6.3 Static analysis integration

Files:

- `src/claw/verifier.py`
- possibly new helper modules

Tasks:

- [ ] Semgrep hook
- [ ] CodeQL hook
- [ ] map findings back to slots/packets

Dependencies:

- M6.2

Definition of done:

- critical-slot proof gates can run and persist results

Milestone gate:

- [ ] M6 approved

## Milestone M7 — Federation, Mining Missions, MCP, Recipes

Goal:

- Use the broader CAM swarm to improve packet quality and reuse.

### M7.1 Mining mission queue

Files:

- `src/claw/pulse/*`
- `src/claw/miner.py`
- `src/claw/web/dashboard_server.py`

Tasks:

- [ ] create mission model
- [ ] queue from weak-evidence plan state
- [ ] queue from retrograde gaps
- [ ] expose mission status

Dependencies:

- M5

Definition of done:

- weak coverage and failure gaps can become explicit acquisition tasks

### M7.2 Component-aware federation

Files:

- `src/claw/community/federation.py`

Tasks:

- [ ] packet-ready component search
- [ ] direct_fit vs pattern_transfer labels
- [ ] precision-preserving results

Dependencies:

- M2
- M3

Definition of done:

- cross-brain answers can improve a weak slot without hiding provenance quality

### M7.3 Recipe compiler

Files:

- `src/claw/connectome/recipes.py`

Tasks:

- [ ] detect repeated success motifs
- [ ] store archetype-specific recipes
- [ ] expose recipe retrieval

Dependencies:

- M5

Definition of done:

- repeated archetypes can emit recipe candidates or promoted recipes

### M7.4 MCP additive extensions

Files:

- `src/claw/mcp_server.py`

Tasks:

- [ ] `claw_decompose_task`
- [ ] `claw_build_application_packet`
- [ ] `claw_get_run_connectome`
- [ ] `claw_trace_failure`
- [ ] `claw_promote_recipe`
- [ ] `claw_queue_mining_mission`

Dependencies:

- M3
- M4
- M5

Definition of done:

- external MCP consumers can use packet and trace capabilities without changing existing tool semantics

Milestone gate:

- [ ] M7 approved

## Milestone M8 — Benchmarks and Proof

Goal:

- Prove the wedge and prevent self-deception.

### M8.1 Pilot suite

- [ ] choose 6 pilot tasks
- [ ] create gold slot graphs
- [ ] create seeded failures
- [ ] create baseline CAM comparison harness

Dependencies:

- M3 minimum

Definition of done:

- pilot suite can measure slot quality and retrograde usefulness

### M8.2 Full benchmark suite

- [ ] expand to full 24-task grid
- [ ] add greenfield / bugfix / transfer coverage
- [ ] add critical-slot labels
- [ ] add acceptable families and proof expectations

Dependencies:

- M5

Definition of done:

- reproducible connectome benchmark exists

### M8.3 Ablation and proof artifacts

- [ ] baseline vs component cards
- [ ] baseline vs packets
- [ ] baseline vs connectome learning
- [ ] baseline vs recipe compiler
- [ ] demo artifact creation

Dependencies:

- M8.2

Definition of done:

- measurable contribution of each layer can be shown

Milestone gate:

- [ ] M8 approved

## Acceptance Gates

These must pass before broad rollout.

- [ ] Additive non-regression with flags off
- [ ] Packet schema validation
- [ ] Receipt completeness
- [ ] Slot decomposition quality on pilot suite
- [ ] Candidate ranking quality on pilot suite
- [ ] Packet completeness
- [ ] Landing mapping coverage
- [ ] Outcome writeback completeness
- [ ] Negative memory visible and durable
- [ ] Retrograde quality on seeded failures
- [ ] Critical-slot safety
- [ ] Federation labeling quality
- [ ] Recipe reuse does not reduce correctness
- [ ] Observability completeness

## Drift Checks Per Week

- [ ] Are we still centered on packet and event objects rather than generic logs?
- [ ] Did any route get added that is not tied to the canonical chain?
- [ ] Did any implementation blur methodology memory with witnessed application memory?
- [ ] Did any critical-slot behavior silently downgrade into normal behavior?
- [ ] Did any payload lose explicit provenance precision or confidence basis?
- [ ] Are weak-evidence and novel-synthesis still explicit states in UX and API?

## Immediate Next Executable Steps

1. M0.1 canonical object contract
2. M0.2 feature flag contract
3. M0.3 API/schema versioning contract
4. M1.1 core Pydantic models
5. M1.2 additive schema
6. M1.3 repository APIs
7. M1.4 barcodes
8. M1.5 lineage
9. M2.1 component extractor
10. M2.3 methodology -> component backfill
