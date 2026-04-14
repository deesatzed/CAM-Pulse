from __future__ import annotations

from tests.benchmarks.connectome_suite.seeded_failures import SEEDED_RETROGRADE_CASES


def test_seeded_retrograde_cases_surface_expected_cause_kinds():
    for case in SEEDED_RETROGRADE_CASES:
        result = case["payload"]()
        top_kinds = {item["kind"] for item in result["cause_chain"][:3]}
        assert top_kinds & case["expected_top_kinds"], case["id"]


def test_seeded_retrograde_cases_keep_confidence_above_minimum():
    for case in SEEDED_RETROGRADE_CASES:
        result = case["payload"]()
        assert result["confidence"] >= 0.60, case["id"]


def test_seeded_retrograde_cases_return_root_cause_summary():
    for case in SEEDED_RETROGRADE_CASES:
        result = case["payload"]()
        summary = result["root_cause_summary"]
        assert summary["primary_kind"]
        assert isinstance(summary["supporting_signals"], list)
        assert isinstance(summary["clusters"], list)
        assert isinstance(summary["narrative"], str)
        assert summary["confidence_band"] in {"medium", "high"}
        assert isinstance(summary["recommended_action"], str)
        assert summary["actionability"] in {"immediate", "review"}
        assert isinstance(summary["decision_path"], list)
        assert summary["dominant_cluster"]
        assert summary["evidence_count"] >= len(result["cause_chain"])
        assert summary["confidence_drivers"]
        assert isinstance(summary["confidence_score"], float)
        assert summary["confidence_reason"]
        assert summary["calibration"] in {"stable", "mixed", "tentative"}
        assert summary["stability"] in {"stable", "competitive", "fragile"}
        assert summary["stability_reason"]
        assert summary["summary_version"] == "v2"
