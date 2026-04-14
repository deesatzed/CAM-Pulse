# CAM-SEQ Brainstorm Notes

Date: 2026-04-11
Location: /Volumes/WS4TB/RNACAM
Scope: Early brainstorming, product framing, pre-plan notes for adapting CAM-Pulse into a barcode-native component application system.

## Core Reframe

Do not build CAM 2 as a smarter repo searcher or prettier coding shell.

Build CAM-SEQ: Component Application Mapping by Sequencing.

The product shift is:

- from repo similarity to component-level causal reuse
- from generic memory cards to witnessed slot-to-component pairing events
- from source provenance only to provenance plus landing-site plus verifier outcome
- from retrieval logs to a dataset of software application episodes

## Why This Is Potentially Novel

The real novelty is not "better retrieval."

The novelty is:

- stable component identity
- task-slot identity
- pairing at moment of use
- exact landing-site preservation
- sequenced verification outcome
- retrograde tracing from failure back to likely source pairing/adaptation
- lineage-aware dedup so cloned code does not inflate evidence

This should make the system able to say:

- this exact component was paired to this exact slot type
- it landed in these files/symbols/hunks
- it passed or failed under these constraints
- these adaptations were required
- this is a real repeated success, not clone inflation

## Biological Analogy That Matters

The neuroscience analogy is useful as a design guide:

- MAPseq analog: where did this component project into the target repo?
- BARseq analog: where exactly did it land in place?
- Connectome-seq analog: which slot-component pairings actually formed and worked?
- Rabies-barcode analog: retrograde tracing from failure back to likely causal source

The barcode metaphor is only useful if it grounds concrete product behavior.

## Current CAM-Pulse Strengths To Build On

Observed in repo:

- methodology memory and attribution in SQLite/sqlite-vec/FTS5
- six-step orchestration loop with correction retries
- methodology links and outcome feedback
- cross-ganglion federation via read-only FTS5
- trace extraction for routing/grouping/composition
- Forge/Evolution/Federation UI surfaces
- MCP server exposing memory, verification, and routing

Relevant files:

- src/claw/db/schema.sql
- src/claw/core/models.py
- src/claw/db/repository.py
- src/claw/memory/semantic.py
- src/claw/cycle.py
- src/claw/community/federation.py
- src/claw/training/trace_extractor.py

## Mature Knowledge Base Observations

From clawDBA:

- top-level clawDBA/claw.db is empty
- useful knowledge is in clawDBA/instances/*/claw.db
- those DBs are rich in capability_data and source_artifacts
- they have little or no live usage/link/bandit history yet

Implication:

- v1 fit buckets and edge memory should start heuristic/bootstrap-first
- online learning should update them over time

## Product Thesis

The end product should not be "better RAG for code."

It should be a software connectomics engine that sequences how working software is assembled from reusable parts.

The moat is the dataset:

slot <-> component <-> landing site <-> verifier outcome <-> recipe motif

## Main Product Artifact

The primary artifact should be the Application Packet, not the retrieval result.

Each nontrivial slot should produce a packet containing:

- slot identity and goal
- selected component with exact receipt
- at least one runner-up and reason rejected
- fit bucket and confidence
- adaptation plan
- proof plan
- risk notes
- expected landing sites

This should be inspectable by humans, usable by agents, and writable to persistent memory.

## Candidate Identity / Event Model

Conceptually important IDs:

- source_barcode
- family_barcode
- slot_barcode
- pair_barcode
- locus_barcode
- outcome_barcode

Likely implementation simplification for v1:

- make source_barcode, family_barcode, slot_barcode canonical
- treat pair/locus/outcome IDs as derived event identifiers

Core event chain:

1. source identified
2. slot identified
3. pair selected
4. landing observed
5. outcome sequenced

## Key Concepts To Operationalize

### Component Genome Layer

Mine component cards with:

- exact receipt
- component type
- abstract jobs
- constraints
- applicability / non-applicability
- dependency / framework fit
- test evidence
- adaptation notes
- risk notes
- lineage family
- prior pairing outcomes

### Taskome Layer

Every task decomposes into slots before retrieval.

Each slot should carry:

- slot type
- abstract job
- required constraints
- preferred stack
- criticality
- expected proof
- anti-patterns

### Barcoded Application Engine

Retrieve candidates per slot using:

- family match
- component type match
- stack fit
- constraint fit
- prior pair success/failure
- adaptation burden
- receipt precision
- source quality
- test evidence

### Outcome Sequencer

Persist:

- pair events
- landing events
- outcome events
- run connectomes

Use OTel as live trace substrate, DB as canonical memory.

### Connectome Intelligence Layer

Higher-order capabilities:

- retrograde failure tracing
- negative memory
- recipe compilation
- lesion studies later

### Critical Slot Policy Lane

Critical slots:

- auth
- migrations
- sandboxing
- secret handling
- deserialization
- permissions
- external execution

Critical-slot rules:

- no silent stretch
- stricter verifier gates
- Semgrep / CodeQL / human review flags where appropriate

## Strongest Demo Idea

The best early demo is not "better retrieval."

The best demo is:

1. decompose a real feature into slots
2. emit application packets
3. generate code
4. show where selected components landed
5. run verification
6. trace a failure backward to a likely bad pairing/adaptation
7. swap to the runner-up or corrected adaptation
8. re-run and show learned memory update

## Pre-Plan / Phasing

### Phase 1

Component genome and barcodes.

Touch:

- schema
- models
- repository
- miner
- semantic memory

Exit:

- component cards with receipts
- family labels
- barcode support
- backfill from existing methodologies

### Phase 2

Slot-aware create and application packets.

Touch:

- cycle
- retrieval/ranking logic
- prompt assembly
- Forge Run

Exit:

- slot-by-slot application packets emitted before generation

### Phase 3

Outcome sequencer and run connectome.

Touch:

- cycle
- tracing
- connectome persistence
- Knowledge / Forge views

Exit:

- every run has pair, landing, and outcome records

### Phase 4

Retrograde tracing and critical policy lane.

Touch:

- verifier
- evolution UI
- policy logic

Exit:

- failures trace back to likely source pairing/adaptation path

### Phase 5

Recipe compiler and federated packet exchange.

Touch:

- trace extraction
- federation
- MCP surface
- recipe compiler

Exit:

- repeated task archetypes benefit from compiled recipes

## Non-Negotiable Expectations

- every nontrivial slot must produce one selected application packet
- every nontrivial slot should preserve at least one explicit runner-up
- every selected packet must include receipts, adaptation plan, and proof plan
- every selected packet must declare precision level: symbol-level or file-level fallback
- every build must persist a run connectome
- every failure must update negative memory
- every critical slot must enforce stricter policy gates
- repeated success patterns should become recipe-eligible

## Open Design Questions

1. What exactly counts as a landing event?
2. How do we infer influence between source component and generated diff safely?
3. What is the minimum viable lineage clustering algorithm?
4. How compact can an application packet be while remaining useful?
5. How many slot types can be handled heuristically before LLM decomposition is required?

## Immediate Next Brainstorm Targets

- exact schema for application packet and event chain
- UX surfaces for packet inspection and failure tracing
- competitive differentiation memo vs 2026 coding tools
- benchmark plan for slot-level retrieval and retrograde diagnosis

## UX Gap Brainstorm (2026 Landscape)

Even with 2026 coding agents becoming strong on SWE-bench-family evaluations and widely available across terminal, IDE, PR, and cloud surfaces, the real UX gaps still appear to be:

### 1. Selection Transparency Gap

Current tools are good at acting, but weak at showing:

- which candidate patterns were considered
- why one was selected
- why runner-ups were rejected
- which evidence was direct-fit vs stretch

Real user need:

- inspectable pre-write decision artifacts, especially for nontrivial or risky changes

### 2. Subproblem Decomposition Gap

Most tools still present work as one task thread or one PR thread.

Real user need:

- explicit task slots
- per-slot ownership
- per-slot evidence
- per-slot risk and proof expectations

### 3. Provenance Precision Gap

Existing tools can usually cite files, snippets, commits, logs, or PR steps.
They rarely preserve a precise chain from:

- source component
- to selected slot
- to landing site
- to verifier outcome

Real user need:

- exact, trustworthy provenance with declared precision level

### 4. Landing-Site Visibility Gap

Users can inspect diffs, but usually cannot answer:

- where a reused idea actually landed
- which symbols/hunks/tests descended from which source component

Real user need:

- projection / landing views, not just diff views

### 5. Failure Explanation Gap

Current tools can show logs, traces, and failing tests.
They usually do not show:

- which slot likely failed
- which selected component likely caused it
- which adaptation step likely broke
- which runner-up might have worked better

Real user need:

- retrograde failure tracing, not just more logs

### 6. Negative Memory Gap

Most tools remember what worked, but weakly encode:

- what repeatedly failed
- under which constraints
- with which stack mismatches

Real user need:

- persistent "do not apply here" memory that is slot-conditioned

### 7. Clone Inflation Gap

Repo mining and retrieval systems overcount duplicated code patterns.

Real user need:

- lineage-aware confidence and deduplicated evidence counts

### 8. Risk-Lane UX Gap

Current products have general controls, permissions, sandboxes, and PR review workflows.
They are less strong at making critical-path risk first-class at the slot level.

Real user need:

- critical-slot UI lane with stricter gates, explicit warnings, and proof requirements

### 9. Long-Horizon Supervision Gap

Modern tools increasingly support parallel background agents and cloud execution.
However, supervising them still often collapses into:

- logs
- commits
- PR comments
- generic progress indicators

Real user need:

- a control plane that makes long-running work intelligible at the decision level, not just the execution level

### 10. Learning UX Gap

Users rarely get a visible answer to:

- what did the system learn from this run?
- which future tasks are now safer or faster?
- what became forbidden, promoted, or recipe-worthy?

Real user need:

- explicit post-run learning summaries tied to slots, pairings, and policies

## Candidate Build Backlog (User Draft Under Evaluation)

The current candidate build backlog proposes:

- additive schema and migration path
- feature-flagged rollout
- Tree-sitter-first component extraction
- optional SCIP ingestion for precision
- methodology-to-component backfill
- taskome + slot decomposition
- per-slot retrieval and application packets
- sequencing via OTel plus DB-backed canonical event memory
- critical-slot policy lane using Semgrep / CodeQL
- component-aware federation
- recipe compiler
- 24-task benchmark suite with gold slots and seeded failures

Suggested first implementation order in that draft:

001 -> 002 -> 003 -> 004 -> 007 -> 010 -> 011 -> 012 -> 013 -> 014 -> 016 -> 017 -> 021 -> 022 -> 023 -> 028

This should be assessed as an ambitious but not yet final execution plan.

## Narrative Refinement Under Evaluation

Key proposed narrative upgrades:

- the scarce thing is no longer basic code generation, but supervision of autonomous software work
- CAM should be framed as an autonomous engineering control plane with causal memory
- the canonical object spine should be:
  Component Card -> Slot -> Application Packet -> Pair Event -> Landing Event -> Outcome Event -> Recipe
- Mine should be active knowledge metabolism, not passive ingestion
- UX should be organized by decision time:
  before mutation / during mutation / after mutation

Suggested stronger product sentence:

CAM continuously learns reusable software genes from the wild, applies them to new work through inspectable pre-write decision packets, sequences what actually landed where, traces failures backward causally, and distills repeatable build recipes under policy.

## UX Contract Candidate: Three Deliverable Moments

Current candidate UX contract organizes the product around three moments:

1. Review before mutation
2. Observe during mutation
3. Learn after mutation

Mapped to proposed surface upgrades:

- Playground Plan tab / preflight review for pre-mutation packet review
- Forge Run as live sequencing console during mutation
- Evolution Lab as retrograde + distill workbench after mutation

Shared object contract proposed across all three moments:

- Component Card
- Slot
- Application Packet
- Pair Event
- Landing Event
- Outcome Event
- Recipe

Core product expectation from this framing:

- before mutation, a reviewer can approve the decision
- during mutation, an operator can supervise the causality
- after mutation, the system can explain what it learned

## Integrated Roadmap Draft

### Product Aim

Build CAM-SEQ as an additive extension to CAM-Pulse:

- an autonomous engineering control plane with causal memory
- centered on the canonical chain:
  Component Card -> Slot -> Application Packet -> Pair Event -> Landing Event -> Outcome Event -> Recipe
- using existing CAM surfaces rather than creating a parallel app

### Rollout Principle

No drift rules:

- keep legacy mine/create/verify/federate/MCP behavior unchanged with flags off
- only add new tables and modules before changing orchestration behavior
- make Application Packet the first-class artifact before building deeper connectome analytics
- do not ship route proliferation before packet and event contracts are stable
- do not claim breakthrough until packet flow, event persistence, and retrograde tracing are all working on benchmark tasks

### Phase 0 — Alignment and Contracts

Goal:

- freeze vocabulary, object contracts, and rollout guardrails

Deliverables:

- canonical object contract
- schema versioning policy
- feature flags
- provenance precision taxonomy
- confidence basis taxonomy
- critical-slot taxonomy

Expected function level:

- no user-visible CAM-SEQ functionality yet
- only design and typed contracts

Expected UX level:

- none beyond internal design docs and payload examples

Exit criteria:

- all teams use the same packet/event vocabulary
- packet summary vs packet detail split is agreed
- route plan and API v2 boundary agreed

### Phase 1 — Foundation and Component Memory

Goal:

- create additive storage and backfilled component memory without changing default CAM execution

Core work:

- feature flags
- additive schema and migrations
- Pydantic + TypeScript core types
- barcode utilities
- lineage utilities
- methodology -> component backfill
- Tree-sitter component extraction
- minimal component search APIs

Expected function level:

- component cards exist and round-trip cleanly
- existing methodologies can be viewed through a component layer
- source and family barcodes are stable
- provenance precision is explicit

Expected UX level:

- light knowledge-layer additions only
- component detail can be inspected, but no packet planning yet

Exit criteria:

- fresh install and upgrade both succeed
- legacy CAM behavior unchanged with flags off
- at least one mature DB can be backfilled into component cards
- component receipts are inspectable via API

### Phase 2 — Pre-Mutation Packet Review

Goal:

- make Application Packet the primary supervision artifact before mutation

Core work:

- task archetype inference
- slot decomposition
- per-slot candidate retrieval
- packet builder
- /api/v2/plans
- /api/v2/packets
- Playground Plan review surface
- approve / swap / mine-gap / federation request actions

Expected function level:

- no nontrivial task writes code before slot decomposition exists
- each slot gets a selected candidate and runner-up or explicit no-runner-up reason
- critical slots are marked before mutation

Expected UX level:

- compact, reviewable packet-first preflight
- slot-level approval and override
- weak evidence surfaced explicitly

Exit criteria:

- user can review and approve slot packets before write
- packets include receipt, fit basis, adaptation plan, proof plan, risk notes
- executing a reviewed plan hands off to a run ID without re-planning

### Phase 3 — In-Flight Sequencing Console

Goal:

- let operators supervise causal assembly during mutation

Core work:

- run event model
- minimal pair persistence
- landing persistence
- SSE event stream
- /api/v2/runs/{id}
- /api/v2/runs/{id}/events
- /api/v2/runs/{id}/connectome
- /api/v2/runs/{id}/landings
- Forge Run tabs: Sequence / Connectome / Landings / Events

Expected function level:

- every write maps to a slot and packet or is labeled novel_synthesis
- retries record what changed
- blocked states are explicit

Expected UX level:

- run strip with current slot and risk state
- slot lanes with retry deltas
- clickable connectome edges
- landing map with ancestry labels
- compact causal event stream

Exit criteria:

- operator can pause, swap, and reverify at slot level
- every benchmark run emits traceable packet -> landing -> outcome events

### Phase 4 — Post-Run Retrograde and Learning

Goal:

- turn outcomes into diagnosis, negative memory, and recipe candidates

Core work:

- outcome event writeback
- negative memory objects
- retrograde tracer
- distill endpoints
- /api/v2/runs/{id}/retrograde
- /api/v2/runs/{id}/distill
- /evolution/run/[runId]
- knowledge packet history and component history routes

Expected function level:

- failures can be traced back to likely slot/component/adaptation causes
- successful runs update fit and recipe candidacy
- gap backlog items can be created from weak coverage or repeated failure

Expected UX level:

- Retrograde tab for cause chains
- Distill tab for promotions, downgrades, and negative memory
- Gaps tab feeding mining missions

Exit criteria:

- seeded failures produce useful top-3 cause chains
- users can compare selected component vs runner-up after the fact
- negative memory is a first-class visible object

### Phase 5 — Critical-Slot Policy Lane

Goal:

- make risky work meaningfully harder and more explicit than ordinary work

Core work:

- critical-slot classifier
- policy engine
- semgrep/codeql integration hooks
- review-required reason model
- explicit waiver path

Expected function level:

- critical slots cannot silently use stretch
- critical slots must satisfy required proof gates or be waived
- unresolved severe findings block acceptance

Expected UX level:

- visible risk lane before mutation
- visible proof-gate state during mutation
- visible policy findings after mutation

Exit criteria:

- critical-slot safety gates pass on benchmark suite
- waivers are auditable and explicit

### Phase 6 — Federation, Mining Missions, and Distillation

Goal:

- use CAM’s existing swarm structure to improve weak slots and repeated archetypes

Core work:

- component-aware federation
- mining mission queue from plan review and retrograde
- recipe compiler
- packet-aware MCP tools

Expected function level:

- weak slots can request federation support or mining support
- repeated successful archetypes emit compiled recipes
- MCP can build packets and trace failures

Expected UX level:

- weak-evidence actions become productive, not dead ends
- recipe promotion appears in Distill mode

Exit criteria:

- cross-brain component retrieval is labeled direct_fit vs pattern_transfer
- repeated archetypes show measurable reuse benefit

### Phase 7 — Proof, Benchmarks, and Hardening

Goal:

- prove the system works and lock in the wedge

Core work:

- pilot benchmark suite first
- then full 24-task suite
- ablation harness
- proof artifacts
- demo runs

Expected function level:

- clear uplift over baseline CAM on slot precision, context efficiency, learning uplift, or retrograde quality

Expected UX level:

- stable enough for reproducible demos and internal operator use

Exit criteria:

- release gates pass
- at least several breakthrough goals are met

### Recommended Execution Slices

#### Slice A — Contracts

- packet schemas
- packet summary schemas
- event schemas
- route contracts
- MCP payload contracts

#### Slice B — Data layer

- schema
- models
- repository
- barcode + lineage utilities

#### Slice C — Knowledge layer

- backfill
- extractor
- component APIs
- component detail route

#### Slice D — Plan layer

- archetype inference
- slot decomposition
- ranking
- packet builder
- plan APIs
- plan review route

#### Slice E — Run layer

- run state model
- event persistence
- landings
- SSE
- Forge Run tabs

#### Slice F — Learning layer

- retrograde
- negative memory
- distill
- packet history
- component history

#### Slice G — Policy + federation

- critical-slot lane
- semgrep/codeql
- component federation
- mining mission queue
- recipe compiler

### Functional Expectations By Stage

#### Minimum viable function

- component cards with receipts
- slot decomposition
- packet review before write
- selected candidate + runner-up
- codegen informed by packets
- minimal pair/outcome persistence

#### Strong function

- landing attribution
- retry deltas
- retrograde cause chains
- negative memory
- critical-slot gating

#### Breakthrough function

- stable recipe distillation
- cross-brain packet support
- targeted mining missions from failures
- measurable second-run uplift

### UX Expectations By Stage

#### Minimum viable UX

- packet-first review page
- slot-level override
- explicit weak evidence

#### Strong UX

- sequencing console with slot lanes and event feed
- landing map
- causal post-run analysis

#### Breakthrough UX

- operator can review before mutation, supervise causality during mutation, and see learned policy after mutation without reading raw logs

### No-Drift Checklist

Before each phase starts:

- confirm the canonical object chain is unchanged
- confirm flags-off behavior remains legacy-compatible
- confirm route additions still map to existing information architecture
- confirm schema and API versions are explicit

Before each implementation PR:

- identify which canonical object is being introduced or extended
- define payload shape first
- define validation rules first
- define test cases first
- avoid mixing route work and deep orchestration work unless required

After each implementation slice:

- verify packet/event payloads round-trip cleanly
- verify no hidden mutation occurs in review-only routes
- verify all new UI states have explicit loading/error/empty states
- verify weak evidence, no-runner-up, and novel synthesis are explicit states
- verify critical-slot behavior differs visibly from normal slots

Before promoting a phase:

- run smoke tests with flags off
- run targeted tests for new flags on
- compare benchmark pilot against baseline CAM
- check whether the UX still centers on packets and events rather than logs and chat

Anti-drift guardrails:

- do not add a new route unless it clearly inspects or acts on the canonical object chain
- do not add free-form agent text where a structured packet or event should exist
- do not treat methodology memory and witnessed application memory as the same thing
- do not let federation hide provenance precision
- do not let critical slots silently downgrade into ordinary slots
- do not let post-run analysis stop at pass/fail plus diff

## File-By-File Implementation Checklist

### Backend contracts and data layer

#### src/claw/db/schema.sql

Additive only:

- add component_cards
- add component_fit
- add component_lineages
- add slot_instances
- add application_packets or packet records if persisted separately
- add pair_events
- add landing_events
- add outcome_events
- add run_connectomes
- add run_connectome_edges
- add compiled_recipes

Checklist:

- keep legacy methodology tables untouched
- make nullable fields explicit for partial receipts
- index barcode columns and foreign keys
- add created_at / updated_at consistently
- avoid irreversible assumptions about landing precision in v1

#### src/claw/core/models.py

Add new Pydantic models for:

- Receipt
- ComponentCard
- ComponentFit
- ComponentLineage
- SlotSpec
- CandidateSummary
- ApplicationPacketSummary
- ApplicationPacket
- PairEvent
- LandingEvent
- OutcomeEvent
- RunConnectome
- CompiledRecipe

Checklist:

- preserve existing methodology models untouched
- version packet schema from day one
- separate summary vs detail models
- include explicit no-runner-up reason
- include confidence_basis and provenance_precision

#### src/claw/db/repository.py

Add CRUD / query methods for:

- components
- lineages
- slots
- packets
- pair events
- landing events
- outcome events
- connectomes
- recipes

Checklist:

- start with simple transactional methods
- keep retrieval methods narrow and typed
- do not hide precision levels in repository return values
- support history lookups for component and packet detail pages

#### src/claw/connectome/barcodes.py

Create:

- source barcode generation
- family barcode generation
- slot barcode generation
- pair / locus / outcome ID helpers

Checklist:

- deterministic and stable
- document exact input fields for each barcode
- keep implementation side-effect free

#### src/claw/connectome/lineage.py

Create:

- lineage clustering helpers
- dedup helpers
- clone-inflation controls

Checklist:

- content hash first
- AST fingerprint optional
- no false precision claims

### Knowledge and mining layer

#### src/claw/mining/component_extractor.py

Create:

- Tree-sitter-based component extraction for Python / TS / JS first

Checklist:

- emit symbol-level candidates where possible
- attach AST fingerprint
- attach file-level fallback when symbol extraction is weak
- keep extraction deterministic

#### src/claw/mining/scip_loader.py

Create later-stage optional support:

- ingest SCIP indexes when available

Checklist:

- optional, not mandatory
- annotate precision uplift explicitly

#### src/claw/miner.py

Extend:

- methodology -> component extraction path
- receipt normalization
- family labeling hooks
- coverage gap reporting hooks

Checklist:

- preserve current mine behavior with flags off
- backfill from existing methodology/capability data before requiring re-mine
- surface weak evidence instead of inventing precision

#### src/claw/memory/semantic.py

Extend:

- component search APIs
- packet-oriented retrieval helpers
- outcome writeback hooks for component-level learning

Checklist:

- keep methodology retrieval intact
- keep methodology memory distinct from witnessed application memory

### Planning and packet layer

#### src/claw/planning/taskome.py

Create:

- archetype inference
- slot decomposition
- critical-slot detection

Checklist:

- deterministic baseline first
- confidence output required
- criticality output required

#### src/claw/memory/component_ranker.py

Create:

- per-slot component ranking
- fit bucket assignment
- transfer mode assignment

Checklist:

- do not conflate fit bucket with transfer mode
- no_help never auto-selectable
- critical slots cannot silently choose stretch

#### src/claw/planning/application_packet.py

Create:

- packet summary builder
- packet detail builder
- runner-up reasoning
- adaptation/proof plan scaffolding

Checklist:

- packet is compact by default
- selected candidate mandatory
- runner-up mandatory unless explicit no-viable-runner-up reason
- weak evidence and review-required reasons explicit

#### src/claw/cycle.py

Extend carefully:

- plan generation before mutation
- packet-aware create flow
- slot-aware execution handoff
- minimal pair / outcome persistence
- later run event emission

Checklist:

- do not break existing correction loop
- do not mutate before plan approval in interactive CAM-SEQ mode
- preserve legacy create path with flags off
- keep slot-level overrides possible

### API and web backend layer

#### src/claw/web/dashboard_server.py

Add `/api/v2` endpoints incrementally:

- plans
- packets
- runs
- connectome
- landings
- retrograde
- distill
- components
- packet history

Checklist:

- keep old `/api/*` endpoints intact
- use typed request/response contracts
- prefer additive handlers before major refactors
- SSE first for run events

#### src/claw/mcp_server.py

Add new MCP tools:

- claw_decompose_task
- claw_build_application_packet
- claw_get_run_connectome
- claw_trace_failure
- claw_promote_recipe
- claw_queue_mining_mission

Checklist:

- additive only
- existing tool semantics unchanged
- return machine-usable packet/event payloads, not UI prose

### Frontend client and routes

#### forge-ui/src/lib/api.ts

Add typed client support for:

- plan APIs
- packet APIs
- run APIs
- connectome APIs
- landing APIs
- retrograde APIs
- distill APIs
- component history APIs

Checklist:

- define TS types first
- keep summary vs detail payloads separate
- keep SSE helper minimal and explicit

#### forge-ui/src/app/playground/page.tsx

Extend or link to plan review flow:

- create plan
- show redirect or embedded Plan tab
- preserve existing execution UX until plan mode is stable

Checklist:

- review-only interactions must not mutate files
- packet review becomes visible before execution

#### forge-ui/src/app/playground/plan/[planId]/page.tsx

Create:

- pre-mutation packet review page

Checklist:

- slot list left rail
- packet detail center
- decision summary right rail
- slot-level actions
- critical slots visibly distinct

#### forge-ui/src/app/forge/run/[id]/page.tsx

Extend:

- Sequence tab
- Connectome tab
- Landings tab
- Events tab

Checklist:

- every retry shows delta
- event feed stays causal, not chat-like
- landings include ancestry label

#### forge-ui/src/app/evolution/page.tsx

Extend top-level overview:

- recent retrograde-worthy failures
- recipe candidates
- gap backlog summaries

Checklist:

- do not overload the page with per-run detail
- deep link into per-run analysis

#### forge-ui/src/app/evolution/run/[runId]/page.tsx

Create:

- Retrograde / Distill / Gaps tabs

Checklist:

- start from failure root when present
- show runner-up comparison
- show mining mission creation action

#### forge-ui/src/app/knowledge/components/[componentId]/page.tsx

Create:

- durable component detail

Checklist:

- receipts
- lineage
- pair history
- landing history
- negative memory
- recipe memberships

#### forge-ui/src/app/knowledge/packets/[packetId]/page.tsx

Create:

- durable packet detail

Checklist:

- selected candidate
- runner-ups
- adaptation plan
- proof plan
- reuse history
- final outcomes

### Suggested build order (file-oriented)

1. src/claw/core/models.py
2. src/claw/db/schema.sql
3. src/claw/db/repository.py
4. src/claw/connectome/barcodes.py
5. src/claw/connectome/lineage.py
6. src/claw/miner.py plus src/claw/mining/component_extractor.py
7. src/claw/planning/taskome.py
8. src/claw/memory/component_ranker.py
9. src/claw/planning/application_packet.py
10. src/claw/web/dashboard_server.py (`/api/v2/plans`, `/api/v2/packets`)
11. forge-ui/src/lib/api.ts
12. forge-ui/src/app/playground/page.tsx
13. forge-ui/src/app/playground/plan/[planId]/page.tsx
14. src/claw/cycle.py
15. src/claw/web/dashboard_server.py (`/api/v2/runs`, events, connectome, landings)
16. forge-ui/src/app/forge/run/[id]/page.tsx
17. src/claw/connectome/retrograde.py
18. src/claw/web/dashboard_server.py (retrograde/distill/component history)
19. forge-ui/src/app/evolution/run/[runId]/page.tsx
20. forge-ui/src/app/knowledge/components/[componentId]/page.tsx
21. forge-ui/src/app/knowledge/packets/[packetId]/page.tsx
22. src/claw/mcp_server.py
