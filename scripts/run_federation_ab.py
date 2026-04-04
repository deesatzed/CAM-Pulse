#!/usr/bin/env python3
"""Federation A/B Experiment — Showpiece #18.

Runs real queries against the CAM Brain in two modes:
  - Control: primary ganglion only (federation disabled)
  - Variant: primary + all sibling ganglia (federation enabled)

Measures result count, ganglion diversity, latency, and unique sibling
contributions per query.  Statistical analysis via paired Wilcoxon
signed-rank test + effect size.

Usage:
    python scripts/run_federation_ab.py
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claw.community.federation import Federation, _extract_keywords, _build_safe_fts5_query
from claw.community.manifest import load_manifest, score_manifest_relevance
from claw.core.config import load_config
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository


# ---------------------------------------------------------------------------
# 30 real queries spanning domains present across ganglia
# ---------------------------------------------------------------------------

QUERIES = [
    # Architecture / design patterns (high federation value)
    "microservice architecture event driven",
    "plugin system extensible modular design",
    "dependency injection factory pattern",
    "adapter pattern interface abstraction",
    "observer pattern event bus publish subscribe",
    # AI / LLM integration (all ganglia have this)
    "agent orchestration multi-agent coordination",
    "RAG retrieval augmented generation pipeline",
    "embedding vector similarity search",
    "prompt engineering chain of thought reasoning",
    "LLM token budget context window management",
    # Memory / knowledge systems (strong in agentic-memory)
    "episodic memory semantic recall",
    "knowledge graph entity extraction",
    "context persistence session management",
    "agentic memory long term storage retrieval",
    "caching strategy cache invalidation policy",
    # Code quality / testing (all ganglia)
    "pytest fixture parameterize coverage",
    "error handling retry exponential backoff jitter",
    "logging structured observability tracing",
    "code review static analysis lint type checking",
    "refactoring extract method decompose function",
    # Security (drive-ops has 66, agentic-memory 11)
    "authentication authorization JWT token session",
    "input validation sanitization injection prevention",
    "HIPAA compliance PHI encryption audit trail",
    "API rate limiting throttle protection",
    "secret management environment variable rotation",
    # Data processing / CLI (drive-ops heavy)
    "file parsing CSV JSON YAML configuration loader",
    "database migration schema evolution versioning",
    "CLI argument parsing typer click command interface",
    "async concurrent parallel task execution pool",
    "data pipeline ETL transform batch processing",
    # Cross-domain queries (designed to stress federation boundaries)
    "storm wiki collaborative knowledge generation",
    "ragflow infiniflow document chunking",
    "Paper2Agent scientific paper processing",
    "ABXorcist antibiotic stewardship clinical",
    "FHIR HL7 medical device integration",
    "forecaster prediction time series model",
    "drive scanning repo discovery dedup archival",
    "MCP server model context protocol tool",
    "whiskey recommendation confidence scoring",
    "emergency department alert triage",
]


# ---------------------------------------------------------------------------
# Core experiment
# ---------------------------------------------------------------------------


def _safe_fts5(query: str) -> str:
    """Convert a natural-language query to a safe FTS5 MATCH string."""
    keywords = _extract_keywords(query)
    return _build_safe_fts5_query(keywords)


async def _search_primary_only(engine: DatabaseEngine, query: str, limit: int = 20):
    """Search only the primary ganglion via FTS5 — control arm."""
    fts_q = _safe_fts5(query)
    if not fts_q:
        return {"total": 0, "ganglion_counts": {"primary": 0}, "ganglia_hit": 1, "elapsed_ms": 0, "ids": []}
    t0 = time.monotonic()
    rows = await engine.fetch_all(
        "SELECT m.id, m.problem_description, m.language, m.lifecycle_state, "
        "m.novelty_score, rank AS fts_rank "
        "FROM methodology_fts f "
        "JOIN methodologies m ON f.rowid = m.rowid "
        "WHERE methodology_fts MATCH ? "
        "ORDER BY rank LIMIT ?",
        (fts_q, limit),
    )
    elapsed = (time.monotonic() - t0) * 1000
    return {
        "total": len(rows),
        "ganglion_counts": {"primary": len(rows)},
        "ganglia_hit": 1,
        "elapsed_ms": round(elapsed, 2),
        "ids": [r["id"] for r in rows],
    }


async def _search_federated(
    engine: DatabaseEngine, federation: Federation, query: str, limit: int = 20
):
    """Search primary + all siblings — variant arm."""
    fts_q = _safe_fts5(query)
    if not fts_q:
        return {"total": 0, "primary_count": 0, "sibling_unique": 0, "ganglion_counts": {"primary": 0}, "ganglia_hit": 1, "elapsed_ms": 0, "ids": []}
    t0 = time.monotonic()

    # Primary search
    primary_rows = await engine.fetch_all(
        "SELECT m.id, m.problem_description, m.language, m.lifecycle_state, "
        "m.novelty_score, rank AS fts_rank "
        "FROM methodology_fts f "
        "JOIN methodologies m ON f.rowid = m.rowid "
        "WHERE methodology_fts MATCH ? "
        "ORDER BY rank LIMIT ?",
        (fts_q, limit),
    )
    primary_ids = {r["id"] for r in primary_rows}

    # Federation search (siblings) — use higher limit to see full tail
    fed_results = await federation.query(query, max_total=limit)

    elapsed = (time.monotonic() - t0) * 1000

    # Build ganglion counts
    ganglion_counts: dict[str, int] = {"primary": len(primary_rows)}
    sibling_unique_ids: set[str] = set()
    for fr in fed_results:
        g = fr.source_instance
        ganglion_counts[g] = ganglion_counts.get(g, 0) + 1
        if fr.methodology.id not in primary_ids:
            sibling_unique_ids.add(fr.methodology.id)

    all_ids = list(primary_ids)
    for fr in fed_results:
        if fr.methodology.id not in primary_ids:
            all_ids.append(fr.methodology.id)

    return {
        "total": len(primary_rows) + len(sibling_unique_ids),
        "primary_count": len(primary_rows),
        "sibling_unique": len(sibling_unique_ids),
        "ganglion_counts": ganglion_counts,
        "ganglia_hit": len(ganglion_counts),
        "elapsed_ms": round(elapsed, 2),
        "ids": all_ids,
    }


async def run_experiment():
    """Execute the full federation A/B experiment."""
    print("=" * 70)
    print("CAM Federation A/B Experiment — Showpiece #18")
    print("=" * 70)
    print()

    # Initialize
    config = load_config()
    engine = DatabaseEngine(config.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()

    # Verify federation
    if not config.instances or not config.instances.enabled:
        print("ERROR: Federation not configured. Enable [instances] in claw.toml")
        return
    siblings = config.instances.siblings
    if not siblings:
        print("ERROR: No siblings configured.")
        return

    federation = Federation(config.instances)

    # Count methodologies per ganglion
    repo = Repository(engine)
    primary_total = await repo.count_methodologies()
    print(f"Primary ganglion: {primary_total:,} methodologies")
    import aiosqlite

    for sib in siblings:
        if Path(sib.db_path).exists():
            async with aiosqlite.connect(f"file:{sib.db_path}?mode=ro", uri=True) as db:
                cur = await db.execute("SELECT COUNT(*) FROM methodologies")
                row = await cur.fetchone()
                print(f"  {sib.name}: {row[0]:,} methodologies")
        else:
            print(f"  {sib.name}: DB NOT FOUND at {sib.db_path}")
    print()

    # Run each query in both modes
    results = []
    print(f"Running {len(QUERIES)} queries in control (primary-only) and variant (federated)...")
    print("-" * 70)

    search_limit = 50  # Higher limit to see federation tail
    for i, query in enumerate(QUERIES, 1):
        control = await _search_primary_only(engine, query, limit=search_limit)
        variant = await _search_federated(engine, federation, query, limit=search_limit)

        result = {
            "query": query,
            "control_total": control["total"],
            "variant_total": variant["total"],
            "sibling_unique": variant["sibling_unique"],
            "control_ganglia": control["ganglia_hit"],
            "variant_ganglia": variant["ganglia_hit"],
            "control_ms": control["elapsed_ms"],
            "variant_ms": variant["elapsed_ms"],
            "ganglion_counts": variant["ganglion_counts"],
            "lift": variant["total"] - control["total"],
        }
        results.append(result)

        # Print progress
        ganglia_str = ", ".join(f"{k}={v}" for k, v in variant["ganglion_counts"].items())
        lift_str = f"+{result['lift']}" if result["lift"] > 0 else str(result["lift"])
        print(
            f"  [{i:2d}/{len(QUERIES)}] {query[:50]:50s} "
            f"ctrl={control['total']:2d} fed={variant['total']:2d} "
            f"({lift_str:>3s}) [{ganglia_str}]"
        )

    print("-" * 70)
    print()

    # Save raw results
    output_path = Path("evidence/federation_ab_results.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({"experiment": "federation_ab", "queries": results}, f, indent=2)
    print(f"Raw results saved to {output_path}")

    # ---------------------------------------------------------------------------
    # Statistical analysis
    # ---------------------------------------------------------------------------
    print()
    print("=" * 70)
    print("Statistical Analysis")
    print("=" * 70)
    print()

    control_totals = [r["control_total"] for r in results]
    variant_totals = [r["variant_total"] for r in results]
    lifts = [r["lift"] for r in results]
    sibling_uniques = [r["sibling_unique"] for r in results]
    variant_ganglia = [r["variant_ganglia"] for r in results]

    # Basic counts
    queries_with_lift = sum(1 for l in lifts if l > 0)
    queries_with_multi_ganglion = sum(1 for g in variant_ganglia if g > 1)

    print(f"Queries with federation lift:       {queries_with_lift}/{len(QUERIES)} ({queries_with_lift/len(QUERIES)*100:.0f}%)")
    print(f"Queries hitting multiple ganglia:    {queries_with_multi_ganglion}/{len(QUERIES)} ({queries_with_multi_ganglion/len(QUERIES)*100:.0f}%)")
    print()

    # Result count comparison
    ctrl_mean = statistics.mean(control_totals)
    var_mean = statistics.mean(variant_totals)
    print(f"Control mean results:  {ctrl_mean:.1f}")
    print(f"Variant mean results:  {var_mean:.1f}")
    if ctrl_mean > 0:
        pct_lift = ((var_mean - ctrl_mean) / ctrl_mean) * 100
        print(f"Result count lift:     +{pct_lift:.1f}%")
    print()

    # Unique sibling contributions
    total_sibling = sum(sibling_uniques)
    print(f"Total unique sibling results:  {total_sibling}")
    print(f"Mean unique sibling per query: {statistics.mean(sibling_uniques):.1f}")
    print()

    # Latency
    ctrl_latency = [r["control_ms"] for r in results]
    var_latency = [r["variant_ms"] for r in results]
    print(f"Control mean latency:  {statistics.mean(ctrl_latency):.1f} ms")
    print(f"Variant mean latency:  {statistics.mean(var_latency):.1f} ms")
    overhead = statistics.mean(var_latency) - statistics.mean(ctrl_latency)
    print(f"Federation overhead:   +{overhead:.1f} ms")
    print()

    # Ganglion utilization
    ganglion_hit_counts: dict[str, int] = {}
    for r in results:
        for g in r["ganglion_counts"]:
            ganglion_hit_counts[g] = ganglion_hit_counts.get(g, 0) + 1
    print("Ganglion utilization across all queries:")
    for g, count in sorted(ganglion_hit_counts.items(), key=lambda x: -x[1]):
        print(f"  {g}: hit in {count}/{len(QUERIES)} queries ({count/len(QUERIES)*100:.0f}%)")
    print()

    # Statistical test: paired Wilcoxon signed-rank
    try:
        from scipy.stats import wilcoxon

        # Only include pairs where there's a difference
        diffs = [v - c for c, v in zip(control_totals, variant_totals)]
        non_zero = [d for d in diffs if d != 0]

        if len(non_zero) >= 6:
            stat, p_value = wilcoxon(
                control_totals, variant_totals, alternative="less"
            )
            print(f"Wilcoxon signed-rank test (paired, one-sided):")
            print(f"  H0: federation does not increase result count")
            print(f"  statistic = {stat:.1f}")
            print(f"  p-value   = {p_value:.6f}")
            print(f"  {'SIGNIFICANT (p < 0.05)' if p_value < 0.05 else 'Not significant'}")
        else:
            print(f"Wilcoxon test: only {len(non_zero)} non-zero differences (need ≥6). Skipped.")
        print()
    except ImportError:
        print("scipy not installed — skipping Wilcoxon test")
        print()

    # Effect size: matched-pairs rank-biserial correlation
    if lifts:
        pos = sum(1 for l in lifts if l > 0)
        neg = sum(1 for l in lifts if l < 0)
        n = pos + neg
        if n > 0:
            r_rb = (pos - neg) / n
            print(f"Rank-biserial correlation: r = {r_rb:.3f}")
            if r_rb > 0.5:
                print(f"  Effect size: LARGE")
            elif r_rb > 0.3:
                print(f"  Effect size: MEDIUM")
            elif r_rb > 0.1:
                print(f"  Effect size: SMALL")
            else:
                print(f"  Effect size: NEGLIGIBLE")
        print()

    # Per-ganglion unique result summary
    sibling_results_by_ganglion: dict[str, int] = {}
    for r in results:
        for g, cnt in r["ganglion_counts"].items():
            if g != "primary":
                sibling_results_by_ganglion[g] = sibling_results_by_ganglion.get(g, 0) + cnt
    if sibling_results_by_ganglion:
        print("Sibling result contributions (total across all queries):")
        for g, cnt in sorted(sibling_results_by_ganglion.items(), key=lambda x: -x[1]):
            print(f"  {g}: {cnt} results")
        print()

    # Summary verdict
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    if queries_with_lift > len(QUERIES) * 0.5:
        print(f"Federation IMPROVES result coverage in {queries_with_lift}/{len(QUERIES)} queries ({queries_with_lift/len(QUERIES)*100:.0f}%).")
        print(f"Average lift: +{pct_lift:.1f}% more results with +{overhead:.1f}ms latency overhead.")
        if total_sibling > 0:
            print(f"{total_sibling} unique results discovered ONLY through federation (not in primary).")
    elif queries_with_lift > 0:
        print(f"Federation provides PARTIAL lift in {queries_with_lift}/{len(QUERIES)} queries.")
    else:
        print("Federation did NOT produce additional results for these queries.")
    print("=" * 70)

    # Cleanup
    await engine.close()

    # Return results for programmatic use
    return results


if __name__ == "__main__":
    asyncio.run(run_experiment())
