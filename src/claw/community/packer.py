"""Pack local methodologies for community sharing.

Strips internal fields, adds provenance metadata, computes content hashes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("claw.community.packer")

# Fields to STRIP from capability_data before publishing
_STRIP_CAPABILITY_KEYS = {
    "fitness_vector", "prism_data", "parent_ids", "superseded_by",
    "source_task_id",
}

# Patterns that indicate secrets — strip from text fields
_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9._\-]+"),
    re.compile(r"[A-Z_]{3,}=[^\s]{8,}"),
]


def _get_instance_id(state_path: Path) -> str:
    """Get or create a stable instance ID."""
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text())
            if "instance_id" in data:
                return data["instance_id"]
        except (json.JSONDecodeError, OSError):
            pass

    seed = f"{platform.node()}:{platform.machine()}:{Path.home()}"
    instance_id = hashlib.sha256(seed.encode()).hexdigest()

    state_path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if state_path.exists():
        try:
            existing = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    existing["instance_id"] = instance_id
    state_path.write_text(json.dumps(existing, indent=2))
    return instance_id


def compute_content_hash(record_id: str, text: str) -> str:
    """SHA-256 hash of record ID + text for dedup."""
    return hashlib.sha256(f"{record_id}:{text[:2000]}".encode()).hexdigest()


def _sanitize_text(text: str) -> str:
    """Remove potential secrets from text."""
    result = text
    for pat in _SECRET_PATTERNS:
        result = pat.sub("[REDACTED]", result)
    return result


def _strip_capability_data(cap_data: dict[str, Any]) -> dict[str, Any]:
    """Remove internal-only keys from capability_data."""
    return {k: v for k, v in cap_data.items() if k not in _STRIP_CAPABILITY_KEYS}


async def pack_methodologies(
    engine: Any,
    state_path: Path,
    min_lifecycle: str = "viable",
    max_count: int = 500,
    contributor_alias: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pack local methodologies into community-shareable format.

    Returns (records, manifest).
    """
    lifecycle_order = ["embryonic", "viable", "thriving", "declining", "dormant", "dead"]
    min_idx = lifecycle_order.index(min_lifecycle) if min_lifecycle in lifecycle_order else 0
    allowed_states = lifecycle_order[min_idx:]

    # Fetch methodologies
    placeholders = ",".join(["?"] * len(allowed_states))
    rows = await engine.fetch_all(
        f"""SELECT id, problem_description, solution_code, methodology_notes,
                   tags, language, scope, methodology_type, capability_data,
                   lifecycle_state, success_count, failure_count, retrieval_count,
                   novelty_score, potential_score, created_at
            FROM methodologies
            WHERE lifecycle_state IN ({placeholders})
            ORDER BY success_count DESC, retrieval_count DESC
            LIMIT ?""",
        [*allowed_states, max_count],
    )

    instance_id = _get_instance_id(state_path)
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    records = []

    for row in rows:
        text_parts = []
        if row["problem_description"]:
            text_parts.append(row["problem_description"])
        if row["methodology_notes"]:
            text_parts.append(row["methodology_notes"])
        if row["solution_code"]:
            text_parts.append(row["solution_code"])
        text = _sanitize_text("\n\n".join(text_parts)[:6000])

        tags = row["tags"] if isinstance(row["tags"], list) else json.loads(row["tags"] or "[]")
        source_urls = []
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("source:"):
                source_urls.append(tag.replace("source:", ""))

        cap_data = {}
        if row["capability_data"]:
            try:
                raw = json.loads(row["capability_data"]) if isinstance(row["capability_data"], str) else row["capability_data"]
                cap_data = _strip_capability_data(raw)
            except (json.JSONDecodeError, TypeError):
                pass

        content_hash = compute_content_hash(row["id"], text)

        record = {
            "id": row["id"],
            "title": (row["problem_description"] or "")[:80],
            "modality": "memory_methodology",
            "text": text,
            "metadata": {
                "language": row["language"] or "",
                "scope": row["scope"] or "global",
                "methodology_type": row["methodology_type"] or "PATTERN",
                "tags": tags,
                "success_count": row["success_count"] or 0,
                "retrieval_count": row["retrieval_count"] or 0,
                "novelty_score": row["novelty_score"],
                "potential_score": row["potential_score"],
                "created_at": row["created_at"] or "",
                "capability_data": cap_data,
            },
            "community_meta": {
                "pack_format_version": "1.0",
                "instance_id": instance_id,
                "contributor_alias": contributor_alias,
                "exported_at": now_iso,
                "origin_lifecycle": row["lifecycle_state"],
                "content_hash": content_hash,
                "source_repo_urls": source_urls,
            },
        }
        records.append(record)

    # Build manifest
    record_hashes = sorted(r["community_meta"]["content_hash"] for r in records)
    manifest_input = ":".join(record_hashes) + f":{instance_id}:{now_iso}"
    manifest_hash = hashlib.sha256(manifest_input.encode()).hexdigest()

    languages = {}
    for r in records:
        lang = r["metadata"].get("language", "other") or "other"
        languages[lang] = languages.get(lang, 0) + 1

    manifest = {
        "pack_format_version": "1.0",
        "instance_id": instance_id,
        "contributor_alias": contributor_alias,
        "exported_at": now_iso,
        "methodology_count": len(records),
        "domains": sorted(languages.keys()),
        "language_breakdown": languages,
        "lifecycle_filter": min_lifecycle,
        "record_hashes": record_hashes,
        "manifest_hash": manifest_hash,
    }

    return records, manifest
