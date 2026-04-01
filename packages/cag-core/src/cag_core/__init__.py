"""cag-core — Standalone Cache-Augmented Generation runtime.

Load and inject pre-built knowledge corpora into LLM prompts.
Zero external dependencies required (stdlib only).

Exported by CAM-Pulse (https://github.com/deesatzed/CAM-Pulse).

Usage::

    from cag_core import CAGCache, inject_into_messages, build_system_message

    cache = CAGCache(cache_dir="./my_corpus")
    cache.load()
    corpus = cache.get_corpus()

    # Inject into OpenAI-style messages
    messages = [{"role": "user", "content": "How do I ...?"}]
    inject_into_messages(corpus, messages)

    # Or build a stable system message for local LLM KV caching
    sys_msg = build_system_message(corpus)
"""
from __future__ import annotations

from cag_core.cache import CAGCache
from cag_core.injection import build_system_message, inject_into_messages

__version__ = "0.1.0"

__all__ = [
    "CAGCache",
    "build_system_message",
    "inject_into_messages",
    "__version__",
]
