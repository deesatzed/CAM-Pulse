"""Deterministic barcode helpers for CAM-SEQ identities.

These helpers generate stable identifiers from normalized inputs. The goal is
identity stability, not secrecy: the same semantic source should generate the
same barcode on repeated ingestion.
"""

from __future__ import annotations

import hashlib
import json
from typing import Iterable


def _norm(value: object) -> str:
    """Normalize an arbitrary value into a stable string token."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).strip()
    return " ".join(text.split())


def _norm_list(values: Iterable[object]) -> list[str]:
    """Normalize a collection and sort it for stable hashing."""
    cleaned = [_norm(v) for v in values if _norm(v)]
    return sorted(set(cleaned))


def _digest(prefix: str, *parts: object) -> str:
    payload = "|".join(_norm(p) for p in parts)
    hexdigest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}_{hexdigest[:16]}"


def build_source_barcode(
    repo: str,
    file_path: str,
    content_hash: str,
    *,
    commit_sha: str | None = None,
    symbol_name: str | None = None,
) -> str:
    """Stable identity for a mined source component.

    Line numbers are intentionally excluded because they are too fragile to act
    as identity anchors across benign file edits.
    """
    return _digest(
        "src",
        repo,
        commit_sha or "",
        file_path,
        symbol_name or "",
        content_hash,
    )


def build_family_barcode(component_type: str, abstract_job: str) -> str:
    """Stable family identity for a reusable job pattern."""
    return _digest("fam", component_type, abstract_job)


def build_slot_barcode(
    task_archetype: str,
    slot_name: str,
    *,
    constraints: Iterable[object] = (),
    target_stack: Iterable[object] = (),
) -> str:
    """Stable identity for a task slot under given constraints."""
    return _digest(
        "slot",
        task_archetype,
        slot_name,
        json.dumps(_norm_list(constraints), separators=(",", ":")),
        json.dumps(_norm_list(target_stack), separators=(",", ":")),
    )


def build_pair_barcode(
    run_id: str,
    slot_barcode: str,
    source_barcode: str,
    *,
    adapter_version: str = "v1",
) -> str:
    """Derived identity for a runtime slot-to-component pairing."""
    return _digest("pair", run_id, slot_barcode, source_barcode, adapter_version)


def build_locus_barcode(
    target_repo: str,
    file_path: str,
    *,
    symbol_name: str | None = None,
    diff_hunk_id: str | None = None,
) -> str:
    """Derived identity for a landing site in the target repo."""
    return _digest("locus", target_repo, file_path, symbol_name or "", diff_hunk_id or "")


def build_outcome_barcode(
    pair_barcode: str,
    verdict: str,
    *,
    tests: Iterable[object] = (),
    findings: Iterable[object] = (),
    files_touched: Iterable[object] = (),
) -> str:
    """Derived identity for the sequenced result of a pairing."""
    return _digest(
        "out",
        pair_barcode,
        verdict,
        json.dumps(_norm_list(tests), separators=(",", ":")),
        json.dumps(_norm_list(findings), separators=(",", ":")),
        json.dumps(_norm_list(files_touched), separators=(",", ":")),
    )
