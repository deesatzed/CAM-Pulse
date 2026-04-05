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
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Query, Request
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
