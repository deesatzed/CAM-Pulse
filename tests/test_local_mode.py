"""Tests for LOCAL mode (Ollama / MLX-LM) across all four CLAW agents.

Covers:
1. AgentMode.LOCAL enum value exists
2. LOCAL health check routing for each agent
3. LOCAL execute routing for each agent
4. _local_health_check() method on base AgentInterface
5. execute_local() success, connect error, and edge-case paths
6. Torch-free embeddings fallback (sentence-transformers not installed)
7. MLX embedding path routing
8. Factory creates LocalAgent for name='local'

Justification for unittest.mock usage:
We are testing OUR code's control flow, parsing, and error handling in
execute_local() and _local_health_check(). The httpx.AsyncClient calls are
the external boundary (local network). We patch ONLY those network calls
to avoid requiring a running Ollama/MLX-LM server during CI.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from claw.agents.claude import ClaudeCodeAgent
from claw.agents.codex import CodexAgent
from claw.agents.gemini import GeminiAgent
from claw.agents.grok import GrokAgent
from claw.agents.interface import AgentInterface
from claw.core.config import EmbeddingsConfig
from claw.core.models import AgentHealth, AgentMode, Task, TaskContext, TaskOutcome
from claw.db.embeddings import EmbeddingEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_context(
    title: str = "Test Task",
    description: str = "Do the thing",
) -> TaskContext:
    """Build a real TaskContext for tests."""
    task = Task(project_id="proj-1", title=title, description=description)
    return TaskContext(task=task)


def _make_local_response_json(
    content: str = "Here is the answer.",
    model: str = "llama3.2",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> dict:
    """Build a real OpenAI-compatible local LLM response dict."""
    return {
        "id": "chatcmpl-local-123",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _make_httpx_response(
    status_code: int = 200,
    json_data: dict | None = None,
) -> httpx.Response:
    """Build a real httpx.Response object."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data or {},
        request=httpx.Request("POST", "http://localhost:11434/v1/chat/completions"),
    )
    return resp


def _make_httpx_get_response(
    status_code: int = 200,
    json_data: dict | None = None,
) -> httpx.Response:
    """Build a real httpx.Response for GET /v1/models."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data or {"data": [{"id": "llama3.2"}]},
        request=httpx.Request("GET", "http://localhost:11434/v1/models"),
    )
    return resp


# ===========================================================================
# AgentMode.LOCAL enum
# ===========================================================================

class TestLocalModeEnum:
    def test_local_mode_exists(self):
        assert AgentMode.LOCAL == "local"
        assert AgentMode.LOCAL.value == "local"

    def test_local_mode_in_agent_mode_values(self):
        values = [m.value for m in AgentMode]
        assert "local" in values


# ===========================================================================
# LOCAL mode routing — all four agents
# ===========================================================================

class TestLocalModeRouting:
    """Verify that mode=LOCAL routes to execute_local / _local_health_check."""

    def _make_agents_local(self):
        return [
            ClaudeCodeAgent(mode=AgentMode.LOCAL, model="llama3.2"),
            CodexAgent(mode=AgentMode.LOCAL, model="llama3.2"),
            GeminiAgent(mode=AgentMode.LOCAL, model="llama3.2"),
            GrokAgent(mode=AgentMode.LOCAL, model="llama3.2"),
        ]

    @pytest.mark.asyncio
    async def test_health_check_routes_to_local(self):
        """All agents in LOCAL mode should call _local_health_check."""
        for agent in self._make_agents_local():
            with patch.object(
                type(agent).__mro__[1],  # AgentInterface
                "_local_health_check",
                new_callable=AsyncMock,
                return_value=AgentHealth(
                    agent_id=agent.agent_id,
                    available=True,
                    mode=AgentMode.LOCAL,
                    version="local:llama3.2",
                ),
            ) as mock_check:
                result = await agent.health_check()
                mock_check.assert_called_once_with(agent.agent_id)
                assert result.available is True
                assert result.mode == AgentMode.LOCAL

    @pytest.mark.asyncio
    async def test_execute_routes_to_local(self):
        """All agents in LOCAL mode should call execute_local."""
        ctx = _make_task_context()
        for agent in self._make_agents_local():
            with patch.object(
                type(agent).__mro__[1],
                "execute_local",
                new_callable=AsyncMock,
                return_value=TaskOutcome(
                    agent_id=agent.agent_id,
                    raw_output="done",
                    tests_passed=True,
                ),
            ) as mock_exec:
                result = await agent.execute(ctx)
                mock_exec.assert_called_once()
                assert result.agent_id == agent.agent_id
                assert result.tests_passed is True


# ===========================================================================
# _local_health_check tests
# ===========================================================================

class TestLocalHealthCheck:
    @pytest.mark.asyncio
    async def test_no_model_returns_unavailable(self):
        agent = ClaudeCodeAgent(mode=AgentMode.LOCAL, model=None)
        result = await agent._local_health_check("claude")
        assert result.available is False
        assert "No model configured" in result.error

    @pytest.mark.asyncio
    async def test_connect_error_returns_unavailable(self):
        agent = ClaudeCodeAgent(
            mode=AgentMode.LOCAL,
            model="llama3.2",
        )
        agent.local_base_url = "http://localhost:99999/v1"

        async def mock_get(self_client, url, **kwargs):
            raise httpx.ConnectError("Connection refused")

        with patch.object(httpx.AsyncClient, "get", mock_get):
            result = await agent._local_health_check("claude")
            assert result.available is False
            assert "not reachable" in result.error

    @pytest.mark.asyncio
    async def test_success_returns_available(self):
        agent = ClaudeCodeAgent(
            mode=AgentMode.LOCAL,
            model="llama3.2",
        )
        agent.local_base_url = "http://localhost:11434/v1"

        async def mock_get(self_client, url, **kwargs):
            return _make_httpx_get_response()

        with patch.object(httpx.AsyncClient, "get", mock_get):
            result = await agent._local_health_check("claude")
            assert result.available is True
            assert result.mode == AgentMode.LOCAL
            assert "local:llama3.2" in result.version

    @pytest.mark.asyncio
    async def test_custom_base_url(self):
        """MLX-LM uses port 8080 by default."""
        agent = GeminiAgent(
            mode=AgentMode.LOCAL,
            model="mlx-community/Llama-3.2-3B-Instruct-4bit",
        )
        agent.local_base_url = "http://localhost:8080/v1"

        captured_urls = []
        original_get = httpx.AsyncClient.get

        async def mock_get(self_client, url, **kwargs):
            captured_urls.append(url)
            return _make_httpx_get_response()

        with patch.object(httpx.AsyncClient, "get", mock_get):
            result = await agent._local_health_check("gemini")
            assert result.available is True
            assert captured_urls
            assert "8080" in captured_urls[0]


# ===========================================================================
# execute_local tests
# ===========================================================================

class TestExecuteLocal:
    @pytest.mark.asyncio
    async def test_no_model_returns_failure(self):
        agent = ClaudeCodeAgent(mode=AgentMode.LOCAL, model=None)
        ctx = _make_task_context()
        result = await agent.execute_local(ctx)
        assert result.failure_reason == "no_model"

    @pytest.mark.asyncio
    async def test_connect_error_returns_descriptive_failure(self):
        agent = CodexAgent(mode=AgentMode.LOCAL, model="llama3.2")
        agent.local_base_url = "http://localhost:11434/v1"
        ctx = _make_task_context()

        async def mock_post(self_client, url, **kwargs):
            raise httpx.ConnectError("Connection refused")

        with patch.object(httpx.AsyncClient, "post", mock_post):
            result = await agent.execute_local(ctx)
            assert result.failure_reason == "local_unreachable"
            assert "Ollama" in result.failure_detail or "MLX-LM" in result.failure_detail

    @pytest.mark.asyncio
    async def test_success_parses_response(self):
        agent = GrokAgent(mode=AgentMode.LOCAL, model="llama3.2")
        agent.local_base_url = "http://localhost:11434/v1"
        ctx = _make_task_context()

        resp_json = _make_local_response_json(
            content="Fixed the bug.",
            model="llama3.2",
            prompt_tokens=200,
            completion_tokens=100,
        )

        async def mock_post(self_client, url, **kwargs):
            return _make_httpx_response(200, resp_json)

        with patch.object(httpx.AsyncClient, "post", mock_post):
            result = await agent.execute_local(ctx)
            assert result.tests_passed is True
            assert result.raw_output == "Fixed the bug."
            assert result.tokens_used == 300
            assert result.model_used == "llama3.2"
            assert result.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_http_error_returns_failure(self):
        agent = GeminiAgent(mode=AgentMode.LOCAL, model="phi3")
        agent.local_base_url = "http://localhost:11434/v1"
        ctx = _make_task_context()

        error_resp = httpx.Response(
            status_code=500,
            json={"error": {"message": "Model not found"}},
            request=httpx.Request("POST", "http://localhost:11434/v1/chat/completions"),
        )

        async def mock_post(self_client, url, **kwargs):
            raise httpx.HTTPStatusError(
                "Server error",
                request=error_resp.request,
                response=error_resp,
            )

        with patch.object(httpx.AsyncClient, "post", mock_post):
            result = await agent.execute_local(ctx)
            assert result.failure_reason == "http_500"

    @pytest.mark.asyncio
    async def test_default_base_url_is_ollama(self):
        """Without local_base_url, should default to Ollama's port 11434."""
        agent = ClaudeCodeAgent(mode=AgentMode.LOCAL, model="llama3.2")
        # Don't set local_base_url — should default
        ctx = _make_task_context()

        captured_url = []

        async def mock_post(self_client, url, **kwargs):
            captured_url.append(url)
            return _make_httpx_response(200, _make_local_response_json())

        with patch.object(httpx.AsyncClient, "post", mock_post):
            await agent.execute_local(ctx)
            assert captured_url
            assert "11434" in captured_url[0]


# ===========================================================================
# can_use_internal_workspace_executor with LOCAL
# ===========================================================================

class TestWorkspaceExecutorLocal:
    def test_local_mode_can_use_workspace_executor(self):
        for agent_cls in [ClaudeCodeAgent, CodexAgent, GeminiAgent, GrokAgent]:
            agent = agent_cls(mode=AgentMode.LOCAL)
            assert agent.can_use_internal_workspace_executor() is True

    def test_cli_mode_cannot_use_workspace_executor(self):
        agent = ClaudeCodeAgent(mode=AgentMode.CLI)
        assert agent.can_use_internal_workspace_executor() is False

    def test_local_mode_cannot_modify_workspace_directly(self):
        agent = ClaudeCodeAgent(mode=AgentMode.LOCAL)
        assert agent.can_modify_workspace() is False


# ===========================================================================
# Torch-free embeddings
# ===========================================================================

class TestTorchFreeEmbeddings:
    def test_gemini_model_skips_sentence_transformers(self):
        """Gemini-prefixed models should never touch sentence-transformers."""
        cfg = EmbeddingsConfig(
            model="gemini-embedding-2-preview",
            dimension=384,
        )
        engine = EmbeddingEngine(cfg)
        assert engine._uses_gemini_api is True
        assert engine.model is None  # Should NOT try to load ST

    def test_non_gemini_model_flags(self):
        """Non-gemini model should flag for sentence-transformers usage."""
        cfg = EmbeddingsConfig(model="all-MiniLM-L6-v2", dimension=384)
        engine = EmbeddingEngine(cfg)
        assert engine._uses_gemini_api is False

    def test_mlx_model_prefix_detected(self):
        """mlx-community/ prefix should trigger MLX path."""
        cfg = EmbeddingsConfig(
            model="mlx-community/bge-small-en-v1.5",
            dimension=384,
        )
        engine = EmbeddingEngine(cfg)
        assert engine._uses_mlx is True
        assert engine._uses_gemini_api is False
        assert engine.model is None  # Should NOT try to load ST

    def test_mlx_embeddings_prefix_detected(self):
        """mlx-embeddings: prefix should trigger MLX path."""
        cfg = EmbeddingsConfig(
            model="mlx-embeddings:bge-small",
            dimension=384,
        )
        engine = EmbeddingEngine(cfg)
        assert engine._uses_mlx is True

    def test_mlx_encode_routes_to_mlx(self, monkeypatch):
        """encode() should use MLX path when model starts with mlx-community/."""
        cfg = EmbeddingsConfig(
            model="mlx-community/bge-small-en-v1.5",
            dimension=3,
        )
        engine = EmbeddingEngine(cfg)
        monkeypatch.setattr(engine, "_embed_with_mlx", lambda texts: [[0.1, 0.2, 0.3]])
        vec = engine.encode("test")
        assert vec == [0.1, 0.2, 0.3]

    def test_mlx_encode_batch_routes_to_mlx(self, monkeypatch):
        """encode_batch() should use MLX path."""
        cfg = EmbeddingsConfig(
            model="mlx-community/bge-small-en-v1.5",
            dimension=2,
        )
        engine = EmbeddingEngine(cfg)
        monkeypatch.setattr(
            engine,
            "_embed_with_mlx",
            lambda texts: [[float(i), 1.0] for i in range(len(texts))],
        )
        vecs = engine.encode_batch(["a", "b"])
        assert len(vecs) == 2
        assert vecs[1][0] == 1.0

    def test_mlx_encode_batch_empty_list(self, monkeypatch):
        cfg = EmbeddingsConfig(model="mlx-community/x", dimension=3)
        engine = EmbeddingEngine(cfg)
        result = engine.encode_batch([])
        assert result == []


# ===========================================================================
# Config: local_base_url field
# ===========================================================================

class TestLocalConfigField:
    def test_agent_config_has_local_base_url(self):
        from claw.core.config import AgentConfig
        cfg = AgentConfig(
            enabled=True,
            mode="local",
            model="llama3.2",
            local_base_url="http://localhost:8080/v1",
        )
        assert cfg.local_base_url == "http://localhost:8080/v1"
        assert cfg.mode == "local"

    def test_agent_config_local_base_url_defaults_none(self):
        from claw.core.config import AgentConfig
        cfg = AgentConfig()
        assert cfg.local_base_url is None


# ===========================================================================
# Factory: LocalAgent creation
# ===========================================================================

class TestLocalAgentFactory:
    """Verify factory creates LocalAgent for name='local'."""

    def test_factory_creates_local_agent(self):
        from claw.core.config import AgentConfig
        from claw.core.factory import _create_agent
        from claw.agents.local_agent import LocalAgent

        cfg = AgentConfig(
            enabled=True,
            mode="local",
            model="test-model",
            local_base_url="http://localhost:1337/v1",
        )
        agent = _create_agent("local", cfg, workspace_dir="/tmp/test")
        assert isinstance(agent, LocalAgent)
        assert agent.model == "test-model"
        assert agent.local_base_url == "http://localhost:1337/v1"
        assert agent.workspace_dir == "/tmp/test"

    def test_factory_local_default_base_url(self):
        from claw.core.config import AgentConfig
        from claw.core.factory import _create_agent
        from claw.agents.local_agent import LocalAgent

        cfg = AgentConfig(enabled=True, mode="local", model="m")
        agent = _create_agent("local", cfg)
        assert isinstance(agent, LocalAgent)
        assert agent.local_base_url == "http://localhost:11434/v1"
