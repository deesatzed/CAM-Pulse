from __future__ import annotations

from tests.benchmarks.connectome_suite.harness import run_pilot_connectome_suite


def test_pilot_harness_executes_all_seed_tasks():
    result = run_pilot_connectome_suite()
    assert result["summary"]["task_count"] == 6
    assert len(result["tasks"]) == 6


def test_pilot_harness_meets_current_planning_floor():
    result = run_pilot_connectome_suite()
    summary = result["summary"]
    assert summary["archetype_accuracy"] >= 0.80
    assert summary["slot_precision"] >= 0.70
    assert summary["slot_recall"] >= 0.90
    assert summary["critical_slot_recall"] >= 0.95
