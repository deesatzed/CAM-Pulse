"""Tests for KV Cache Manager — prefix-based caching for local LLM inference.

Validates that the KVCacheManager correctly builds stable system messages,
tracks cache hit metrics, and integrates with the agent interface.

All tests use REAL objects — no mocks, no placeholders.
"""
from __future__ import annotations

import pytest

from claw.memory.kv_cache_manager import KVCacheManager, KVCacheStats, KV_COMPRESSION_RATIOS
from claw.agents.interface import AgentInterface
from claw.agents.claude import ClaudeCodeAgent
from claw.core.models import AgentMode, Task, TaskContext
from claw.core.config import LocalLLMConfig, CAGConfig, ClawConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_context(task_type: str, title: str = "test task", description: str = "test description") -> TaskContext:
    task = Task(
        project_id="test-project",
        title=title,
        description=description,
        task_type=task_type,
    )
    return TaskContext(task=task)


def _make_agent() -> ClaudeCodeAgent:
    return ClaudeCodeAgent(mode=AgentMode.CLI)


# ---------------------------------------------------------------------------
# Test: KVCacheManager initialization
# ---------------------------------------------------------------------------

class TestKVCacheManagerInit:
    def test_default_init(self):
        mgr = KVCacheManager()
        assert mgr.keep_alive == -1
        assert mgr.kv_cache_quantization == "q8_0"
        assert mgr.provider == "ollama"
        assert mgr.compression_ratio == 2.0
        assert mgr.system_message == ""

    def test_custom_init(self):
        mgr = KVCacheManager(keep_alive=3600, kv_cache_quantization="q4_0")
        assert mgr.keep_alive == 3600
        assert mgr.kv_cache_quantization == "q4_0"
        assert mgr.compression_ratio == 4.0

    def test_turboq_init(self):
        mgr = KVCacheManager(provider="turboq", kv_cache_quantization="turbo3")
        assert mgr.provider == "turboq"
        assert mgr.kv_cache_quantization == "turbo3"
        assert mgr.compression_ratio == 4.9

    def test_turbo4_init(self):
        mgr = KVCacheManager(provider="turboq", kv_cache_quantization="turbo4")
        assert mgr.compression_ratio == 6.0

    def test_f16_init(self):
        mgr = KVCacheManager(kv_cache_quantization="f16")
        assert mgr.compression_ratio == 1.0

    def test_unknown_quant_defaults_to_1x(self):
        mgr = KVCacheManager(kv_cache_quantization="unknown_type")
        assert mgr.compression_ratio == 1.0


# ---------------------------------------------------------------------------
# Test: build_system_message
# ---------------------------------------------------------------------------

class TestBuildSystemMessage:
    def test_builds_stable_message(self):
        mgr = KVCacheManager()
        corpus = "=== METHODOLOGY m1 ===\nPROBLEM: test\n==="
        result = mgr.build_system_message(corpus, knowledge_budget=10000)

        assert "KNOWLEDGE BASE START" in result
        assert "KNOWLEDGE BASE END" in result
        assert "METHODOLOGY m1" in result
        assert result == mgr.system_message

    def test_message_is_deterministic(self):
        """Same corpus + budget must produce byte-identical message."""
        corpus = "Pattern Alpha\nPattern Beta\nPattern Gamma"
        mgr1 = KVCacheManager()
        mgr2 = KVCacheManager()
        msg1 = mgr1.build_system_message(corpus, 5000)
        msg2 = mgr2.build_system_message(corpus, 5000)
        assert msg1 == msg2

    def test_respects_knowledge_budget(self):
        corpus = "X" * 50000
        mgr = KVCacheManager()
        mgr.build_system_message(corpus, knowledge_budget=1000)

        # The corpus portion should be truncated to budget
        x_count = mgr.system_message.count("X")
        assert x_count == 1000

    def test_updates_stats(self):
        mgr = KVCacheManager()
        corpus = "A" * 2000
        mgr.build_system_message(corpus, knowledge_budget=2000)

        status = mgr.get_status()
        assert status["corpus_chars"] == 2000
        assert status["corpus_tokens_approx"] == 500
        assert status["corpus_hash"] != ""

    def test_no_dynamic_content(self):
        """System message must NOT contain timestamps or request IDs."""
        mgr = KVCacheManager()
        msg = mgr.build_system_message("test corpus", 1000)
        # No datetime, no uuid, no request ID patterns
        assert "202" not in msg  # No year-like patterns
        assert "uuid" not in msg.lower()


# ---------------------------------------------------------------------------
# Test: record_request and cache hit estimation
# ---------------------------------------------------------------------------

class TestRecordRequest:
    def test_first_request_is_cold(self):
        mgr = KVCacheManager()
        mgr.build_system_message("corpus", 1000)
        mgr.record_request(prompt_tokens=5000, eval_tokens=200)

        status = mgr.get_status()
        assert status["requests_sent"] == 1
        assert status["cache_hits_estimated"] == 0

    def test_second_request_with_low_tokens_is_cache_hit(self):
        mgr = KVCacheManager()
        mgr.build_system_message("corpus", 1000)

        # First request: cold, 5000 prompt tokens (includes corpus)
        mgr.record_request(prompt_tokens=5000, eval_tokens=200)

        # Second request: warm, only 500 prompt tokens (corpus cached)
        mgr.record_request(prompt_tokens=500, eval_tokens=200)

        status = mgr.get_status()
        assert status["requests_sent"] == 2
        assert status["cache_hits_estimated"] == 1
        assert status["hit_rate"] == 1.0

    def test_second_request_with_same_tokens_is_miss(self):
        mgr = KVCacheManager()
        mgr.build_system_message("corpus", 1000)

        mgr.record_request(prompt_tokens=5000, eval_tokens=200)
        # Same prompt_tokens = cache miss (re-processed the corpus)
        mgr.record_request(prompt_tokens=5000, eval_tokens=200)

        status = mgr.get_status()
        assert status["cache_hits_estimated"] == 0

    def test_hit_rate_multiple_requests(self):
        mgr = KVCacheManager()
        mgr.build_system_message("corpus", 1000)

        mgr.record_request(prompt_tokens=5000, eval_tokens=200)  # cold
        mgr.record_request(prompt_tokens=400, eval_tokens=200)   # hit
        mgr.record_request(prompt_tokens=500, eval_tokens=300)   # hit
        mgr.record_request(prompt_tokens=4800, eval_tokens=200)  # miss

        status = mgr.get_status()
        assert status["requests_sent"] == 4
        assert status["cache_hits_estimated"] == 2
        # hit_rate = 2 / (4-1) = 0.667
        assert 0.6 < status["hit_rate"] < 0.7

    def test_total_tokens_tracked(self):
        mgr = KVCacheManager()
        mgr.build_system_message("corpus", 1000)

        mgr.record_request(prompt_tokens=1000, eval_tokens=200)
        mgr.record_request(prompt_tokens=500, eval_tokens=300)

        status = mgr.get_status()
        assert status["total_prompt_tokens"] == 1500
        assert status["total_eval_tokens"] == 500


# ---------------------------------------------------------------------------
# Test: get_status
# ---------------------------------------------------------------------------

class TestGetStatus:
    def test_initial_status(self):
        mgr = KVCacheManager(keep_alive=-1, kv_cache_quantization="q4_0")
        status = mgr.get_status()

        assert status["keep_alive"] == -1
        assert status["kv_cache_quantization"] == "q4_0"
        assert status["provider"] == "ollama"
        assert status["compression_ratio"] == 4.0
        assert status["requests_sent"] == 0
        assert status["system_message_chars"] == 0

    def test_status_after_build(self):
        mgr = KVCacheManager()
        mgr.build_system_message("test corpus data", 5000)
        status = mgr.get_status()

        assert status["system_message_chars"] > 0
        assert status["corpus_chars"] == len("test corpus data")

    def test_turboq_status(self):
        mgr = KVCacheManager(provider="turboq", kv_cache_quantization="turbo3")
        mgr.build_system_message("turboq corpus", 5000)
        status = mgr.get_status()

        assert status["provider"] == "turboq"
        assert status["kv_cache_quantization"] == "turbo3"
        assert status["compression_ratio"] == 4.9
        assert status["system_message_chars"] > 0


# ---------------------------------------------------------------------------
# Test: AgentInterface integration
# ---------------------------------------------------------------------------

class TestAgentKVCacheIntegration:
    def test_set_kv_cache_manager(self):
        agent = _make_agent()
        mgr = KVCacheManager()
        agent.set_kv_cache_manager(mgr)
        assert agent._kv_cache_manager is mgr

    def test_kv_cache_manager_default_none(self):
        agent = _make_agent()
        assert agent._kv_cache_manager is None

    def test_skip_cag_in_prompt(self):
        """When skip_cag=True, CAG corpus should NOT appear in prompt."""
        agent = _make_agent()
        agent.set_cag_corpus("=== SHOULD NOT APPEAR IN PROMPT ===")

        ctx = _make_task_context("mining_extraction")
        prompt = agent._build_openrouter_prompt(ctx, skip_cag=True)

        assert "SHOULD NOT APPEAR IN PROMPT" not in prompt
        assert "CAG: full methodology corpus" not in prompt

    def test_skip_cag_false_still_injects(self):
        """When skip_cag=False (default), CAG corpus should appear."""
        agent = _make_agent()
        agent.set_cag_corpus("=== VISIBLE CORPUS ===")

        ctx = _make_task_context("mining_extraction")
        prompt = agent._build_openrouter_prompt(ctx, skip_cag=False)

        assert "VISIBLE CORPUS" in prompt

    def test_skip_cag_non_eligible_still_none(self):
        """Non-eligible tasks should not get CAG regardless of skip_cag."""
        agent = _make_agent()
        agent.set_cag_corpus("corpus data")

        ctx = _make_task_context("debugging")
        prompt_skip = agent._build_openrouter_prompt(ctx, skip_cag=True)
        prompt_normal = agent._build_openrouter_prompt(ctx, skip_cag=False)

        assert "corpus data" not in prompt_skip
        assert "corpus data" not in prompt_normal


# ---------------------------------------------------------------------------
# Test: LocalLLMConfig KV cache fields
# ---------------------------------------------------------------------------

class TestLocalLLMConfigKVFields:
    def test_default_keep_alive(self):
        cfg = LocalLLMConfig()
        assert cfg.keep_alive == -1

    def test_default_kv_cache_quantization(self):
        cfg = LocalLLMConfig()
        assert cfg.kv_cache_quantization == "q8_0"

    def test_custom_values(self):
        cfg = LocalLLMConfig(keep_alive=3600, kv_cache_quantization="q4_0")
        assert cfg.keep_alive == 3600
        assert cfg.kv_cache_quantization == "q4_0"

    def test_local_llm_in_claw_config(self):
        """ClawConfig should have local_llm field."""
        cfg = ClawConfig()
        assert hasattr(cfg, "local_llm")
        assert isinstance(cfg.local_llm, LocalLLMConfig)

    def test_turboq_provider_config(self):
        """LocalLLMConfig should accept turboq provider with turbo3 quant."""
        cfg = LocalLLMConfig(
            provider="turboq",
            kv_cache_quantization="turbo3",
            turboq_binary="llama-server-turboq",
        )
        assert cfg.provider == "turboq"
        assert cfg.kv_cache_quantization == "turbo3"
        assert cfg.turboq_binary == "llama-server-turboq"

    def test_turboq_binary_default(self):
        cfg = LocalLLMConfig()
        assert cfg.turboq_binary == "llama-server-turboq"

    def test_turbo4_quant_config(self):
        cfg = LocalLLMConfig(kv_cache_quantization="turbo4")
        assert cfg.kv_cache_quantization == "turbo4"


# ---------------------------------------------------------------------------
# Test: KVCacheStats
# ---------------------------------------------------------------------------

class TestKVCacheStats:
    def test_hit_rate_zero_requests(self):
        stats = KVCacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate_one_request(self):
        stats = KVCacheStats(requests_sent=1)
        assert stats.hit_rate == 0.0

    def test_hit_rate_with_hits(self):
        stats = KVCacheStats(requests_sent=5, cache_hits_estimated=3)
        # hit_rate = 3 / (5-1) = 0.75
        assert stats.hit_rate == 0.75


# ---------------------------------------------------------------------------
# Test: KV_COMPRESSION_RATIOS constant
# ---------------------------------------------------------------------------

class TestKVCompressionRatios:
    def test_f16_baseline(self):
        assert KV_COMPRESSION_RATIOS["f16"] == 1.0

    def test_q8_0_ratio(self):
        assert KV_COMPRESSION_RATIOS["q8_0"] == 2.0

    def test_q4_0_ratio(self):
        assert KV_COMPRESSION_RATIOS["q4_0"] == 4.0

    def test_turbo3_ratio(self):
        """TurboQuant turbo3: ~4.9x compression, near-zero quality loss."""
        assert KV_COMPRESSION_RATIOS["turbo3"] == 4.9

    def test_turbo4_ratio(self):
        """TurboQuant turbo4: ~6x compression, near-zero quality loss."""
        assert KV_COMPRESSION_RATIOS["turbo4"] == 6.0

    def test_turbo3_beats_ollama_q8(self):
        """TurboQuant turbo3 provides 2.45x better compression than Ollama q8_0."""
        assert KV_COMPRESSION_RATIOS["turbo3"] / KV_COMPRESSION_RATIOS["q8_0"] > 2.0

    def test_turbo3_beats_ollama_q4(self):
        """TurboQuant turbo3 provides better compression than q4_0 with less quality loss."""
        assert KV_COMPRESSION_RATIOS["turbo3"] > KV_COMPRESSION_RATIOS["q4_0"]
