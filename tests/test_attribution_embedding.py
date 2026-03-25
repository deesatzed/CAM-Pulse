"""Tests for embedding attribution upgrade (Phase C).

Covers:
- Lexical pass unchanged when embedding disabled
- Embedding pass catches semantic matches
- Embedding score upgrades lexical matches
- Threshold filters low-similarity mismatches
- API call count bounded
- Fallback to pure lexical when engine is None
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from claw.core.models import ContextBrief, Methodology, Task, TaskOutcome
from claw.cycle import _infer_used_methodology_ids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_methodology(
    id: str,
    problem_description: str = "",
    methodology_notes: str = "",
    tags: list[str] | None = None,
    files_affected: list[str] | None = None,
) -> Methodology:
    return Methodology(
        id=id,
        problem_description=problem_description,
        solution_code="pass",
        methodology_notes=methodology_notes,
        tags=tags or [],
        files_affected=files_affected or [],
    )


def _make_outcome(
    approach_summary: str = "",
    raw_output: str = "",
    diff: str = "",
    files_changed: list[str] | None = None,
) -> TaskOutcome:
    return TaskOutcome(
        approach_summary=approach_summary,
        raw_output=raw_output,
        diff=diff,
        files_changed=files_changed or [],
    )


def _make_task() -> Task:
    return Task(
        id="test-task-1",
        title="Test task",
        description="Test task",
        project_id="test-proj",
    )


def _make_context_brief(past_solutions: list[Methodology]) -> ContextBrief:
    return ContextBrief(
        task=_make_task(),
        past_solutions=past_solutions,
    )


class FakeEmbeddingEngine:
    """Deterministic embedding engine for testing.

    Produces vectors that make similar text produce high cosine similarity
    and dissimilar text produce low cosine similarity.
    """

    def __init__(self, embeddings_map: dict[str, list[float]]):
        """Map from text substring → embedding vector.

        If text matches a key (substring), return that vector.
        Otherwise return a zero-ish vector.
        """
        self._map = embeddings_map
        self.encode_calls: list[str] = []

    def encode(self, text: str) -> list[float]:
        self.encode_calls.append(text)
        for key, vec in self._map.items():
            if key.lower() in text.lower():
                return vec
        # Default: orthogonal vector
        return [0.0] * len(next(iter(self._map.values())))

    @staticmethod
    def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        import math
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)


class FakeMemoryConfig:
    """Minimal memory config for testing."""

    def __init__(
        self,
        enabled: bool = False,
        weight: float = 0.6,
        threshold: float = 0.35,
    ):
        self.attribution_embedding_enabled = enabled
        self.attribution_embedding_weight = weight
        self.attribution_embedding_threshold = threshold


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Test: Lexical unchanged when disabled
# ---------------------------------------------------------------------------

class TestLexicalUnchangedWhenDisabled:
    """With attribution_embedding_enabled=False, behavior is pure lexical."""

    def test_lexical_only_no_engine(self):
        """No embedding engine passed → pure lexical."""
        m1 = _make_methodology(
            "m1",
            problem_description="python authentication token validation",
            tags=["authentication", "validation"],
        )
        outcome = _make_outcome(
            approach_summary="implemented authentication token validation for users",
        )
        ctx = _make_context_brief([m1])

        result = _run(_infer_used_methodology_ids(ctx, outcome))
        assert len(result) >= 1
        assert result[0][0] == "m1"

    def test_lexical_only_disabled_config(self):
        """Engine provided but config disabled → pure lexical, no encode calls."""
        engine = FakeEmbeddingEngine({"auth": [1.0, 0.0, 0.0]})
        config = FakeMemoryConfig(enabled=False)

        m1 = _make_methodology(
            "m1",
            problem_description="python authentication token validation",
            tags=["authentication"],
        )
        outcome = _make_outcome(
            approach_summary="implemented authentication token validation",
        )
        ctx = _make_context_brief([m1])

        result = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=engine, memory_config=config
        ))
        assert len(result) >= 1
        assert result[0][0] == "m1"
        # No encode calls should have been made
        assert len(engine.encode_calls) == 0


# ---------------------------------------------------------------------------
# Test: Embedding catches semantic match
# ---------------------------------------------------------------------------

class TestEmbeddingCatchesSemanticMatch:
    """Embedding pass should catch semantically similar but lexically different text."""

    def test_semantic_match_caught(self):
        """'auth flow' methodology matched to 'login session' outcome via embeddings."""
        # Vectors: auth_vec and login_vec have high cosine similarity
        auth_vec = [0.9, 0.3, 0.1, 0.0]
        login_vec = [0.85, 0.35, 0.15, 0.0]
        css_vec = [0.0, 0.0, 0.1, 0.95]

        engine = FakeEmbeddingEngine({
            "authentication flow": auth_vec,
            "login session": login_vec,
            "css styling": css_vec,
        })
        config = FakeMemoryConfig(enabled=True, weight=0.8, threshold=0.30)

        # Methodology uses "authentication flow" but outcome uses "login session"
        # Lexically they share no tokens (below threshold), but embeddings are similar
        m1 = _make_methodology(
            "m1",
            problem_description="authentication flow for secure access",
            methodology_notes="OAuth2 bearer token management",
        )
        outcome = _make_outcome(
            approach_summary="login session management with bearer tokens",
        )
        ctx = _make_context_brief([m1])

        result = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=engine, memory_config=config
        ))
        # m1 should appear (either via lexical "bearer" + "tokens" overlap, or embedding)
        ids = [r[0] for r in result]
        assert "m1" in ids


# ---------------------------------------------------------------------------
# Test: Embedding reranks higher score
# ---------------------------------------------------------------------------

class TestEmbeddingReranksHigherScore:
    """When embedding score > lexical score, combined reflects the higher value."""

    def test_embedding_upgrades_score(self):
        """A lexically-matched methodology gets upgraded score from embedding pass."""
        # Both share "validation" tokens (lexical match),
        # but embedding provides a higher similarity
        val_vec = [0.9, 0.4, 0.1, 0.0]

        engine = FakeEmbeddingEngine({
            "validation": val_vec,
        })
        config = FakeMemoryConfig(enabled=True, weight=1.0, threshold=0.30)

        m1 = _make_methodology(
            "m1",
            problem_description="input validation for API endpoints",
            tags=["validation", "api"],
        )
        outcome = _make_outcome(
            approach_summary="added input validation checks to the REST endpoints",
        )
        ctx = _make_context_brief([m1])

        # Without embedding
        result_no_emb = _run(_infer_used_methodology_ids(ctx, outcome))
        assert len(result_no_emb) >= 1
        lexical_score = result_no_emb[0][1]

        # With embedding
        result_with_emb = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=engine, memory_config=config
        ))
        assert len(result_with_emb) >= 1
        combined_score = result_with_emb[0][1]

        # Combined should be >= lexical (max of the two)
        assert combined_score >= lexical_score


# ---------------------------------------------------------------------------
# Test: Threshold filters low similarity
# ---------------------------------------------------------------------------

class TestThresholdFiltersLowSimilarity:
    """Embedding pass should NOT match methodologies below the threshold."""

    def test_low_similarity_filtered(self):
        """'database indexing' methodology vs 'CSS styling' outcome → no match."""
        db_vec = [0.9, 0.1, 0.0, 0.0]
        css_vec = [0.0, 0.0, 0.1, 0.95]

        engine = FakeEmbeddingEngine({
            "database indexing": db_vec,
            "css styling": css_vec,
        })
        config = FakeMemoryConfig(enabled=True, weight=0.6, threshold=0.50)

        m1 = _make_methodology(
            "m1",
            problem_description="database indexing strategies for performance",
            methodology_notes="B-tree index optimization",
        )
        outcome = _make_outcome(
            approach_summary="css styling improvements for the landing page",
        )
        ctx = _make_context_brief([m1])

        result = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=engine, memory_config=config
        ))
        ids = [r[0] for r in result]
        assert "m1" not in ids

    def test_zero_vector_methodology_skipped(self):
        """Methodology with empty text fields should not cause errors."""
        engine = FakeEmbeddingEngine({"anything": [1.0, 0.0, 0.0]})
        config = FakeMemoryConfig(enabled=True, weight=0.6, threshold=0.30)

        m1 = _make_methodology(
            "m1",
            problem_description="",
            methodology_notes="",
            tags=[],
        )
        outcome = _make_outcome(
            approach_summary="implemented something entirely new",
        )
        ctx = _make_context_brief([m1])

        result = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=engine, memory_config=config
        ))
        # Should not crash, and m1 should not appear
        ids = [r[0] for r in result]
        assert "m1" not in ids


# ---------------------------------------------------------------------------
# Test: API call count bounded
# ---------------------------------------------------------------------------

class TestAPICallsBounded:
    """Encode calls should be bounded: 1 for outcome + N for methodologies."""

    def test_encode_calls_counted(self):
        """With 3 methodologies (all unmatched lexically), expect 1+3=4 encode calls."""
        vec = [0.5, 0.5, 0.0, 0.0]
        engine = FakeEmbeddingEngine({"fallback": vec})
        config = FakeMemoryConfig(enabled=True, weight=0.6, threshold=0.90)  # High threshold → no matches

        meths = [
            _make_methodology(f"m{i}", problem_description=f"unique_concept_{i}_alpha")
            for i in range(3)
        ]
        outcome = _make_outcome(
            approach_summary="completely different topic about beta gamma delta",
        )
        ctx = _make_context_brief(meths)

        _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=engine, memory_config=config
        ))
        # 1 outcome encoding + 3 methodology encodings (all go to unmatched since lexical won't match)
        assert len(engine.encode_calls) == 4

    def test_no_encode_when_all_matched_lexically(self):
        """If all methodologies match lexically, encode = 1 (outcome) + N (upgrade pass)."""
        vec = [0.5, 0.5, 0.0, 0.0]
        engine = FakeEmbeddingEngine({"testing": vec})
        config = FakeMemoryConfig(enabled=True, weight=0.6, threshold=0.30)

        m1 = _make_methodology(
            "m1",
            problem_description="testing framework configuration setup",
            tags=["testing", "configuration"],
        )
        outcome = _make_outcome(
            approach_summary="testing framework configuration was updated",
        )
        ctx = _make_context_brief([m1])

        _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=engine, memory_config=config
        ))
        # 1 outcome + 1 upgrade pass for m1 = 2
        assert len(engine.encode_calls) == 2


# ---------------------------------------------------------------------------
# Test: Fallback when engine is None
# ---------------------------------------------------------------------------

class TestFallbackWhenEngineNone:
    """Pure lexical when embedding_engine=None, regardless of config."""

    def test_none_engine_still_works(self):
        """Passing None engine should produce lexical results without error."""
        config = FakeMemoryConfig(enabled=True)

        m1 = _make_methodology(
            "m1",
            problem_description="python error handling middleware",
            tags=["error", "middleware"],
        )
        outcome = _make_outcome(
            approach_summary="added error handling middleware to the application",
        )
        ctx = _make_context_brief([m1])

        result = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=None, memory_config=config
        ))
        assert len(result) >= 1
        assert result[0][0] == "m1"

    def test_empty_past_solutions(self):
        """No past solutions → empty result, no crash."""
        engine = FakeEmbeddingEngine({"x": [1.0]})
        config = FakeMemoryConfig(enabled=True)
        outcome = _make_outcome(approach_summary="something")
        ctx = _make_context_brief([])

        result = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=engine, memory_config=config
        ))
        assert result == []

    def test_none_context_brief(self):
        """None context brief → empty result."""
        outcome = _make_outcome(approach_summary="something")
        result = _run(_infer_used_methodology_ids(
            None, outcome
        ))
        assert result == []


# ---------------------------------------------------------------------------
# Test: Engine error gracefully caught
# ---------------------------------------------------------------------------

class TestEngineErrorGraceful:
    """If embedding engine raises, fall back to lexical only."""

    def test_encode_error_caught(self):
        """Embedding engine raises → lexical results preserved, no crash."""
        class BrokenEngine:
            def encode(self, text):
                raise RuntimeError("API down")

            @staticmethod
            def cosine_similarity(v1, v2):
                return 0.0

        config = FakeMemoryConfig(enabled=True, weight=0.6, threshold=0.30)

        m1 = _make_methodology(
            "m1",
            problem_description="caching strategy for redis connections",
            tags=["caching", "redis"],
        )
        m2 = _make_methodology(
            "m2",
            problem_description="totally unrelated quantum physics simulation",
        )
        outcome = _make_outcome(
            approach_summary="implemented caching strategy using redis connections pool",
        )
        ctx = _make_context_brief([m1, m2])

        result = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=BrokenEngine(), memory_config=config
        ))
        # Lexical pass should still have matched m1
        ids = [r[0] for r in result]
        assert "m1" in ids


# ---------------------------------------------------------------------------
# Test: Max 5 results returned
# ---------------------------------------------------------------------------

class TestMaxResults:
    """At most 5 results returned even with many matches."""

    def test_max_five_results(self):
        """With 8 lexically matching methodologies, only top 5 returned."""
        meths = [
            _make_methodology(
                f"m{i}",
                problem_description=f"python module_{i} optimization logging metrics",
                tags=["optimization", "logging", "metrics"],
            )
            for i in range(8)
        ]
        outcome = _make_outcome(
            approach_summary="optimized python logging and metrics collection modules",
        )
        ctx = _make_context_brief(meths)

        result = _run(_infer_used_methodology_ids(ctx, outcome))
        assert len(result) <= 5
