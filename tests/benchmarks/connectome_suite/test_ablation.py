from __future__ import annotations

from tests.benchmarks.connectome_suite.ablation import run_planning_ablation


def test_planning_ablation_executes():
    result = run_planning_ablation()
    assert result["suite_size"] == 24
    assert "baseline" in result
    assert "current" in result
    assert "uplift" in result


def test_planning_ablation_current_beats_naive_baseline():
    result = run_planning_ablation()
    assert result["uplift"]["archetype_accuracy"] > 0
    assert result["uplift"]["slot_recall"] > 0
