# Changelog

All notable changes to Clawamorphosis (CAM) are documented here.

---

## [Unreleased]

### Added
- PULSE retryable discoveries — failed and discovered repos are no longer permanently blocked; only `assimilated` status counts as "known"
- `_repair_json()` — 3-stage progressive JSON repair for malformed LLM mining output (trailing comma fix, truncation recovery, individual object extraction)
- `cam learn search` — hybrid vector + text semantic search across all methodologies with provenance, scores, and lifecycle stage
- PULSE Knowledge Loop showpiece (`docs/CAM_SHOWPIECE_PULSE_KNOWLEDGE_LOOP.md`, `scripts/test_pulse_knowledge_loop.sh`)
- Cross-Repo Intelligence showpiece (`docs/CAM_SHOWPIECE_CROSS_REPO_INTELLIGENCE.md`, `scripts/test_cross_repo_intelligence.sh`)
- Competitive differentiation table in README (CAM vs Aider vs Cursor vs AutoGPT vs generic claws)
- 12 new tests for `_repair_json` (trailing commas, truncation, nested objects, integration with `parse_findings`)
- 2 new tests for retryable PULSE discoveries (`test_failed_discovery_is_retryable`, `test_discovered_status_is_retryable`)
- Domain bias novelty scoring with mission profile support
- Profile-enriched keyword generation for X-Scout scans
- PULSE config tests (profile fields, domain parsing, novelty_bias)

### Fixed
- LLM mining JSON parse failure rate reduced from ~75% to 0% via `_repair_json()`
- PULSE novelty filter no longer permanently blocks failed discoveries
- `cam learn search` verbose mode: `learning_stage` corrected to `lifecycle_state`
- `cam pulse scan` result object: fixed `AttributeError` (result is `PulseScanResult` not dict)
- Cross-repo intelligence script Step 3 provenance parsing for Rich table format

### Changed
- Test count: 1,735 -> 1,840 passing (105 new tests)
- Methodology count: ~1,700 -> 1,800+ (86 new from first live PULSE scan)

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
