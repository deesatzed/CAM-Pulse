"""Tests for cag_core.injection — inject_into_messages and build_system_message."""
from __future__ import annotations

import pytest

from cag_core.injection import build_system_message, inject_into_messages


# ---------------------------------------------------------------------------
# inject_into_messages
# ---------------------------------------------------------------------------


class TestInjectIntoMessages:
    def test_adds_to_existing_system_message(self):
        messages = [{"role": "system", "content": "You are helpful."}]
        inject_into_messages("knowledge here", messages)

        assert "knowledge here" in messages[0]["content"]
        assert "You are helpful." in messages[0]["content"]
        assert "--- END KNOWLEDGE BASE ---" in messages[0]["content"]

    def test_creates_system_message_when_none_exists(self):
        messages = [{"role": "user", "content": "Hello"}]
        inject_into_messages("knowledge here", messages)

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "knowledge here" in messages[0]["content"]
        assert messages[1]["role"] == "user"

    def test_respects_budget(self):
        corpus = "A" * 50000
        messages = [{"role": "user", "content": "Hi"}]
        inject_into_messages(corpus, messages, knowledge_budget=100)

        system_content = messages[0]["content"]
        # The truncated corpus should be 100 chars, not 50000
        assert "A" * 100 in system_content
        assert "A" * 50000 not in system_content

    def test_empty_corpus_noop(self):
        messages = [{"role": "user", "content": "Hi"}]
        inject_into_messages("", messages)
        assert len(messages) == 1

    def test_knowledge_base_delimiters(self):
        messages = [{"role": "user", "content": "Hi"}]
        inject_into_messages("test corpus", messages)

        content = messages[0]["content"]
        assert "## Knowledge Base" in content
        assert "--- END KNOWLEDGE BASE ---" in content

    def test_preserves_existing_system_content(self):
        messages = [{"role": "system", "content": "Original instructions."}]
        inject_into_messages("new knowledge", messages)

        assert messages[0]["content"].startswith("Original instructions.")
        assert "new knowledge" in messages[0]["content"]

    def test_handles_empty_message_list(self):
        messages = []
        inject_into_messages("some corpus", messages)

        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert "some corpus" in messages[0]["content"]

    def test_handles_system_message_with_empty_content(self):
        messages = [{"role": "system", "content": ""}]
        inject_into_messages("corpus text", messages)

        assert "corpus text" in messages[0]["content"]
        assert messages[0]["role"] == "system"

    def test_handles_system_message_with_missing_content_key(self):
        messages = [{"role": "system"}]
        inject_into_messages("corpus text", messages)

        assert "corpus text" in messages[0]["content"]

    def test_multiple_user_messages_preserved(self):
        messages = [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Response"},
            {"role": "user", "content": "Second"},
        ]
        inject_into_messages("corpus", messages)

        assert len(messages) == 4
        assert messages[0]["role"] == "system"
        assert messages[1]["content"] == "First"
        assert messages[2]["content"] == "Response"
        assert messages[3]["content"] == "Second"

    def test_budget_zero_still_adds_delimiters(self):
        messages = [{"role": "user", "content": "Hi"}]
        inject_into_messages("some corpus", messages, knowledge_budget=0)

        content = messages[0]["content"]
        assert "## Knowledge Base" in content
        assert "--- END KNOWLEDGE BASE ---" in content
        # But no actual corpus content
        assert "some corpus" not in content

    def test_exact_budget_no_truncation(self):
        corpus = "X" * 100
        messages = [{"role": "user", "content": "Hi"}]
        inject_into_messages(corpus, messages, knowledge_budget=100)

        content = messages[0]["content"]
        assert "X" * 100 in content


# ---------------------------------------------------------------------------
# build_system_message
# ---------------------------------------------------------------------------


class TestBuildSystemMessage:
    def test_format(self):
        msg = build_system_message("my corpus text")
        assert "=== KNOWLEDGE BASE START ===" in msg
        assert "=== KNOWLEDGE BASE END ===" in msg
        assert "my corpus text" in msg
        assert "knowledge-grounded AI agent" in msg

    def test_truncates_to_budget(self):
        msg = build_system_message("B" * 50000, knowledge_budget=200)
        assert "B" * 200 in msg
        assert "B" * 50000 not in msg

    def test_short_corpus_not_truncated(self):
        msg = build_system_message("short text", knowledge_budget=10000)
        assert "short text" in msg

    def test_exact_budget_not_truncated(self):
        corpus = "C" * 500
        msg = build_system_message(corpus, knowledge_budget=500)
        assert "C" * 500 in msg

    def test_one_over_budget_truncated(self):
        corpus = "D" * 501
        msg = build_system_message(corpus, knowledge_budget=500)
        assert "D" * 500 in msg
        assert "D" * 501 not in msg

    def test_empty_corpus(self):
        msg = build_system_message("")
        assert "=== KNOWLEDGE BASE START ===" in msg
        assert "=== KNOWLEDGE BASE END ===" in msg
        assert "knowledge-grounded AI agent" in msg

    def test_preamble_is_stable(self):
        """The preamble must be identical across calls for KV caching."""
        msg1 = build_system_message("corpus A")
        msg2 = build_system_message("corpus B")

        # Everything before the corpus should be the same
        prefix1 = msg1.split("=== KNOWLEDGE BASE START ===\n")[0]
        prefix2 = msg2.split("=== KNOWLEDGE BASE START ===\n")[0]
        assert prefix1 == prefix2

    def test_default_budget_applied(self):
        # Default is 16000 chars
        corpus = "E" * 20000
        msg = build_system_message(corpus)
        assert "E" * 16000 in msg
        assert "E" * 20000 not in msg


# ---------------------------------------------------------------------------
# Cross-module integration
# ---------------------------------------------------------------------------


class TestCrossModuleIntegration:
    """Verify inject and build_system_message work with CAGCache output."""

    def test_cache_to_inject_pipeline(self, tmp_path):
        from cag_core.cache import CAGCache

        import json

        corpus_text = "=== METHODOLOGY test ===\nDOMAIN: testing\nSOLUTION: use pytest\n==="
        meta = {"stale": False, "methodology_count": 1}
        (tmp_path / "corpus.txt").write_text(corpus_text, encoding="utf-8")
        (tmp_path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        cache = CAGCache(cache_dir=str(tmp_path))
        assert cache.load() is True

        messages = [{"role": "user", "content": "How to test?"}]
        inject_into_messages(cache.get_corpus(), messages)

        assert len(messages) == 2
        assert "METHODOLOGY test" in messages[0]["content"]
        assert messages[1]["content"] == "How to test?"

    def test_cache_to_system_message_pipeline(self, tmp_path):
        from cag_core.cache import CAGCache

        import json

        corpus_text = "Pattern: always test before deploy"
        meta = {"stale": False}
        (tmp_path / "corpus.txt").write_text(corpus_text, encoding="utf-8")
        (tmp_path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        cache = CAGCache(cache_dir=str(tmp_path))
        assert cache.load() is True

        msg = build_system_message(cache.get_corpus())
        assert "always test before deploy" in msg
        assert "=== KNOWLEDGE BASE START ===" in msg
