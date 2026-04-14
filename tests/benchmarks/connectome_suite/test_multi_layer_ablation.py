from __future__ import annotations

from tests.benchmarks.connectome_suite.multi_layer_ablation import run_multi_layer_ablation


def test_multi_layer_ablation_executes():
    result = run_multi_layer_ablation()
    assert result["baseline_selected"]
    assert result["fit_selected"]
    assert result["governed_selected"]


def test_multi_layer_ablation_shows_fit_and_policy_effects():
    result = run_multi_layer_ablation()
    assert result["baseline_selected"] == "comp_transfer"
    assert result["fit_selected"] == "comp_direct"
    assert result["governed_selected"] == "comp_direct"
    assert result["baseline_transfer_mode"].endswith("PATTERN_TRANSFER")
    assert "non_direct_fit" in result["governed_packet_review_reasons"]
