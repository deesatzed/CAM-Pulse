from __future__ import annotations

from tests.benchmarks.connectome_suite.live_run_harness import run_live_reviewed_benchmark


def test_live_reviewed_benchmark_executes_repeated_reviewed_runs():
    result = run_live_reviewed_benchmark()
    assert result["run_count"] == 4
    assert result["completed_runs"] == 4
    assert result["connectome_count"] == 4
    assert result["workspace_mutation_count"] >= result["run_count"]
    assert result["final_landing_count"] >= 1


def test_live_reviewed_benchmark_activates_recipe_and_feeds_planning():
    result = run_live_reviewed_benchmark()
    assert result["active_recipe_count"] >= 1
    assert result["fourth_packet_selected_component"] in {"comp_direct", "comp_other"}
    assert result["fourth_packet_family_barcode"] in {"fam_auth", "fam_other"}
    assert "recipe_family_preference" in result["fourth_packet_confidence_basis"]
    assert result["fourth_distill_recipe_count"] >= 1
