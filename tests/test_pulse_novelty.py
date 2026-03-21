"""Tests for CAM-PULSE novelty filter."""

import pytest
from claw.core.config import DatabaseConfig, PulseConfig
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
        # Insert a known URL
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('d1', 'https://github.com/known/repo', 'https://github.com/known/repo', 'discovered')"""
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
               VALUES ('d2', 'https://github.com/x/y', 'https://github.com/x/y', 'discovered')"""
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
        # Insert one as known
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('dk', 'https://github.com/new/repo0', 'https://github.com/new/repo0', 'discovered')"""
        )
        novel = await nf.filter_discoveries(discoveries)
        # repo0 is known (score 0.0), repo1 and repo2 should pass
        assert len(novel) == 2
        # Verify scores were set
        for d in novel:
            assert d.novelty_score >= 0.5

    @pytest.mark.asyncio
    async def test_semantic_novelty_without_engine(self, pulse_engine):
        """Without embedding engine, semantic score defaults to 1.0."""
        nf = NoveltyFilter(pulse_engine, embedding_engine=None, config=PulseConfig())
        score = await nf._semantic_novelty("some text")
        assert score == 1.0
