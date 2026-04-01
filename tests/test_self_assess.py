"""Tests for miner.assess_findings_against_existing — post-mine self-assessment."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

from claw.miner import (
    MiningFinding,
    MiningReport,
    RepoMiningResult,
    assess_findings_against_existing,
)


# ---------------------------------------------------------------------------
# Helpers — lightweight stand-ins (NOT mocks — real dataclass instances)
# ---------------------------------------------------------------------------

def _finding(title: str = "structured logging", desc: str = "JSON log output",
             source_repo: str = "repo-a") -> MiningFinding:
    """Create a real MiningFinding with sensible defaults."""
    return MiningFinding(
        title=title,
        description=desc,
        category="architecture",
        source_repo=source_repo,
    )


def _report(findings: list[MiningFinding] | None = None,
            skipped: bool = False, error: str | None = None) -> MiningReport:
    """Build a MiningReport with a single RepoMiningResult."""
    result = RepoMiningResult(
        repo_name="test-repo",
        repo_path="/tmp/test-repo",
        findings=findings or [],
        skipped=skipped,
        error=error,
    )
    report = MiningReport()
    report.repo_results = [result]
    report.repos_scanned = 1
    report.total_findings = len(result.findings)
    return report


@dataclass
class FakeMethodology:
    """Real object mimicking Methodology with similarity attr."""
    problem_description: str
    similarity: float = 0.0


class FakeSemanticMemory:
    """Real SemanticMemory stand-in returning pre-configured results.

    NOT a mock — this is a concrete class with a real async search() method.
    We use this instead of the actual SemanticMemory to avoid needing a
    database + embedding engine while still exercising the full code path.
    """

    def __init__(self, results: list[list[FakeMethodology]] | None = None,
                 error: Exception | None = None):
        self._results = results or []
        self._call_idx = 0
        self._error = error

    async def search(self, query: str, limit: int = 1) -> list[FakeMethodology]:
        if self._error:
            raise self._error
        if self._call_idx < len(self._results):
            result = self._results[self._call_idx]
            self._call_idx += 1
            return result
        return []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAssessFindings:
    def _run(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def test_duplicate_classification(self):
        """Finding with cosine > 0.85 is classified as DUPLICATE."""
        report = _report(findings=[_finding()])
        mem = FakeSemanticMemory(results=[
            [FakeMethodology(problem_description="structured JSON logging", similarity=0.92)],
        ])
        assessments = self._run(assess_findings_against_existing(
            report, embedding_engine=None, repository=None, semantic_memory=mem,
        ))
        assert len(assessments) == 1
        assert assessments[0]["classification"] == "DUPLICATE"
        assert assessments[0]["similarity"] == 0.92

    def test_partial_gap_classification(self):
        """Finding with 0.60 <= cosine <= 0.85 is PARTIAL_GAP."""
        report = _report(findings=[_finding(title="retry backoff")])
        mem = FakeSemanticMemory(results=[
            [FakeMethodology(problem_description="exponential retry", similarity=0.72)],
        ])
        assessments = self._run(assess_findings_against_existing(
            report, embedding_engine=None, repository=None, semantic_memory=mem,
        ))
        assert assessments[0]["classification"] == "PARTIAL_GAP"

    def test_novel_classification(self):
        """Finding with cosine < 0.60 is NOVEL."""
        report = _report(findings=[_finding(title="quantum error correction")])
        mem = FakeSemanticMemory(results=[
            [FakeMethodology(problem_description="unrelated stuff", similarity=0.3)],
        ])
        assessments = self._run(assess_findings_against_existing(
            report, embedding_engine=None, repository=None, semantic_memory=mem,
        ))
        assert assessments[0]["classification"] == "NOVEL"

    def test_no_results_is_novel(self):
        """When semantic memory returns nothing, classify as NOVEL."""
        report = _report(findings=[_finding()])
        mem = FakeSemanticMemory(results=[[]])
        assessments = self._run(assess_findings_against_existing(
            report, embedding_engine=None, repository=None, semantic_memory=mem,
        ))
        assert assessments[0]["classification"] == "NOVEL"
        assert assessments[0]["similarity"] == 0.0

    def test_search_error_returns_novel(self):
        """When semantic search raises, finding defaults to NOVEL."""
        report = _report(findings=[_finding()])
        mem = FakeSemanticMemory(error=RuntimeError("connection refused"))
        assessments = self._run(assess_findings_against_existing(
            report, embedding_engine=None, repository=None, semantic_memory=mem,
        ))
        assert assessments[0]["classification"] == "NOVEL"
        assert "search error" in assessments[0]["closest_match"]

    def test_skipped_repos_excluded(self):
        """Skipped repos produce no assessments."""
        report = _report(findings=[_finding()], skipped=True)
        mem = FakeSemanticMemory()
        assessments = self._run(assess_findings_against_existing(
            report, embedding_engine=None, repository=None, semantic_memory=mem,
        ))
        assert len(assessments) == 0

    def test_errored_repos_excluded(self):
        """Repos with errors produce no assessments."""
        report = _report(findings=[_finding()], error="auth failed")
        mem = FakeSemanticMemory()
        assessments = self._run(assess_findings_against_existing(
            report, embedding_engine=None, repository=None, semantic_memory=mem,
        ))
        assert len(assessments) == 0

    def test_multiple_findings(self):
        """Multiple findings each get their own assessment."""
        report = _report(findings=[
            _finding(title="logging"),
            _finding(title="schemas"),
            _finding(title="novel thing"),
        ])
        mem = FakeSemanticMemory(results=[
            [FakeMethodology(problem_description="existing logging", similarity=0.90)],
            [FakeMethodology(problem_description="existing schemas", similarity=0.70)],
            [FakeMethodology(problem_description="unrelated", similarity=0.20)],
        ])
        assessments = self._run(assess_findings_against_existing(
            report, embedding_engine=None, repository=None, semantic_memory=mem,
        ))
        assert len(assessments) == 3
        assert assessments[0]["classification"] == "DUPLICATE"
        assert assessments[1]["classification"] == "PARTIAL_GAP"
        assert assessments[2]["classification"] == "NOVEL"

    def test_boundary_085(self):
        """Exactly 0.85 is NOT a duplicate (> 0.85 required)."""
        report = _report(findings=[_finding()])
        mem = FakeSemanticMemory(results=[
            [FakeMethodology(problem_description="match", similarity=0.85)],
        ])
        assessments = self._run(assess_findings_against_existing(
            report, embedding_engine=None, repository=None, semantic_memory=mem,
        ))
        assert assessments[0]["classification"] == "PARTIAL_GAP"

    def test_boundary_060(self):
        """Exactly 0.60 is PARTIAL_GAP (>= 0.60 required)."""
        report = _report(findings=[_finding()])
        mem = FakeSemanticMemory(results=[
            [FakeMethodology(problem_description="match", similarity=0.60)],
        ])
        assessments = self._run(assess_findings_against_existing(
            report, embedding_engine=None, repository=None, semantic_memory=mem,
        ))
        assert assessments[0]["classification"] == "PARTIAL_GAP"

    def test_dict_result_format(self):
        """Semantic memory returning dicts (not objects) should also work."""
        report = _report(findings=[_finding()])

        class DictMem(FakeSemanticMemory):
            async def search(self, query: str, limit: int = 1) -> list:
                return [{"problem_description": "dict match", "similarity": 0.55}]

        assessments = self._run(assess_findings_against_existing(
            report, embedding_engine=None, repository=None, semantic_memory=DictMem(),
        ))
        assert assessments[0]["classification"] == "NOVEL"
        assert assessments[0]["closest_match"] == "dict match"

    def test_source_repo_preserved(self):
        """Assessment includes source_repo from the original finding."""
        report = _report(findings=[_finding(source_repo="my-repo")])
        mem = FakeSemanticMemory(results=[
            [FakeMethodology(problem_description="x", similarity=0.5)],
        ])
        assessments = self._run(assess_findings_against_existing(
            report, embedding_engine=None, repository=None, semantic_memory=mem,
        ))
        assert assessments[0]["source_repo"] == "my-repo"
