# Phase 1: CAM-PULSE Local MLX Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a 5th "local" agent slot to CAM-PULSE that routes tasks to a local MLX/llama.cpp server (Atomic-Chat, mlx-server, Ollama) via OpenAI-compatible API, with Kelly recalibration for $0-cost agents, MLX embedding activation, task-type routing priors, and a CAG methodology serializer.

**Architecture:** Five parallel work streams modifying isolated files. The `local` agent reuses `AgentInterface.execute_local()` (already implemented). Kelly gets a quality-only payoff branch. Embeddings already support MLX — just needs config wiring. Dispatcher gets new static routing entries. CAG serializer is a standalone new module reading from the existing `Repository`/`Methodology` models.

**Tech Stack:** Python 3.11+, httpx, Pydantic, SQLite, pytest, TOML config

**Design doc:** `docs/plans/2026-03-30-local-mlx-cam-design.md`

---

## Work Stream 1A: Local Agent + Backend Config

### Task 1: Add LocalAgent class

**Files:**
- Create: `src/claw/agents/local_agent.py`
- Test: `tests/test_local_agent.py`

**Step 1: Write the failing test**

```python
# tests/test_local_agent.py
"""Tests for the dedicated LocalAgent."""
from __future__ import annotations

import pytest

from claw.agents.local_agent import LocalAgent
from claw.core.models import AgentHealth, AgentMode, Task, TaskContext


def _make_task_context(title="Test", description="Do it") -> TaskContext:
    task = Task(project_id="proj-1", title=title, description=description)
    return TaskContext(task=task)


class TestLocalAgentInit:
    def test_agent_id_is_local(self):
        agent = LocalAgent(model="test-model", local_base_url="http://localhost:1337/v1")
        assert agent.agent_id == "local"

    def test_mode_is_always_local(self):
        agent = LocalAgent(model="test-model", local_base_url="http://localhost:1337/v1")
        assert agent.mode == AgentMode.LOCAL

    def test_supported_modes_only_local(self):
        agent = LocalAgent(model="test-model", local_base_url="http://localhost:1337/v1")
        assert agent.supported_modes == [AgentMode.LOCAL]

    def test_custom_base_url_stored(self):
        agent = LocalAgent(model="m", local_base_url="http://localhost:8080/v1")
        assert agent.local_base_url == "http://localhost:8080/v1"

    def test_no_model_raises_on_execute(self):
        """Agent with empty model returns failure outcome."""
        import asyncio
        agent = LocalAgent(model="", local_base_url="http://localhost:1337/v1")
        tc = _make_task_context()
        result = asyncio.get_event_loop().run_until_complete(agent.execute(tc))
        assert result.failure_reason == "no_model"
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_local_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claw.agents.local_agent'`

**Step 3: Write minimal implementation**

```python
# src/claw/agents/local_agent.py
"""Local LLM Agent for CLAW.

Dedicated agent for local inference backends (Atomic-Chat, mlx-server,
Ollama, llama.cpp). Uses the OpenAI-compatible /v1/chat/completions
endpoint that all local providers expose.

All inference logic lives in AgentInterface.execute_local() — this class
just wires the config and constrains the mode to LOCAL.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from claw.agents.interface import AgentInterface
from claw.core.models import AgentHealth, AgentMode, TaskContext, TaskOutcome

logger = logging.getLogger("claw.agent.local")


class LocalAgent(AgentInterface):
    """Local inference agent — Atomic-Chat, mlx-server, Ollama, llama.cpp."""

    def __init__(
        self,
        model: Optional[str] = None,
        local_base_url: str = "http://localhost:11434/v1",
        timeout: int = 300,
        max_tokens: int = 16384,
        workspace_dir: Optional[str] = None,
    ):
        super().__init__(agent_id="local", name="Local LLM Agent")
        self.mode = AgentMode.LOCAL
        self.model = model
        self.local_base_url = local_base_url
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.workspace_dir = workspace_dir

    @property
    def supported_modes(self) -> list[AgentMode]:
        return [AgentMode.LOCAL]

    @property
    def instruction_file(self) -> str:
        return ""

    async def health_check(self) -> AgentHealth:
        return await self._local_health_check("local")

    async def execute(
        self, task: TaskContext, context: Optional[Any] = None
    ) -> TaskOutcome:
        return await self.execute_local(task, context)
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_local_agent.py -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add src/claw/agents/local_agent.py tests/test_local_agent.py
git commit -m "feat: add LocalAgent class for dedicated local inference slot"
```

---

### Task 2: Register LocalAgent in factory

**Files:**
- Modify: `src/claw/core/factory.py:305-363`
- Modify: `tests/test_local_mode.py` (add factory test)

**Step 1: Write the failing test**

Add to `tests/test_local_mode.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_local_mode.py::TestLocalAgentFactory -v`
Expected: FAIL — `assert isinstance(agent, LocalAgent)` fails (factory returns None for unknown "local" name)

**Step 3: Write minimal implementation**

In `src/claw/core/factory.py`, add after the grok block (after line 360):

```python
    if name == "local":
        from claw.agents.local_agent import LocalAgent
        return LocalAgent(
            model=agent_cfg.model,
            local_base_url=agent_cfg.local_base_url or "http://localhost:11434/v1",
            timeout=agent_cfg.timeout,
            max_tokens=agent_cfg.max_tokens,
            workspace_dir=workspace_dir,
        )
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_local_mode.py::TestLocalAgentFactory -v`
Expected: PASS

**Step 5: Run full test suite to confirm no regressions**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest --tb=short -q`
Expected: All 2624+ tests pass

**Step 6: Commit**

```bash
git add src/claw/core/factory.py tests/test_local_mode.py
git commit -m "feat: register LocalAgent in factory for [agents.local] config"
```

---

### Task 3: Add LocalLLMConfig enhancements

**Files:**
- Modify: `src/claw/core/config.py:117-122`
- Test: `tests/test_config.py` (or existing config tests)

**Step 1: Write the failing test**

```python
# Add to tests/test_config.py or create tests/test_local_config.py
class TestLocalLLMConfig:
    def test_default_provider(self):
        from claw.core.config import LocalLLMConfig
        cfg = LocalLLMConfig()
        assert cfg.provider == "ollama"

    def test_ctx_size_default(self):
        from claw.core.config import LocalLLMConfig
        cfg = LocalLLMConfig()
        assert cfg.ctx_size == 32768

    def test_kv_cache_type_default(self):
        from claw.core.config import LocalLLMConfig
        cfg = LocalLLMConfig()
        assert cfg.kv_cache_type == "f16"

    def test_custom_values(self):
        from claw.core.config import LocalLLMConfig
        cfg = LocalLLMConfig(
            provider="atomic-chat",
            base_url="http://localhost:1337/v1",
            ctx_size=131072,
            kv_cache_type="turbo3",
        )
        assert cfg.provider == "atomic-chat"
        assert cfg.ctx_size == 131072
        assert cfg.kv_cache_type == "turbo3"
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_local_config.py -v`
Expected: FAIL — `AttributeError: 'LocalLLMConfig' has no field 'ctx_size'`

**Step 3: Write minimal implementation**

Replace `LocalLLMConfig` in `src/claw/core/config.py:117-122`:

```python
class LocalLLMConfig(BaseModel):
    """Configuration for local LLM providers (Ollama, MLX-LM, Atomic-Chat, llama.cpp)."""
    provider: str = "ollama"  # ollama | mlx-server | atomic-chat | llama-cpp
    base_url: str = "http://localhost:11434/v1"
    model: str = ""
    timeout: int = 300
    ctx_size: int = 32768  # 64GB default; set 131072 for 128GB
    kv_cache_type: str = "f16"  # f16 | q4_0 | turbo3
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_local_config.py -v`
Expected: PASS (4 tests)

**Step 5: Run full test suite**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest --tb=short -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/claw/core/config.py tests/test_local_config.py
git commit -m "feat: extend LocalLLMConfig with ctx_size, kv_cache_type, provider"
```

---

### Task 4: Enhance execute_local() with provider-aware health check

**Files:**
- Modify: `src/claw/agents/interface.py:735-780`
- Modify: `tests/test_local_mode.py`

**Step 1: Write the failing test**

Add to `tests/test_local_mode.py`:

```python
class TestLocalHealthCheckProviderAware:
    """Health check returns provider info from /v1/models response."""

    def test_health_check_reports_model_list(self):
        """Health check extracts model IDs from /v1/models response."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        models_response = {
            "data": [
                {"id": "mlx-community/Qwen2.5-7B-Instruct-4bit", "object": "model"},
            ]
        }
        resp = _make_httpx_response(200, models_response)

        agent = ClaudeCodeAgent(mode=AgentMode.LOCAL, model="test")
        agent.local_base_url = "http://localhost:1337/v1"

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=resp):
            health = asyncio.get_event_loop().run_until_complete(
                agent._local_health_check("claude")
            )
        assert health.available is True
        assert health.mode == AgentMode.LOCAL
```

**Step 2: Run test to verify current behavior**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_local_mode.py::TestLocalHealthCheckProviderAware -v`
Expected: PASS (this test should pass with existing code since health check already works)

This confirms existing behavior is correct. No code change needed for basic health check — the existing `_local_health_check` at line 735 already hits `/v1/models`.

**Step 3: Commit test only**

```bash
git add tests/test_local_mode.py
git commit -m "test: add provider-aware health check tests for local mode"
```

---

## Work Stream 1B: Kelly Routing Recalibration

### Task 5: Add quality-only payoff for $0-cost agents

**Files:**
- Modify: `src/claw/evolution/kelly.py:117-120`
- Modify: `src/claw/core/config.py` (KellyConfig)
- Modify: `tests/test_kelly.py`

**Step 1: Write the failing test**

Add to `tests/test_kelly.py`:

```python
class TestKellyLocalAgentPayoff:
    """Kelly handles $0-cost local agents without degenerate payoff ratios."""

    def test_zero_cost_uses_quality_payoff(self):
        """When avg_cost_usd == 0, payoff is based on quality alone."""
        sizer = BayesianKellySizer(kappa=10.0, local_quality_multiplier=2.0)
        result = sizer.compute_fraction(
            successes=20, failures=5,
            avg_quality_score=0.7, avg_cost_usd=0.0,
        )
        # b should be 0.7 * 2.0 = 1.4, NOT infinity
        assert result.payoff_ratio == pytest.approx(1.4, abs=0.01)
        assert result.fraction > 0
        assert result.fraction <= 0.40  # under f_max

    def test_zero_cost_zero_quality_uses_default(self):
        """When both cost and quality are 0, use payoff_default."""
        sizer = BayesianKellySizer(kappa=10.0)
        result = sizer.compute_fraction(
            successes=0, failures=0,
            avg_quality_score=0.0, avg_cost_usd=0.0,
        )
        assert result.payoff_ratio == pytest.approx(2.0, abs=0.01)

    def test_nonzero_cost_unchanged(self):
        """Existing behavior: nonzero cost uses quality/cost ratio."""
        sizer = BayesianKellySizer(kappa=10.0)
        result = sizer.compute_fraction(
            successes=20, failures=5,
            avg_quality_score=0.7, avg_cost_usd=0.01,
        )
        expected_b = 0.7 / 0.01  # = 70.0
        assert result.payoff_ratio == pytest.approx(expected_b, abs=0.1)

    def test_local_quality_multiplier_default(self):
        """Default local_quality_multiplier is 2.0."""
        sizer = BayesianKellySizer()
        assert sizer.local_quality_multiplier == 2.0
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_kelly.py::TestKellyLocalAgentPayoff -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'local_quality_multiplier'`

**Step 3: Write minimal implementation**

In `src/claw/evolution/kelly.py`:

Add `local_quality_multiplier` parameter to `__init__` (after line 76):

```python
    def __init__(
        self,
        kappa: float = 10.0,
        f_max: float = 0.40,
        min_exploration_floor: float = 0.02,
        payoff_default: float = 2.0,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
        local_quality_multiplier: float = 2.0,
    ):
```

Add `self.local_quality_multiplier = local_quality_multiplier` in body.

Replace lines 117-120 in `compute_fraction`:

```python
        if avg_cost_usd > 0.001 and avg_quality_score > 0.0:
            b = avg_quality_score / avg_cost_usd
        elif avg_cost_usd <= 0.001 and avg_quality_score > 0.0:
            # Local/free agents: compete on quality, not cost ratio
            b = avg_quality_score * self.local_quality_multiplier
        else:
            b = self.payoff_default
```

In `src/claw/core/config.py` `KellyConfig` class, add field:

```python
    local_quality_multiplier: float = 2.0  # Payoff multiplier for $0-cost local agents
```

In `src/claw/core/factory.py` where `BayesianKellySizer` is instantiated (line ~134), add:

```python
        local_quality_multiplier=config.kelly.local_quality_multiplier,
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_kelly.py::TestKellyLocalAgentPayoff -v`
Expected: PASS (4 tests)

**Step 5: Run full Kelly tests + full suite**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_kelly.py -v && python -m pytest --tb=short -q`
Expected: All Kelly tests pass, all 2624+ tests pass

**Step 6: Commit**

```bash
git add src/claw/evolution/kelly.py src/claw/core/config.py src/claw/core/factory.py tests/test_kelly.py
git commit -m "feat: Kelly quality-only payoff for zero-cost local agents"
```

---

## Work Stream 1C: MLX Embedding Activation

### Task 6: Verify MLX embedding path works and add config guidance

**Files:**
- Modify: `tests/test_embeddings.py`
- No code changes needed — MLX embedding path already implemented in `embeddings.py:68-105`

**Step 1: Write the test**

Add to `tests/test_embeddings.py`:

```python
class TestMLXEmbeddingRouting:
    """Verify MLX model selection routes to _embed_with_mlx."""

    def test_mlx_community_prefix_detected(self):
        cfg = EmbeddingsConfig(model="mlx-community/bge-small-en-v1.5", dimension=384)
        engine = EmbeddingEngine(cfg)
        assert engine._uses_mlx is True
        assert engine._uses_gemini_api is False

    def test_mlx_embeddings_prefix_detected(self):
        cfg = EmbeddingsConfig(model="mlx-embeddings:bge-small-en-v1.5", dimension=384)
        engine = EmbeddingEngine(cfg)
        assert engine._uses_mlx is True

    def test_gemini_prefix_not_mlx(self):
        cfg = EmbeddingsConfig(model="gemini-embedding-2-preview", dimension=384)
        engine = EmbeddingEngine(cfg)
        assert engine._uses_mlx is False
        assert engine._uses_gemini_api is True

    def test_dimension_384_compatible(self):
        """MLX model with 384 dims is compatible with existing vec0 table."""
        cfg = EmbeddingsConfig(model="mlx-community/bge-small-en-v1.5", dimension=384)
        engine = EmbeddingEngine(cfg)
        assert engine.dimension == 384
```

**Step 2: Run test**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_embeddings.py::TestMLXEmbeddingRouting -v`
Expected: PASS (all 4 — this confirms existing code works correctly)

**Step 3: Commit test**

```bash
git add tests/test_embeddings.py
git commit -m "test: verify MLX embedding routing for local offline operation"
```

---

## Work Stream 1D: Task-Type Routing Priors for Local

### Task 7: Add local agent to static routing table

**Files:**
- Modify: `src/claw/dispatcher.py:35-56`
- Modify: `tests/test_dispatcher.py`

**Step 1: Write the failing test**

Add to `tests/test_dispatcher.py`:

```python
class TestLocalAgentRouting:
    """Verify local agent gets routed for appropriate task types."""

    def test_mining_extraction_routes_to_local(self):
        from claw.dispatcher import STATIC_ROUTING
        assert STATIC_ROUTING.get("mining_extraction") == "local"

    def test_bulk_classification_routes_to_local(self):
        from claw.dispatcher import STATIC_ROUTING
        assert STATIC_ROUTING.get("bulk_classification") == "local"

    def test_quick_fix_still_routes_to_grok(self):
        """quick_fix remains with grok — local doesn't steal existing priors."""
        from claw.dispatcher import STATIC_ROUTING
        assert STATIC_ROUTING.get("quick_fix") == "grok"

    def test_analysis_still_routes_to_claude(self):
        """Cloud judgment tasks unchanged."""
        from claw.dispatcher import STATIC_ROUTING
        assert STATIC_ROUTING.get("analysis") == "claude"

    def test_dispatcher_routes_mining_extraction(self):
        """Full Dispatcher routes mining_extraction to local agent."""
        import asyncio
        from unittest.mock import MagicMock
        from claw.agents.local_agent import LocalAgent
        from claw.dispatcher import Dispatcher
        from claw.core.models import Task, TaskContext

        local_agent = LocalAgent(model="test")
        agents = {
            "local": local_agent,
            "claude": MagicMock(),
        }
        dispatcher = Dispatcher(agents=agents, exploration_rate=0.0)
        task = Task(project_id="p", title="t", description="d", task_type="mining_extraction")
        tc = TaskContext(task=task)
        selected = asyncio.get_event_loop().run_until_complete(dispatcher.route_task(tc))
        assert selected == "local"
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_dispatcher.py::TestLocalAgentRouting -v`
Expected: FAIL — `assert STATIC_ROUTING.get("mining_extraction") == "local"` fails (key doesn't exist)

**Step 3: Write minimal implementation**

In `src/claw/dispatcher.py`, add to `STATIC_ROUTING` dict (after line 55):

```python
    # Local — high-volume, low-judgment tasks suitable for local inference
    "mining_extraction": "local",
    "bulk_classification": "local",
    "pattern_extraction": "local",
    "code_summarization": "local",
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_dispatcher.py::TestLocalAgentRouting -v`
Expected: PASS (5 tests)

**Step 5: Run full dispatcher tests + full suite**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_dispatcher.py -v && python -m pytest --tb=short -q`
Expected: All pass

**Step 6: Commit**

```bash
git add src/claw/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: add local agent static routing for mining/classification tasks"
```

---

## Work Stream 2A: CAG Methodology Serializer

### Task 8: Create CAG serializer module

**Files:**
- Create: `src/claw/memory/cag_serializer.py`
- Create: `tests/test_cag_serializer.py`

**Step 1: Write the failing test**

```python
# tests/test_cag_serializer.py
"""Tests for CAG methodology serializer."""
from __future__ import annotations

import json

import pytest

from claw.core.models import Methodology
from claw.memory.cag_serializer import serialize_methodology, serialize_corpus


def _make_methodology(
    id: str = "m-001",
    problem: str = "How to handle retries",
    solution: str = "def retry(fn, n=3): ...",
    notes: str = "Exponential backoff recommended",
    tags: list | None = None,
    lifecycle_state: str = "viable",
    fitness_vector: dict | None = None,
    capability_data: dict | None = None,
) -> Methodology:
    return Methodology(
        id=id,
        problem_description=problem,
        solution_code=solution,
        methodology_notes=notes,
        tags=tags or ["python", "source:github.com/example/repo"],
        lifecycle_state=lifecycle_state,
        fitness_vector=fitness_vector or {"success_rate": 0.8, "retrieval_count": 5},
        capability_data=capability_data or {
            "domain": ["error-handling"],
            "inputs": [{"name": "function", "type": "callable"}],
            "outputs": [{"name": "result", "type": "any"}],
            "activation_triggers": ["retry", "resilience"],
            "composability": {"can_chain": True},
        },
    )


class TestSerializeSingleMethodology:
    def test_contains_id(self):
        m = _make_methodology(id="m-123")
        text = serialize_methodology(m)
        assert "m-123" in text

    def test_contains_problem(self):
        m = _make_methodology(problem="Handle timeout errors")
        text = serialize_methodology(m)
        assert "Handle timeout errors" in text

    def test_contains_solution(self):
        m = _make_methodology(solution="def handle_timeout(): pass")
        text = serialize_methodology(m)
        assert "def handle_timeout(): pass" in text

    def test_contains_domain(self):
        m = _make_methodology()
        text = serialize_methodology(m)
        assert "error-handling" in text

    def test_contains_lifecycle(self):
        m = _make_methodology(lifecycle_state="thriving")
        text = serialize_methodology(m)
        assert "thriving" in text

    def test_contains_fitness_score(self):
        m = _make_methodology(fitness_vector={"success_rate": 0.92})
        text = serialize_methodology(m)
        assert "0.92" in text or "0.9" in text

    def test_long_solution_truncated_with_pointer(self):
        long_code = "x = 1\n" * 500  # >2000 chars
        m = _make_methodology(solution=long_code)
        text = serialize_methodology(m, max_solution_chars=2000)
        assert len(text) < len(long_code) + 500  # much shorter than raw
        assert "[TRUNCATED" in text or "..." in text

    def test_contains_tags(self):
        m = _make_methodology(tags=["python", "retry"])
        text = serialize_methodology(m)
        assert "python" in text
        assert "retry" in text

    def test_contains_activation_triggers(self):
        m = _make_methodology()
        text = serialize_methodology(m)
        assert "retry" in text or "resilience" in text


class TestSerializeCorpus:
    def test_empty_list_returns_header_only(self):
        text = serialize_corpus([])
        assert "CAM Knowledge Base" in text or text.strip() == ""

    def test_single_methodology(self):
        m = _make_methodology(id="m-001")
        text = serialize_corpus([m])
        assert "m-001" in text

    def test_multiple_methodologies_separated(self):
        m1 = _make_methodology(id="m-001", problem="Problem A")
        m2 = _make_methodology(id="m-002", problem="Problem B")
        text = serialize_corpus([m1, m2])
        assert "m-001" in text
        assert "m-002" in text
        assert "Problem A" in text
        assert "Problem B" in text

    def test_max_count_limits_output(self):
        methods = [_make_methodology(id=f"m-{i:03d}") for i in range(100)]
        text = serialize_corpus(methods, max_count=10)
        assert "m-009" in text
        assert "m-010" not in text

    def test_sorted_by_fitness(self):
        """Higher fitness methodologies appear first."""
        m_low = _make_methodology(id="low", fitness_vector={"success_rate": 0.2})
        m_high = _make_methodology(id="high", fitness_vector={"success_rate": 0.9})
        text = serialize_corpus([m_low, m_high])
        assert text.index("high") < text.index("low")
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_cag_serializer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claw.memory.cag_serializer'`

**Step 3: Write minimal implementation**

```python
# src/claw/memory/cag_serializer.py
"""CAG Methodology Serializer.

Converts Methodology objects into a structured text format optimized for
LLM comprehension when loaded into a KV cache. Each methodology becomes
a delimited block with problem, solution, domain, and capability metadata.

Used by the CAG retriever (Phase 2) and the knowledge export pipeline (Phase 3).
"""
from __future__ import annotations

import json
from typing import Optional

from claw.core.models import Methodology


def _extract_fitness_score(m: Methodology) -> float:
    """Compute a single fitness score from the fitness_vector."""
    fv = m.fitness_vector or {}
    if not fv:
        return 0.0
    return sum(fv.values()) / len(fv)


def _extract_domain(m: Methodology) -> str:
    """Extract domain from capability_data."""
    cap = m.capability_data or {}
    if isinstance(cap, str):
        try:
            cap = json.loads(cap)
        except (json.JSONDecodeError, TypeError):
            return "unknown"
    domains = cap.get("domain", [])
    if isinstance(domains, list):
        return ", ".join(str(d) for d in domains) or "unknown"
    return str(domains)


def _extract_triggers(m: Methodology) -> str:
    """Extract activation triggers from capability_data."""
    cap = m.capability_data or {}
    if isinstance(cap, str):
        try:
            cap = json.loads(cap)
        except (json.JSONDecodeError, TypeError):
            return ""
    triggers = cap.get("activation_triggers", [])
    if isinstance(triggers, list):
        return ", ".join(str(t) for t in triggers)
    return str(triggers)


def _extract_io(m: Methodology, key: str) -> str:
    """Extract inputs or outputs from capability_data."""
    cap = m.capability_data or {}
    if isinstance(cap, str):
        try:
            cap = json.loads(cap)
        except (json.JSONDecodeError, TypeError):
            return ""
    items = cap.get(key, [])
    if isinstance(items, list):
        parts = []
        for item in items:
            if isinstance(item, dict):
                parts.append(f"{item.get('name', '?')}:{item.get('type', '?')}")
            else:
                parts.append(str(item))
        return ", ".join(parts)
    return str(items)


def serialize_methodology(
    m: Methodology,
    max_solution_chars: int = 2000,
) -> str:
    """Serialize a single Methodology into a structured text block."""
    fitness = _extract_fitness_score(m)
    domain = _extract_domain(m)
    triggers = _extract_triggers(m)
    inputs = _extract_io(m, "inputs")
    outputs = _extract_io(m, "outputs")
    tags = ", ".join(m.tags) if m.tags else ""

    solution = m.solution_code or ""
    if len(solution) > max_solution_chars:
        solution = solution[:max_solution_chars] + f"\n[TRUNCATED — full: methodology#{m.id}]"

    lines = [
        f"=== METHODOLOGY {m.id} ===",
        f"DOMAIN: {domain} | TAGS: {tags} | LIFECYCLE: {m.lifecycle_state} | FITNESS: {fitness:.2f}",
        f"PROBLEM: {m.problem_description}",
        f"SOLUTION:\n{solution}",
    ]

    if m.methodology_notes:
        lines.append(f"NOTES: {m.methodology_notes}")

    if inputs or outputs:
        lines.append(f"IO: inputs=[{inputs}] outputs=[{outputs}]")

    if triggers:
        lines.append(f"TRIGGERS: {triggers}")

    lines.append("===")
    return "\n".join(lines)


def serialize_corpus(
    methodologies: list[Methodology],
    max_count: int = 0,
    max_solution_chars: int = 2000,
) -> str:
    """Serialize a list of methodologies into a full corpus document.

    Methodologies are sorted by fitness (highest first). If max_count > 0,
    only the top-N are included.
    """
    if not methodologies:
        return "# CAM Knowledge Base\nEmpty corpus.\n"

    # Sort by fitness descending
    sorted_methods = sorted(
        methodologies,
        key=lambda m: _extract_fitness_score(m),
        reverse=True,
    )

    if max_count > 0:
        sorted_methods = sorted_methods[:max_count]

    header = (
        f"# CAM Knowledge Base\n"
        f"# Total methodologies: {len(sorted_methods)}\n"
        f"# Format: structured blocks for LLM context injection\n\n"
    )

    blocks = [serialize_methodology(m, max_solution_chars) for m in sorted_methods]
    return header + "\n\n".join(blocks) + "\n"
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_cag_serializer.py -v`
Expected: PASS (14 tests)

**Step 5: Run full test suite**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest --tb=short -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/claw/memory/cag_serializer.py tests/test_cag_serializer.py
git commit -m "feat: add CAG methodology serializer for KV-cache corpus generation"
```

---

### Task 9: Add CAGConfig to config.py and ClawConfig

**Files:**
- Modify: `src/claw/core/config.py`
- Modify: `tests/test_local_config.py`

**Step 1: Write the failing test**

Add to `tests/test_local_config.py`:

```python
class TestCAGConfig:
    def test_default_disabled(self):
        from claw.core.config import CAGConfig
        cfg = CAGConfig()
        assert cfg.enabled is False

    def test_default_cache_dir(self):
        from claw.core.config import CAGConfig
        cfg = CAGConfig()
        assert cfg.cache_dir == "data/cag_caches"

    def test_default_max_methodologies(self):
        from claw.core.config import CAGConfig
        cfg = CAGConfig()
        assert cfg.max_methodologies_per_cache == 2000

    def test_custom_values(self):
        from claw.core.config import CAGConfig
        cfg = CAGConfig(enabled=True, max_methodologies_per_cache=500)
        assert cfg.enabled is True
        assert cfg.max_methodologies_per_cache == 500

    def test_cag_on_clawconfig(self):
        from claw.core.config import ClawConfig, CAGConfig
        cc = ClawConfig()
        assert isinstance(cc.cag, CAGConfig)
        assert cc.cag.enabled is False
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_local_config.py::TestCAGConfig -v`
Expected: FAIL — `ImportError: cannot import name 'CAGConfig'`

**Step 3: Write minimal implementation**

In `src/claw/core/config.py`, add after `DeepConfConfig` (around line 276):

```python
class CAGConfig(BaseModel):
    """Cache-Augmented Generation configuration."""
    enabled: bool = False
    cache_dir: str = "data/cag_caches"
    auto_rebuild_on_stale: bool = False
    max_methodologies_per_cache: int = 2000
    serialization_format: str = "structured_text"
    max_solution_chars: int = 2000
```

In `ClawConfig` (around line 392), add field:

```python
    cag: CAGConfig = Field(default_factory=CAGConfig)
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest tests/test_local_config.py::TestCAGConfig -v`
Expected: PASS (5 tests)

**Step 5: Run full test suite**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest --tb=short -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/claw/core/config.py tests/test_local_config.py
git commit -m "feat: add CAGConfig for KV-cache retrieval layer configuration"
```

---

## Integration: claw.toml example config

### Task 10: Add local agent and CAG config sections to claw.toml

**Files:**
- Modify: `claw.toml`

**Step 1: Add config sections**

After the existing `[agents.grok]` block, add:

```toml
# ---------------------------------------------------------------------------
# Local LLM Agent — local inference via Atomic-Chat, mlx-server, or Ollama
# ---------------------------------------------------------------------------
# Dedicated agent slot for local inference on Apple Silicon (MLX) or CPU.
# Uses OpenAI-compatible /v1/chat/completions endpoint.
# To activate: set enabled = true, configure model and local_base_url.
#
# Atomic-Chat: http://localhost:1337/v1
# MLX-LM:     http://localhost:8080/v1
# Ollama:     http://localhost:11434/v1

[agents.local]
enabled = false
mode = "local"
model = ""  # e.g. "mlx-community/Qwen2.5-7B-Instruct-4bit"
local_base_url = "http://localhost:1337/v1"
max_concurrent = 1
timeout = 300
max_budget_usd = 0.0
max_tokens = 16384
```

After the `[deep_conf]` section, add:

```toml
# ---------------------------------------------------------------------------
# CAG — Cache-Augmented Generation (vectorless retrieval via KV cache)
# ---------------------------------------------------------------------------
# Precomputes methodology corpus into TurboQuant-compressed KV cache.
# When enabled, the CAG retriever loads cached context for instant,
# perfectly-grounded retrieval — no vector search, no embedding noise.
# Requires a local backend with /slots/ API (Phase 2).

[cag]
enabled = false
cache_dir = "data/cag_caches"
auto_rebuild_on_stale = false
max_methodologies_per_cache = 2000
serialization_format = "structured_text"
max_solution_chars = 2000
```

**Step 2: Verify config loads cleanly**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -c "from claw.core.config import load_config; c = load_config(); print(f'agents: {list(c.agents.keys())}'); print(f'cag enabled: {c.cag.enabled}')"`
Expected: `agents: ['claude', 'codex', 'gemini', 'grok', 'local']` and `cag enabled: False`

**Step 3: Commit**

```bash
git add claw.toml
git commit -m "feat: add [agents.local] and [cag] config sections to claw.toml"
```

---

## Final Validation

### Task 11: Run full test suite and verify no regressions

**Step 1: Full pytest run**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -m pytest --tb=short -q`
Expected: All 2624+ tests pass, plus the ~30 new tests from this plan

**Step 2: Verify local agent creation**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -c "
from claw.core.config import load_config
from claw.core.factory import _create_agent
c = load_config()
if 'local' in c.agents:
    agent = _create_agent('local', c.agents['local'])
    print(f'Agent: {agent.agent_id}, mode: {agent.mode}, model: {agent.model}')
else:
    print('local agent not in config')
"`
Expected: `Agent: local, mode: AgentMode.LOCAL, model: ` (empty model since config has model = "")

**Step 3: Verify CAG serializer**

Run: `cd /Volumes/WS4TB/a_aSatzClaw/multiclaw && python -c "
from claw.core.models import Methodology
from claw.memory.cag_serializer import serialize_methodology, serialize_corpus
m = Methodology(problem_description='Handle retries', solution_code='def retry(): pass')
print(serialize_methodology(m)[:200])
print('---')
print(f'Corpus length for 1 method: {len(serialize_corpus([m]))} chars')
"`
Expected: Prints serialized methodology block and corpus length

**Step 4: Final commit message**

All tasks complete. The following files were created or modified:

```
Created:
  src/claw/agents/local_agent.py          (Task 1)
  src/claw/memory/cag_serializer.py       (Task 8)
  tests/test_local_agent.py               (Task 1)
  tests/test_local_config.py              (Tasks 3, 9)
  tests/test_cag_serializer.py            (Task 8)

Modified:
  src/claw/core/factory.py                (Task 2)
  src/claw/core/config.py                 (Tasks 3, 5, 9)
  src/claw/evolution/kelly.py             (Task 5)
  src/claw/dispatcher.py                  (Task 7)
  tests/test_local_mode.py                (Tasks 2, 4)
  tests/test_kelly.py                     (Task 5)
  tests/test_dispatcher.py                (Task 7)
  tests/test_embeddings.py                (Task 6)
  claw.toml                               (Task 10)
```

---

## Dependency Graph

```
Task 1 (LocalAgent class)
    └── Task 2 (register in factory) ──┐
Task 3 (LocalLLMConfig)                │
Task 5 (Kelly recalibration)           ├── Task 10 (claw.toml) ── Task 11 (final validation)
Task 6 (MLX embedding verify)          │
Task 7 (routing priors)          ──────┘
Task 8 (CAG serializer)
Task 9 (CAGConfig)               ──────┘
```

**Parallel execution**: Tasks 1, 3, 5, 6, 7, 8, 9 can all start simultaneously.
Task 2 depends on Task 1. Task 10 depends on Tasks 2, 3, 9. Task 11 depends on all.
