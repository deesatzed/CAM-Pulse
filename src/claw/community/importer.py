"""Community knowledge import orchestration.

Pulls records from HuggingFace, validates through 7 gates,
quarantines for review, and approves into the live KB.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from claw.community.validator import ValidationResult, validate_record
from claw.memory.cag_staleness import maybe_mark_cag_stale

logger = logging.getLogger("claw.community.importer")


async def import_records(
    records: list[dict[str, Any]],
    engine: Any,
    max_records: int = 200,
    auto_approve: bool = False,
    config: Optional[object] = None,
) -> dict[str, Any]:
    """Validate and quarantine community records.

    Returns summary: {imported, skipped, rejected, errors, details}.
    """
    # Ensure community_imports table exists
    await _ensure_tables(engine)

    summary = {"imported": 0, "skipped": 0, "rejected": 0, "errors": [], "details": []}
    seen_hashes: set[str] = set()

    for i, record in enumerate(records[:max_records]):
        record_id = record.get("id", f"unknown-{i}")
        content_hash = record.get("community_meta", {}).get("content_hash", "")

        # Cross-contributor dedup within this session
        if content_hash in seen_hashes:
            summary["skipped"] += 1
            summary["details"].append({"id": record_id, "action": "skip_session_dedup"})
            continue
        seen_hashes.add(content_hash)

        # Run validation
        result = await validate_record(record, engine)

        if not result.passed:
            summary["rejected"] += 1
            failed_gates = [g.gate_name for g in result.gates if not g.passed and g.hard]
            detail = [g.detail for g in result.gates if not g.passed and g.hard]
            summary["details"].append({
                "id": record_id,
                "action": "rejected",
                "gates": failed_gates,
                "detail": detail,
            })
            # Log audit
            await _log_audit(engine, record, "rejected", failed_gates[0] if failed_gates else "", str(detail))
            continue

        if auto_approve:
            # Write directly to methodologies
            await _approve_record(result, engine)
            summary["imported"] += 1
            summary["details"].append({"id": record_id, "action": "auto_approved"})
        else:
            # Quarantine
            await _quarantine_record(result, engine)
            summary["imported"] += 1
            summary["details"].append({"id": record_id, "action": "quarantined"})

    if summary["imported"] > 0:
        maybe_mark_cag_stale(config)
    return summary


async def list_quarantined(engine: Any) -> list[dict[str, Any]]:
    """List all quarantined records."""
    await _ensure_tables(engine)
    rows = await engine.fetch_all(
        "SELECT id, content_hash, contributor_instance_id, contributor_alias, "
        "origin_id, gate_results, imported_at FROM community_imports "
        "WHERE status = 'quarantined' ORDER BY imported_at DESC"
    )
    results = []
    for r in rows:
        sanitized = {}
        try:
            sanitized = json.loads(r.get("gate_results", "{}"))
        except (json.JSONDecodeError, TypeError):
            pass
        results.append({
            "id": r["id"],
            "content_hash": r["content_hash"],
            "contributor": r.get("contributor_alias") or r["contributor_instance_id"][:12],
            "origin_id": r.get("origin_id", ""),
            "imported_at": r["imported_at"],
            "gate_warnings": sanitized.get("warnings", []),
        })
    return results


async def approve_all(engine: Any) -> int:
    """Approve all quarantined records into the live KB. Returns count."""
    await _ensure_tables(engine)
    rows = await engine.fetch_all(
        "SELECT id, sanitized_record FROM community_imports WHERE status = 'quarantined'"
    )
    count = 0
    for row in rows:
        try:
            record = json.loads(row["sanitized_record"])
            result = ValidationResult(record_id=row["id"])
            result.sanitized_record = record
            await _approve_record(result, engine)
            await engine.execute(
                "UPDATE community_imports SET status = 'approved', approved_at = ? WHERE id = ?",
                [datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), row["id"]],
            )
            count += 1
        except Exception as e:
            logger.warning("Failed to approve %s: %s", row["id"], e)
    return count


async def approve_one(engine: Any, quarantine_id: str) -> bool:
    """Approve a single quarantined record."""
    await _ensure_tables(engine)
    rows = await engine.fetch_all(
        "SELECT sanitized_record FROM community_imports WHERE id = ? AND status = 'quarantined'",
        [quarantine_id],
    )
    if not rows:
        return False

    record = json.loads(rows[0]["sanitized_record"])
    result = ValidationResult(record_id=quarantine_id)
    result.sanitized_record = record
    await _approve_record(result, engine)
    await engine.execute(
        "UPDATE community_imports SET status = 'approved', approved_at = ? WHERE id = ?",
        [datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), quarantine_id],
    )
    return True


async def reject_one(engine: Any, quarantine_id: str) -> bool:
    """Reject a single quarantined record."""
    await _ensure_tables(engine)
    rows = await engine.fetch_all(
        "SELECT id FROM community_imports WHERE id = ? AND status = 'quarantined'",
        [quarantine_id],
    )
    if not rows:
        return False
    await engine.execute(
        "UPDATE community_imports SET status = 'rejected' WHERE id = ?",
        [quarantine_id],
    )
    return True


async def _ensure_tables(engine: Any) -> None:
    """Create community tables if they don't exist."""
    await engine.conn.execute("""
        CREATE TABLE IF NOT EXISTS community_imports (
            id TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            contributor_instance_id TEXT NOT NULL,
            contributor_alias TEXT,
            origin_id TEXT,
            status TEXT DEFAULT 'quarantined'
                CHECK (status IN ('quarantined','approved','rejected')),
            gate_results TEXT NOT NULL DEFAULT '{}',
            sanitized_record TEXT NOT NULL,
            imported_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            approved_at TEXT,
            UNIQUE(content_hash)
        )
    """)
    await engine.conn.execute("""
        CREATE TABLE IF NOT EXISTS community_import_audit (
            id TEXT PRIMARY KEY,
            contributor_instance_id TEXT,
            action TEXT NOT NULL,
            gate_name TEXT,
            detail TEXT NOT NULL DEFAULT '{}',
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
    """)
    await engine.conn.commit()


async def _quarantine_record(result: ValidationResult, engine: Any) -> None:
    """Insert a validated record into the quarantine table."""
    record = result.sanitized_record or {}
    cm = record.get("community_meta", {})

    gate_data = {
        "gates": {g.gate_name: {"passed": g.passed, "hard": g.hard, "detail": g.detail} for g in result.gates},
        "warnings": result.warnings,
    }

    await engine.execute(
        """INSERT OR IGNORE INTO community_imports
           (id, content_hash, contributor_instance_id, contributor_alias, origin_id, gate_results, sanitized_record)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            str(uuid.uuid4()),
            cm.get("content_hash", ""),
            cm.get("instance_id", ""),
            cm.get("contributor_alias", ""),
            record.get("id", ""),
            json.dumps(gate_data),
            json.dumps(record),
        ],
    )


async def _approve_record(result: ValidationResult, engine: Any) -> None:
    """Insert an approved record into the live methodologies table."""
    record = result.sanitized_record or {}
    overrides = record.get("_import_overrides", {})
    meta = record.get("metadata", {})
    cm = record.get("community_meta", {})

    new_id = str(uuid.uuid4())
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = json.loads(tags)
    tags.append(f"community:{cm.get('instance_id', 'unknown')[:12]}")
    tags.append("imported")

    cap_data = meta.get("capability_data", {})
    cap_data["community_origin"] = {
        "instance_id": cm.get("instance_id", ""),
        "contributor_alias": cm.get("contributor_alias", ""),
        "origin_lifecycle": cm.get("origin_lifecycle", ""),
        "imported_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    text = record.get("text", "")
    parts = text.split("\n\n", 2)
    problem = parts[0] if parts else text
    solution = parts[1] if len(parts) > 1 else ""
    notes = parts[2] if len(parts) > 2 else ""

    await engine.execute(
        """INSERT INTO methodologies
           (id, problem_description, solution_code, methodology_notes,
            tags, language, scope, methodology_type, capability_data,
            lifecycle_state, success_count, failure_count, retrieval_count,
            fitness_vector, generation, novelty_score, potential_score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            new_id,
            problem,
            solution,
            notes,
            json.dumps(tags),
            meta.get("language", ""),
            overrides.get("scope", "project"),
            meta.get("methodology_type", "PATTERN"),
            json.dumps(cap_data),
            overrides.get("lifecycle_state", "embryonic"),
            overrides.get("success_count", 0),
            overrides.get("failure_count", 0),
            overrides.get("retrieval_count", 0),
            overrides.get("fitness_vector", "{}"),
            overrides.get("generation", 0),
            meta.get("novelty_score"),
            meta.get("potential_score"),
        ],
    )


async def _log_audit(
    engine: Any,
    record: dict[str, Any],
    action: str,
    gate_name: str,
    detail: str,
) -> None:
    """Write an audit log entry."""
    cm = record.get("community_meta", {})
    try:
        await engine.execute(
            """INSERT INTO community_import_audit
               (id, contributor_instance_id, action, gate_name, detail)
               VALUES (?, ?, ?, ?, ?)""",
            [
                str(uuid.uuid4()),
                cm.get("instance_id", ""),
                action,
                gate_name,
                detail,
            ],
        )
    except Exception as e:
        logger.warning("Failed to log audit: %s", e)
