# Changelog

All notable changes to CAM-PULSE are documented here.

---

## [Unreleased]

---

## [0.7.0] - 2026-03-30

### Added — Phase 5.1: Bayesian Kelly Criterion
- **Bayesian Kelly agent routing** (`src/claw/evolution/kelly.py`): Sukhov (2026) position-sizing formula `f* = (p̄ - (1-p̄)/b) × n_eff / (n_eff + κ)` for intelligent agent selection
- `BayesianKellySizer` with `compute_fraction()`, `compute_routing_weights()`, `sample_agent()`, `adaptive_margin()`, `get_posterior_std()`
- **Kelly config** (`[kelly]` in claw.toml): kappa=10.0, f_max=0.40, min_exploration_floor=0.02, disabled by default
- **Dispatcher integration**: Kelly overrides planner-assigned recommended_agent when performance data exists. Priority: Kelly → recommended → exploration → learned → static → fallback
- **Fitness uncertainty discount**: `kelly_posterior_std` on `compute_fitness()` reduces efficacy up to 30% for unreliable agents
- **Adaptive A/B margins**: `_BASE_WIN_MARGIN * n_eff / (n_eff + kappa)` replaces fixed 0.05 threshold — demands bigger effects from thin data
- **Proven routing with real data**: 3 rounds × 5 task types × 4 agents. Architecture: claude 37.6%, gemini 26.1%, grok 26.1%, codex 10.2%
- 39 tests in `test_kelly.py`; updated `test_phase4.py` for adaptive margin

### Added — Phase 5.1: Knowledge Mining Expansion
- Mined repo330 projects: Bayesian-Kelly (8), Crucix (8), Atomic-Chat (14), Cookbook (13), OpenMAIC (12)
- Mined gits2rev.md repos: claude-mem (11), LightRAG (13), Superpowers (11), Everything-Claude-Code (14)
- General ganglion: 1,877 → 2,027 methodologies (+150)

### Changed
- Test count: 2,624 → 2,663 passing (+39 from Kelly tests)
- Dispatcher routing priority: Kelly now overrides planner-assigned recommended_agent when it has data
- `_WIN_MARGIN` renamed to `_BASE_WIN_MARGIN` in prompt_evolver.py (from 0.05 to 0.15 base)

### Fixed
- pulse_discoveries CHECK constraint missing 'scanning', 'mounting', 'refreshing' statuses in main claw.db
- pulse_scan_log UNIQUE constraint race condition from concurrent PULSE ingests

---

## [0.6.0] - 2026-03-28

### Added — Phase 4.5: Drive-Ops + Knowledge Application
- Drive-Ops Ganglion: mined 1,046 methodologies from 63 repos across 1.5TB drive
- Content-hash dedup: SHA-256 of first 4KB per file catches identical codebases (82 dupes caught)
- `.mineignore` file support for persistent path exclusions during mining
- Configurable mining filters: `extra_code_extensions` and `extra_skip_dirs` in `claw.toml` `[mining]`
- Live knowledge application proven: 3 PULSE patterns injected into agent prompt, TaskPulse microservice built with traceable pattern lineage
- Self-enhancement run #3: gemini agent (exploration), quality 0.97, drift 0.898, all 7 gates PASSED (2,624 tests), 203.4s atomic swap
- README and landing page updated with proven results (14 showpieces)

---

## [0.5.0] - 2026-03-27

### Added — Phase 4.0: CAM Swarm Federation
- CAM Brain architecture: ganglia (specialized instances) + swarm (runtime coordination)
- Multi-instance federation: sibling ganglia cross-query via read-only FTS5
- Brain manifest generation: categories, languages, source repos, domain keywords
- Relevance scoring: 60% keyword overlap + 20% language + 20% maturity
- EMA fitness feedback loop: `outcome_ema` in fitness_vector, alpha=0.3, blend 60/40
- Configurable mining: `MiningConfig` with `extra_code_extensions`, `extra_skip_dirs`
- `cam kb instances {list|manifest|query|add|remove}` — federation management CLI
- Content-hash dedup: SHA-256 of first 4KB per file for cross-repo duplicate detection

### Fixed
- Federation bug: `prism_data` must be in `json_dict_fields` for Methodology validation
- Miner base-dir fix: `is_repo or (is_source_tree and dir_path != base)`

### Changed
- Test count: 2,348 -> 2,624 passing
- Methodology count: 1,877+ from 273+ source repos across 11 languages

---

## [0.4.5] - 2026-03-25

### Added — Phase 3.9: Resilience + Safety
- Self-enhancement pipeline: 6-phase clone -> enhance -> validate -> swap -> post-swap -> rollback (`reconstruct.py`)
- 7-gate validation: syntax, config, import, DB schema, CLI smoke, full pytest, diff summary (`validation_gate.py`)
- Protected files: changes to 5 critical files (verifier.py, factory.py, engine.py, schema.sql, config.py) require human review
- TruffleHog pre-assimilation secret scanning with 800+ credential detectors and regex fallback (`security/scanner.py`)
- Freshness monitor: ETag/304 checks, significance scoring, stale methodology retirement (`pulse/freshness.py`)
- Community knowledge sharing: packer, validator (7 gates), hub (HuggingFace), importer with quarantine flow (`community/`)
- License-aware mining: `permissive|copyleft|unknown|none` detection from LICENSE/COPYING files
- A/B knowledge ablation testing: Bayesian Beta-distribution comparison, MIN_SAMPLES=20 (`prompt_evolver`)
- Embedding attribution: 2-pass lexical + cosine matching for methodology usage tracking
- Fitness history tracking: `methodology_fitness_log` table (Migration 14) with trigger events
- deepConf 6-factor confidence scoring: retrieval, authority, accuracy, novelty, provenance, verification
- Context budget enforcement: 25% of token_budget_remaining for knowledge injection (max 8K, floor 2K)
- `cam kb community {publish|browse|import|approve|status}` — community sharing CLI
- `cam ab-test {start|status|stop}` — knowledge ablation scheduling and monitoring
- `cam security scan <path>` / `cam security status` — secret scanning CLI
- `cam self-enhance {status|start|validate|swap|rollback}` — self-enhancement CLI

### Changed
- Test count: 2,348 -> 2,577 passing
- Self-enhance proven: clone -> enhance (1 task, quality 0.97) -> all 7 gates PASS -> 2,028/2,028 tests pass

---

## [0.4.0] - 2026-03-24

### Added — Phase 3.75: Inner Correction Loop
- **Inner correction loop** — When verification catches correctable failures, the workspace is byte-level restored and the agent is re-prompted with specific violations + test output. Up to 3 attempts per task. (`cycle.py:_act_with_correction()`, `CorrectionFeedback` model)
  - Workspace snapshot/restore: `_snapshot_workspace_content()` / `_restore_workspace()`
  - Failure classifier: `_is_correctable_failure()` (test failures, placeholders, drift = correctable; budget, HTTP = infrastructure)
  - Proven: Run 1 triggered 3 correction retries; Run 2 succeeded first attempt (10/10 tests, drift 0.868, quality 0.76)
  - 28 tests in `test_cycle_correction.py`
- **Metric expectations enforcement** — Verifier auto-extracts structured metric targets from natural language specs (`"greater than 90 percent coverage"` -> `MetricExpectation(min_coverage_pct, gte, 90, hard=True)`). Supported: `min_coverage_pct`, `min_test_count`, `min_files_changed`, `max_files_changed`. Hard expectations block approval; soft generate recommendations. (`verifier.py:_check_metric_expectations()`, 51 tests in `test_verifier_metrics.py` + `test_verifier_min_tests.py`)
- **HuggingFace model repository mining** — `HFMountAdapter` (`pulse/hf_adapter.py`) classifies HF repos into micro/standard/large tiers with size-appropriate mining strategies. Micro (< 100 MB) gets full clone; larger repos use metadata-only API approach to avoid downloading weights. `cam pulse ingest https://huggingface.co/...` works transparently alongside GitHub URLs. (81 tests in `test_hf_adapter.py`)
- **Repo freshness monitor** — Two-phase staleness detection for previously-mined repos. Phase 1: ETag-cached metadata check (0 rate limit cost for unchanged repos). Phase 2: Significance scoring from commits, releases, README changes, and size delta. Only repos with significance >= 0.4 trigger re-mine. (`pulse/freshness.py`, `cam pulse freshness`, `cam pulse refresh`)
- **`size_at_mine` column** — Tracks repo size at mine time in `pulse_discoveries`, enabling size-delta computation in freshness scoring. Migration 12 adds the column; `seed_existing_repos()` captures size from GitHub API.
- **deepConf 6-factor confidence scoring** — Methodology retrieval scored by cosine similarity (0.30), BM25 text match (0.20), fitness (0.20), freshness (0.10), cross-domain synergy (0.10), source diversity (0.10). Configurable via `[deep_conf]` in `claw.toml`. (`memory/hybrid_search.py:_deep_conf_score()`)
- **Co-retrieval stigmergic links** — When co-retrieved methodologies lead to successful builds, CAM records links between them. Future retrievals boost co-proven pairs. (`memory/semantic.py:record_co_retrieval_outcome()`, `MethodologyLink` model with `co_retrieval` link type)
- **Safety mitigations** — `--dry-run` on destructive PULSE commands, auto-backup before self-enhancement swaps, confirmation prompts before re-mining, infrastructure failure isolation (API timeouts never penalize methodology fitness)
- **PR Bridge tests** — 42 tests covering `PulsePRBridge` construction, URL parsing, threshold boundaries, config interaction. (92% coverage on `pr_bridge.py`)
- **Knowledge injection into agent prompts** — Full methodology content (problem_description, implementation_sketch, solution_code, activation_triggers) injected as `## Retrieved Knowledge` section in agent prompts. Proven: Retrieved=3, Used=3, Attributed=3, 4/4 tests passing.
- **Multi-pass mining pipeline** — Three-pass approach replaces monolithic single-LLM-call mining:
  - Pass 1: Rule-based domain classification (10 categories, keyword matching, zero cost)
  - Pass 2: Knowledge overlap assessment (semantic search, computes overlap_score and suggested_focus)
  - Pass 3: Focused LLM mining with structured domain context and adaptive token budget (small=2K, medium=4K, large=6K)
- **README-first file serialization** — Priority-based ordering: README (tier 0), configs (tier 1), core source (tier 2), tests/docs/examples (tier 3)
- **Domain-aware mining context** — `_find_domain_knowledge()` searches semantic memory across ALL repos for similar patterns, injects "focus on what's NOVEL" directives
- **`KnowledgeOverlap` dataclass** — Structured Pass 2 result with repo_known_titles, domain_known_titles, overlap_score, suggested_focus
- **`_DOMAIN_KEYWORDS` and `_LANGUAGE_SIGNALS`** — 10-category keyword maps + config-file language detection for Pass 1
- **Infrastructure failure protection** — `_INFRASTRUCTURE_ERRORS` frozenset distinguishes agent bugs (timeout, no_api_key, http_*) from methodology failures; infrastructure failures do not penalize methodology fitness
- **Null LLM content handling** — OpenRouter `content: null` responses caught at client level; model refusals raise `LLMError`; null content defaults to empty string
- **`cam pulse ingest`** — Direct URL ingestion for prescreened repos (9 repos, 52 methodologies from heroui, deer-flow, spec-kit, starlette, claude-peers-mcp, editor, MegaMemory)
- PULSE Usage Proof showpiece (`docs/CAM_SHOWPIECE_PULSE_USAGE_PROOF.md`, `scripts/test_pulse_usage_proof.sh`)
- **Plugin Event System showpiece** — Cross-repo knowledge synthesis: 3 repos -> 1 cohesive module. Retrieved=3, Used=3, Attributed=3, 5/5 tests, 258 source lines. Demonstrates knowledge compounding across builds. (`docs/CAM_SHOWPIECE_PLUGIN_EVENT_SYSTEM.md`, `scripts/test_plugin_event_showpiece.sh`)
- PULSE retryable discoveries — failed and discovered repos are no longer permanently blocked; only `assimilated` status counts as "known"
- `_repair_json()` — 3-stage progressive JSON repair for malformed LLM mining output (trailing comma fix, truncation recovery, individual object extraction)
- `cam learn search` — hybrid vector + text semantic search across all methodologies with provenance, scores, and lifecycle stage
- PULSE Knowledge Loop showpiece (`docs/CAM_SHOWPIECE_PULSE_KNOWLEDGE_LOOP.md`, `scripts/test_pulse_knowledge_loop.sh`)
- Cross-Repo Intelligence showpiece (`docs/CAM_SHOWPIECE_CROSS_REPO_INTELLIGENCE.md`, `scripts/test_cross_repo_intelligence.sh`)
- Competitive differentiation table in README (CAM vs Aider vs Cursor vs AutoGPT vs generic claws)
- 13 new tests for multi-pass mining (domain classification, knowledge overlap, context builder, token budget, keyword coverage)
- 12 new tests for `_repair_json` (trailing commas, truncation, nested objects, integration with `parse_findings`)
- 2 new tests for retryable PULSE discoveries (`test_failed_discovery_is_retryable`, `test_discovered_status_is_retryable`)
- Domain bias novelty scoring with mission profile support
- Profile-enriched keyword generation for X-Scout scans
- PULSE config tests (profile fields, domain parsing, novelty_bias)

### Fixed
- Knowledge gap: methodology context passed to `_build_openrouter_prompt()` but never read — now full `past_solutions` with solution_code, capability_data injected
- `capability_data.applicability` returned list instead of dict — added `isinstance` guard
- LLM mining JSON parse failure rate reduced from ~75% to 0% via `_repair_json()`
- PULSE novelty filter no longer permanently blocks failed discoveries
- `cam learn search` verbose mode: `learning_stage` corrected to `lifecycle_state`
- `cam pulse scan` result object: fixed `AttributeError` (result is `PulseScanResult` not dict)
- Cross-repo intelligence script Step 3 provenance parsing for Rich table format
- Methodologies no longer penalized for infrastructure failures (timeout, no_api_key, HTTP errors)
- OpenRouter `content: null` crash in `parse_findings()` — null guard added
- **`_execute_once()` correction loop was dead code** — `cli.py:4375` now calls `_act_with_correction()` instead of bare `act()+verify()`
- **Verifier test count always reported 0** — Removed `-q` flag from pytest args in `verifier.py:933,937` that suppressed the summary line needed by `_parse_test_count()` regex
- **`pr_bridge.py` schema mismatch** — INSERT used `type` and `metadata` columns that don't exist in schema; corrected to `task_type`, removed `metadata`
- **pytest-asyncio 0.23.x incompatible with pytest 9.x** — Bumped minimum to `>=0.24.0` in pyproject.toml (AttributeError: 'Package' object has no attribute 'obj')

### Changed
- Test count: 1,735 -> 2,348 passing (613 new tests across 70 test files)
- Methodology count: 122 (86 from live PULSE scan + 36 from prescreened ingestion)
- `MicroClaw.run_cycle()` override replaces base class's separate act()+verify() with `_act_with_correction()` loop
- `mine_repo()` refactored from single-pass to three-pass pipeline
- `serialize_repo()` now orders files by priority tier (README first, configs second, core source third)
- Source: 73 Python modules, 63,684 LOC; Tests: 70 files, 35,911 LOC
- Phase 3.75 (Inner Correction Loop) status: Complete

---

## [0.3.0] - 2026-03-20

### Added — Phase 3: CAM-PULSE
- CAM-PULSE (Perpetual Unified Learning Swarm Engine) — autonomous X-powered discovery
- X-Scout module using xAI Responses API with native `x_search` tool
- Novelty filter with URL dedup + semantic distance scoring
- Assimilation pipeline: git clone -> RepoMiner -> methodology storage
- PR Bridge for fleet registration and enhancement queuing
- Circuit breaker with exponential backoff for API resilience
- 3-layer budget controls: per-scan, per-day, per-agent caps
- Mission profiles (`[pulse.profile]` in claw.toml) with domain-specific keyword enrichment and novelty bias
- `cam pulse preflight` — validates xAI key and model configuration
- `cam pulse scan` — one-shot discovery from X
- `cam pulse daemon` — perpetual polling mode (configurable interval)
- `cam pulse status` / `cam pulse discoveries` / `cam pulse report` — monitoring commands
- Docker Compose for PULSE daemon deployment
- `.env.example` template for git-clone users
- `cam setup` now includes PULSE configuration section
- Self-mining: CAM periodically mines its own source for methodology extraction

### Changed
- xAI timeout increased from 30s to 120s for `x_search` tool calls
- `cam setup` redesigned: `.env` is single source for keys and models
- Grok model hints updated to grok-4 family

---

## [0.2.0] - 2026-03-17

### Added — Phase 2: Local Mode + Docker
- Docker deployment (`docker compose up --build`)
- Ollama local LLM support (zero cloud keys)
- MLX-LM native Apple Silicon acceleration
- Torch-free lightweight install option (`pip install -e .`)
- Gemini API embedding fallback for torch-free installs
- `cam doctor audit` — methodology trust auditing
- `cam doctor expectations` — expectation matching
- medCSS Modernizer showpiece
- Repo Upgrade Advisor showpiece
- Expectation Ladder showpiece
- Reliability pipeline harness (`scripts/run_cam_reliability_pipeline.sh`)

---

## [0.1.0] - 2026-03-10

### Added — Phase 1: Core Engine
- `cam evaluate` — inspect repos before touching them
- `cam mine` — extract methodologies from repo folders into SQLite
- `cam create` — generate implementation specs for new features
- `cam enhance` — improve existing repos with learned patterns
- `cam validate` — verify real workspace diffs against saved specs
- `cam ideate` — brainstorm improvements using knowledge base
- `cam forge-benchmark` — deterministic standalone regression harness
- `cam preflight` — contract system blocking unsafe execution
- `cam govern` — governance stats and methodology management
- `cam learn report` / `cam learn reassess` / `cam learn delta` — knowledge lifecycle
- `cam task results` — execution tracking
- `cam chat` — guided workflow chat interface
- Namespace-safe execution with `--namespace-safe-retry`
- Multi-agent routing: Claude, Codex, Gemini, Grok via OpenRouter
- SKILL.md wrapper and GitHub issue templates
- SQLite + sqlite-vec for methodology storage and vector search
- Hybrid search (BM25 text + cosine vector similarity)
