"""Tests for CAG (Cache-Augmented Generation) Retriever.

All tests use REAL dependencies -- no mocks, no placeholders, no cached responses.
Methodology objects are real Pydantic models with real fields.
File system operations use pytest's tmp_path fixture for isolation.
"""
from __future__ import annotations

import json

import pytest
from datetime import datetime, timezone
from pathlib import Path

from claw.core.config import CAGConfig
from claw.core.models import Methodology
from claw.memory.cag_retriever import CAGRetriever


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_methodology(
    id: str,
    fitness: float = 0.5,
    description: str = "test problem",
    solution: str | None = None,
    tags: list[str] | None = None,
    lifecycle_state: str = "viable",
) -> Methodology:
    """Create a test methodology with given fitness.

    The fitness_vector stores a 'total' key that get_fitness_score() reads.
    Additional dimension keys are included to make the vector realistic.
    """
    return Methodology(
        id=id,
        problem_description=description,
        solution_code=solution or f"def solve_{id}(): pass",
        tags=tags or ["test"],
        language="python",
        scope="project",
        lifecycle_state=lifecycle_state,
        created_at=datetime.now(timezone.utc),
        fitness_vector={
            "total": fitness,
            "retrieval_relevance": fitness,
            "outcome_efficacy": fitness,
        },
    )


def _make_config(tmp_path: Path, **overrides) -> CAGConfig:
    """Create a CAGConfig pointing at a tmp directory."""
    defaults = {
        "enabled": True,
        "cache_dir": str(tmp_path / "cag_caches"),
        "auto_rebuild_on_stale": False,
        "max_methodologies_per_cache": 2000,
        "serialization_format": "structured_text",
        "max_solution_chars": 2000,
    }
    defaults.update(overrides)
    return CAGConfig(**defaults)


def _make_retriever(tmp_path: Path, **config_overrides) -> CAGRetriever:
    """Create a CAGRetriever with a tmp-path-based config and no repository."""
    config = _make_config(tmp_path, **config_overrides)
    return CAGRetriever(config=config, repository=None)


# ---------------------------------------------------------------------------
# Test: build_cache creates files on disk
# ---------------------------------------------------------------------------

class TestBuildCacheCreatesFiles:
    async def test_build_cache_creates_files(self, tmp_path: Path):
        """build_cache() must create corpus.txt and meta.json on disk."""
        retriever = _make_retriever(tmp_path)
        methods = [_make_methodology("m-001"), _make_methodology("m-002")]

        await retriever.build_cache(ganglion="general", methodologies=methods)

        cache_dir = tmp_path / "cag_caches" / "general"
        assert (cache_dir / "corpus.txt").exists()
        assert (cache_dir / "meta.json").exists()

        # Verify corpus contains methodology content
        corpus_text = (cache_dir / "corpus.txt").read_text(encoding="utf-8")
        assert "m-001" in corpus_text
        assert "m-002" in corpus_text

        # Verify meta.json is valid JSON
        meta = json.loads((cache_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["ganglion"] == "general"
        assert meta["methodology_count"] == 2


# ---------------------------------------------------------------------------
# Test: build_cache sorts by fitness
# ---------------------------------------------------------------------------

class TestBuildCacheSortsByFitness:
    async def test_build_cache_sorts_by_fitness(self, tmp_path: Path):
        """Higher-fitness methodologies must appear first in corpus."""
        retriever = _make_retriever(tmp_path)
        m_low = _make_methodology("low-fit", fitness=0.1)
        m_mid = _make_methodology("mid-fit", fitness=0.5)
        m_high = _make_methodology("high-fit", fitness=0.9)

        # Pass in random order
        await retriever.build_cache(
            ganglion="general",
            methodologies=[m_low, m_high, m_mid],
        )

        corpus = retriever.get_corpus("general")
        # High fitness should appear before mid, mid before low
        pos_high = corpus.index("high-fit")
        pos_mid = corpus.index("mid-fit")
        pos_low = corpus.index("low-fit")
        assert pos_high < pos_mid < pos_low


# ---------------------------------------------------------------------------
# Test: build_cache respects max_methodologies_per_cache
# ---------------------------------------------------------------------------

class TestBuildCacheRespectsMaxCount:
    async def test_build_cache_respects_max_count(self, tmp_path: Path):
        """Only max_methodologies_per_cache should appear in corpus."""
        retriever = _make_retriever(tmp_path, max_methodologies_per_cache=2)
        methods = [
            _make_methodology(f"m-{i:03d}", fitness=1.0 - i * 0.1)
            for i in range(5)
        ]

        meta = await retriever.build_cache(ganglion="general", methodologies=methods)

        assert meta["methodology_count"] == 2
        corpus = retriever.get_corpus("general")
        # Top 2 by fitness: m-000 (1.0) and m-001 (0.9)
        assert "m-000" in corpus
        assert "m-001" in corpus
        # m-002 through m-004 should NOT be present
        assert "m-002" not in corpus
        assert "m-003" not in corpus
        assert "m-004" not in corpus


# ---------------------------------------------------------------------------
# Test: build_cache returns metadata
# ---------------------------------------------------------------------------

class TestBuildCacheReturnsMetadata:
    async def test_build_cache_returns_metadata(self, tmp_path: Path):
        """Metadata dict must have all required keys with correct types."""
        retriever = _make_retriever(tmp_path)
        methods = [_make_methodology("m-001")]

        meta = await retriever.build_cache(ganglion="general", methodologies=methods)

        assert isinstance(meta, dict)
        assert meta["ganglion"] == "general"
        assert meta["methodology_count"] == 1
        assert isinstance(meta["built_at"], str)
        assert meta["stale"] is False
        assert isinstance(meta["corpus_tokens_approx"], int)
        assert meta["corpus_tokens_approx"] > 0
        assert isinstance(meta["methodology_ids"], list)
        assert meta["methodology_ids"] == ["m-001"]


# ---------------------------------------------------------------------------
# Test: load_cache succeeds
# ---------------------------------------------------------------------------

class TestLoadCacheSucceeds:
    async def test_load_cache_succeeds(self, tmp_path: Path):
        """Build with one retriever, load with a new one -- corpus must match."""
        config = _make_config(tmp_path)
        retriever1 = CAGRetriever(config=config, repository=None)
        methods = [
            _make_methodology("m-alpha", fitness=0.8),
            _make_methodology("m-beta", fitness=0.6),
        ]
        await retriever1.build_cache(ganglion="general", methodologies=methods)

        original_corpus = retriever1.get_corpus("general")
        assert original_corpus  # non-empty

        # Create a completely new retriever with same config
        retriever2 = CAGRetriever(config=config, repository=None)
        assert not retriever2.is_loaded("general")

        loaded = await retriever2.load_cache("general")
        assert loaded is True
        assert retriever2.is_loaded("general")
        assert retriever2.get_corpus("general") == original_corpus


# ---------------------------------------------------------------------------
# Test: load_cache returns False when no cache exists
# ---------------------------------------------------------------------------

class TestLoadCacheReturnsFalse:
    async def test_load_cache_returns_false_when_no_cache(self, tmp_path: Path):
        """Loading from empty directory must return False."""
        retriever = _make_retriever(tmp_path)
        loaded = await retriever.load_cache("nonexistent-ganglion")
        assert loaded is False
        assert not retriever.is_loaded("nonexistent-ganglion")


# ---------------------------------------------------------------------------
# Test: is_stale defaults to True
# ---------------------------------------------------------------------------

class TestIsStaleDefault:
    def test_is_stale_default_true(self, tmp_path: Path):
        """Before any build, is_stale must return True."""
        retriever = _make_retriever(tmp_path)
        assert retriever.is_stale("general") is True
        assert retriever.is_stale("any-ganglion") is True


# ---------------------------------------------------------------------------
# Test: is_stale False after build
# ---------------------------------------------------------------------------

class TestIsStaleAfterBuild:
    async def test_is_stale_false_after_build(self, tmp_path: Path):
        """After build, is_stale must return False."""
        retriever = _make_retriever(tmp_path)
        methods = [_make_methodology("m-001")]

        await retriever.build_cache(ganglion="general", methodologies=methods)
        assert retriever.is_stale("general") is False


# ---------------------------------------------------------------------------
# Test: mark_stale
# ---------------------------------------------------------------------------

class TestMarkStale:
    async def test_mark_stale(self, tmp_path: Path):
        """build, then mark_stale => is_stale returns True."""
        retriever = _make_retriever(tmp_path)
        methods = [_make_methodology("m-001")]

        await retriever.build_cache(ganglion="general", methodologies=methods)
        assert retriever.is_stale("general") is False

        retriever.mark_stale("general")
        assert retriever.is_stale("general") is True


# ---------------------------------------------------------------------------
# Test: mark_stale persists to disk
# ---------------------------------------------------------------------------

class TestMarkStalePersists:
    async def test_mark_stale_persists_to_disk(self, tmp_path: Path):
        """mark_stale must persist so a new retriever sees stale=True."""
        config = _make_config(tmp_path)
        retriever1 = CAGRetriever(config=config, repository=None)
        methods = [_make_methodology("m-001")]

        await retriever1.build_cache(ganglion="general", methodologies=methods)
        retriever1.mark_stale("general")

        # New retriever with same config
        retriever2 = CAGRetriever(config=config, repository=None)
        loaded = await retriever2.load_cache("general")
        assert loaded is True
        assert retriever2.is_stale("general") is True


# ---------------------------------------------------------------------------
# Test: mark_stale without prior build
# ---------------------------------------------------------------------------

class TestMarkStaleNoPriorBuild:
    def test_mark_stale_creates_minimal_meta(self, tmp_path: Path):
        """mark_stale on a ganglion with no prior build creates a stale meta."""
        retriever = _make_retriever(tmp_path)
        retriever.mark_stale("fresh-ganglion")

        assert retriever.is_stale("fresh-ganglion") is True

        # Verify file was created on disk
        meta_path = tmp_path / "cag_caches" / "fresh-ganglion" / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["stale"] is True
        assert meta["ganglion"] == "fresh-ganglion"


# ---------------------------------------------------------------------------
# Test: get_status
# ---------------------------------------------------------------------------

class TestGetStatus:
    async def test_get_status(self, tmp_path: Path):
        """get_status must return all expected fields."""
        retriever = _make_retriever(tmp_path)
        methods = [_make_methodology("m-001"), _make_methodology("m-002")]

        # Before build
        status_before = retriever.get_status("general")
        assert status_before["ganglion"] == "general"
        assert status_before["methodology_count"] == 0
        assert status_before["built_at"] is None
        assert status_before["stale"] is True
        assert status_before["corpus_tokens_approx"] == 0
        assert status_before["loaded"] is False

        # After build
        await retriever.build_cache(ganglion="general", methodologies=methods)
        status_after = retriever.get_status("general")
        assert status_after["ganglion"] == "general"
        assert status_after["methodology_count"] == 2
        assert status_after["built_at"] is not None
        assert status_after["stale"] is False
        assert status_after["corpus_tokens_approx"] > 0
        assert status_after["loaded"] is True


# ---------------------------------------------------------------------------
# Test: get_corpus empty when not loaded
# ---------------------------------------------------------------------------

class TestGetCorpusEmpty:
    def test_get_corpus_empty_when_not_loaded(self, tmp_path: Path):
        """get_corpus returns empty string before any load/build."""
        retriever = _make_retriever(tmp_path)
        assert retriever.get_corpus("general") == ""
        assert retriever.get_corpus("nonexistent") == ""


# ---------------------------------------------------------------------------
# Test: get_methodology_ids
# ---------------------------------------------------------------------------

class TestGetMethodologyIds:
    async def test_get_methodology_ids(self, tmp_path: Path):
        """IDs from get_methodology_ids must match the methodologies in cache."""
        retriever = _make_retriever(tmp_path)
        methods = [
            _make_methodology("id-alpha", fitness=0.9),
            _make_methodology("id-beta", fitness=0.7),
            _make_methodology("id-gamma", fitness=0.5),
        ]

        await retriever.build_cache(ganglion="general", methodologies=methods)
        ids = retriever.get_methodology_ids("general")

        assert len(ids) == 3
        # Should be ordered by fitness (highest first)
        assert ids[0] == "id-alpha"
        assert ids[1] == "id-beta"
        assert ids[2] == "id-gamma"

    def test_get_methodology_ids_empty_before_build(self, tmp_path: Path):
        """get_methodology_ids returns empty list before build."""
        retriever = _make_retriever(tmp_path)
        assert retriever.get_methodology_ids("general") == []


# ---------------------------------------------------------------------------
# Test: build_cache with custom ganglion
# ---------------------------------------------------------------------------

class TestBuildCacheCustomGanglion:
    async def test_build_cache_with_custom_ganglion(self, tmp_path: Path):
        """Different ganglions must use separate directories."""
        retriever = _make_retriever(tmp_path)
        methods_general = [_make_methodology("gen-001")]
        methods_agentic = [_make_methodology("agn-001"), _make_methodology("agn-002")]

        await retriever.build_cache(ganglion="general", methodologies=methods_general)
        await retriever.build_cache(ganglion="agentic-memory", methodologies=methods_agentic)

        # Verify separate directories
        general_dir = tmp_path / "cag_caches" / "general"
        agentic_dir = tmp_path / "cag_caches" / "agentic-memory"
        assert general_dir.exists()
        assert agentic_dir.exists()

        # Verify separate corpora
        general_corpus = retriever.get_corpus("general")
        agentic_corpus = retriever.get_corpus("agentic-memory")
        assert "gen-001" in general_corpus
        assert "gen-001" not in agentic_corpus
        assert "agn-001" in agentic_corpus
        assert "agn-002" in agentic_corpus

        # Verify separate metadata
        assert retriever.get_status("general")["methodology_count"] == 1
        assert retriever.get_status("agentic-memory")["methodology_count"] == 2


# ---------------------------------------------------------------------------
# Test: corpus_tokens_approx
# ---------------------------------------------------------------------------

class TestCorpusTokensApprox:
    async def test_corpus_tokens_approx(self, tmp_path: Path):
        """Token estimate must be roughly len(corpus) // 4."""
        retriever = _make_retriever(tmp_path)
        methods = [
            _make_methodology(
                f"m-{i:03d}",
                description=f"Problem number {i} with a longer description for tokens",
                solution=f"def solve_{i}():\n    return {i} * 2\n",
            )
            for i in range(10)
        ]

        meta = await retriever.build_cache(ganglion="general", methodologies=methods)
        corpus = retriever.get_corpus("general")

        expected_approx = len(corpus) // 4
        assert meta["corpus_tokens_approx"] == expected_approx


# ---------------------------------------------------------------------------
# Test: empty methodologies list
# ---------------------------------------------------------------------------

class TestEmptyMethodologies:
    async def test_build_cache_empty_methodologies(self, tmp_path: Path):
        """build_cache with empty list creates valid cache files."""
        retriever = _make_retriever(tmp_path)
        meta = await retriever.build_cache(ganglion="general", methodologies=[])

        assert meta["methodology_count"] == 0
        assert meta["stale"] is False
        assert meta["methodology_ids"] == []

        # Corpus should exist but contain the empty corpus header
        corpus = retriever.get_corpus("general")
        assert "CAM Knowledge Base" in corpus


# ---------------------------------------------------------------------------
# Test: load_cache with corrupted meta.json
# ---------------------------------------------------------------------------

class TestLoadCorruptedMeta:
    async def test_load_cache_corrupt_meta_returns_false(self, tmp_path: Path):
        """If meta.json is corrupted, load_cache returns False."""
        retriever = _make_retriever(tmp_path)
        methods = [_make_methodology("m-001")]
        await retriever.build_cache(ganglion="general", methodologies=methods)

        # Corrupt the meta.json
        meta_path = tmp_path / "cag_caches" / "general" / "meta.json"
        meta_path.write_text("this is not valid json {{{", encoding="utf-8")

        # New retriever should fail to load
        retriever2 = CAGRetriever(
            config=_make_config(tmp_path), repository=None
        )
        loaded = await retriever2.load_cache("general")
        assert loaded is False


# ---------------------------------------------------------------------------
# Test: is_loaded reflects state accurately
# ---------------------------------------------------------------------------

class TestIsLoaded:
    async def test_is_loaded(self, tmp_path: Path):
        """is_loaded must reflect whether corpus is in memory."""
        retriever = _make_retriever(tmp_path)

        # Before build
        assert retriever.is_loaded("general") is False

        # After build
        methods = [_make_methodology("m-001")]
        await retriever.build_cache(ganglion="general", methodologies=methods)
        assert retriever.is_loaded("general") is True

        # Different ganglion still not loaded
        assert retriever.is_loaded("other") is False


# ---------------------------------------------------------------------------
# Test: fitness-based ordering with equal fitness
# ---------------------------------------------------------------------------

class TestFitnessOrderingEdgeCases:
    async def test_methodologies_with_no_fitness_vector(self, tmp_path: Path):
        """Methodologies with empty fitness_vector get default 0.5 score."""
        retriever = _make_retriever(tmp_path, max_methodologies_per_cache=3)
        m_no_fitness = Methodology(
            id="no-fitness",
            problem_description="no fitness vector",
            solution_code="pass",
            tags=["test"],
            language="python",
            scope="project",
            lifecycle_state="viable",
            fitness_vector={},
        )
        m_high = _make_methodology("high-fit", fitness=0.9)
        m_low = _make_methodology("low-fit", fitness=0.1)

        await retriever.build_cache(
            ganglion="general",
            methodologies=[m_no_fitness, m_low, m_high],
        )

        ids = retriever.get_methodology_ids("general")
        # high (0.9) > no-fitness (0.5 default) > low (0.1)
        assert ids[0] == "high-fit"
        assert ids[1] == "no-fitness"
        assert ids[2] == "low-fit"
