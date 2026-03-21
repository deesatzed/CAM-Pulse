"""Tests for CAM-PULSE assimilator."""

import json

import pytest
from claw.core.config import DatabaseConfig, PulseConfig
from claw.db.engine import DatabaseEngine
from claw.pulse.assimilator import PulseAssimilator
from claw.pulse.models import PulseDiscovery


@pytest.fixture
async def pulse_engine():
    config = DatabaseConfig(db_path=":memory:")
    engine = DatabaseEngine(config)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    yield engine
    await engine.close()


@pytest.fixture
async def assimilator(pulse_engine):
    """Build a PulseAssimilator with real engine.

    The miner is constructed via the existing claw_context pattern to get
    all dependencies right. For save/status tests we only use the engine.
    """
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
    return PulseAssimilator(pulse_engine, miner, config)


class TestPulseAssimilator:
    def test_repo_name_from_url(self):
        assert PulseAssimilator._repo_name_from_url("https://github.com/owner/repo") == "owner_repo"
        assert PulseAssimilator._repo_name_from_url("https://github.com/org/my-project") == "org_my-project"

    @pytest.mark.asyncio
    async def test_save_discovery(self, assimilator, pulse_engine):
        disc = PulseDiscovery(
            github_url="https://github.com/test/repo",
            canonical_url="https://github.com/test/repo",
            x_post_text="Amazing new AI tool",
            keywords_matched=["AI tool"],
            novelty_score=0.85,
            scan_id="scan123",
        )
        await assimilator.save_discovery(disc)

        row = await pulse_engine.fetch_one(
            "SELECT * FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://github.com/test/repo"],
        )
        assert row is not None
        assert row["github_url"] == "https://github.com/test/repo"
        assert row["novelty_score"] == 0.85
        assert json.loads(row["keywords_matched"]) == ["AI tool"]

    @pytest.mark.asyncio
    async def test_save_discovery_ignores_duplicate(self, assimilator, pulse_engine):
        disc = PulseDiscovery(
            github_url="https://github.com/dup/repo",
            canonical_url="https://github.com/dup/repo",
            scan_id="s1",
        )
        await assimilator.save_discovery(disc)
        await assimilator.save_discovery(disc)  # Should not raise

        row = await pulse_engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://github.com/dup/repo"],
        )
        assert row["cnt"] == 1

    @pytest.mark.asyncio
    async def test_update_discovery_status(self, assimilator, pulse_engine):
        disc = PulseDiscovery(
            github_url="https://github.com/test/status",
            canonical_url="https://github.com/test/status",
            scan_id="s1",
        )
        await assimilator.save_discovery(disc)

        # Update status
        await assimilator._update_discovery_status("https://github.com/test/status", "mining")
        row = await pulse_engine.fetch_one(
            "SELECT status FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://github.com/test/status"],
        )
        assert row["status"] == "mining"

        # Update with error
        await assimilator._update_discovery_status(
            "https://github.com/test/status", "failed", error="clone error"
        )
        row = await pulse_engine.fetch_one(
            "SELECT status, error_detail FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://github.com/test/status"],
        )
        assert row["status"] == "failed"
        assert row["error_detail"] == "clone error"

    @pytest.mark.asyncio
    async def test_update_discovery_assimilated(self, assimilator, pulse_engine):
        disc = PulseDiscovery(
            github_url="https://github.com/test/assim",
            canonical_url="https://github.com/test/assim",
            scan_id="s1",
        )
        await assimilator.save_discovery(disc)

        await assimilator._update_discovery_assimilated(
            "https://github.com/test/assim",
            methodology_ids=["m1", "m2"],
            mine_result_summary={"findings": 3, "tokens_used": 500},
        )
        row = await pulse_engine.fetch_one(
            "SELECT status, methodology_ids, mine_result FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://github.com/test/assim"],
        )
        assert row["status"] == "assimilated"
        assert json.loads(row["methodology_ids"]) == ["m1", "m2"]
        assert json.loads(row["mine_result"])["findings"] == 3
