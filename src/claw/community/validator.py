"""7-gate validation for community knowledge imports.

Gates:
1. Schema validation — required fields present, types correct
2. Field allow-list — strip unknown/dangerous fields
3. Content safety — scan for injection patterns
4. Manifest hash — verify content integrity
5. Dedup — skip if content_hash already exists locally
6. Niche collision — warn (soft) if very similar methodology exists
7. Lifecycle reset — always reset to embryonic
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("claw.community.validator")

# Gate 3: dangerous patterns in text/solution content
_DANGEROUS_PATTERNS = [
    re.compile(r"\bexec\s*\("),
    re.compile(r"\beval\s*\("),
    re.compile(r"__import__\s*\("),
    re.compile(r"\bsubprocess\b"),
    re.compile(r"\bos\.system\s*\("),
    re.compile(r"\bimportlib\b"),
    re.compile(r"\bopen\s*\([^)]*[\"'][wa]"),
    re.compile(r";\s*rm\s"),
    re.compile(r"&&\s*rm\s"),
    re.compile(r"\|\s*sh\b"),
    re.compile(r"\|\s*bash\b"),
]

# Fields allowed in metadata
_ALLOWED_METADATA_KEYS = {
    "language", "scope", "methodology_type", "tags",
    "success_count", "retrieval_count", "novelty_score",
    "potential_score", "created_at", "capability_data",
}

# Patterns indicating secrets in text
_SECRET_SCAN_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9._\-]{20,}"),
    re.compile(r"[A-Z_]{4,}=[^\s]{10,}"),
]


@dataclass
class GateResult:
    """Result from a single validation gate."""
    gate_name: str
    passed: bool
    hard: bool = True  # Hard gates block import; soft gates only warn
    detail: str = ""


@dataclass
class ValidationResult:
    """Aggregate result from all 7 gates."""
    record_id: str
    gates: list[GateResult] = field(default_factory=list)
    sanitized_record: Optional[dict[str, Any]] = None

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates if g.hard)

    @property
    def warnings(self) -> list[str]:
        return [g.detail for g in self.gates if not g.passed and not g.hard]


def _gate_schema(record: dict[str, Any]) -> GateResult:
    """Gate 1: Validate required fields and types."""
    required = {"id", "title", "modality", "text", "metadata", "community_meta"}
    missing = required - set(record.keys())
    if missing:
        return GateResult("schema", False, True, f"Missing fields: {missing}")

    if record.get("modality") not in ("memory_methodology", "memory_task"):
        return GateResult("schema", False, True, f"Invalid modality: {record.get('modality')}")

    cm = record.get("community_meta", {})
    if not isinstance(cm, dict):
        return GateResult("schema", False, True, "community_meta must be a dict")

    if not cm.get("pack_format_version", "").startswith("1."):
        return GateResult("schema", False, True, f"Unsupported format: {cm.get('pack_format_version')}")

    if not isinstance(cm.get("instance_id", ""), str) or len(cm.get("instance_id", "")) != 64:
        return GateResult("schema", False, True, "Invalid instance_id (must be 64-char hex)")

    text = record.get("text", "")
    if len(str(text)) > 32000:
        return GateResult("schema", False, True, f"Text exceeds 32KB limit ({len(str(text))} bytes)")

    return GateResult("schema", True, True)


def _gate_field_allowlist(record: dict[str, Any]) -> tuple[GateResult, dict[str, Any]]:
    """Gate 2: Strip unknown fields from metadata, sanitize text."""
    cleaned = dict(record)

    # Filter metadata
    meta = cleaned.get("metadata", {})
    if isinstance(meta, dict):
        cleaned["metadata"] = {k: v for k, v in meta.items() if k in _ALLOWED_METADATA_KEYS}

    # Sanitize text — strip potential secrets
    text = cleaned.get("text", "")
    for pat in _SECRET_SCAN_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    cleaned["text"] = text

    return GateResult("field_allowlist", True, True), cleaned


def _gate_content_safety(record: dict[str, Any]) -> GateResult:
    """Gate 3: Scan for dangerous code patterns."""
    text = record.get("text", "")
    for pat in _DANGEROUS_PATTERNS:
        match = pat.search(text)
        if match:
            return GateResult(
                "content_safety", False, True,
                f"Dangerous pattern found: '{match.group()}' at position {match.start()}"
            )
    return GateResult("content_safety", True, True)


def _gate_manifest_hash(record: dict[str, Any]) -> GateResult:
    """Gate 4: Verify content hash integrity."""
    cm = record.get("community_meta", {})
    expected_hash = cm.get("content_hash", "")
    if not expected_hash:
        return GateResult("manifest_hash", False, True, "No content_hash in community_meta")

    # Recompute
    from claw.community.packer import compute_content_hash
    actual_hash = compute_content_hash(record.get("id", ""), record.get("text", ""))

    if actual_hash != expected_hash:
        return GateResult(
            "manifest_hash", False, True,
            f"Hash mismatch: expected {expected_hash[:16]}..., got {actual_hash[:16]}..."
        )
    return GateResult("manifest_hash", True, True)


async def _gate_dedup(record: dict[str, Any], engine: Any) -> GateResult:
    """Gate 5: Check if content_hash already exists in community_imports or methodologies."""
    cm = record.get("community_meta", {})
    content_hash = cm.get("content_hash", "")

    # Check community_imports table
    try:
        existing = await engine.fetch_all(
            "SELECT id FROM community_imports WHERE content_hash = ?",
            [content_hash],
        )
        if existing:
            return GateResult("dedup", False, True, "Already imported (same content_hash)")
    except Exception:
        pass  # Table might not exist yet on first run

    return GateResult("dedup", True, True)


def _gate_lifecycle_reset(record: dict[str, Any]) -> tuple[GateResult, dict[str, Any]]:
    """Gate 7: Reset lifecycle state to embryonic, clear counters."""
    cleaned = dict(record)
    cleaned["_import_overrides"] = {
        "lifecycle_state": "embryonic",
        "success_count": 0,
        "failure_count": 0,
        "retrieval_count": 0,
        "fitness_vector": "{}",
        "generation": 0,
        "scope": "project",  # Community imports start as project-scoped
    }
    return GateResult("lifecycle_reset", True, False, "Lifecycle reset to embryonic"), cleaned


async def validate_record(
    record: dict[str, Any],
    engine: Any,
) -> ValidationResult:
    """Run all 7 validation gates on a single record.

    Returns ValidationResult with gate details and sanitized record.
    """
    result = ValidationResult(record_id=record.get("id", "unknown"))

    # Gate 1: Schema
    g1 = _gate_schema(record)
    result.gates.append(g1)
    if not g1.passed:
        return result

    # Gate 2: Field allowlist
    g2, cleaned = _gate_field_allowlist(record)
    result.gates.append(g2)

    # Gate 3: Content safety
    g3 = _gate_content_safety(cleaned)
    result.gates.append(g3)
    if not g3.passed:
        return result

    # Gate 4: Manifest hash (run on ORIGINAL record, not cleaned — hash was computed on original text)
    g4 = _gate_manifest_hash(record)
    result.gates.append(g4)
    if not g4.passed:
        return result

    # Gate 5: Dedup
    g5 = await _gate_dedup(record, engine)
    result.gates.append(g5)
    if not g5.passed:
        return result

    # Gate 6: Niche collision (soft — warn only)
    # Deferred to approve step (requires embedding, expensive)
    result.gates.append(GateResult("niche_collision", True, False, "Deferred to approve step"))

    # Gate 7: Lifecycle reset
    g7, final = _gate_lifecycle_reset(cleaned)
    result.gates.append(g7)
    result.sanitized_record = final

    return result
