"""Injection utilities — prepend CAG corpus into LLM prompt messages.

Provides two functions:

- ``inject_into_messages()`` — mutate an OpenAI-style message list in place
- ``build_system_message()`` — return a stable system string for local LLM
  KV prefix caching

Zero external dependencies: only uses Python builtins.
"""
from __future__ import annotations

from cag_core.cache import DEFAULT_KNOWLEDGE_BUDGET


def inject_into_messages(
    corpus: str,
    messages: list,
    knowledge_budget: int = DEFAULT_KNOWLEDGE_BUDGET,
) -> None:
    """Inject the CAG corpus into an OpenAI-style message list (in place).

    If the first message is a system message, the corpus is appended to it.
    Otherwise a new system message is inserted at position 0.

    Parameters
    ----------
    corpus : str
        The full corpus text from ``CAGCache.get_corpus()``.
    messages : list[dict]
        OpenAI-style ``[{"role": "...", "content": "..."}, ...]``.
        Modified in place.
    knowledge_budget : int
        Maximum characters of corpus to inject.  Defaults to 16000.
    """
    if not corpus:
        return

    truncated = corpus[:knowledge_budget]
    kb_block = (
        "\n## Knowledge Base\n"
        "The following is your pre-loaded knowledge corpus. "
        "Use these patterns as guidance for your implementation "
        "where applicable.\n\n"
        + truncated
        + "\n\n--- END KNOWLEDGE BASE ---"
    )

    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = messages[0].get("content", "") + kb_block
    else:
        messages.insert(0, {"role": "system", "content": kb_block})


def build_system_message(
    corpus: str,
    knowledge_budget: int = DEFAULT_KNOWLEDGE_BUDGET,
) -> str:
    """Build a stable system message for local LLM KV prefix caching.

    The returned string should be used as the ``system`` role message.
    Because it starts with a fixed preamble and the corpus rarely changes,
    local LLM servers (Ollama, llama.cpp, TurboQuant) can cache the KV
    state for this prefix and skip re-computation on subsequent requests.

    Parameters
    ----------
    corpus : str
        The full corpus text.
    knowledge_budget : int
        Maximum characters of corpus to include.  Defaults to 16000.

    Returns
    -------
    str
        A complete system message string.
    """
    truncated = corpus[:knowledge_budget] if len(corpus) > knowledge_budget else corpus
    return (
        "You are a knowledge-grounded AI agent. Below is your complete "
        "knowledge base. Use these patterns as authoritative guidance "
        "for all tasks. Do not hallucinate beyond this knowledge.\n\n"
        "=== KNOWLEDGE BASE START ===\n"
        + truncated
        + "\n=== KNOWLEDGE BASE END ==="
    )
