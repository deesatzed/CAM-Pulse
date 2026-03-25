"""Tests for metric expectations enforcement in the verifier.

Covers:
  - MetricExpectation model
  - _parse_coverage_pct() extraction from pytest-cov output
  - _extract_metrics_from_description() auto-extraction from task text
  - _collect_metric_expectations() combining contract + description
  - _evaluate_metric() operator comparisons
  - _check_metric_expectations() full evaluation pipeline
  - Coverage metric as hard violation in verify() flow
  - Soft vs hard metric expectations
"""

from __future__ import annotations

import pytest

from claw.core.models import (
    ExpectationContract,
    MetricExpectation,
    Task,
    TaskContext,
    TaskOutcome,
    VerificationResult,
)
from claw.verifier import Verifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_context(
    description: str = "",
    metric_expectations: list[MetricExpectation] | None = None,
) -> TaskContext:
    task = Task(
        project_id="proj-test",
        title="Build test module",
        description=description,
        priority=5,
        task_type="architecture",
    )
    ctx = TaskContext(task=task)
    if metric_expectations is not None:
        ctx.expectation_contract = ExpectationContract(
            goal=description,
            metric_expectations=metric_expectations,
        )
    return ctx


def _make_verifier() -> Verifier:
    return Verifier(embedding_engine=None, llm_client=None)


def _make_outcome(files: list[str] | None = None) -> TaskOutcome:
    return TaskOutcome(
        approach_summary="Built the module",
        tests_passed=True,
        files_changed=files or ["src/mod.py"],
        raw_output="done",
        diff="+ def foo(): pass",
    )


# ---------------------------------------------------------------------------
# MetricExpectation model
# ---------------------------------------------------------------------------

class TestMetricExpectationModel:
    def test_defaults(self):
        m = MetricExpectation(name="test_count", metric="min_test_count")
        assert m.operator == "gte"
        assert m.value == 0.0
        assert m.hard is True

    def test_with_values(self):
        m = MetricExpectation(
            name="coverage",
            metric="min_coverage_pct",
            operator="gte",
            value=90.0,
            hard=True,
        )
        assert m.name == "coverage"
        assert m.value == 90.0

    def test_soft_metric(self):
        m = MetricExpectation(
            name="file_count",
            metric="min_files_changed",
            operator="gte",
            value=3.0,
            hard=False,
        )
        assert m.hard is False


# ---------------------------------------------------------------------------
# _parse_coverage_pct
# ---------------------------------------------------------------------------

class TestParseCoveragePct:
    def test_standard_output(self):
        output = """
Name              Stmts   Miss  Cover   Missing
-----------------------------------------------
app/__init__.py       1      0   100%
app/cli.py           31     10    68%   32-42, 46
app/data.py          65      0   100%
-----------------------------------------------
TOTAL                97     10    90%
"""
        assert Verifier._parse_coverage_pct(output) == 90.0

    def test_full_coverage(self):
        output = "TOTAL                50      0   100%"
        assert Verifier._parse_coverage_pct(output) == 100.0

    def test_zero_coverage(self):
        output = "TOTAL                50     50     0%"
        assert Verifier._parse_coverage_pct(output) == 0.0

    def test_no_coverage_output(self):
        output = "22 passed in 0.05s"
        assert Verifier._parse_coverage_pct(output) is None

    def test_empty_string(self):
        assert Verifier._parse_coverage_pct("") is None


# ---------------------------------------------------------------------------
# _extract_metrics_from_description
# ---------------------------------------------------------------------------

class TestExtractMetricsFromDescription:
    def test_greater_than_90_percent_coverage(self):
        metrics = Verifier._extract_metrics_from_description(
            "Build a module with greater than 90 percent coverage target."
        )
        assert len(metrics) == 1
        assert metrics[0].metric == "min_coverage_pct"
        assert metrics[0].value == 90.0
        assert metrics[0].hard is True

    def test_greater_than_symbol(self):
        metrics = Verifier._extract_metrics_from_description(
            "Ensure >85% coverage."
        )
        assert len(metrics) == 1
        assert metrics[0].value == 85.0

    def test_at_least_coverage(self):
        metrics = Verifier._extract_metrics_from_description(
            "at least 95% coverage"
        )
        assert len(metrics) == 1
        assert metrics[0].value == 95.0

    def test_coverage_target_equals(self):
        metrics = Verifier._extract_metrics_from_description(
            "coverage target: 80%"
        )
        assert len(metrics) == 1
        assert metrics[0].value == 80.0

    def test_no_coverage_pattern(self):
        metrics = Verifier._extract_metrics_from_description(
            "Build a module with tests."
        )
        assert len(metrics) == 0

    def test_does_not_duplicate_on_multiple_patterns(self):
        metrics = Verifier._extract_metrics_from_description(
            "above 90% coverage target. Also ensure >90% coverage."
        )
        # Should only extract once (first match wins)
        assert len(metrics) == 1


# ---------------------------------------------------------------------------
# _collect_metric_expectations
# ---------------------------------------------------------------------------

class TestCollectMetricExpectations:
    def test_explicit_from_contract(self):
        ctx = _make_task_context(
            description="Build something.",
            metric_expectations=[
                MetricExpectation(name="cov", metric="min_coverage_pct", value=90.0),
            ],
        )
        v = _make_verifier()
        metrics = v._collect_metric_expectations(ctx)
        assert len(metrics) == 1
        assert metrics[0].value == 90.0

    def test_auto_from_description(self):
        ctx = _make_task_context(
            description="Build with greater than 85 percent coverage."
        )
        v = _make_verifier()
        metrics = v._collect_metric_expectations(ctx)
        assert len(metrics) == 1
        assert metrics[0].value == 85.0

    def test_explicit_overrides_auto(self):
        ctx = _make_task_context(
            description="Build with greater than 85 percent coverage.",
            metric_expectations=[
                MetricExpectation(name="cov", metric="min_coverage_pct", value=95.0),
            ],
        )
        v = _make_verifier()
        metrics = v._collect_metric_expectations(ctx)
        # Explicit 95 wins, auto 85 is skipped (same metric type)
        assert len(metrics) == 1
        assert metrics[0].value == 95.0

    def test_no_metrics(self):
        ctx = _make_task_context(description="Build something.")
        v = _make_verifier()
        metrics = v._collect_metric_expectations(ctx)
        assert len(metrics) == 0


# ---------------------------------------------------------------------------
# _evaluate_metric
# ---------------------------------------------------------------------------

class TestEvaluateMetric:
    def test_gte_pass(self):
        m = MetricExpectation(name="t", metric="x", operator="gte", value=10.0)
        assert Verifier._evaluate_metric(m, 10.0) is True
        assert Verifier._evaluate_metric(m, 15.0) is True

    def test_gte_fail(self):
        m = MetricExpectation(name="t", metric="x", operator="gte", value=10.0)
        assert Verifier._evaluate_metric(m, 9.0) is False

    def test_gt_pass(self):
        m = MetricExpectation(name="t", metric="x", operator="gt", value=10.0)
        assert Verifier._evaluate_metric(m, 11.0) is True

    def test_gt_fail_on_equal(self):
        m = MetricExpectation(name="t", metric="x", operator="gt", value=10.0)
        assert Verifier._evaluate_metric(m, 10.0) is False

    def test_lte_pass(self):
        m = MetricExpectation(name="t", metric="x", operator="lte", value=10.0)
        assert Verifier._evaluate_metric(m, 10.0) is True
        assert Verifier._evaluate_metric(m, 5.0) is True

    def test_lte_fail(self):
        m = MetricExpectation(name="t", metric="x", operator="lte", value=10.0)
        assert Verifier._evaluate_metric(m, 11.0) is False

    def test_lt_pass(self):
        m = MetricExpectation(name="t", metric="x", operator="lt", value=10.0)
        assert Verifier._evaluate_metric(m, 9.0) is True

    def test_eq_pass(self):
        m = MetricExpectation(name="t", metric="x", operator="eq", value=10.0)
        assert Verifier._evaluate_metric(m, 10.0) is True

    def test_eq_fail(self):
        m = MetricExpectation(name="t", metric="x", operator="eq", value=10.0)
        assert Verifier._evaluate_metric(m, 11.0) is False


# ---------------------------------------------------------------------------
# _check_metric_expectations
# ---------------------------------------------------------------------------

class TestCheckMetricExpectations:
    def test_coverage_violation(self):
        ctx = _make_task_context(
            metric_expectations=[
                MetricExpectation(name="cov", metric="min_coverage_pct", value=90.0),
            ],
        )
        v = _make_verifier()
        violations, recs = v._check_metric_expectations(
            ctx,
            tests_after=10,
            test_output="TOTAL                97     30    69%",
            files_changed=["a.py"],
        )
        assert len(violations) == 1
        assert "cov" in violations[0]["detail"]
        assert "69" in violations[0]["detail"]
        assert "90" in violations[0]["detail"]

    def test_coverage_passes(self):
        ctx = _make_task_context(
            metric_expectations=[
                MetricExpectation(name="cov", metric="min_coverage_pct", value=90.0),
            ],
        )
        v = _make_verifier()
        violations, recs = v._check_metric_expectations(
            ctx,
            tests_after=10,
            test_output="TOTAL                97     5     95%",
            files_changed=["a.py"],
        )
        assert len(violations) == 0

    def test_soft_metric_goes_to_recommendations(self):
        ctx = _make_task_context(
            metric_expectations=[
                MetricExpectation(name="files", metric="min_files_changed", value=5.0, hard=False),
            ],
        )
        v = _make_verifier()
        violations, recs = v._check_metric_expectations(
            ctx,
            tests_after=10,
            test_output="",
            files_changed=["a.py", "b.py"],
        )
        assert len(violations) == 0  # Not hard
        assert len(recs) == 1
        assert "files" in recs[0]

    def test_unmeasurable_metric_skipped(self):
        ctx = _make_task_context(
            metric_expectations=[
                MetricExpectation(name="cov", metric="min_coverage_pct", value=90.0),
            ],
        )
        v = _make_verifier()
        violations, recs = v._check_metric_expectations(
            ctx,
            tests_after=10,
            test_output="10 passed in 0.5s",  # No coverage output
            files_changed=["a.py"],
        )
        assert len(violations) == 0
        assert len(recs) == 1
        assert "could not be measured" in recs[0]

    def test_no_metrics_returns_empty(self):
        ctx = _make_task_context(description="Build something.")
        v = _make_verifier()
        violations, recs = v._check_metric_expectations(
            ctx, tests_after=10, test_output="", files_changed=["a.py"],
        )
        assert len(violations) == 0
        assert len(recs) == 0

    def test_files_changed_metric(self):
        ctx = _make_task_context(
            metric_expectations=[
                MetricExpectation(name="files", metric="min_files_changed", value=3.0),
            ],
        )
        v = _make_verifier()
        violations, recs = v._check_metric_expectations(
            ctx,
            tests_after=5,
            test_output="",
            files_changed=["a.py"],
        )
        assert len(violations) == 1
        assert "1" in violations[0]["detail"]
        assert "3" in violations[0]["detail"]

    def test_multiple_metrics(self):
        ctx = _make_task_context(
            metric_expectations=[
                MetricExpectation(name="cov", metric="min_coverage_pct", value=90.0),
                MetricExpectation(name="files", metric="min_files_changed", value=2.0),
            ],
        )
        v = _make_verifier()
        violations, recs = v._check_metric_expectations(
            ctx,
            tests_after=10,
            test_output="TOTAL                97     5     95%",
            files_changed=["a.py", "b.py", "c.py"],
        )
        assert len(violations) == 0  # Both pass


# ---------------------------------------------------------------------------
# Integration: metric expectations in verify() flow
# ---------------------------------------------------------------------------

class TestMetricExpectationsInVerify:
    @pytest.mark.asyncio
    async def test_coverage_violation_blocks_approval(self):
        v = _make_verifier()
        ctx = _make_task_context(
            description="Build with greater than 90 percent coverage target."
        )
        outcome = _make_outcome()

        async def fake_run_tests(workspace):
            return True, "22 passed in 0.5s", 22

        async def fake_run_coverage(workspace):
            return "TOTAL                97     30    69%"

        v.run_tests = fake_run_tests
        v._run_coverage = fake_run_coverage

        result = await v.verify(outcome, ctx, workspace_dir="/tmp/fake")
        assert not result.approved
        metric_viols = [vi for vi in result.violations if vi["check"] == "metric_expectation"]
        assert len(metric_viols) == 1
        assert "69" in metric_viols[0]["detail"]

    @pytest.mark.asyncio
    async def test_coverage_pass_allows_approval(self):
        v = _make_verifier()
        ctx = _make_task_context(
            description="Build with greater than 90 percent coverage target."
        )
        outcome = _make_outcome()

        async def fake_run_tests(workspace):
            return True, "22 passed in 0.5s", 22

        async def fake_run_coverage(workspace):
            return "TOTAL                97      5    95%"

        v.run_tests = fake_run_tests
        v._run_coverage = fake_run_coverage

        result = await v.verify(outcome, ctx, workspace_dir="/tmp/fake")
        assert result.approved

    @pytest.mark.asyncio
    async def test_explicit_contract_metrics_enforced(self):
        v = _make_verifier()
        ctx = _make_task_context(
            description="Build a module.",
            metric_expectations=[
                MetricExpectation(name="coverage", metric="min_coverage_pct", value=80.0),
            ],
        )
        outcome = _make_outcome()

        async def fake_run_tests(workspace):
            return True, "10 passed in 0.5s", 10

        async def fake_run_coverage(workspace):
            return "TOTAL                50     30    40%"

        v.run_tests = fake_run_tests
        v._run_coverage = fake_run_coverage

        result = await v.verify(outcome, ctx, workspace_dir="/tmp/fake")
        assert not result.approved
        assert any(v["check"] == "metric_expectation" for v in result.violations)
