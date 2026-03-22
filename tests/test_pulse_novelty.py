"""Tests for CAM-PULSE novelty filter."""

import pytest
from claw.core.config import DatabaseConfig, PulseConfig, PulseProfileConfig
from claw.db.engine import DatabaseEngine
from claw.pulse.models import PulseDiscovery
from claw.pulse.novelty import NoveltyFilter


@pytest.fixture
async def pulse_engine():
    """In-memory engine with pulse tables."""
    config = DatabaseConfig(db_path=":memory:")
    engine = DatabaseEngine(config)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    yield engine
    await engine.close()


class TestNoveltyFilter:
    @pytest.mark.asyncio
    async def test_unknown_url_is_novel(self, pulse_engine):
        nf = NoveltyFilter(pulse_engine, config=PulseConfig())
        disc = PulseDiscovery(
            github_url="https://github.com/new/repo",
            canonical_url="https://github.com/new/repo",
        )
        score = await nf.score(disc)
        assert score >= 0.5  # URL is new = at least 0.5

    @pytest.mark.asyncio
    async def test_known_url_scores_zero(self, pulse_engine):
        # Insert a known URL (assimilated = truly processed, should block)
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('d1', 'https://github.com/known/repo', 'https://github.com/known/repo', 'assimilated')"""
        )
        nf = NoveltyFilter(pulse_engine, config=PulseConfig())
        disc = PulseDiscovery(
            github_url="https://github.com/known/repo",
            canonical_url="https://github.com/known/repo",
        )
        score = await nf.score(disc)
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_known_in_fleet_scores_zero(self, pulse_engine):
        # Insert into fleet_repos
        await pulse_engine.execute(
            """INSERT INTO fleet_repos (id, repo_path, repo_name, status)
               VALUES ('r1', 'https://github.com/fleet/repo', 'fleet_repo', 'pending')"""
        )
        nf = NoveltyFilter(pulse_engine, config=PulseConfig())
        disc = PulseDiscovery(
            github_url="https://github.com/fleet/repo",
            canonical_url="https://github.com/fleet/repo",
        )
        score = await nf.score(disc)
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_is_already_known_false(self, pulse_engine):
        nf = NoveltyFilter(pulse_engine, config=PulseConfig())
        result = await nf.is_already_known("https://github.com/nobody/nothing")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_already_known_true(self, pulse_engine):
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('d2', 'https://github.com/x/y', 'https://github.com/x/y', 'assimilated')"""
        )
        nf = NoveltyFilter(pulse_engine, config=PulseConfig())
        result = await nf.is_already_known("https://github.com/x/y")
        assert result is True

    @pytest.mark.asyncio
    async def test_filter_discoveries_threshold(self, pulse_engine):
        nf = NoveltyFilter(pulse_engine, config=PulseConfig(novelty_threshold=0.5))
        discoveries = [
            PulseDiscovery(
                github_url=f"https://github.com/new/repo{i}",
                canonical_url=f"https://github.com/new/repo{i}",
            )
            for i in range(3)
        ]
        # Insert one as assimilated (known = won't retry)
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('dk', 'https://github.com/new/repo0', 'https://github.com/new/repo0', 'assimilated')"""
        )
        novel = await nf.filter_discoveries(discoveries)
        # repo0 is known (score 0.0), repo1 and repo2 should pass
        assert len(novel) == 2
        # Verify scores were set
        for d in novel:
            assert d.novelty_score >= 0.5

    @pytest.mark.asyncio
    async def test_failed_discovery_is_retryable(self, pulse_engine):
        """Failed discoveries should NOT block re-assimilation."""
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('df', 'https://github.com/fail/repo', 'https://github.com/fail/repo', 'failed')"""
        )
        nf = NoveltyFilter(pulse_engine, config=PulseConfig())
        result = await nf.is_already_known("https://github.com/fail/repo")
        assert result is False  # failed = retryable, not "known"

    @pytest.mark.asyncio
    async def test_discovered_status_is_retryable(self, pulse_engine):
        """Discovered-but-not-assimilated repos should be retryable."""
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('dd', 'https://github.com/disc/repo', 'https://github.com/disc/repo', 'discovered')"""
        )
        nf = NoveltyFilter(pulse_engine, config=PulseConfig())
        result = await nf.is_already_known("https://github.com/disc/repo")
        assert result is False  # discovered = not yet processed, retryable

    @pytest.mark.asyncio
    async def test_semantic_novelty_without_engine(self, pulse_engine):
        """Without embedding engine, semantic score defaults to 1.0."""
        nf = NoveltyFilter(pulse_engine, embedding_engine=None, config=PulseConfig())
        score = await nf._semantic_novelty("some text")
        assert score == 1.0


class TestDomainBias:
    @pytest.mark.asyncio
    async def test_no_bias_when_no_profile(self, pulse_engine):
        nf = NoveltyFilter(pulse_engine, config=PulseConfig())
        disc = PulseDiscovery(
            github_url="https://github.com/new/repo",
            canonical_url="https://github.com/new/repo",
            x_post_text="A memory management tool for agents",
        )
        score = await nf.score(disc)
        # Without profile bias, score should be base: 0.5 + 0.5*1.0 = 1.0
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_bias_boosts_matching_domain(self, pulse_engine):
        config = PulseConfig(
            profile=PulseProfileConfig(
                name="agent-memory",
                novelty_bias={"memory": 0.15},
            ),
        )
        nf = NoveltyFilter(pulse_engine, config=config)
        disc = PulseDiscovery(
            github_url="https://github.com/new/memrepo",
            canonical_url="https://github.com/new/memrepo",
            x_post_text="A memory management tool for agents",
        )
        score = await nf.score(disc)
        # Base 1.0 + 0.15 bias = 1.0 (capped)
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_bias_does_not_exceed_one(self, pulse_engine):
        config = PulseConfig(
            profile=PulseProfileConfig(
                name="test",
                novelty_bias={"memory": 0.50},
            ),
        )
        nf = NoveltyFilter(pulse_engine, config=config)
        disc = PulseDiscovery(
            github_url="https://github.com/new/memrepo2",
            canonical_url="https://github.com/new/memrepo2",
            x_post_text="memory management system",
        )
        score = await nf.score(disc)
        assert score <= 1.0

    @pytest.mark.asyncio
    async def test_no_bias_when_domain_not_in_text(self, pulse_engine):
        config = PulseConfig(
            profile=PulseProfileConfig(
                name="agent-memory",
                novelty_bias={"memory": 0.15},
            ),
        )
        nf = NoveltyFilter(pulse_engine, config=config)
        disc = PulseDiscovery(
            github_url="https://github.com/new/webrepo",
            canonical_url="https://github.com/new/webrepo",
            x_post_text="A web framework for building APIs",
        )
        score = await nf.score(disc)
        # No match for "memory" in text, so no bias applied
        assert score == 1.0  # base score without bias

    @pytest.mark.asyncio
    async def test_highest_bias_wins(self, pulse_engine):
        """When multiple domains match, highest bias is used (not cumulative)."""
        config = PulseConfig(
            profile=PulseProfileConfig(
                name="multi",
                novelty_bias={"memory": 0.05, "rag": 0.20},
            ),
        )
        nf = NoveltyFilter(pulse_engine, config=config)
        disc = PulseDiscovery(
            github_url="https://github.com/new/ragmem",
            canonical_url="https://github.com/new/ragmem",
            x_post_text="A memory-augmented RAG system",
            keywords_matched=["memory rag"],
        )
        # _apply_domain_bias should use max(0.05, 0.20) = 0.20
        bias = nf._apply_domain_bias(0.75, disc)
        assert bias == pytest.approx(0.95)

    def test_apply_domain_bias_no_config(self, pulse_engine):
        """Without config, no bias applied."""
        import asyncio
        nf = NoveltyFilter(pulse_engine, config=None)
        disc = PulseDiscovery(
            github_url="https://github.com/a/b",
            canonical_url="https://github.com/a/b",
            x_post_text="memory tool",
        )
        result = nf._apply_domain_bias(0.8, disc)
        assert result == 0.8
