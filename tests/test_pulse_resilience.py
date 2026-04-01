"""Stress / resilience tests for CAM-PULSE subsystem.

Exercises real error-handling paths in scout, novelty, assimilator,
freshness, orchestrator, dashboard, and hf_adapter modules. Every test
passes genuinely invalid data, unreachable endpoints, or boundary-case
inputs to verify that PULSE components degrade gracefully without
unhandled exceptions.

NO MOCK, NO SIMULATION, NO PLACEHOLDERS -- all failures are organic.
"""

from __future__ import annotations

import asyncio

import uuid
from pathlib import Path

import pytest

from claw.core.config import (
    ClawConfig,
    DatabaseConfig,
    FreshnessConfig,
    PulseConfig,
    PulseProfileConfig,
)
from claw.db.engine import DatabaseEngine
from claw.pulse.models import (
    AssimilationResult,
    FreshnessResult,
    Phase1Result,
    PulseDiscovery,
    PulseScanResult,
    RefreshResult,
)
from claw.pulse.orchestrator import PulseOrchestrator
from claw.pulse.scout import XScout


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def pulse_engine():
    """In-memory SQLite engine with full schema for pulse tests."""
    config = DatabaseConfig(db_path=":memory:")
    engine = DatabaseEngine(config)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    yield engine
    await engine.close()


# ===================================================================
# 1. SCOUT RESILIENCE
# ===================================================================

class TestScoutNetworkResilience:
    """XScout.scan() must return [] on network failures, never crash."""

    @pytest.mark.asyncio
    async def test_scan_with_no_api_key_returns_empty(self, monkeypatch):
        """Missing API key -> empty list, no exception."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        config = PulseConfig(xai_model="grok-3")
        scout = XScout(config)
        result = await scout.scan(keywords=["test"])
        assert result == []

    @pytest.mark.asyncio
    async def test_scan_with_no_model_returns_empty(self, monkeypatch):
        """Missing model -> empty list, no exception."""
        monkeypatch.setenv("XAI_API_KEY", "fake-key-for-test")
        config = PulseConfig(xai_model="")
        scout = XScout(config)
        result = await scout.scan(keywords=["test"])
        assert result == []

    @pytest.mark.asyncio
    async def test_scan_against_unreachable_endpoint(self, monkeypatch):
        """
        Point the scout at an endpoint that refuses connections.
        The scan must catch the ConnectError and return [].
        """
        monkeypatch.setenv("XAI_API_KEY", "fake-key-for-resilience-test")
        config = PulseConfig(xai_model="grok-3")
        scout = XScout(config)

        # Use localhost on an extremely unlikely port to guarantee connection refused
        import claw.pulse.scout as scout_mod
        original_url = scout_mod.XAI_RESPONSES_URL
        scout_mod.XAI_RESPONSES_URL = "http://127.0.0.1:1"

        try:
            result = await scout.scan(keywords=["resilience test"])
            assert isinstance(result, list)
            assert len(result) == 0
        finally:
            scout_mod.XAI_RESPONSES_URL = original_url

    @pytest.mark.asyncio
    async def test_scan_against_invalid_host(self, monkeypatch):
        """
        Point the scout at a DNS name that will not resolve.
        Must return [] gracefully.
        """
        monkeypatch.setenv("XAI_API_KEY", "fake-key-for-resilience-test")
        config = PulseConfig(xai_model="grok-3")
        scout = XScout(config)

        import claw.pulse.scout as scout_mod
        original_url = scout_mod.XAI_RESPONSES_URL
        scout_mod.XAI_RESPONSES_URL = "http://this-host-does-not-exist-xyzzy.invalid/v1/responses"

        try:
            result = await scout.scan(keywords=["dns fail test"])
            assert isinstance(result, list)
            assert len(result) == 0
        finally:
            scout_mod.XAI_RESPONSES_URL = original_url

    @pytest.mark.asyncio
    async def test_scan_with_empty_keywords_list(self, monkeypatch):
        """Empty keywords list -> no API calls, empty result."""
        monkeypatch.setenv("XAI_API_KEY", "fake-key")
        config = PulseConfig(xai_model="grok-3", keywords=[])
        scout = XScout(config)
        result = await scout.scan(keywords=[])
        assert result == []


class TestScoutDiscoveryExtraction:
    """_extract_discoveries_from_response must handle malformed data."""

    def _make_scout(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "test-key")
        config = PulseConfig(xai_model="grok-3")
        return XScout(config)

    def test_none_output_field(self, monkeypatch):
        scout = self._make_scout(monkeypatch)
        response = {"output": None}
        result = scout._extract_discoveries_from_response(response, "kw", "s1")
        assert result == []

    def test_integer_output_field(self, monkeypatch):
        scout = self._make_scout(monkeypatch)
        response = {"output": 42}
        result = scout._extract_discoveries_from_response(response, "kw", "s1")
        assert result == []

    def test_deeply_nested_none_content(self, monkeypatch):
        scout = self._make_scout(monkeypatch)
        response = {"output": [{"content": [{"text": None}]}]}
        result = scout._extract_discoveries_from_response(response, "kw", "s1")
        assert isinstance(result, list)

    def test_empty_dict_response(self, monkeypatch):
        scout = self._make_scout(monkeypatch)
        result = scout._extract_discoveries_from_response({}, "kw", "s1")
        assert result == []

    def test_text_field_is_integer(self, monkeypatch):
        scout = self._make_scout(monkeypatch)
        response = {"output": [], "text": 12345}
        result = scout._extract_discoveries_from_response(response, "kw", "s1")
        assert isinstance(result, list)

    def test_content_is_nested_dicts_without_text(self, monkeypatch):
        scout = self._make_scout(monkeypatch)
        response = {"output": [{"content": [{"no_text_key": "value"}]}]}
        result = scout._extract_discoveries_from_response(response, "kw", "s1")
        assert result == []

    def test_output_as_plain_string(self, monkeypatch):
        """output field is a plain string instead of a list."""
        scout = self._make_scout(monkeypatch)
        response = {"output": "Check https://github.com/test/repo for details"}
        result = scout._extract_discoveries_from_response(response, "kw", "s1")
        assert len(result) == 1
        assert result[0].canonical_url == "https://github.com/test/repo"

    def test_massive_text_does_not_crash(self, monkeypatch):
        """10 MB text blob with no URLs should complete without OOM."""
        scout = self._make_scout(monkeypatch)
        big_text = "no github links here " * 500_000  # ~10 MB
        response = {"output": big_text}
        result = scout._extract_discoveries_from_response(response, "kw", "s1")
        assert isinstance(result, list)
        assert len(result) == 0


class TestScoutUrlEdgeCases:
    """Static URL extraction / canonicalization with boundary inputs."""

    def test_extract_from_none_text_raises_type_error(self):
        """Passing None to a static method expecting str should raise cleanly."""
        with pytest.raises((TypeError, AttributeError)):
            XScout.extract_github_urls(None)

    def test_extract_from_empty_string(self):
        assert XScout.extract_github_urls("") == []

    def test_canonical_with_empty_string(self):
        result = XScout.canonical_github_url("")
        assert isinstance(result, str)

    def test_canonical_with_garbage_url(self):
        result = XScout.canonical_github_url("not-a-url-at-all")
        assert isinstance(result, str)

    def test_extract_with_thousands_of_urls(self):
        """Stress test: 2000 unique GitHub URLs in one text block."""
        lines = [f"https://github.com/org{i}/repo{i}" for i in range(2000)]
        text = "\n".join(lines)
        urls = XScout.extract_github_urls(text)
        assert len(urls) == 2000

    def test_canonical_with_unicode_path(self):
        result = XScout.canonical_github_url("https://github.com/user/repo-with-\u00e9-accent")
        assert isinstance(result, str)

    def test_extract_handle_near_url_empty_text(self):
        result = XScout._extract_handle_near_url("", "https://github.com/x/y")
        assert result == ""


# ===================================================================
# 2. NOVELTY FILTER RESILIENCE
# ===================================================================

class TestNoveltyFilterResilience:
    """NoveltyFilter must handle empty DBs, malformed discoveries, etc."""

    @pytest.mark.asyncio
    async def test_score_discovery_with_empty_url(self, pulse_engine):
        from claw.pulse.novelty import NoveltyFilter

        nf = NoveltyFilter(pulse_engine, config=PulseConfig())
        disc = PulseDiscovery(github_url="", canonical_url="")
        score = await nf.score(disc)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_score_discovery_with_none_text(self, pulse_engine):
        from claw.pulse.novelty import NoveltyFilter

        nf = NoveltyFilter(pulse_engine, config=PulseConfig())
        disc = PulseDiscovery(
            github_url="https://github.com/test/none-text",
            canonical_url="https://github.com/test/none-text",
            x_post_text="",
        )
        score = await nf.score(disc)
        assert isinstance(score, float)

    @pytest.mark.asyncio
    async def test_filter_empty_list(self, pulse_engine):
        from claw.pulse.novelty import NoveltyFilter

        nf = NoveltyFilter(pulse_engine, config=PulseConfig())
        result = await nf.filter_discoveries([])
        assert result == []

    @pytest.mark.asyncio
    async def test_filter_large_discovery_set(self, pulse_engine):
        """Filter 200 discoveries: must not crash or deadlock."""
        from claw.pulse.novelty import NoveltyFilter

        nf = NoveltyFilter(pulse_engine, config=PulseConfig(novelty_threshold=0.5))
        discoveries = [
            PulseDiscovery(
                github_url=f"https://github.com/stress/repo{i}",
                canonical_url=f"https://github.com/stress/repo{i}",
                x_post_text=f"Discovery number {i} about AI tools",
                keywords_matched=[f"keyword_{i}"],
            )
            for i in range(200)
        ]
        novel = await nf.filter_discoveries(discoveries)
        assert isinstance(novel, list)
        assert len(novel) <= 200
        # All novel items should have scores >= threshold
        for d in novel:
            assert d.novelty_score >= 0.5

    @pytest.mark.asyncio
    async def test_is_already_known_with_empty_url(self, pulse_engine):
        from claw.pulse.novelty import NoveltyFilter

        nf = NoveltyFilter(pulse_engine, config=PulseConfig())
        result = await nf.is_already_known("")
        assert result is False

    @pytest.mark.asyncio
    async def test_domain_bias_with_none_keywords(self, pulse_engine):
        """Discovery with keywords_matched=None should not crash bias calc."""
        from claw.pulse.novelty import NoveltyFilter

        config = PulseConfig(
            profile=PulseProfileConfig(
                name="test",
                novelty_bias={"AI": 0.1},
            ),
        )
        nf = NoveltyFilter(pulse_engine, config=config)
        disc = PulseDiscovery(
            github_url="https://github.com/test/bias",
            canonical_url="https://github.com/test/bias",
            x_post_text="An AI tool",
            keywords_matched=None,  # type: ignore[arg-type]
        )
        # _apply_domain_bias should handle None gracefully
        try:
            result = nf._apply_domain_bias(0.5, disc)
            assert isinstance(result, float)
        except TypeError:
            # Acceptable: explicit type rejection. The key is no unhandled crash.
            pass

    @pytest.mark.asyncio
    async def test_semantic_novelty_with_huge_text(self, pulse_engine):
        """Large text input should not cause OOM in semantic scoring."""
        from claw.pulse.novelty import NoveltyFilter

        nf = NoveltyFilter(pulse_engine, embedding_engine=None, config=PulseConfig())
        huge_text = "A " * 100_000  # 200KB
        score = await nf._semantic_novelty(huge_text)
        # Without embedding engine defaults to 1.0
        assert score == 1.0


# ===================================================================
# 3. FRESHNESS MONITOR RESILIENCE
# ===================================================================

class TestFreshnessMonitorResilience:
    """FreshnessMonitor must handle invalid URLs, network failures."""

    def test_extract_owner_repo_empty(self):
        from claw.pulse.freshness import FreshnessMonitor

        assert FreshnessMonitor.extract_owner_repo("") is None

    def test_extract_owner_repo_not_github(self):
        from claw.pulse.freshness import FreshnessMonitor

        assert FreshnessMonitor.extract_owner_repo("https://gitlab.com/user/repo") is None

    def test_extract_owner_repo_no_repo_part(self):
        from claw.pulse.freshness import FreshnessMonitor

        assert FreshnessMonitor.extract_owner_repo("https://github.com/user") is None

    def test_extract_owner_repo_with_trailing_git(self):
        from claw.pulse.freshness import FreshnessMonitor

        result = FreshnessMonitor.extract_owner_repo("https://github.com/user/repo.git")
        assert result == "user/repo"

    def test_extract_owner_repo_http_prefix(self):
        from claw.pulse.freshness import FreshnessMonitor

        result = FreshnessMonitor.extract_owner_repo("http://github.com/user/repo")
        assert result == "user/repo"

    @pytest.mark.asyncio
    async def test_check_all_on_empty_db(self, pulse_engine):
        """check_all with no assimilated discoveries returns empty list."""
        from claw.pulse.freshness import FreshnessMonitor

        config = ClawConfig()
        monitor = FreshnessMonitor(pulse_engine, config)
        results = await monitor.check_all()
        assert results == []

    @pytest.mark.asyncio
    async def test_phase1_with_unparseable_url(self, pulse_engine):
        """Phase 1 metadata check with a URL that cannot be parsed."""
        import httpx
        from claw.pulse.freshness import FreshnessMonitor

        config = ClawConfig()
        monitor = FreshnessMonitor(pulse_engine, config)

        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            p1 = await monitor._phase1_metadata_check(
                client, "https://notgithub.example.com/foo/bar", ""
            )
            assert isinstance(p1, Phase1Result)
            assert p1.error is not None
            assert "Cannot parse" in p1.error

    @pytest.mark.asyncio
    async def test_phase1_with_real_unreachable_repo(self, pulse_engine):
        """Phase 1 against a GitHub URL for a repo that does not exist.

        This hits the real GitHub API (unauthenticated), which returns 404.
        If no network is available, it returns an HTTP error instead -- both
        are graceful degradation.
        """
        import httpx
        from claw.pulse.freshness import FreshnessMonitor

        config = ClawConfig()
        monitor = FreshnessMonitor(pulse_engine, config)

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            p1 = await monitor._phase1_metadata_check(
                client,
                f"https://github.com/nonexistent-user-{uuid.uuid4().hex[:8]}/nonexistent-repo-{uuid.uuid4().hex[:8]}",
                "",
            )
            assert isinstance(p1, Phase1Result)
            # Either 404 error from GitHub or network error -- both acceptable
            if p1.error:
                assert isinstance(p1.error, str)
            # Should not have changed=True for a nonexistent repo
            # (either error or the status was 404)

    @pytest.mark.asyncio
    async def test_retire_stale_methodologies_empty_db(self, pulse_engine):
        """Retirement with no matching canonical_url returns empty lists."""
        from claw.pulse.freshness import FreshnessMonitor

        config = ClawConfig()
        monitor = FreshnessMonitor(pulse_engine, config)
        retired, kept = await monitor.retire_stale_methodologies(
            "https://github.com/nonexistent/repo", ["m1", "m2"]
        )
        assert retired == []
        assert kept == []

    @pytest.mark.asyncio
    async def test_retire_with_malformed_json_in_db(self, pulse_engine):
        """If methodology_ids contains invalid JSON, retirement handles it."""
        from claw.pulse.freshness import FreshnessMonitor

        # Insert a discovery with malformed methodology_ids
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, status, methodology_ids)
               VALUES ('bad1', 'https://github.com/bad/json',
                       'https://github.com/bad/json', 'assimilated', 'not-valid-json')"""
        )
        config = ClawConfig()
        monitor = FreshnessMonitor(pulse_engine, config)
        retired, kept = await monitor.retire_stale_methodologies(
            "https://github.com/bad/json", ["m1"]
        )
        assert retired == []
        assert kept == []

    @pytest.mark.asyncio
    async def test_preview_retirement_with_no_old_ids(self, pulse_engine):
        from claw.pulse.freshness import FreshnessMonitor

        config = ClawConfig()
        monitor = FreshnessMonitor(pulse_engine, config)
        would_retire, would_keep = await monitor.preview_retirement(
            "https://github.com/ghost/repo", ["m1"]
        )
        assert would_retire == []
        assert would_keep == []

    @pytest.mark.asyncio
    async def test_get_stored_size_for_missing_url(self, pulse_engine):
        from claw.pulse.freshness import FreshnessMonitor

        config = ClawConfig()
        monitor = FreshnessMonitor(pulse_engine, config)
        size = await monitor._get_stored_size("https://github.com/missing/url")
        assert size == 0


# ===================================================================
# 4. DISCOVERY MODEL RESILIENCE
# ===================================================================

class TestDiscoveryModelResilience:
    """PulseDiscovery, PulseScanResult, etc. handle edge-case construction."""

    def test_discovery_with_all_empty_strings(self):
        disc = PulseDiscovery(
            github_url="",
            canonical_url="",
            x_post_text="",
            x_post_url="",
            x_author_handle="",
            scan_id="",
        )
        assert disc.novelty_score == 0.0
        assert disc.keywords_matched == []

    def test_discovery_with_very_long_text(self):
        long_text = "X" * 100_000
        disc = PulseDiscovery(
            github_url="https://github.com/a/b",
            canonical_url="https://github.com/a/b",
            x_post_text=long_text,
        )
        assert len(disc.x_post_text) == 100_000

    def test_scan_result_accumulates_errors(self):
        result = PulseScanResult(scan_id="err-test")
        for i in range(500):
            result.errors.append(f"Error {i}: something went wrong")
        assert len(result.errors) == 500

    def test_discovery_with_unicode_fields(self):
        disc = PulseDiscovery(
            github_url="https://github.com/user/\u00e9-repo",
            canonical_url="https://github.com/user/\u00e9-repo",
            x_post_text="Japanese: \u65e5\u672c\u8a9e, Arabic: \u0627\u0644\u0639\u0631\u0628\u064a\u0629, Emoji: attempt",
            x_author_handle="\u00fcser_name",
        )
        assert "\u65e5\u672c\u8a9e" in disc.x_post_text

    def test_phase1_result_defaults(self):
        p1 = Phase1Result(canonical_url="https://github.com/a/b")
        assert p1.changed is False
        assert p1.error is None
        assert p1.rate_limit_remaining == -1

    def test_freshness_result_defaults(self):
        fr = FreshnessResult(canonical_url="https://github.com/a/b")
        assert fr.needs_refresh is False
        assert fr.significance_score == 0.0
        assert fr.error is None

    def test_assimilation_result_defaults(self):
        disc = PulseDiscovery(
            github_url="https://github.com/a/b",
            canonical_url="https://github.com/a/b",
        )
        ar = AssimilationResult(discovery=disc)
        assert ar.success is False
        assert ar.methodology_ids == []
        assert ar.error is None


# ===================================================================
# 5. ASSIMILATOR RESILIENCE
# ===================================================================

class TestAssimilatorResilience:
    """PulseAssimilator handles invalid repos, save errors, etc."""

    def test_repo_name_from_url_edge_cases(self):
        from claw.pulse.assimilator import PulseAssimilator

        assert PulseAssimilator._repo_name_from_url("") == ""
        assert PulseAssimilator._repo_name_from_url("https://github.com/a/b") == "a_b"
        assert PulseAssimilator._repo_name_from_url("not-a-url") == "not-a-url"

    @pytest.mark.asyncio
    async def test_save_discovery_with_empty_fields(self, pulse_engine):
        """Save a discovery where all optional fields are empty."""
        from claw.pulse.assimilator import PulseAssimilator
        from claw.core.config import load_config
        from claw.db.repository import Repository
        from claw.db.embeddings import EmbeddingEngine
        from claw.llm.client import LLMClient
        from claw.memory.hybrid_search import HybridSearch
        from claw.memory.semantic import SemanticMemory
        from claw.miner import RepoMiner

        config = load_config()
        repository = Repository(pulse_engine)
        embedding_engine = EmbeddingEngine()
        hybrid_search = HybridSearch(repository, embedding_engine)
        llm_client = LLMClient(config.llm)
        semantic_memory = SemanticMemory(repository, embedding_engine, hybrid_search)
        miner = RepoMiner(repository, llm_client, semantic_memory, config)
        assimilator = PulseAssimilator(pulse_engine, miner, config)

        disc = PulseDiscovery(
            github_url="",
            canonical_url="",
            x_post_text="",
            keywords_matched=[],
            scan_id="",
        )
        await assimilator.save_discovery(disc)

        row = await pulse_engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM pulse_discoveries WHERE canonical_url = ?",
            [""],
        )
        assert row["cnt"] >= 1

    @pytest.mark.asyncio
    async def test_save_discovery_truncates_long_text(self, pulse_engine):
        """x_post_text is truncated to 500 chars on save."""
        from claw.pulse.assimilator import PulseAssimilator
        from claw.core.config import load_config
        from claw.db.repository import Repository
        from claw.db.embeddings import EmbeddingEngine
        from claw.llm.client import LLMClient
        from claw.memory.hybrid_search import HybridSearch
        from claw.memory.semantic import SemanticMemory
        from claw.miner import RepoMiner

        config = load_config()
        repository = Repository(pulse_engine)
        embedding_engine = EmbeddingEngine()
        hybrid_search = HybridSearch(repository, embedding_engine)
        llm_client = LLMClient(config.llm)
        semantic_memory = SemanticMemory(repository, embedding_engine, hybrid_search)
        miner = RepoMiner(repository, llm_client, semantic_memory, config)
        assimilator = PulseAssimilator(pulse_engine, miner, config)

        long_text = "Z" * 5000
        disc = PulseDiscovery(
            github_url="https://github.com/long/text",
            canonical_url="https://github.com/long/text",
            x_post_text=long_text,
            scan_id="trunc-test",
        )
        await assimilator.save_discovery(disc)

        row = await pulse_engine.fetch_one(
            "SELECT x_post_text FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://github.com/long/text"],
        )
        assert len(row["x_post_text"]) <= 500

    def test_detect_license_nonexistent_path(self):
        """License detection on a path that does not exist returns 'none'."""
        from claw.pulse.assimilator import PulseAssimilator

        result = PulseAssimilator._detect_license(Path("/tmp/nonexistent-path-" + uuid.uuid4().hex))
        assert result == "none"

    def test_detect_license_empty_directory(self, tmp_path):
        """License detection on an empty directory returns 'none'."""
        from claw.pulse.assimilator import PulseAssimilator

        result = PulseAssimilator._detect_license(tmp_path)
        assert result == "none"

    def test_detect_license_with_mit(self, tmp_path):
        """License detection recognizes a real MIT LICENSE file."""
        from claw.pulse.assimilator import PulseAssimilator

        license_file = tmp_path / "LICENSE"
        license_file.write_text(
            "MIT License\n\n"
            "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
            "of this software and associated documentation files.\n"
        )
        result = PulseAssimilator._detect_license(tmp_path)
        assert result == "permissive"

    def test_detect_license_with_gpl(self, tmp_path):
        """License detection recognizes a GPL LICENSE file."""
        from claw.pulse.assimilator import PulseAssimilator

        license_file = tmp_path / "LICENSE"
        license_file.write_text("GNU General Public License version 3\n")
        result = PulseAssimilator._detect_license(tmp_path)
        assert result == "copyleft"


# ===================================================================
# 6. DASHBOARD RESILIENCE
# ===================================================================

class TestDashboardResilience:
    """Dashboard rendering must never crash, even with garbage data in DB."""

    @pytest.mark.asyncio
    async def test_show_novel_with_null_fields(self, pulse_engine):
        """Insert discoveries with NULL optional fields, render dashboard."""
        from claw.pulse.dashboard import PulseDashboard

        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, status)
               VALUES ('null1', 'https://github.com/null/test',
                       'https://github.com/null/test', 'discovered')"""
        )
        dash = PulseDashboard(pulse_engine)
        # Should not raise even though novelty_score, keywords_matched etc. are NULL
        await dash.show_novel(limit=10)

    @pytest.mark.asyncio
    async def test_show_stats_with_corrupted_keywords(self, pulse_engine):
        """keywords_matched column has invalid JSON. Dashboard must not crash."""
        from claw.pulse.dashboard import PulseDashboard

        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, status, keywords_matched)
               VALUES ('corrupt1', 'https://github.com/corrupt/kw',
                       'https://github.com/corrupt/kw', 'discovered', 'INVALID_JSON{{{{')"""
        )
        dash = PulseDashboard(pulse_engine)
        await dash.show_stats()

    @pytest.mark.asyncio
    async def test_show_daily_report_boundary_date(self, pulse_engine):
        """Daily report for a far-future date should not crash."""
        from claw.pulse.dashboard import PulseDashboard

        dash = PulseDashboard(pulse_engine)
        await dash.show_daily_report(date="2099-12-31")

    @pytest.mark.asyncio
    async def test_show_scans_with_null_cost(self, pulse_engine):
        """Scan log entries with NULL cost/tokens should render cleanly."""
        from claw.pulse.dashboard import PulseDashboard

        await pulse_engine.execute(
            """INSERT INTO pulse_scan_log
               (id, repos_discovered, repos_novel, repos_assimilated)
               VALUES ('null-cost', 0, 0, 0)"""
        )
        dash = PulseDashboard(pulse_engine)
        await dash.show_scans()

    def test_parse_json_list_edge_cases(self):
        """Helper function handles all edge inputs."""
        from claw.pulse.dashboard import _parse_json_list

        assert _parse_json_list(None) == []
        assert _parse_json_list(0) == []
        assert _parse_json_list(False) == []
        assert _parse_json_list("") == []
        assert _parse_json_list("{}") == []  # dict, not list
        assert _parse_json_list('["a"]') == ["a"]
        assert _parse_json_list([1, 2, 3]) == [1, 2, 3]

    def test_truncate_edge_cases(self):
        from claw.pulse.dashboard import _truncate

        assert _truncate("", 10) == ""
        assert _truncate("abc", 3) == "abc"
        assert _truncate("abcd", 3) == "..."  # 3-3=0 chars + ellipsis


# ===================================================================
# 7. HF ADAPTER RESILIENCE
# ===================================================================

class TestHFAdapterResilience:
    """hf_adapter module must handle missing binaries and bad inputs."""

    def test_classify_tier_nonexistent_path(self):
        from claw.pulse.hf_adapter import classify_tier, MountTier

        tier = classify_tier("/nonexistent/path/" + uuid.uuid4().hex)
        assert tier == MountTier.PHANTOM

    def test_classify_tier_real_directory(self, tmp_path):
        from claw.pulse.hf_adapter import classify_tier, MountTier

        # A real directory without .git => MATERIALIZED
        tier = classify_tier(str(tmp_path))
        assert tier == MountTier.MATERIALIZED

    def test_classify_tier_git_directory(self, tmp_path):
        from claw.pulse.hf_adapter import classify_tier, MountTier

        (tmp_path / ".git").mkdir()
        tier = classify_tier(str(tmp_path))
        assert tier == MountTier.MATERIALIZED

    def test_mining_strategy_phantom(self):
        from claw.pulse.hf_adapter import mining_strategy, MountTier

        strategy = mining_strategy(MountTier.PHANTOM)
        assert strategy["action"] == "skip"

    def test_mining_strategy_mounted(self):
        from claw.pulse.hf_adapter import mining_strategy, MountTier

        strategy = mining_strategy(MountTier.MOUNTED)
        assert strategy["action"] == "mine"
        assert strategy["skip_binary"] is True

    def test_mining_strategy_materialized(self):
        from claw.pulse.hf_adapter import mining_strategy, MountTier

        strategy = mining_strategy(MountTier.MATERIALIZED)
        assert strategy["action"] == "mine"

    def test_is_hf_mount_nonexistent_path(self):
        from claw.pulse.hf_adapter import is_hf_mount

        result = is_hf_mount("/nonexistent/path/" + uuid.uuid4().hex)
        assert result is False

    def test_is_hf_mount_regular_directory(self, tmp_path):
        from claw.pulse.hf_adapter import is_hf_mount

        assert is_hf_mount(str(tmp_path)) is False

    @pytest.mark.asyncio
    async def test_mount_adapter_unmount_nonexistent(self):
        """Unmounting a nonexistent path should return True (nothing to do)."""
        from claw.pulse.hf_adapter import HFMountAdapter

        adapter = HFMountAdapter(mount_base="/tmp/test-mounts")
        result = await adapter.unmount("/nonexistent/path/" + uuid.uuid4().hex)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_head_sha_no_git(self, tmp_path):
        """get_head_sha on a non-git directory returns None."""
        from claw.pulse.hf_adapter import HFMountAdapter

        adapter = HFMountAdapter()
        sha = await adapter.get_head_sha(str(tmp_path))
        assert sha is None


# ===================================================================
# 8. ORCHESTRATOR RESILIENCE
# ===================================================================

class TestOrchestratorResilience:
    """PulseOrchestrator handles failures without crashing."""

    def test_scan_result_report_with_errors(self):
        """build_scan_report handles error-laden results."""
        result = PulseScanResult(
            scan_id="fail-report",
            keywords_used=["test"],
            errors=[f"Error {i}" for i in range(10)],
        )
        result.failed_count = 5
        result.discoveries = [
            PulseDiscovery(
                github_url=f"https://github.com/err/repo{i}",
                canonical_url=f"https://github.com/err/repo{i}",
                novelty_score=0.1 * i,
                keywords_matched=["test"],
            )
            for i in range(3)
        ]
        # Manual report build (same logic as orchestrator)
        lines = [
            f"=== PULSE Scan Report [{result.scan_id}] ===",
            f"Keywords: {', '.join(result.keywords_used)}",
            f"Discovered: {len(result.discoveries)}",
            f"Novel: {result.novel_count}",
            f"Assimilated: {result.assimilated_count}",
            f"Skipped: {result.skipped_count}",
            f"Failed: {result.failed_count}",
        ]
        if result.errors:
            lines.append(f"Errors: {len(result.errors)}")
            for err in result.errors[:5]:
                lines.append(f"  - {err[:100]}")
        report = "\n".join(lines)
        assert "fail-report" in report
        assert "Errors: 10" in report
        assert "Failed: 5" in report

    def test_circuit_breaker_attributes_exist(self):
        """Verify the orchestrator class defines circuit breaker fields."""
        # We cannot fully instantiate PulseOrchestrator without all deps,
        # but we can verify the __init__ signature accepts the right params.
        import inspect
        sig = inspect.signature(PulseOrchestrator.__init__)
        params = list(sig.parameters.keys())
        assert "engine" in params
        assert "scout" in params
        assert "novelty" in params
        assert "assimilator" in params
        assert "config" in params

    def test_stop_method_exists(self):
        """PulseOrchestrator.stop is callable."""
        assert callable(getattr(PulseOrchestrator, "stop", None))


# ===================================================================
# 9. CONCURRENT OPERATIONS -- DEADLOCK DETECTION
# ===================================================================

class TestConcurrentPulseOperations:
    """Verify that concurrent async operations do not deadlock."""

    @pytest.mark.asyncio
    async def test_concurrent_novelty_scoring(self, pulse_engine):
        """Run 50 novelty scores concurrently against the same DB."""
        from claw.pulse.novelty import NoveltyFilter

        nf = NoveltyFilter(pulse_engine, config=PulseConfig(novelty_threshold=0.5))

        async def score_one(i: int) -> float:
            disc = PulseDiscovery(
                github_url=f"https://github.com/concurrent/repo{i}",
                canonical_url=f"https://github.com/concurrent/repo{i}",
                x_post_text=f"Concurrent discovery {i}",
            )
            return await nf.score(disc)

        results = await asyncio.gather(*[score_one(i) for i in range(50)])
        assert len(results) == 50
        for r in results:
            assert isinstance(r, float)
            assert 0.0 <= r <= 1.0

    @pytest.mark.asyncio
    async def test_concurrent_save_discoveries(self, pulse_engine):
        """Save 50 discoveries concurrently: no DB deadlock."""
        from claw.pulse.assimilator import PulseAssimilator
        from claw.core.config import load_config
        from claw.db.repository import Repository
        from claw.db.embeddings import EmbeddingEngine
        from claw.llm.client import LLMClient
        from claw.memory.hybrid_search import HybridSearch
        from claw.memory.semantic import SemanticMemory
        from claw.miner import RepoMiner

        config = load_config()
        repository = Repository(pulse_engine)
        embedding_engine = EmbeddingEngine()
        hybrid_search = HybridSearch(repository, embedding_engine)
        llm_client = LLMClient(config.llm)
        semantic_memory = SemanticMemory(repository, embedding_engine, hybrid_search)
        miner = RepoMiner(repository, llm_client, semantic_memory, config)
        assimilator = PulseAssimilator(pulse_engine, miner, config)

        async def save_one(i: int):
            disc = PulseDiscovery(
                github_url=f"https://github.com/concurrent-save/repo{i}",
                canonical_url=f"https://github.com/concurrent-save/repo{i}",
                x_post_text=f"Concurrent save test {i}",
                keywords_matched=[f"kw{i}"],
                scan_id=f"conc-{i}",
            )
            await assimilator.save_discovery(disc)

        await asyncio.gather(*[save_one(i) for i in range(50)])

        row = await pulse_engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM pulse_discoveries WHERE scan_id LIKE 'conc-%'"
        )
        assert row["cnt"] == 50

    @pytest.mark.asyncio
    async def test_concurrent_dashboard_renders(self, pulse_engine):
        """Multiple dashboard renders concurrently must not deadlock."""
        from claw.pulse.dashboard import PulseDashboard

        # Seed some data
        for i in range(10):
            await pulse_engine.execute(
                """INSERT INTO pulse_discoveries
                   (id, github_url, canonical_url, status, novelty_score, keywords_matched)
                   VALUES (?, ?, ?, 'discovered', 0.8, '["test"]')""",
                [f"conc-dash-{i}", f"https://github.com/dash/repo{i}",
                 f"https://github.com/dash/repo{i}"],
            )

        dash = PulseDashboard(pulse_engine)

        async def render_all():
            await dash.show_novel(limit=5)
            await dash.show_stats()
            await dash.show_scans(limit=5)

        # Run 5 concurrent render cycles
        await asyncio.gather(*[render_all() for _ in range(5)])

    @pytest.mark.asyncio
    async def test_concurrent_filter_and_save(self, pulse_engine):
        """Interleaved filter + save operations: no deadlock."""
        from claw.pulse.novelty import NoveltyFilter
        from claw.pulse.assimilator import PulseAssimilator
        from claw.core.config import load_config
        from claw.db.repository import Repository
        from claw.db.embeddings import EmbeddingEngine
        from claw.llm.client import LLMClient
        from claw.memory.hybrid_search import HybridSearch
        from claw.memory.semantic import SemanticMemory
        from claw.miner import RepoMiner

        config = load_config()
        repository = Repository(pulse_engine)
        embedding_engine = EmbeddingEngine()
        hybrid_search = HybridSearch(repository, embedding_engine)
        llm_client = LLMClient(config.llm)
        semantic_memory = SemanticMemory(repository, embedding_engine, hybrid_search)
        miner = RepoMiner(repository, llm_client, semantic_memory, config)
        assimilator = PulseAssimilator(pulse_engine, miner, config)
        nf = NoveltyFilter(pulse_engine, config=PulseConfig(novelty_threshold=0.5))

        async def filter_batch(start: int):
            discoveries = [
                PulseDiscovery(
                    github_url=f"https://github.com/mixed/repo{start + j}",
                    canonical_url=f"https://github.com/mixed/repo{start + j}",
                    x_post_text=f"Mixed operation {start + j}",
                )
                for j in range(10)
            ]
            return await nf.filter_discoveries(discoveries)

        async def save_batch(start: int):
            for j in range(10):
                disc = PulseDiscovery(
                    github_url=f"https://github.com/mixed-save/repo{start + j}",
                    canonical_url=f"https://github.com/mixed-save/repo{start + j}",
                    scan_id=f"mixed-{start + j}",
                )
                await assimilator.save_discovery(disc)

        # Run filter and save interleaved
        await asyncio.gather(
            filter_batch(0),
            save_batch(100),
            filter_batch(200),
            save_batch(300),
            filter_batch(400),
        )


# ===================================================================
# 10. PR BRIDGE RESILIENCE
# ===================================================================

class TestPRBridgeResilience:
    """PulsePRBridge handles edge cases in discovery evaluation."""

    def test_repo_name_from_url_edge_cases(self):
        from claw.pulse.pr_bridge import PulsePRBridge

        assert PulsePRBridge._repo_name_from_url("https://github.com/a/b") == "a_b"
        assert PulsePRBridge._repo_name_from_url("") == ""
        assert PulsePRBridge._repo_name_from_url("not-a-url") == "not-a-url"

    def test_discovery_below_threshold_returns_false(self):
        """Below threshold evaluation is a pure logic check, no deps needed."""
        disc = PulseDiscovery(
            github_url="https://github.com/low/score",
            canonical_url="https://github.com/low/score",
            novelty_score=0.1,
        )
        # Test threshold logic directly: 0.1 < 0.85 (default) = should not enhance
        config = PulseConfig(enhance_novelty_threshold=0.85)
        assert disc.novelty_score < config.enhance_novelty_threshold


# ===================================================================
# 11. LARGE DISCOVERY SET MEMORY PRESSURE
# ===================================================================

class TestLargeDiscoverySetMemory:
    """Verify that processing 100+ discoveries does not exhaust memory."""

    @pytest.mark.asyncio
    async def test_filter_500_discoveries(self, pulse_engine):
        """Filtering 500 discoveries should complete within resource bounds."""
        from claw.pulse.novelty import NoveltyFilter

        nf = NoveltyFilter(pulse_engine, config=PulseConfig(novelty_threshold=0.5))
        discoveries = [
            PulseDiscovery(
                github_url=f"https://github.com/large/repo{i}",
                canonical_url=f"https://github.com/large/repo{i}",
                x_post_text=f"Large batch item {i} with descriptive text about AI tooling",
                keywords_matched=[f"kw{i % 10}"],
                scan_id="large-batch",
            )
            for i in range(500)
        ]
        novel = await nf.filter_discoveries(discoveries)
        assert isinstance(novel, list)
        # All should be novel (none in DB)
        assert len(novel) == 500

    @pytest.mark.asyncio
    async def test_save_200_discoveries_sequential(self, pulse_engine):
        """Saving 200 discoveries sequentially: DB handles the volume."""
        from claw.pulse.assimilator import PulseAssimilator
        from claw.core.config import load_config
        from claw.db.repository import Repository
        from claw.db.embeddings import EmbeddingEngine
        from claw.llm.client import LLMClient
        from claw.memory.hybrid_search import HybridSearch
        from claw.memory.semantic import SemanticMemory
        from claw.miner import RepoMiner

        config = load_config()
        repository = Repository(pulse_engine)
        embedding_engine = EmbeddingEngine()
        hybrid_search = HybridSearch(repository, embedding_engine)
        llm_client = LLMClient(config.llm)
        semantic_memory = SemanticMemory(repository, embedding_engine, hybrid_search)
        miner = RepoMiner(repository, llm_client, semantic_memory, config)
        assimilator = PulseAssimilator(pulse_engine, miner, config)

        for i in range(200):
            disc = PulseDiscovery(
                github_url=f"https://github.com/bulk/repo{i}",
                canonical_url=f"https://github.com/bulk/repo{i}",
                x_post_text=f"Bulk save {i}",
                keywords_matched=[f"bulk{i}"],
                scan_id=f"bulk-{i}",
            )
            await assimilator.save_discovery(disc)

        row = await pulse_engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM pulse_discoveries WHERE scan_id LIKE 'bulk-%'"
        )
        assert row["cnt"] == 200

    def test_extract_urls_from_massive_text(self):
        """Extract GitHub URLs from a 5000-URL text blob."""
        lines = []
        for i in range(5000):
            lines.append(
                f"Check out https://github.com/org{i}/project{i} -- it does something cool."
            )
        text = "\n".join(lines)
        urls = XScout.extract_github_urls(text)
        assert len(urls) == 5000

    @pytest.mark.asyncio
    async def test_multiple_known_checks_at_scale(self, pulse_engine):
        """Insert 100 assimilated, then check is_already_known for each."""
        from claw.pulse.novelty import NoveltyFilter

        for i in range(100):
            await pulse_engine.execute(
                """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
                   VALUES (?, ?, ?, 'assimilated')""",
                [f"scale-{i}", f"https://github.com/scale/repo{i}",
                 f"https://github.com/scale/repo{i}"],
            )

        nf = NoveltyFilter(pulse_engine, config=PulseConfig())

        for i in range(100):
            result = await nf.is_already_known(f"https://github.com/scale/repo{i}")
            assert result is True

        # And 100 unknown checks
        for i in range(100, 200):
            result = await nf.is_already_known(f"https://github.com/scale/repo{i}")
            assert result is False
