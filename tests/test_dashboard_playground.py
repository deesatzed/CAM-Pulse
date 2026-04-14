"""Tests for the Playground execution endpoints in the dashboard server.

Covers:
  POST /api/execute          — submit a task for MicroClaw execution
  GET  /api/sessions/{id}    — retrieve session status + gate results
  GET  /api/sessions/{id}/corrections — correction loop replay data
"""

from __future__ import annotations

import uuid
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
    # Also reset the cached playground context so tests are isolated
    dashboard_server._playground_ctx = None
    yield
    dashboard_server._state.clear()
    dashboard_server._playground_ctx = None


def _make_mock_engine():
    engine = AsyncMock()
    engine.connect = AsyncMock()
    engine.apply_migrations = AsyncMock()
    engine.initialize_schema = AsyncMock()
    engine.close = AsyncMock()

    async def _fetch_all(sql, params=None):
        return []

    engine.fetch_all = AsyncMock(side_effect=_fetch_all)

    async def _fetch_one(sql, params=None):
        if "count" in sql.lower():
            return {"cnt": 0}
        return None

    engine.fetch_one = AsyncMock(side_effect=_fetch_one)
    return engine


def _make_mock_repo(engine):
    repo = AsyncMock()
    repo.engine = engine
    return repo


def _setup_client() -> TestClient:
    """Create a TestClient with minimal mocked state for playground tests."""
    from claw.web.dashboard_server import app as dash_app, _state

    engine = _make_mock_engine()
    repo = _make_mock_repo(engine)

    _state["config"] = MagicMock()
    _state["engine"] = engine
    _state["repository"] = repo
    _state["federation"] = None
    _state["ready"] = True

    return TestClient(dash_app)


def _inject_job(client: TestClient, session_id: str, overrides: dict | None = None):
    """Inject a playground job directly into app.state.playground_jobs."""
    if not hasattr(client.app.state, "playground_jobs"):
        client.app.state.playground_jobs = {}

    job = {
        "session_id": session_id,
        "status": "completed",
        "task_description": "injected test task",
        "project_id": "playground",
        "steps": [
            {
                "step": "plan",
                "detail": "Planning complete",
                "timestamp": "2026-04-08T00:00:00Z",
            }
        ],
        "gates": [
            {"check": "dependency_jail", "status": "pass", "detail": ""},
            {"check": "style_match", "status": "pass", "detail": ""},
            {"check": "chaos_check", "status": "fail", "detail": "Flaky test detected"},
        ],
        "corrections": [],
        "result": {"success": True, "summary": "All gates passed"},
        "error": None,
        "error_trace": None,
        "created_at": "2026-04-08T00:00:00Z",
    }
    if overrides:
        job.update(overrides)
    client.app.state.playground_jobs[session_id] = job
    return job


# ---------------------------------------------------------------------------
# Tests: POST /api/execute
# ---------------------------------------------------------------------------


class TestExecuteEndpoint:
    def test_execute_missing_description(self):
        """POST with empty body returns 400 with error message."""
        client = _setup_client()
        resp = client.post("/api/execute", json={})
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data
        assert "task_description" in data["error"].lower()

    def test_execute_empty_string_description(self):
        """POST with whitespace-only task_description returns 400."""
        client = _setup_client()
        resp = client.post("/api/execute", json={"task_description": "   "})
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data

    def test_execute_returns_session_id(self):
        """POST with valid task_description returns 200 with session_id and status='started'.

        We patch _ensure_playground_ctx so the background asyncio task does not
        need a real DB or LLM.  The background task will fail (that is fine) --
        we only verify the immediate HTTP response.
        """
        client = _setup_client()

        with patch(
            "claw.web.dashboard_server._ensure_playground_ctx",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ):
            resp = client.post(
                "/api/execute",
                json={"task_description": "Add a hello world endpoint"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        # Validate the session_id is a proper UUID
        uuid.UUID(data["session_id"])  # raises ValueError if malformed
        assert data["status"] == "started"

    def test_execute_stores_job_in_state(self):
        """After POST, the job is present in app.state.playground_jobs."""
        client = _setup_client()

        with patch(
            "claw.web.dashboard_server._ensure_playground_ctx",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ):
            resp = client.post(
                "/api/execute",
                json={"task_description": "Implement feature X"},
            )

        data = resp.json()
        session_id = data["session_id"]
        jobs = getattr(client.app.state, "playground_jobs", {})
        assert session_id in jobs
        job = jobs[session_id]
        assert job["task_description"] == "Implement feature X"
        assert job["project_id"] == "playground"
        assert job["created_at"].endswith(("Z", "+00:00"))

    def test_execute_custom_project_id(self):
        """POST with a custom project_id stores it correctly."""
        client = _setup_client()

        with patch(
            "claw.web.dashboard_server._ensure_playground_ctx",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ):
            resp = client.post(
                "/api/execute",
                json={
                    "task_description": "Build a widget",
                    "project_id": "my-project",
                },
            )

        data = resp.json()
        session_id = data["session_id"]
        jobs = client.app.state.playground_jobs
        assert jobs[session_id]["project_id"] == "my-project"


# ---------------------------------------------------------------------------
# Tests: GET /api/sessions/{session_id}
# ---------------------------------------------------------------------------


class TestSessionsEndpoint:
    def test_session_not_found(self):
        """GET unknown session_id returns 404."""
        client = _setup_client()
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/sessions/{fake_id}")
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data

    def test_session_not_found_no_playground_jobs_attr(self):
        """GET when playground_jobs was never initialized still returns 404."""
        client = _setup_client()
        # Ensure no playground_jobs attribute on app.state
        if hasattr(client.app.state, "playground_jobs"):
            del client.app.state.playground_jobs

        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/sessions/{fake_id}")
        assert resp.status_code == 404

    def test_session_found(self):
        """GET a known session returns full shape with all expected fields."""
        client = _setup_client()
        session_id = str(uuid.uuid4())
        injected = _inject_job(client, session_id)

        resp = client.get(f"/api/sessions/{session_id}")
        assert resp.status_code == 200
        data = resp.json()

        # Verify response shape
        assert data["session_id"] == session_id
        assert data["status"] == "completed"
        assert isinstance(data["steps"], list)
        assert len(data["steps"]) == 1
        assert data["steps"][0]["step"] == "plan"
        assert isinstance(data["gates"], list)
        assert len(data["gates"]) == 3
        assert data["gates"][2]["status"] == "fail"
        assert data["corrections_count"] == 0
        assert data["result"] == {"success": True, "summary": "All gates passed"}
        assert data["error"] is None
        assert data["created_at"] == "2026-04-08T00:00:00Z"

    def test_session_found_with_corrections_count(self):
        """corrections_count reflects the number of correction entries."""
        client = _setup_client()
        session_id = str(uuid.uuid4())
        _inject_job(
            client,
            session_id,
            overrides={
                "corrections": [
                    {"attempt": 1, "feedback": "fix imports"},
                    {"attempt": 2, "feedback": "fix types"},
                ],
            },
        )

        resp = client.get(f"/api/sessions/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["corrections_count"] == 2

    def test_session_with_error_state(self):
        """Session in error state includes error field."""
        client = _setup_client()
        session_id = str(uuid.uuid4())
        _inject_job(
            client,
            session_id,
            overrides={
                "status": "error",
                "error": "ClawFactory.create() failed",
                "result": None,
            },
        )

        resp = client.get(f"/api/sessions/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert data["error"] == "ClawFactory.create() failed"
        assert data["result"] is None


# ---------------------------------------------------------------------------
# Tests: GET /api/sessions/{session_id}/corrections
# ---------------------------------------------------------------------------


class TestCorrectionsEndpoint:
    def test_corrections_not_found(self):
        """GET corrections for unknown session returns 404."""
        client = _setup_client()
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/sessions/{fake_id}/corrections")
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data

    def test_corrections_not_found_no_playground_jobs_attr(self):
        """GET corrections when playground_jobs was never initialized returns 404."""
        client = _setup_client()
        if hasattr(client.app.state, "playground_jobs"):
            del client.app.state.playground_jobs

        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/sessions/{fake_id}/corrections")
        assert resp.status_code == 404

    def test_corrections_found_empty(self):
        """Session with no corrections returns empty list, total_attempts=1."""
        client = _setup_client()
        session_id = str(uuid.uuid4())
        _inject_job(client, session_id, overrides={"corrections": []})

        resp = client.get(f"/api/sessions/{session_id}/corrections")
        assert resp.status_code == 200
        data = resp.json()

        assert data["session_id"] == session_id
        assert data["corrections"] == []
        assert data["total_attempts"] == 1  # +1 for initial attempt

    def test_corrections_found_with_data(self):
        """Session with corrections returns full shape."""
        client = _setup_client()
        session_id = str(uuid.uuid4())
        corrections_data = [
            {
                "attempt": 1,
                "violations": ["style_match"],
                "feedback": "Fix import ordering",
                "code_diff": "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-import os, sys\n+import os\n+import sys",
            },
            {
                "attempt": 2,
                "violations": ["chaos_check"],
                "feedback": "Add error handling for edge case",
                "code_diff": "--- a/foo.py\n+++ b/foo.py\n@@ -5 +5,3 @@\n-result = x / y\n+try:\n+    result = x / y\n+except ZeroDivisionError:\n+    result = 0",
            },
        ]
        _inject_job(client, session_id, overrides={"corrections": corrections_data})

        resp = client.get(f"/api/sessions/{session_id}/corrections")
        assert resp.status_code == 200
        data = resp.json()

        assert data["session_id"] == session_id
        assert isinstance(data["corrections"], list)
        assert len(data["corrections"]) == 2
        assert data["total_attempts"] == 3  # 2 corrections + 1 initial attempt
        # Verify correction content is passed through
        assert data["corrections"][0]["attempt"] == 1
        assert data["corrections"][1]["violations"] == ["chaos_check"]
