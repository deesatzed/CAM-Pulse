from __future__ import annotations

from typing import Any

from tests.benchmarks.connectome_suite.full_suite import FULL_CONNECTOME_SUITE
from tests.benchmarks.connectome_suite.harness import run_connectome_suite


def _naive_slots(task_text: str) -> list[str]:
    text = task_text.lower()
    slots: list[str] = ["tests"]
    if "oauth" in text or "token refresh" in text:
        slots.extend(["auth_flow", "token_refresh"])
    if "csv" in text or "import" in text or "ingest" in text:
        slots.extend(["parser", "queue_worker"])
    if "rate limit" in text or "backoff" in text or "sync" in text:
        slots.extend(["api_client", "retry_logic"])
    if "webhook" in text:
        slots.extend(["ingest_handler", "retry_logic"])
    if "parser" in text or "transform" in text or "normalize" in text:
        slots.extend(["parser", "normalization"])
    if "fixture" in text or "tempdir" in text or "storage test" in text:
        slots.extend(["test_fixture", "cleanup_logic"])
    if "mcp" in text or "registry" in text:
        slots.extend(["registry", "tool_discovery"])
    if "transfer" in text or "cross-language" in text or "typescript" in text or "go" in text:
        slots.extend(["source_pattern", "target_adapter"])
    return list(dict.fromkeys(slots))


def _score_naive_suite(items: list[dict[str, Any]]) -> dict[str, Any]:
    task_results = []
    total_predicted = 0
    total_gold = 0
    total_matched = 0
    total_critical_gold = 0
    total_critical_matched = 0

    for item in items:
        predicted = set(_naive_slots(item["task_text"]))
        gold = set(item["gold_slots"])
        matched = predicted & gold
        critical_gold = set(item["critical_slots"])
        critical_matched = predicted & critical_gold
        task_results.append(
            {
                "id": item["id"],
                "archetype_match": False,
                "slot_precision": len(matched) / len(predicted) if predicted else 0.0,
                "slot_recall": len(matched) / len(gold) if gold else 1.0,
                "critical_slot_recall": len(critical_matched) / len(critical_gold) if critical_gold else 1.0,
            }
        )
        total_predicted += len(predicted)
        total_gold += len(gold)
        total_matched += len(matched)
        total_critical_gold += len(critical_gold)
        total_critical_matched += len(critical_matched)

    return {
        "tasks": task_results,
        "summary": {
            "task_count": len(task_results),
            "archetype_accuracy": 0.0,
            "slot_precision": total_matched / total_predicted if total_predicted else 0.0,
            "slot_recall": total_matched / total_gold if total_gold else 1.0,
            "critical_slot_recall": total_critical_matched / total_critical_gold if total_critical_gold else 1.0,
        },
    }


def run_planning_ablation() -> dict[str, Any]:
    current = run_connectome_suite(FULL_CONNECTOME_SUITE)
    naive = _score_naive_suite(FULL_CONNECTOME_SUITE)
    return {
        "suite_size": len(FULL_CONNECTOME_SUITE),
        "baseline": naive["summary"],
        "current": current["summary"],
        "uplift": {
            "archetype_accuracy": current["summary"]["archetype_accuracy"] - naive["summary"]["archetype_accuracy"],
            "slot_precision": current["summary"]["slot_precision"] - naive["summary"]["slot_precision"],
            "slot_recall": current["summary"]["slot_recall"] - naive["summary"]["slot_recall"],
            "critical_slot_recall": current["summary"]["critical_slot_recall"] - naive["summary"]["critical_slot_recall"],
        },
    }
