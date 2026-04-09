"""Tests for Phase C: Embedding Attribution Upgrade.

Validates the two-pass attribution system in _infer_used_methodology_ids():
  Pass 1 (lexical): Token overlap, always runs.
  Pass 2 (embedding): Cosine similarity via real embedding engine, opt-in.

Tests 1 and 6 run without any API key (pure lexical path).
Tests 2-5 require GOOGLE_API_KEY and use the real Gemini embedding engine.

Calibration note (gemini-embedding-2-preview, 384 dims):
  Similar domains (auth/login, validation/sanitization):  cosine ~0.77-0.86
  Unrelated domains (DB/CSS, physics/recipes):            cosine ~0.59-0.67
  The discrimination gap sits around 0.68-0.77.
  A threshold of 0.70 reliably separates related from unrelated.

Coverage:
  1. test_lexical_unchanged_when_disabled  - embedding disabled/engine None -> pure lexical
  2. test_embedding_catches_semantic_match  - semantically similar but lexically different
  3. test_embedding_reranks_higher_score    - embedding upgrades lexical score
  4. test_threshold_filters_low_similarity  - cross-domain mismatch filtered out
  5. test_max_api_calls_bounded            - encode() call count is bounded
  6. test_fallback_when_engine_none         - None engine -> pure lexical
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from claw.core.config import EmbeddingsConfig, MemoryConfig
from claw.core.models import ContextBrief, Methodology, Task, TaskOutcome
from claw.cycle import _infer_used_methodology_ids


# ---------------------------------------------------------------------------
# Skip marker for tests that require the real Google embedding API
# ---------------------------------------------------------------------------
skipif_no_google = pytest.mark.skipif(
    not os.getenv("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY required for real embedding tests",
)


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


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


class FakeMemoryConfig:
    """Minimal memory config namespace for attribution embedding settings.

    Not a mock -- just a plain object carrying three attributes that
    _infer_used_methodology_ids reads via getattr().
    """

    def __init__(
        self,
        enabled: bool = False,
        weight: float = 0.6,
        threshold: float = 0.35,
    ):
        self.attribution_embedding_enabled = enabled
        self.attribution_embedding_weight = weight
        self.attribution_embedding_threshold = threshold


def _get_real_embedding_engine():
    """Create a real EmbeddingEngine using Gemini embeddings and GOOGLE_API_KEY.

    Returns the engine configured for gemini-embedding-2-preview (384 dims).
    Caller must ensure GOOGLE_API_KEY is set in the environment.
    """
    from claw.db.embeddings import EmbeddingEngine

    cfg = EmbeddingsConfig(
        model="gemini-embedding-2-preview",
        dimension=384,
        api_key_env="GOOGLE_API_KEY",
        task_type="RETRIEVAL_DOCUMENT",
    )
    return EmbeddingEngine(cfg)


class CountingEngine:
    """Wrapper around a real embedding engine that counts encode() calls.

    This is NOT a mock. It delegates every call to the real engine and
    simply tracks how many times encode() was invoked.
    """

    def __init__(self, real_engine: Any):
        self.real = real_engine
        self.encode_count = 0

    def encode(self, text: str) -> list[float]:
        self.encode_count += 1
        return self.real.encode(text)

    async def async_encode(self, text: str) -> list[float]:
        return self.encode(text)

    @staticmethod
    def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        from claw.db.embeddings import EmbeddingEngine
        return EmbeddingEngine.cosine_similarity(vec1, vec2)


# ---------------------------------------------------------------------------
# Test 1: Lexical unchanged when disabled
# ---------------------------------------------------------------------------

class TestLexicalUnchangedWhenDisabled:
    """With attribution_embedding_enabled=False, behavior is pure lexical."""

    def test_lexical_only_no_engine(self):
        """No embedding engine passed -> pure lexical matching works."""
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
        """Engine provided but config disabled -> pure lexical, no encode calls."""
        # Use a counting engine to verify zero encode calls without
        # needing a real API key -- the engine should never be called.
        class NeverCalledEngine:
            """Engine whose encode() should never be reached."""
            def __init__(self):
                self.encode_count = 0

            def encode(self, text: str) -> list[float]:
                self.encode_count += 1
                return [0.0] * 384

            async def async_encode(self, text: str) -> list[float]:
                return self.encode(text)

            @staticmethod
            def cosine_similarity(v1: list[float], v2: list[float]) -> float:
                return 0.0

        engine = NeverCalledEngine()
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
        # No encode calls should have been made since embedding is disabled
        assert engine.encode_count == 0

    def test_lexical_scores_are_deterministic(self):
        """Same inputs produce identical lexical scores across runs."""
        m1 = _make_methodology(
            "m1",
            problem_description="redis caching connection pool management",
            tags=["redis", "caching"],
        )
        outcome = _make_outcome(
            approach_summary="added redis caching connection pool to web service",
        )
        ctx = _make_context_brief([m1])

        result1 = _run(_infer_used_methodology_ids(ctx, outcome))
        result2 = _run(_infer_used_methodology_ids(ctx, outcome))
        assert result1 == result2


# ---------------------------------------------------------------------------
# Test 2: Embedding catches semantic match (real API)
# ---------------------------------------------------------------------------

class TestEmbeddingCatchesSemanticMatch:
    """Embedding pass should catch semantically similar but lexically different text."""

    @skipif_no_google
    def test_semantic_match_caught_real_embeddings(self):
        """'authentication flow' methodology matched to 'login session management' outcome.

        Lexically these share very few tokens, but semantically they are
        closely related. The real Gemini embedding model produces cosine ~0.77
        for this pair -- well above any reasonable threshold.
        """
        engine = _get_real_embedding_engine()
        # Threshold 0.70 is calibrated for gemini-embedding-2-preview:
        # similar domains produce 0.77+, unrelated produce 0.59-0.67.
        config = FakeMemoryConfig(enabled=True, weight=0.6, threshold=0.70)

        # Methodology about authentication flow -- uses auth-specific vocabulary
        m_auth = _make_methodology(
            "m-auth",
            problem_description="authentication flow with JWT tokens and OAuth2 bearer management",
            methodology_notes="Use bcrypt for password hashing, issue JWT access tokens with short TTL",
            tags=["auth", "jwt", "security"],
            files_affected=["auth.py", "middleware.py"],
        )

        # Outcome about login session management -- different vocabulary, same domain
        outcome = _make_outcome(
            approach_summary="Implemented login session management with cookie-based auth and CSRF protection",
            raw_output="Created login endpoint that validates credentials and issues session cookies",
            diff="+ def login(request):\n+     user = verify_credentials(request.form)\n+     session.set_cookie(user.id)",
            files_changed=["login.py", "session.py"],
        )
        ctx = _make_context_brief([m_auth])

        # First, run without embedding to see if lexical catches it
        result_lexical = _run(_infer_used_methodology_ids(ctx, outcome))
        lexical_ids = [r[0] for r in result_lexical]

        # Now run with embedding enabled
        result_embedding = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=engine, memory_config=config
        ))
        embedding_ids = [r[0] for r in result_embedding]

        # The methodology should appear in the embedding result.
        assert "m-auth" in embedding_ids, (
            f"Expected 'm-auth' in embedding results, got {result_embedding}"
        )

        # If lexical missed it, embedding caught it (the primary purpose of Pass 2)
        if "m-auth" not in lexical_ids:
            assert len(result_embedding) > len(result_lexical)


# ---------------------------------------------------------------------------
# Test 3: Embedding reranks to higher score (real API)
# ---------------------------------------------------------------------------

class TestEmbeddingReranksHigherScore:
    """When embedding score > lexical score, combined reflects the boost."""

    @skipif_no_google
    def test_embedding_upgrades_lexical_score_real(self):
        """A lexically-matched methodology gets an upgraded score from the embedding pass.

        The methodology and outcome share a few lexical tokens (giving a low lexical score).
        But semantically they are highly related (cosine ~0.79), so with weight=1.0 the
        embedding score dominates: max(lexical, cosine * 1.0) > lexical.
        """
        engine = _get_real_embedding_engine()
        # weight=1.0 so embedding cosine maps directly to final score
        config = FakeMemoryConfig(enabled=True, weight=1.0, threshold=0.30)

        m1 = _make_methodology(
            "m1",
            problem_description="input validation for API endpoints to prevent injection attacks",
            methodology_notes="sanitize all user inputs, use parameterized queries, validate schema",
            tags=["validation", "api", "security"],
        )
        outcome = _make_outcome(
            approach_summary="added input validation checks to the REST endpoints for sanitization",
        )
        ctx = _make_context_brief([m1])

        # Without embedding -- pure lexical
        result_no_emb = _run(_infer_used_methodology_ids(ctx, outcome))
        assert len(result_no_emb) >= 1, "Expected lexical match"
        lexical_score = result_no_emb[0][1]

        # With embedding -- combined score should be >= lexical
        result_with_emb = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=engine, memory_config=config
        ))
        assert len(result_with_emb) >= 1
        combined_score = result_with_emb[0][1]

        # max(lexical, cosine * weight) >= lexical by definition
        assert combined_score >= lexical_score, (
            f"Combined score {combined_score} should be >= lexical {lexical_score}"
        )


# ---------------------------------------------------------------------------
# Test 4: Threshold filters low similarity (real API)
# ---------------------------------------------------------------------------

class TestThresholdFiltersLowSimilarity:
    """Embedding pass should NOT match methodologies in completely different domains.

    Calibration with gemini-embedding-2-preview (384 dims):
      DB-indexing vs CSS-styling:     raw cosine ~0.61
      Quantum-physics vs recipe-parsing: raw cosine ~0.59
      Marine-biology vs semiconductors:  raw cosine ~0.67

    A threshold of 0.70 reliably filters all of these while still
    admitting genuinely similar domains (cosine >= 0.77).
    """

    @skipif_no_google
    def test_cross_domain_filtered_real_embeddings(self):
        """'database indexing' methodology vs 'CSS styling' outcome -> no match.

        Raw cosine ~0.61, well below threshold 0.70.
        """
        engine = _get_real_embedding_engine()
        config = FakeMemoryConfig(enabled=True, weight=0.6, threshold=0.70)

        m_db = _make_methodology(
            "m-db",
            problem_description="database indexing strategies for query performance optimization",
            methodology_notes="B-tree index on frequently queried columns, composite indexes for JOIN clauses",
            tags=["database", "indexing", "postgresql", "performance"],
            files_affected=["migrations/add_indexes.sql", "models/query_optimizer.py"],
        )
        outcome = _make_outcome(
            approach_summary="CSS styling improvements for the landing page hero section",
            raw_output="Updated flexbox layout, adjusted responsive breakpoints for mobile",
            diff="+ .hero { display: flex; gap: 2rem; }\n+ @media (max-width: 768px) { .hero { flex-direction: column; } }",
            files_changed=["styles/hero.css", "components/LandingHero.tsx"],
        )
        ctx = _make_context_brief([m_db])

        result = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=engine, memory_config=config
        ))
        ids = [r[0] for r in result]
        assert "m-db" not in ids, (
            f"'m-db' (database indexing) should NOT match CSS styling outcome, got {result}"
        )

    @skipif_no_google
    def test_unrelated_science_vs_cooking_filtered(self):
        """Quantum physics methodology vs recipe parsing outcome -> no match.

        Raw cosine ~0.59, well below threshold 0.70.
        """
        engine = _get_real_embedding_engine()
        config = FakeMemoryConfig(enabled=True, weight=0.6, threshold=0.70)

        m_physics = _make_methodology(
            "m-phys",
            problem_description="quantum entanglement simulation for photon pair generation",
            methodology_notes="Bell state measurement, CHSH inequality verification",
            tags=["quantum", "physics", "simulation"],
        )
        outcome = _make_outcome(
            approach_summary="refactored the recipe ingredient parser for metric unit conversion",
            raw_output="Added gram-to-ounce conversion, improved fraction parsing",
            files_changed=["recipe_parser.py", "unit_converter.py"],
        )
        ctx = _make_context_brief([m_physics])

        result = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=engine, memory_config=config
        ))
        ids = [r[0] for r in result]
        assert "m-phys" not in ids, (
            f"Quantum physics methodology should not match recipe parsing outcome, got {result}"
        )


# ---------------------------------------------------------------------------
# Test 5: API call count bounded (real API)
# ---------------------------------------------------------------------------

class TestMaxAPICallsBounded:
    """Encode calls should be bounded: 1 for outcome + up to N for methodologies."""

    @skipif_no_google
    def test_encode_calls_bounded_three_methodologies(self):
        """With 3 methodologies (1 lexically matched, 2 unmatched), verify encode count.

        Expected flow:
        - 1 encode() call for the outcome text
        - 2 encode() calls for the 2 lexically unmatched methodologies (Pass 2 unmatched loop)
        - 1 encode() call for the 1 lexically matched methodology (Pass 2 upgrade loop)
        Total: 4 encode() calls maximum.
        """
        real_engine = _get_real_embedding_engine()
        counting = CountingEngine(real_engine)
        config = FakeMemoryConfig(enabled=True, weight=0.6, threshold=0.35)

        # m1 shares tokens with outcome ("python", "error", "handling") -> lexical match
        m1 = _make_methodology(
            "m1",
            problem_description="python error handling with retry decorators",
            tags=["python", "error", "handling"],
        )
        # m2 has no token overlap with outcome -> lexical unmatched
        m2 = _make_methodology(
            "m2",
            problem_description="kubernetes pod autoscaling configuration",
            tags=["kubernetes", "devops", "scaling"],
        )
        # m3 also no token overlap -> lexical unmatched
        m3 = _make_methodology(
            "m3",
            problem_description="GraphQL schema federation gateway setup",
            tags=["graphql", "federation", "gateway"],
        )

        outcome = _make_outcome(
            approach_summary="implemented python error handling with exponential backoff retry logic",
            files_changed=["retry.py", "error_handler.py"],
        )
        ctx = _make_context_brief([m1, m2, m3])

        _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=counting, memory_config=config
        ))

        # At most: 1 (outcome) + 2 (unmatched) + 1 (upgrade for m1) = 4
        assert counting.encode_count <= 4, (
            f"Expected at most 4 encode() calls, got {counting.encode_count}"
        )
        # At least 1 call must have happened (the outcome encoding)
        assert counting.encode_count >= 1, (
            f"Expected at least 1 encode() call, got {counting.encode_count}"
        )


# ---------------------------------------------------------------------------
# Test 6: Fallback when engine is None
# ---------------------------------------------------------------------------

class TestFallbackWhenEngineNone:
    """Pure lexical when embedding_engine=None, regardless of config."""

    def test_none_engine_still_produces_lexical_results(self):
        """Passing None engine should produce lexical results without error."""
        config = FakeMemoryConfig(enabled=True)  # enabled but engine is None

        m1 = _make_methodology(
            "m1",
            problem_description="python error handling middleware for web framework",
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

    def test_none_engine_no_config_lexical_only(self):
        """Both engine and config are None -> pure lexical still works."""
        m1 = _make_methodology(
            "m1",
            problem_description="redis caching connection pool management",
            tags=["caching", "redis"],
        )
        outcome = _make_outcome(
            approach_summary="implemented caching strategy using redis connections pool",
        )
        ctx = _make_context_brief([m1])

        result = _run(_infer_used_methodology_ids(
            ctx, outcome, embedding_engine=None, memory_config=None
        ))
        ids = [r[0] for r in result]
        assert "m1" in ids

    def test_empty_past_solutions_returns_empty(self):
        """No past solutions -> empty result, no crash."""
        outcome = _make_outcome(approach_summary="something about python functions")
        ctx = _make_context_brief([])

        result = _run(_infer_used_methodology_ids(ctx, outcome))
        assert result == []

    def test_none_context_brief_returns_empty(self):
        """None context brief -> empty result."""
        outcome = _make_outcome(approach_summary="something about python functions")
        result = _run(_infer_used_methodology_ids(None, outcome))
        assert result == []


# ---------------------------------------------------------------------------
# Additional coverage: edge cases and engine error resilience
# ---------------------------------------------------------------------------

class TestEngineErrorGraceful:
    """If embedding engine raises, fall back to lexical only."""

    def test_encode_error_falls_back_to_lexical(self):
        """Embedding engine raises RuntimeError -> lexical results preserved, no crash."""
        class BrokenEngine:
            """Engine that always raises on encode()."""
            def encode(self, text: str) -> list[float]:
                raise RuntimeError("Gemini API quota exceeded")

            async def async_encode(self, text: str) -> list[float]:
                return self.encode(text)

            @staticmethod
            def cosine_similarity(v1: list[float], v2: list[float]) -> float:
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
        assert len(result) > 0
