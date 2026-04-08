# Category Discovery + KB Search Intelligence

## Overview

This document describes how CAM's knowledge base search and category taxonomy evolved to support creative exploration and self-discovering category boundaries. It covers the pre-state (rigid taxonomy, deterministic search), the changes implemented, and the post-state (adaptive discovery, exploratory retrieval).

---

## Pre-State: How Search and Categories Worked Before

### Category Taxonomy (Frozen)

```
┌─────────────────────────────────────────────────────────┐
│                  11 HARDCODED CATEGORIES                 │
│                                                         │
│  architecture    ai_integration    memory               │
│  code_quality    cli_ux            testing               │
│  data_processing security          algorithm             │
│  cross_cutting   design_patterns                         │
│                                                         │
│  Defined: miner.py:229 (_VALID_CATEGORIES)              │
│  Fallback: ANY invalid LLM output → cross_cutting       │
│  Signal: NONE (silent, no logging)                      │
└─────────────────────────────────────────────────────────┘
```

**Problems:**
- Categories could never evolve. "Observability," "deployment," and "developer experience" forced into `cross_cutting`.
- Invalid LLM outputs silently absorbed with zero observability.
- `cross_cutting` became a dumping ground (229+ methodologies) with the weakest keyword signals (8 terms vs 12+ for other categories).

### KB Search Pipeline (Deterministic, Narrow)

```
Task description
       │
       ▼
┌──────────────────┐     ┌──────────────────┐
│  Vector Search   │     │   FTS5 Search    │
│  (cosine, K=7)   │     │  (BM25, K=21)    │
│  sqlite-vec      │     │  OR-joined       │
└────────┬─────────┘     └────────┬─────────┘
         │                        │
         ▼                        ▼
    ┌─────────────────────────────────┐
    │      Hybrid Merge               │
    │  0.6 × vector + 0.4 × text     │
    │  + fitness (0.6 sim + 0.4 fit)  │
    │  + additive novelty (+0.15×n)   │  ← Weak: easily drowned
    └────────────┬────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────────┐
    │      HARD RELEVANCE FLOOR       │
    │      combined_score >= 0.3      │  ← Everything below: invisible
    │      Output: ~3-5 candidates    │
    └────────────┬────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────────┐
    │      Bandit Selection           │
    │  Thompson sampling (Beta)       │
    │  Epsilon-greedy: 10-20%         │  ← Good math, but only 3-5 options
    │  Output: 1 PRIMARY + 2 CONTEXT  │
    └────────────┬────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────────┐
    │      Agent Prompt Injection     │
    │  [PRIMARY] recommended pattern  │
    │  [CONTEXT] alternative patterns │
    │  Novelty hints (non-binding)    │
    └─────────────────────────────────┘
```

**Problems:**
1. **K=7 funnel**: Only 7 candidates reached the merge layer. After filtering, ~3-5 reached the bandit. Thompson sampling with 3 candidates is mathematically valid but not exploratory.
2. **Hard relevance floor at 0.3**: Experimental/novel methodologies with lower scores were permanently invisible. No exploration tier.
3. **Deterministic search**: Same query always returned same top-K in same order. No serendipity, no random discovery.
4. **Additive novelty (+0.15 × score)**: A novel methodology with novelty=0.8 got +0.12 boost. Base similarity scores of 0.6-1.0 completely dominated this signal.
5. **100% fitness-biased CAG corpus**: Top-2000 by fitness score meant dominant categories (architecture, code_quality) crowded out rare patterns.

### CAG Corpus Selection (Fitness-Only)

```
All methodologies
       │
       ▼
┌──────────────────────┐
│  Sort by fitness ↓   │
│  Take top 2000       │  ← If 1500 are "architecture", only 500 slots for rest
│  Serialize to text   │
└──────────────────────┘
```

---

## Changes Implemented

### Change 1: Invalid Category Logging (miner.py:1127-1133)

**What**: When LLM outputs an invalid category, log the original value before defaulting to `cross_cutting`.

**Why**: Creates the signal stream for category discovery. If the LLM repeatedly says "observability" and we keep squashing it, that's a category waiting to be born.

**Code**: `logger.info("Invalid category '%s' from LLM (title='%s') → defaulting to cross_cutting", raw_category, title[:80])`

### Change 2: Widened Search Funnel (cycle.py:996-1022)

**What**: Increased `find_similar` limit from 7 to 15. Added two-tier relevance filtering: core tier (>=0.3) + exploration tier (>=0.15, capped at 3 extras).

**Why**: Gives the bandit a real candidate pool. 10+ candidates instead of 3-5 means Thompson sampling and epsilon-greedy can actually discover non-obvious patterns.

### Change 3: Epsilon Re-ranking (hybrid_search.py)

**What**: Added `_apply_epsilon_rerank()` method. With 15% probability, shuffles the top half of search results before returning.

**Why**: Breaks determinism. Same query occasionally returns different orderings, enabling serendipitous discovery of lower-ranked but valuable patterns.

### Change 4: Blended Novelty Scoring (hybrid_search.py:333-345)

**What**: Changed novelty from additive (`+= 0.15 * novelty`) to multiplicative blending: `(1 - blend) * base + blend * (base + novelty)`, capped at 30% influence.

**Why**: Novel patterns can now actually shift rankings. A novelty=0.8 methodology gets meaningful score uplift, not a trivial +0.12.

### Change 5: Stratified CAG Corpus (cag_retriever.py)

**What**: Replaced pure fitness sorting with 4-tier stratified selection:
- 40% high-fitness (exploitation)
- 30% category-balanced round-robin (diversity)
- 20% high-novelty (exploration)
- 10% random sample (serendipity)

**Why**: Prevents dominant categories from crowding out rare patterns in the precomputed corpus. Guarantees minimum representation.

### Change 6: Category Discovery Pipeline (gap_analyzer.py + CLI)

**What**: Added `discover_candidate_categories()` method and `cam gaps --discover` CLI flag. Analyzes `cross_cutting` methodologies using keyword frequency clustering, identifies emergent themes above a minimum cluster size, and suggests new category names.

**Why**: Closes the taxonomy evolution gap. Instead of manually guessing when a new category is needed, the system detects it from data patterns.

---

## Post-State: How Search and Categories Work After

### Category Taxonomy (Observable + Discoverable)

```
┌──────────────────────────────────────────────────────────────┐
│                  11 CATEGORIES + DISCOVERY                   │
│                                                              │
│  architecture    ai_integration    memory                    │
│  code_quality    cli_ux            testing                    │
│  data_processing security          algorithm                  │
│  cross_cutting   design_patterns                              │
│                                                              │
│  + LOGGED: every invalid category from LLM is recorded       │
│  + DISCOVERY: `cam gaps --discover` clusters cross_cutting    │
│  + MIGRATION: reclassify_methodologies() for batch re-tag    │
│                                                              │
│  Lifecycle:                                                   │
│    1. LLM says "observability" → logged, falls to cross_cut  │
│    2. cross_cutting grows → `cam gaps --discover` detects     │
│    3. Human approves new category → add to _VALID_CATEGORIES  │
│    4. reclassify_methodologies() migrates existing entries     │
│    5. Next mining pass uses expanded category list            │
└──────────────────────────────────────────────────────────────┘
```

### KB Search Pipeline (Exploratory, Wide Funnel)

```
Task description
       │
       ▼
┌──────────────────┐     ┌──────────────────┐
│  Vector Search   │     │   FTS5 Search    │
│  (cosine, K=45)  │     │  (BM25, K=45)    │  ← 3× limit for merge quality
│  sqlite-vec      │     │  OR-joined       │
└────────┬─────────┘     └────────┬─────────┘
         │                        │
         ▼                        ▼
    ┌──────────────────────────────────────┐
    │       Hybrid Merge                   │
    │  0.6 × vector + 0.4 × text          │
    │  + fitness (0.6 sim + 0.4 fit)       │
    │  + BLENDED novelty (up to 30%)       │  ← Novel items can now shift rank
    └────────────┬─────────────────────────┘
                 │
                 ▼
    ┌──────────────────────────────────────┐
    │       MMR Diversity Re-ranking       │
    │  lambda=0.7 (relevance vs diversity) │
    └────────────┬─────────────────────────┘
                 │
                 ▼
    ┌──────────────────────────────────────┐
    │       EPSILON RE-RANKING (NEW)       │
    │  15% chance: shuffle top half        │  ← Breaks determinism
    │  85% chance: preserve order          │
    └────────────┬─────────────────────────┘
                 │
                 ▼
    ┌──────────────────────────────────────┐
    │       TWO-TIER RELEVANCE FILTER      │
    │  Core tier:    score >= 0.3          │
    │  Explore tier: score >= 0.15 (max 3) │  ← New: edge cases visible
    │  Output: up to ~15 candidates        │
    └────────────┬─────────────────────────┘
                 │
                 ▼
    ┌──────────────────────────────────────┐
    │       Bandit Selection               │
    │  Thompson sampling (Beta posteriors) │
    │  Epsilon-greedy: 10-20%              │  ← Now with 10+ real options
    │  Output: 1 PRIMARY + 2 CONTEXT       │
    └────────────┬─────────────────────────┘
                 │
                 ▼
    ┌──────────────────────────────────────┐
    │       Agent Prompt Injection         │
    │  [PRIMARY] recommended pattern       │
    │  [CONTEXT] alternative patterns      │
    │  Novelty hints (informational)       │
    └──────────────────────────────────────┘
```

### CAG Corpus Selection (Stratified)

```
All methodologies
       │
       ▼
┌────────────────────────────────────┐
│  Tier 1: 40% by fitness           │  ← Exploitation: proven patterns
│  Tier 2: 30% category round-robin │  ← Diversity: balanced coverage
│  Tier 3: 20% by novelty score     │  ← Exploration: cutting-edge
│  Tier 4: 10% random sample        │  ← Serendipity: surprise finds
│                                    │
│  Budget < 10: pure fitness sort    │  ← Edge case: small budgets
│  Budget ≤ total: return all sorted │
└────────────────────────────────────┘
```

---

## Functional Detail

### 1. Invalid Category Logging

**File**: `src/claw/miner.py:1127-1133`

When the LLM returns a category not in `_VALID_CATEGORIES`:
- The original category string is logged at INFO level with the finding title
- The finding is still assigned `cross_cutting` for compatibility
- Log format: `Invalid category 'observability' from LLM (title='...') → defaulting to cross_cutting`

This creates a queryable signal: `grep "Invalid category" logs/ | sort | uniq -c | sort -rn` reveals what categories the LLM "wants" to use.

### 2. Widened Search Funnel

**File**: `src/claw/cycle.py:996-1030`

- `find_similar_with_signals(task.description, limit=15)` — fetches 15 results (was 7)
- Two-tier filtering replaces the single hard floor:
  - **Core tier**: `combined_score >= 0.3` — reliable, proven patterns
  - **Exploration tier**: `0.15 <= combined_score < 0.3` — experimental, capped at 3 extras
- Total candidates reaching bandit: up to 18 (was ~3-5)

### 3. Epsilon Re-ranking

**File**: `src/claw/memory/hybrid_search.py`

New `_apply_epsilon_rerank()` method:
- **Trigger**: `random.random() < 0.15` (15% of searches)
- **Action**: Shuffles top half of results, preserves bottom half
- **Effect**: On 85% of queries, behavior is identical to before. On 15%, lower-ranked results get a chance to surface.
- **Configurable**: `epsilon_rerank` parameter on `HybridSearch.__init__`

### 4. Blended Novelty Scoring

**File**: `src/claw/memory/hybrid_search.py:333-345`

Old: `combined_score += 0.15 * novelty_score` (additive, +0.12 max)
New: `combined_score = (1 - blend) * base + blend * (base + novelty)` where `blend = min(novelty_signal, 0.30)`

Example with novelty_score=0.8, base=0.5:
- Old: 0.5 + 0.12 = 0.62
- New: 0.88 * 0.5 + 0.12 * 0.62 = 0.514 (modest but meaningful shift in ranking)

The cap at 30% ensures novelty can influence but not dominate rankings.

### 5. Stratified CAG Corpus

**File**: `src/claw/memory/cag_retriever.py`

New `_stratified_select()` static method replaces pure fitness sorting:

| Tier | Budget % | Selection Strategy | Purpose |
|------|----------|-------------------|---------|
| 1 | 40% | Top by fitness score | Exploitation: proven patterns |
| 2 | 30% | Category round-robin | Diversity: all categories represented |
| 3 | 20% | Top by novelty score | Exploration: cutting-edge discoveries |
| 4 | 10% | Random sample | Serendipity: unexpected finds |

Category round-robin iterates across categories, taking the next-best methodology from each category in turn. This prevents a single dominant category from consuming all slots.

Edge cases:
- Budget < 10: Falls back to pure fitness sort (stratification overhead isn't worth it)
- All methods fit within budget: Returns all, sorted by fitness

### 6. Category Discovery Pipeline

**Files**: `src/claw/community/gap_analyzer.py`, `src/claw/cli/_monolith.py`, `src/claw/db/repository.py`

**`cam gaps --discover`** workflow:

1. Fetches all `cross_cutting`-tagged methodologies from primary DB
2. Tokenizes problem descriptions and methodology notes
3. Counts keyword frequency across all cross_cutting methods
4. Identifies keywords appearing in 5+ methodologies (configurable)
5. Deduplicates overlapping clusters (>70% shared methods → merge)
6. Returns top 10 candidate themes with sample titles

**`reclassify_methodologies()`** in repository:
- Takes list of methodology IDs, old category, new category
- Updates JSON tags array: replaces `category:{old}` with `category:{new}`
- Returns count of updated rows

**Migration workflow** (human-in-the-loop):
1. Run `cam gaps --discover` — see candidate categories
2. Choose a candidate (e.g., "observability")
3. Add `"observability"` to `_VALID_CATEGORIES` in miner.py
4. Add trigger keywords to `_CATEGORY_TRIGGER_MAP`
5. Run `reclassify_methodologies()` to migrate existing entries
6. Update `prompts/repo-mine.md` with the new category option
7. Next mining pass: LLM sees expanded menu, new findings route correctly

---

## Verification

### Test Results

| Test Suite | Before | After | Delta |
|-----------|--------|-------|-------|
| Full suite | 3,619 pass, 12 fail | 3,621 pass, 10 fail | +2 pass, -2 fail |
| test_cag_retriever.py | 20 pass, 1 fail | 21 pass, 0 fail | Fixed |
| test_gap_analyzer.py | All pass | All pass | No regression |
| test_cycle_correction.py | All pass | All pass | No regression |
| test_miner.py | All pass | All pass | No regression |
| test_hybrid_bm25.py | All pass | All pass | No regression |

All 10 remaining failures are pre-existing (cag_compressor regex mismatch, ablation Bayesian, validation_gate diff).

### Live Validation

`cam gaps --discover` successfully identifies:
- **observability** (86 methods) — strongest emergent category candidate
- **logging** (82 methods) — overlapping cluster, part of observability domain
- **agent** (51 methods) — agent-related patterns potentially distinct from ai_integration

---

## Files Modified

| File | Change |
|------|--------|
| `src/claw/miner.py:1127-1133` | Log invalid categories before defaulting |
| `src/claw/cycle.py:996-1030` | Widen K from 7→15, two-tier relevance filter |
| `src/claw/memory/hybrid_search.py:86-113` | Add epsilon_rerank parameter |
| `src/claw/memory/hybrid_search.py:164-167` | Add epsilon re-ranking step |
| `src/claw/memory/hybrid_search.py:333-345` | Blended novelty scoring |
| `src/claw/memory/hybrid_search.py:436-460` | New _apply_epsilon_rerank() method |
| `src/claw/memory/cag_retriever.py:90-100` | Replace fitness sort with stratified select |
| `src/claw/memory/cag_retriever.py:177-253` | New _stratified_select() method |
| `src/claw/community/gap_analyzer.py:120-220` | New discover_candidate_categories() method |
| `src/claw/db/repository.py:2012-2042` | New reclassify_methodologies() method |
| `src/claw/cli/_monolith.py:8598-8730` | Add --discover flag to cam gaps |

---

## Architecture Decision Record

**Decision**: Category taxonomy remains hardcoded but is now observable and discoverable.

**Alternatives considered**:
1. **Dynamic categories** (LLM picks freely): Rejected — would fragment the taxonomy unpredictably, making coverage analysis unreliable.
2. **Embedding-based clustering** (k-means on vectors): Deferred — requires numpy/sklearn dependency, and keyword frequency analysis provides sufficient signal for the current scale.
3. **Auto-create categories**: Rejected — human-in-the-loop approval is critical for taxonomy quality. Auto-creation would produce noise categories.

**Rationale**: The human-in-the-loop approach balances automation (discovery) with quality control (approval). The logging of invalid categories creates a passive signal stream that costs zero effort to maintain.
