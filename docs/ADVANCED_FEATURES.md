# Advanced Features Guide

**Audience**: CAM operators who want to tune the intelligence, routing, and safety systems beyond the defaults.

---

## Kelly Routing (Bayesian Agent Selection)

### What It Does

Instead of randomly picking which agent (Claude, Gemini, Codex, Grok, Local) handles a task, Kelly routing uses Bayesian statistics to pick the agent most likely to succeed — weighted by past performance and task type.

### How It Works

- Each agent accumulates a success history per `task_type` (mining, enhancement, etc.)
- The Kelly Criterion calculates an optimal "bet size" (exploration vs exploitation)
- High `kappa` = more exploitation (trust history), low `kappa` = more exploration (try new agents)
- `f_max` caps the maximum fraction any single agent gets, preventing monopoly
- Every agent gets at least `min_exploration_floor` chance (default 5%)

### Config

```toml
[kelly]
enabled = true
kappa = 10.0                    # Shrinkage parameter (higher = more exploitation)
f_max = 0.40                    # Max fraction for any single agent (40%)
min_exploration_floor = 0.05    # Every agent gets at least 5% chance
payoff_default = 1.0            # Default payoff for unknown agent-task pairs
prior_alpha = 1.0               # Bayesian prior (uniform)
prior_beta = 1.0
local_quality_multiplier = 0.7  # Local agent quality discount (cheaper but weaker)
```

### Diagnostics

```bash
.venv/bin/cam doctor routing
```

Shows: agent win rates, Kelly fractions, exploration rate, task type breakdown.

**Use this when**: You want to verify which agents are being selected and why.

### Tuning Guide

| Symptom | Adjust | To |
|---------|--------|----|
| Same agent always picked | Decrease `kappa` | 5.0 (more exploration) |
| Too many task failures | Increase `kappa` | 15.0 (trust history more) |
| Local agent never selected | Increase `local_quality_multiplier` | 0.9 |
| One agent dominates all tasks | Decrease `f_max` | 0.30 |
| New agent never gets tried | Increase `min_exploration_floor` | 0.10 |

---

## Deep Confidence Scoring (deepConf)

### What It Does

A 6-factor confidence score applied to every methodology. Used by hybrid search to rank results beyond simple text or vector similarity.

### The 6 Factors

| Factor | Default Weight | What It Measures |
|--------|---------------|------------------|
| `retrieval` | 0.25 | BM25 text + cosine vector similarity to the query |
| `authority` | 0.15 | Source repo quality (stars, contributors, recency) |
| `accuracy` | 0.20 | Test pass rate, validation gate results |
| `novelty` | 0.15 | How different from existing knowledge (assimilation score) |
| `potential` | 0.15 | Predicted future utility (IO generality, trigger breadth) |
| `consensus` | 0.10 | Agreement across multiple agents |

### Config

```toml
[deep_conf]
retrieval_weight = 0.25
authority_weight = 0.15
accuracy_weight = 0.20
novelty_weight = 0.15
potential_weight = 0.15
consensus_weight = 0.10
```

Weights must sum to 1.0.

### Tuning Guide

| Goal | Adjust |
|------|--------|
| Prioritize proven, tested patterns | Increase `accuracy_weight` |
| Prioritize novel discoveries | Increase `novelty_weight` |
| Prioritize repos from popular/trusted sources | Increase `authority_weight` |
| Prioritize patterns with broad applicability | Increase `potential_weight` |

---

## Prompt Evolution and A/B Testing

### What It Does

Automatically mutates prompts using zero-cost string transformations and A/B tests the variants to find better-performing versions. No LLM calls are needed for mutations.

### Mutation Types

| Type | What It Does |
|------|-------------|
| `add_emphasis` | Wraps key directive sentences in IMPORTANT markers |
| `reorder_sections` | Reverses section order (except first section) |
| `add_constraints` | Appends quality constraint reminders |
| `simplify` | Strips parenthetical remarks, compresses whitespace |
| `add_examples_placeholder` | Adds "provide concrete examples" reminder |

### How A/B Testing Works

1. A control prompt (original) and a variant (mutated) each receive 50% of invocations
2. After 20 samples per variant, a Bayesian comparison declares a winner
3. The winner is promoted (activated), the loser is deactivated
4. The cycle can repeat, continuously improving prompts

### Prompt Enrichment

The `evolve_prompt()` method also enriches static prompts with:
- Up to 3 thriving methodologies from semantic memory
- Up to 5 top error patterns from the error KB

This means prompts get smarter over time as CAM learns.

### Config

```toml
[evolution]
ab_test_sample_size = 20      # Min samples before declaring winner
ab_test_kappa = 10.0          # Kelly shrinkage for adaptive win margin
mutation_rate = 0.1           # Fraction of prompts to mutate
```

---

## Error Knowledge Base

### What It Does

Tracks every failed attempt across all tasks and agents. Detects patterns automatically:

- **Repeated failures**: Same error on same task — adds to "forbidden approaches" list so agents do not retry known bad paths
- **Cross-task patterns**: Same error signature across 2+ tasks — flags systematic issues
- **Cross-agent failures**: All agents fail the same way — flagged as "critical urgency" (likely needs human intervention)

### How It Works

1. Every task attempt is recorded: approach summary, outcome, error signature
2. Error signatures are normalized (UUIDs, file paths, line numbers stripped) for grouping
3. `get_forbidden_approaches(task_id)` prevents agents from retrying known failures on that task
4. `get_common_failure_patterns(project_id)` surfaces recurring issues across the project
5. `get_cross_agent_failures()` finds errors where all agents failed identically

### Error Categories

Automatically classified: `type_error`, `import_error`, `attribute_error`, `value_error`, `key_error`, `index_error`, `connection_error`, `database_error`, `permission_error`, `file_error`, `async_error`, `api_error`, `validation_error`, `syntax_error`, `test_failure`

### No Configuration Needed

Error KB is always active. It feeds automatically into prompt evolution (top 5 error patterns appended to evolved prompts) and into task planning (forbidden approaches excluded).

---

## Budget Enforcement

### What It Does

Hard spending caps at 4 levels to prevent runaway API costs. All denominated in USD.

### Default Limits

| Level | Default Limit | Scope |
|-------|--------------|-------|
| Per task | $5.00 | Single task execution |
| Per project | $50.00 | All tasks in a project |
| Per day | $100.00 | All API spend today |
| Per agent | $25.00 | Single agent's daily spend |

### Config

```toml
[budget]
per_task_usd = 5.0
per_project_usd = 50.0
per_day_usd = 100.0
per_agent_usd = 25.0
```

### Behavior When Exceeded

The orchestrator pauses and reports which budget was exceeded. There is no automatic override — a human must increase the limit or acknowledge the pause.

**Use this when**: You want cost guardrails for automated mining or enhancement runs.

---

## Pattern Learning

### What It Does

Extracts successful patterns from completed tasks and promotes them from project-scope to global-scope methodologies. This is how CAM's knowledge generalizes over time.

### What Gets Learned

1. **Error resolution patterns**: Same error resolved the same way 2+ times across different tasks
2. **Methodology reuse patterns**: High-fitness methodology used successfully across 3+ tasks

### Promotion Requirements

A methodology is promoted from project-scope to global-scope when:
- It is in "thriving" lifecycle state
- Effective success count >= 3
- Average expectation match score >= 0.65 (if attribution history exists)
- Optionally: used across 2+ different projects

### No Manual Config Needed

Pattern learning runs automatically during self-enhancement cycles (`cam self-enhance run`).

---

## Semantic Memory and Hybrid Search

### What It Does

Combines multiple retrieval signals for methodology search:

1. **BM25 text search** — keyword matching
2. **Cosine vector similarity** — 384-dim Gemini embeddings
3. **deepConf scoring** — 6-factor confidence (see above)
4. **Stigmergic links** — co-retrieval associations

### Stigmergic Links

When two methodologies are frequently retrieved together in the same context, they form "stigmergic links" — co-retrieval associations. Future queries for one methodology will boost the ranking of linked methodologies.

This is an emergent organizational structure: the knowledge base self-organizes based on usage patterns.

### Config

```toml
[assimilation]
novelty_retrieval_boost = 0.1       # Boost for novel methodologies in search
potential_retrieval_boost = 0.1     # Boost for high-potential methodologies
synergy_score_threshold = 0.7       # Min score to create a synergy link
```

---

## Feature Dependencies

| Feature | Requires | Optional Enhancement |
|---------|----------|---------------------|
| Kelly routing | `[kelly] enabled = true` | Works with or without local agent |
| CAG | `[cag] enabled = true` | Local agent enables KV prefix caching |
| KV cache | CAG enabled + local agent enabled | TurboQuant binary for turbo3/turbo4 |
| Prompt evolution | Always active | Error KB enriches evolved prompts |
| Error KB | Always active | Feeds into prompt evolution automatically |
| Budget enforcement | Always active | Adjustable limits via `[budget]` |
| Pattern learning | Runs during self-enhancement | Semantic memory enables promotion |
| deepConf | Always active | Adjustable weights via `[deep_conf]` |
| Stigmergic links | Semantic memory active | Strengthens with usage |

---

## Quick Reference: All Config Sections

```toml
[kelly]                    # Bayesian agent routing
[deep_conf]                # 6-factor confidence scoring weights
[evolution]                # Prompt mutation and A/B testing
[budget]                   # 4-level spending caps
[assimilation]             # Novelty scoring and synergy discovery
[governance]               # Memory lifecycle and quotas (see GOVERNANCE_TUNING.md)
[cag]                      # Cache-Augmented Generation (see CAG_GUIDE.md)
[local_llm]                # Local inference backend (see LOCAL_LLM_SETUP.md)
[pulse]                    # Autonomous discovery engine
[self_enhance]             # Self-enhancement pipeline
```
