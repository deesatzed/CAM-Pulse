"""Tests for the CAM-PULSE Brain Dashboard web server."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
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


def _make_real_config():
    """Build a real ClawConfig with concrete Pydantic sub-models.

    Used by config-endpoint tests that access deeply-nested attributes.
    """
    from claw.core.config import (
        AgentConfig,
        BrainConfig,
        CAGConfig,
        ClawConfig,
        EvolutionConfig,
        GovernanceConfig,
        InstanceRegistryConfig,
        LocalLLMConfig,
        MiningConfig,
        OrchestratorConfig,
    )

    agents = {
        "claude": AgentConfig(
            enabled=True,
            mode="openrouter",
            api_key_env="OPENROUTER_API_KEY",
            model="openai/gpt-5.4-mini",
            max_concurrent=2,
            timeout=600,
            max_budget_usd=5.0,
            context_window_tokens=128000,
        ),
        "local": AgentConfig(
            enabled=True,
            mode="local",
            model="qwen3.5:9b",
            max_concurrent=1,
            timeout=300,
            max_budget_usd=0.0,
            max_tokens=16384,
            context_window_tokens=32768,
        ),
    }

    brains = {
        "python": BrainConfig(
            enabled=True,
            max_bytes=921_600,
            prompt="repo-mine.md",
            ganglion_name="",
        ),
        "typescript": BrainConfig(
            enabled=True,
            max_bytes=1_536_000,
            prompt="repo-mine-typescript.md",
            priority_extensions=[".ts", ".tsx", ".js", ".jsx"],
            ganglion_name="typescript",
        ),
    }

    config = ClawConfig(
        agents=agents,
        mining=MiningConfig(
            brains=brains,
            extra_code_extensions=[".cpp", ".rb"],
            extra_skip_dirs=["vendor"],
        ),
        cag=CAGConfig(
            enabled=True,
            knowledge_budget_chars=16000,
            token_budget_max=100000,
            max_solution_chars=2000,
            shorthand_compression=False,
            cache_dir="data/cag_caches",
            context_pointer_threshold=2000,
        ),
        instances=InstanceRegistryConfig(
            enabled=True,
            instance_name="general",
            instance_description="General-purpose AI development patterns",
            siblings=[],
        ),
        evolution=EvolutionConfig(
            ab_test_sample_size=20,
            mutation_rate=0.1,
            promotion_threshold=0.6,
        ),
        local_llm=LocalLLMConfig(
            provider="ollama",
            model="qwen3.5:9b",
            base_url="http://localhost:11434/v1",
            kv_cache_quantization="q8_0",
            ctx_size=32768,
            keep_alive=-1,
        ),
        orchestrator=OrchestratorConfig(
            max_retries=5,
            exploration_rate=0.10,
            max_correction_attempts=3,
        ),
        governance=GovernanceConfig(
            max_methodologies=5000,
            dedup_enabled=True,
            sweep_on_startup=True,
        ),
    )
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


def _setup_client_real_config() -> TestClient:
    """Create a TestClient with a real ClawConfig for config-endpoint tests."""
    from claw.web.dashboard_server import app as dash_app, _state

    engine = _make_mock_engine()
    repo = _make_mock_repo(engine)
    config = _make_real_config()

    _state["config"] = config
    _state["engine"] = engine
    _state["repository"] = repo
    _state["federation"] = None
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

    def test_stats_includes_health_score(self):
        """Stats response includes health_score and health_breakdown."""
        client = _setup_client(with_siblings=False)
        resp = client.get("/api/stats")
        data = resp.json()
        assert "health_score" in data
        assert isinstance(data["health_score"], int)
        assert "health_breakdown" in data
        assert isinstance(data["health_breakdown"], dict)


class TestContradictionEndpoint:
    def test_contradiction_api_returns_list(self):
        """GET /api/governance/contradictions returns JSON list."""
        client = _setup_client(with_siblings=False)
        resp = client.get("/api/governance/contradictions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestMethodologyGraphEndpoint:
    def test_methodology_graph_returns_structure(self):
        """GET /api/methodology/{id}/graph returns nodes and edges."""
        client = _setup_client(with_siblings=False)
        resp = client.get("/api/methodology/nonexistent-id/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)


class TestWellKnownEndpoint:
    def test_well_known_mcp_json(self):
        """GET /.well-known/mcp.json returns valid JSON with expected keys."""
        client = _setup_client(with_siblings=False)
        resp = client.get("/.well-known/mcp.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "cam-pulse"
        assert data["version"] == "1.0"
        assert "tools" in data
        assert isinstance(data["tools"], list)
        assert "brains" in data
        assert isinstance(data["brains"], list)
        assert "total_methodologies" in data
        assert "transport" in data

    def test_well_known_no_secrets(self):
        """Discovery endpoint does not expose secrets or absolute paths."""
        client = _setup_client(with_siblings=False)
        resp = client.get("/.well-known/mcp.json")
        text = resp.text
        assert "sk-" not in text
        assert "Bearer" not in text
        # No absolute paths to user directories
        assert "/Users/" not in text
        assert "/home/" not in text


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


# ---------------------------------------------------------------------------
# Phase 1A — Forge Builder: Config Read/Write API tests
# ---------------------------------------------------------------------------


class TestConfigGetEndpoint:
    """Tests for GET /api/config."""

    def test_config_returns_200(self):
        client = _setup_client_real_config()
        resp = client.get("/api/config")
        assert resp.status_code == 200

    def test_config_returns_agents(self):
        client = _setup_client_real_config()
        data = client.get("/api/config").json()
        assert "agents" in data
        assert "claude" in data["agents"]
        assert "local" in data["agents"]

    def test_config_agent_fields(self):
        client = _setup_client_real_config()
        data = client.get("/api/config").json()
        claude = data["agents"]["claude"]
        assert claude["enabled"] is True
        assert claude["mode"] == "openrouter"
        assert claude["model"] == "openai/gpt-5.4-mini"
        assert claude["max_budget_usd"] == 5.0
        assert claude["max_concurrent"] == 2
        assert claude["timeout"] == 600
        assert claude["context_window_tokens"] == 128000
        assert claude["api_key_env"] == "OPENROUTER_API_KEY"
        # has_key depends on whether env var is set
        assert isinstance(claude["has_key"], bool)

    def test_config_strips_api_key_values(self):
        """API key VALUES must never be returned -- only env var name + has_key."""
        client = _setup_client_real_config()
        resp_text = client.get("/api/config").text
        # Should never contain actual key values
        for env_var in ["OPENROUTER_API_KEY", "GOOGLE_API_KEY"]:
            real_value = os.environ.get(env_var, "")
            if real_value:
                assert real_value not in resp_text

    def test_config_returns_brains(self):
        client = _setup_client_real_config()
        data = client.get("/api/config").json()
        assert "brains" in data
        assert "python" in data["brains"]
        assert "typescript" in data["brains"]
        ts = data["brains"]["typescript"]
        assert ts["ganglion_name"] == "typescript"
        assert ".ts" in ts["priority_extensions"]

    def test_config_returns_cag(self):
        client = _setup_client_real_config()
        data = client.get("/api/config").json()
        cag = data["cag"]
        assert cag["enabled"] is True
        assert cag["knowledge_budget_chars"] == 16000
        assert cag["token_budget_max"] == 100000
        assert cag["max_solution_chars"] == 2000
        assert cag["shorthand_compression"] is False

    def test_config_returns_federation(self):
        client = _setup_client_real_config()
        data = client.get("/api/config").json()
        fed = data["federation"]
        assert fed["enabled"] is True
        assert fed["instance_name"] == "general"
        assert isinstance(fed["siblings_count"], int)

    def test_config_returns_evolution(self):
        client = _setup_client_real_config()
        data = client.get("/api/config").json()
        evo = data["evolution"]
        assert evo["ab_test_sample_size"] == 20
        assert evo["mutation_rate"] == 0.1
        assert evo["promotion_threshold"] == 0.6

    def test_config_returns_mining(self):
        client = _setup_client_real_config()
        data = client.get("/api/config").json()
        mining = data["mining"]
        assert ".cpp" in mining["extra_code_extensions"]
        assert "vendor" in mining["extra_skip_dirs"]
        assert mining["recovery_enabled"] is True

    def test_config_returns_local_llm(self):
        client = _setup_client_real_config()
        data = client.get("/api/config").json()
        llm = data["local_llm"]
        assert llm["provider"] == "ollama"
        assert llm["model"] == "qwen3.5:9b"
        assert llm["kv_cache_quantization"] == "q8_0"

    def test_config_returns_orchestrator(self):
        client = _setup_client_real_config()
        data = client.get("/api/config").json()
        orch = data["orchestrator"]
        assert orch["max_retries"] == 5
        assert orch["exploration_rate"] == 0.10

    def test_config_returns_governance(self):
        client = _setup_client_real_config()
        data = client.get("/api/config").json()
        gov = data["governance"]
        assert gov["max_methodologies"] == 5000
        assert gov["dedup_enabled"] is True

    def test_config_has_key_reflects_env(self):
        """has_key should be True if the env var is set, False otherwise."""
        client = _setup_client_real_config()
        data = client.get("/api/config").json()
        local = data["agents"]["local"]
        # local agent has api_key_env="" so has_key should be False
        assert local["has_key"] is False


class TestConfigPatchEndpoint:
    """Tests for PATCH /api/config/{section}."""

    def _write_test_toml(self, tmp_dir: Path) -> Path:
        """Write a minimal valid claw.toml for patching tests."""
        import toml
        content = {
            "database": {"db_path": "data/claw.db"},
            "cag": {
                "enabled": True,
                "knowledge_budget_chars": 16000,
                "token_budget_max": 100000,
                "max_solution_chars": 2000,
            },
            "evolution": {
                "ab_test_sample_size": 20,
                "mutation_rate": 0.1,
                "promotion_threshold": 0.6,
            },
            "instances": {
                "enabled": True,
                "instance_name": "general",
                "instance_description": "test",
            },
            "mining": {
                "extra_code_extensions": [".cpp"],
                "extra_skip_dirs": ["vendor"],
            },
            "local_llm": {
                "provider": "ollama",
                "model": "qwen3.5:9b",
            },
        }
        toml_path = tmp_dir / "claw.toml"
        with open(toml_path, "w") as f:
            toml.dump(content, f)
        return toml_path

    def test_patch_invalid_section_returns_400(self):
        client = _setup_client_real_config()
        resp = client.patch(
            "/api/config/nonexistent_section",
            json={"enabled": True},
        )
        assert resp.status_code == 400
        assert "Invalid section" in resp.json()["error"]

    def test_patch_empty_body_returns_400(self):
        client = _setup_client_real_config()
        resp = client.patch("/api/config/cag", json={})
        assert resp.status_code == 400
        assert "non-empty" in resp.json()["error"]

    def test_patch_cag_section_succeeds(self, tmp_path):
        """PATCH /api/config/cag should update the cag section and create backup."""
        import toml as toml_lib
        from claw.web.dashboard_server import _resolve_toml_path

        toml_path = self._write_test_toml(tmp_path)

        client = _setup_client_real_config()
        with patch(
            "claw.web.dashboard_server._resolve_toml_path",
            return_value=toml_path,
        ):
            resp = client.patch(
                "/api/config/cag",
                json={"knowledge_budget_chars": 24000},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "updated"
        assert data["section"] == "cag"

        # Verify the file was actually updated
        with open(toml_path) as f:
            updated = toml_lib.load(f)
        assert updated["cag"]["knowledge_budget_chars"] == 24000
        # Other fields should be preserved
        assert updated["cag"]["enabled"] is True
        assert updated["cag"]["token_budget_max"] == 100000

        # Verify backup was created
        backup = toml_path.with_suffix(".toml.bak")
        assert backup.exists()

    def test_patch_evolution_section(self, tmp_path):
        """PATCH evolution section with deep merge."""
        import toml as toml_lib

        toml_path = self._write_test_toml(tmp_path)
        client = _setup_client_real_config()
        with patch(
            "claw.web.dashboard_server._resolve_toml_path",
            return_value=toml_path,
        ):
            resp = client.patch(
                "/api/config/evolution",
                json={"ab_test_sample_size": 50, "mutation_rate": 0.2},
            )
        assert resp.status_code == 200

        with open(toml_path) as f:
            updated = toml_lib.load(f)
        assert updated["evolution"]["ab_test_sample_size"] == 50
        assert updated["evolution"]["mutation_rate"] == 0.2
        # Unchanged field preserved
        assert updated["evolution"]["promotion_threshold"] == 0.6

    def test_patch_creates_section_if_missing(self, tmp_path):
        """If the section doesn't exist in the TOML yet, it should be created."""
        import toml as toml_lib

        toml_path = self._write_test_toml(tmp_path)
        client = _setup_client_real_config()
        with patch(
            "claw.web.dashboard_server._resolve_toml_path",
            return_value=toml_path,
        ):
            resp = client.patch(
                "/api/config/logging",
                json={"level": "DEBUG"},
            )
        assert resp.status_code == 200

        with open(toml_path) as f:
            updated = toml_lib.load(f)
        assert updated["logging"]["level"] == "DEBUG"

    def test_patch_toml_not_found_returns_404(self):
        client = _setup_client_real_config()
        with patch(
            "claw.web.dashboard_server._resolve_toml_path",
            return_value=Path("/nonexistent/claw.toml"),
        ):
            resp = client.patch(
                "/api/config/cag",
                json={"enabled": False},
            )
        assert resp.status_code == 404

    def test_patch_preserves_other_sections(self, tmp_path):
        """Patching one section must not affect other sections."""
        import toml as toml_lib

        toml_path = self._write_test_toml(tmp_path)
        client = _setup_client_real_config()
        with patch(
            "claw.web.dashboard_server._resolve_toml_path",
            return_value=toml_path,
        ):
            resp = client.patch(
                "/api/config/cag",
                json={"enabled": False},
            )
        assert resp.status_code == 200

        with open(toml_path) as f:
            updated = toml_lib.load(f)
        # cag was updated
        assert updated["cag"]["enabled"] is False
        # database section untouched
        assert updated["database"]["db_path"] == "data/claw.db"
        # evolution section untouched
        assert updated["evolution"]["ab_test_sample_size"] == 20


class TestConfigReloadEndpoint:
    """Tests for POST /api/config/reload."""

    def test_reload_clears_state(self):
        from claw.web.dashboard_server import _state

        client = _setup_client_real_config()
        # State should be populated
        assert _state.get("ready") is True

        resp = client.post("/api/config/reload")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "reloaded"

        # State should be cleared
        assert _state.get("ready") is None
        assert "config" not in _state

    def test_reload_closes_engine(self):
        from claw.web.dashboard_server import _state

        client = _setup_client_real_config()
        engine = _state["engine"]

        resp = client.post("/api/config/reload")
        assert resp.status_code == 200

        # Engine close should have been called
        engine.close.assert_called_once()

    def test_reload_is_idempotent(self):
        """Calling reload twice should not raise errors."""
        client = _setup_client_real_config()
        resp1 = client.post("/api/config/reload")
        assert resp1.status_code == 200
        resp2 = client.post("/api/config/reload")
        assert resp2.status_code == 200


class TestDeepMerge:
    """Unit tests for the _deep_merge helper used in PATCH."""

    def test_simple_merge(self):
        from claw.web.dashboard_server import _deep_merge
        base = {"a": 1, "b": 2}
        update = {"b": 3, "c": 4}
        result = _deep_merge(base, update)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        from claw.web.dashboard_server import _deep_merge
        base = {"outer": {"a": 1, "b": 2}, "top": True}
        update = {"outer": {"b": 99, "c": 3}}
        result = _deep_merge(base, update)
        assert result == {"outer": {"a": 1, "b": 99, "c": 3}, "top": True}

    def test_does_not_mutate_base(self):
        from claw.web.dashboard_server import _deep_merge
        base = {"a": {"x": 1}}
        update = {"a": {"y": 2}}
        result = _deep_merge(base, update)
        # Original base should not be modified
        assert "y" not in base["a"]
        assert result["a"] == {"x": 1, "y": 2}

    def test_overwrite_non_dict_with_dict(self):
        from claw.web.dashboard_server import _deep_merge
        base = {"a": "string_value"}
        update = {"a": {"nested": True}}
        result = _deep_merge(base, update)
        assert result["a"] == {"nested": True}


# ---------------------------------------------------------------------------
# A/B Test Detail Endpoint tests
# ---------------------------------------------------------------------------


def _setup_ab_detail_client(variant_rows, ab_sample_rows=None, ab_individual_rows=None):
    """Create a TestClient with engine wired for ab-test detail queries.

    Parameters
    ----------
    variant_rows : list[dict]
        Rows returned for the prompt_variants query.
    ab_sample_rows : list[dict] or None
        Rows returned for the ab_quality_samples aggregate query.
    ab_individual_rows : list[dict] or None
        Rows returned for the per-sample composite_score query (for p-value).
    """
    from claw.web.dashboard_server import app as dash_app, _state

    engine = AsyncMock()
    engine.connect = AsyncMock()
    engine.apply_migrations = AsyncMock()
    engine.initialize_schema = AsyncMock()
    engine.close = AsyncMock()

    call_count = {"n": 0}

    async def _fetch_all(sql, params=None):
        sql_lower = sql.strip().lower()
        # prompt_variants query
        if "from prompt_variants" in sql_lower and "where prompt_name" in sql_lower:
            return variant_rows
        # ab_quality_samples aggregate query
        if "from ab_quality_samples" in sql_lower and "group by" in sql_lower:
            if ab_sample_rows is not None:
                return ab_sample_rows
            raise Exception("no such table: ab_quality_samples")
        # ab_quality_samples per-sample query (for Mann-Whitney)
        if "from ab_quality_samples" in sql_lower and "group by" not in sql_lower:
            if ab_individual_rows is not None:
                return ab_individual_rows
            raise Exception("no such table: ab_quality_samples")
        return []

    engine.fetch_all = AsyncMock(side_effect=_fetch_all)
    engine.fetch_one = AsyncMock(return_value=None)

    repo = AsyncMock()
    repo.engine = engine
    repo.count_methodologies = AsyncMock(return_value=0)
    repo.count_active_methodologies = AsyncMock(return_value=0)
    repo.count_methodologies_by_state = AsyncMock(return_value={})
    repo.get_methodology = AsyncMock(return_value=None)

    config = _make_mock_config(with_siblings=False)

    _state["config"] = config
    _state["engine"] = engine
    _state["repository"] = repo
    _state["federation"] = None
    _state["ready"] = True

    return TestClient(dash_app)


class TestABTestDetailEndpoint:
    """Tests for GET /api/evolution/ab-test/{name}."""

    def test_returns_404_for_unknown_test(self):
        client = _setup_ab_detail_client(variant_rows=[])
        resp = client.get("/api/evolution/ab-test/nonexistent")
        assert resp.status_code == 404
        assert "not found" in resp.json()["error"]

    def test_returns_single_variant(self):
        """A test with only a control variant should return it without comparison."""
        rows = [
            {
                "id": "v-001",
                "prompt_name": "deepdive",
                "variant_label": "control",
                "content": "You are an expert...",
                "agent_id": None,
                "is_active": 1,
                "sample_count": 10,
                "success_count": 7,
                "avg_quality_score": 0.65,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-07T12:00:00Z",
            },
        ]
        client = _setup_ab_detail_client(variant_rows=rows)
        resp = client.get("/api/evolution/ab-test/deepdive")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "deepdive"
        assert "control" in data["variants"]
        assert data["variants"]["control"]["sample_count"] == 10
        assert data["variants"]["control"]["success_rate"] == 0.7
        assert data["comparison"] is None
        assert data["winner"] is None

    def test_returns_both_variants_with_comparison(self):
        """When both control and variant exist, comparison metrics are computed."""
        rows = [
            {
                "id": "v-001",
                "prompt_name": "deepdive",
                "variant_label": "control",
                "content": "Control prompt",
                "agent_id": None,
                "is_active": 1,
                "sample_count": 30,
                "success_count": 20,
                "avg_quality_score": 0.60,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-07T12:00:00Z",
            },
            {
                "id": "v-002",
                "prompt_name": "deepdive",
                "variant_label": "variant",
                "content": "Variant prompt with emphasis",
                "agent_id": None,
                "is_active": 0,
                "sample_count": 30,
                "success_count": 28,
                "avg_quality_score": 0.85,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-07T12:00:00Z",
            },
        ]
        client = _setup_ab_detail_client(variant_rows=rows)
        resp = client.get("/api/evolution/ab-test/deepdive")
        assert resp.status_code == 200
        data = resp.json()

        assert data["name"] == "deepdive"
        assert "control" in data["variants"]
        assert "variant" in data["variants"]

        # Comparison should be populated
        comp = data["comparison"]
        assert comp is not None
        assert "control_bayesian_score" in comp
        assert "variant_bayesian_score" in comp
        assert "margin" in comp
        assert comp["margin"] > 0  # variant is better
        assert comp["quality_delta"] == 0.25  # 0.85 - 0.60
        assert comp["success_rate_delta"] > 0

    def test_winner_declared_when_margin_exceeds_threshold(self):
        """Winner is declared when margin > 0.15 and both arms have >= 20 samples."""
        rows = [
            {
                "id": "v-001",
                "prompt_name": "deepdive",
                "variant_label": "control",
                "content": "Control",
                "agent_id": None,
                "is_active": 1,
                "sample_count": 25,
                "success_count": 10,
                "avg_quality_score": 0.40,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-07T12:00:00Z",
            },
            {
                "id": "v-002",
                "prompt_name": "deepdive",
                "variant_label": "variant",
                "content": "Variant",
                "agent_id": None,
                "is_active": 0,
                "sample_count": 25,
                "success_count": 23,
                "avg_quality_score": 0.90,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-07T12:00:00Z",
            },
        ]
        client = _setup_ab_detail_client(variant_rows=rows)
        resp = client.get("/api/evolution/ab-test/deepdive")
        data = resp.json()
        assert data["winner"] == "variant"

    def test_no_winner_when_insufficient_samples(self):
        """No winner when sample_count < 20 even if margin is large."""
        rows = [
            {
                "id": "v-001",
                "prompt_name": "test",
                "variant_label": "control",
                "content": "Control",
                "agent_id": None,
                "is_active": 1,
                "sample_count": 5,
                "success_count": 1,
                "avg_quality_score": 0.20,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-07T12:00:00Z",
            },
            {
                "id": "v-002",
                "prompt_name": "test",
                "variant_label": "variant",
                "content": "Variant",
                "agent_id": None,
                "is_active": 0,
                "sample_count": 5,
                "success_count": 5,
                "avg_quality_score": 1.0,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-07T12:00:00Z",
            },
        ]
        client = _setup_ab_detail_client(variant_rows=rows)
        resp = client.get("/api/evolution/ab-test/test")
        data = resp.json()
        assert data["winner"] is None
        # Comparison should still be populated
        assert data["comparison"] is not None
        assert data["comparison"]["margin"] > 0

    def test_control_wins_when_variant_is_worse(self):
        """Control is declared winner when it is better by > 0.15 margin."""
        rows = [
            {
                "id": "v-001",
                "prompt_name": "test",
                "variant_label": "control",
                "content": "Strong control",
                "agent_id": None,
                "is_active": 1,
                "sample_count": 30,
                "success_count": 28,
                "avg_quality_score": 0.92,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-07T12:00:00Z",
            },
            {
                "id": "v-002",
                "prompt_name": "test",
                "variant_label": "variant",
                "content": "Weak variant",
                "agent_id": None,
                "is_active": 0,
                "sample_count": 30,
                "success_count": 10,
                "avg_quality_score": 0.35,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-07T12:00:00Z",
            },
        ]
        client = _setup_ab_detail_client(variant_rows=rows)
        resp = client.get("/api/evolution/ab-test/test")
        data = resp.json()
        assert data["winner"] == "control"
        assert data["comparison"]["margin"] < 0

    def test_ab_quality_stats_included_when_available(self):
        """ab_quality_stats field is present when ab_quality_samples has data."""
        variant_rows = [
            {
                "id": "v-001",
                "prompt_name": "deepdive",
                "variant_label": "control",
                "content": "Control",
                "agent_id": None,
                "is_active": 1,
                "sample_count": 13,
                "success_count": 10,
                "avg_quality_score": 0.60,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-07T12:00:00Z",
            },
        ]
        ab_rows = [
            {
                "variant_label": "control",
                "n": 13,
                "avg_composite": 0.62,
                "avg_d1": 0.80,
                "avg_d2": 0.50,
                "avg_d3": 0.70,
                "avg_d4": 0.55,
                "avg_d5": 0.45,
                "avg_d6": 0.60,
                "avg_corrections": 1.3,
                "total_success": 10,
            },
        ]
        client = _setup_ab_detail_client(
            variant_rows=variant_rows, ab_sample_rows=ab_rows
        )
        resp = client.get("/api/evolution/ab-test/deepdive")
        assert resp.status_code == 200
        data = resp.json()
        assert "ab_quality_stats" in data
        ctrl_stats = data["ab_quality_stats"]["control"]
        assert ctrl_stats["n"] == 13
        assert ctrl_stats["avg_composite"] == 0.62
        assert ctrl_stats["dimensions"]["d_functional_correctness"] == 0.80
        assert ctrl_stats["avg_corrections"] == 1.3

    def test_ab_quality_stats_omitted_when_table_missing(self):
        """If ab_quality_samples table does not exist, response omits that key."""
        variant_rows = [
            {
                "id": "v-001",
                "prompt_name": "deepdive",
                "variant_label": "control",
                "content": "Control",
                "agent_id": None,
                "is_active": 1,
                "sample_count": 5,
                "success_count": 3,
                "avg_quality_score": 0.50,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-07T12:00:00Z",
            },
        ]
        # ab_sample_rows=None triggers the Exception path in the helper
        client = _setup_ab_detail_client(
            variant_rows=variant_rows, ab_sample_rows=None
        )
        resp = client.get("/api/evolution/ab-test/deepdive")
        assert resp.status_code == 200
        data = resp.json()
        assert "ab_quality_stats" not in data

    def test_variant_includes_prompt_content(self):
        """Each variant in the response includes the full prompt content."""
        rows = [
            {
                "id": "v-001",
                "prompt_name": "deepdive",
                "variant_label": "control",
                "content": "You are an expert code reviewer...",
                "agent_id": "claude",
                "is_active": 1,
                "sample_count": 15,
                "success_count": 12,
                "avg_quality_score": 0.75,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-07T12:00:00Z",
            },
        ]
        client = _setup_ab_detail_client(variant_rows=rows)
        resp = client.get("/api/evolution/ab-test/deepdive")
        data = resp.json()
        ctrl = data["variants"]["control"]
        assert ctrl["content"] == "You are an expert code reviewer..."
        assert ctrl["agent_id"] == "claude"
        assert ctrl["is_active"] is True

    def test_zero_samples_gives_zero_success_rate(self):
        """Variant with zero samples should have success_rate = 0."""
        rows = [
            {
                "id": "v-001",
                "prompt_name": "new_test",
                "variant_label": "control",
                "content": "Blank",
                "agent_id": None,
                "is_active": 1,
                "sample_count": 0,
                "success_count": 0,
                "avg_quality_score": 0.0,
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-04-01T00:00:00Z",
            },
        ]
        client = _setup_ab_detail_client(variant_rows=rows)
        resp = client.get("/api/evolution/ab-test/new_test")
        data = resp.json()
        assert data["variants"]["control"]["success_rate"] == 0.0
        assert data["variants"]["control"]["sample_count"] == 0
