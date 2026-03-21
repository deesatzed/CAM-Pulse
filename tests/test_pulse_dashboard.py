"""Tests for CAM-PULSE dashboard."""

import json

import pytest
from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine
from claw.pulse.dashboard import PulseDashboard, _parse_json_list, _truncate


@pytest.fixture
async def pulse_engine():
    config = DatabaseConfig(db_path=":memory:")
    engine = DatabaseEngine(config)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    yield engine
    await engine.close()


class TestHelpers:
    def test_parse_json_list_from_string(self):
        assert _parse_json_list('["a", "b"]') == ["a", "b"]

    def test_parse_json_list_from_list(self):
        assert _parse_json_list(["a", "b"]) == ["a", "b"]

    def test_parse_json_list_invalid(self):
        assert _parse_json_list("not json") == []

    def test_parse_json_list_none(self):
        assert _parse_json_list(None) == []

    def test_truncate_short(self):
        assert _truncate("short", 10) == "short"

    def test_truncate_long(self):
        assert _truncate("a very long string here", 10) == "a very ..."

    def test_truncate_exact(self):
        assert _truncate("12345", 5) == "12345"


class TestPulseDashboard:
    @pytest.mark.asyncio
    async def test_show_stats_empty(self, pulse_engine, capsys):
        dash = PulseDashboard(pulse_engine)
        await dash.show_stats()
        # Should not raise with empty database

    @pytest.mark.asyncio
    async def test_show_novel_empty(self, pulse_engine, capsys):
        dash = PulseDashboard(pulse_engine)
        await dash.show_novel()
        # Should not raise

    @pytest.mark.asyncio
    async def test_show_scans_empty(self, pulse_engine, capsys):
        dash = PulseDashboard(pulse_engine)
        await dash.show_scans()
        # Should not raise

    @pytest.mark.asyncio
    async def test_show_novel_with_data(self, pulse_engine):
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, novelty_score, status, keywords_matched)
               VALUES ('d1', 'https://github.com/test/repo', 'https://github.com/test/repo',
                       0.85, 'discovered', '["AI tool"]')"""
        )
        dash = PulseDashboard(pulse_engine)
        await dash.show_novel(limit=10)  # Should not raise

    @pytest.mark.asyncio
    async def test_show_scans_with_data(self, pulse_engine):
        await pulse_engine.execute(
            """INSERT INTO pulse_scan_log
               (id, repos_discovered, repos_novel, repos_assimilated)
               VALUES ('scan1', 5, 3, 2)"""
        )
        dash = PulseDashboard(pulse_engine)
        await dash.show_scans(limit=10)  # Should not raise

    @pytest.mark.asyncio
    async def test_show_daily_report_empty(self, pulse_engine):
        dash = PulseDashboard(pulse_engine)
        await dash.show_daily_report(date="2026-03-21")
        # Should not raise
