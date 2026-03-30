"""Tests for `cam doctor routing` subcommand."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from claw.core.config import DatabaseConfig, KellyConfig


def _seed_agent_scores(db_path: Path) -> None:
    """Create agent_scores table and populate with test data."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS agent_scores (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                successes INTEGER DEFAULT 0,
                failures INTEGER DEFAULT 0,
                total_attempts INTEGER DEFAULT 0,
                avg_duration_seconds REAL DEFAULT 0.0,
                avg_quality_score REAL DEFAULT 0.5,
                avg_cost_usd REAL DEFAULT 0.0,
                last_used_at TEXT,
                created_at TEXT,
                updated_at TEXT
            )"""
        )
        conn.executemany(
            """INSERT INTO agent_scores
               (id, agent_id, task_type, successes, failures, total_attempts,
                avg_quality_score, avg_cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("1", "claude", "architecture", 5, 1, 6, 0.92, 0.05),
                ("2", "grok", "architecture", 2, 3, 5, 0.70, 0.03),
                ("3", "codex", "testing", 4, 0, 4, 0.88, 0.04),
                ("4", "claude", "testing", 1, 2, 3, 0.60, 0.05),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _create_empty_db(db_path: Path) -> None:
    """Create empty agent_scores table."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS agent_scores (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                successes INTEGER DEFAULT 0,
                failures INTEGER DEFAULT 0,
                total_attempts INTEGER DEFAULT 0,
                avg_duration_seconds REAL DEFAULT 0.0,
                avg_quality_score REAL DEFAULT 0.5,
                avg_cost_usd REAL DEFAULT 0.0,
                last_used_at TEXT,
                created_at TEXT,
                updated_at TEXT
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def _patched_config(db_path: Path, kelly_enabled: bool = True):
    """Return a patched load_config that points at tmp db."""
    from claw.core.config import load_config

    real_cfg = load_config(None)
    # Pydantic models are frozen, so reconstruct with overrides
    patched = real_cfg.model_copy(update={
        "database": DatabaseConfig(db_path=str(db_path)),
        "kelly": KellyConfig(enabled=kelly_enabled, kappa=10.0, f_max=0.40),
    })
    return lambda *a, **kw: patched


class TestDoctorRouting:
    """Tests for _doctor_routing_async."""

    def test_routing_disabled_message(self, tmp_path, capsys, monkeypatch):
        """When Kelly is disabled, show a message instead of a table."""
        from claw.cli import _doctor_routing_async

        db = tmp_path / "claw.db"
        _create_empty_db(db)

        monkeypatch.setattr("claw.core.config.load_config", _patched_config(db, kelly_enabled=False))
        asyncio.run(_doctor_routing_async(config_path=None))

        captured = capsys.readouterr().out
        assert "disabled" in captured.lower()

    def test_routing_shows_table(self, tmp_path, capsys, monkeypatch):
        """When Kelly is enabled with data, show a table with routing weights."""
        from claw.cli import _doctor_routing_async

        db = tmp_path / "claw.db"
        _seed_agent_scores(db)

        monkeypatch.setattr("claw.core.config.load_config", _patched_config(db, kelly_enabled=True))
        asyncio.run(_doctor_routing_async(config_path=None))

        captured = capsys.readouterr().out
        assert "claude" in captured
        assert "architecture" in captured

    def test_routing_empty_db(self, tmp_path, capsys, monkeypatch):
        """When no agent_scores exist, show an informational message."""
        from claw.cli import _doctor_routing_async

        db = tmp_path / "claw.db"
        _create_empty_db(db)

        monkeypatch.setattr("claw.core.config.load_config", _patched_config(db, kelly_enabled=True))
        asyncio.run(_doctor_routing_async(config_path=None))

        captured = capsys.readouterr().out
        assert "no agent_scores" in captured.lower() or "Run some tasks" in captured

    def test_routing_all_agents_present(self, tmp_path, capsys, monkeypatch):
        """All agents from the seeded data appear in output."""
        from claw.cli import _doctor_routing_async

        db = tmp_path / "claw.db"
        _seed_agent_scores(db)

        monkeypatch.setattr("claw.core.config.load_config", _patched_config(db, kelly_enabled=True))
        asyncio.run(_doctor_routing_async(config_path=None))

        captured = capsys.readouterr().out
        assert "claude" in captured
        assert "grok" in captured
        assert "codex" in captured
        assert "testing" in captured
