"""KV Cache Manager for local LLM inference.

Manages KV cache state for local inference backends. Supports two tiers:

**Tier 1 (Recommended): TurboQuant via turboq / llama-server-turboq**
    - TheTom/llama-cpp-turboquant fork with Metal M4 support
    - --cache-type-k turbo3 --cache-type-v turbo3 (server-side flag)
    - ~4.9x KV cache compression with near-zero quality loss
    - Ollama-compatible API on port 11434

**Tier 2: Ollama 0.19 native prefix caching**
    - MLX runner auto-caches KV state for byte-identical system message prefixes
    - q8_0 = 2x compression, q4_0 = 4x compression (with quality loss)
    - Simpler setup, but 2.5x less compression than TurboQuant turbo3

Architecture (both tiers):
    1. CAG corpus is pre-formatted into a stable system message at startup
    2. The system message is byte-identical across all requests for a given
       corpus version, enabling prefix cache hits
    3. Task-specific content goes in the user message (variable per request)
    4. keep_alive=-1 prevents model/cache eviction between requests

For Atomic Chat (llama.cpp backend), explicit /slots/0/save and /slots/0/restore
endpoints are available as an alternative strategy.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("claw.memory.kv_cache_manager")


# Compression ratios for KV cache quantization types (vs f16 baseline).
# Source: TurboQuant paper (Google, March 2026) + TheTom community benchmarks.
KV_COMPRESSION_RATIOS: dict[str, float] = {
    "f16": 1.0,
    "q8_0": 2.0,
    "q4_0": 4.0,
    "turbo3": 4.9,   # ~3.25 bits per value, near-zero quality loss
    "turbo4": 6.0,   # ~2.67 bits per value, near-zero quality loss
}


@dataclass
class KVCacheStats:
    """Tracks KV cache hit/miss metrics for monitoring."""
    corpus_hash: str = ""
    corpus_chars: int = 0
    corpus_tokens_approx: int = 0
    requests_sent: int = 0
    cache_hits_estimated: int = 0
    total_prompt_tokens: int = 0
    total_eval_tokens: int = 0
    last_prompt_tokens: int = 0
    first_request_at: Optional[float] = None
    last_request_at: Optional[float] = None

    @property
    def hit_rate(self) -> float:
        """Estimated cache hit rate (0.0–1.0)."""
        if self.requests_sent <= 1:
            return 0.0
        return self.cache_hits_estimated / max(1, self.requests_sent - 1)


class KVCacheManager:
    """Manages KV cache state for prefix-based caching.

    Supports two backend tiers:
    - **TurboQuant** (turboq): Server-side --cache-type-k turbo3 enables ~4.9x
      KV compression with near-zero quality loss. Ollama-compatible API.
    - **Ollama 0.19**: MLX runner auto-caches KV state for byte-identical
      system message prefixes. q8_0 = 2x, q4_0 = 4x compression.

    Both tiers use the same prefix-caching strategy: a stable system message
    containing the CAG corpus is byte-identical across requests, allowing the
    backend to reuse cached KV state.
    """

    def __init__(
        self,
        keep_alive: int = -1,
        kv_cache_quantization: str = "q8_0",
        provider: str = "ollama",
    ):
        """Initialize KV cache manager.

        Args:
            keep_alive: Keep-alive parameter in seconds.
                -1 = never unload (recommended for CAG).
                0 = unload immediately after request.
            kv_cache_quantization: KV cache quantization type.
                "f16"    = full precision (1x, baseline).
                "q8_0"   = 8-bit (2x compression, Ollama default).
                "q4_0"   = 4-bit (4x compression, quality loss).
                "turbo3" = TurboQuant 3.25-bit (~4.9x, near-lossless).
                "turbo4" = TurboQuant 4-bit variant (~6x, near-lossless).
            provider: Backend provider ("ollama", "turboq", "llama-cpp", etc.).
        """
        self._keep_alive = keep_alive
        self._kv_cache_quantization = kv_cache_quantization
        self._provider = provider
        self._compression_ratio = KV_COMPRESSION_RATIOS.get(kv_cache_quantization, 1.0)
        self._system_message: str = ""
        self._corpus_hash: str = ""
        self._stats = KVCacheStats()

    def build_system_message(
        self, corpus: str, knowledge_budget: int, brain_topology: str = "",
    ) -> str:
        """Build a stable system message from the CAG corpus.

        The system message is designed to be byte-identical across requests
        so that Ollama's prefix cache hits on every subsequent request.
        Do NOT include any dynamic content (timestamps, request IDs, etc.)
        in this message.

        Args:
            corpus: The serialized CAG methodology corpus text.
            knowledge_budget: Max chars of corpus to include.
            brain_topology: Deterministic brain topology summary text.
                When provided, inserted between preamble and corpus.

        Returns:
            The formatted system message string.
        """
        truncated = corpus[:knowledge_budget] if len(corpus) > knowledge_budget else corpus
        # Hash includes topology so cache invalidates when brain topology changes
        hash_input = (brain_topology + truncated) if brain_topology else truncated
        corpus_hash = hashlib.md5(hash_input.encode()).hexdigest()[:12]

        topology_section = ""
        if brain_topology:
            topology_section = (
                "\n=== BRAIN TOPOLOGY ===\n"
                f"{brain_topology}\n"
                "=== END BRAIN TOPOLOGY ===\n"
            )

        self._system_message = (
            "You are a knowledge-grounded AI agent. Below is your complete "
            "methodology knowledge base. Use these patterns as authoritative "
            "guidance for all tasks. Do not hallucinate beyond this knowledge.\n"
            f"{topology_section}\n"
            "=== KNOWLEDGE BASE START ===\n"
            f"{truncated}\n"
            "=== KNOWLEDGE BASE END ==="
        )
        self._corpus_hash = corpus_hash
        self._stats.corpus_hash = corpus_hash
        self._stats.corpus_chars = len(truncated)
        self._stats.corpus_tokens_approx = len(truncated) // 4

        logger.info(
            "KV cache system message built: %d chars (~%d tokens), hash=%s, "
            "provider=%s, quant=%s (%.1fx compression)",
            len(truncated), len(truncated) // 4, corpus_hash,
            self._provider, self._kv_cache_quantization, self._compression_ratio,
        )

        return self._system_message

    @property
    def system_message(self) -> str:
        """The current stable system message for KV cache reuse."""
        return self._system_message

    @property
    def keep_alive(self) -> int:
        """Ollama keep_alive parameter value."""
        return self._keep_alive

    @property
    def kv_cache_quantization(self) -> str:
        """KV cache quantization type."""
        return self._kv_cache_quantization

    @property
    def provider(self) -> str:
        """Backend provider name."""
        return self._provider

    @property
    def compression_ratio(self) -> float:
        """Estimated KV cache compression ratio vs f16 baseline."""
        return self._compression_ratio

    def record_request(self, prompt_tokens: int, eval_tokens: int) -> None:
        """Record metrics from a completed request.

        Estimates cache hit by checking if prompt_tokens is close to the
        expected value for just the user message (cache hit) vs the full
        system+user prompt (cache miss).

        Args:
            prompt_tokens: Prompt tokens reported by the API.
            eval_tokens: Completion/eval tokens reported by the API.
        """
        now = time.monotonic()
        self._stats.requests_sent += 1
        self._stats.total_prompt_tokens += prompt_tokens
        self._stats.total_eval_tokens += eval_tokens
        self._stats.last_request_at = now

        if self._stats.first_request_at is None:
            self._stats.first_request_at = now
            self._stats.last_prompt_tokens = prompt_tokens
            logger.info(
                "First request (cold cache): %d prompt tokens, %d eval tokens",
                prompt_tokens, eval_tokens,
            )
        else:
            # Estimate cache hit: if prompt_tokens is significantly lower
            # than the first request, the prefix was cached
            first_tokens = self._stats.last_prompt_tokens
            if prompt_tokens < first_tokens * 0.8:
                self._stats.cache_hits_estimated += 1
                logger.debug(
                    "Cache hit estimated: %d prompt tokens (first was %d)",
                    prompt_tokens, first_tokens,
                )

    def get_status(self) -> dict:
        """Return cache status for reporting."""
        return {
            "corpus_hash": self._stats.corpus_hash,
            "corpus_chars": self._stats.corpus_chars,
            "corpus_tokens_approx": self._stats.corpus_tokens_approx,
            "requests_sent": self._stats.requests_sent,
            "cache_hits_estimated": self._stats.cache_hits_estimated,
            "hit_rate": round(self._stats.hit_rate, 3),
            "total_prompt_tokens": self._stats.total_prompt_tokens,
            "total_eval_tokens": self._stats.total_eval_tokens,
            "keep_alive": self._keep_alive,
            "kv_cache_quantization": self._kv_cache_quantization,
            "provider": self._provider,
            "compression_ratio": self._compression_ratio,
            "system_message_chars": len(self._system_message),
        }
