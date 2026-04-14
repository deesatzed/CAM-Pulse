"""Optional SCIP index helpers for CAM-SEQ.

This module is intentionally lightweight in M2: it can detect common SCIP
index locations and parse JSON/JSONL exports when present. Native `.scip`
protobuf decoding is deferred until a dedicated parser dependency is added.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class ScipSymbolRecord:
    symbol: str
    file_path: str
    kind: str = "symbol"
    line_start: Optional[int] = None
    line_end: Optional[int] = None


_COMMON_INDEX_PATHS = [
    ".scip/index.json",
    ".scip/index.jsonl",
    "index.scip.json",
    "index.scip.jsonl",
    "scip.json",
    "scip.jsonl",
    "index.scip",
]


def detect_scip_index(repo_path: Path) -> Optional[Path]:
    """Return the first recognizable SCIP index path under a repo."""
    for rel in _COMMON_INDEX_PATHS:
        candidate = repo_path / rel
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _parse_json_symbol(item: dict[str, Any]) -> Optional[ScipSymbolRecord]:
    symbol = str(item.get("symbol") or item.get("symbol_name") or "").strip()
    file_path = str(item.get("file_path") or item.get("path") or "").strip()
    if not symbol or not file_path:
        return None
    return ScipSymbolRecord(
        symbol=symbol,
        file_path=file_path,
        kind=str(item.get("kind") or item.get("symbol_kind") or "symbol"),
        line_start=item.get("line_start"),
        line_end=item.get("line_end"),
    )


def load_scip_symbols(index_path: Path) -> list[ScipSymbolRecord]:
    """Load symbol records from a JSON/JSONL SCIP export.

    Unsupported binary `.scip` files return an empty list in M2.
    """
    suffixes = "".join(index_path.suffixes).lower()
    if suffixes.endswith(".scip"):
        return []

    try:
        text = index_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    records: list[ScipSymbolRecord] = []
    if suffixes.endswith(".jsonl"):
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            parsed = _parse_json_symbol(item)
            if parsed is not None:
                records.append(parsed)
        return records

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        items = payload.get("symbols") or payload.get("entries") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        parsed = _parse_json_symbol(item)
        if parsed is not None:
            records.append(parsed)
    return records


def load_repo_scip(repo_path: Path) -> tuple[Optional[Path], list[ScipSymbolRecord]]:
    """Detect and load a repo-local SCIP export if available."""
    index_path = detect_scip_index(repo_path)
    if index_path is None:
        return None, []
    return index_path, load_scip_symbols(index_path)
