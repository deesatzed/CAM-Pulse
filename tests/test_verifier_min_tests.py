"""Tests for the minimum test count verifier check.

Covers:
  - _extract_minimum_test_requirement() with various description patterns
  - minimum_test_count violation in verify() flow
  - Edge cases (no tests_after, no requirement, exact threshold)
"""

from __future__ import annotations

import pytest

from claw.core.models import Task, TaskContext, TaskOutcome, VerificationResult
from claw.verifier import Verifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_context(description: str = "") -> TaskContext:
    task = Task(
        project_id="proj-test",
        title="Build test module",
        description=description,
        priority=5,
        task_type="architecture",
    )
    return TaskContext(task=task)


def _make_verifier(min_test_count: int = 0) -> Verifier:
    return Verifier(
        embedding_engine=None,
        llm_client=None,
        min_test_count=min_test_count,
    )


# ---------------------------------------------------------------------------
# _extract_minimum_test_requirement tests
# ---------------------------------------------------------------------------

class TestExtractMinimumTestRequirement:
    def test_range_pattern_returns_lower_bound(self):
        ctx = _make_task_context("Include 22-28 tests covering the module.")
        v = _make_verifier()
        assert v._extract_minimum_test_requirement(ctx) == 22

    def test_at_least_pattern(self):
        ctx = _make_task_context("Write at least 15 tests for coverage.")
        v = _make_verifier()
        assert v._extract_minimum_test_requirement(ctx) == 15

    def test_minimum_pattern(self):
        ctx = _make_task_context("Require minimum 20 tests.")
        v = _make_verifier()
        assert v._extract_minimum_test_requirement(ctx) == 20

    def test_covering_list_counts_items(self):
        ctx = _make_task_context(
            "Include tests covering: single lookup, batch check, unknown drug, "
            "case-insensitive, severity filter, alias resolution."
        )
        v = _make_verifier()
        assert v._extract_minimum_test_requirement(ctx) == 6

    def test_no_pattern_returns_config_default(self):
        ctx = _make_task_context("Build a great module with tests.")
        v = _make_verifier(min_test_count=5)
        assert v._extract_minimum_test_requirement(ctx) == 5

    def test_no_pattern_no_config_returns_zero(self):
        ctx = _make_task_context("Build a great module with tests.")
        v = _make_verifier(min_test_count=0)
        assert v._extract_minimum_test_requirement(ctx) == 0

    def test_range_with_en_dash(self):
        ctx = _make_task_context("Include 30\u201340 tests.")
        v = _make_verifier()
        assert v._extract_minimum_test_requirement(ctx) == 30

    def test_explicit_pattern_takes_precedence_over_covering_list(self):
        ctx = _make_task_context(
            "Write at least 10 tests. Include tests covering: a, b, c."
        )
        v = _make_verifier()
        # "at least 10" should NOT match because the range/explicit patterns
        # are checked first; here there's no range so "at least 10" hits
        assert v._extract_minimum_test_requirement(ctx) == 10


# ---------------------------------------------------------------------------
# Minimum test count violation in verify() flow
# ---------------------------------------------------------------------------

class TestMinimumTestCountViolation:
    @pytest.mark.asyncio
    async def test_violation_when_tests_below_minimum(self):
        v = _make_verifier(min_test_count=20)
        ctx = _make_task_context("Build a module.")
        outcome = TaskOutcome(
            approach_summary="Built the module",
            tests_passed=True,
            files_changed=["src/mod.py"],
            raw_output="done",
            diff="+ def foo(): pass",
        )
        # Patch run_tests to return passing with low count
        async def fake_run_tests(workspace):
            return True, "10 passed in 0.5s", 10

        v.run_tests = fake_run_tests
        result = await v.verify(outcome, ctx, workspace_dir="/tmp/fake")
        assert not result.approved
        assert any(v["check"] == "minimum_test_count" for v in result.violations)
        assert "10 found" in result.violations[0]["detail"]
        assert "20 required" in result.violations[0]["detail"]

    @pytest.mark.asyncio
    async def test_no_violation_when_tests_meet_minimum(self):
        v = _make_verifier(min_test_count=10)
        ctx = _make_task_context("Build a module.")
        outcome = TaskOutcome(
            approach_summary="Built the module",
            tests_passed=True,
            files_changed=["src/mod.py"],
            raw_output="done",
            diff="+ def foo(): pass",
        )
        async def fake_run_tests(workspace):
            return True, "15 passed in 0.5s", 15

        v.run_tests = fake_run_tests
        result = await v.verify(outcome, ctx, workspace_dir="/tmp/fake")
        assert result.approved
        assert not any(v["check"] == "minimum_test_count" for v in result.violations)

    @pytest.mark.asyncio
    async def test_no_violation_when_min_is_zero(self):
        v = _make_verifier(min_test_count=0)
        ctx = _make_task_context("Build a module.")
        outcome = TaskOutcome(
            approach_summary="Built the module",
            tests_passed=True,
            files_changed=["src/mod.py"],
            raw_output="done",
            diff="+ def foo(): pass",
        )
        async def fake_run_tests(workspace):
            return True, "3 passed in 0.5s", 3

        v.run_tests = fake_run_tests
        result = await v.verify(outcome, ctx, workspace_dir="/tmp/fake")
        assert result.approved

    @pytest.mark.asyncio
    async def test_no_violation_when_no_workspace(self):
        """No tests run → no minimum test check."""
        v = _make_verifier(min_test_count=20)
        ctx = _make_task_context("Build a module.")
        outcome = TaskOutcome(
            approach_summary="Built the module",
            tests_passed=True,
            files_changed=["src/mod.py"],
            raw_output="done",
            diff="+ def foo(): pass",
        )
        result = await v.verify(outcome, ctx, workspace_dir=None)
        assert result.approved
        assert not any(v["check"] == "minimum_test_count" for v in result.violations)

    @pytest.mark.asyncio
    async def test_spec_description_overrides_config(self):
        """Spec says "at least 25 tests" but config says 5 → use 25."""
        v = _make_verifier(min_test_count=5)
        ctx = _make_task_context("Write at least 25 tests for coverage.")
        outcome = TaskOutcome(
            approach_summary="Built the module",
            tests_passed=True,
            files_changed=["src/mod.py"],
            raw_output="done",
            diff="+ def foo(): pass",
        )
        async def fake_run_tests(workspace):
            return True, "10 passed in 0.5s", 10

        v.run_tests = fake_run_tests
        result = await v.verify(outcome, ctx, workspace_dir="/tmp/fake")
        assert not result.approved
        violation = [v for v in result.violations if v["check"] == "minimum_test_count"][0]
        assert "25 required" in violation["detail"]

    @pytest.mark.asyncio
    async def test_exact_threshold_passes(self):
        """Exactly meeting the minimum is acceptable."""
        v = _make_verifier(min_test_count=10)
        ctx = _make_task_context("Build a module.")
        outcome = TaskOutcome(
            approach_summary="Built the module",
            tests_passed=True,
            files_changed=["src/mod.py"],
            raw_output="done",
            diff="+ def foo(): pass",
        )
        async def fake_run_tests(workspace):
            return True, "10 passed in 0.5s", 10

        v.run_tests = fake_run_tests
        result = await v.verify(outcome, ctx, workspace_dir="/tmp/fake")
        assert result.approved
