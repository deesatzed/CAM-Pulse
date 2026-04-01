"""Tests for CAG recipe generator and exported cag_runtime.py.

Tests cover:
- Recipe generation validity (compilable, no CAM imports, correct defaults)
- CAGCache class via exec() of generated code
- inject_into_messages() and build_system_message() functions
- End-to-end export pipeline
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from claw.memory.cag_recipe import generate_recipe


# ---------------------------------------------------------------------------
# Recipe generation
# ---------------------------------------------------------------------------


class TestGenerateRecipe:
    def test_valid_python(self):
        code = generate_recipe()
        compile(code, "cag_runtime.py", "exec")

    def test_contains_class(self):
        code = generate_recipe()
        assert "class CAGCache" in code

    def test_contains_inject_function(self):
        code = generate_recipe()
        assert "def inject_into_messages" in code

    def test_contains_system_message_function(self):
        code = generate_recipe()
        assert "def build_system_message" in code

    def test_no_claw_imports(self):
        code = generate_recipe()
        assert "from claw" not in code
        assert "import claw" not in code

    def test_embeds_ganglion(self):
        code = generate_recipe(ganglion="my-custom-ganglion")
        assert "my-custom-ganglion" in code

    def test_embeds_knowledge_budget(self):
        code = generate_recipe(knowledge_budget=32000)
        assert "32000" in code

    def test_default_ganglion(self):
        code = generate_recipe()
        assert "imported" in code

    def test_has_main_block(self):
        code = generate_recipe()
        assert 'if __name__ == "__main__"' in code


# ---------------------------------------------------------------------------
# CAGCache integration (exec the generated code)
# ---------------------------------------------------------------------------


def _exec_recipe(ganglion: str = "test") -> dict:
    """Exec the generated recipe and return its namespace."""
    code = generate_recipe(ganglion=ganglion, knowledge_budget=16000)
    ns: dict = {}
    exec(code, ns)  # noqa: S102
    return ns


class TestCAGCacheIntegration:
    def test_load_corpus(self, tmp_path):
        ns = _exec_recipe()
        corpus_text = "=== METHODOLOGY abc123 ===\nDOMAIN: testing\nPROBLEM: How to test\nSOLUTION:\nRun pytest\n==="
        meta = {"ganglion": "test", "methodology_count": 1, "built_at": "2026-03-31T00:00:00Z",
                "stale": False, "corpus_tokens_approx": 25, "methodology_ids": ["abc123"],
                "pointer_count": 0, "shorthand_compression": False}

        (tmp_path / "corpus.txt").write_text(corpus_text)
        (tmp_path / "meta.json").write_text(json.dumps(meta))

        cache = ns["CAGCache"](cache_dir=str(tmp_path))
        assert cache.load() is True
        assert cache.get_corpus() == corpus_text
        assert cache.is_loaded() is True

    def test_load_missing_files(self, tmp_path):
        ns = _exec_recipe()
        cache = ns["CAGCache"](cache_dir=str(tmp_path))
        assert cache.load() is False
        assert cache.is_loaded() is False

    def test_is_stale(self, tmp_path):
        ns = _exec_recipe()

        (tmp_path / "corpus.txt").write_text("content")
        (tmp_path / "meta.json").write_text(json.dumps({"stale": True}))

        cache = ns["CAGCache"](cache_dir=str(tmp_path))
        cache.load()
        assert cache.is_stale() is True

    def test_not_stale(self, tmp_path):
        ns = _exec_recipe()

        (tmp_path / "corpus.txt").write_text("content")
        (tmp_path / "meta.json").write_text(json.dumps({"stale": False}))

        cache = ns["CAGCache"](cache_dir=str(tmp_path))
        cache.load()
        assert cache.is_stale() is False

    def test_mark_stale(self, tmp_path):
        ns = _exec_recipe()

        (tmp_path / "corpus.txt").write_text("content")
        meta = {"ganglion": "test", "stale": False, "methodology_count": 5}
        (tmp_path / "meta.json").write_text(json.dumps(meta))

        cache = ns["CAGCache"](cache_dir=str(tmp_path))
        cache.load()
        assert cache.is_stale() is False

        cache.mark_stale()
        assert cache.is_stale() is True

        # Verify persisted to disk
        on_disk = json.loads((tmp_path / "meta.json").read_text())
        assert on_disk["stale"] is True
        assert on_disk["methodology_count"] == 5  # preserved

    def test_get_status_shape(self, tmp_path):
        ns = _exec_recipe()

        (tmp_path / "corpus.txt").write_text("some corpus")
        meta = {"ganglion": "test", "methodology_count": 3, "built_at": "2026-03-31",
                "stale": False, "corpus_tokens_approx": 100, "pointer_count": 0,
                "shorthand_compression": False}
        (tmp_path / "meta.json").write_text(json.dumps(meta))

        cache = ns["CAGCache"](cache_dir=str(tmp_path))
        cache.load()
        status = cache.get_status()

        assert status["methodology_count"] == 3
        assert status["loaded"] is True
        assert status["stale"] is False
        assert status["corpus_tokens_approx"] == 100
        assert "ganglion" in status
        assert "built_at" in status


# ---------------------------------------------------------------------------
# inject_into_messages
# ---------------------------------------------------------------------------


class TestInjectIntoMessages:
    def test_adds_to_existing_system_message(self):
        ns = _exec_recipe()
        inject = ns["inject_into_messages"]

        messages = [{"role": "system", "content": "You are helpful."}]
        inject("knowledge here", messages)

        assert "knowledge here" in messages[0]["content"]
        assert "You are helpful." in messages[0]["content"]
        assert "--- END KNOWLEDGE BASE ---" in messages[0]["content"]

    def test_creates_system_message(self):
        ns = _exec_recipe()
        inject = ns["inject_into_messages"]

        messages = [{"role": "user", "content": "Hello"}]
        inject("knowledge here", messages)

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "knowledge here" in messages[0]["content"]
        assert messages[1]["role"] == "user"

    def test_respects_budget(self):
        ns = _exec_recipe()
        inject = ns["inject_into_messages"]

        corpus = "A" * 50000
        messages = [{"role": "user", "content": "Hi"}]
        inject(corpus, messages, knowledge_budget=100)

        system_content = messages[0]["content"]
        # The truncated corpus should be 100 chars, not 50000
        assert "A" * 100 in system_content
        assert "A" * 50000 not in system_content

    def test_empty_corpus_noop(self):
        ns = _exec_recipe()
        inject = ns["inject_into_messages"]

        messages = [{"role": "user", "content": "Hi"}]
        inject("", messages)
        assert len(messages) == 1

    def test_knowledge_base_delimiters(self):
        ns = _exec_recipe()
        inject = ns["inject_into_messages"]

        messages = [{"role": "user", "content": "Hi"}]
        inject("test corpus", messages)

        content = messages[0]["content"]
        assert "## Knowledge Base" in content
        assert "--- END KNOWLEDGE BASE ---" in content


# ---------------------------------------------------------------------------
# build_system_message
# ---------------------------------------------------------------------------


class TestBuildSystemMessage:
    def test_format(self):
        ns = _exec_recipe()
        build = ns["build_system_message"]

        msg = build("my corpus text")
        assert "=== KNOWLEDGE BASE START ===" in msg
        assert "=== KNOWLEDGE BASE END ===" in msg
        assert "my corpus text" in msg
        assert "knowledge-grounded AI agent" in msg

    def test_truncates_to_budget(self):
        ns = _exec_recipe()
        build = ns["build_system_message"]

        msg = build("B" * 50000, knowledge_budget=200)
        assert "B" * 200 in msg
        assert "B" * 50000 not in msg

    def test_short_corpus_not_truncated(self):
        ns = _exec_recipe()
        build = ns["build_system_message"]

        msg = build("short text", knowledge_budget=10000)
        assert "short text" in msg


# ---------------------------------------------------------------------------
# End-to-end export pipeline
# ---------------------------------------------------------------------------


class TestEndToEndExport:
    @pytest.mark.asyncio
    async def test_export_recipe_creates_files(self, tmp_path):
        """Full pipeline: create docs → convert → export recipe → use recipe."""
        from claw.core.config import CAGConfig
        from claw.memory.cag_retriever import CAGRetriever
        from claw.memory.rag_adapter import adapt_to_methodologies, read_source

        # Create source documents
        src_dir = tmp_path / "rag_source"
        src_dir.mkdir()
        for i in range(3):
            (src_dir / f"doc{i}.md").write_text(
                f"# Document {i}\n\n"
                f"This document covers topic {i} with detailed explanations "
                f"about the subject matter and practical examples for usage."
            )

        # Read and convert
        docs, _ = read_source(src_dir)
        meths = adapt_to_methodologies(docs)

        # Build cache
        cache_dir = str(tmp_path / "cag_cache")
        cfg = CAGConfig(enabled=True, cache_dir=cache_dir, knowledge_budget_chars=16000)
        retriever = CAGRetriever(cfg)
        await retriever.build_cache(ganglion="export-test", methodologies=meths)

        # Export recipe
        import shutil

        export_path = tmp_path / "export"
        export_path.mkdir()
        shutil.copy2(
            str(Path(cache_dir) / "export-test" / "corpus.txt"),
            str(export_path / "corpus.txt"),
        )
        shutil.copy2(
            str(Path(cache_dir) / "export-test" / "meta.json"),
            str(export_path / "meta.json"),
        )

        recipe_code = generate_recipe(ganglion="export-test", knowledge_budget=16000)
        (export_path / "cag_runtime.py").write_text(recipe_code, encoding="utf-8")

        # Verify files exist
        assert (export_path / "cag_runtime.py").exists()
        assert (export_path / "corpus.txt").exists()
        assert (export_path / "meta.json").exists()

        # Verify recipe works
        ns: dict = {}
        exec(recipe_code, ns)  # noqa: S102

        cache = ns["CAGCache"](cache_dir=str(export_path))
        assert cache.load() is True
        corpus = cache.get_corpus()
        assert "Document" in corpus
        assert "=== METHODOLOGY" in corpus

        # Verify injection works
        messages = [{"role": "user", "content": "Hello"}]
        ns["inject_into_messages"](corpus, messages)
        assert len(messages) == 2
        assert "Document" in messages[0]["content"]
