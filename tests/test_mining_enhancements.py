"""Tests for mining enhancements: configurable filters, .mineignore, content dedup."""

import hashlib
import shutil
import time
from pathlib import Path

import pytest

from claw.core.config import ClawConfig, MiningConfig
from claw.miner import (
    RepoCandidate,
    RepoScanLedger,
    _CODE_EXTENSIONS,
    _SKIP_DIRS,
    _collect_repo_metadata,
    _dedup_iterations,
    _discover_repos,
    _get_code_extensions,
    _get_skip_dirs,
    _is_mineignored,
    _load_mineignore,
    _looks_like_source_tree,
    serialize_repo,
)


# ---------------------------------------------------------------------------
# 1. Configurable Extensions & Skip Dirs
# ---------------------------------------------------------------------------

class TestConfigurableExtensions:

    def test_get_code_extensions_default(self):
        """Without config, returns base defaults."""
        exts = _get_code_extensions(None)
        assert exts == _CODE_EXTENSIONS
        assert ".py" in exts
        assert ".cpp" not in exts

    def test_get_code_extensions_with_config(self):
        """Config extras are merged with base defaults."""
        cfg = ClawConfig(mining=MiningConfig(extra_code_extensions=[".cpp", ".rb"]))
        exts = _get_code_extensions(cfg)
        assert ".py" in exts  # base
        assert ".cpp" in exts  # extra
        assert ".rb" in exts  # extra

    def test_get_code_extensions_normalizes_dot(self):
        """Extensions without leading dot get it added."""
        cfg = ClawConfig(mining=MiningConfig(extra_code_extensions=["cpp"]))
        exts = _get_code_extensions(cfg)
        assert ".cpp" in exts

    def test_get_skip_dirs_default(self):
        """Without config, returns base defaults."""
        dirs = _get_skip_dirs(None)
        assert dirs == _SKIP_DIRS
        assert "node_modules" in dirs
        assert "migrations" not in dirs

    def test_get_skip_dirs_with_config(self):
        """Config extras are merged with base defaults."""
        cfg = ClawConfig(mining=MiningConfig(extra_skip_dirs=["migrations", "vendor"]))
        dirs = _get_skip_dirs(cfg)
        assert "node_modules" in dirs  # base
        assert "migrations" in dirs  # extra
        assert "vendor" in dirs  # extra

    def test_serialize_repo_uses_extra_extensions(self, tmp_path):
        """serialize_repo includes files matching extra extensions."""
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "lib.cpp").write_text("int main() {}")

        # Without config — .cpp excluded
        content_no_cfg, count_no_cfg = serialize_repo(tmp_path)
        assert "main.py" in content_no_cfg
        assert "lib.cpp" not in content_no_cfg
        assert count_no_cfg == 1

        # With config — .cpp included
        cfg = ClawConfig(mining=MiningConfig(extra_code_extensions=[".cpp"]))
        content_cfg, count_cfg = serialize_repo(tmp_path, config=cfg)
        assert "main.py" in content_cfg
        assert "lib.cpp" in content_cfg
        assert count_cfg == 2

    def test_serialize_repo_skips_extra_dirs(self, tmp_path):
        """serialize_repo skips directories in extra_skip_dirs."""
        (tmp_path / "main.py").write_text("print('hello')")
        migrations = tmp_path / "migrations"
        migrations.mkdir()
        (migrations / "001.py").write_text("migration code")

        # Without config — migrations included
        content_no_cfg, count_no_cfg = serialize_repo(tmp_path)
        assert count_no_cfg == 2

        # With config — migrations excluded
        cfg = ClawConfig(mining=MiningConfig(extra_skip_dirs=["migrations"]))
        content_cfg, count_cfg = serialize_repo(tmp_path, config=cfg)
        assert count_cfg == 1
        assert "001.py" not in content_cfg

    def test_discover_repos_uses_extra_skip_dirs(self, tmp_path):
        """_discover_repos skips directories in extra_skip_dirs."""
        # Create a repo inside a normally discovered path
        repo = tmp_path / "myrepo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "main.py").write_text("code")

        # Create a repo inside a custom skip dir
        vendor = tmp_path / "vendor"
        vendor.mkdir()
        vendor_repo = vendor / "dep"
        vendor_repo.mkdir()
        (vendor_repo / ".git").mkdir()
        (vendor_repo / "lib.py").write_text("dep code")

        # Without config — both found
        found_no_cfg = _discover_repos(tmp_path, max_depth=3)
        names = {c.name for c in found_no_cfg}
        assert "myrepo" in names
        assert "dep" in names

        # With config — vendor excluded
        cfg = ClawConfig(mining=MiningConfig(extra_skip_dirs=["vendor"]))
        found_cfg = _discover_repos(tmp_path, max_depth=3, config=cfg)
        names_cfg = {c.name for c in found_cfg}
        assert "myrepo" in names_cfg
        assert "dep" not in names_cfg


# ---------------------------------------------------------------------------
# 2. .mineignore Support
# ---------------------------------------------------------------------------

class TestMineignore:

    def test_load_mineignore_no_file(self, tmp_path):
        """Returns empty list when no .mineignore exists."""
        assert _load_mineignore(tmp_path) == []

    def test_load_mineignore_basic(self, tmp_path):
        (tmp_path / ".mineignore").write_text(
            "# comment\nnode_modules_backup/\n\n*.min.js\nReposEV/\n"
        )
        patterns = _load_mineignore(tmp_path)
        assert "node_modules_backup/" in patterns
        assert "*.min.js" in patterns
        assert "ReposEV/" in patterns
        assert len(patterns) == 3  # comment and blank excluded

    def test_is_mineignored_exact_dir(self):
        """Matches directory name as path component."""
        assert _is_mineignored("ReposEV/somefile.py", ["ReposEV/"])
        assert _is_mineignored("deep/ReposEV/somefile.py", ["ReposEV/"])

    def test_is_mineignored_glob(self):
        """Matches glob patterns."""
        assert _is_mineignored("bundle.min.js", ["*.min.js"])
        assert _is_mineignored("static/app.min.js", ["*.min.js"])

    def test_is_mineignored_no_match(self):
        """Does not match unrelated paths."""
        assert not _is_mineignored("src/main.py", ["ReposEV/"])
        assert not _is_mineignored("src/main.py", ["*.min.js"])

    def test_discover_repos_respects_mineignore(self, tmp_path):
        """_discover_repos skips directories matching .mineignore patterns."""
        # Create .mineignore at scan root
        (tmp_path / ".mineignore").write_text("old_stuff\n")

        # Create a repo that should be found
        good = tmp_path / "good_repo"
        good.mkdir()
        (good / ".git").mkdir()
        (good / "main.py").write_text("good code")

        # Create a repo in ignored dir
        old = tmp_path / "old_stuff"
        old.mkdir()
        old_repo = old / "legacy"
        old_repo.mkdir()
        (old_repo / ".git").mkdir()
        (old_repo / "main.py").write_text("old code")

        found = _discover_repos(tmp_path, max_depth=3)
        names = {c.name for c in found}
        assert "good_repo" in names
        assert "legacy" not in names

    def test_serialize_repo_respects_mineignore(self, tmp_path):
        """serialize_repo skips files matching .mineignore patterns."""
        (tmp_path / ".mineignore").write_text("generated/\n")
        (tmp_path / "main.py").write_text("real code")
        gen = tmp_path / "generated"
        gen.mkdir()
        (gen / "output.py").write_text("generated code")

        content, count = serialize_repo(tmp_path)
        assert count == 1
        assert "main.py" in content
        assert "output.py" not in content


# ---------------------------------------------------------------------------
# 3. Content-Level Cross-Repo Dedup
# ---------------------------------------------------------------------------

class TestContentDedup:

    def test_content_hash_computed(self, tmp_path):
        """_collect_repo_metadata returns a content hash."""
        (tmp_path / "main.py").write_text("print('hello')")
        _, _, _, _, content_hash = _collect_repo_metadata(tmp_path)
        assert content_hash
        assert len(content_hash) == 64  # SHA-256 hex

    def test_identical_repos_same_content_hash(self, tmp_path):
        """Two repos with identical files produce the same content hash."""
        repo_a = tmp_path / "repo_a"
        repo_a.mkdir()
        (repo_a / "main.py").write_text("print('hello')")
        (repo_a / "util.py").write_text("def helper(): pass")

        repo_b = tmp_path / "repo_b"
        shutil.copytree(repo_a, repo_b)

        _, _, _, _, hash_a = _collect_repo_metadata(repo_a)
        _, _, _, _, hash_b = _collect_repo_metadata(repo_b)
        assert hash_a == hash_b

    def test_different_repos_different_content_hash(self, tmp_path):
        """Repos with different content produce different hashes."""
        repo_a = tmp_path / "repo_a"
        repo_a.mkdir()
        (repo_a / "main.py").write_text("print('hello')")

        repo_b = tmp_path / "repo_b"
        repo_b.mkdir()
        (repo_b / "main.py").write_text("print('world')")

        _, _, _, _, hash_a = _collect_repo_metadata(repo_a)
        _, _, _, _, hash_b = _collect_repo_metadata(repo_b)
        assert hash_a != hash_b

    def test_dedup_iterations_content_hash(self, tmp_path):
        """Content hash dedup catches repos with different names but same code."""
        repo_a = tmp_path / "project-dec2025"
        repo_a.mkdir()
        (repo_a / "main.py").write_text("print('same code')")

        repo_b = tmp_path / "project-final-release"
        shutil.copytree(repo_a, repo_b)

        _, _, _, _, hash_a = _collect_repo_metadata(repo_a)
        _, _, _, _, hash_b = _collect_repo_metadata(repo_b)

        candidates = [
            RepoCandidate(path=repo_a, name="project-dec2025", canonical_name="project-dec2025",
                          depth=1, file_count=1, total_bytes=100, last_commit_ts=100.0,
                          content_hash=hash_a),
            RepoCandidate(path=repo_b, name="project-final-release", canonical_name="project-final-release",
                          depth=1, file_count=1, total_bytes=100, last_commit_ts=99.0,
                          content_hash=hash_b),
        ]

        selected, skipped = _dedup_iterations(candidates)
        assert len(selected) == 1
        assert len(skipped) == 1
        assert "content-duplicate" in skipped[0][1]

    def test_dedup_iterations_keeps_most_recent(self, tmp_path):
        """Content hash dedup keeps the most recently modified copy."""
        repo_a = tmp_path / "old_copy"
        repo_a.mkdir()
        (repo_a / "main.py").write_text("same")

        repo_b = tmp_path / "new_copy"
        shutil.copytree(repo_a, repo_b)

        _, _, _, _, ch = _collect_repo_metadata(repo_a)

        candidates = [
            RepoCandidate(path=repo_a, name="old_copy", canonical_name="old_copy",
                          depth=1, file_count=1, total_bytes=4, last_commit_ts=1000.0,
                          content_hash=ch),
            RepoCandidate(path=repo_b, name="new_copy", canonical_name="new_copy",
                          depth=1, file_count=1, total_bytes=4, last_commit_ts=2000.0,
                          content_hash=ch),
        ]

        selected, skipped = _dedup_iterations(candidates)
        assert len(selected) == 1
        assert selected[0].name == "new_copy"  # most recent wins

    def test_ledger_content_hash_cross_repo_skip(self, tmp_path):
        """Ledger skips new repo if content hash matches an already-mined repo."""
        ledger_path = tmp_path / "ledger.json"
        ledger = RepoScanLedger(ledger_path)

        # Create two repos with identical content
        repo_a = tmp_path / "repo_a"
        repo_a.mkdir()
        (repo_a / "main.py").write_text("same code")

        repo_b = tmp_path / "repo_b"
        shutil.copytree(repo_a, repo_b)

        _, _, _, sig_a, ch_a = _collect_repo_metadata(repo_a)
        _, _, _, sig_b, ch_b = _collect_repo_metadata(repo_b)

        # Simulate repo_a already mined
        from claw.miner import RepoMiningResult
        candidate_a = RepoCandidate(
            path=repo_a, name="repo_a", canonical_name="repo_a",
            depth=1, file_count=1, total_bytes=9, scan_signature=sig_a,
            content_hash=ch_a,
        )
        result_a = RepoMiningResult(repo_name="repo_a", repo_path=str(repo_a))
        ledger.record_result(candidate_a, result_a)

        # Now check repo_b — should be skipped as content duplicate
        candidate_b = RepoCandidate(
            path=repo_b, name="repo_b", canonical_name="repo_b",
            depth=1, file_count=1, total_bytes=9, scan_signature=sig_b,
            content_hash=ch_b,
        )
        should, reason = ledger.should_mine(candidate_b)
        assert not should
        assert "content-duplicate" in reason

    def test_ledger_content_hash_allows_different_repos(self, tmp_path):
        """Ledger allows mining when content hashes differ."""
        ledger_path = tmp_path / "ledger.json"
        ledger = RepoScanLedger(ledger_path)

        repo_a = tmp_path / "repo_a"
        repo_a.mkdir()
        (repo_a / "main.py").write_text("code A")

        repo_b = tmp_path / "repo_b"
        repo_b.mkdir()
        (repo_b / "main.py").write_text("code B")

        _, _, _, sig_a, ch_a = _collect_repo_metadata(repo_a)
        _, _, _, sig_b, ch_b = _collect_repo_metadata(repo_b)

        from claw.miner import RepoMiningResult
        candidate_a = RepoCandidate(
            path=repo_a, name="repo_a", canonical_name="repo_a",
            depth=1, file_count=1, total_bytes=6, scan_signature=sig_a,
            content_hash=ch_a,
        )
        ledger.record_result(candidate_a, RepoMiningResult(repo_name="repo_a", repo_path=str(repo_a)))

        candidate_b = RepoCandidate(
            path=repo_b, name="repo_b", canonical_name="repo_b",
            depth=1, file_count=1, total_bytes=6, scan_signature=sig_b,
            content_hash=ch_b,
        )
        should, reason = ledger.should_mine(candidate_b)
        assert should
        assert reason == "new"

    def test_content_hash_empty_for_no_files(self, tmp_path):
        """Empty repo produces empty content hash."""
        _, _, _, _, content_hash = _collect_repo_metadata(tmp_path)
        assert content_hash == ""


# ---------------------------------------------------------------------------
# 4. MiningConfig
# ---------------------------------------------------------------------------

class TestMiningConfig:

    def test_defaults(self):
        """MiningConfig has sensible defaults."""
        cfg = MiningConfig()
        assert cfg.extra_code_extensions == []
        assert cfg.extra_skip_dirs == []

    def test_claw_config_has_mining(self):
        """ClawConfig includes mining field."""
        cfg = ClawConfig()
        assert hasattr(cfg, "mining")
        assert isinstance(cfg.mining, MiningConfig)

    def test_mining_config_from_dict(self):
        """MiningConfig can be created from dict (toml parsing)."""
        cfg = MiningConfig(
            extra_code_extensions=[".cpp", ".rb"],
            extra_skip_dirs=["vendor", "migrations"],
        )
        assert ".cpp" in cfg.extra_code_extensions
        assert "vendor" in cfg.extra_skip_dirs
