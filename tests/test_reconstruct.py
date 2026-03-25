"""Tests for the self-enhancement pipeline (reconstruct.py).

Covers:
  - TriggerAssessment model and summary formatting
  - EnhancementResult model and summary formatting
  - State persistence (_load_state, _save_state)
  - ReconstructionPipeline.assess_trigger() logic
  - ReconstructionPipeline.clone() mechanics
  - ReconstructionPipeline.detect_protected_changes()
  - ReconstructionPipeline.swap() and rollback()
  - ReconstructionPipeline.cleanup_old_backups()
  - SelfEnhanceConfig defaults and overrides
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claw.core.config import ClawConfig, SelfEnhanceConfig
from claw.reconstruct import (
    EnhancementResult,
    ProtectedFileChange,
    ReconstructionPipeline,
    TriggerAssessment,
    _load_state,
    _save_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_live_dir(tmp_path: Path) -> Path:
    """Create a minimal live directory structure."""
    live = tmp_path / "live"
    live.mkdir()
    (live / "src" / "claw").mkdir(parents=True)
    (live / "src" / "claw" / "__init__.py").write_text("# init\n")
    (live / "src" / "claw" / "core").mkdir(parents=True)
    (live / "src" / "claw" / "core" / "__init__.py").write_text("# core init\n")
    (live / "tests").mkdir()
    (live / "tests" / "test_sample.py").write_text("def test_ok(): pass\n")
    (live / "pyproject.toml").write_text("[project]\nname = 'claw'\n")
    (live / "claw.toml").write_text("[database]\ndb_path = 'data/claw.db'\n")
    (live / "data").mkdir()
    (live / ".env").write_text("OPENROUTER_API_KEY=test\n")
    return live


@pytest.fixture
def config() -> ClawConfig:
    return ClawConfig(
        self_enhance=SelfEnhanceConfig(
            enabled=True,
            workspace_parent="",
            max_backup_count=2,
            protected_files=["src/claw/core/__init__.py"],
            min_new_methodologies=5,
            min_avg_novelty_score=0.7,
            cooldown_hours=24,
        )
    )


@pytest.fixture
def pipeline(config: ClawConfig, tmp_live_dir: Path) -> ReconstructionPipeline:
    return ReconstructionPipeline(config, db_engine=None, live_dir=tmp_live_dir)


# ---------------------------------------------------------------------------
# TriggerAssessment model
# ---------------------------------------------------------------------------

class TestTriggerAssessment:
    def test_defaults(self):
        a = TriggerAssessment(should_trigger=False)
        assert not a.should_trigger
        assert a.new_methodologies_count == 0
        assert a.avg_novelty_score == 0.0

    def test_summary_no_trigger(self):
        a = TriggerAssessment(
            should_trigger=False,
            reasons=["No conditions met"],
        )
        s = a.summary()
        assert "NO TRIGGER" in s

    def test_summary_trigger(self):
        a = TriggerAssessment(
            should_trigger=True,
            reasons=["Methodology threshold met"],
            new_methodologies_count=15,
            avg_novelty_score=0.82,
        )
        s = a.summary()
        assert "TRIGGER" in s
        assert "15" in s

    def test_cooldown_shown(self):
        a = TriggerAssessment(
            should_trigger=False,
            cooldown_remaining_hours=12.5,
        )
        s = a.summary()
        assert "12.5" in s


# ---------------------------------------------------------------------------
# EnhancementResult model
# ---------------------------------------------------------------------------

class TestEnhancementResult:
    def test_defaults(self):
        r = EnhancementResult(success=False, phase_reached="init")
        assert not r.success
        assert r.tasks_executed == 0

    def test_summary_success(self):
        r = EnhancementResult(
            success=True,
            phase_reached="complete",
            tasks_executed=5,
            tasks_succeeded=4,
            duration_seconds=120.0,
            swap_completed=True,
        )
        s = r.summary()
        assert "SUCCESS" in s
        assert "4/5" in s
        assert "COMPLETED" in s

    def test_summary_failure_with_error(self):
        r = EnhancementResult(
            success=False,
            phase_reached="validate",
            error="Validation failed at gate: Import Smoke Test",
        )
        s = r.summary()
        assert "FAILED" in s
        assert "Import Smoke Test" in s

    def test_protected_files_in_summary(self):
        r = EnhancementResult(
            success=False,
            phase_reached="protected_review",
            protected_file_changes=[
                ProtectedFileChange("src/claw/verifier.py", 10, 3),
            ],
        )
        s = r.summary()
        assert "Protected file changes: 1" in s

    def test_rollback_in_summary(self):
        r = EnhancementResult(
            success=False,
            phase_reached="post_swap",
            rollback_performed=True,
        )
        s = r.summary()
        assert "PERFORMED" in s


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

class TestStatePersistence:
    def test_save_and_load(self, tmp_path: Path):
        state = {"last_enhance_completed_at": "2026-03-25T12:00:00", "methodology_count": 100}
        _save_state(tmp_path, state)
        loaded = _load_state(tmp_path)
        assert loaded["last_enhance_completed_at"] == "2026-03-25T12:00:00"
        assert loaded["methodology_count"] == 100

    def test_load_missing_file(self, tmp_path: Path):
        loaded = _load_state(tmp_path)
        assert loaded == {}

    def test_load_corrupt_file(self, tmp_path: Path):
        state_path = tmp_path / "data" / "self_enhance_state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text("not json{{{")
        loaded = _load_state(tmp_path)
        assert loaded == {}


# ---------------------------------------------------------------------------
# Pipeline: assess_trigger
# ---------------------------------------------------------------------------

class TestAssessTrigger:
    @pytest.mark.asyncio
    async def test_disabled_config(self, tmp_live_dir: Path):
        cfg = ClawConfig(self_enhance=SelfEnhanceConfig(enabled=False))
        p = ReconstructionPipeline(cfg, live_dir=tmp_live_dir)
        a = await p.assess_trigger()
        assert not a.should_trigger
        assert "enabled is false" in a.reasons[0]

    @pytest.mark.asyncio
    async def test_no_db_no_trigger(self, pipeline: ReconstructionPipeline):
        """Without a DB engine, can't query methodology count."""
        a = await pipeline.assess_trigger()
        assert not a.should_trigger

    @pytest.mark.asyncio
    async def test_cooldown_blocks_trigger(self, pipeline: ReconstructionPipeline):
        """If last run was recent, cooldown blocks trigger."""
        from datetime import UTC, datetime
        pipeline._state["last_enhance_completed_at"] = datetime.now(UTC).isoformat()
        a = await pipeline.assess_trigger()
        assert not a.should_trigger
        assert a.cooldown_remaining_hours > 0

    @pytest.mark.asyncio
    async def test_methodology_threshold_triggers(self, pipeline: ReconstructionPipeline):
        """With enough new methodologies, trigger fires."""
        pipeline._state["methodology_count_at_last_enhance"] = 10

        mock_engine = AsyncMock()
        mock_engine.fetch_all = AsyncMock(return_value=[{"avg_nov": 0.65}])
        pipeline.db_engine = mock_engine

        mock_repo_cls = MagicMock()
        mock_repo_instance = AsyncMock()
        mock_repo_instance.count_methodologies = AsyncMock(return_value=20)
        mock_repo_cls.return_value = mock_repo_instance

        with patch.dict("sys.modules", {}), \
             patch("claw.reconstruct.Repository", mock_repo_cls, create=True):
            # Force re-import path by patching at usage site
            import claw.reconstruct as mod
            original_assess = mod.ReconstructionPipeline.assess_trigger

            async def patched_assess(self_inner):
                # Manually set the repo mock
                self_inner._mock_repo = mock_repo_instance
                return await original_assess(self_inner)

            # Simpler approach: just test the trigger logic directly
            pass

        # Direct approach: set methodology count via state + engine queries
        # The assess_trigger method does: repo = Repository(self.db_engine)
        # We can't easily mock that import. Instead, test the logic with a
        # complete mock that replaces the entire DB layer.
        pipeline.db_engine = mock_engine

        # Patch at the point of use inside the method
        with patch("claw.db.repository.Repository") as MockRepo:
            MockRepo.return_value = mock_repo_instance
            a = await pipeline.assess_trigger()

        assert a.should_trigger
        assert a.new_methodologies_count == 10

    @pytest.mark.asyncio
    async def test_novelty_threshold_triggers(self, pipeline: ReconstructionPipeline):
        """High novelty score triggers even with few methodologies."""
        pipeline._state["methodology_count_at_last_enhance"] = 97

        mock_engine = AsyncMock()
        mock_engine.fetch_all = AsyncMock(return_value=[{"avg_nov": 0.85}])
        pipeline.db_engine = mock_engine

        mock_repo_instance = AsyncMock()
        mock_repo_instance.count_methodologies = AsyncMock(return_value=100)

        with patch("claw.db.repository.Repository") as MockRepo:
            MockRepo.return_value = mock_repo_instance
            a = await pipeline.assess_trigger()

        assert a.should_trigger
        assert "Novelty threshold met" in a.reasons[0]


# ---------------------------------------------------------------------------
# Pipeline: clone
# ---------------------------------------------------------------------------

class TestClone:
    def test_clone_creates_copy(self, pipeline: ReconstructionPipeline, tmp_live_dir: Path):
        copy_dir = pipeline.clone()
        assert copy_dir.exists()
        assert (copy_dir / "src" / "claw" / "__init__.py").exists()
        assert (copy_dir / "tests" / "test_sample.py").exists()
        assert (copy_dir / "pyproject.toml").exists()
        assert (copy_dir / ".env").exists()
        # Cleanup
        shutil.rmtree(copy_dir)

    def test_clone_excludes_data_dir(self, pipeline: ReconstructionPipeline, tmp_live_dir: Path):
        (tmp_live_dir / "data" / "claw.db").write_text("fake db")
        copy_dir = pipeline.clone()
        assert not (copy_dir / "data").exists()
        shutil.rmtree(copy_dir)

    def test_clone_excludes_pycache(self, pipeline: ReconstructionPipeline, tmp_live_dir: Path):
        (tmp_live_dir / "src" / "claw" / "__pycache__").mkdir()
        (tmp_live_dir / "src" / "claw" / "__pycache__" / "mod.pyc").write_bytes(b"pyc")
        copy_dir = pipeline.clone()
        assert not (copy_dir / "src" / "claw" / "__pycache__").exists()
        shutil.rmtree(copy_dir)


# ---------------------------------------------------------------------------
# Pipeline: detect_protected_changes
# ---------------------------------------------------------------------------

class TestDetectProtectedChanges:
    def test_no_changes(self, pipeline: ReconstructionPipeline, tmp_live_dir: Path):
        copy_dir = pipeline.clone()
        changes = pipeline.detect_protected_changes(copy_dir)
        assert len(changes) == 0
        shutil.rmtree(copy_dir)

    def test_detects_modification(self, pipeline: ReconstructionPipeline, tmp_live_dir: Path):
        copy_dir = pipeline.clone()
        # Modify a protected file in the copy
        protected = copy_dir / "src" / "claw" / "core" / "__init__.py"
        protected.write_text("# core init\n# modified\n")
        changes = pipeline.detect_protected_changes(copy_dir)
        assert len(changes) == 1
        assert changes[0].file_path == "src/claw/core/__init__.py"
        assert changes[0].additions > 0
        shutil.rmtree(copy_dir)


# ---------------------------------------------------------------------------
# Pipeline: swap and rollback
# ---------------------------------------------------------------------------

class TestSwapAndRollback:
    def test_swap_replaces_src(self, pipeline: ReconstructionPipeline, tmp_live_dir: Path):
        copy_dir = pipeline.clone()
        # Add a new file in the copy
        (copy_dir / "src" / "claw" / "new_module.py").write_text("# new\n")
        pipeline.swap(copy_dir)
        assert (tmp_live_dir / "src" / "claw" / "new_module.py").exists()
        shutil.rmtree(copy_dir)

    def test_swap_replaces_tests(self, pipeline: ReconstructionPipeline, tmp_live_dir: Path):
        copy_dir = pipeline.clone()
        (copy_dir / "tests" / "test_new.py").write_text("def test_new(): pass\n")
        pipeline.swap(copy_dir)
        assert (tmp_live_dir / "tests" / "test_new.py").exists()
        shutil.rmtree(copy_dir)

    def test_rollback_restores_original(self, pipeline: ReconstructionPipeline, tmp_live_dir: Path):
        # Capture original content
        original = (tmp_live_dir / "src" / "claw" / "__init__.py").read_text()

        # Create backup, then modify live
        backup_dir = pipeline.create_backup()
        (tmp_live_dir / "src" / "claw" / "__init__.py").write_text("# totally changed\n")

        # Rollback
        pipeline.rollback(backup_dir)
        restored = (tmp_live_dir / "src" / "claw" / "__init__.py").read_text()
        assert restored == original
        shutil.rmtree(backup_dir)


# ---------------------------------------------------------------------------
# Pipeline: backup management
# ---------------------------------------------------------------------------

class TestBackupManagement:
    def test_cleanup_keeps_max(self, pipeline: ReconstructionPipeline, tmp_live_dir: Path):
        workspace_parent = tmp_live_dir.parent
        # Create 4 fake backups
        for i in range(4):
            d = workspace_parent / f"cam-backup-2026032{i}T120000"
            d.mkdir()
            (d / "marker.txt").write_text(f"backup {i}")

        removed = pipeline.cleanup_old_backups()
        remaining = list(workspace_parent.glob("cam-backup-*"))
        assert len(remaining) == 2  # max_backup_count = 2
        assert removed == 2

    def test_cleanup_copies(self, pipeline: ReconstructionPipeline, tmp_live_dir: Path):
        workspace_parent = tmp_live_dir.parent
        for i in range(3):
            d = workspace_parent / f"cam-self-enhance-2026032{i}T120000"
            d.mkdir()
            (d / "marker.txt").write_text(f"copy {i}")

        removed = pipeline.cleanup_old_copies()
        remaining = list(workspace_parent.glob("cam-self-enhance-*"))
        assert len(remaining) == 1  # Keep most recent
        assert removed == 2


# ---------------------------------------------------------------------------
# SelfEnhanceConfig
# ---------------------------------------------------------------------------

class TestSelfEnhanceConfig:
    def test_defaults(self):
        c = SelfEnhanceConfig()
        assert not c.enabled
        assert c.max_backup_count == 3
        assert c.min_new_methodologies == 10
        assert c.cooldown_hours == 24
        assert c.require_user_confirmation is True

    def test_protected_files_default(self):
        c = SelfEnhanceConfig()
        assert "src/claw/verifier.py" in c.protected_files
        assert "src/claw/core/config.py" in c.protected_files

    def test_custom_values(self):
        c = SelfEnhanceConfig(
            enabled=True,
            min_new_methodologies=20,
            min_avg_novelty_score=0.9,
            cooldown_hours=48,
        )
        assert c.enabled
        assert c.min_new_methodologies == 20
        assert c.min_avg_novelty_score == 0.9
        assert c.cooldown_hours == 48


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------

class TestConfigIntegration:
    def test_self_enhance_in_clawconfig(self):
        cfg = ClawConfig()
        assert hasattr(cfg, "self_enhance")
        assert isinstance(cfg.self_enhance, SelfEnhanceConfig)

    def test_load_from_toml(self, tmp_path: Path):
        """Verify claw.toml with [self_enhance] section loads correctly."""
        toml_content = """
[database]
db_path = "data/claw.db"

[self_enhance]
enabled = true
min_new_methodologies = 15
cooldown_hours = 12
"""
        toml_path = tmp_path / "claw.toml"
        toml_path.write_text(toml_content)

        from claw.core.config import load_config
        cfg = load_config(toml_path)
        assert cfg.self_enhance.enabled is True
        assert cfg.self_enhance.min_new_methodologies == 15
        assert cfg.self_enhance.cooldown_hours == 12
