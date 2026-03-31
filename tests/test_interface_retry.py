"""Tests for AgentInterface retry + semaphore enhancements.

Validates:
- Retry logic in execute_openrouter() and execute_local()
- Exponential backoff with jitter
- Module-level semaphore enforcement
- Non-retryable errors (401, 404) fail immediately
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from claw.agents.interface import (
    AgentInterface,
    _agent_backoff_delay,
    get_agent_semaphore,
)
from claw.core.models import TaskContext, TaskOutcome


# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing
# ---------------------------------------------------------------------------

class _StubAgent(AgentInterface):
    """Concrete agent for testing interface-level methods."""

    def __init__(self, agent_id: str = "test", name: str = "Test Agent"):
        super().__init__(agent_id, name)
        self.model = "test/model"
        self.max_tokens = 4096
        self.timeout = 10

    async def execute(self, task: TaskContext, context=None) -> TaskOutcome:
        return TaskOutcome(agent_id=self.agent_id)

    async def health_check(self) -> dict:
        return {"status": "ok"}

    @property
    def supported_modes(self) -> list[str]:
        return ["openrouter"]

    @property
    def instruction_file(self):
        return None


def _make_task() -> TaskContext:
    """Build a minimal TaskContext for testing."""
    from claw.core.models import Task
    task = Task(
        id="test-task-001",
        project_id="test-project",
        task_type="analysis",
        title="Test task",
        description="Test task",
    )
    return TaskContext(task=task, project_path="/tmp/test")


# ---------------------------------------------------------------------------
# Backoff delay tests
# ---------------------------------------------------------------------------

class TestAgentBackoffDelay:
    """_agent_backoff_delay() produces exponential delays with jitter."""

    def test_first_attempt_around_2s(self):
        delays = [_agent_backoff_delay(0, base_seconds=2.0) for _ in range(50)]
        assert all(2.0 <= d <= 3.5 for d in delays)

    def test_second_attempt_around_4s(self):
        delays = [_agent_backoff_delay(1, base_seconds=2.0) for _ in range(50)]
        assert all(4.0 <= d <= 5.5 for d in delays)

    def test_capped_at_60s(self):
        delays = [_agent_backoff_delay(10, base_seconds=2.0) for _ in range(50)]
        assert all(d <= 61.5 for d in delays)

    def test_jitter_produces_varied_values(self):
        delays = [_agent_backoff_delay(0, base_seconds=2.0) for _ in range(100)]
        unique = len(set(delays))
        assert unique > 50, f"Expected varied delays, got {unique} unique out of 100"


# ---------------------------------------------------------------------------
# Semaphore tests
# ---------------------------------------------------------------------------

class TestAgentSemaphore:
    """Module-level semaphore enforces max_concurrent."""

    def test_returns_semaphore(self):
        sem = get_agent_semaphore(3)
        assert isinstance(sem, asyncio.Semaphore)

    def test_same_limit_returns_same_semaphore(self):
        sem1 = get_agent_semaphore(5)
        sem2 = get_agent_semaphore(5)
        assert sem1 is sem2

    def test_different_limit_returns_new_semaphore(self):
        sem1 = get_agent_semaphore(5)
        sem2 = get_agent_semaphore(3)
        assert sem1 is not sem2

    @pytest.mark.asyncio
    async def test_limits_concurrency(self):
        """Verify semaphore actually limits concurrent access."""
        max_concurrent = 2
        sem = get_agent_semaphore(max_concurrent)
        active = 0
        max_active = 0

        async def worker():
            nonlocal active, max_active
            async with sem:
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.05)
                active -= 1

        await asyncio.gather(*[worker() for _ in range(10)])
        assert max_active <= max_concurrent


# ---------------------------------------------------------------------------
# execute_openrouter retry tests
# ---------------------------------------------------------------------------

class TestExecuteOpenrouterRetry:
    """execute_openrouter() retries transient errors."""

    @pytest.mark.asyncio
    async def test_retries_on_429(self):
        """429 is retried up to max_retries times."""
        agent = _StubAgent()
        agent._max_concurrent = 10  # Don't block on semaphore
        task = _make_task()

        resp_429 = httpx.Response(429, request=httpx.Request("POST", "https://x"))
        resp_200 = httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "model": "test/model",
            },
            request=httpx.Request("POST", "https://x"),
        )

        call_count = 0
        original_post = httpx.AsyncClient.post

        async def mock_post(self_client, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return resp_429
            return resp_200

        with patch.object(httpx.AsyncClient, "post", mock_post):
            with patch("os.getenv", return_value="test-key"):
                with patch.object(agent, "_build_openrouter_prompt", return_value="test prompt"):
                    with patch("claw.agents.interface._agent_backoff_delay", return_value=0.01):
                        outcome = await agent.execute_openrouter(task)

        assert outcome.failure_reason is None
        assert outcome.raw_output == "ok"
        assert call_count == 3  # 2 retries + 1 success

    @pytest.mark.asyncio
    async def test_fails_after_max_retries_on_500(self):
        """Persistent 500 errors exhaust retries."""
        agent = _StubAgent()
        agent._max_concurrent = 10
        task = _make_task()

        resp_500 = httpx.Response(500, request=httpx.Request("POST", "https://x"))

        async def mock_post(self_client, url, **kwargs):
            return resp_500

        with patch.object(httpx.AsyncClient, "post", mock_post):
            with patch("os.getenv", return_value="test-key"):
                with patch.object(agent, "_build_openrouter_prompt", return_value="test"):
                    with patch("claw.agents.interface._agent_backoff_delay", return_value=0.01):
                        outcome = await agent.execute_openrouter(task)

        assert outcome.failure_reason == "max_retries"

    @pytest.mark.asyncio
    async def test_401_fails_immediately(self):
        """401 is not retried — returns immediately."""
        agent = _StubAgent()
        agent._max_concurrent = 10
        task = _make_task()

        resp_401 = httpx.Response(401, request=httpx.Request("POST", "https://x"))
        call_count = 0

        async def mock_post(self_client, url, **kwargs):
            nonlocal call_count
            call_count += 1
            return resp_401

        with patch.object(httpx.AsyncClient, "post", mock_post):
            with patch("os.getenv", return_value="test-key"):
                with patch.object(agent, "_build_openrouter_prompt", return_value="test"):
                    outcome = await agent.execute_openrouter(task)

        assert outcome.failure_reason == "http_401"
        assert call_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_404_fails_immediately(self):
        """404 is not retried — returns immediately."""
        agent = _StubAgent()
        agent._max_concurrent = 10
        task = _make_task()

        resp_404 = httpx.Response(404, request=httpx.Request("POST", "https://x"))

        async def mock_post(self_client, url, **kwargs):
            return resp_404

        with patch.object(httpx.AsyncClient, "post", mock_post):
            with patch("os.getenv", return_value="test-key"):
                with patch.object(agent, "_build_openrouter_prompt", return_value="test"):
                    outcome = await agent.execute_openrouter(task)

        assert outcome.failure_reason == "http_404"

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self):
        """Timeout errors trigger retry."""
        agent = _StubAgent()
        agent._max_concurrent = 10
        task = _make_task()

        call_count = 0

        async def mock_post(self_client, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise httpx.ReadTimeout("timeout")
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "recovered"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 5},
                    "model": "test/model",
                },
                request=httpx.Request("POST", "https://x"),
            )

        with patch.object(httpx.AsyncClient, "post", mock_post):
            with patch("os.getenv", return_value="test-key"):
                with patch.object(agent, "_build_openrouter_prompt", return_value="test"):
                    with patch("claw.agents.interface._agent_backoff_delay", return_value=0.01):
                        outcome = await agent.execute_openrouter(task)

        assert outcome.raw_output == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_api_key_returns_immediately(self):
        """Missing API key returns error without any HTTP call."""
        agent = _StubAgent()
        task = _make_task()

        with patch("os.getenv", return_value=""):
            outcome = await agent.execute_openrouter(task)

        assert outcome.failure_reason == "no_api_key"

    @pytest.mark.asyncio
    async def test_no_model_returns_immediately(self):
        """Missing model returns error without any HTTP call."""
        agent = _StubAgent()
        agent.model = None
        task = _make_task()

        outcome = await agent.execute_openrouter(task)
        assert outcome.failure_reason == "no_model"


# ---------------------------------------------------------------------------
# execute_local retry tests
# ---------------------------------------------------------------------------

class TestExecuteLocalRetry:
    """execute_local() retries transient errors."""

    @pytest.mark.asyncio
    async def test_retries_on_connect_error(self):
        """ConnectError triggers retry with backoff."""
        agent = _StubAgent()
        agent._max_concurrent = 10
        task = _make_task()

        call_count = 0

        async def mock_post(self_client, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise httpx.ConnectError("refused")
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "local ok"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 5},
                    "model": "local/model",
                },
                request=httpx.Request("POST", "http://localhost:11434/v1/chat/completions"),
            )

        with patch.object(httpx.AsyncClient, "post", mock_post):
            with patch.object(agent, "_build_openrouter_prompt", return_value="test"):
                with patch("claw.agents.interface._agent_backoff_delay", return_value=0.01):
                    outcome = await agent.execute_local(task)

        assert outcome.raw_output == "local ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_persistent_connect_error_reports_unreachable(self):
        """Persistent ConnectError gives local_unreachable failure."""
        agent = _StubAgent()
        agent._max_concurrent = 10
        task = _make_task()

        async def mock_post(self_client, url, **kwargs):
            raise httpx.ConnectError("refused")

        with patch.object(httpx.AsyncClient, "post", mock_post):
            with patch.object(agent, "_build_openrouter_prompt", return_value="test"):
                with patch("claw.agents.interface._agent_backoff_delay", return_value=0.01):
                    outcome = await agent.execute_local(task)

        assert outcome.failure_reason == "local_unreachable"
