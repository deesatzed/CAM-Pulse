from __future__ import annotations

from collections import Counter

from tests.benchmarks.connectome_suite.full_suite import FULL_CONNECTOME_SUITE


def test_full_connectome_suite_has_24_tasks():
    assert len(FULL_CONNECTOME_SUITE) == 24


def test_full_connectome_suite_has_three_variants_per_archetype():
    counts = Counter(item["archetype"] for item in FULL_CONNECTOME_SUITE)
    assert counts
    assert all(count == 3 for count in counts.values())


def test_full_connectome_suite_entries_have_required_fields():
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
    for item in FULL_CONNECTOME_SUITE:
        assert required.issubset(item.keys())
        assert item["gold_slots"]
        assert "tests" in item["expected_proof_gates"]
