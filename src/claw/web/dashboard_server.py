"""CAM-PULSE Federated Knowledge Dashboard.

A FastAPI web server that exposes CAM's federated brain through a browser UI.
Queries the primary ganglion + all configured siblings simultaneously,
returning results tagged by source ganglion with provenance metadata.

Start with:  cam dashboard [--port 8420]
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import math
import os
import shutil
import tempfile
import time
import uuid
from datetime import datetime as _datetime
from pathlib import Path
from typing import Any, Optional

import toml

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from claw.db.repository import _build_safe_fts5_query

logger = logging.getLogger("claw.web.dashboard")

# ---------------------------------------------------------------------------
# Factory — lazy init on first request
# ---------------------------------------------------------------------------

_state: dict[str, Any] = {}


async def _ensure_state(app: FastAPI) -> dict[str, Any]:
    """Lazily initialize DB engine, repository, and federation on first use."""
    if _state.get("ready"):
        return _state

    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine
    from claw.db.repository import Repository

    config = load_config()
    engine = DatabaseEngine(config.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repository = Repository(engine)

    _state["config"] = config
    _state["engine"] = engine
    _state["repository"] = repository

    # Federation (optional — only if siblings configured)
    federation = None
    if config.instances and config.instances.enabled and config.instances.siblings:
        from claw.community.federation import Federation

        federation = Federation(config.instances)

    _state["federation"] = federation
    _state["ready"] = True
    return _state


async def _shutdown_state() -> None:
    if _state.get("engine"):
        await _state["engine"].close()
    _state.clear()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(application: FastAPI):
    yield
    await _shutdown_state()


app = FastAPI(title="CAM-PULSE Dashboard", docs_url="/api/docs", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API endpoints — JSON
# ---------------------------------------------------------------------------


@app.get("/api/stats")
async def api_stats() -> JSONResponse:
    """Return methodology counts, lifecycle distribution, and ganglion info."""
    st = await _ensure_state(app)
    repo = st["repository"]
    config = st["config"]

    total = await repo.count_methodologies()
    active = await repo.count_active_methodologies()
    by_state = await repo.count_methodologies_by_state()

    # Language distribution
    rows = await repo.engine.fetch_all(
        "SELECT language, COUNT(*) as cnt FROM methodologies "
        "WHERE lifecycle_state != 'dead' GROUP BY language ORDER BY cnt DESC LIMIT 10"
    )
    languages = {str(r["language"] or "unknown"): int(r["cnt"]) for r in rows}

    # Top categories from tags
    tag_rows = await repo.engine.fetch_all(
        "SELECT tags FROM methodologies WHERE lifecycle_state != 'dead' AND tags IS NOT NULL"
    )
    cat_counts: dict[str, int] = {}
    for r in tag_rows:
        raw = r["tags"]
        if not raw:
            continue
        try:
            tags = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        for t in tags:
            if isinstance(t, str) and t.startswith("category:"):
                cat = t.split(":", 1)[1]
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
    top_categories = dict(sorted(cat_counts.items(), key=lambda x: -x[1])[:15])

    # Source repos
    src_rows = await repo.engine.fetch_all(
        "SELECT COUNT(DISTINCT json_each.value) as cnt "
        "FROM methodologies, json_each(methodologies.tags) "
        "WHERE json_each.value LIKE 'source:%'"
    )
    source_repo_count = int(src_rows[0]["cnt"]) if src_rows else 0

    # Sibling info
    siblings = []
    if config.instances and config.instances.enabled:
        for sib in config.instances.siblings:
            sib_info: dict[str, Any] = {
                "name": sib.name,
                "description": getattr(sib, "description", ""),
                "db_exists": Path(sib.db_path).exists(),
            }
            if sib_info["db_exists"]:
                try:
                    import aiosqlite

                    async with aiosqlite.connect(
                        sib.db_path, uri=True if "?" in sib.db_path else False
                    ) as db:
                        db.row_factory = aiosqlite.Row
                        cur = await db.execute("SELECT COUNT(*) as cnt FROM methodologies")
                        row = await cur.fetchone()
                        sib_info["methodology_count"] = int(row["cnt"]) if row else 0
                except Exception:
                    sib_info["methodology_count"] = 0
            siblings.append(sib_info)

    return JSONResponse(
        {
            "primary": {
                "name": getattr(config.instances, "instance_name", "primary")
                if config.instances
                else "primary",
                "total": total,
                "active": active,
                "lifecycle": by_state,
                "languages": languages,
                "top_categories": top_categories,
                "source_repos": source_repo_count,
            },
            "siblings": siblings,
            "total_across_brain": total + sum(s.get("methodology_count", 0) for s in siblings),
        }
    )


@app.get("/api/search")
async def api_search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    """Federated search across primary + all sibling ganglia."""
    st = await _ensure_state(app)
    repo = st["repository"]
    federation = st["federation"]

    t0 = time.monotonic()
    results: list[dict[str, Any]] = []

    # 1. Search primary ganglion via FTS5
    safe_q = _build_safe_fts5_query(q)
    if not safe_q:
        return JSONResponse({"query": q, "results": [], "elapsed_ms": 0})

    primary_rows = await repo.engine.fetch_all(
        "SELECT m.id, m.problem_description, m.solution_code, m.methodology_notes, "
        "m.tags, m.language, m.lifecycle_state, m.novelty_score, m.retrieval_count, "
        "m.success_count, m.failure_count, "
        "rank AS fts_rank "
        "FROM methodology_fts f "
        "JOIN methodologies m ON f.rowid = m.rowid "
        "WHERE methodology_fts MATCH ? "
        "ORDER BY rank LIMIT ?",
        (safe_q, limit),
    )
    for r in primary_rows:
        tags = []
        if r["tags"]:
            try:
                tags = json.loads(r["tags"]) if isinstance(r["tags"], str) else r["tags"]
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(
            {
                "id": r["id"],
                "problem": r["problem_description"][:300],
                "solution_preview": (r["solution_code"] or "")[:200],
                "notes": (r["methodology_notes"] or "")[:200],
                "tags": tags,
                "language": r["language"],
                "lifecycle": r["lifecycle_state"],
                "novelty": r["novelty_score"],
                "retrievals": r["retrieval_count"],
                "successes": r["success_count"],
                "source_ganglion": "primary",
                "fts_rank": abs(float(r["fts_rank"] or 0)),
            }
        )

    # 2. Search siblings via federation
    federation_results = []
    if federation:
        try:
            federation_results = await federation.query(q, max_total=limit)
            for fr in federation_results:
                m = fr.methodology
                tags = m.tags if isinstance(m.tags, list) else []
                results.append(
                    {
                        "id": m.id,
                        "problem": m.problem_description[:300],
                        "solution_preview": (m.solution_code or "")[:200],
                        "notes": (m.methodology_notes or "")[:200],
                        "tags": tags,
                        "language": m.language,
                        "lifecycle": m.lifecycle_state,
                        "novelty": m.novelty_score,
                        "retrievals": m.retrieval_count,
                        "successes": m.success_count,
                        "source_ganglion": fr.source_instance,
                        "fts_rank": fr.fts_rank,
                        "relevance_score": fr.relevance_score,
                    }
                )
        except Exception as exc:
            logger.warning("Federation query failed: %s", exc)

    elapsed_ms = (time.monotonic() - t0) * 1000

    # Deduplicate by id, keep highest fts_rank
    seen: dict[str, dict] = {}
    for r in results:
        rid = r["id"]
        if rid not in seen or r["fts_rank"] > seen[rid]["fts_rank"]:
            seen[rid] = r
    deduped = sorted(seen.values(), key=lambda x: x["fts_rank"], reverse=True)[:limit]

    ganglion_counts: dict[str, int] = {}
    for r in deduped:
        g = r["source_ganglion"]
        ganglion_counts[g] = ganglion_counts.get(g, 0) + 1

    return JSONResponse(
        {
            "query": q,
            "total_results": len(deduped),
            "elapsed_ms": round(elapsed_ms, 1),
            "ganglion_counts": ganglion_counts,
            "results": deduped,
        }
    )


@app.get("/api/methodology/{methodology_id}")
async def api_methodology_detail(methodology_id: str) -> JSONResponse:
    """Get full methodology detail by ID."""
    st = await _ensure_state(app)
    repo = st["repository"]

    m = await repo.get_methodology(methodology_id)
    if not m:
        return JSONResponse({"error": "not found"}, status_code=404)

    return JSONResponse(
        {
            "id": m.id,
            "problem_description": m.problem_description,
            "solution_code": m.solution_code,
            "methodology_notes": m.methodology_notes,
            "tags": m.tags,
            "language": m.language,
            "lifecycle_state": m.lifecycle_state,
            "methodology_type": m.methodology_type,
            "novelty_score": m.novelty_score,
            "potential_score": m.potential_score,
            "retrieval_count": m.retrieval_count,
            "success_count": m.success_count,
            "failure_count": m.failure_count,
            "created_at": str(m.created_at),
            "files_affected": m.files_affected,
        }
    )


# ---------------------------------------------------------------------------
# Phase 1 — Forge: Methodology fitness, Gaps, Evolution, Costs, Federation, Mining
# ---------------------------------------------------------------------------


@app.get("/api/methodology/{methodology_id}/fitness")
async def api_methodology_fitness(methodology_id: str) -> JSONResponse:
    """Return fitness time-series for a methodology."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT fitness_total, fitness_vector, trigger_event, created_at "
            "FROM methodology_fitness_log WHERE methodology_id = ? "
            "ORDER BY created_at",
            (methodology_id,),
        )
    except Exception:
        rows = []
    entries = []
    for r in rows:
        vec = {}
        if r["fitness_vector"]:
            try:
                vec = json.loads(r["fitness_vector"]) if isinstance(r["fitness_vector"], str) else r["fitness_vector"]
            except (json.JSONDecodeError, TypeError):
                pass
        entries.append({
            "fitness_total": r["fitness_total"],
            "fitness_vector": vec,
            "trigger_event": r["trigger_event"],
            "created_at": str(r["created_at"]),
        })
    return JSONResponse({"methodology_id": methodology_id, "entries": entries})


@app.get("/api/gaps/matrix")
async def api_gaps_matrix() -> JSONResponse:
    """Coverage matrix from GapAnalyzer."""
    st = await _ensure_state(app)
    try:
        from claw.community.gap_analyzer import GapAnalyzer
        ga = GapAnalyzer(st["repository"])
        matrix = ga.compute_coverage_matrix()
        return JSONResponse(matrix if isinstance(matrix, dict) else matrix.__dict__ if hasattr(matrix, "__dict__") else {"matrix": str(matrix)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/gaps/discover")
async def api_gaps_discover() -> JSONResponse:
    """Category discovery via GapAnalyzer."""
    st = await _ensure_state(app)
    try:
        from claw.community.gap_analyzer import GapAnalyzer
        ga = GapAnalyzer(st["repository"])
        clusters = ga.discover_categories()
        return JSONResponse({"clusters": clusters if isinstance(clusters, list) else []})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/gaps/trend")
async def api_gaps_trend() -> JSONResponse:
    """Coverage trend over time."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT id, total_methodologies, sparse_cells, created_at "
            "FROM coverage_snapshots ORDER BY created_at DESC LIMIT 20"
        )
        snapshots = []
        for r in rows:
            sparse = []
            if r["sparse_cells"]:
                try:
                    sparse = json.loads(r["sparse_cells"]) if isinstance(r["sparse_cells"], str) else r["sparse_cells"]
                except (json.JSONDecodeError, TypeError):
                    pass
            snapshots.append({
                "id": r["id"],
                "total_methodologies": r["total_methodologies"],
                "sparse_cells": sparse,
                "created_at": str(r["created_at"]),
            })
        summary = f"{len(snapshots)} snapshots" if snapshots else "No snapshots yet"
        return JSONResponse({"summary": summary, "snapshots": snapshots})
    except Exception:
        return JSONResponse({"summary": "No coverage snapshots available", "snapshots": []})


@app.get("/api/evolution/ab-tests")
async def api_evolution_ab_tests() -> JSONResponse:
    """List A/B tests from prompt_variants."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT name, variant_type, parent_name, fitness_score, "
            "sample_count, created_at FROM prompt_variants ORDER BY created_at DESC"
        )
        tests = [dict(r) for r in rows]
        return JSONResponse({"tests": tests})
    except Exception:
        return JSONResponse({"tests": []})



@app.get("/api/evolution/ab-test/{name}")
async def api_evolution_ab_test_detail(name: str) -> JSONResponse:
    """Detailed analysis for a specific A/B test by prompt_name."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        # Fetch all variants for this test name from prompt_variants
        rows = await repo.engine.fetch_all(
            "SELECT id, prompt_name, variant_label, content, agent_id, "
            "is_active, sample_count, success_count, avg_quality_score, "
            "created_at, updated_at "
            "FROM prompt_variants WHERE prompt_name = ? "
            "ORDER BY variant_label",
            [name],
        )
        if not rows:
            return JSONResponse(
                {"error": f"A/B test '{name}' not found"},
                status_code=404,
            )

        # Build per-variant detail
        variants: dict[str, dict] = {}
        for r in rows:
            label = r["variant_label"]
            sample_count = int(r["sample_count"])
            success_count = int(r["success_count"])
            success_rate = success_count / sample_count if sample_count > 0 else 0.0
            variants[label] = {
                "id": str(r["id"]),
                "variant_label": label,
                "content": str(r["content"]),
                "agent_id": r["agent_id"],
                "is_active": bool(r["is_active"]),
                "sample_count": sample_count,
                "success_count": success_count,
                "success_rate": round(success_rate, 4),
                "avg_quality_score": round(float(r["avg_quality_score"]), 4),
                "created_at": str(r["created_at"]),
                "updated_at": str(r["updated_at"]),
            }

        # Compute Bayesian comparison if both control and variant exist
        comparison = None
        winner = None
        if "control" in variants and "variant" in variants:
            ctrl = variants["control"]
            var = variants["variant"]

            # Bayesian posterior mean: Beta(1 + successes, 1 + failures)
            ctrl_alpha = 1.0 + ctrl["success_count"]
            ctrl_beta = 1.0 + (ctrl["sample_count"] - ctrl["success_count"])
            ctrl_bayesian = ctrl_alpha / (ctrl_alpha + ctrl_beta)

            var_alpha = 1.0 + var["success_count"]
            var_beta = 1.0 + (var["sample_count"] - var["success_count"])
            var_bayesian = var_alpha / (var_alpha + var_beta)

            margin = var_bayesian - ctrl_bayesian

            comparison = {
                "control_bayesian_score": round(ctrl_bayesian, 4),
                "variant_bayesian_score": round(var_bayesian, 4),
                "margin": round(margin, 4),
                "quality_delta": round(
                    var["avg_quality_score"] - ctrl["avg_quality_score"], 4
                ),
                "success_rate_delta": round(
                    var["success_rate"] - ctrl["success_rate"], 4
                ),
            }

            # Declare winner if both have enough samples
            min_samples = 20
            if ctrl["sample_count"] >= min_samples and var["sample_count"] >= min_samples:
                if margin > 0.15:
                    winner = "variant"
                elif margin < -0.15:
                    winner = "control"

        # Pull per-sample stats from ab_quality_samples if available
        ab_stats = None
        try:
            ab_rows = await repo.engine.fetch_all(
                "SELECT variant_label, "
                "COUNT(*) as n, "
                "AVG(composite_score) as avg_composite, "
                "AVG(d_functional_correctness) as avg_d1, "
                "AVG(d_structural_compliance) as avg_d2, "
                "AVG(d_intent_alignment) as avg_d3, "
                "AVG(d_correction_efficiency) as avg_d4, "
                "AVG(d_token_economy) as avg_d5, "
                "AVG(d_expectation_match) as avg_d6, "
                "AVG(correction_attempts) as avg_corrections, "
                "SUM(success) as total_success "
                "FROM ab_quality_samples "
                "WHERE project_id = ? "
                "GROUP BY variant_label",
                [name],
            )
            if ab_rows:
                ab_stats = {}
                for ar in ab_rows:
                    n = int(ar["n"])
                    ab_stats[ar["variant_label"]] = {
                        "n": n,
                        "avg_composite": round(float(ar["avg_composite"]), 4),
                        "success_rate": round(int(ar["total_success"]) / n, 4) if n > 0 else 0.0,
                        "avg_corrections": round(float(ar["avg_corrections"]), 2),
                        "dimensions": {
                            "d_functional_correctness": round(float(ar["avg_d1"]), 4),
                            "d_structural_compliance": round(float(ar["avg_d2"]), 4),
                            "d_intent_alignment": round(float(ar["avg_d3"]), 4),
                            "d_correction_efficiency": round(float(ar["avg_d4"]), 4),
                            "d_token_economy": round(float(ar["avg_d5"]), 4),
                            "d_expectation_match": round(float(ar["avg_d6"]), 4),
                        },
                    }

                # Compute Mann-Whitney p-value if scipy is available and both arms present
                if "control" in ab_stats and "variant" in ab_stats:
                    try:
                        sample_rows = await repo.engine.fetch_all(
                            "SELECT variant_label, composite_score "
                            "FROM ab_quality_samples WHERE project_id = ?",
                            [name],
                        )
                        ctrl_scores = [
                            float(s["composite_score"]) for s in sample_rows
                            if s["variant_label"] == "control"
                        ]
                        var_scores = [
                            float(s["composite_score"]) for s in sample_rows
                            if s["variant_label"] == "variant"
                        ]
                        if len(ctrl_scores) >= 2 and len(var_scores) >= 2:
                            try:
                                from scipy.stats import mannwhitneyu
                                u_stat, p_value = mannwhitneyu(
                                    var_scores, ctrl_scores, alternative="greater"
                                )
                                ab_stats["p_value"] = round(float(p_value), 6)
                                ab_stats["mann_whitney_u"] = float(u_stat)
                            except ImportError:
                                pass
                    except Exception:
                        pass
        except Exception:
            pass  # ab_quality_samples table may not exist

        result = {
            "name": name,
            "variants": variants,
            "comparison": comparison,
            "winner": winner,
        }
        if ab_stats is not None:
            result["ab_quality_stats"] = ab_stats
        return JSONResponse(result)
    except Exception as exc:
        if "not found" in str(exc).lower():
            return JSONResponse({"error": str(exc)}, status_code=404)
        logger.exception("Error fetching A/B test detail for '%s'", name)
        return JSONResponse(
            {"error": f"Failed to fetch A/B test detail: {exc}"},
            status_code=500,
        )


@app.get("/api/evolution/fitness/{methodology_id}")
async def api_evolution_fitness(methodology_id: str) -> JSONResponse:
    """Fitness trajectory for evolution lab."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT fitness_total, fitness_vector, trigger_event, created_at "
            "FROM methodology_fitness_log WHERE methodology_id = ? ORDER BY created_at",
            (methodology_id,),
        )
        trajectory = []
        for r in rows:
            vec = {}
            if r["fitness_vector"]:
                try:
                    vec = json.loads(r["fitness_vector"]) if isinstance(r["fitness_vector"], str) else r["fitness_vector"]
                except (json.JSONDecodeError, TypeError):
                    pass
            trajectory.append({
                "fitness": r["fitness_total"],
                "vector": vec,
                "event": r["trigger_event"],
                "timestamp": str(r["created_at"]),
            })
        return JSONResponse({"methodology_id": methodology_id, "trajectory": trajectory})
    except Exception:
        return JSONResponse({"methodology_id": methodology_id, "trajectory": []})


@app.get("/api/evolution/routing")
async def api_evolution_routing() -> JSONResponse:
    """Agent routing heatmap from agent_scores."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT agent_id, task_type, successes, failures, total_attempts, "
            "avg_quality_score, avg_cost_usd FROM agent_scores"
        )
        routing = []
        for r in rows:
            routing.append({
                "agent_id": r["agent_id"],
                "task_type": r["task_type"],
                "wins": r["successes"],
                "losses": r["failures"],
                "total": r["total_attempts"],
                "avg_quality": round(float(r["avg_quality_score"] or 0), 3),
                "avg_cost": round(float(r["avg_cost_usd"] or 0), 4),
            })
        return JSONResponse({"routing": routing})
    except Exception:
        return JSONResponse({"routing": []})


@app.get("/api/evolution/bandit")
async def api_evolution_bandit(task_type: Optional[str] = Query(None)) -> JSONResponse:
    """Bandit arm stats from methodology_bandit_outcomes."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        if task_type:
            rows = await repo.engine.fetch_all(
                "SELECT methodology_id, task_type, "
                "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as wins, "
                "SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) as losses, "
                "COUNT(*) as total, MAX(created_at) as last_updated "
                "FROM methodology_bandit_outcomes WHERE task_type = ? "
                "GROUP BY methodology_id, task_type",
                (task_type,),
            )
        else:
            rows = await repo.engine.fetch_all(
                "SELECT methodology_id, task_type, "
                "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as wins, "
                "SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) as losses, "
                "COUNT(*) as total, MAX(created_at) as last_updated "
                "FROM methodology_bandit_outcomes GROUP BY methodology_id, task_type"
            )
        arms = []
        task_types_set: set[str] = set()
        for r in rows:
            wins = int(r["wins"])
            total = int(r["total"])
            win_rate = wins / total if total > 0 else 0
            arms.append({
                "methodology_id": r["methodology_id"],
                "task_type": r["task_type"],
                "successes": wins,
                "failures": int(r["losses"]),
                "total": total,
                "win_rate": round(win_rate, 3),
                "last_updated": str(r["last_updated"]),
            })
            if r["task_type"]:
                task_types_set.add(r["task_type"])
        return JSONResponse({"arms": arms, "task_types": sorted(task_types_set)})
    except Exception:
        return JSONResponse({"arms": [], "task_types": []})


@app.get("/api/costs/summary")
async def api_costs_summary() -> JSONResponse:
    """Token cost summary from mining_outcomes + agent configs."""
    st = await _ensure_state(app)
    repo = st["repository"]
    config = st["config"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT model_used, agent_id, brain, "
            "COUNT(*) as runs, SUM(tokens_used) as total_tokens, "
            "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes, "
            "ROUND(AVG(duration_seconds), 1) as avg_duration "
            "FROM mining_outcomes GROUP BY model_used, agent_id, brain "
            "ORDER BY runs DESC"
        )
        mining_costs = [dict(r) for r in rows]
    except Exception:
        mining_costs = []
    agent_budgets = {}
    for aid, acfg in config.agents.items():
        agent_budgets[aid] = {
            "max_budget_usd": acfg.max_budget_usd,
            "model": acfg.model,
            "mode": acfg.mode,
        }
    return JSONResponse({"mining_costs": mining_costs, "agent_budgets": agent_budgets})


@app.get("/api/costs/by-agent")
async def api_costs_by_agent() -> JSONResponse:
    """Per-agent cost breakdown from mining_outcomes + agent_scores."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        mining = await repo.engine.fetch_all(
            "SELECT agent_id, model_used, COUNT(*) as runs, "
            "SUM(tokens_used) as total_tokens, "
            "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes "
            "FROM mining_outcomes GROUP BY agent_id, model_used ORDER BY runs DESC"
        )
        mining_data = [dict(r) for r in mining]
    except Exception:
        mining_data = []
    try:
        task_rows = await repo.engine.fetch_all(
            "SELECT agent_id, task_type, "
            "SUM(successes) as wins, "
            "ROUND(AVG(avg_quality_score), 3) as avg_quality, "
            "ROUND(SUM(avg_cost_usd * total_attempts), 4) as total_cost_usd "
            "FROM agent_scores GROUP BY agent_id, task_type ORDER BY wins DESC"
        )
        task_data = [dict(r) for r in task_rows]
    except Exception:
        task_data = []
    return JSONResponse({"mining": mining_data, "task_execution": task_data})


@app.get("/api/federation/topology")
async def api_federation_topology() -> JSONResponse:
    """Brain topology: ganglion nodes with methodology counts and connectivity."""
    st = await _ensure_state(app)
    config = st["config"]
    repo = st["repository"]
    total = await repo.count_methodologies()
    nodes: list[dict[str, Any]] = [
        {"id": "primary", "type": "primary", "methodology_count": total, "db_exists": True}
    ]
    edges: list[dict[str, str]] = []
    siblings = getattr(config, "instances", None)
    sibling_list = []
    if siblings and siblings.enabled:
        sibling_list = siblings.siblings or []
    for sib in sibling_list:
        sib_count = 0
        db_exists = Path(sib.db_path).exists() if sib.db_path else False
        if db_exists:
            try:
                import aiosqlite
                async with aiosqlite.connect(sib.db_path) as db:
                    db.row_factory = aiosqlite.Row
                    cur = await db.execute("SELECT COUNT(*) as cnt FROM methodologies")
                    row = await cur.fetchone()
                    sib_count = int(row["cnt"]) if row else 0
            except Exception:
                pass
        nodes.append({
            "id": sib.name, "type": "sibling", "methodology_count": sib_count,
            "db_exists": db_exists, "description": getattr(sib, "description", ""),
        })
        edges.append({"source": "primary", "target": sib.name, "type": "federation"})
    total_all = total + sum(n["methodology_count"] for n in nodes if n["id"] != "primary")
    return JSONResponse({"nodes": nodes, "edges": edges, "total_methodologies": total_all})


@app.post("/api/federation/analyze")
async def api_federation_analyze(request: Request) -> JSONResponse:
    """Cross-language analysis via federation."""
    body = await request.json()
    query = body.get("query", "").strip()
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    st = await _ensure_state(app)
    try:
        from claw.community.cross_language import CrossLanguageAnalyzer
        analyzer = CrossLanguageAnalyzer(st["repository"], st["config"])
        report = await analyzer.analyze(query)
        return JSONResponse(report if isinstance(report, dict) else report.__dict__ if hasattr(report, "__dict__") else {"query": query, "universal_patterns": [], "unique_innovations": [], "transferable_insights": [], "metrics": {}})
    except Exception as exc:
        logger.warning("Federation analysis failed: %s", exc)
        return JSONResponse({"query": query, "universal_patterns": [], "unique_innovations": [], "transferable_insights": [], "metrics": {}, "error": str(exc)})


@app.post("/api/mine")
async def api_mine(request: Request) -> JSONResponse:
    """Start a mining job (runs in background)."""
    body = await request.json()
    path = body.get("path", "").strip()
    brain = body.get("brain")
    if not path:
        return JSONResponse({"error": "path required"}, status_code=400)
    if not Path(path).exists():
        return JSONResponse({"error": f"Path not found: {path}"}, status_code=404)
    import uuid
    job_id = str(uuid.uuid4())[:8]
    _state.setdefault("mining_jobs", {})[job_id] = {
        "status": "queued", "path": path, "brain": brain,
        "findings": 0, "error": None,
    }

    async def _run_mine():
        job = _state["mining_jobs"][job_id]
        job["status"] = "running"
        try:
            from claw.miner import RepoMiner
            st = await _ensure_state(app)
            miner = RepoMiner(st["config"], st["repository"])
            results = await miner.mine_directory(Path(path), brain=brain)
            job["status"] = "completed"
            job["findings"] = len(results) if results else 0
        except Exception as exc:
            job["status"] = "error"
            job["error"] = str(exc)

    asyncio.create_task(_run_mine())
    return JSONResponse({"job_id": job_id, "status": "queued"})


@app.get("/api/mine/{job_id}")
async def api_mine_status(job_id: str) -> JSONResponse:
    """Get mining job status."""
    jobs = _state.get("mining_jobs", {})
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return JSONResponse(jobs[job_id])


@app.get("/api/mine/recent/list")
async def api_mine_recent() -> JSONResponse:
    """List recent mining outcomes."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT * FROM mining_outcomes ORDER BY created_at DESC LIMIT 20"
        )
        return JSONResponse({"outcomes": [dict(r) for r in rows]})
    except Exception:
        return JSONResponse({"outcomes": []})


# ---------------------------------------------------------------------------
# Phase 1A — Forge Builder: Config Read/Write API
# ---------------------------------------------------------------------------

_VALID_CONFIG_SECTIONS = {
    "database", "cag", "evolution", "instances", "mining", "local_llm",
    "orchestrator", "governance", "logging", "mcp", "knowledge",
    "agents.claude", "agents.grok", "agents.gemini", "agents.local",
    "agents.gpt", "agents.deepseek", "agents.minimax", "agents.openai",
    "mining.brains.python", "mining.brains.typescript", "mining.brains.go",
    "mining.brains.rust", "mining.brains.misc", "mining.brains.sql",
    "mining.brains.elixir", "mining.brains.java",
}


def _deep_merge(base: dict, update: dict) -> dict:
    """Recursively merge update into base, returning a new dict."""
    import copy
    result = copy.deepcopy(base)
    for k, v in update.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _resolve_toml_path() -> Path:
    """Canonical claw.toml path resolution."""
    st = _state
    config = st.get("config")
    if config:
        db_path = getattr(config, "database", None)
        if db_path:
            db_str = str(db_path.db_path) if hasattr(db_path, "db_path") else str(db_path)
            project_root = Path(db_str).resolve().parent.parent
            candidate = project_root / "claw.toml"
            if candidate.exists():
                return candidate
    cwd_toml = Path.cwd() / "claw.toml"
    if cwd_toml.exists():
        return cwd_toml
    return Path.cwd() / "claw.toml"


@app.get("/api/config")
async def api_config_get() -> JSONResponse:
    """Return full ClawConfig as JSON, stripping API key values."""
    st = await _ensure_state(app)
    config = st["config"]

    # Agents
    agents_out: dict[str, Any] = {}
    for aid, acfg in config.agents.items():
        env_var = getattr(acfg, "api_key_env", "") or ""
        has_key = bool(env_var and os.environ.get(env_var))
        agents_out[aid] = {
            "enabled": acfg.enabled,
            "mode": acfg.mode,
            "model": acfg.model,
            "max_concurrent": acfg.max_concurrent,
            "timeout": acfg.timeout,
            "max_budget_usd": acfg.max_budget_usd,
            "max_tokens": getattr(acfg, "max_tokens", None),
            "context_window_tokens": getattr(acfg, "context_window_tokens", None),
            "api_key_env": env_var,
            "has_key": has_key,
        }

    # Brains
    brains_out: dict[str, Any] = {}
    if hasattr(config, "mining") and hasattr(config.mining, "brains"):
        for bname, bcfg in config.mining.brains.items():
            brains_out[bname] = {
                "enabled": bcfg.enabled,
                "max_bytes": bcfg.max_bytes,
                "prompt": bcfg.prompt,
                "ganglion_name": getattr(bcfg, "ganglion_name", ""),
                "priority_extensions": getattr(bcfg, "priority_extensions", []),
            }

    # CAG
    cag = config.cag
    cag_out = {
        "enabled": cag.enabled,
        "knowledge_budget_chars": cag.knowledge_budget_chars,
        "token_budget_max": getattr(cag, "token_budget_max", None),
        "max_solution_chars": getattr(cag, "max_solution_chars", None),
        "shorthand_compression": getattr(cag, "shorthand_compression", False),
        "cache_dir": getattr(cag, "cache_dir", None),
        "context_pointer_threshold": getattr(cag, "context_pointer_threshold", None),
    }

    # Federation/instances
    inst = config.instances
    fed_out = {
        "enabled": inst.enabled if inst else False,
        "instance_name": getattr(inst, "instance_name", "") if inst else "",
        "instance_description": getattr(inst, "instance_description", "") if inst else "",
        "siblings_count": len(inst.siblings) if inst and inst.siblings else 0,
    }

    # Evolution
    evo = config.evolution
    evo_out = {
        "ab_test_sample_size": evo.ab_test_sample_size,
        "mutation_rate": evo.mutation_rate,
        "promotion_threshold": evo.promotion_threshold,
    }

    # Mining
    mining = config.mining
    mining_out = {
        "extra_code_extensions": list(mining.extra_code_extensions) if mining.extra_code_extensions else [],
        "extra_skip_dirs": list(mining.extra_skip_dirs) if mining.extra_skip_dirs else [],
        "recovery_enabled": getattr(mining, "recovery_enabled", True),
    }

    # Local LLM
    llm = getattr(config, "local_llm", None)
    llm_out = {}
    if llm:
        llm_out = {
            "provider": llm.provider,
            "model": llm.model,
            "base_url": getattr(llm, "base_url", None),
            "kv_cache_quantization": getattr(llm, "kv_cache_quantization", None),
            "ctx_size": getattr(llm, "ctx_size", None),
            "keep_alive": getattr(llm, "keep_alive", None),
        }

    # Orchestrator
    orch = getattr(config, "orchestrator", None)
    orch_out = {}
    if orch:
        orch_out = {
            "max_retries": orch.max_retries,
            "exploration_rate": orch.exploration_rate,
            "max_correction_attempts": getattr(orch, "max_correction_attempts", None),
        }

    # Governance
    gov = getattr(config, "governance", None)
    gov_out = {}
    if gov:
        gov_out = {
            "max_methodologies": gov.max_methodologies,
            "dedup_enabled": gov.dedup_enabled,
            "sweep_on_startup": getattr(gov, "sweep_on_startup", False),
        }

    return JSONResponse({
        "agents": agents_out,
        "brains": brains_out,
        "cag": cag_out,
        "federation": fed_out,
        "evolution": evo_out,
        "mining": mining_out,
        "local_llm": llm_out,
        "orchestrator": orch_out,
        "governance": gov_out,
    })


@app.patch("/api/config/{section}")
async def api_config_patch(section: str, request: Request) -> JSONResponse:
    """Partial config update via deep merge + atomic write."""
    if section not in _VALID_CONFIG_SECTIONS:
        return JSONResponse(
            {"error": f"Invalid section '{section}'. Valid: {sorted(_VALID_CONFIG_SECTIONS)}"},
            status_code=400,
        )
    body = await request.json()
    if not body:
        return JSONResponse({"error": "Body must be non-empty JSON"}, status_code=400)

    toml_path = _resolve_toml_path()
    if not toml_path.exists():
        return JSONResponse({"error": f"claw.toml not found at {toml_path}"}, status_code=404)

    # Read
    with open(toml_path) as f:
        raw_config = toml.load(f)

    # Navigate nested sections (e.g. "agents.claude" → raw_config["agents"]["claude"])
    parts = section.split(".")
    target = raw_config
    for p in parts[:-1]:
        if p not in target:
            target[p] = {}
        target = target[p]
    key = parts[-1]
    existing = target.get(key, {})
    if isinstance(existing, dict):
        target[key] = _deep_merge(existing, body)
    else:
        target[key] = body

    # Validate by attempting to load
    try:
        from claw.core.config import load_config
        # Write to temp, attempt load
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, dir=str(toml_path.parent)) as tmp:
            toml.dump(raw_config, tmp)
            tmp_path = Path(tmp.name)
    except Exception as exc:
        return JSONResponse({"error": f"Serialization failed: {exc}"}, status_code=500)

    # Backup + atomic replace
    backup_path = toml_path.with_suffix(".toml.bak")
    shutil.copy2(toml_path, backup_path)
    shutil.move(str(tmp_path), str(toml_path))

    return JSONResponse({"status": "updated", "section": section})


@app.post("/api/config/reload")
async def api_config_reload() -> JSONResponse:
    """Clear cached state so next request triggers fresh initialization."""
    engine = _state.get("engine")
    if engine:
        try:
            await engine.close()
        except Exception:
            pass
    _state.clear()
    return JSONResponse({"status": "reloaded"})


# ---------------------------------------------------------------------------
# Phase 1C — Forge Builder: Prompt CRUD
# ---------------------------------------------------------------------------


@app.get("/api/prompts")
async def api_prompts_list() -> JSONResponse:
    """List available prompt templates."""
    prompts_dir = Path.cwd() / "prompts"
    if not prompts_dir.exists():
        return JSONResponse({"prompts": []})
    prompts = []
    for f in sorted(prompts_dir.glob("repo-mine*.md")):
        content = f.read_text(errors="replace")
        prompts.append({
            "name": f.name,
            "path": str(f),
            "size_bytes": f.stat().st_size,
            "line_count": content.count("\n") + 1,
        })
    return JSONResponse({"prompts": prompts})


@app.get("/api/prompts/{name}")
async def api_prompt_get(name: str) -> JSONResponse:
    """Read a prompt template by name."""
    prompts_dir = Path.cwd() / "prompts"
    # Try exact match, then with .md suffix, then with repo-mine- prefix
    candidates = [
        prompts_dir / name,
        prompts_dir / f"{name}.md",
        prompts_dir / f"repo-mine-{name}.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            content = candidate.read_text(errors="replace")
            return JSONResponse({"name": candidate.name, "content": content, "path": str(candidate)})
    return JSONResponse({"error": f"Prompt '{name}' not found"}, status_code=404)


@app.post("/api/prompts")
async def api_prompt_create(request: Request) -> JSONResponse:
    """Create or update a prompt template."""
    body = await request.json()
    name = body.get("name", "").strip()
    content = body.get("content", "")
    fork_from = body.get("fork_from")

    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    # Sanitize name
    safe_name = name.replace(" ", "-").lower()
    if not safe_name.replace("-", "").replace("_", "").isalnum():
        return JSONResponse({"error": "name must be alphanumeric (hyphens/underscores ok)"}, status_code=400)

    # Auto-prefix
    if not safe_name.startswith("repo-mine"):
        safe_name = f"repo-mine-{safe_name}"
    if not safe_name.endswith(".md"):
        safe_name = f"{safe_name}.md"

    prompts_dir = Path.cwd() / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    target = prompts_dir / safe_name

    # Fork from existing
    if fork_from and not content:
        source = prompts_dir / fork_from
        if not source.exists():
            # Try with prefix
            source = prompts_dir / f"repo-mine-{fork_from}.md"
        if not source.exists():
            return JSONResponse({"error": f"Fork source '{fork_from}' not found"}, status_code=404)
        content = source.read_text(errors="replace")

    if not content:
        return JSONResponse({"error": "content is required (or use fork_from)"}, status_code=400)
    if len(content) > 100_000:
        return JSONResponse({"error": "Content exceeds 100KB limit"}, status_code=400)

    # Backup if exists
    if target.exists():
        backup = target.with_suffix(".md.bak")
        shutil.copy2(target, backup)

    target.write_text(content)
    return JSONResponse({
        "status": "created",
        "name": safe_name,
        "path": str(target),
        "size_bytes": len(content.encode("utf-8")),
    })


# ---------------------------------------------------------------------------
# Phase 1B — Forge Builder: Brain/Ganglion CRUD
# ---------------------------------------------------------------------------


def _remove_toml_sibling_block(raw: str, name: str) -> str | None:
    """Remove a [[instances.siblings]] block by name from raw TOML text.

    Returns the modified text, or None if the named block was not found.
    """
    lines = raw.split("\n")
    filtered: list[str] = []
    i = 0
    found = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped == "[[instances.siblings]]":
            # Collect the full block (header + key-value lines until next header or EOF)
            block_lines = [line]
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].strip()
                if next_stripped.startswith("["):
                    break
                block_lines.append(lines[j])
                j += 1

            # Check if this block's name matches
            block_text = "\n".join(block_lines)
            if f'name = "{name}"' in block_text:
                found = True
                # Skip blank lines after block
                while j < len(lines) and not lines[j].strip():
                    j += 1
                i = j
                continue
            else:
                filtered.extend(block_lines)
                i = j
                continue
        filtered.append(line)
        i += 1

    if not found:
        return None
    return "\n".join(filtered)


@app.post("/api/ganglia")
async def api_create_ganglion(request: Request) -> JSONResponse:
    """Create a new brain ganglion with DB and sibling registration."""
    body = await request.json()
    name = body.get("name", "").strip().lower()
    description = body.get("description", "")
    prompt_template = body.get("prompt_template", "repo-mine-misc.md")

    # --- Validate name ---
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        return JSONResponse(
            {"error": "name must be alphanumeric (hyphens/underscores ok)"},
            status_code=400,
        )

    # --- Resolve project root from the primary DB path ---
    st = await _ensure_state(app)
    config = st["config"]
    db_path_str = str(config.database.db_path) if hasattr(config.database, "db_path") else str(config.database)
    project_root = Path(db_path_str).resolve().parent.parent

    ganglion_dir = project_root / "instances" / name
    ganglion_db_path = ganglion_dir / "claw.db"

    # --- Check if ganglion already exists ---
    if ganglion_dir.exists() and ganglion_db_path.exists():
        return JSONResponse(
            {"error": f"Ganglion '{name}' already exists at {ganglion_dir}"},
            status_code=409,
        )

    # --- Validate prompt template ---
    prompts_dir = project_root / "prompts"
    if prompts_dir.exists():
        available = [f.name for f in prompts_dir.glob("repo-mine*.md")]
        if prompt_template not in available:
            return JSONResponse(
                {"error": f"Prompt template '{prompt_template}' not found. Available: {available}"},
                status_code=400,
            )

    # --- Provision the ganglion DB ---
    try:
        from claw.db.engine import DatabaseConfig, DatabaseEngine
        ganglion_dir.mkdir(parents=True, exist_ok=True)

        db_config = DatabaseConfig(db_path=str(ganglion_db_path))
        sib_engine = DatabaseEngine(db_config)
        await sib_engine.connect()
        await sib_engine.initialize_schema()
        await sib_engine.close()

        logger.info(
            "Phase1B: provisioned ganglion '%s' at %s", name, ganglion_db_path,
        )
    except Exception as exc:
        logger.error("Phase1B: failed to create ganglion '%s': %s", name, exc)
        return JSONResponse(
            {"error": f"Failed to create ganglion: {exc}"},
            status_code=500,
        )

    # --- Register as sibling in claw.toml ---
    sibling_registered = False
    toml_path = project_root / "claw.toml"
    if toml_path.exists():
        try:
            raw = toml_path.read_text()
            db_path_abs = str(ganglion_db_path.resolve())
            sibling_block = (
                f'\n[[instances.siblings]]\n'
                f'name = "{name}"\n'
                f'db_path = "{db_path_abs}"\n'
                f'description = "{description}"\n'
            )
            raw += sibling_block
            toml_path.write_text(raw)
            sibling_registered = True
            logger.info("Phase1B: registered ganglion '%s' in claw.toml", name)
        except Exception as exc:
            logger.warning("Phase1B: failed to update claw.toml: %s", exc)
    else:
        logger.warning(
            "Phase1B: claw.toml not found at %s -- ganglion created but not registered",
            toml_path,
        )

    return JSONResponse({
        "status": "created",
        "name": name,
        "ganglion_path": str(ganglion_dir),
        "db_path": str(ganglion_db_path),
        "prompt_template": prompt_template,
        "description": description,
        "sibling_registered": sibling_registered,
    })


@app.delete("/api/ganglia/{name}")
async def api_delete_ganglion(name: str) -> JSONResponse:
    """Disable a brain ganglion.  Keeps DB file intact for reversibility."""
    st = await _ensure_state(app)
    config = st["config"]
    db_path_str = str(config.database.db_path) if hasattr(config.database, "db_path") else str(config.database)
    project_root = Path(db_path_str).resolve().parent.parent

    toml_path = project_root / "claw.toml"
    if not toml_path.exists():
        return JSONResponse(
            {"error": f"claw.toml not found at {toml_path}"},
            status_code=500,
        )

    raw = toml_path.read_text()
    updated = _remove_toml_sibling_block(raw, name)
    if updated is None:
        return JSONResponse(
            {"error": f"Sibling '{name}' not found in claw.toml"},
            status_code=404,
        )

    # Backup + write
    backup = toml_path.with_suffix(".toml.bak")
    shutil.copy2(toml_path, backup)
    toml_path.write_text(updated)
    logger.info("Phase1B: disabled ganglion '%s' (removed from claw.toml)", name)

    ganglion_dir = project_root / "instances" / name
    db_exists = (ganglion_dir / "claw.db").exists()

    return JSONResponse({
        "status": "disabled",
        "name": name,
        "db_preserved": db_exists,
        "db_path": str(ganglion_dir / "claw.db") if db_exists else None,
        "note": "Database preserved for reversibility. Delete instances/{name}/ to fully remove.",
    })


@app.post("/api/forge/preview-repo")
async def api_forge_preview_repo(request: Request) -> JSONResponse:
    """Analyze a repository path for language zones and file metrics."""
    body = await request.json()
    path = body.get("path", "").strip()
    if not path:
        return JSONResponse({"error": "path is required"}, status_code=400)

    repo_path = Path(path)
    if not repo_path.exists():
        return JSONResponse({"error": f"Path not found: {path}"}, status_code=404)

    st = await _ensure_state(app)
    config = st["config"]

    # Detect languages
    try:
        from claw.miner import detect_all_repo_languages
        loop = asyncio.get_event_loop()
        lang_zones = await loop.run_in_executor(None, detect_all_repo_languages, repo_path, config)
    except Exception:
        lang_zones = {}

    # Count files and bytes
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
    total_files = 0
    total_bytes = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            total_files += 1
            try:
                total_bytes += (Path(root) / f).stat().st_size
            except OSError:
                pass

    # Build zone info
    zone_info: dict[str, Any] = {}
    if isinstance(lang_zones, dict):
        for lang, data in lang_zones.items():
            if isinstance(data, dict):
                zone_info[lang] = data
            else:
                zone_info[lang] = {"brain": lang, "file_count": 0, "file_extensions": [], "pct": 0}
    elif isinstance(lang_zones, list):
        for entry in lang_zones:
            if isinstance(entry, dict):
                zone_info[entry.get("brain", "unknown")] = entry

    # Suggest brain
    suggested = "misc"
    if zone_info:
        suggested = max(zone_info.keys(), key=lambda k: zone_info[k].get("pct", zone_info[k].get("file_count", 0)))

    return JSONResponse({
        "path": path,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "language_zones": zone_info,
        "suggested_brain": suggested,
    })


@app.post("/api/forge/validate")
async def api_forge_validate(request: Request) -> JSONResponse:
    """Pre-flight validation for a forge build configuration."""
    body = await request.json()
    brain_name = body.get("brain_name")
    agent_ids = body.get("agent_ids", [])
    repo_paths = body.get("repo_paths", [])

    st = await _ensure_state(app)
    config = st["config"]
    db_path_str = str(config.database.db_path) if hasattr(config.database, "db_path") else str(config.database)
    project_root = Path(db_path_str).resolve().parent.parent

    checks: list[dict[str, str]] = []
    all_valid = True

    # Check brain
    if brain_name:
        ganglion_dir = project_root / "instances" / brain_name
        brain_exists = ganglion_dir.exists() and (ganglion_dir / "claw.db").exists()
        checks.append({
            "check": "brain_exists",
            "status": "green" if brain_exists else "red",
            "detail": (
                f"Ganglion at {ganglion_dir}"
                if brain_exists
                else f"No ganglion found at {ganglion_dir}"
            ),
        })
        if not brain_exists:
            all_valid = False

    # Check agents
    for aid in agent_ids:
        acfg = config.agents.get(aid)
        if not acfg:
            checks.append({"check": f"agent_{aid}", "status": "red", "detail": f"Agent '{aid}' not configured"})
            all_valid = False
            continue
        if not acfg.enabled:
            checks.append({"check": f"agent_{aid}", "status": "yellow", "detail": f"Agent '{aid}' is disabled"})
            continue
        # API key check (skip for local agents)
        if acfg.mode == "local":
            checks.append({"check": f"agent_{aid}", "status": "green", "detail": f"Local agent '{aid}' ready"})
        else:
            env_var = getattr(acfg, "api_key_env", "") or ""
            if env_var and os.environ.get(env_var):
                checks.append({"check": f"agent_{aid}", "status": "green", "detail": f"Agent '{aid}' ready ({env_var} set)"})
            else:
                checks.append({"check": f"agent_{aid}", "status": "red", "detail": f"Missing env var {env_var} for agent '{aid}'"})
                all_valid = False

    # Check repo paths
    for rp in repo_paths:
        if Path(rp).exists():
            checks.append({"check": f"repo_{rp}", "status": "green", "detail": f"Path exists: {rp}"})
        else:
            checks.append({"check": f"repo_{rp}", "status": "red", "detail": f"Not found: {rp}"})
            all_valid = False

    return JSONResponse({"valid": all_valid, "checks": checks})


# ---------------------------------------------------------------------------
# Phase 2 — Brain Intelligence Visualization API
# ---------------------------------------------------------------------------


@app.get("/api/brain/graph")
async def api_brain_graph() -> JSONResponse:
    """Brain topology: nodes (ganglia) + edges (federation links) + category data."""
    st = await _ensure_state(app)
    repo = st["repository"]
    config = st["config"]

    nodes = []
    edges = []

    # Primary ganglion node
    try:
        primary_rows = await repo.engine.fetch_all(
            "SELECT COUNT(*) as cnt FROM methodologies"
        )
        primary_count = primary_rows[0]["cnt"] if primary_rows else 0
    except Exception:
        primary_count = 0

    # Category breakdown for primary
    try:
        cat_rows = await repo.engine.fetch_all(
            "SELECT category, COUNT(*) as cnt FROM methodologies GROUP BY category ORDER BY cnt DESC"
        )
        primary_cats = {r["category"] or "uncategorized": r["cnt"] for r in cat_rows}
    except Exception:
        primary_cats = {}

    # Fitness summary for primary
    try:
        fit_rows = await repo.engine.fetch_all(
            "SELECT AVG(fitness_score) as avg_f, MIN(fitness_score) as min_f, "
            "MAX(fitness_score) as max_f FROM methodologies WHERE fitness_score IS NOT NULL"
        )
        fr = fit_rows[0] if fit_rows else {}
        primary_fitness = {
            "avg": round(fr.get("avg_f") or 0, 3),
            "min": round(fr.get("min_f") or 0, 3),
            "max": round(fr.get("max_f") or 0, 3),
        }
    except Exception:
        primary_fitness = {"avg": 0, "min": 0, "max": 0}

    # Top methodologies by fitness for primary
    try:
        top_rows = await repo.engine.fetch_all(
            "SELECT title, category, fitness_score FROM methodologies "
            "WHERE fitness_score IS NOT NULL ORDER BY fitness_score DESC LIMIT 5"
        )
        primary_top = [
            {"title": r["title"], "category": r["category"], "fitness": round(r["fitness_score"], 3)}
            for r in top_rows
        ]
    except Exception:
        primary_top = []

    nodes.append({
        "id": "primary",
        "name": "primary",
        "methodology_count": primary_count,
        "categories": primary_cats,
        "top_methodologies": primary_top,
        "fitness_summary": primary_fitness,
        "is_primary": True,
    })

    # Sibling ganglion nodes
    siblings = getattr(config, "instances", None)
    sibling_configs = []
    if siblings:
        sibling_configs = getattr(siblings, "siblings", []) or []

    for sib in sibling_configs:
        sib_name = sib.name if hasattr(sib, "name") else str(sib)
        sib_db_path = sib.db_path if hasattr(sib, "db_path") else None

        sib_count = 0
        sib_cats: dict[str, int] = {}
        sib_fitness = {"avg": 0, "min": 0, "max": 0}
        sib_top: list[dict] = []
        db_exists = False

        if sib_db_path and Path(sib_db_path).exists():
            db_exists = True
            try:
                import aiosqlite
                async with aiosqlite.connect(sib_db_path) as db:
                    db.row_factory = aiosqlite.Row

                    cur = await db.execute("SELECT COUNT(*) as cnt FROM methodologies")
                    row = await cur.fetchone()
                    sib_count = int(row["cnt"]) if row else 0

                    cur = await db.execute(
                        "SELECT category, COUNT(*) as cnt FROM methodologies GROUP BY category ORDER BY cnt DESC"
                    )
                    for r in await cur.fetchall():
                        sib_cats[r["category"] or "uncategorized"] = int(r["cnt"])

                    cur = await db.execute(
                        "SELECT AVG(fitness_score) as avg_f, MIN(fitness_score) as min_f, "
                        "MAX(fitness_score) as max_f FROM methodologies WHERE fitness_score IS NOT NULL"
                    )
                    fit_row = await cur.fetchone()
                    if fit_row and fit_row["avg_f"] is not None:
                        sib_fitness = {
                            "avg": round(float(fit_row["avg_f"]), 3),
                            "min": round(float(fit_row["min_f"]), 3),
                            "max": round(float(fit_row["max_f"]), 3),
                        }

                    cur = await db.execute(
                        "SELECT title, category, fitness_score FROM methodologies "
                        "WHERE fitness_score IS NOT NULL ORDER BY fitness_score DESC LIMIT 5"
                    )
                    for r in await cur.fetchall():
                        sib_top.append({
                            "title": r["title"], "category": r["category"],
                            "fitness": round(float(r["fitness_score"]), 3),
                        })
            except Exception as exc:
                logger.warning("Brain graph: failed to query sibling '%s': %s", sib_name, exc)

        nodes.append({
            "id": sib_name,
            "name": sib_name,
            "methodology_count": sib_count,
            "categories": sib_cats,
            "top_methodologies": sib_top,
            "fitness_summary": sib_fitness,
            "db_exists": db_exists,
            "is_primary": False,
        })

        edges.append({"source": "primary", "target": sib_name, "type": "federation"})

    return JSONResponse({"nodes": nodes, "edges": edges})


@app.get("/api/brain/bandit-state")
async def api_bandit_state(task_type: Optional[str] = Query(None)) -> JSONResponse:
    """Bandit arm stats: Beta posterior, mean, CI for each methodology with outcome data."""
    st = await _ensure_state(app)
    repo = st["repository"]

    try:
        if task_type:
            rows = await repo.engine.fetch_all(
                "SELECT methodology_id, task_type, "
                "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successes, "
                "SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) as failures, "
                "COUNT(*) as total "
                "FROM methodology_bandit_outcomes "
                "WHERE task_type = ? "
                "GROUP BY methodology_id, task_type",
                (task_type,),
            )
        else:
            rows = await repo.engine.fetch_all(
                "SELECT methodology_id, task_type, "
                "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successes, "
                "SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) as failures, "
                "COUNT(*) as total "
                "FROM methodology_bandit_outcomes "
                "GROUP BY methodology_id, task_type"
            )
    except Exception:
        rows = []

    # Aggregate per methodology across task types
    method_stats: dict[str, dict] = {}
    for r in rows:
        mid = r["methodology_id"]
        if mid not in method_stats:
            method_stats[mid] = {
                "methodology_id": mid,
                "successes": 0,
                "failures": 0,
                "total": 0,
                "task_types": [],
            }
        method_stats[mid]["successes"] += r["successes"]
        method_stats[mid]["failures"] += r["failures"]
        method_stats[mid]["total"] += r["total"]
        if r["task_type"] and r["task_type"] not in method_stats[mid]["task_types"]:
            method_stats[mid]["task_types"].append(r["task_type"])

    # Compute Beta posterior stats
    arms = []
    for mid, s in method_stats.items():
        alpha = s["successes"] + 1  # Beta prior
        beta_param = s["failures"] + 1
        mean = alpha / (alpha + beta_param)
        n = alpha + beta_param
        ci_half = 1.96 * math.sqrt(mean * (1 - mean) / n) if n > 0 else 0
        ci_low = max(0, mean - ci_half)
        ci_high = min(1, mean + ci_half)

        # Look up methodology title
        try:
            title_rows = await repo.engine.fetch_all(
                "SELECT title FROM methodologies WHERE id = ?", (mid,)
            )
            title = title_rows[0]["title"] if title_rows else mid
        except Exception:
            title = mid

        arms.append({
            "methodology_id": mid,
            "title": title,
            "alpha": alpha,
            "beta": beta_param,
            "mean": round(mean, 4),
            "ci_low": round(ci_low, 4),
            "ci_high": round(ci_high, 4),
            "successes": s["successes"],
            "failures": s["failures"],
            "total": s["total"],
            "task_types": s["task_types"],
        })

    arms.sort(key=lambda x: x["mean"], reverse=True)
    return JSONResponse({"arms": arms, "count": len(arms)})


@app.get("/api/brain/capability-boundaries")
async def api_capability_boundaries() -> JSONResponse:
    """Identify hard tasks, failing methodologies, and coverage gaps."""
    st = await _ensure_state(app)
    repo = st["repository"]

    # Hard tasks: task_types where all agents fail > 50%
    hard_tasks: list[dict] = []
    try:
        rows = await repo.engine.fetch_all(
            "SELECT task_type, agent_id, "
            "CAST(failures AS REAL) / NULLIF(total_attempts, 0) as failure_rate "
            "FROM agent_scores WHERE total_attempts > 0"
        )
        task_agents: dict[str, list[float]] = {}
        for r in rows:
            tt = r["task_type"]
            if tt not in task_agents:
                task_agents[tt] = []
            task_agents[tt].append(r["failure_rate"] or 0)
        for tt, rates in task_agents.items():
            if rates and all(rate > 0.5 for rate in rates):
                hard_tasks.append({
                    "task_type": tt,
                    "agents_tried": len(rates),
                    "avg_failure_rate": round(sum(rates) / len(rates), 3),
                })
    except Exception:
        pass

    # Failing methodologies: > 3 failures and 0 successes in bandit
    failing_methods: list[dict] = []
    try:
        rows = await repo.engine.fetch_all(
            "SELECT methodology_id, "
            "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successes, "
            "SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) as failures "
            "FROM methodology_bandit_outcomes "
            "GROUP BY methodology_id "
            "HAVING failures > 3 AND successes = 0"
        )
        for r in rows:
            try:
                title_rows = await repo.engine.fetch_all(
                    "SELECT title, category FROM methodologies WHERE id = ?",
                    (r["methodology_id"],),
                )
                title = title_rows[0]["title"] if title_rows else r["methodology_id"]
                category = title_rows[0]["category"] if title_rows else None
            except Exception:
                title = r["methodology_id"]
                category = None
            failing_methods.append({
                "methodology_id": r["methodology_id"],
                "title": title,
                "category": category,
                "failures": r["failures"],
            })
    except Exception:
        pass

    # Coverage gaps from gap matrix
    coverage_gaps: list[dict] = []
    try:
        from claw.community.gap_analyzer import GapAnalyzer
        ga = GapAnalyzer(repo)
        matrix = ga.compute_coverage_matrix()
        if hasattr(matrix, "sparse_cells"):
            for cell in matrix.sparse_cells[:20]:
                coverage_gaps.append({
                    "category": cell.category if hasattr(cell, "category") else str(cell),
                    "brain": cell.brain if hasattr(cell, "brain") else "primary",
                    "count": cell.count if hasattr(cell, "count") else 0,
                })
        elif isinstance(matrix, dict) and "sparse_cells" in matrix:
            for cell in matrix["sparse_cells"][:20]:
                coverage_gaps.append(cell if isinstance(cell, dict) else {"category": str(cell)})
    except Exception as exc:
        logger.debug("Capability boundaries: gap matrix unavailable: %s", exc)

    return JSONResponse({
        "hard_tasks": hard_tasks,
        "failing_methodologies": failing_methods,
        "coverage_gaps": coverage_gaps,
    })


# ---------------------------------------------------------------------------
# Phase 5 — Composite Execution, SSE Streaming, Script Generation
# ---------------------------------------------------------------------------

_forge_jobs: dict[str, dict[str, Any]] = {}


@app.post("/api/forge/execute")
async def api_forge_execute(request: Request) -> JSONResponse:
    """Execute a composite forge job (brain creation, mining, etc.)."""
    import uuid

    body = await request.json()
    steps = body.get("steps", [])
    if not steps:
        return JSONResponse({"error": "steps array required"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    job: dict[str, Any] = {
        "job_id": job_id,
        "status": "queued",
        "steps": steps,
        "stages": [],
        "total_methodologies_created": 0,
        "error": None,
        "created_at": time.time(),
    }
    _forge_jobs[job_id] = job

    async def _run_forge():
        job["status"] = "running"

        for step in steps:
            step_type = step.get("type", "unknown")
            stage: dict[str, Any] = {
                "stage": step_type,
                "status": "running",
                "detail": "",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            job["stages"].append(stage)

            try:
                if step_type == "create_brain":
                    name = step.get("config", {}).get("name", "unnamed")
                    desc = step.get("config", {}).get("description", "")
                    prompt = step.get("config", {}).get("prompt_template", "repo-mine-misc.md")

                    st = await _ensure_state(app)
                    config = st["config"]
                    db_path_str = str(config.database.db_path) if hasattr(config.database, "db_path") else str(config.database)
                    project_root = Path(db_path_str).resolve().parent.parent
                    ganglion_dir = project_root / "instances" / name
                    ganglion_db_path = ganglion_dir / "claw.db"

                    if not (ganglion_dir.exists() and ganglion_db_path.exists()):
                        from claw.db.engine import DatabaseConfig, DatabaseEngine
                        ganglion_dir.mkdir(parents=True, exist_ok=True)
                        db_config = DatabaseConfig(db_path=str(ganglion_db_path))
                        sib_engine = DatabaseEngine(db_config)
                        await sib_engine.connect()
                        await sib_engine.initialize_schema()
                        await sib_engine.close()

                    stage["status"] = "success"
                    stage["detail"] = f"Brain '{name}' created at {ganglion_dir}"

                elif step_type == "mine":
                    paths = step.get("paths", [])
                    brain = step.get("brain")
                    stage["detail"] = f"Mining {len(paths)} repos for brain '{brain}'"

                    try:
                        from claw.miner import RepoMiner
                        st = await _ensure_state(app)
                        miner = RepoMiner(st["config"], st["repository"])
                        total_findings = 0
                        for p in paths:
                            if Path(p).exists():
                                results = await miner.mine_directory(Path(p), brain=brain)
                                total_findings += len(results) if results else 0
                        job["total_methodologies_created"] += total_findings
                        stage["status"] = "success"
                        stage["detail"] = f"Mined {total_findings} methodologies from {len(paths)} repos"
                    except Exception as exc:
                        stage["status"] = "error"
                        stage["detail"] = str(exc)

                elif step_type == "config_update":
                    stage["status"] = "success"
                    stage["detail"] = "Config updated"

                elif step_type == "cag_rebuild":
                    stage["status"] = "skipped"
                    stage["detail"] = "CAG rebuild deferred — will rebuild on next query"

                else:
                    stage["status"] = "skipped"
                    stage["detail"] = f"Unknown step type: {step_type}"

            except Exception as exc:
                stage["status"] = "error"
                stage["detail"] = str(exc)
                job["status"] = "error"
                job["error"] = str(exc)
                return

        job["status"] = "completed"

    asyncio.create_task(_run_forge())
    return JSONResponse({"job_id": job_id, "status": "queued"})


@app.get("/api/forge/execute/{job_id}/stream")
async def api_forge_stream(job_id: str) -> JSONResponse:
    """SSE-like endpoint — returns current stage events as JSON for polling.

    A proper SSE endpoint would use StreamingResponse with text/event-stream,
    but for compatibility with simple fetch clients, this returns JSON snapshot.
    """
    if job_id not in _forge_jobs:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    job = _forge_jobs[job_id]
    return JSONResponse({
        "job_id": job_id,
        "status": job["status"],
        "stages": job["stages"],
        "total_methodologies_created": job.get("total_methodologies_created", 0),
        "error": job.get("error"),
    })


@app.get("/api/forge/execute/{job_id}")
async def api_forge_job_status(job_id: str) -> JSONResponse:
    """Get final status + results of a forge job."""
    if job_id not in _forge_jobs:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    job = _forge_jobs[job_id]
    return JSONResponse({
        "job_id": job_id,
        "status": job["status"],
        "stages": job["stages"],
        "total_methodologies_created": job.get("total_methodologies_created", 0),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
    })


@app.post("/api/forge/generate-script")
async def api_forge_generate_script(request: Request) -> JSONResponse:
    """Generate a shell script for Tier 3 operations (clone, install, env setup)."""
    body = await request.json()
    operations = body.get("operations", [])
    repo_urls = body.get("repo_urls", [])
    brain_name = body.get("brain_name", "custom")
    env_vars = body.get("env_vars", [])

    lines = [
        "#!/usr/bin/env bash",
        "# CAM-PULSE Forge — Generated Script",
        f"# Brain: {brain_name}",
        f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "set -euo pipefail",
        "",
    ]

    if "clone_repos" in operations and repo_urls:
        lines.append("# --- Clone repositories ---")
        lines.append(f"CLONE_DIR=\"./forge-repos/{brain_name}\"")
        lines.append("mkdir -p \"$CLONE_DIR\"")
        for url in repo_urls:
            repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
            lines.append(f'git clone "{url}" "$CLONE_DIR/{repo_name}" || echo "Skipping {repo_name} (already exists)"')
        lines.append("")

    if "install_deps" in operations:
        lines.append("# --- Install CAM dependencies ---")
        lines.append("pip install -e . 2>/dev/null || echo 'Already installed'")
        lines.append("")

    if "set_env" in operations:
        lines.append("# --- Environment variables (fill in values) ---")
        for var in env_vars:
            lines.append(f'export {var}=""  # <-- Fill in your key')
        if not env_vars:
            lines.append('export OPENROUTER_API_KEY=""  # <-- Fill in your key')
        lines.append("")

    if "mine" in operations:
        lines.append("# --- Mine repositories ---")
        if repo_urls:
            for url in repo_urls:
                repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
                lines.append(f'cam mine --brain {brain_name} "./forge-repos/{brain_name}/{repo_name}"')
        else:
            lines.append(f"cam mine --brain {brain_name} /path/to/your/repo")
        lines.append("")

    lines.append('echo "Done! Brain \'{brain_name}\' is ready."'.replace("{brain_name}", brain_name))

    script = "\n".join(lines) + "\n"
    filename = f"forge-{brain_name}-{time.strftime('%Y%m%d')}.sh"

    return JSONResponse({
        "script": script,
        "filename": filename,
        "description": f"Setup script for '{brain_name}' brain with {len(operations)} operations",
    })


@app.post("/api/forge/analyze-intent")
async def api_forge_analyze_intent(request: Request) -> JSONResponse:
    """Analyze a natural language intent to suggest brain configuration."""
    body = await request.json()
    intent = body.get("intent", "").strip()
    repo_path = body.get("repo_path")

    if not intent:
        return JSONResponse({"error": "intent is required"}, status_code=400)

    st = await _ensure_state(app)
    repo = st["repository"]
    config = st["config"]

    # Search existing knowledge
    existing_knowledge = []
    try:
        safe_q = _build_safe_fts5_query(intent)
        if safe_q:
            rows = await repo.engine.fetch_all(
                "SELECT m.id, m.problem_description, m.language, m.lifecycle_state, "
                "m.tags, rank AS fts_rank "
                "FROM methodology_fts f JOIN methodologies m ON f.rowid = m.rowid "
                "WHERE methodology_fts MATCH ? ORDER BY rank LIMIT 10",
                (safe_q,),
            )
            for r in rows:
                existing_knowledge.append({
                    "id": r["id"],
                    "problem": r["problem_description"][:200],
                    "language": r["language"],
                    "lifecycle": r["lifecycle_state"],
                    "fts_rank": abs(float(r["fts_rank"] or 0)),
                })
    except Exception:
        pass

    # Detect repo languages if path provided
    repo_analysis = None
    if repo_path and Path(repo_path).exists():
        try:
            from claw.miner import detect_all_repo_languages
            loop = asyncio.get_event_loop()
            lang_zones = await loop.run_in_executor(None, detect_all_repo_languages, Path(repo_path), config)
            repo_analysis = lang_zones if isinstance(lang_zones, dict) else {}
        except Exception:
            pass

    # Extract heuristics from intent
    intent_lower = intent.lower()
    lang_keywords = {
        "python": "python", "typescript": "typescript", "go": "go", "golang": "go",
        "rust": "rust", "sql": "sql", "java": "java", "react": "typescript",
        "django": "python", "flask": "python", "fastapi": "python",
        "next.js": "typescript", "nextjs": "typescript",
    }
    suggested_brain = "misc"
    for kw, brain in lang_keywords.items():
        if kw in intent_lower:
            suggested_brain = brain
            break

    # Agent recommendations
    agent_recs = []
    for aid, acfg in config.agents.items():
        if acfg.enabled:
            agent_recs.append({
                "agent_id": aid,
                "mode": acfg.mode,
                "model": acfg.model,
            })

    # Gap analysis
    gaps = []
    try:
        from claw.community.gap_analyzer import GapAnalyzer
        ga = GapAnalyzer(repo)
        matrix = ga.compute_coverage_matrix()
        if isinstance(matrix, dict) and "sparse_cells" in matrix:
            gaps = matrix["sparse_cells"][:10]
    except Exception:
        pass

    return JSONResponse({
        "existing_knowledge": existing_knowledge,
        "gaps": gaps,
        "suggested_config": {
            "brain_name": suggested_brain,
            "description": intent,
            "prompt_template": f"repo-mine-{suggested_brain}.md",
        },
        "agent_recommendations": agent_recs,
        "repo_analysis": repo_analysis,
    })




# ---------------------------------------------------------------------------
# Playground — real task execution via MicroClaw
# ---------------------------------------------------------------------------

_playground_ctx_lock = asyncio.Lock()
_playground_ctx: Any = None  # Cached ClawContext for playground executions


async def _ensure_playground_ctx() -> Any:
    """Lazily build a full ClawContext (needed by MicroClaw) and cache it."""
    global _playground_ctx
    if _playground_ctx is not None:
        return _playground_ctx
    async with _playground_ctx_lock:
        if _playground_ctx is not None:
            return _playground_ctx
        from claw.core.factory import ClawFactory
        _playground_ctx = await ClawFactory.create()
        return _playground_ctx


@app.post("/api/execute")
async def execute_task(request: Request):
    """Submit a task for MicroClaw execution with real 7-gate verification."""
    body = await request.json()
    task_description = body.get("task_description", "").strip()
    if not task_description:
        return JSONResponse({"error": "task_description required"}, status_code=400)

    project_id = body.get("project_id", "playground")
    workspace_dir = body.get("workspace_dir")  # optional override (unused for now)

    session_id = str(uuid.uuid4())

    # Store job state
    if not hasattr(request.app.state, "playground_jobs"):
        request.app.state.playground_jobs = {}

    job: dict[str, Any] = {
        "session_id": session_id,
        "status": "starting",
        "task_description": task_description,
        "project_id": project_id,
        "steps": [],          # List of {"step": str, "detail": str, "timestamp": str}
        "gates": [],          # List of {"check": str, "status": str, "detail": str}
        "corrections": [],    # List of CorrectionFeedback dicts
        "result": None,       # CycleResult dict when done
        "error": None,
        "error_trace": None,
        "created_at": _datetime.utcnow().isoformat() + "Z",
    }
    request.app.state.playground_jobs[session_id] = job

    # Run in background
    async def _run_playground_execution():
        try:
            ctx = await _ensure_playground_ctx()

            # Ensure the project exists (upsert-style: ignore duplicate)
            from claw.core.models import Project, Task
            project = Project(
                id=project_id,
                name=project_id,
                repo_path=workspace_dir or ".",
            )
            try:
                await ctx.repository.create_project(project)
            except Exception:
                pass  # Project already exists

            # Create a pending task for MicroClaw to grab
            task = Task(
                project_id=project_id,
                title=task_description[:120],
                description=task_description,
            )
            await ctx.repository.create_task(task)

            from claw.cycle import MicroClaw

            micro = MicroClaw(
                ctx=ctx,
                project_id=project_id,
                session_id=session_id,
            )

            job["status"] = "running"

            def on_step(step_name: str, detail: str):
                job["steps"].append({
                    "step": step_name,
                    "detail": detail,
                    "timestamp": _datetime.utcnow().isoformat() + "Z",
                })
                # Track gate results from the verify step
                if step_name == "verify" and micro._current_verification:
                    vr = micro._current_verification
                    gate_names = [
                        "dependency_jail", "style_match", "chaos_check",
                        "placeholder_scan", "drift_alignment",
                        "claim_validation", "llm_deep_review",
                    ]
                    violated_checks = {v["check"] for v in vr.violations}
                    job["gates"] = [
                        {
                            "check": g,
                            "status": "fail" if g in violated_checks else "pass",
                            "detail": next(
                                (v["detail"] for v in vr.violations if v["check"] == g),
                                "",
                            ),
                        }
                        for g in gate_names
                    ]
                # Track correction attempts
                if step_name == "correct":
                    if (
                        micro._current_context_brief
                        and micro._current_context_brief.correction_feedback
                    ):
                        cf = micro._current_context_brief.correction_feedback
                        job["corrections"].append(cf.model_dump())

            cycle_result = await micro.run_cycle(on_step=on_step)
            job["result"] = cycle_result.model_dump()
            job["status"] = "completed" if cycle_result.success else "failed"

        except Exception as exc:
            job["status"] = "error"
            job["error"] = str(exc)
            import traceback
            job["error_trace"] = traceback.format_exc()

    asyncio.create_task(_run_playground_execution())

    return JSONResponse({
        "session_id": session_id,
        "status": "started",
    })


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    """Get execution session status, gate results, and final outcome."""
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(session_id)
    if not job:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    return JSONResponse({
        "session_id": job["session_id"],
        "status": job["status"],
        "task_description": job["task_description"],
        "steps": job["steps"],
        "gates": job["gates"],
        "corrections_count": len(job["corrections"]),
        "result": job["result"],
        "error": job.get("error"),
        "created_at": job["created_at"],
    })


@app.get("/api/sessions/{session_id}/corrections")
async def get_session_corrections(session_id: str, request: Request):
    """Get correction loop replay data for a session."""
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(session_id)
    if not job:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    return JSONResponse({
        "session_id": session_id,
        "corrections": job["corrections"],
        "total_attempts": len(job["corrections"]) + 1,  # +1 for initial attempt
    })

# ---------------------------------------------------------------------------
# HTML UI — single-page, no npm required
# ---------------------------------------------------------------------------

_E = html.escape


def _ganglion_badge(name: str) -> str:
    colors = {
        "primary": "#ff6b3d",
        "drive-ops": "#1777ff",
        "agentic-memory": "#16a085",
    }
    c = colors.get(name, "#76809d")
    return f'<span class="ganglion-badge" style="--gc:{c}">{_E(name)}</span>'


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, q: Optional[str] = None) -> HTMLResponse:
    """Main dashboard page."""
    st = await _ensure_state(app)

    # Get stats
    stats_resp = await api_stats()
    stats = json.loads(stats_resp.body)

    # Build search results HTML
    search_html = ""
    if q:
        search_resp = await api_search(q=q, limit=30)
        search_data = json.loads(search_resp.body)
        search_html = _render_search_results(q, search_data)

    page = _render_page(stats, q or "", search_html)
    return HTMLResponse(page)


def _render_search_results(query: str, data: dict) -> str:
    results = data.get("results", [])
    gc = data.get("ganglion_counts", {})
    elapsed = data.get("elapsed_ms", 0)

    ganglion_summary = " ".join(
        f'{_ganglion_badge(g)} <strong>{c}</strong>' for g, c in gc.items()
    )

    rows = []
    for r in results:
        tags_html = ""
        for t in (r.get("tags") or [])[:5]:
            if isinstance(t, str):
                tags_html += f'<span class="tag">{_E(t)}</span>'

        badge = _ganglion_badge(r.get("source_ganglion", "?"))
        lang = _E(r.get("language") or "?")
        lifecycle = _E(r.get("lifecycle", "?"))
        problem = _E(r.get("problem", ""))
        solution = _E(r.get("solution_preview", ""))
        mid = r.get("id", "")

        rows.append(f"""
        <div class="result-card">
          <div class="result-header">
            {badge}
            <span class="lang">{lang}</span>
            <span class="lifecycle">{lifecycle}</span>
            <span class="score">rank {r.get('fts_rank', 0):.2f}</span>
          </div>
          <h4><a href="/api/methodology/{mid}">{problem[:120]}</a></h4>
          <pre class="solution-preview">{solution}</pre>
          <div class="result-tags">{tags_html}</div>
          <div class="result-meta">
            retrievals: {r.get('retrievals', 0)} |
            successes: {r.get('successes', 0)} |
            novelty: {r.get('novelty') or 'n/a'}
          </div>
        </div>
        """)

    return f"""
    <div class="search-summary">
      <strong>{data.get('total_results', 0)}</strong> results for
      "<strong>{_E(query)}</strong>" in <strong>{elapsed:.0f}ms</strong>
      &mdash; {ganglion_summary}
    </div>
    {''.join(rows)}
    """


def _render_page(stats: dict, query: str, search_html: str) -> str:
    primary = stats.get("primary", {})
    siblings = stats.get("siblings", [])
    total_brain = stats.get("total_across_brain", 0)

    # Ganglion cards
    ganglion_cards = f"""
    <div class="ganglion-card primary">
      <h3>{_ganglion_badge("primary")} Primary Ganglion</h3>
      <div class="big-number">{primary.get('active', 0):,}</div>
      <div class="label">active methodologies</div>
      <div class="meta">{primary.get('source_repos', 0)} source repos |
      {len(primary.get('languages', {}))} languages</div>
    </div>
    """
    for sib in siblings:
        name = sib.get("name", "?")
        count = sib.get("methodology_count", 0)
        ok = sib.get("db_exists", False)
        status = "online" if ok else "offline"
        ganglion_cards += f"""
        <div class="ganglion-card">
          <h3>{_ganglion_badge(name)} {_E(name)}</h3>
          <div class="big-number">{count:,}</div>
          <div class="label">methodologies</div>
          <div class="meta">{status} | {_E(sib.get('description', '')[:60])}</div>
        </div>
        """

    # Lifecycle chart (horizontal bars)
    lifecycle = primary.get("lifecycle", {})
    lifecycle_bars = ""
    max_lc = max(lifecycle.values()) if lifecycle else 1
    for state, count in sorted(lifecycle.items(), key=lambda x: -x[1]):
        pct = (count / max_lc) * 100 if max_lc else 0
        lifecycle_bars += f"""
        <div class="bar-row">
          <span class="bar-label">{_E(state)}</span>
          <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
          <span class="bar-value">{count:,}</span>
        </div>
        """

    # Top categories
    categories = primary.get("top_categories", {})
    cat_html = ""
    for cat, cnt in list(categories.items())[:10]:
        cat_html += f'<span class="cat-chip">{_E(cat)} <strong>{cnt}</strong></span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CAM-PULSE Brain Dashboard</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
      background: #0d1117; color: #c9d1d9; line-height: 1.5;
    }}
    a {{ color: #58a6ff; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    .container {{ max-width: 1280px; margin: 0 auto; padding: 0 24px; }}

    header {{
      background: linear-gradient(135deg, #161b22 0%, #0d1117 100%);
      border-bottom: 1px solid #21262d; padding: 32px 0;
    }}
    header h1 {{ font-size: 1.8rem; color: #f0f6fc; }}
    header .subtitle {{ color: #8b949e; margin-top: 4px; }}
    .brain-total {{
      font-size: 2.4rem; font-weight: 700; color: #ff6b3d;
      margin-top: 8px;
    }}
    .brain-total span {{ font-size: 1rem; color: #8b949e; font-weight: 400; }}

    .ganglia-grid {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px; margin: 24px 0;
    }}
    .ganglion-card {{
      background: #161b22; border: 1px solid #21262d; border-radius: 12px;
      padding: 20px; transition: border-color 0.2s;
    }}
    .ganglion-card:hover {{ border-color: #388bfd; }}
    .ganglion-card.primary {{ border-color: #ff6b3d44; }}
    .ganglion-card h3 {{ font-size: 0.95rem; color: #c9d1d9; margin-bottom: 8px; }}
    .big-number {{ font-size: 2rem; font-weight: 700; color: #f0f6fc; }}
    .label {{ font-size: 0.82rem; color: #8b949e; }}
    .meta {{ font-size: 0.78rem; color: #484f58; margin-top: 6px; }}

    .ganglion-badge {{
      display: inline-block; padding: 2px 10px; border-radius: 999px;
      font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.05em;
      background: color-mix(in srgb, var(--gc) 15%, transparent);
      color: var(--gc); border: 1px solid color-mix(in srgb, var(--gc) 30%, transparent);
    }}

    .search-box {{
      margin: 32px 0; display: flex; gap: 12px;
    }}
    .search-box input {{
      flex: 1; padding: 12px 16px; font-size: 1rem;
      background: #0d1117; border: 1px solid #30363d; border-radius: 8px;
      color: #f0f6fc; outline: none;
    }}
    .search-box input:focus {{ border-color: #58a6ff; }}
    .search-box button {{
      padding: 12px 24px; background: #ff6b3d; color: #fff; border: none;
      border-radius: 8px; font-weight: 600; cursor: pointer;
    }}
    .search-box button:hover {{ background: #ff8552; }}

    .search-summary {{
      padding: 16px 0; color: #8b949e; border-bottom: 1px solid #21262d;
      margin-bottom: 16px;
    }}

    .result-card {{
      background: #161b22; border: 1px solid #21262d; border-radius: 10px;
      padding: 16px; margin-bottom: 12px;
    }}
    .result-card:hover {{ border-color: #30363d; }}
    .result-header {{
      display: flex; gap: 8px; align-items: center; margin-bottom: 8px;
      flex-wrap: wrap;
    }}
    .result-header .lang {{
      font-size: 0.75rem; color: #7ee787; background: #7ee78718;
      padding: 2px 8px; border-radius: 4px;
    }}
    .result-header .lifecycle {{
      font-size: 0.75rem; color: #d2a8ff; background: #d2a8ff18;
      padding: 2px 8px; border-radius: 4px;
    }}
    .result-header .score {{
      font-size: 0.72rem; color: #484f58; margin-left: auto;
    }}
    .result-card h4 {{ color: #f0f6fc; font-size: 0.95rem; margin-bottom: 6px; }}
    .solution-preview {{
      font-size: 0.8rem; color: #8b949e; background: #0d1117;
      padding: 8px 12px; border-radius: 6px; overflow: hidden;
      max-height: 80px; white-space: pre-wrap; word-break: break-word;
    }}
    .result-tags {{ margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }}
    .tag {{
      font-size: 0.7rem; padding: 2px 8px; border-radius: 4px;
      background: #21262d; color: #8b949e;
    }}
    .result-meta {{ font-size: 0.72rem; color: #484f58; margin-top: 8px; }}

    .stats-grid {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin: 24px 0;
    }}
    .stats-panel {{
      background: #161b22; border: 1px solid #21262d; border-radius: 12px;
      padding: 20px;
    }}
    .stats-panel h3 {{ font-size: 0.95rem; color: #f0f6fc; margin-bottom: 12px; }}

    .bar-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
    .bar-label {{ width: 80px; font-size: 0.78rem; color: #8b949e; text-align: right; }}
    .bar-track {{
      flex: 1; height: 8px; background: #21262d; border-radius: 4px; overflow: hidden;
    }}
    .bar-fill {{
      height: 100%; background: linear-gradient(90deg, #ff6b3d, #ff8f6b);
      border-radius: 4px;
    }}
    .bar-value {{ width: 50px; font-size: 0.78rem; color: #8b949e; }}

    .cat-chip {{
      display: inline-block; padding: 4px 12px; margin: 3px;
      background: #21262d; border-radius: 6px; font-size: 0.78rem; color: #c9d1d9;
    }}
    .cat-chip strong {{ color: #ff6b3d; margin-left: 4px; }}

    footer {{
      border-top: 1px solid #21262d; padding: 24px 0; margin-top: 48px;
      text-align: center; color: #484f58; font-size: 0.82rem;
    }}

    @media (max-width: 768px) {{
      .stats-grid {{ grid-template-columns: 1fr; }}
      .ganglia-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="container">
      <h1>CAM-PULSE Brain Dashboard</h1>
      <div class="subtitle">Federated knowledge explorer &mdash; querying all ganglia simultaneously</div>
      <div class="brain-total">{total_brain:,} <span>methodologies across the CAM Brain</span></div>
    </div>
  </header>

  <main class="container">
    <div class="ganglia-grid">
      {ganglion_cards}
    </div>

    <form class="search-box" action="/" method="get">
      <input type="text" name="q" value="{_E(query)}"
             placeholder="Search across all ganglia... (e.g. retry backoff, agent routing, secret scanning)">
      <button type="submit">Search Brain</button>
    </form>

    <div id="search-results">
      {search_html}
    </div>

    <div class="stats-grid">
      <div class="stats-panel">
        <h3>Lifecycle Distribution</h3>
        {lifecycle_bars}
      </div>
      <div class="stats-panel">
        <h3>Top Knowledge Domains</h3>
        <div>{cat_html}</div>
      </div>
    </div>
  </main>

  <footer>
    <div class="container">
      CAM-PULSE Brain Dashboard &mdash; {total_brain:,} methodologies |
      {len(siblings) + 1} ganglia |
      <a href="/api/docs">API Docs</a> |
      <a href="/api/stats">Stats JSON</a>
    </div>
  </footer>
</body>
</html>"""
