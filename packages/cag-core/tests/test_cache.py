"""Tests for cag_core.cache — CAGCache class."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cag_core.cache import CAGCache, DEFAULT_GANGLION, DEFAULT_KNOWLEDGE_BUDGET


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_corpus(tmp_path: Path, corpus: str, meta: dict) -> Path:
    """Write corpus.txt and meta.json into tmp_path and return the dir."""
    (tmp_path / "corpus.txt").write_text(corpus, encoding="utf-8")
    (tmp_path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_ganglion_value(self):
        assert DEFAULT_GANGLION == "imported"

    def test_default_knowledge_budget_value(self):
        assert DEFAULT_KNOWLEDGE_BUDGET == 16000


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_cache_dir(self):
        cache = CAGCache()
        assert cache._cache_dir == Path(".")

    def test_custom_cache_dir(self, tmp_path):
        cache = CAGCache(cache_dir=str(tmp_path))
        assert cache._cache_dir == tmp_path

    def test_custom_ganglion(self):
        cache = CAGCache(ganglion="my-ganglion")
        assert cache._ganglion == "my-ganglion"

    def test_initial_state_empty(self):
        cache = CAGCache()
        assert cache.get_corpus() == ""
        assert cache.is_loaded() is False


# ---------------------------------------------------------------------------
# Path properties
# ---------------------------------------------------------------------------


class TestPaths:
    def test_corpus_path(self, tmp_path):
        cache = CAGCache(cache_dir=str(tmp_path))
        assert cache.corpus_path == tmp_path / "corpus.txt"

    def test_meta_path(self, tmp_path):
        cache = CAGCache(cache_dir=str(tmp_path))
        assert cache.meta_path == tmp_path / "meta.json"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_success(self, tmp_path):
        corpus_text = "=== METHODOLOGY abc123 ===\nDOMAIN: testing\nPROBLEM: test\nSOLUTION:\nRun pytest\n==="
        meta = {
            "ganglion": "test",
            "methodology_count": 1,
            "built_at": "2026-03-31T00:00:00Z",
            "stale": False,
            "corpus_tokens_approx": 25,
            "methodology_ids": ["abc123"],
            "pointer_count": 0,
            "shorthand_compression": False,
        }
        _write_corpus(tmp_path, corpus_text, meta)

        cache = CAGCache(cache_dir=str(tmp_path))
        assert cache.load() is True
        assert cache.get_corpus() == corpus_text
        assert cache.is_loaded() is True

    def test_load_missing_files(self, tmp_path):
        cache = CAGCache(cache_dir=str(tmp_path))
        assert cache.load() is False
        assert cache.is_loaded() is False

    def test_load_missing_corpus_only(self, tmp_path):
        (tmp_path / "meta.json").write_text(json.dumps({"stale": False}))
        cache = CAGCache(cache_dir=str(tmp_path))
        assert cache.load() is False

    def test_load_missing_meta_only(self, tmp_path):
        (tmp_path / "corpus.txt").write_text("content")
        cache = CAGCache(cache_dir=str(tmp_path))
        assert cache.load() is False

    def test_load_invalid_json(self, tmp_path):
        (tmp_path / "corpus.txt").write_text("content")
        (tmp_path / "meta.json").write_text("NOT VALID JSON {{{")
        cache = CAGCache(cache_dir=str(tmp_path))
        assert cache.load() is False

    def test_load_meta_not_dict(self, tmp_path):
        (tmp_path / "corpus.txt").write_text("content")
        (tmp_path / "meta.json").write_text(json.dumps([1, 2, 3]))
        cache = CAGCache(cache_dir=str(tmp_path))
        assert cache.load() is False


# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------


class TestStale:
    def test_is_stale_true(self, tmp_path):
        _write_corpus(tmp_path, "content", {"stale": True})
        cache = CAGCache(cache_dir=str(tmp_path))
        cache.load()
        assert cache.is_stale() is True

    def test_is_stale_false(self, tmp_path):
        _write_corpus(tmp_path, "content", {"stale": False})
        cache = CAGCache(cache_dir=str(tmp_path))
        cache.load()
        assert cache.is_stale() is False

    def test_is_stale_defaults_true_when_missing(self, tmp_path):
        _write_corpus(tmp_path, "content", {})
        cache = CAGCache(cache_dir=str(tmp_path))
        cache.load()
        assert cache.is_stale() is True


# ---------------------------------------------------------------------------
# mark_stale
# ---------------------------------------------------------------------------


class TestMarkStale:
    def test_mark_stale_sets_flag(self, tmp_path):
        meta = {"ganglion": "test", "stale": False, "methodology_count": 5}
        _write_corpus(tmp_path, "content", meta)

        cache = CAGCache(cache_dir=str(tmp_path))
        cache.load()
        assert cache.is_stale() is False

        cache.mark_stale()
        assert cache.is_stale() is True

    def test_mark_stale_persists_to_disk(self, tmp_path):
        meta = {"ganglion": "test", "stale": False, "methodology_count": 5}
        _write_corpus(tmp_path, "content", meta)

        cache = CAGCache(cache_dir=str(tmp_path))
        cache.load()
        cache.mark_stale()

        on_disk = json.loads((tmp_path / "meta.json").read_text())
        assert on_disk["stale"] is True
        assert on_disk["methodology_count"] == 5  # preserved

    def test_mark_stale_creates_meta_if_missing(self, tmp_path):
        cache = CAGCache(cache_dir=str(tmp_path), ganglion="fresh")
        cache.mark_stale()

        assert (tmp_path / "meta.json").exists()
        on_disk = json.loads((tmp_path / "meta.json").read_text())
        assert on_disk["stale"] is True
        assert on_disk["ganglion"] == "fresh"

    def test_mark_stale_handles_corrupt_meta(self, tmp_path):
        (tmp_path / "meta.json").write_text("NOT JSON")
        cache = CAGCache(cache_dir=str(tmp_path), ganglion="test")
        cache.mark_stale()

        on_disk = json.loads((tmp_path / "meta.json").read_text())
        assert on_disk["stale"] is True

    def test_mark_stale_handles_non_dict_meta(self, tmp_path):
        (tmp_path / "meta.json").write_text(json.dumps([1, 2, 3]))
        cache = CAGCache(cache_dir=str(tmp_path), ganglion="test")
        cache.mark_stale()

        on_disk = json.loads((tmp_path / "meta.json").read_text())
        assert isinstance(on_disk, dict)
        assert on_disk["stale"] is True

    def test_mark_stale_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        cache = CAGCache(cache_dir=str(nested), ganglion="deep")
        cache.mark_stale()

        assert (nested / "meta.json").exists()


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_status_shape(self, tmp_path):
        meta = {
            "ganglion": "test",
            "methodology_count": 3,
            "built_at": "2026-03-31",
            "stale": False,
            "corpus_tokens_approx": 100,
            "pointer_count": 0,
            "shorthand_compression": False,
        }
        _write_corpus(tmp_path, "some corpus", meta)

        cache = CAGCache(cache_dir=str(tmp_path))
        cache.load()
        status = cache.get_status()

        assert status["methodology_count"] == 3
        assert status["loaded"] is True
        assert status["stale"] is False
        assert status["corpus_tokens_approx"] == 100
        assert "ganglion" in status
        assert "built_at" in status
        assert "pointer_count" in status
        assert "shorthand_compression" in status

    def test_status_defaults_when_empty(self, tmp_path):
        _write_corpus(tmp_path, "content", {})
        cache = CAGCache(cache_dir=str(tmp_path))
        cache.load()
        status = cache.get_status()

        assert status["methodology_count"] == 0
        assert status["built_at"] is None
        assert status["stale"] is True
        assert status["corpus_tokens_approx"] == 0
        assert status["pointer_count"] == 0
        assert status["shorthand_compression"] is False

    def test_status_uses_constructor_ganglion(self, tmp_path):
        _write_corpus(tmp_path, "content", {"ganglion": "disk-ganglion"})
        cache = CAGCache(cache_dir=str(tmp_path), ganglion="constructor-ganglion")
        cache.load()
        status = cache.get_status()
        assert status["ganglion"] == "constructor-ganglion"


# ---------------------------------------------------------------------------
# corpus_hash
# ---------------------------------------------------------------------------


class TestCorpusHash:
    def test_hash_empty_corpus(self):
        cache = CAGCache()
        assert cache.corpus_hash() == ""

    def test_hash_returns_12_chars(self, tmp_path):
        _write_corpus(tmp_path, "some content", {"stale": False})
        cache = CAGCache(cache_dir=str(tmp_path))
        cache.load()
        h = cache.corpus_hash()
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_deterministic(self, tmp_path):
        _write_corpus(tmp_path, "deterministic content", {"stale": False})
        cache = CAGCache(cache_dir=str(tmp_path))
        cache.load()
        assert cache.corpus_hash() == cache.corpus_hash()

    def test_different_corpus_different_hash(self, tmp_path):
        _write_corpus(tmp_path, "content A", {"stale": False})
        cache_a = CAGCache(cache_dir=str(tmp_path))
        cache_a.load()

        (tmp_path / "corpus.txt").write_text("content B", encoding="utf-8")
        cache_b = CAGCache(cache_dir=str(tmp_path))
        cache_b.load()

        assert cache_a.corpus_hash() != cache_b.corpus_hash()
