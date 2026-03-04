"""Tests for CLAW LLM client and token tracker."""

import pytest

from claw.llm.client import LLMClient, LLMMessage, LLMResponse, _backoff_delay, _parse_json_response
from claw.llm.token_tracker import TokenTracker
from claw.core.exceptions import ResponseParseError


class TestLLMMessage:
    def test_to_dict(self):
        msg = LLMMessage("user", "Hello")
        assert msg.to_dict() == {"role": "user", "content": "Hello"}


class TestLLMResponse:
    def test_fields(self):
        resp = LLMResponse(
            content="answer",
            model="test-model",
            tokens_used=100,
            input_tokens=60,
            output_tokens=40,
        )
        assert resp.content == "answer"
        assert resp.model == "test-model"
        assert resp.tokens_used == 100


class TestBackoff:
    def test_exponential(self):
        assert _backoff_delay(0) == 2.0
        assert _backoff_delay(1) == 4.0
        assert _backoff_delay(2) == 8.0

    def test_cap_at_60(self):
        assert _backoff_delay(10) == 60.0


class TestParseJson:
    def test_plain_json(self):
        result = _parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_fenced_json(self):
        result = _parse_json_response('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_invalid_json_raises(self):
        with pytest.raises(ResponseParseError):
            _parse_json_response("not json")


class TestLLMClientCooldown:
    def test_cooldown_mechanism(self):
        client = LLMClient()
        # Simulate failures
        error = Exception("fail")
        client._record_model_failure("model-a", error)
        assert client._cooldown_remaining_seconds("model-a") == 0.0  # Not yet at threshold

        client._record_model_failure("model-a", error)
        assert client._cooldown_remaining_seconds("model-a") > 0.0  # Now in cooldown

    def test_success_clears_cooldown(self):
        client = LLMClient()
        error = Exception("fail")
        client._record_model_failure("model-a", error)
        client._record_model_failure("model-a", error)
        assert client._cooldown_remaining_seconds("model-a") > 0.0

        client._record_model_success("model-a")
        assert client._cooldown_remaining_seconds("model-a") == 0.0

    def test_failover_state(self):
        client = LLMClient()
        error = Exception("fail")
        client._record_model_failure("model-a", error)
        client._record_model_failure("model-a", error)

        state = client.get_model_failover_state()
        assert "model-a" in state
        assert state["model-a"]["cooldown_remaining_seconds"] > 0


class TestTokenTracker:
    async def test_record_and_totals(self):
        tracker = TokenTracker()
        tracker.set_context(task_id="t1", agent_id="claude", agent_role="builder")

        r = await tracker.record("test-model", input_tokens=1000, output_tokens=500)
        assert r.input_tokens == 1000
        assert r.total_tokens == 1500
        assert r.cost_usd > 0

        session = tracker.get_session_totals()
        assert session["call_count"] == 1
        assert session["total_input_tokens"] == 1000

    async def test_per_agent_totals(self):
        tracker = TokenTracker()
        tracker.set_context(task_id="t1", agent_id="claude")
        await tracker.record("model", input_tokens=100, output_tokens=50)

        tracker.set_context(task_id="t1", agent_id="codex")
        await tracker.record("model", input_tokens=200, output_tokens=100)

        claude_totals = tracker.get_agent_totals("claude")
        assert claude_totals["total_input_tokens"] == 100

        codex_totals = tracker.get_agent_totals("codex")
        assert codex_totals["total_input_tokens"] == 200

    async def test_cost_estimation(self):
        tracker = TokenTracker(cost_per_1k_input=0.01, cost_per_1k_output=0.03)
        tracker.set_context(agent_id="test")
        r = await tracker.record("model", input_tokens=1000, output_tokens=1000)
        expected = 0.01 + 0.03
        assert abs(r.cost_usd - expected) < 0.001
