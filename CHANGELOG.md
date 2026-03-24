# Changelog

All notable changes to CAM-PULSE are documented here.

---

## [Unreleased]

### Added
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
- **Plugin Event System showpiece** — Cross-repo knowledge synthesis: 3 repos → 1 cohesive module. Retrieved=3, Used=3, Attributed=3, 5/5 tests, 258 source lines. Demonstrates knowledge compounding across builds. (`docs/CAM_SHOWPIECE_PLUGIN_EVENT_SYSTEM.md`, `scripts/test_plugin_event_showpiece.sh`)
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

### Changed
- Test count: 1,735 -> 1,868 passing (133 new tests)
- Methodology count: ~1,700 -> 1,800+ (86 from live PULSE scan + 52 from prescreened ingestion)
- `mine_repo()` refactored from single-pass to three-pass pipeline
- `serialize_repo()` now orders files by priority tier (README first, configs second, core source third)
- Landing page updated: 8 showpieces, 1,868 tests, knowledge application proof, multi-pass mining, cross-repo synthesis
- X/Twitter announcement thread rewritten with knowledge application proof
- Phase 3 status: Complete

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
