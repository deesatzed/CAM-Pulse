# CAM-SEQ M1 Implementation Spec

Date: 2026-04-12
Status: Draft
Depends on: `docs/plans/CAM_SEQ_M0_contract.md`

## Scope

M1 covers:

- core Pydantic models
- additive database schema
- repository APIs
- barcode utilities
- lineage utilities
- feature-flag wiring

M1 does not cover:

- task decomposition
- application packets as runtime planning artifacts
- run sequencing UI
- retrograde tracing
- recipe compilation

The purpose of M1 is to create a stable, additive data foundation for CAM-SEQ without changing default CAM behavior.

## 1. Design Goals

### 1.1 Additive only

Do not mutate the semantics of:

- methodologies
- methodology retrieval
- current `mine`
- current `create`
- current verification
- current federation

M1 should only add new storage, models, and utilities.

### 1.2 Stable identity before deep intelligence

The first thing CAM-SEQ needs is stable identity:

- source identity
- family identity
- lineage identity

It does not yet need sophisticated learning.

### 1.3 Explicit uncertainty

M1 must support partial receipts and partial precision honestly.

That means:

- symbol may be missing
- line range may be missing
- commit may be missing
- provenance precision must be explicit

### 1.4 Summary/detail separation

Even at the model layer, do not collapse lightweight list payloads and detailed record payloads into one type.

## 2. New Backend Modules

Create these modules in M1:

- `src/claw/connectome/barcodes.py`
- `src/claw/connectome/lineage.py`

Create these modules if implementation benefits from separation in M1:

- `src/claw/mining/component_extractor.py`

Do not create packet, retrograde, or recipe modules in M1.

## 3. Pydantic Model Spec

All model names below should be added to `src/claw/core/models.py`.

### 3.1 Shared enums / literals

Add enums or typed literal-compatible constants for:

- `FitBucket`
  - `will_help`
  - `may_help`
  - `stretch`
  - `no_help`

- `TransferMode`
  - `direct_fit`
  - `pattern_transfer`
  - `heuristic_fallback`

- `ProvenancePrecision`
  - `precise_symbol`
  - `symbol`
  - `file`
  - `chunk`

- `SlotRisk`
  - `normal`
  - `critical`

- `CoverageState`
  - `covered`
  - `weak`
  - `uncovered`
  - `quarantined`
  - `clone_inflated`

- `AdaptationBurden`
  - `low`
  - `medium`
  - `high`

- `LandingOrigin`
  - `adapted_component`
  - `novel_synthesis`
  - `mixed_ancestry`
  - `manual_override`

### 3.2 Receipt

Purpose:

- precise or partial source identity for a reusable component

Fields:

- `source_barcode: str`
- `family_barcode: str`
- `lineage_id: str`
- `repo: str`
- `commit: Optional[str] = None`
- `file_path: str`
- `symbol: Optional[str] = None`
- `line_start: Optional[int] = None`
- `line_end: Optional[int] = None`
- `content_hash: str`
- `provenance_precision: ProvenancePrecision`

Rules:

- `repo`, `file_path`, `content_hash`, `provenance_precision` required
- `symbol` optional
- line numbers optional

### 3.3 ComponentCard

Purpose:

- precise reusable implementation unit derived from mining or backfill

Fields:

- `id: str`
- `methodology_id: Optional[str] = None`
- `title: str`
- `component_type: str`
- `abstract_jobs: list[str] = []`
- `receipt: Receipt`
- `language: Optional[str] = None`
- `frameworks: list[str] = []`
- `dependencies: list[str] = []`
- `constraints: list[str] = []`
- `inputs: list[dict[str, Any]] = []`
- `outputs: list[dict[str, Any]] = []`
- `test_evidence: list[str] = []`
- `applicability: list[str] = []`
- `non_applicability: list[str] = []`
- `adaptation_notes: list[str] = []`
- `risk_notes: list[str] = []`
- `keywords: list[str] = []`
- `coverage_state: CoverageState = "weak"`
- `success_count: int = 0`
- `failure_count: int = 0`
- `created_at: datetime`
- `updated_at: datetime`

Rules:

- keep fields JSON-friendly
- do not include packet-specific runtime fields here

### 3.4 ComponentLineage

Purpose:

- deduplicated lineage family across cloned or near-duplicate source components

Fields:

- `id: str`
- `family_barcode: str`
- `canonical_content_hash: str`
- `canonical_title: Optional[str] = None`
- `language: Optional[str] = None`
- `lineage_size: int = 1`
- `deduped_support_count: int = 1`
- `clone_inflated: bool = False`
- `created_at: datetime`
- `updated_at: datetime`

### 3.5 ComponentFit

Purpose:

- learned or heuristic fit estimate for a component under a slot/task pattern

Fields:

- `id: str`
- `component_id: str`
- `task_archetype: Optional[str] = None`
- `component_type: Optional[str] = None`
- `slot_signature: Optional[str] = None`
- `fit_bucket: FitBucket`
- `transfer_mode: TransferMode`
- `confidence: float`
- `confidence_basis: list[str] = []`
- `success_count: int = 0`
- `failure_count: int = 0`
- `evidence_count: int = 0`
- `notes: list[str] = []`
- `updated_at: datetime`

Rule:

- M1 can persist heuristic rows even before full learning exists

### 3.6 ComponentCardSummary

Purpose:

- lightweight list/search payload for component explorer views

Fields:

- `id: str`
- `title: str`
- `component_type: str`
- `language: Optional[str] = None`
- `family_barcode: str`
- `repo: str`
- `file_path: str`
- `symbol: Optional[str] = None`
- `provenance_precision: ProvenancePrecision`
- `success_count: int = 0`
- `failure_count: int = 0`
- `coverage_state: CoverageState`

### 3.7 SlotSpec

Purpose:

- defined in M1 for contract freezing, even if used more fully in M3

Fields:

- `slot_id: str`
- `slot_barcode: str`
- `name: str`
- `abstract_job: str`
- `risk: SlotRisk = "normal"`
- `constraints: list[str] = []`
- `target_stack: list[str] = []`
- `proof_expectations: list[str] = []`

### 3.8 CandidateSummary

Purpose:

- defined in M1 for packet contract freezing, but not heavily used until M3

Fields:

- `component_id: str`
- `title: str`
- `fit_bucket: FitBucket`
- `transfer_mode: TransferMode`
- `confidence: float`
- `confidence_basis: list[str] = []`
- `receipt: Receipt`
- `why_fit: list[str] = []`
- `known_failure_modes: list[str] = []`
- `prior_success_count: int = 0`
- `prior_failure_count: int = 0`
- `deduped_lineage_count: int = 0`
- `adaptation_burden: AdaptationBurden = "medium"`

### 3.9 ApplicationPacketSummary

Purpose:

- frozen in M1 for future API/UI work

Fields:

- `packet_id: str`
- `plan_id: str`
- `task_archetype: str`
- `slot_id: str`
- `slot_name: str`
- `status: str`
- `selected_component_id: str`
- `fit_bucket: FitBucket`
- `transfer_mode: TransferMode`
- `confidence: float`
- `review_required: bool`
- `coverage_state: CoverageState`

### 3.10 PairEvent, LandingEvent, OutcomeEvent, RunConnectome, CompiledRecipe

Purpose:

- freeze field direction in M1 so DB and API work do not drift later

These can be added to models now but only partially used in M1.

Minimal fields:

#### PairEvent

- `id: str`
- `run_id: str`
- `slot_id: str`
- `slot_barcode: str`
- `packet_id: str`
- `component_id: str`
- `source_barcode: str`
- `confidence: float`
- `confidence_basis: list[str] = []`
- `replacement_of_pair_id: Optional[str] = None`
- `created_at: datetime`

#### LandingEvent

- `id: str`
- `run_id: str`
- `slot_id: str`
- `packet_id: str`
- `file_path: str`
- `symbol: Optional[str] = None`
- `diff_hunk_id: Optional[str] = None`
- `origin: LandingOrigin`
- `created_at: datetime`

#### OutcomeEvent

- `id: str`
- `run_id: str`
- `slot_id: str`
- `packet_id: str`
- `success: bool`
- `verifier_findings: list[str] = []`
- `test_refs: list[str] = []`
- `negative_memory_updates: list[str] = []`
- `recipe_eligible: bool = False`
- `created_at: datetime`

#### RunConnectome

- `id: str`
- `run_id: str`
- `task_archetype: Optional[str] = None`
- `status: str`
- `created_at: datetime`

#### CompiledRecipe

- `id: str`
- `task_archetype: str`
- `recipe_name: str`
- `recipe_json: dict[str, Any]`
- `sample_size: int = 0`
- `is_active: bool = False`
- `created_at: datetime`
- `updated_at: datetime`

## 4. Database Schema Spec

All tables are additive and should be added to `src/claw/db/schema.sql`.

### 4.1 component_lineages

Columns:

- `id TEXT PRIMARY KEY`
- `family_barcode TEXT NOT NULL`
- `canonical_content_hash TEXT NOT NULL`
- `canonical_title TEXT`
- `language TEXT`
- `lineage_size INTEGER NOT NULL DEFAULT 1`
- `deduped_support_count INTEGER NOT NULL DEFAULT 1`
- `clone_inflated INTEGER NOT NULL DEFAULT 0`
- `created_at TEXT DEFAULT ...`
- `updated_at TEXT DEFAULT ...`

Indexes:

- `idx_component_lineages_family`
- `idx_component_lineages_hash`

### 4.2 component_cards

Columns:

- `id TEXT PRIMARY KEY`
- `methodology_id TEXT REFERENCES methodologies(id) ON DELETE SET NULL`
- `lineage_id TEXT NOT NULL REFERENCES component_lineages(id) ON DELETE CASCADE`
- `source_barcode TEXT NOT NULL UNIQUE`
- `family_barcode TEXT NOT NULL`
- `title TEXT NOT NULL`
- `component_type TEXT NOT NULL`
- `abstract_jobs_json TEXT NOT NULL DEFAULT '[]'`
- `repo TEXT NOT NULL`
- `commit_sha TEXT`
- `file_path TEXT NOT NULL`
- `symbol_name TEXT`
- `line_start INTEGER`
- `line_end INTEGER`
- `content_hash TEXT NOT NULL`
- `provenance_precision TEXT NOT NULL`
- `language TEXT`
- `frameworks_json TEXT NOT NULL DEFAULT '[]'`
- `dependencies_json TEXT NOT NULL DEFAULT '[]'`
- `constraints_json TEXT NOT NULL DEFAULT '[]'`
- `inputs_json TEXT NOT NULL DEFAULT '[]'`
- `outputs_json TEXT NOT NULL DEFAULT '[]'`
- `test_evidence_json TEXT NOT NULL DEFAULT '[]'`
- `applicability_json TEXT NOT NULL DEFAULT '[]'`
- `non_applicability_json TEXT NOT NULL DEFAULT '[]'`
- `adaptation_notes_json TEXT NOT NULL DEFAULT '[]'`
- `risk_notes_json TEXT NOT NULL DEFAULT '[]'`
- `keywords_json TEXT NOT NULL DEFAULT '[]'`
- `coverage_state TEXT NOT NULL DEFAULT 'weak'`
- `success_count INTEGER NOT NULL DEFAULT 0`
- `failure_count INTEGER NOT NULL DEFAULT 0`
- `created_at TEXT DEFAULT ...`
- `updated_at TEXT DEFAULT ...`

Indexes:

- `idx_component_cards_family`
- `idx_component_cards_lineage`
- `idx_component_cards_repo`
- `idx_component_cards_type`
- `idx_component_cards_language`

### 4.3 component_fit

Columns:

- `id TEXT PRIMARY KEY`
- `component_id TEXT NOT NULL REFERENCES component_cards(id) ON DELETE CASCADE`
- `task_archetype TEXT`
- `component_type TEXT`
- `slot_signature TEXT`
- `fit_bucket TEXT NOT NULL`
- `transfer_mode TEXT NOT NULL`
- `confidence REAL NOT NULL DEFAULT 0.0`
- `confidence_basis_json TEXT NOT NULL DEFAULT '[]'`
- `success_count INTEGER NOT NULL DEFAULT 0`
- `failure_count INTEGER NOT NULL DEFAULT 0`
- `evidence_count INTEGER NOT NULL DEFAULT 0`
- `notes_json TEXT NOT NULL DEFAULT '[]'`
- `updated_at TEXT DEFAULT ...`

Indexes:

- `idx_component_fit_component`
- `idx_component_fit_archetype`
- `idx_component_fit_slot_signature`

### 4.4 slot_instances

M1 support only. Full use later.

Columns:

- `id TEXT PRIMARY KEY`
- `slot_barcode TEXT NOT NULL`
- `task_archetype TEXT`
- `name TEXT NOT NULL`
- `abstract_job TEXT NOT NULL`
- `risk TEXT NOT NULL DEFAULT 'normal'`
- `constraints_json TEXT NOT NULL DEFAULT '[]'`
- `target_stack_json TEXT NOT NULL DEFAULT '[]'`
- `proof_expectations_json TEXT NOT NULL DEFAULT '[]'`
- `created_at TEXT DEFAULT ...`

Indexes:

- `idx_slot_instances_barcode`
- `idx_slot_instances_archetype`

### 4.5 application_packets

Persisted packet records for plan review and history.

Columns:

- `id TEXT PRIMARY KEY`
- `schema_version TEXT NOT NULL`
- `plan_id TEXT NOT NULL`
- `task_archetype TEXT NOT NULL`
- `slot_id TEXT NOT NULL`
- `status TEXT NOT NULL`
- `packet_json TEXT NOT NULL`
- `selected_component_id TEXT NOT NULL REFERENCES component_cards(id) ON DELETE RESTRICT`
- `review_required INTEGER NOT NULL DEFAULT 0`
- `coverage_state TEXT NOT NULL DEFAULT 'weak'`
- `created_at TEXT DEFAULT ...`
- `updated_at TEXT DEFAULT ...`

Indexes:

- `idx_application_packets_plan`
- `idx_application_packets_slot`
- `idx_application_packets_selected`

### 4.6 pair_events

Columns:

- `id TEXT PRIMARY KEY`
- `run_id TEXT NOT NULL`
- `slot_id TEXT NOT NULL`
- `slot_barcode TEXT NOT NULL`
- `packet_id TEXT NOT NULL REFERENCES application_packets(id) ON DELETE CASCADE`
- `component_id TEXT NOT NULL REFERENCES component_cards(id) ON DELETE RESTRICT`
- `source_barcode TEXT NOT NULL`
- `confidence REAL NOT NULL DEFAULT 0.0`
- `confidence_basis_json TEXT NOT NULL DEFAULT '[]'`
- `replacement_of_pair_id TEXT`
- `created_at TEXT DEFAULT ...`

### 4.7 landing_events

Columns:

- `id TEXT PRIMARY KEY`
- `run_id TEXT NOT NULL`
- `slot_id TEXT NOT NULL`
- `packet_id TEXT NOT NULL REFERENCES application_packets(id) ON DELETE CASCADE`
- `file_path TEXT NOT NULL`
- `symbol_name TEXT`
- `diff_hunk_id TEXT`
- `origin TEXT NOT NULL`
- `created_at TEXT DEFAULT ...`

### 4.8 outcome_events

Columns:

- `id TEXT PRIMARY KEY`
- `run_id TEXT NOT NULL`
- `slot_id TEXT NOT NULL`
- `packet_id TEXT NOT NULL REFERENCES application_packets(id) ON DELETE CASCADE`
- `success INTEGER NOT NULL`
- `verifier_findings_json TEXT NOT NULL DEFAULT '[]'`
- `test_refs_json TEXT NOT NULL DEFAULT '[]'`
- `negative_memory_updates_json TEXT NOT NULL DEFAULT '[]'`
- `recipe_eligible INTEGER NOT NULL DEFAULT 0`
- `created_at TEXT DEFAULT ...`

### 4.9 run_connectomes

Columns:

- `id TEXT PRIMARY KEY`
- `run_id TEXT NOT NULL UNIQUE`
- `task_archetype TEXT`
- `status TEXT NOT NULL`
- `created_at TEXT DEFAULT ...`

### 4.10 run_connectome_edges

Columns:

- `id TEXT PRIMARY KEY`
- `connectome_id TEXT NOT NULL REFERENCES run_connectomes(id) ON DELETE CASCADE`
- `source_node TEXT NOT NULL`
- `target_node TEXT NOT NULL`
- `edge_type TEXT NOT NULL`
- `metadata_json TEXT NOT NULL DEFAULT '{}'`

### 4.11 compiled_recipes

Columns:

- `id TEXT PRIMARY KEY`
- `task_archetype TEXT NOT NULL`
- `recipe_name TEXT NOT NULL`
- `recipe_json TEXT NOT NULL DEFAULT '{}'`
- `sample_size INTEGER NOT NULL DEFAULT 0`
- `is_active INTEGER NOT NULL DEFAULT 0`
- `created_at TEXT DEFAULT ...`
- `updated_at TEXT DEFAULT ...`

## 5. Repository API Spec

These methods should be added to `src/claw/db/repository.py`.

### 5.1 Lineages

- `save_component_lineage(lineage: ComponentLineage) -> ComponentLineage`
- `get_component_lineage(lineage_id: str) -> Optional[ComponentLineage]`
- `find_lineage_by_hash(canonical_content_hash: str) -> Optional[ComponentLineage]`
- `list_lineage_components(lineage_id: str, limit: int = 100) -> list[ComponentCardSummary]`

### 5.2 Components

- `save_component_card(card: ComponentCard) -> ComponentCard`
- `get_component_card(component_id: str) -> Optional[ComponentCard]`
- `list_component_cards(limit: int = 100, language: Optional[str] = None) -> list[ComponentCardSummary]`
- `list_components_for_methodology(methodology_id: str) -> list[ComponentCardSummary]`
- `search_component_cards_text(query: str, limit: int = 20, language: Optional[str] = None) -> list[ComponentCardSummary]`
- `update_component_outcome(component_id: str, success: bool) -> None`

### 5.3 Component fit

- `save_component_fit(fit: ComponentFit) -> ComponentFit`
- `list_component_fit(component_id: str) -> list[ComponentFit]`
- `find_component_fit(task_archetype: Optional[str], slot_signature: Optional[str], component_type: Optional[str], limit: int = 20) -> list[ComponentFit]`

### 5.4 Packets

- `save_application_packet(packet: ApplicationPacket) -> None`
- `get_application_packet(packet_id: str) -> Optional[ApplicationPacket]`
- `list_packets_for_plan(plan_id: str) -> list[ApplicationPacketSummary]`
- `list_packet_history_for_component(component_id: str, limit: int = 50) -> list[ApplicationPacketSummary]`

### 5.5 Events

- `save_pair_event(event: PairEvent) -> PairEvent`
- `save_landing_event(event: LandingEvent) -> LandingEvent`
- `save_outcome_event(event: OutcomeEvent) -> OutcomeEvent`
- `list_run_pair_events(run_id: str) -> list[PairEvent]`
- `list_run_landing_events(run_id: str) -> list[LandingEvent]`
- `list_run_outcome_events(run_id: str) -> list[OutcomeEvent]`

### 5.6 Connectomes

- `save_run_connectome(connectome: RunConnectome) -> RunConnectome`
- `get_run_connectome(run_id: str) -> Optional[RunConnectome]`
- `save_run_connectome_edge(...) -> None`
- `list_run_connectome_edges(connectome_id: str) -> list[dict[str, Any]]`

## 6. Barcode Utility Spec

Implement in `src/claw/connectome/barcodes.py`.

### 6.1 source barcode

Input fields:

- repo
- commit if known, else empty string
- file_path
- symbol if known, else empty string
- content_hash

Rule:

- do not depend on line numbers for stable identity

### 6.2 family barcode

Input fields:

- component_type
- normalized abstract job string

### 6.3 slot barcode

Input fields:

- task_archetype
- slot name
- normalized constraints
- normalized target stack

### 6.4 pair / locus / outcome helpers

These may be derived helpers in M1 but should not be required by higher layers yet.

## 7. Lineage Utility Spec

Implement in `src/claw/connectome/lineage.py`.

### 7.1 Canonical lineage baseline

Start simple:

- exact content_hash match = same lineage candidate
- same family_barcode + same content_hash = same lineage

Optional improvement in same module:

- AST fingerprint similarity for near-duplicate clustering

### 7.2 Clone-inflation baseline

If multiple component cards share one lineage, then:

- lineage_size increases
- deduped_support_count should stay lineage-aware
- confidence logic later can depend on deduped support instead of raw count

## 8. Feature Flag Wiring Spec

Update `src/claw/core/config.py` and `src/claw/core/factory.py`.

### 8.1 Config model

Add a new config group:

- `camseq.component_cards`
- `camseq.application_packets`
- `camseq.connectome_seq`
- `camseq.critical_slot_policy`
- `camseq.a2a_packets`

Defaults:

- all false

### 8.2 Factory/runtime behavior

M1 only needs:

- flags accessible to runtime services
- no behavior changes when false

Do not yet deeply wire all flags into all systems.

## 9. Validation and Tests For M1

Add tests for:

- barcode stability
- lineage dedup baseline
- model validation
- schema migration
- repository round-trips
- flags-off compatibility

Suggested files:

- `tests/connectome/test_barcodes.py`
- `tests/connectome/test_lineage_dedup.py`
- `tests/db/test_component_schema.py`
- `tests/db/test_component_repository.py`
- `tests/config/test_camseq_flags.py`

## 10. M1 Exit Criteria

M1 is complete only when:

- new models validate cleanly
- new tables migrate cleanly
- repository methods round-trip entities correctly
- source and family barcodes are stable
- lineage baseline works for exact duplicates
- flags default off
- no legacy flows change behavior with flags off

## 11. Deferred To M2+

These are explicitly out of M1:

- task planning
- application packet review UI
- plan APIs
- packet execution integration
- run connectome UI
- retrograde tracing
- recipe logic
- Semgrep / CodeQL gating
