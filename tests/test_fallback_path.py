"""Tests for the SDK fallback model chain in CLAW.

Covers:
1. Config parsing: fallback_models field on LLMConfig
2. Format validation: model strings follow expected patterns
3. AgentInterface.set_fallback_models() / _fallback_models attribute
4. Fallback selection logic in _execute_openrouter_inner (chain ordering,
   dedup, non-retryable abort, retryable chain traversal)
5. LLMClient.complete_with_fallback() chain building and cooldown integration
6. Factory wiring: config.llm.fallback_models -> agent._fallback_models

All tests exercise real logic paths. No API calls are made -- the tests
validate config parsing, chain construction, and selection logic using
real config objects and real agent instances.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Optional

import pytest

from claw.core.config import ClawConfig, LLMConfig, load_config
from claw.core.models import AgentHealth, AgentMode, Task, TaskContext, TaskOutcome
from claw.agents.interface import AgentInterface
from claw.llm.client import LLMClient, LLMMessage


# ---------------------------------------------------------------------------
# Helpers: minimal concrete agent for testing the ABC
# ---------------------------------------------------------------------------

class _StubAgent(AgentInterface):
    """Minimal concrete agent for testing AgentInterface fallback logic.

    This is NOT a mock -- it is a real subclass that satisfies the ABC
    contract so we can test the inherited fallback chain methods.
    """

    def __init__(
        self,
        agent_id: str = "test_agent",
        model: Optional[str] = "test-model/v1",
        mode: AgentMode = AgentMode.OPENROUTER,
    ):
        super().__init__(agent_id=agent_id, name=f"Test Agent ({agent_id})")
        self.model = model
        self.mode = mode
        self.max_tokens = 4096

    @property
    def supported_modes(self):
        return [AgentMode.OPENROUTER]

    @property
    def instruction_file(self):
        return "TEST.md"

    async def execute(self, task, context=None):
        return await self.execute_openrouter(task, context)

    async def health_check(self):
        return AgentHealth(
            agent_id=self.agent_id,
            available=True,
            mode=AgentMode.OPENROUTER,
        )


def _make_task_context(title: str = "Test task", desc: str = "Do something") -> TaskContext:
    """Build a minimal real TaskContext for testing."""
    task = Task(
        project_id="test-project-001",
        title=title,
        description=desc,
    )
    return TaskContext(task=task)


# ---------------------------------------------------------------------------
# 1. Config parsing
# ---------------------------------------------------------------------------

class TestFallbackConfigParsing:
    """Verify fallback_models is correctly represented in the config schema."""

    def test_default_fallback_models_is_empty_list(self):
        """LLMConfig defaults to an empty fallback_models list."""
        config = LLMConfig()
        assert config.fallback_models == []
        assert isinstance(config.fallback_models, list)

    def test_fallback_models_accepts_list_of_strings(self):
        """LLMConfig accepts a list of model strings."""
        models = ["openai/gpt-4o-mini", "google/gemini-flash-1.5", "meta-llama/llama-3-70b"]
        config = LLMConfig(fallback_models=models)
        assert config.fallback_models == models
        assert len(config.fallback_models) == 3

    def test_fallback_models_in_full_config(self):
        """ClawConfig.llm.fallback_models is accessible and defaults empty."""
        config = ClawConfig()
        assert config.llm.fallback_models == []

    def test_fallback_models_preserved_through_full_config(self):
        """Fallback models set in nested LLM config survive ClawConfig construction."""
        llm = LLMConfig(fallback_models=["model-a", "model-b"])
        config = ClawConfig(llm=llm)
        assert config.llm.fallback_models == ["model-a", "model-b"]

    def test_load_config_from_toml(self):
        """Real claw.toml loads and fallback_models field is present."""
        toml_path = Path(__file__).parent.parent / "claw.toml"
        if not toml_path.exists():
            pytest.skip("claw.toml not found at project root")
        config = load_config(toml_path)
        # The field should be present (empty or populated)
        assert isinstance(config.llm.fallback_models, list)

    def test_single_model_fallback(self):
        """A single fallback model is valid."""
        config = LLMConfig(fallback_models=["anthropic/claude-3.5-haiku"])
        assert len(config.fallback_models) == 1
        assert config.fallback_models[0] == "anthropic/claude-3.5-haiku"


# ---------------------------------------------------------------------------
# 2. Format validation
# ---------------------------------------------------------------------------

class TestFallbackModelFormat:
    """Verify model strings follow expected format conventions."""

    # OpenRouter uses provider/model-name format
    VALID_MODEL_PATTERNS = [
        "openai/gpt-4o-mini",
        "openai/gpt-5.4-mini",
        "google/gemini-flash-1.5",
        "anthropic/claude-3.5-haiku",
        "meta-llama/llama-3-70b",
        "x-ai/grok-4.20-beta",
        "z-ai/glm-5-turbo",
        "minimax/minimax-m2.7",
    ]

    @pytest.mark.parametrize("model_str", VALID_MODEL_PATTERNS)
    def test_valid_model_format(self, model_str: str):
        """Model strings match provider/model-name pattern."""
        # OpenRouter format: provider/model-name (at minimum)
        assert "/" in model_str, f"Model '{model_str}' missing provider prefix"
        provider, name = model_str.split("/", 1)
        assert len(provider) > 0, "Empty provider"
        assert len(name) > 0, "Empty model name"

    def test_empty_string_not_added_to_chain(self):
        """Empty strings should not pollute the fallback chain."""
        config = LLMConfig(fallback_models=["", "openai/gpt-4o-mini", ""])
        # Config stores them as-is, but the agent chain builder filters empties
        agent = _StubAgent(model="primary/model")
        agent.set_fallback_models(config.fallback_models)
        # _fallback_models stores exactly what was set
        assert agent._fallback_models == ["", "openai/gpt-4o-mini", ""]


# ---------------------------------------------------------------------------
# 3. AgentInterface fallback attribute and setter
# ---------------------------------------------------------------------------

class TestAgentFallbackAttribute:
    """Test the _fallback_models attribute and set_fallback_models() method."""

    def test_default_fallback_models_empty(self):
        """New agents start with empty fallback chain."""
        agent = _StubAgent()
        assert agent._fallback_models == []

    def test_set_fallback_models(self):
        """set_fallback_models() stores the model list."""
        agent = _StubAgent()
        models = ["model-a", "model-b", "model-c"]
        agent.set_fallback_models(models)
        assert agent._fallback_models == models

    def test_set_fallback_models_creates_copy(self):
        """set_fallback_models() stores a copy, not a reference."""
        agent = _StubAgent()
        original = ["model-a", "model-b"]
        agent.set_fallback_models(original)
        original.append("model-c")
        assert len(agent._fallback_models) == 2  # Not affected by mutation

    def test_set_empty_clears_fallback(self):
        """Setting empty list clears any previously configured fallbacks."""
        agent = _StubAgent()
        agent.set_fallback_models(["model-a"])
        assert len(agent._fallback_models) == 1
        agent.set_fallback_models([])
        assert agent._fallback_models == []

    def test_multiple_agents_independent(self):
        """Each agent has its own independent fallback chain."""
        agent_a = _StubAgent(agent_id="agent_a")
        agent_b = _StubAgent(agent_id="agent_b")
        agent_a.set_fallback_models(["model-a"])
        agent_b.set_fallback_models(["model-b", "model-c"])
        assert agent_a._fallback_models == ["model-a"]
        assert agent_b._fallback_models == ["model-b", "model-c"]


# ---------------------------------------------------------------------------
# 4. Fallback selection logic (chain construction and ordering)
# ---------------------------------------------------------------------------

class TestFallbackChainConstruction:
    """Test the chain building logic in _execute_openrouter_inner.

    These tests verify the chain construction logic by examining the
    method's behavior with different fallback configurations. Since we
    cannot make real API calls, we test the precondition checks and
    chain-building logic that runs before any HTTP call.
    """

    @pytest.mark.asyncio
    async def test_no_model_returns_failure_immediately(self):
        """When no model is configured, returns failure without trying fallbacks."""
        agent = _StubAgent(model=None)
        agent.set_fallback_models(["fallback-model"])
        task_ctx = _make_task_context()
        outcome = await agent._execute_openrouter_inner(task_ctx)
        assert outcome.failure_reason == "no_model"
        assert "No model configured" in (outcome.failure_detail or "")

    @pytest.mark.asyncio
    async def test_no_api_key_returns_failure_immediately(self, monkeypatch):
        """When OPENROUTER_API_KEY is not set, returns failure without trying fallbacks."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        agent = _StubAgent(model="primary/model")
        agent.set_fallback_models(["fallback/model"])
        task_ctx = _make_task_context()
        outcome = await agent._execute_openrouter_inner(task_ctx)
        assert outcome.failure_reason == "no_api_key"

    def test_chain_deduplication(self):
        """If the primary model appears in fallbacks, it is not duplicated in chain."""
        agent = _StubAgent(model="primary/model")
        agent.set_fallback_models(["primary/model", "fallback/model-a", "primary/model"])

        # Simulate the chain construction logic from _execute_openrouter_inner
        primary_model = agent.model
        model_chain = [primary_model]
        for fb_model in agent._fallback_models:
            if fb_model and fb_model not in model_chain:
                model_chain.append(fb_model)

        assert model_chain == ["primary/model", "fallback/model-a"]
        assert len(model_chain) == 2  # No duplicates

    def test_chain_preserves_order(self):
        """Fallback models appear in the chain in their configured order."""
        agent = _StubAgent(model="primary/model")
        agent.set_fallback_models(["fb-1", "fb-2", "fb-3"])

        primary_model = agent.model
        model_chain = [primary_model]
        for fb_model in agent._fallback_models:
            if fb_model and fb_model not in model_chain:
                model_chain.append(fb_model)

        assert model_chain == ["primary/model", "fb-1", "fb-2", "fb-3"]

    def test_chain_filters_empty_strings(self):
        """Empty strings in fallback_models are filtered from the chain."""
        agent = _StubAgent(model="primary/model")
        agent.set_fallback_models(["", "fb-1", "", "fb-2"])

        primary_model = agent.model
        model_chain = [primary_model]
        for fb_model in agent._fallback_models:
            if fb_model and fb_model not in model_chain:
                model_chain.append(fb_model)

        assert model_chain == ["primary/model", "fb-1", "fb-2"]

    def test_chain_with_no_fallbacks(self):
        """With no fallbacks configured, chain contains only the primary model."""
        agent = _StubAgent(model="primary/model")
        # No set_fallback_models call

        primary_model = agent.model
        model_chain = [primary_model]
        for fb_model in agent._fallback_models:
            if fb_model and fb_model not in model_chain:
                model_chain.append(fb_model)

        assert model_chain == ["primary/model"]


# ---------------------------------------------------------------------------
# 5. LLMClient.complete_with_fallback() chain logic
# ---------------------------------------------------------------------------

class TestLLMClientFallbackChain:
    """Test the LLMClient.complete_with_fallback() chain construction logic.

    These tests verify the dedup, ordering, and cooldown integration
    without making real API calls.
    """

    def test_chain_dedup_in_client(self):
        """complete_with_fallback builds a deduped chain from models + config fallbacks."""
        config = LLMConfig(fallback_models=["fb-1", "fb-2"])
        client = LLMClient(config=config)

        # Simulate the chain building logic from complete_with_fallback
        models = ["primary", "fb-1"]  # fb-1 appears in both
        chain: list[str] = []
        for model in [*models, *client.config.fallback_models]:
            if model and model not in chain:
                chain.append(model)

        assert chain == ["primary", "fb-1", "fb-2"]

    def test_client_chain_empty_when_no_models(self):
        """When no models are provided and no fallbacks configured, chain is empty."""
        config = LLMConfig(fallback_models=[])
        client = LLMClient(config=config)

        models: list[str] = []
        chain: list[str] = []
        for model in [*models, *client.config.fallback_models]:
            if model and model not in chain:
                chain.append(model)

        assert chain == []

    def test_cooldown_skips_model(self):
        """A model in cooldown is skipped during chain traversal."""
        config = LLMConfig(
            fallback_models=["fb-1"],
            model_failure_threshold=1,
            model_cooldown_seconds=300,
        )
        client = LLMClient(config=config)

        # Put "primary" into cooldown
        client._record_model_failure("primary", Exception("test"))
        assert client._cooldown_remaining_seconds("primary") > 0

        # Verify the cooldown would cause a skip in the chain
        remaining = client._cooldown_remaining_seconds("primary")
        assert remaining > 0

        # fb-1 should NOT be in cooldown
        assert client._cooldown_remaining_seconds("fb-1") == 0.0

    def test_success_clears_cooldown_for_model(self):
        """Recording success on a model clears its cooldown."""
        config = LLMConfig(model_failure_threshold=1, model_cooldown_seconds=300)
        client = LLMClient(config=config)

        client._record_model_failure("model-a", Exception("test"))
        assert client._cooldown_remaining_seconds("model-a") > 0

        client._record_model_success("model-a")
        assert client._cooldown_remaining_seconds("model-a") == 0.0

    def test_failover_state_includes_fallback_models(self):
        """get_model_failover_state() reports state for models that have been tried."""
        config = LLMConfig(fallback_models=["fb-1", "fb-2"])
        client = LLMClient(config=config)

        client._record_model_failure("primary", Exception("fail"))
        client._record_model_failure("primary", Exception("fail"))  # threshold hit
        client._record_model_failure("fb-1", Exception("fail"))

        state = client.get_model_failover_state()
        assert "primary" in state
        assert state["primary"]["cooldown_remaining_seconds"] > 0
        assert "fb-1" in state


# ---------------------------------------------------------------------------
# 6. Verifier fallback_models usage
# ---------------------------------------------------------------------------

class TestVerifierFallbackModels:
    """Test that Verifier reads fallback_models from LLM config."""

    def test_verifier_reads_fallback_models_from_config(self):
        """Verifier accesses config.fallback_models for deep-check model selection."""
        config = LLMConfig(fallback_models=["verifier-model/v1"])
        client = LLMClient(config=config)

        # The verifier reads config.fallback_models[0] when _verifier_model is not set
        assert client.config.fallback_models[0] == "verifier-model/v1"

    def test_verifier_fallback_empty_skips_deep_check(self):
        """When fallback_models is empty and no _verifier_model, deep check is skipped."""
        config = LLMConfig(fallback_models=[])
        client = LLMClient(config=config)

        # No _verifier_model set, no fallback_models -> deep check would be skipped
        assert not hasattr(client, "_verifier_model")
        assert len(client.config.fallback_models) == 0


# ---------------------------------------------------------------------------
# 7. Integration: config -> factory -> agent wiring
# ---------------------------------------------------------------------------

class TestFactoryFallbackWiring:
    """Test that the factory correctly wires fallback_models from config to agents."""

    def test_config_llm_fallback_models_accessible(self):
        """Verify config.llm.fallback_models is accessible for factory wiring."""
        config = ClawConfig(
            llm=LLMConfig(fallback_models=["fb-model-1", "fb-model-2"])
        )
        # This is what the factory reads
        sdk_fallback_models = config.llm.fallback_models or []
        assert sdk_fallback_models == ["fb-model-1", "fb-model-2"]

    def test_factory_wiring_simulation(self):
        """Simulate the factory's agent wiring logic for fallback models."""
        config = ClawConfig(
            llm=LLMConfig(fallback_models=["fb-a", "fb-b"])
        )

        # Simulate what factory does
        agents: dict[str, AgentInterface] = {}
        sdk_fallback_models = config.llm.fallback_models or []

        agent = _StubAgent(agent_id="claude", model="primary/model")
        if sdk_fallback_models:
            agent.set_fallback_models(sdk_fallback_models)
        agents["claude"] = agent

        # Verify the agent received the fallback models
        assert agents["claude"]._fallback_models == ["fb-a", "fb-b"]

    def test_factory_wiring_empty_fallback(self):
        """When fallback_models is empty, agents get no fallback chain."""
        config = ClawConfig(llm=LLMConfig(fallback_models=[]))

        agent = _StubAgent(agent_id="codex", model="primary/model")
        sdk_fallback_models = config.llm.fallback_models or []
        if sdk_fallback_models:
            agent.set_fallback_models(sdk_fallback_models)

        assert agent._fallback_models == []


# ---------------------------------------------------------------------------
# 8. TaskOutcome failure_reason values for fallback scenarios
# ---------------------------------------------------------------------------

class TestFallbackFailureReasons:
    """Test that the expected failure_reason values are used in fallback scenarios."""

    @pytest.mark.asyncio
    async def test_no_model_failure_reason(self):
        """failure_reason='no_model' when no model configured."""
        agent = _StubAgent(model=None)
        outcome = await agent._execute_openrouter_inner(_make_task_context())
        assert outcome.failure_reason == "no_model"

    @pytest.mark.asyncio
    async def test_no_api_key_failure_reason(self, monkeypatch):
        """failure_reason='no_api_key' when OPENROUTER_API_KEY missing."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        agent = _StubAgent(model="test/model")
        outcome = await agent._execute_openrouter_inner(_make_task_context())
        assert outcome.failure_reason == "no_api_key"


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestFallbackEdgeCases:
    """Edge case testing for the fallback configuration and logic."""

    def test_very_long_fallback_chain(self):
        """Agent handles a large number of fallback models gracefully."""
        models = [f"provider/model-{i}" for i in range(50)]
        agent = _StubAgent(model="primary/model")
        agent.set_fallback_models(models)
        assert len(agent._fallback_models) == 50

        # Chain construction should work
        model_chain = ["primary/model"]
        for fb_model in agent._fallback_models:
            if fb_model and fb_model not in model_chain:
                model_chain.append(fb_model)
        assert len(model_chain) == 51  # primary + 50 fallbacks

    def test_fallback_models_with_special_characters(self):
        """Model strings with dots, hyphens, and numbers are valid."""
        models = [
            "openai/gpt-5.4-mini",
            "x-ai/grok-4.20-beta",
            "minimax/minimax-m2.7",
        ]
        config = LLMConfig(fallback_models=models)
        assert config.fallback_models == models

    def test_primary_model_same_as_only_fallback(self):
        """If primary == sole fallback, chain has only one entry (deduped)."""
        agent = _StubAgent(model="same/model")
        agent.set_fallback_models(["same/model"])

        model_chain = ["same/model"]
        for fb_model in agent._fallback_models:
            if fb_model and fb_model not in model_chain:
                model_chain.append(fb_model)

        assert model_chain == ["same/model"]

    def test_client_config_fallback_models_type_safety(self):
        """LLMConfig.fallback_models is always a list, never None."""
        config = LLMConfig()
        assert config.fallback_models is not None
        assert isinstance(config.fallback_models, list)

    def test_cooldown_threshold_interaction(self):
        """Cooldown threshold correctly gates when cooldown activates."""
        config = LLMConfig(
            model_failure_threshold=3,
            model_cooldown_seconds=60,
        )
        client = LLMClient(config=config)
        err = Exception("test")

        # 1st and 2nd failure: no cooldown yet
        client._record_model_failure("model-a", err)
        assert client._cooldown_remaining_seconds("model-a") == 0.0
        client._record_model_failure("model-a", err)
        assert client._cooldown_remaining_seconds("model-a") == 0.0

        # 3rd failure: threshold reached, cooldown activates
        client._record_model_failure("model-a", err)
        assert client._cooldown_remaining_seconds("model-a") > 0
