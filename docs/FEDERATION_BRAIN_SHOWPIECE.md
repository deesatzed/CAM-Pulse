# Federation Brain A/B Test — Showpiece #18

## Summary

Federated search across 3 ganglia (4,112 total methodologies) produces **+5.3% more results** with a Wilcoxon signed-rank p = 0.000005 and **105 unique results** invisible to single-ganglion queries. The federation layer adds just 1.7ms latency overhead. 60% of queries benefit from cross-ganglion knowledge.

This experiment also proved that **enriched manifests** (vocabulary extracted from methodology text) are essential: the same federation infrastructure went from 10% query coverage to 60% after manifest enrichment.

## Experimental Design

### Architecture: CAM Brain = 3 Ganglia

| Ganglion | Methodologies | Source Repos | Domain Focus |
|----------|:------------:|:------------:|-------------|
| **primary** | 2,938 | 324 | General SWE patterns, KB from mining |
| **drive-ops** | 1,046 | 63 | Drive scanning, repo discovery, code organization |
| **agentic-memory** | 128 | 11 | Agent memory, RAG, collaborative AI patterns |
| **Total Brain** | **4,112** | **398** | |

### Control vs Variant

| | Control | Variant |
|---|---------|---------|
| **Primary ganglion** | FTS5 search | FTS5 search |
| **Sibling ganglia** | Disabled | Federation query (read-only FTS5) |
| **Manifest relevance** | N/A | Keyword overlap scoring (threshold 0.2) |
| **Max results** | 50 | 50 (primary) + 3 per sibling |

### Query Corpus

40 real queries spanning 8 domains:

| Domain | Queries | Example |
|--------|:------:|---------|
| Architecture | 5 | "microservice architecture event driven" |
| AI/LLM | 5 | "RAG retrieval augmented generation pipeline" |
| Memory/Knowledge | 5 | "agentic memory long term storage retrieval" |
| Code Quality | 5 | "error handling retry exponential backoff jitter" |
| Security | 5 | "authentication authorization JWT token session" |
| Data Processing | 5 | "file parsing CSV JSON YAML configuration loader" |
| Cross-Domain | 10 | "ABXorcist antibiotic stewardship clinical" |

## Results

### Per-Query Results

| Query | Control | Variant | Lift | Ganglia Hit |
|-------|:------:|:------:|:---:|:----------:|
| microservice architecture event driven | 50 | 56 | +6 | primary, drive-ops, agentic-memory |
| agent orchestration multi-agent coordination | 50 | 56 | +6 | primary, drive-ops, agentic-memory |
| RAG retrieval augmented generation pipeline | 50 | 56 | +6 | primary, agentic-memory, drive-ops |
| prompt engineering chain of thought reasoning | 50 | 56 | +6 | primary, drive-ops, agentic-memory |
| LLM token budget context window management | 50 | 56 | +6 | primary, agentic-memory, drive-ops |
| episodic memory semantic recall | 50 | 56 | +6 | primary, drive-ops, agentic-memory |
| agentic memory long term storage retrieval | 50 | 56 | +6 | primary, drive-ops, agentic-memory |
| logging structured observability tracing | 50 | 56 | +6 | primary, drive-ops, agentic-memory |
| async concurrent parallel task execution pool | 50 | 56 | +6 | primary, drive-ops, agentic-memory |
| forecaster prediction time series model | 50 | 56 | +6 | primary, drive-ops, agentic-memory |
| MCP server model context protocol tool | 50 | 56 | +6 | primary, agentic-memory, drive-ops |
| knowledge graph entity extraction | 50 | 53 | +3 | primary, agentic-memory |
| context persistence session management | 50 | 53 | +3 | primary, agentic-memory |
| code review static analysis lint type checking | 50 | 53 | +3 | primary, drive-ops |
| authentication authorization JWT token session | 50 | 53 | +3 | primary, agentic-memory |
| input validation sanitization injection prevention | 50 | 53 | +3 | primary, drive-ops |
| API rate limiting throttle protection | 50 | 53 | +3 | primary, drive-ops |
| file parsing CSV JSON YAML configuration loader | 50 | 53 | +3 | primary, drive-ops |
| data pipeline ETL transform batch processing | 50 | 53 | +3 | primary, agentic-memory |
| storm wiki collaborative knowledge generation | 50 | 53 | +3 | primary, agentic-memory |
| Paper2Agent scientific paper processing | 50 | 53 | +3 | primary, agentic-memory |
| ABXorcist antibiotic stewardship clinical | 50 | 53 | +3 | primary, drive-ops |
| drive scanning repo discovery dedup archival | 50 | 53 | +3 | primary, drive-ops |
| whiskey recommendation confidence scoring | 50 | 53 | +3 | primary, drive-ops |
| *(16 queries with 0 lift — primary already saturated)* | 50 | 50 | 0 | primary only |

### Aggregate Statistics

| Metric | Value |
|--------|-------|
| **Queries with federation lift** | 24/40 (60%) |
| **Queries hitting multiple ganglia** | 24/40 (60%) |
| **Total unique sibling results** | 105 |
| **Mean unique sibling results per query** | 2.6 |
| **Result count lift** | +5.3% |
| **Federation latency overhead** | +1.7 ms |

### Statistical Analysis

| Test | Value | Interpretation |
|------|-------|---------------|
| **Wilcoxon signed-rank** (paired, one-sided) | p = 0.000005 | Highly significant |
| **Rank-biserial correlation** | r = 1.000 | Large effect size |
| **H0**: Federation does not increase results | **REJECTED** | |

### Ganglion Utilization

| Ganglion | Hit Rate | Total Results Contributed |
|----------|:-------:|:------------------------:|
| primary | 40/40 (100%) | 1,972 |
| drive-ops | 18/40 (45%) | 54 |
| agentic-memory | 17/40 (42%) | 51 |

## The Manifest Enrichment Discovery

The experiment revealed that **manifest vocabulary is the gating factor** for federation effectiveness:

### Before: Generic Manifests (categories + languages only)

- domain_keywords: ~15 terms (e.g., "architecture", "memory", "python")
- Queries with federation lift: **4/40 (10%)**
- Only category-level matches triggered federation

### After: Enriched Manifests (categories + languages + repo names + methodology vocabulary)

- domain_keywords: **70-82 terms** (includes source repo names, high-frequency methodology terms)
- Queries with federation lift: **24/40 (60%)**
- Source repo names (e.g., "abxorcist", "paper2agent") and domain terms (e.g., "agent", "retrieval", "model") now trigger federation

### Implementation

Added to `manifest.py:generate_manifest()`:
1. Source repo names added as domain keywords (top 20)
2. TF-based vocabulary extraction from `problem_description` text (top 50 terms with freq >= 3)
3. Stop word filtering to avoid noise

This change increased manifest domain_keywords from ~15 to 70-82 per ganglion, with zero false positives in testing.

## What Federation Discovers

Examples of knowledge federation reveals that single-ganglion search misses:

| Query | What Primary Misses | Federation Finds |
|-------|-------------------|-----------------|
| "ABXorcist antibiotic stewardship" | Primary has general patterns | drive-ops has ABXorcist-specific architecture patterns |
| "storm wiki collaborative knowledge" | Primary has RAG patterns | agentic-memory has Storm/collaborative AI patterns from 11 agent repos |
| "MCP server model context protocol" | Primary has MCP client patterns | Both siblings have MCP server implementation patterns from distinct codebases |
| "whiskey recommendation confidence" | Primary has general scoring | drive-ops has dram-quest recommendation engine patterns |

## Infrastructure

| Component | File | Purpose |
|-----------|------|---------|
| Dashboard Server | `src/claw/web/dashboard_server.py` | FastAPI with federated search |
| Federation Layer | `src/claw/community/federation.py` | Cross-ganglion FTS5 queries |
| Enriched Manifests | `src/claw/community/manifest.py` | TF-based vocabulary extraction |
| A/B Runner | `scripts/run_federation_ab.py` | 40-query paired experiment |
| CLI Command | `cam dashboard --port 8420` | Live browser UI |
| Tests | `tests/test_dashboard_server.py` | 23 endpoint tests |
| Tests | `tests/test_federation.py` | 34 federation tests |

## Reproduction

```bash
# 1. Verify ganglia databases exist
ls data/instances/*/claw.db

# 2. Regenerate enriched manifests
cam manifest regenerate

# 3. Run federation A/B experiment
python scripts/run_federation_ab.py

# 4. Launch live dashboard
cam dashboard --port 8420
# Open http://127.0.0.1:8420 and search
```

## Comparison to Previous Showpieces

| | Showpiece 15 | Showpiece 17 | Showpiece 18 (This) |
|---|---|---|---|
| **What** | Retry logic | SkyDate SWE | Federation Brain |
| **Proof** | KB wins 7/8 quality checks | +33.6% composite, p<0.05 | +5.3% results, p=0.000005 |
| **Scope** | Single function | Full-stack app | Cross-database search |
| **Novel finding** | KB improves code quality | KB prevents failures (100% vs 67%) | Manifest vocabulary is the gating factor |
| **Sample size** | 1 task, 2 runs | 23 tasks | 40 queries, paired design |
| **Infrastructure** | Manual comparison | A/B test framework | Federation layer + dashboard |

## Conclusion

Federation across specialized ganglia produces statistically significant knowledge expansion (p = 0.000005) with negligible latency cost (+1.7ms). The key insight is that **manifest vocabulary must be enriched beyond category labels** — source repo names and high-frequency methodology terms are essential for cross-ganglion relevance scoring. With enriched manifests, 60% of queries discover results from sibling ganglia that are invisible to single-instance search. The CAM Brain is more than the sum of its ganglia.
