"""Tests for CAG cache staleness marker."""

from __future__ import annotations

import json
from types import SimpleNamespace

from claw.memory.cag_staleness import mark_cag_stale, maybe_mark_cag_stale


def test_mark_cag_stale_creates_meta(tmp_path):
    """mark_cag_stale on empty dir creates meta.json with stale=True."""
    cache_dir = str(tmp_path / "cag_caches")
    mark_cag_stale(cache_dir=cache_dir, ganglion="general")

    meta_path = tmp_path / "cag_caches" / "general" / "meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["stale"] is True
    assert meta["ganglion"] == "general"


def test_mark_cag_stale_updates_existing(tmp_path):
    """mark_cag_stale updates stale=False to stale=True."""
    cache_dir = str(tmp_path / "cag_caches")
    ganglion_dir = tmp_path / "cag_caches" / "general"
    ganglion_dir.mkdir(parents=True)
    meta_path = ganglion_dir / "meta.json"
    meta_path.write_text(json.dumps({"ganglion": "general", "stale": False}))

    mark_cag_stale(cache_dir=cache_dir, ganglion="general")

    meta = json.loads(meta_path.read_text())
    assert meta["stale"] is True


def test_mark_cag_stale_preserves_other_fields(tmp_path):
    """mark_cag_stale preserves existing fields like methodology_count."""
    cache_dir = str(tmp_path / "cag_caches")
    ganglion_dir = tmp_path / "cag_caches" / "general"
    ganglion_dir.mkdir(parents=True)
    meta_path = ganglion_dir / "meta.json"
    meta_path.write_text(json.dumps({
        "ganglion": "general",
        "stale": False,
        "methodology_count": 100,
        "built_at": "2026-03-30T00:00:00Z",
    }))

    mark_cag_stale(cache_dir=cache_dir, ganglion="general")

    meta = json.loads(meta_path.read_text())
    assert meta["stale"] is True
    assert meta["methodology_count"] == 100
    assert meta["built_at"] == "2026-03-30T00:00:00Z"


def test_maybe_mark_stale_noop_when_disabled(tmp_path):
    """maybe_mark_cag_stale is a no-op when cag.enabled=False."""
    cache_dir = str(tmp_path / "cag_caches")
    config = SimpleNamespace(
        cag=SimpleNamespace(enabled=False, cache_dir=cache_dir),
    )

    maybe_mark_cag_stale(config)

    meta_path = tmp_path / "cag_caches" / "general" / "meta.json"
    assert not meta_path.exists()


def test_maybe_mark_stale_noop_when_no_config(tmp_path):
    """maybe_mark_cag_stale does not crash when config is None."""
    maybe_mark_cag_stale(None)
    # No assertion needed -- just verifying no exception is raised


def test_maybe_mark_stale_triggers_when_enabled(tmp_path):
    """maybe_mark_cag_stale writes meta when cag.enabled=True."""
    cache_dir = str(tmp_path / "cag_caches")
    config = SimpleNamespace(
        cag=SimpleNamespace(enabled=True, cache_dir=cache_dir),
    )

    maybe_mark_cag_stale(config)

    meta_path = tmp_path / "cag_caches" / "general" / "meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["stale"] is True
    assert meta["ganglion"] == "general"
