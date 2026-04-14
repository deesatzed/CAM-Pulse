from __future__ import annotations

from typing import Any

from claw.planning.taskome import decompose_task

from tests.benchmarks.connectome_suite.pilot_suite import PILOT_CONNECTOME_SUITE


_ARCHETYPE_ALIASES = {
    "async_csv_import": "async_ingestion",
    "async_ingestion": "async_ingestion",
    "rate_limited_sync": "rate_limited_external_sync",
    "rate_limited_external_sync": "rate_limited_external_sync",
    "mcp_registry": "mcp_registry_scaffold",
    "mcp_registry_scaffold": "mcp_registry_scaffold",
    "storage_test_scaffolding": "storage_test_scaffolding",
    "oauth_session_management": "oauth_session_management",
}

_SLOT_ALIASES = {
    "rate_limit": "throttle_policy",
    "tool_registry": "registry",
    "registration": "tool_discovery",
    "validation": "schema_wiring",
    "tempdir_fixture": "test_fixture",
    "storage_fixture": "storage_helper",
}


def _normalize_archetype(name: str) -> str:
    return _ARCHETYPE_ALIASES.get(name, name)


def _normalize_slot(name: str) -> str:
    return _SLOT_ALIASES.get(name, name)


def evaluate_task(item: dict[str, Any]) -> dict[str, Any]:
    plan = decompose_task(item["task_text"])
    predicted_slots = {_normalize_slot(slot.name) for slot in plan.slots}
    gold_slots = {_normalize_slot(name) for name in item["gold_slots"]}
    predicted_critical = {_normalize_slot(slot.name) for slot in plan.slots if getattr(slot.risk, "value", str(slot.risk)) == "critical"}
    gold_critical = {_normalize_slot(name) for name in item["critical_slots"]}

    matched_slots = predicted_slots & gold_slots
    matched_critical = predicted_critical & gold_critical

    precision = len(matched_slots) / len(predicted_slots) if predicted_slots else 0.0
    recall = len(matched_slots) / len(gold_slots) if gold_slots else 1.0
    critical_recall = len(matched_critical) / len(gold_critical) if gold_critical else 1.0

    return {
        "id": item["id"],
        "task_text": item["task_text"],
        "expected_archetype": item["archetype"],
        "predicted_archetype": plan.task_archetype,
        "archetype_match": _normalize_archetype(plan.task_archetype) == _normalize_archetype(item["archetype"]),
        "gold_slots": sorted(gold_slots),
        "predicted_slots": sorted(predicted_slots),
        "matched_slots": sorted(matched_slots),
        "gold_critical_slots": sorted(gold_critical),
        "predicted_critical_slots": sorted(predicted_critical),
        "matched_critical_slots": sorted(matched_critical),
        "slot_precision": precision,
        "slot_recall": recall,
        "critical_slot_recall": critical_recall,
    }


def run_connectome_suite(items: list[dict[str, Any]]) -> dict[str, Any]:
    task_results = [evaluate_task(item) for item in items]
    total_predicted = sum(len(item["predicted_slots"]) for item in task_results)
    total_gold = sum(len(item["gold_slots"]) for item in task_results)
    total_matched = sum(len(item["matched_slots"]) for item in task_results)
    total_critical_gold = sum(len(item["gold_critical_slots"]) for item in task_results)
    total_critical_matched = sum(len(item["matched_critical_slots"]) for item in task_results)

    return {
        "tasks": task_results,
        "summary": {
            "task_count": len(task_results),
            "archetype_accuracy": sum(1 for item in task_results if item["archetype_match"]) / len(task_results),
            "slot_precision": total_matched / total_predicted if total_predicted else 0.0,
            "slot_recall": total_matched / total_gold if total_gold else 1.0,
            "critical_slot_recall": total_critical_matched / total_critical_gold if total_critical_gold else 1.0,
        },
    }


def evaluate_pilot_task(item: dict[str, Any]) -> dict[str, Any]:
    return evaluate_task(item)


def run_pilot_connectome_suite() -> dict[str, Any]:
    return run_connectome_suite(PILOT_CONNECTOME_SUITE)
