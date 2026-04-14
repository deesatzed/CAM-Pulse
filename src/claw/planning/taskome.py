"""Deterministic task archetype inference and slot decomposition for CAM-SEQ."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from claw.connectome.barcodes import build_slot_barcode
from claw.core.models import SlotRisk, SlotSpec


class TaskomePlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:12]}")
    task_text: str
    workspace_dir: Optional[str] = None
    task_archetype: str
    archetype_confidence: float
    slots: list[SlotSpec] = Field(default_factory=list)
    critical_slot_ids: list[str] = Field(default_factory=list)
    check_commands: list[str] = Field(default_factory=list)
    coverage_summary: dict[str, int] = Field(default_factory=dict)


_ARCHETYPE_RULES: list[tuple[str, tuple[str, ...], list[dict[str, object]]]] = [
    (
        "oauth_session_management",
        ("oauth", "session", "token", "refresh", "auth"),
        [
            {"name": "auth_flow", "abstract_job": "authenticated_api_client", "risk": SlotRisk.CRITICAL, "proof": ["tests", "verifier"]},
            {"name": "session_store", "abstract_job": "session_store", "risk": SlotRisk.CRITICAL, "proof": ["tests", "verifier"]},
            {"name": "token_refresh", "abstract_job": "token_refresh_serialization", "risk": SlotRisk.CRITICAL, "proof": ["tests", "verifier", "human_review"]},
            {"name": "middleware_integration", "abstract_job": "middleware_integration", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "tests", "abstract_job": "test_fixture", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "config_wiring", "abstract_job": "config_helper", "risk": SlotRisk.NORMAL, "proof": ["verifier"]},
        ],
    ),
    (
        "async_ingestion",
        ("csv", "import", "ingest", "background", "progress"),
        [
            {"name": "file_intake", "abstract_job": "file_intake", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "parser", "abstract_job": "parser_transform", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "validation", "abstract_job": "validator", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "queue_worker", "abstract_job": "idempotent_event_processor", "risk": SlotRisk.NORMAL, "proof": ["tests", "verifier"]},
            {"name": "retry_logic", "abstract_job": "retry_with_backoff", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "progress_persistence", "abstract_job": "progress_persistence", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "error_reporting", "abstract_job": "error_reporting", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "tests", "abstract_job": "test_fixture", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
        ],
    ),
    (
        "rate_limited_external_sync",
        ("rate limit", "sync", "external api", "backoff"),
        [
            {"name": "api_client", "abstract_job": "authenticated_api_client", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "retry_logic", "abstract_job": "retry_with_backoff", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "throttle_policy", "abstract_job": "rate_limit_policy", "risk": SlotRisk.NORMAL, "proof": ["tests", "verifier"]},
            {"name": "persistence", "abstract_job": "repository", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "tests", "abstract_job": "test_fixture", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
        ],
    ),
    (
        "webhook_reliability_pipeline",
        ("webhook", "retry", "persistence", "validation"),
        [
            {"name": "ingest_handler", "abstract_job": "route_handler", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "validation", "abstract_job": "validator", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "persistence", "abstract_job": "repository", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "retry_logic", "abstract_job": "retry_with_backoff", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "tests", "abstract_job": "test_fixture", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
        ],
    ),
    (
        "parser_transform_pipeline",
        ("parse", "parser", "transform", "normalize"),
        [
            {"name": "parser", "abstract_job": "parser_transform", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "normalization", "abstract_job": "streaming_response_normalization", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "validation", "abstract_job": "validator", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "tests", "abstract_job": "test_fixture", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
        ],
    ),
    (
        "storage_test_scaffolding",
        ("tempdir", "fixture", "storage", "test"),
        [
            {"name": "test_fixture", "abstract_job": "tempdir_test_fixture", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "storage_helper", "abstract_job": "repository", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "cleanup_logic", "abstract_job": "cleanup_helper", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "tests", "abstract_job": "test_fixture", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
        ],
    ),
    (
        "mcp_registry_scaffold",
        ("mcp", "registry", "tool", "self-registration"),
        [
            {"name": "registry", "abstract_job": "mcp_registry", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "tool_discovery", "abstract_job": "tool_discovery", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "schema_wiring", "abstract_job": "config_helper", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "tests", "abstract_job": "test_fixture", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
        ],
    ),
    (
        "cross_language_pattern_transfer",
        ("transfer", "cross-language", "typescript", "go", "python"),
        [
            {"name": "source_pattern", "abstract_job": "pattern_transfer_source", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
            {"name": "target_adapter", "abstract_job": "pattern_transfer_adapter", "risk": SlotRisk.NORMAL, "proof": ["tests", "verifier"]},
            {"name": "tests", "abstract_job": "test_fixture", "risk": SlotRisk.NORMAL, "proof": ["tests"]},
        ],
    ),
]


def infer_task_archetype(task_text: str) -> tuple[str, float, list[str]]:
    text = task_text.lower()
    best_name = "parser_transform_pipeline"
    best_score = 0
    best_hits: list[str] = []
    for name, keywords, _slots in _ARCHETYPE_RULES:
        hits = [kw for kw in keywords if kw in text]
        if len(hits) > best_score:
            best_name = name
            best_score = len(hits)
            best_hits = hits
    confidence = min(0.35 + (best_score * 0.17), 0.95)
    return best_name, confidence, best_hits


def _constraints_for_slot(task_text: str, slot_name: str, target_stack: list[str]) -> list[str]:
    text = task_text.lower()
    constraints: list[str] = []
    if "async" in text:
        constraints.append("async")
    if "sync" in text:
        constraints.append("sync")
    if "critical" in text or slot_name in {"auth_flow", "token_refresh", "session_store"}:
        constraints.append("review_required")
    if any(item in text for item in ("httpx", "fastapi", "pytest", "requests")):
        for item in ("httpx", "fastapi", "pytest", "requests"):
            if item in text and item not in target_stack:
                target_stack.append(item)
    return list(dict.fromkeys(constraints))


def decompose_task(
    task_text: str,
    *,
    workspace_path: Optional[str] = None,
    target_language: Optional[str] = None,
    target_stack_hints: Optional[list[str]] = None,
    check_commands: Optional[list[str]] = None,
) -> TaskomePlan:
    archetype, confidence, _hits = infer_task_archetype(task_text)
    slot_defs = next(slots for name, _keywords, slots in _ARCHETYPE_RULES if name == archetype)
    target_stack = list(target_stack_hints or [])
    if target_language and target_language not in target_stack:
        target_stack.insert(0, target_language)
    if not target_stack and workspace_path:
        suffixes = {p.suffix.lower() for p in Path(workspace_path).glob("*") if p.is_file()}
        if ".py" in suffixes:
            target_stack.append("python")
        elif ".ts" in suffixes or ".tsx" in suffixes:
            target_stack.append("typescript")

    slots: list[SlotSpec] = []
    critical_slot_ids: list[str] = []
    for idx, slot_def in enumerate(slot_defs):
        name = str(slot_def["name"])
        abstract_job = str(slot_def["abstract_job"])
        risk = slot_def["risk"]
        proof = list(slot_def["proof"])
        constraints = _constraints_for_slot(task_text, name, target_stack)
        slot_id = f"slot_{idx+1}_{name}"
        slot = SlotSpec(
            slot_id=slot_id,
            slot_barcode=build_slot_barcode(archetype, name, constraints=constraints, target_stack=target_stack),
            name=name,
            abstract_job=abstract_job,
            risk=risk,
            constraints=constraints,
            target_stack=target_stack,
            proof_expectations=proof,
        )
        slots.append(slot)
        if slot.risk == SlotRisk.CRITICAL:
            critical_slot_ids.append(slot.slot_id)

    return TaskomePlan(
        task_text=task_text,
        workspace_dir=workspace_path,
        task_archetype=archetype,
        archetype_confidence=confidence,
        slots=slots,
        critical_slot_ids=critical_slot_ids,
        check_commands=check_commands or [],
        coverage_summary={
            "total_slots": len(slots),
            "critical_slots": len(critical_slot_ids),
            "weak_slots": 0,
        },
    )
