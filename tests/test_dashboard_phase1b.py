"""Tests for Phase 1B Brain/Ganglion CRUD endpoints in the dashboard server."""

from __future__ import annotations

import json
import os
import textwrap
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
        if "select language" in sql_lower and "group by" in sql_lower:
            return [{"language": "Python", "cnt": 100}]
        if "count(*)" in sql_lower:
            if "lifecycle_state" in sql_lower and "group by" in sql_lower:
                return [{"lifecycle_state": "viable", "cnt": 100}]
            if "json_each" in sql_lower:
                return [{"cnt": 5}]
            return [{"cnt": 100}]
        if "select tags" in sql_lower:
            return [{"tags": json.dumps(["category:testing"])}]
        return []

    engine.fetch_all = AsyncMock(side_effect=_fetch_all)

    async def _fetch_one(sql, params=None):
        if "count" in sql.lower():
            return {"cnt": 100}
        return None

    engine.fetch_one = AsyncMock(side_effect=_fetch_one)
    return engine


def _make_mock_repo(engine):
    repo = AsyncMock()
    repo.engine = engine
    repo.count_methodologies = AsyncMock(return_value=100)
    repo.count_active_methodologies = AsyncMock(return_value=95)
    repo.count_methodologies_by_state = AsyncMock(return_value={"viable": 100})
    return repo


def _make_real_config(db_path: str = "data/claw.db", siblings=None):
    """Build a real ClawConfig with concrete Pydantic sub-models."""
    from claw.core.config import (
        AgentConfig,
        ClawConfig,
        DatabaseConfig,
        InstanceConfig,
        InstanceRegistryConfig,
    )

    sib_list = siblings or []

    config = ClawConfig(
        database=DatabaseConfig(db_path=db_path),
        agents={
            "claude": AgentConfig(
                enabled=True,
                mode="openrouter",
                api_key_env="OPENROUTER_API_KEY",
                model="test-model",
                max_budget_usd=5.0,
            ),
            "local": AgentConfig(
                enabled=True,
                mode="local",
                model="qwen3.5:9b",
            ),
            "disabled_agent": AgentConfig(
                enabled=False,
                mode="openrouter",
                api_key_env="SOME_KEY",
                model="other-model",
            ),
        },
        instances=InstanceRegistryConfig(
            enabled=True,
            instance_name="primary",
            siblings=sib_list,
        ),
    )
    return config


def _setup_client(tmp_path: Path, siblings=None) -> TestClient:
    """Create a TestClient with state pointed at tmp_path."""
    from claw.web.dashboard_server import app as dash_app, _state

    # Create data/ dir so db_path resolves correctly
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    db_path = str(data_dir / "claw.db")

    engine = _make_mock_engine()
    repo = _make_mock_repo(engine)
    config = _make_real_config(db_path=db_path, siblings=siblings)

    _state["config"] = config
    _state["engine"] = engine
    _state["repository"] = repo
    _state["federation"] = None
    _state["ready"] = True

    return TestClient(dash_app)


# ---------------------------------------------------------------------------
# Tests: _remove_toml_sibling_block
# ---------------------------------------------------------------------------


class TestRemoveTomlSiblingBlock:
    def test_removes_matching_block(self):
        from claw.web.dashboard_server import _remove_toml_sibling_block

        raw = textwrap.dedent("""\
            [instances]
            enabled = true

            [[instances.siblings]]
            name = "typescript"
            db_path = "/path/to/typescript/claw.db"
            description = "TS brain"

            [[instances.siblings]]
            name = "go"
            db_path = "/path/to/go/claw.db"
            description = "Go brain"
        """)
        result = _remove_toml_sibling_block(raw, "typescript")
        assert result is not None
        assert 'name = "typescript"' not in result
        assert 'name = "go"' in result
        assert "[instances]" in result

    def test_returns_none_when_not_found(self):
        from claw.web.dashboard_server import _remove_toml_sibling_block

        raw = textwrap.dedent("""\
            [instances]
            enabled = true

            [[instances.siblings]]
            name = "go"
            db_path = "/path/to/go/claw.db"
        """)
        result = _remove_toml_sibling_block(raw, "rust")
        assert result is None

    def test_preserves_other_siblings(self):
        from claw.web.dashboard_server import _remove_toml_sibling_block

        raw = textwrap.dedent("""\
            [[instances.siblings]]
            name = "alpha"
            db_path = "/a.db"

            [[instances.siblings]]
            name = "beta"
            db_path = "/b.db"

            [[instances.siblings]]
            name = "gamma"
            db_path = "/c.db"
        """)
        result = _remove_toml_sibling_block(raw, "beta")
        assert result is not None
        assert 'name = "alpha"' in result
        assert 'name = "beta"' not in result
        assert 'name = "gamma"' in result


# ---------------------------------------------------------------------------
# Tests: POST /api/ganglia
# ---------------------------------------------------------------------------


class TestCreateGanglion:
    def test_create_ganglion_success(self, tmp_path):
        client = _setup_client(tmp_path)

        # Create prompts dir with a prompt template
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "repo-mine-misc.md").write_text("# Misc prompt")

        # Create claw.toml
        toml_path = tmp_path / "claw.toml"
        toml_path.write_text("[instances]\nenabled = true\n")

        resp = client.post("/api/ganglia", json={
            "name": "elixir",
            "description": "Elixir language patterns",
            "prompt_template": "repo-mine-misc.md",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["name"] == "elixir"
        assert "elixir" in data["ganglion_path"]
        assert data["sibling_registered"] is True

        # Verify claw.toml was updated
        toml_content = toml_path.read_text()
        assert 'name = "elixir"' in toml_content

    def test_create_ganglion_invalid_name(self, tmp_path):
        client = _setup_client(tmp_path)

        resp = client.post("/api/ganglia", json={"name": ""})
        assert resp.status_code == 400
        assert "alphanumeric" in resp.json()["error"]

    def test_create_ganglion_invalid_name_special_chars(self, tmp_path):
        client = _setup_client(tmp_path)

        resp = client.post("/api/ganglia", json={"name": "my brain!!"})
        assert resp.status_code == 400

    def test_create_ganglion_already_exists(self, tmp_path):
        client = _setup_client(tmp_path)

        # Pre-create the ganglion directory with a DB file
        ganglion_dir = tmp_path / "instances" / "existing"
        ganglion_dir.mkdir(parents=True)
        (ganglion_dir / "claw.db").touch()

        resp = client.post("/api/ganglia", json={"name": "existing"})
        assert resp.status_code == 409
        assert "already exists" in resp.json()["error"]

    def test_create_ganglion_bad_prompt_template(self, tmp_path):
        client = _setup_client(tmp_path)

        # Create prompts dir without the requested template
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "repo-mine-misc.md").write_text("# Misc")

        resp = client.post("/api/ganglia", json={
            "name": "swift",
            "prompt_template": "repo-mine-nonexistent.md",
        })
        assert resp.status_code == 400
        assert "not found" in resp.json()["error"]

    def test_create_ganglion_allows_hyphens_and_underscores(self, tmp_path):
        client = _setup_client(tmp_path)

        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "repo-mine-misc.md").write_text("# Misc")
        (tmp_path / "claw.toml").write_text("[instances]\nenabled = true\n")

        resp = client.post("/api/ganglia", json={"name": "my-brain_v2"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "my-brain_v2"


# ---------------------------------------------------------------------------
# Tests: DELETE /api/ganglia/{name}
# ---------------------------------------------------------------------------


class TestDeleteGanglion:
    def test_delete_ganglion_success(self, tmp_path):
        from claw.core.config import InstanceConfig

        sib = InstanceConfig(
            name="typescript",
            db_path=str(tmp_path / "instances" / "typescript" / "claw.db"),
            description="TS patterns",
        )
        client = _setup_client(tmp_path, siblings=[sib])

        # Create claw.toml with the sibling
        toml_path = tmp_path / "claw.toml"
        toml_path.write_text(textwrap.dedent("""\
            [instances]
            enabled = true

            [[instances.siblings]]
            name = "typescript"
            db_path = "{db_path}"
            description = "TS patterns"
        """.format(db_path=sib.db_path)))

        # Create the ganglion dir + DB so db_preserved reports correctly
        ganglion_dir = tmp_path / "instances" / "typescript"
        ganglion_dir.mkdir(parents=True)
        (ganglion_dir / "claw.db").touch()

        resp = client.delete("/api/ganglia/typescript")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "disabled"
        assert data["name"] == "typescript"
        assert data["db_preserved"] is True

        # Verify claw.toml no longer has the sibling
        toml_content = toml_path.read_text()
        assert 'name = "typescript"' not in toml_content
        # Backup should exist
        assert toml_path.with_suffix(".toml.bak").exists()

    def test_delete_ganglion_not_found(self, tmp_path):
        client = _setup_client(tmp_path)

        toml_path = tmp_path / "claw.toml"
        toml_path.write_text("[instances]\nenabled = true\n")

        resp = client.delete("/api/ganglia/nonexistent")
        assert resp.status_code == 404
        assert "not found" in resp.json()["error"]

    def test_delete_ganglion_no_toml(self, tmp_path):
        client = _setup_client(tmp_path)
        # No claw.toml at all
        resp = client.delete("/api/ganglia/whatever")
        assert resp.status_code == 500
        assert "claw.toml" in resp.json()["error"]


# ---------------------------------------------------------------------------
# Tests: POST /api/forge/preview-repo
# ---------------------------------------------------------------------------


class TestPreviewRepo:
    def test_preview_repo_success(self, tmp_path):
        client = _setup_client(tmp_path)

        # Create a fake repo with some Python files
        repo_dir = tmp_path / "fake_repo"
        repo_dir.mkdir()
        (repo_dir / "main.py").write_text("print('hello')")
        (repo_dir / "utils.py").write_text("def helper(): pass")
        (repo_dir / "README.md").write_text("# Readme")

        resp = client.post("/api/forge/preview-repo", json={
            "path": str(repo_dir),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == str(repo_dir)
        assert data["total_files"] >= 2
        assert data["total_bytes"] > 0
        assert isinstance(data["language_zones"], dict)
        assert isinstance(data["suggested_brain"], str)

    def test_preview_repo_missing_path(self, tmp_path):
        client = _setup_client(tmp_path)

        resp = client.post("/api/forge/preview-repo", json={"path": ""})
        assert resp.status_code == 400
        assert "required" in resp.json()["error"]

    def test_preview_repo_nonexistent_dir(self, tmp_path):
        client = _setup_client(tmp_path)

        resp = client.post("/api/forge/preview-repo", json={
            "path": "/nonexistent/repo/path",
        })
        assert resp.status_code == 404
        assert "not found" in resp.json()["error"].lower()

    def test_preview_repo_detects_python(self, tmp_path):
        client = _setup_client(tmp_path)

        repo_dir = tmp_path / "python_repo"
        repo_dir.mkdir()
        for i in range(5):
            (repo_dir / f"mod{i}.py").write_text(f"# module {i}")
        (repo_dir / "pyproject.toml").write_text("[project]\nname='test'")

        resp = client.post("/api/forge/preview-repo", json={
            "path": str(repo_dir),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["suggested_brain"] == "python"

    def test_preview_repo_detects_typescript(self, tmp_path):
        client = _setup_client(tmp_path)

        repo_dir = tmp_path / "ts_repo"
        repo_dir.mkdir()
        for i in range(5):
            (repo_dir / f"comp{i}.ts").write_text(f"// component {i}")
        (repo_dir / "tsconfig.json").write_text("{}")

        resp = client.post("/api/forge/preview-repo", json={
            "path": str(repo_dir),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["suggested_brain"] == "typescript"


# ---------------------------------------------------------------------------
# Tests: POST /api/forge/validate
# ---------------------------------------------------------------------------


class TestForgeValidate:
    def test_validate_all_green(self, tmp_path):
        client = _setup_client(tmp_path)

        # Create brain directory
        brain_dir = tmp_path / "instances" / "typescript"
        brain_dir.mkdir(parents=True)
        (brain_dir / "claw.db").touch()

        # Create a repo directory
        repo_dir = tmp_path / "my_repo"
        repo_dir.mkdir()

        # Set env var for agent
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test-key"}):
            resp = client.post("/api/forge/validate", json={
                "brain_name": "typescript",
                "agent_ids": ["claude", "local"],
                "repo_paths": [str(repo_dir)],
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert all(c["status"] == "green" for c in data["checks"])

    def test_validate_missing_brain(self, tmp_path):
        client = _setup_client(tmp_path)

        resp = client.post("/api/forge/validate", json={
            "brain_name": "nonexistent",
            "agent_ids": [],
            "repo_paths": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        brain_check = [c for c in data["checks"] if c["check"] == "brain_exists"][0]
        assert brain_check["status"] == "red"

    def test_validate_disabled_agent(self, tmp_path):
        client = _setup_client(tmp_path)

        resp = client.post("/api/forge/validate", json={
            "brain_name": None,
            "agent_ids": ["disabled_agent"],
            "repo_paths": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        agent_check = [c for c in data["checks"] if "disabled_agent" in c["check"]][0]
        assert agent_check["status"] == "yellow"

    def test_validate_unknown_agent(self, tmp_path):
        client = _setup_client(tmp_path)

        resp = client.post("/api/forge/validate", json={
            "agent_ids": ["mystery_agent"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        check = data["checks"][0]
        assert check["status"] == "red"
        assert "not configured" in check["detail"]

    def test_validate_missing_api_key(self, tmp_path):
        client = _setup_client(tmp_path)

        # Ensure OPENROUTER_API_KEY is not set
        with patch.dict(os.environ, {}, clear=True):
            resp = client.post("/api/forge/validate", json={
                "agent_ids": ["claude"],
            })
        assert resp.status_code == 200
        data = resp.json()
        claude_check = [c for c in data["checks"] if "claude" in c["check"]][0]
        assert claude_check["status"] == "red"
        assert "Missing env var" in claude_check["detail"]

    def test_validate_local_agent_no_key_needed(self, tmp_path):
        client = _setup_client(tmp_path)

        resp = client.post("/api/forge/validate", json={
            "agent_ids": ["local"],
        })
        assert resp.status_code == 200
        data = resp.json()
        local_check = [c for c in data["checks"] if "local" in c["check"]][0]
        assert local_check["status"] == "green"

    def test_validate_nonexistent_repo_path(self, tmp_path):
        client = _setup_client(tmp_path)

        resp = client.post("/api/forge/validate", json={
            "repo_paths": ["/nonexistent/path/repo"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        path_check = data["checks"][0]
        assert path_check["status"] == "red"
        assert "Not found" in path_check["detail"]

    def test_validate_empty_request(self, tmp_path):
        client = _setup_client(tmp_path)

        resp = client.post("/api/forge/validate", json={})
        assert resp.status_code == 200
        data = resp.json()
        # No checks means all green (vacuously true)
        assert data["valid"] is True
        assert data["checks"] == []
