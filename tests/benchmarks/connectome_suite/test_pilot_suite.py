from __future__ import annotations

from tests.benchmarks.connectome_suite.pilot_suite import PILOT_CONNECTOME_SUITE


def test_pilot_connectome_suite_has_six_seed_tasks():
    assert len(PILOT_CONNECTOME_SUITE) == 6


def test_pilot_connectome_suite_entries_have_required_fields():
    required = {
        "id",
        "archetype",
        "variant",
        "task_text",
        "gold_slots",
        "critical_slots",
        "acceptable_component_families",
        "expected_proof_gates",
    }
    for item in PILOT_CONNECTOME_SUITE:
        assert required.issubset(item.keys())
        assert item["gold_slots"]
        assert "tests" in item["expected_proof_gates"]


def test_pilot_connectome_suite_includes_critical_slot_coverage():
    critical = [item for item in PILOT_CONNECTOME_SUITE if item["critical_slots"]]
    assert critical
    assert any(item["archetype"] == "oauth_session_management" for item in critical)
