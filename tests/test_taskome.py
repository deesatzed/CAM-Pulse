from __future__ import annotations

from claw.core.models import SlotRisk
from claw.planning.taskome import decompose_task, infer_task_archetype


def test_infer_oauth_archetype():
    archetype, confidence, hits = infer_task_archetype("Add OAuth session handling with token refresh locking")
    assert archetype == "oauth_session_management"
    assert confidence >= 0.5
    assert hits


def test_decompose_async_ingestion_task():
    plan = decompose_task(
        "Add background CSV import with progress tracking and retry logic",
        target_language="python",
        target_stack_hints=["fastapi"],
    )
    names = [slot.name for slot in plan.slots]
    assert plan.task_archetype == "async_ingestion"
    assert "parser" in names
    assert "queue_worker" in names
    assert "retry_logic" in names
    assert plan.coverage_summary["total_slots"] == len(plan.slots)


def test_oauth_plan_marks_critical_slots():
    plan = decompose_task("Implement OAuth session and token refresh")
    risky = {slot.name: slot.risk for slot in plan.slots}
    assert risky["auth_flow"] == SlotRisk.CRITICAL
    assert risky["token_refresh"] == SlotRisk.CRITICAL
