"""Tests for the CAM-PULSE Brain Dashboard web server."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip entire module if fastapi not available
fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset dashboard module state between tests."""
    from claw.web import dashboard_server

    dashboard_server._state.clear()
    yield
    dashboard_server._state.clear()


def _make_mock_engine():
    engine = AsyncMock()
    engine.connect = AsyncMock()
    engine.apply_migrations = AsyncMock()
    engine.initialize_schema = AsyncMock()
    engine.close = AsyncMock()

    async def _fetch_all(sql, params=None):
        sql_lower = sql.strip().lower()
        # Language distribution query (SELECT language, COUNT...)
        if "select language" in sql_lower and "group by" in sql_lower:
            return [
                {"language": "Python", "cnt": 2200},
                {"language": "TypeScript", "cnt": 400},
                {"language": "JavaScript", "cnt": 150},
            ]
        if "count(*)" in sql_lower and "methodology_fts" not in sql_lower:
            if "lifecycle_state" in sql_lower and "group by" in sql_lower:
                return [
                    {"lifecycle_state": "embryonic", "cnt": 1800},
                    {"lifecycle_state": "viable", "cnt": 900},
                    {"lifecycle_state": "thriving", "cnt": 150},
                    {"lifecycle_state": "declining", "cnt": 30},
                    {"lifecycle_state": "dormant", "cnt": 10},
                    {"lifecycle_state": "dead", "cnt": 5},
                ]
            if "json_each" in sql_lower:
                return [{"cnt": 250}]
            return [{"cnt": 2895}]
        if "select tags" in sql_lower and "methodology_fts" not in sql_lower:
            return [
                {"tags": json.dumps(["category:architecture", "source:repo1"])},
                {"tags": json.dumps(["category:ai_integration", "source:repo2"])},
                {"tags": json.dumps(["category:architecture", "category:security"])},
            ]
        if "methodology_fts" in sql_lower:
            return [
                {
                    "id": "m-001",
                    "problem_description": "Retry with exponential backoff",
                    "solution_code": "async def retry(fn, max_retries=3):",
                    "methodology_notes": "Use jitter to prevent thundering herd",
                    "tags": json.dumps(["category:error_handling", "source:MiroFish"]),
                    "language": "Python",
                    "lifecycle_state": "viable",
                    "novelty_score": 0.72,
                    "retrieval_count": 15,
                    "success_count": 12,
                    "failure_count": 1,
                    "fts_rank": -2.5,
                },
            ]
        return []

    engine.fetch_all = AsyncMock(side_effect=_fetch_all)

    async def _fetch_one(sql, params=None):
        if "count" in sql.lower():
            return {"cnt": 2895}
        return None

    engine.fetch_one = AsyncMock(side_effect=_fetch_one)
    return engine


def _make_mock_repo(engine):
    repo = AsyncMock()
    repo.engine = engine
    repo.count_methodologies = AsyncMock(return_value=2895)
    repo.count_active_methodologies = AsyncMock(return_value=2890)
    repo.count_methodologies_by_state = AsyncMock(
        return_value={
            "embryonic": 1800,
            "viable": 900,
            "thriving": 150,
            "declining": 30,
            "dormant": 10,
            "dead": 5,
        }
    )
    repo.get_methodology = AsyncMock(return_value=None)
    return repo


def _make_mock_config(with_siblings: bool = True):
    config = MagicMock()
    config.database = "data/claw.db"

    instances = MagicMock()
    instances.enabled = with_siblings
    instances.instance_name = "primary"
    instances.instance_description = "General purpose"

    if with_siblings:
        sib1 = MagicMock()
        sib1.name = "drive-ops"
        sib1.db_path = "/nonexistent/drive-ops.db"
        sib1.description = "Drive scanning and repo discovery"
        sib2 = MagicMock()
        sib2.name = "agentic-memory"
        sib2.db_path = "/nonexistent/agentic-memory.db"
        sib2.description = "Agent memory and RAG patterns"
        instances.siblings = [sib1, sib2]
    else:
        instances.siblings = []

    config.instances = instances
    return config


def _setup_client(with_siblings: bool = True) -> TestClient:
    """Create a TestClient with mocked state."""
    from claw.web.dashboard_server import app as dash_app, _state

    engine = _make_mock_engine()
    repo = _make_mock_repo(engine)
    config = _make_mock_config(with_siblings=with_siblings)

    _state["config"] = config
    _state["engine"] = engine
    _state["repository"] = repo
    _state["federation"] = None  # No real federation in tests
    _state["ready"] = True

    return TestClient(dash_app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStatsEndpoint:
    def test_stats_returns_primary_counts(self):
        client = _setup_client(with_siblings=False)
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["primary"]["total"] == 2895
        assert data["primary"]["active"] == 2890
        assert "lifecycle" in data["primary"]
        assert data["primary"]["lifecycle"]["embryonic"] == 1800

    def test_stats_returns_languages(self):
        client = _setup_client()
        resp = client.get("/api/stats")
        data = resp.json()
        assert "Python" in data["primary"]["languages"]

    def test_stats_returns_categories(self):
        client = _setup_client()
        resp = client.get("/api/stats")
        data = resp.json()
        assert "architecture" in data["primary"]["top_categories"]

    def test_stats_includes_sibling_info(self):
        client = _setup_client(with_siblings=True)
        resp = client.get("/api/stats")
        data = resp.json()
        assert len(data["siblings"]) == 2
        assert data["siblings"][0]["name"] == "drive-ops"
        assert data["siblings"][1]["name"] == "agentic-memory"

    def test_stats_total_across_brain(self):
        client = _setup_client(with_siblings=False)
        resp = client.get("/api/stats")
        data = resp.json()
        assert data["total_across_brain"] == 2895


class TestSearchEndpoint:
    def test_search_returns_results(self):
        client = _setup_client()
        resp = client.get("/api/search?q=retry+backoff")
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "retry backoff"
        assert data["total_results"] >= 1
        assert data["elapsed_ms"] >= 0

    def test_search_results_have_required_fields(self):
        client = _setup_client()
        resp = client.get("/api/search?q=retry")
        data = resp.json()
        r = data["results"][0]
        assert "id" in r
        assert "problem" in r
        assert "source_ganglion" in r
        assert r["source_ganglion"] == "primary"
        assert "language" in r
        assert "lifecycle" in r

    def test_search_ganglion_counts(self):
        client = _setup_client()
        resp = client.get("/api/search?q=retry")
        data = resp.json()
        assert "primary" in data["ganglion_counts"]

    def test_search_requires_query(self):
        client = _setup_client()
        resp = client.get("/api/search")
        assert resp.status_code == 422  # validation error

    def test_search_respects_limit(self):
        client = _setup_client()
        resp = client.get("/api/search?q=retry&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 5


class TestMethodologyDetail:
    def test_methodology_not_found(self):
        client = _setup_client()
        resp = client.get("/api/methodology/nonexistent-id")
        assert resp.status_code == 404

    def test_methodology_found(self):
        from claw.core.models import Methodology
        from claw.web.dashboard_server import _state

        client = _setup_client()
        m = Methodology(
            id="test-123",
            problem_description="Test methodology",
            solution_code="def solve(): pass",
            language="Python",
            lifecycle_state="viable",
            tags=["category:testing"],
        )
        _state["repository"].get_methodology = AsyncMock(return_value=m)

        resp = client.get("/api/methodology/test-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "test-123"
        assert data["problem_description"] == "Test methodology"
        assert data["language"] == "Python"


class TestHTMLDashboard:
    def test_index_returns_html(self):
        client = _setup_client()
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "CAM-PULSE Brain Dashboard" in resp.text

    def test_index_shows_methodology_count(self):
        client = _setup_client()
        resp = client.get("/")
        assert "2,890" in resp.text  # active count

    def test_index_shows_ganglion_names(self):
        client = _setup_client(with_siblings=True)
        resp = client.get("/")
        assert "drive-ops" in resp.text
        assert "agentic-memory" in resp.text
        assert "primary" in resp.text

    def test_search_via_html(self):
        client = _setup_client()
        resp = client.get("/?q=retry")
        assert resp.status_code == 200
        assert "retry" in resp.text.lower()
        # Should contain search results section
        assert "search-results" in resp.text

    def test_index_has_search_form(self):
        client = _setup_client()
        resp = client.get("/")
        assert '<form class="search-box"' in resp.text
        assert 'name="q"' in resp.text

    def test_index_shows_lifecycle_bars(self):
        client = _setup_client()
        resp = client.get("/")
        assert "embryonic" in resp.text
        assert "viable" in resp.text

    def test_index_shows_categories(self):
        client = _setup_client()
        resp = client.get("/")
        assert "architecture" in resp.text

    def test_footer_shows_ganglion_count(self):
        client = _setup_client(with_siblings=True)
        resp = client.get("/")
        assert "3 ganglia" in resp.text


class TestEdgeCases:
    def test_empty_search_query_rejected(self):
        client = _setup_client()
        resp = client.get("/api/search?q=")
        assert resp.status_code == 422

    def test_large_limit_capped(self):
        client = _setup_client()
        resp = client.get("/api/search?q=test&limit=200")
        assert resp.status_code == 422  # limit > 100

    def test_no_siblings_configured(self):
        client = _setup_client(with_siblings=False)
        resp = client.get("/api/stats")
        data = resp.json()
        assert data["siblings"] == []
        assert data["total_across_brain"] == 2895
