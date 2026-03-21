"""Tests for CAM-PULSE database schema and operations."""

import json

import pytest
from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine


@pytest.fixture
async def pulse_engine():
    config = DatabaseConfig(db_path=":memory:")
    engine = DatabaseEngine(config)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    yield engine
    await engine.close()


class TestPulseSchema:
    @pytest.mark.asyncio
    async def test_pulse_discoveries_table_exists(self, pulse_engine):
        row = await pulse_engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='pulse_discoveries'"
        )
        assert row["cnt"] == 1

    @pytest.mark.asyncio
    async def test_pulse_scan_log_table_exists(self, pulse_engine):
        row = await pulse_engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='pulse_scan_log'"
        )
        assert row["cnt"] == 1

    @pytest.mark.asyncio
    async def test_insert_discovery(self, pulse_engine):
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, x_post_text, novelty_score,
                status, scan_id, keywords_matched)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ["d1", "https://github.com/test/repo", "https://github.com/test/repo",
             "Found this repo", 0.85, "discovered", "scan1", '["AI", "tool"]'],
        )
        row = await pulse_engine.fetch_one(
            "SELECT * FROM pulse_discoveries WHERE id = 'd1'"
        )
        assert row is not None
        assert row["canonical_url"] == "https://github.com/test/repo"
        assert row["novelty_score"] == 0.85
        assert row["status"] == "discovered"
        assert json.loads(row["keywords_matched"]) == ["AI", "tool"]

    @pytest.mark.asyncio
    async def test_discovery_unique_canonical_url(self, pulse_engine):
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, status)
               VALUES ('d1', 'https://github.com/test/a', 'https://github.com/test/a', 'discovered')"""
        )
        with pytest.raises(Exception):
            await pulse_engine.execute(
                """INSERT INTO pulse_discoveries
                   (id, github_url, canonical_url, status)
                   VALUES ('d2', 'https://github.com/test/a', 'https://github.com/test/a', 'discovered')"""
            )

    @pytest.mark.asyncio
    async def test_discovery_status_constraint(self, pulse_engine):
        with pytest.raises(Exception):
            await pulse_engine.execute(
                """INSERT INTO pulse_discoveries
                   (id, github_url, canonical_url, status)
                   VALUES ('d1', 'https://github.com/t/r', 'https://github.com/t/r', 'INVALID_STATUS')"""
            )

    @pytest.mark.asyncio
    async def test_insert_scan_log(self, pulse_engine):
        await pulse_engine.execute(
            """INSERT INTO pulse_scan_log
               (id, scan_type, keywords, repos_discovered, repos_novel, repos_assimilated)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ["s1", "x_search", '["AI", "tool"]', 10, 5, 3],
        )
        row = await pulse_engine.fetch_one(
            "SELECT * FROM pulse_scan_log WHERE id = 's1'"
        )
        assert row is not None
        assert row["scan_type"] == "x_search"
        assert row["repos_discovered"] == 10
        assert row["repos_novel"] == 5

    @pytest.mark.asyncio
    async def test_discovery_status_transitions(self, pulse_engine):
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, status)
               VALUES ('d1', 'https://github.com/test/r', 'https://github.com/test/r', 'discovered')"""
        )
        # Transition through states
        for status in ["cloning", "mining", "assimilated"]:
            await pulse_engine.execute(
                "UPDATE pulse_discoveries SET status = ? WHERE id = 'd1'",
                [status],
            )
            row = await pulse_engine.fetch_one(
                "SELECT status FROM pulse_discoveries WHERE id = 'd1'"
            )
            assert row["status"] == status

    @pytest.mark.asyncio
    async def test_scan_log_default_values(self, pulse_engine):
        await pulse_engine.execute(
            "INSERT INTO pulse_scan_log (id) VALUES ('s1')"
        )
        row = await pulse_engine.fetch_one(
            "SELECT * FROM pulse_scan_log WHERE id = 's1'"
        )
        assert row["scan_type"] == "x_search"
        assert row["repos_discovered"] == 0
        assert row["cost_usd"] == 0.0
        assert row["tokens_used"] == 0

    @pytest.mark.asyncio
    async def test_migration_idempotent(self, pulse_engine):
        """Running migrations again should not fail."""
        await pulse_engine.apply_migrations()
        await pulse_engine.initialize_schema()
        # Tables should still exist
        row = await pulse_engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='pulse_discoveries'"
        )
        assert row["cnt"] == 1
