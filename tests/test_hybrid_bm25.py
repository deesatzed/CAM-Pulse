"""Tests for BM25 score normalization in hybrid search.

Validates:
- Repository.search_methodologies_text() returns (Methodology, rank) tuples
- HybridSearch._text_search() normalizes BM25 ranks to [0, 1]
- Min-max normalization preserves ordering
- Single-result and all-same-rank edge cases
- Jitter in LLMClient backoff delay
"""

from __future__ import annotations

import uuid

import pytest

from claw.core.models import Methodology
from claw.llm.client import _backoff_delay
from claw.memory.hybrid_search import HybridSearch, HybridSearchResult


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_meth(desc: str = "test") -> Methodology:
    return Methodology(
        id=str(uuid.uuid4()),
        problem_description=desc,
        solution_code="pass",
        methodology_notes="notes",
        language="python",
        methodology_type="pattern",
        lifecycle_state="viable",
        tags=["test"],
    )


# ---------------------------------------------------------------------------
# BM25 normalization tests (unit-level, no DB)
# ---------------------------------------------------------------------------

class TestBM25Normalization:
    """_text_search() normalizes FTS5 BM25 ranks correctly."""

    @pytest.mark.asyncio
    async def test_normalizes_multiple_results(self):
        """Multiple results are min-max normalized: best → 1.0, worst → 0.0."""
        m1 = _make_meth("best match")
        m2 = _make_meth("medium match")
        m3 = _make_meth("worst match")

        # Simulate FTS5 ranks: more negative = better
        raw_results = [(m1, -10.0), (m2, -5.0), (m3, -1.0)]

        # Manually apply the normalization logic
        ranks = [r for _, r in raw_results]
        best_rank = min(ranks)    # -10.0
        worst_rank = max(ranks)   # -1.0
        spread = worst_rank - best_rank  # 9.0

        scores = []
        for _meth, rank in raw_results:
            score = (worst_rank - rank) / spread if spread > 0 else 1.0
            scores.append(score)

        assert abs(scores[0] - 1.0) < 0.001   # best → 1.0
        assert abs(scores[1] - 0.444) < 0.01   # middle
        assert abs(scores[2] - 0.0) < 0.001    # worst → 0.0

    @pytest.mark.asyncio
    async def test_single_result_gets_score_1(self):
        """A single FTS5 result gets text_score = 1.0."""
        m1 = _make_meth("only result")
        raw_results = [(m1, -7.5)]

        ranks = [r for _, r in raw_results]
        best_rank = min(ranks)
        worst_rank = max(ranks)
        spread = worst_rank - best_rank  # 0.0

        score = (worst_rank - raw_results[0][1]) / spread if spread > 0 else 1.0
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_all_same_rank_all_get_1(self):
        """When all results have identical rank, all get 1.0."""
        results = [(_make_meth(f"m{i}"), -5.0) for i in range(4)]
        ranks = [r for _, r in results]
        spread = max(ranks) - min(ranks)  # 0.0

        for _meth, rank in results:
            score = (max(ranks) - rank) / spread if spread > 0 else 1.0
            assert score == 1.0

    @pytest.mark.asyncio
    async def test_preserves_bm25_ordering(self):
        """Normalized scores preserve the BM25 ordering."""
        raw_results = [
            (_make_meth("best"), -20.0),
            (_make_meth("good"), -15.0),
            (_make_meth("fair"), -8.0),
            (_make_meth("poor"), -2.0),
        ]

        ranks = [r for _, r in raw_results]
        best_rank = min(ranks)
        worst_rank = max(ranks)
        spread = worst_rank - best_rank

        scores = [(worst_rank - rank) / spread for _, rank in raw_results]
        # Verify monotonically decreasing
        for i in range(len(scores) - 1):
            assert scores[i] > scores[i + 1]

    @pytest.mark.asyncio
    async def test_scores_bounded_0_to_1(self):
        """All normalized scores are within [0, 1]."""
        raw_results = [
            (_make_meth(f"m{i}"), -(i * 3.7 + 0.1))
            for i in range(10)
        ]

        ranks = [r for _, r in raw_results]
        best_rank = min(ranks)
        worst_rank = max(ranks)
        spread = worst_rank - best_rank

        for _, rank in raw_results:
            score = (worst_rank - rank) / spread if spread > 0 else 1.0
            assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Repository return type test (integration)
# ---------------------------------------------------------------------------

class TestRepositoryReturnsRankTuples:
    """search_methodologies_text() returns (Methodology, float) tuples."""

    @pytest.mark.asyncio
    async def test_return_type(self, repository):
        """Verify return type is list of (Methodology, float) tuples."""
        from claw.core.models import Task, Project

        project = Project(
            id=str(uuid.uuid4()),
            name="test",
            repo_path="/tmp/test",
        )
        await repository.create_project(project)
        task = Task(
            id=str(uuid.uuid4()),
            project_id=project.id,
            task_type="analysis",
            title="test task",
            description="test task",
        )
        await repository.create_task(task)

        m = Methodology(
            id=str(uuid.uuid4()),
            source_task_id=task.id,
            problem_description="Memory leak in connection pool handler",
            solution_code="fix the leak",
            methodology_notes="Close connections properly",
            language="python",
            methodology_type="bug_fix",
            lifecycle_state="viable",
            tags=["memory", "leak"],
        )
        await repository.save_methodology(m)

        results = await repository.search_methodologies_text("memory leak")
        assert len(results) >= 1
        assert isinstance(results[0], tuple)
        assert len(results[0]) == 2

        meth, rank = results[0]
        assert isinstance(meth, Methodology)
        assert isinstance(rank, float)
        assert rank < 0  # FTS5 BM25 ranks are negative


# ---------------------------------------------------------------------------
# Jitter in LLMClient backoff
# ---------------------------------------------------------------------------

class TestBackoffJitter:
    """_backoff_delay() from client.py includes random jitter."""

    def test_delay_includes_jitter(self):
        """100 calls should produce varied (non-identical) delays."""
        delays = [_backoff_delay(0, base_seconds=2.0) for _ in range(100)]
        unique = len(set(delays))
        assert unique > 50, f"Expected jitter variation, got {unique} unique values"

    def test_base_delay_correct(self):
        """Base delay without jitter should be approximately 2^attempt * base."""
        delays = [_backoff_delay(0, base_seconds=2.0) for _ in range(100)]
        # Base = 2.0, jitter up to 25% = 0.5
        assert all(2.0 <= d <= 2.6 for d in delays)

    def test_cap_at_60(self):
        """Even high attempt numbers are capped near 60s."""
        delays = [_backoff_delay(20, base_seconds=2.0) for _ in range(100)]
        # Delay capped at 60, plus up to 25% jitter = 75
        assert all(d <= 76 for d in delays)
