-- CLAW — Database Schema
-- SQLite with WAL mode, FTS5, and sqlite-vec

-- 1. PROJECTS
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    tech_stack TEXT NOT NULL DEFAULT '{}',       -- JSON string
    project_rules TEXT,
    banned_dependencies TEXT NOT NULL DEFAULT '[]', -- JSON array string
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- 2. TASKS (Work Queue)
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','EVALUATING','PLANNING','DISPATCHED','CODING','REVIEWING','STUCK','DONE')),
    priority INTEGER NOT NULL DEFAULT 0,
    task_type TEXT,
    recommended_agent TEXT,
    assigned_agent TEXT,
    action_template_id TEXT REFERENCES action_templates(id) ON DELETE SET NULL,
    execution_steps TEXT NOT NULL DEFAULT '[]',       -- JSON array string
    acceptance_checks TEXT NOT NULL DEFAULT '[]',     -- JSON array string
    context_snapshot_id TEXT,
    attempt_count INTEGER DEFAULT 0,
    escalation_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(project_id, priority DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_action_template ON tasks(action_template_id);

-- 2b. ACTION_TEMPLATES (Reusable executable runbooks)
CREATE TABLE IF NOT EXISTS action_templates (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    problem_pattern TEXT NOT NULL,
    execution_steps TEXT NOT NULL DEFAULT '[]',      -- JSON array string
    acceptance_checks TEXT NOT NULL DEFAULT '[]',    -- JSON array string
    rollback_steps TEXT NOT NULL DEFAULT '[]',       -- JSON array string
    preconditions TEXT NOT NULL DEFAULT '[]',        -- JSON array string
    source_methodology_id TEXT REFERENCES methodologies(id) ON DELETE SET NULL,
    source_repo TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_action_templates_repo ON action_templates(source_repo);
CREATE INDEX IF NOT EXISTS idx_action_templates_confidence ON action_templates(confidence DESC);

-- 3. HYPOTHESIS_LOG (Trial & Error Memory)
CREATE TABLE IF NOT EXISTS hypothesis_log (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    approach_summary TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'FAILURE'
        CHECK (outcome IN ('SUCCESS','FAILURE')),
    error_signature TEXT,
    error_full TEXT,
    files_changed TEXT NOT NULL DEFAULT '[]',     -- JSON array string
    duration_seconds REAL,
    model_used TEXT,
    agent_id TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(task_id, attempt_number)
);
CREATE INDEX IF NOT EXISTS idx_hyp_task ON hypothesis_log(task_id);
CREATE INDEX IF NOT EXISTS idx_hyp_error_sig ON hypothesis_log(error_signature);

-- 3b. METHODOLOGY_USAGE_LOG (Attribution of retrieved/used knowledge)
CREATE TABLE IF NOT EXISTS methodology_usage_log (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    methodology_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    stage TEXT NOT NULL DEFAULT 'retrieved_presented',
    agent_id TEXT,
    success INTEGER,
    expectation_match_score REAL,
    quality_score REAL,
    relevance_score REAL,
    notes TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_meth_usage_task ON methodology_usage_log(task_id);
CREATE INDEX IF NOT EXISTS idx_meth_usage_methodology ON methodology_usage_log(methodology_id);
CREATE INDEX IF NOT EXISTS idx_meth_usage_stage ON methodology_usage_log(stage);

-- 4. METHODOLOGIES (Long-Term Memory / RAG)
CREATE TABLE IF NOT EXISTS methodologies (
    id TEXT PRIMARY KEY,
    problem_description TEXT NOT NULL,
    solution_code TEXT NOT NULL,
    methodology_notes TEXT,
    source_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    tags TEXT NOT NULL DEFAULT '[]',               -- JSON array string
    language TEXT,
    scope TEXT NOT NULL DEFAULT 'project',
    methodology_type TEXT,
    files_affected TEXT NOT NULL DEFAULT '[]',      -- JSON array string
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- MEE lifecycle fields
    lifecycle_state TEXT NOT NULL DEFAULT 'viable'
        CHECK (lifecycle_state IN ('embryonic','viable','thriving','declining','dormant','dead')),
    retrieval_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_retrieved_at TEXT,
    generation INTEGER NOT NULL DEFAULT 0,
    fitness_vector TEXT NOT NULL DEFAULT '{}',      -- JSON string
    parent_ids TEXT NOT NULL DEFAULT '[]',          -- JSON array string
    superseded_by TEXT,
    prism_data TEXT,                                  -- JSON: PrismEmbedding (nullable)
    capability_data TEXT,                              -- JSON: CapabilityData (nullable)
    novelty_score REAL,                                -- 0.0-1.0: how different from existing KB
    potential_score REAL                                -- 0.0-1.0: future composability/value
);
CREATE INDEX IF NOT EXISTS idx_meth_scope ON methodologies(scope);
CREATE INDEX IF NOT EXISTS idx_meth_lifecycle ON methodologies(lifecycle_state);
CREATE INDEX IF NOT EXISTS idx_meth_novelty ON methodologies(novelty_score DESC);

-- Methodology embeddings (sqlite-vec virtual table)
-- Stores 384-dimensional float32 vectors for semantic search
-- Queried as: SELECT rowid, distance FROM methodology_embeddings WHERE embedding MATCH ?
CREATE VIRTUAL TABLE IF NOT EXISTS methodology_embeddings USING vec0(
    methodology_id TEXT PRIMARY KEY,
    embedding float[384]
);

-- Methodology full-text search (FTS5)
CREATE VIRTUAL TABLE IF NOT EXISTS methodology_fts USING fts5(
    methodology_id UNINDEXED,
    problem_description,
    methodology_notes,
    tags
);

-- 5. PEER_REVIEWS (Escalation Diagnoses)
CREATE TABLE IF NOT EXISTS peer_reviews (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    model_used TEXT NOT NULL,
    diagnosis TEXT NOT NULL,
    recommended_approach TEXT,
    reasoning TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_peer_task ON peer_reviews(task_id);

-- 6. CONTEXT_SNAPSHOTS (Checkpoint/Rewind State)
CREATE TABLE IF NOT EXISTS context_snapshots (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    git_ref TEXT NOT NULL,
    file_manifest TEXT,                            -- JSON string
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_snap_task ON context_snapshots(task_id);

-- 7. METHODOLOGY_LINKS (Stigmergic co-retrieval)
CREATE TABLE IF NOT EXISTS methodology_links (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'co_retrieval',
    strength REAL NOT NULL DEFAULT 1.0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(source_id, target_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_meth_links_source ON methodology_links(source_id);
CREATE INDEX IF NOT EXISTS idx_meth_links_target ON methodology_links(target_id);

-- 8. TOKEN_COSTS (Per-call LLM cost tracking)
CREATE TABLE IF NOT EXISTS token_costs (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    run_id TEXT,
    agent_role TEXT NOT NULL DEFAULT '',
    agent_id TEXT,
    model_used TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_token_costs_task ON token_costs(task_id);
CREATE INDEX IF NOT EXISTS idx_token_costs_agent ON token_costs(agent_id);
CREATE INDEX IF NOT EXISTS idx_token_costs_created ON token_costs(created_at DESC);

-- =========================================================================
-- CLAW-specific tables (not in ralfed)
-- =========================================================================

-- 9. AGENT_SCORES (Bayesian routing scores per task_type + agent)
CREATE TABLE IF NOT EXISTS agent_scores (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    total_attempts INTEGER NOT NULL DEFAULT 0,
    avg_duration_seconds REAL NOT NULL DEFAULT 0.0,
    avg_quality_score REAL NOT NULL DEFAULT 0.0,
    avg_cost_usd REAL NOT NULL DEFAULT 0.0,
    last_used_at TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(agent_id, task_type)
);
CREATE INDEX IF NOT EXISTS idx_agent_scores_agent ON agent_scores(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_scores_type ON agent_scores(task_type);

-- 10. PROMPT_VARIANTS (A/B testing for prompt evolution)
CREATE TABLE IF NOT EXISTS prompt_variants (
    id TEXT PRIMARY KEY,
    prompt_name TEXT NOT NULL,
    variant_label TEXT NOT NULL DEFAULT 'control',
    content TEXT NOT NULL,
    agent_id TEXT,
    is_active INTEGER NOT NULL DEFAULT 0,
    sample_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    avg_quality_score REAL NOT NULL DEFAULT 0.0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(prompt_name, variant_label, agent_id)
);

-- 11. CAPABILITY_BOUNDARIES (Tasks that all agents fail)
CREATE TABLE IF NOT EXISTS capability_boundaries (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    task_description TEXT NOT NULL,
    agents_attempted TEXT NOT NULL DEFAULT '[]',    -- JSON array string
    failure_signatures TEXT NOT NULL DEFAULT '[]',  -- JSON array string
    discovered_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_retested_at TEXT,
    retest_result TEXT,
    escalated_to_human INTEGER NOT NULL DEFAULT 0,
    resolved INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cap_bounds_type ON capability_boundaries(task_type);

-- 12. FLEET_REPOS (Fleet repo tracking)
CREATE TABLE IF NOT EXISTS fleet_repos (
    id TEXT PRIMARY KEY,
    repo_path TEXT NOT NULL UNIQUE,
    repo_name TEXT NOT NULL,
    priority REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','evaluating','enhancing','completed','failed','skipped')),
    enhancement_branch TEXT,
    last_evaluated_at TEXT,
    evaluation_score REAL,
    budget_allocated_usd REAL NOT NULL DEFAULT 0.0,
    budget_used_usd REAL NOT NULL DEFAULT 0.0,
    tasks_created INTEGER NOT NULL DEFAULT 0,
    tasks_completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_fleet_repos_status ON fleet_repos(status);
CREATE INDEX IF NOT EXISTS idx_fleet_repos_priority ON fleet_repos(priority DESC);

-- 13. EPISODES (Episodic memory — session event log)
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data TEXT NOT NULL DEFAULT '{}',          -- JSON string
    agent_id TEXT,
    task_id TEXT,
    cycle_level TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_episodes_project ON episodes(project_id);
CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id);
CREATE INDEX IF NOT EXISTS idx_episodes_type ON episodes(event_type);
CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created_at DESC);

-- 14. SYNERGY_EXPLORATION_LOG (Tracks explored capability pairs — SMART dedup)
CREATE TABLE IF NOT EXISTS synergy_exploration_log (
    id TEXT PRIMARY KEY,
    cap_a_id TEXT NOT NULL,
    cap_b_id TEXT NOT NULL,
    explored_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    result TEXT NOT NULL DEFAULT 'pending'
        CHECK (result IN ('pending','synergy','no_match','error','stale')),
    synergy_score REAL,
    synergy_type TEXT,
    edge_id TEXT,
    exploration_method TEXT,
    details TEXT NOT NULL DEFAULT '{}',
    UNIQUE(cap_a_id, cap_b_id)
);
CREATE INDEX IF NOT EXISTS idx_synergy_log_cap_a ON synergy_exploration_log(cap_a_id);
CREATE INDEX IF NOT EXISTS idx_synergy_log_cap_b ON synergy_exploration_log(cap_b_id);
CREATE INDEX IF NOT EXISTS idx_synergy_log_result ON synergy_exploration_log(result);

-- 15. GOVERNANCE_LOG (Audit trail for governance actions)
CREATE TABLE IF NOT EXISTS governance_log (
    id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    methodology_id TEXT,
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_governance_log_action ON governance_log(action_type);
CREATE INDEX IF NOT EXISTS idx_governance_log_created ON governance_log(created_at DESC);

-- 16. PULSE_DISCOVERIES (X-discovered repos via CAM-PULSE)
CREATE TABLE IF NOT EXISTS pulse_discoveries (
    id TEXT PRIMARY KEY,
    github_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    x_post_url TEXT,
    x_post_text TEXT,
    x_author_handle TEXT,
    discovered_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    novelty_score REAL,
    status TEXT NOT NULL DEFAULT 'discovered'
        CHECK (status IN ('discovered','cloning','scanning','mounting','mining','assimilated','failed','skipped','queued_enhance','refreshing')),
    scan_id TEXT,
    keywords_matched TEXT NOT NULL DEFAULT '[]',
    mine_result TEXT,
    methodology_ids TEXT NOT NULL DEFAULT '[]',
    error_detail TEXT,
    last_checked_at TEXT,
    last_pushed_at TEXT,
    head_sha_at_mine TEXT,
    etag TEXT,
    stars_at_mine INTEGER,
    latest_release_tag TEXT,
    freshness_status TEXT DEFAULT 'unknown',
    source_kind TEXT DEFAULT 'github',
    size_at_mine INTEGER,
    license_type TEXT,
    UNIQUE(canonical_url)
);
CREATE INDEX IF NOT EXISTS idx_pulse_disc_status ON pulse_discoveries(status);
CREATE INDEX IF NOT EXISTS idx_pulse_disc_novelty ON pulse_discoveries(novelty_score DESC);
CREATE INDEX IF NOT EXISTS idx_pulse_disc_discovered ON pulse_discoveries(discovered_at DESC);

-- 17. PULSE_SCAN_LOG (Scan session tracking for CAM-PULSE)
CREATE TABLE IF NOT EXISTS pulse_scan_log (
    id TEXT PRIMARY KEY,
    scan_type TEXT NOT NULL DEFAULT 'x_search',
    keywords TEXT NOT NULL DEFAULT '[]',
    started_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT,
    repos_discovered INTEGER NOT NULL DEFAULT 0,
    repos_novel INTEGER NOT NULL DEFAULT 0,
    repos_assimilated INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    error_detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_pulse_scan_started ON pulse_scan_log(started_at DESC);

-- 18. METHODOLOGY_FITNESS_LOG (Fitness score history for time-series analysis)
CREATE TABLE IF NOT EXISTS methodology_fitness_log (
    id TEXT PRIMARY KEY,
    methodology_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
    fitness_total REAL NOT NULL,
    fitness_vector TEXT NOT NULL DEFAULT '{}',
    trigger_event TEXT NOT NULL DEFAULT 'recompute',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_fitness_log_meth ON methodology_fitness_log(methodology_id);
CREATE INDEX IF NOT EXISTS idx_fitness_log_created ON methodology_fitness_log(created_at DESC);

-- 18.5 COMMUNITY_IMPORTS (Quarantine staging for community knowledge)
CREATE TABLE IF NOT EXISTS community_imports (
    id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    contributor_instance_id TEXT NOT NULL,
    contributor_alias TEXT,
    origin_id TEXT,
    status TEXT DEFAULT 'quarantined'
        CHECK (status IN ('quarantined','approved','rejected')),
    gate_results TEXT NOT NULL DEFAULT '{}',
    sanitized_record TEXT NOT NULL,
    imported_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    approved_at TEXT,
    UNIQUE(content_hash)
);
CREATE INDEX IF NOT EXISTS idx_community_imports_status ON community_imports(status);
CREATE INDEX IF NOT EXISTS idx_community_imports_contributor ON community_imports(contributor_instance_id);

-- 18.6 COMMUNITY_IMPORT_AUDIT (Audit trail for community imports)
CREATE TABLE IF NOT EXISTS community_import_audit (
    id TEXT PRIMARY KEY,
    contributor_instance_id TEXT,
    action TEXT NOT NULL,
    gate_name TEXT,
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_community_audit_action ON community_import_audit(action);

-- 19. AB_QUALITY_SAMPLES (Per-sample multi-dimensional quality metrics for A/B testing)
CREATE TABLE IF NOT EXISTS ab_quality_samples (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    variant_label TEXT NOT NULL,
    agent_id TEXT,
    d_functional_correctness REAL NOT NULL DEFAULT 0.0,
    d_structural_compliance REAL NOT NULL DEFAULT 0.0,
    d_intent_alignment REAL NOT NULL DEFAULT 0.0,
    d_correction_efficiency REAL NOT NULL DEFAULT 0.0,
    d_token_economy REAL NOT NULL DEFAULT 0.0,
    d_expectation_match REAL NOT NULL DEFAULT 0.0,
    composite_score REAL NOT NULL DEFAULT 0.0,
    correction_attempts INTEGER NOT NULL DEFAULT 1,
    escalation_tier INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0.0,
    success INTEGER NOT NULL DEFAULT 0,
    error_category TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_ab_samples_project ON ab_quality_samples(project_id);
CREATE INDEX IF NOT EXISTS idx_ab_samples_variant ON ab_quality_samples(variant_label);
CREATE INDEX IF NOT EXISTS idx_ab_samples_task ON ab_quality_samples(task_id);
