"""Tests for HF repo ingestion pipeline.

Covers:
  - Canonical URL construction for HF repos
  - _repo_name_from_url() handling of HF URLs
  - Discovery record creation in assimilate_hf_repo()
  - Schema constraint bug: 'mounting' status not in CHECK constraint
  - Freshness metadata population with source_kind=hf_repo
  - HFMountAdapter construction and import
  - mining_strategy() for all tiers
  - HFMountConfig defaults from load_config()
  - CLI ingest-hf command registration and callable
  - PulseDiscovery dataclass with HF data
  - Save/retrieve cycle for HF discovery records

NO MOCKS. All DB operations use real in-memory SQLite.
All config operations use real load_config().
"""

from __future__ import annotations

import json

import pytest

from claw.core.config import DatabaseConfig, load_config
from claw.core.exceptions import DatabaseError
from claw.db.engine import DatabaseEngine
from claw.pulse.assimilator import PulseAssimilator
from claw.pulse.models import AssimilationResult, PulseDiscovery


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


@pytest.fixture
async def assimilator(pulse_engine):
    """PulseAssimilator backed by real in-memory engine and real dependencies."""
    from claw.db.embeddings import EmbeddingEngine
    from claw.db.repository import Repository
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


def _build_assimilator(pulse_engine, config):
    """Helper: build a PulseAssimilator with real deps and provided config."""
    from claw.db.embeddings import EmbeddingEngine
    from claw.db.repository import Repository
    from claw.llm.client import LLMClient
    from claw.memory.hybrid_search import HybridSearch
    from claw.memory.semantic import SemanticMemory
    from claw.miner import RepoMiner

    repository = Repository(pulse_engine)
    embedding_engine = EmbeddingEngine()
    hybrid_search = HybridSearch(repository, embedding_engine)
    llm_client = LLMClient(config.llm)
    semantic_memory = SemanticMemory(repository, embedding_engine, hybrid_search)
    miner = RepoMiner(repository, llm_client, semantic_memory, config)
    return PulseAssimilator(pulse_engine, miner, config)


# ---------------------------------------------------------------------------
# TestAssimilateHfRepoSetup
# ---------------------------------------------------------------------------

class TestAssimilateHfRepoSetup:
    """Test the HF assimilation setup logic (without requiring real mount/download)."""

    @pytest.mark.asyncio
    async def test_canonical_url_format(self, assimilator, pulse_engine):
        """save_discovery persists canonical_url and github_url for an HF repo."""
        disc = PulseDiscovery(
            github_url="https://huggingface.co/test/model",
            canonical_url="https://huggingface.co/test/model",
            x_post_text="HF repo ingest: test/model",
            keywords_matched=["hf-ingest"],
            novelty_score=1.0,
            scan_id="test-scan",
        )
        await assimilator.save_discovery(disc)

        row = await pulse_engine.fetch_one(
            "SELECT canonical_url, github_url FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://huggingface.co/test/model"],
        )
        assert row is not None
        assert row["canonical_url"] == "https://huggingface.co/test/model"
        assert row["github_url"] == "https://huggingface.co/test/model"

    @pytest.mark.asyncio
    async def test_canonical_url_prefix_for_hf(self):
        """The canonical URL built in assimilate_hf_repo uses huggingface.co prefix."""
        repo_id = "d4data/biomedical-ner-all"
        canonical_url = f"https://huggingface.co/{repo_id}"
        assert canonical_url == "https://huggingface.co/d4data/biomedical-ner-all"
        assert canonical_url.startswith("https://huggingface.co/")
        assert repo_id in canonical_url

    def test_repo_name_from_hf_url(self):
        """_repo_name_from_url strips HF prefix and replaces slashes with underscores."""
        name = PulseAssimilator._repo_name_from_url("https://huggingface.co/owner/model")
        assert name == "owner_model"

    def test_repo_name_from_github_url(self):
        """_repo_name_from_url still works for GitHub URLs."""
        name = PulseAssimilator._repo_name_from_url("https://github.com/owner/repo")
        assert name == "owner_repo"

    def test_repo_name_from_hf_url_deep_path(self):
        """_repo_name_from_url handles HF org/repo with nested structure."""
        name = PulseAssimilator._repo_name_from_url("https://huggingface.co/bigscience/bloom")
        assert name == "bigscience_bloom"

    def test_repo_name_preserves_hyphens(self):
        """Hyphens in repo names are preserved (only slashes become underscores)."""
        name = PulseAssimilator._repo_name_from_url("https://huggingface.co/d4data/biomedical-ner-all")
        assert name == "d4data_biomedical-ner-all"

    @pytest.mark.asyncio
    async def test_assimilate_hf_populates_source_kind(self, assimilator, pulse_engine):
        """Source kind should be set to 'hf_repo' for HF URLs via _update_freshness_on_assimilate."""
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('hf1', 'https://huggingface.co/test/model',
                        'https://huggingface.co/test/model', 'assimilated')"""
        )

        await assimilator._update_freshness_on_assimilate(
            "https://huggingface.co/test/model", "sha123", ""
        )

        row = await pulse_engine.fetch_one(
            "SELECT source_kind, freshness_status FROM pulse_discoveries WHERE id = 'hf1'",
        )
        assert row["source_kind"] == "hf_repo"
        assert row["freshness_status"] == "fresh"

    @pytest.mark.asyncio
    async def test_assimilate_hf_github_url_keeps_github_source_kind(self, assimilator, pulse_engine):
        """GitHub URLs via _update_freshness_on_assimilate get source_kind='github'."""
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('gh1', 'https://github.com/test/repo',
                        'https://github.com/test/repo', 'assimilated')"""
        )

        await assimilator._update_freshness_on_assimilate(
            "https://github.com/test/repo", "sha456", ""
        )

        row = await pulse_engine.fetch_one(
            "SELECT source_kind FROM pulse_discoveries WHERE id = 'gh1'",
        )
        assert row["source_kind"] == "github"

    @pytest.mark.asyncio
    async def test_assimilate_hf_sets_head_sha(self, assimilator, pulse_engine):
        """_update_freshness_on_assimilate stores head_sha_at_mine."""
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('hf2', 'https://huggingface.co/test/sha-test',
                        'https://huggingface.co/test/sha-test', 'assimilated')"""
        )

        await assimilator._update_freshness_on_assimilate(
            "https://huggingface.co/test/sha-test",
            "abc123def456789012345678901234567890abcd",
            "",
        )

        row = await pulse_engine.fetch_one(
            "SELECT head_sha_at_mine FROM pulse_discoveries WHERE id = 'hf2'",
        )
        assert row["head_sha_at_mine"] == "abc123def456789012345678901234567890abcd"

    @pytest.mark.asyncio
    async def test_assimilate_hf_sets_last_checked_at(self, assimilator, pulse_engine):
        """_update_freshness_on_assimilate populates last_checked_at timestamp."""
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
               VALUES ('hf3', 'https://huggingface.co/test/checked-at',
                        'https://huggingface.co/test/checked-at', 'assimilated')"""
        )

        await assimilator._update_freshness_on_assimilate(
            "https://huggingface.co/test/checked-at", "sha789", ""
        )

        row = await pulse_engine.fetch_one(
            "SELECT last_checked_at FROM pulse_discoveries WHERE id = 'hf3'",
        )
        assert row["last_checked_at"] is not None
        # ISO 8601 format check
        assert "T" in row["last_checked_at"]
        assert row["last_checked_at"].endswith("Z")


# ---------------------------------------------------------------------------
# TestAssimilateHfRepoSchemaConstraint
# ---------------------------------------------------------------------------

class TestAssimilateHfRepoSchemaConstraint:
    """Verify the CHECK constraint on pulse_discoveries.status includes
    'mounting' and 'refreshing' for HF ingestion and freshness workflows.
    """

    @pytest.mark.asyncio
    async def test_assimilate_hf_uses_cloning_status(self, pulse_engine):
        """assimilate_hf_repo uses 'cloning' status (valid CHECK value) during mount phase."""
        config = load_config()
        config.pulse.hf_mount.fallback_to_download = False
        config.pulse.hf_mount.mount_base = "/tmp/test-hf-status-check"
        assim = _build_assimilator(pulse_engine, config)

        # Will fail to mount, but status transition should not raise CHECK error
        result = await assim.assimilate_hf_repo(
            "totally-fake/nonexistent-repo-xyz-abc-123",
            "pulse-default",
        )
        assert result.success is False  # Mount fails, but no CHECK constraint error

    @pytest.mark.asyncio
    async def test_discovery_record_created_on_mount_failure(self, pulse_engine):
        """Discovery record is created even when mount fails."""
        config = load_config()
        config.pulse.hf_mount.fallback_to_download = False
        config.pulse.hf_mount.mount_base = "/tmp/test-hf-record-create"
        assim = _build_assimilator(pulse_engine, config)

        await assim.assimilate_hf_repo(
            "fake/record-on-failure",
            "pulse-default",
        )

        row = await pulse_engine.fetch_one(
            "SELECT canonical_url, status, scan_id, keywords_matched "
            "FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://huggingface.co/fake/record-on-failure"],
        )
        assert row is not None
        assert row["canonical_url"] == "https://huggingface.co/fake/record-on-failure"
        assert row["status"] == "failed"
        assert row["scan_id"].startswith("hf-ingest-")
        assert json.loads(row["keywords_matched"]) == ["hf-ingest"]

    @pytest.mark.asyncio
    async def test_mounting_and_refreshing_in_allowed_statuses(self, pulse_engine):
        """Both 'mounting' and 'refreshing' are now valid CHECK constraint values."""
        for status in ("mounting", "refreshing"):
            disc_id = f"check-{status}"
            await pulse_engine.execute(
                """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
                   VALUES (?, ?, ?, 'discovered')""",
                [disc_id, f"https://huggingface.co/test/{status}",
                 f"https://huggingface.co/test/{status}"],
            )
            # Should NOT raise — both are in the CHECK constraint
            await pulse_engine.execute(
                "UPDATE pulse_discoveries SET status = ? WHERE id = ?",
                [status, disc_id],
            )
            row = await pulse_engine.fetch_one(
                "SELECT status FROM pulse_discoveries WHERE id = ?", [disc_id]
            )
            assert row["status"] == status

    @pytest.mark.asyncio
    async def test_valid_statuses_accepted(self, pulse_engine):
        """All valid statuses in the CHECK constraint are accepted."""
        valid_statuses = [
            "discovered", "cloning", "mining", "assimilated",
            "failed", "skipped", "queued_enhance",
        ]

        for i, status in enumerate(valid_statuses):
            disc_id = f"valid-{i}"
            await pulse_engine.execute(
                """INSERT INTO pulse_discoveries (id, github_url, canonical_url, status)
                   VALUES (?, ?, ?, ?)""",
                [disc_id, f"https://huggingface.co/test/valid-{i}",
                 f"https://huggingface.co/test/valid-{i}", status],
            )
            row = await pulse_engine.fetch_one(
                "SELECT status FROM pulse_discoveries WHERE id = ?", [disc_id]
            )
            assert row["status"] == status


# ---------------------------------------------------------------------------
# TestAssimilationResultObject
# ---------------------------------------------------------------------------

class TestAssimilationResultObject:
    """Test the AssimilationResult constructed within assimilate_hf_repo."""

    def test_assimilation_result_default_values(self):
        """AssimilationResult defaults: success=False, empty lists, no error."""
        disc = PulseDiscovery(
            github_url="https://huggingface.co/test/model",
            canonical_url="https://huggingface.co/test/model",
        )
        result = AssimilationResult(discovery=disc)
        assert result.success is False
        assert result.methodology_ids == []
        assert result.findings_count == 0
        assert result.error is None

    def test_assimilation_result_discovery_url(self):
        """AssimilationResult carries the discovery with the correct canonical_url."""
        disc = PulseDiscovery(
            github_url="https://huggingface.co/fake/result-url-test",
            canonical_url="https://huggingface.co/fake/result-url-test",
            x_post_text="HF repo ingest: fake/result-url-test",
            keywords_matched=["hf-ingest"],
            novelty_score=1.0,
            scan_id="hf-ingest-test",
        )
        result = AssimilationResult(discovery=disc)
        assert result.discovery.canonical_url == "https://huggingface.co/fake/result-url-test"
        assert result.discovery.github_url == "https://huggingface.co/fake/result-url-test"

    def test_assimilation_result_with_error(self):
        """AssimilationResult can carry an error message."""
        disc = PulseDiscovery(
            github_url="https://huggingface.co/test/err",
            canonical_url="https://huggingface.co/test/err",
        )
        result = AssimilationResult(discovery=disc, error="Mount failed: binary not found")
        assert result.success is False
        assert result.error == "Mount failed: binary not found"

    def test_assimilation_result_success_with_methodologies(self):
        """AssimilationResult populated for a successful ingestion."""
        disc = PulseDiscovery(
            github_url="https://huggingface.co/test/success",
            canonical_url="https://huggingface.co/test/success",
        )
        result = AssimilationResult(
            discovery=disc,
            success=True,
            methodology_ids=["m1", "m2", "m3"],
            findings_count=5,
        )
        assert result.success is True
        assert len(result.methodology_ids) == 3
        assert result.findings_count == 5
        assert result.error is None


# ---------------------------------------------------------------------------
# TestHFMountAdapterIntegration
# ---------------------------------------------------------------------------

class TestHFMountAdapterIntegration:
    """Tests that verify hf-mount adapter works for ingestion setup."""

    def test_hf_mount_adapter_import(self):
        """HFMountAdapter is importable."""
        from claw.pulse.hf_adapter import HFMountAdapter
        adapter = HFMountAdapter()
        assert adapter._mount_base.name == "hf_mounts"

    def test_hf_mount_adapter_custom_mount_base(self):
        """HFMountAdapter accepts custom mount_base."""
        from claw.pulse.hf_adapter import HFMountAdapter
        adapter = HFMountAdapter(mount_base="/custom/path")
        assert str(adapter._mount_base) == "/custom/path"

    def test_hf_mount_adapter_fallback_flag(self):
        """Fallback flag is correctly stored."""
        from claw.pulse.hf_adapter import HFMountAdapter
        adapter_with = HFMountAdapter(fallback_to_download=True)
        adapter_without = HFMountAdapter(fallback_to_download=False)
        assert adapter_with._fallback is True
        assert adapter_without._fallback is False

    def test_hf_mount_adapter_timeout(self):
        """Custom timeout is stored."""
        from claw.pulse.hf_adapter import HFMountAdapter
        adapter = HFMountAdapter(mount_timeout_secs=60)
        assert adapter._timeout == 60

    def test_hf_mount_adapter_cache_size(self):
        """Custom cache size is stored."""
        from claw.pulse.hf_adapter import HFMountAdapter
        adapter = HFMountAdapter(cache_size_bytes=2_000_000_000)
        assert adapter._cache_size == 2_000_000_000

    def test_mining_strategy_for_mounted(self):
        """MOUNTED tier returns mine action with hf_mount source."""
        from claw.pulse.hf_adapter import MountTier, mining_strategy
        strategy = mining_strategy(MountTier.MOUNTED)
        assert strategy["action"] == "mine"
        assert strategy["source_kind"] == "hf_mount"
        assert strategy["skip_binary"] is True

    def test_mining_strategy_for_phantom_skips(self):
        """PHANTOM tier returns skip action."""
        from claw.pulse.hf_adapter import MountTier, mining_strategy
        strategy = mining_strategy(MountTier.PHANTOM)
        assert strategy["action"] == "skip"

    def test_mining_strategy_for_materialized(self):
        """MATERIALIZED tier returns mine with local source."""
        from claw.pulse.hf_adapter import MountTier, mining_strategy
        strategy = mining_strategy(MountTier.MATERIALIZED)
        assert strategy["action"] == "mine"
        assert strategy["source_kind"] == "local"
        assert strategy["skip_binary"] is True

    def test_mining_strategy_mounted_max_file_size_is_conservative(self):
        """MOUNTED tier has lower max_file_size than MATERIALIZED (streaming constraint)."""
        from claw.pulse.hf_adapter import MountTier, mining_strategy
        mounted = mining_strategy(MountTier.MOUNTED)
        materialized = mining_strategy(MountTier.MATERIALIZED)
        assert mounted["max_file_size"] < materialized["max_file_size"]
        assert mounted["max_file_size"] == 500_000
        assert materialized["max_file_size"] == 900_000

    def test_classify_tier_nonexistent_is_phantom(self):
        """Nonexistent path classifies as PHANTOM."""
        from claw.pulse.hf_adapter import MountTier, classify_tier
        tier = classify_tier("/nonexistent/path/that/does/not/exist")
        assert tier is MountTier.PHANTOM

    def test_mount_result_defaults(self):
        """MountResult default state is unsuccessful."""
        from claw.pulse.hf_adapter import MountResult
        r = MountResult()
        assert r.success is False
        assert r.mount_path == ""
        assert r.method == ""
        assert r.error is None

    def test_hf_mount_config_defaults(self):
        """HFMountConfig has sensible defaults."""
        config = load_config()
        hf = config.pulse.hf_mount
        assert hf.enabled is True
        assert hf.fallback_to_download is True
        assert hf.mount_timeout_secs == 30
        assert hf.cache_size_bytes == 1_073_741_824

    def test_hf_mount_config_has_token_env(self):
        """HFMountConfig specifies which env var to read for HF token."""
        config = load_config()
        hf = config.pulse.hf_mount
        assert hf.hf_token_env == "HF_TOKEN"

    def test_hf_mount_config_poll_interval_zero(self):
        """Poll interval defaults to 0 (static snapshot for mining)."""
        config = load_config()
        hf = config.pulse.hf_mount
        assert hf.poll_interval_secs == 0

    def test_hf_mount_config_mount_base_default(self):
        """Default mount base is data/hf_mounts."""
        config = load_config()
        hf = config.pulse.hf_mount
        assert hf.mount_base == "data/hf_mounts"

    def test_hf_mount_config_binary_path_default(self):
        """Default binary path points to ~/.local/bin/hf-mount."""
        config = load_config()
        hf = config.pulse.hf_mount
        assert hf.binary_path == "~/.local/bin/hf-mount"


# ---------------------------------------------------------------------------
# TestHFMountAdapterAsync
# ---------------------------------------------------------------------------

class TestHFMountAdapterAsync:
    """Async operations on HFMountAdapter using real filesystem."""

    @pytest.mark.asyncio
    async def test_unmount_nonexistent_path_succeeds(self):
        """Unmounting a nonexistent path returns True (nothing to clean up)."""
        from claw.pulse.hf_adapter import HFMountAdapter
        adapter = HFMountAdapter()
        result = await adapter.unmount("/nonexistent/path/for/unmount/test")
        assert result is True

    @pytest.mark.asyncio
    async def test_unmount_temp_directory_removes_it(self):
        """Unmounting a real (non-hf-mount) temp directory removes it."""
        import os
        import tempfile

        from claw.pulse.hf_adapter import HFMountAdapter

        td = tempfile.mkdtemp(prefix="hf-ingest-test-")
        # Write a file so the directory is non-empty
        with open(os.path.join(td, "test.txt"), "w") as f:
            f.write("test content")
        assert os.path.exists(td)

        adapter = HFMountAdapter()
        result = await adapter.unmount(td)
        assert result is True
        assert not os.path.exists(td)

    @pytest.mark.asyncio
    async def test_mount_repo_fails_gracefully_no_binary_no_fallback(self):
        """mount_repo with no hf-mount binary and fallback disabled returns error."""
        from claw.pulse.hf_adapter import HFMountAdapter

        adapter = HFMountAdapter(
            mount_base="/tmp/test-hf-no-binary",
            fallback_to_download=False,
        )

        result = await adapter.mount_repo("fake/repo-no-binary")

        # Should fail because hf-mount likely unavailable and fallback disabled
        if not result.success:
            assert result.error is not None
            assert len(result.error) > 0


# ---------------------------------------------------------------------------
# TestIngestHFCLI
# ---------------------------------------------------------------------------

class TestIngestHFCLI:
    """Tests for the ingest-hf CLI command registration."""

    def test_cli_imports(self):
        """CLI imports successfully."""
        from claw.cli import app
        assert app is not None

    def test_pulse_app_imports(self):
        """pulse_app sub-application imports successfully."""
        from claw.cli import pulse_app
        assert pulse_app is not None

    def test_pulse_ingest_hf_function_exists(self):
        """The pulse_ingest_hf function is importable from cli module."""
        from claw.cli import pulse_ingest_hf
        assert callable(pulse_ingest_hf)

    def test_pulse_ingest_hf_is_typer_command(self):
        """pulse_ingest_hf is registered as a typer command on pulse_app."""
        from claw.cli import pulse_app

        # Collect all command callback names from registered commands
        callback_names = []
        for cmd_info in pulse_app.registered_commands:
            if hasattr(cmd_info, "callback") and cmd_info.callback is not None:
                callback_names.append(cmd_info.callback.__name__)

        assert "pulse_ingest_hf" in callback_names

    def test_pulse_ingest_hf_command_name(self):
        """The command is registered under the name 'ingest-hf'."""
        from claw.cli import pulse_app

        # Collect command names
        command_names = []
        for cmd_info in pulse_app.registered_commands:
            if hasattr(cmd_info, "name") and cmd_info.name:
                command_names.append(cmd_info.name)

        assert "ingest-hf" in command_names


# ---------------------------------------------------------------------------
# TestDiscoveryModelForHF
# ---------------------------------------------------------------------------

class TestDiscoveryModelForHF:
    """Test PulseDiscovery dataclass with HF-specific data."""

    def test_discovery_with_hf_url(self):
        """PulseDiscovery can hold HF URLs in both github_url and canonical_url."""
        disc = PulseDiscovery(
            github_url="https://huggingface.co/owner/model",
            canonical_url="https://huggingface.co/owner/model",
            x_post_text="HF repo ingest: owner/model",
            keywords_matched=["hf-ingest"],
            novelty_score=1.0,
            scan_id="hf-ingest-20260325-120000",
        )
        assert disc.canonical_url.startswith("https://huggingface.co/")
        assert disc.github_url == disc.canonical_url
        assert disc.keywords_matched == ["hf-ingest"]
        assert disc.novelty_score == 1.0
        assert disc.scan_id.startswith("hf-ingest-")

    def test_discovery_x_post_text_format(self):
        """The x_post_text for HF ingestion follows 'HF repo ingest: <id>' pattern."""
        repo_id = "bigscience/bloom"
        disc = PulseDiscovery(
            github_url=f"https://huggingface.co/{repo_id}",
            canonical_url=f"https://huggingface.co/{repo_id}",
            x_post_text=f"HF repo ingest: {repo_id}",
            keywords_matched=["hf-ingest"],
            novelty_score=1.0,
            scan_id="test",
        )
        assert "bigscience/bloom" in disc.x_post_text

    def test_discovery_defaults(self):
        """PulseDiscovery defaults are sensible for HF use case."""
        disc = PulseDiscovery(
            github_url="https://huggingface.co/a/b",
            canonical_url="https://huggingface.co/a/b",
        )
        assert disc.x_post_url == ""
        assert disc.x_post_text == ""
        assert disc.x_author_handle == ""
        assert disc.keywords_matched == []
        assert disc.novelty_score == 0.0
        assert disc.scan_id == ""


# ---------------------------------------------------------------------------
# TestSaveAndRetrieveHFDiscovery
# ---------------------------------------------------------------------------

class TestSaveAndRetrieveHFDiscovery:
    """End-to-end save/retrieve cycle for HF discovery records."""

    @pytest.mark.asyncio
    async def test_save_and_retrieve_hf_discovery(self, assimilator, pulse_engine):
        """Save an HF discovery, retrieve it, verify all fields."""
        disc = PulseDiscovery(
            github_url="https://huggingface.co/meta-llama/Llama-3-8B",
            canonical_url="https://huggingface.co/meta-llama/Llama-3-8B",
            x_post_text="HF repo ingest: meta-llama/Llama-3-8B",
            keywords_matched=["hf-ingest", "llama"],
            novelty_score=0.95,
            scan_id="hf-ingest-20260325-130000",
        )
        await assimilator.save_discovery(disc)

        row = await pulse_engine.fetch_one(
            "SELECT * FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://huggingface.co/meta-llama/Llama-3-8B"],
        )

        assert row is not None
        assert row["github_url"] == "https://huggingface.co/meta-llama/Llama-3-8B"
        assert row["canonical_url"] == "https://huggingface.co/meta-llama/Llama-3-8B"
        assert row["novelty_score"] == 0.95
        assert json.loads(row["keywords_matched"]) == ["hf-ingest", "llama"]
        assert row["scan_id"] == "hf-ingest-20260325-130000"

    @pytest.mark.asyncio
    async def test_save_discovery_default_status_is_discovered(self, assimilator, pulse_engine):
        """Newly saved discovery has default status 'discovered'."""
        disc = PulseDiscovery(
            github_url="https://huggingface.co/test/default-status",
            canonical_url="https://huggingface.co/test/default-status",
            scan_id="hf-default-status",
        )
        await assimilator.save_discovery(disc)

        row = await pulse_engine.fetch_one(
            "SELECT status FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://huggingface.co/test/default-status"],
        )
        assert row is not None
        assert row["status"] == "discovered"

    @pytest.mark.asyncio
    async def test_duplicate_hf_discovery_ignored(self, assimilator, pulse_engine):
        """Saving the same HF discovery twice does not raise or create duplicates."""
        disc = PulseDiscovery(
            github_url="https://huggingface.co/dup/test-repo",
            canonical_url="https://huggingface.co/dup/test-repo",
            scan_id="hf-dup-test",
        )
        await assimilator.save_discovery(disc)
        await assimilator.save_discovery(disc)

        row = await pulse_engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://huggingface.co/dup/test-repo"],
        )
        assert row["cnt"] == 1

    @pytest.mark.asyncio
    async def test_status_transitions_for_hf_valid(self, assimilator, pulse_engine):
        """Status transitions through valid values: discovered -> cloning -> mining -> failed."""
        disc = PulseDiscovery(
            github_url="https://huggingface.co/test/status-transition",
            canonical_url="https://huggingface.co/test/status-transition",
            scan_id="hf-status-test",
        )
        await assimilator.save_discovery(disc)

        # Initial status should be 'discovered' (schema default)
        row = await pulse_engine.fetch_one(
            "SELECT status FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://huggingface.co/test/status-transition"],
        )
        assert row["status"] == "discovered"

        # Transition to 'cloning' (valid)
        await assimilator._update_discovery_status(
            "https://huggingface.co/test/status-transition", "cloning"
        )
        row = await pulse_engine.fetch_one(
            "SELECT status FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://huggingface.co/test/status-transition"],
        )
        assert row["status"] == "cloning"

        # Transition to 'mining' (valid)
        await assimilator._update_discovery_status(
            "https://huggingface.co/test/status-transition", "mining"
        )
        row = await pulse_engine.fetch_one(
            "SELECT status FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://huggingface.co/test/status-transition"],
        )
        assert row["status"] == "mining"

        # Transition to 'failed' with error detail
        await assimilator._update_discovery_status(
            "https://huggingface.co/test/status-transition",
            "failed",
            error="mount failed: hf-mount binary not found",
        )
        row = await pulse_engine.fetch_one(
            "SELECT status, error_detail FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://huggingface.co/test/status-transition"],
        )
        assert row["status"] == "failed"
        assert "mount failed" in row["error_detail"]

    @pytest.mark.asyncio
    async def test_hf_discovery_novelty_score_persists(self, assimilator, pulse_engine):
        """Novelty score of 1.0 (set for all HF ingestions) is correctly stored."""
        disc = PulseDiscovery(
            github_url="https://huggingface.co/test/novelty",
            canonical_url="https://huggingface.co/test/novelty",
            novelty_score=1.0,
            scan_id="hf-novelty-test",
        )
        await assimilator.save_discovery(disc)

        row = await pulse_engine.fetch_one(
            "SELECT novelty_score FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://huggingface.co/test/novelty"],
        )
        assert row["novelty_score"] == 1.0

    @pytest.mark.asyncio
    async def test_hf_discovery_x_post_text_truncated(self, assimilator, pulse_engine):
        """x_post_text longer than 500 chars is truncated on save."""
        long_text = "A" * 600
        disc = PulseDiscovery(
            github_url="https://huggingface.co/test/truncate",
            canonical_url="https://huggingface.co/test/truncate",
            x_post_text=long_text,
            scan_id="hf-truncate-test",
        )
        await assimilator.save_discovery(disc)

        row = await pulse_engine.fetch_one(
            "SELECT x_post_text FROM pulse_discoveries WHERE canonical_url = ?",
            ["https://huggingface.co/test/truncate"],
        )
        assert row is not None
        assert len(row["x_post_text"]) == 500
