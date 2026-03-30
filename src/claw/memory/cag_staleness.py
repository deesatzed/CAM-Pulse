"""CAG cache staleness marker.

Lightweight module imported by mutation paths (miner, governance, etc.)
to mark the CAG cache as stale when methodologies change.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("claw.memory.cag_staleness")


def mark_cag_stale(
    cache_dir: str = "data/cag_caches",
    ganglion: str = "general",
) -> None:
    """Mark a ganglion's CAG cache as stale.

    Reads the existing meta.json (if any), sets stale=True, writes back.
    Creates a minimal meta entry if none exists.

    This is a sync function -- safe to call from any context.
    """
    meta_path = Path(cache_dir) / ganglion / "meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            meta = {}

    if not isinstance(meta, dict):
        meta = {}

    meta["ganglion"] = ganglion
    meta["stale"] = True
    meta_path.write_text(json.dumps(meta, indent=2))
    logger.debug("CAG cache marked stale for ganglion '%s'", ganglion)


def maybe_mark_cag_stale(config: Optional[object] = None) -> None:
    """Mark stale only if CAG is enabled in config.

    Safe to call even when config is None or CAG is disabled -- just a no-op.
    Extracts cache_dir from config.cag.cache_dir if available.
    """
    if config is None:
        return

    cag_cfg = getattr(config, "cag", None)
    if cag_cfg is None or not getattr(cag_cfg, "enabled", False):
        return

    cache_dir = getattr(cag_cfg, "cache_dir", "data/cag_caches")
    mark_cag_stale(cache_dir=cache_dir)
