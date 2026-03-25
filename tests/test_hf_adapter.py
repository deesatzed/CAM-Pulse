"""Tests for hf-mount adapter module.

Covers:
  - MountTier enum values and comparisons
  - MountInfo dataclass construction and field access
  - MountResult dataclass defaults, success, and error states
  - HF_BINARY_EXTENSIONS frozenset membership and type
  - hf_mount_available() real system check
  - is_hf_mount() on regular and nonexistent paths
  - classify_tier() on nonexistent, regular dirs, and git dirs
  - mining_strategy() for all three tiers
  - HFMountAdapter construction and attribute verification
  - HFMountAdapter.get_head_sha() on real git repos and non-git dirs
  - HFMountAdapter.unmount() on a non-hf-mount temp directory
  - Constants verification
"""

from __future__ import annotations

import os
import subprocess
import tempfile

import pytest

from claw.pulse.hf_adapter import (
    HF_BINARY_EXTENSIONS,
    HFMountAdapter,
    MountInfo,
    MountResult,
    MountTier,
    _STATVFS_F_BAVAIL,
    _STATVFS_F_BLOCKS,
    _STATVFS_F_FILES,
    classify_tier,
    hf_mount_available,
    is_hf_mount,
    mining_strategy,
)
from pathlib import Path


# ---------------------------------------------------------------------------
# MountTier enum
# ---------------------------------------------------------------------------

class TestMountTier:
    def test_mount_tier_values(self):
        """PHANTOM, MOUNTED, MATERIALIZED have correct string values."""
        assert MountTier.PHANTOM.value == "phantom"
        assert MountTier.MOUNTED.value == "mounted"
        assert MountTier.MATERIALIZED.value == "materialized"

    def test_mount_tier_equality(self):
        """Enum comparison works for same and different members."""
        assert MountTier.PHANTOM == MountTier.PHANTOM
        assert MountTier.MOUNTED == MountTier.MOUNTED
        assert MountTier.MATERIALIZED == MountTier.MATERIALIZED
        assert MountTier.PHANTOM != MountTier.MOUNTED
        assert MountTier.MOUNTED != MountTier.MATERIALIZED

    def test_mount_tier_membership(self):
        """All three tiers are present in the enum."""
        members = list(MountTier)
        assert len(members) == 3
        assert MountTier.PHANTOM in members
        assert MountTier.MOUNTED in members
        assert MountTier.MATERIALIZED in members

    def test_mount_tier_from_value(self):
        """Can reconstruct enum from its string value."""
        assert MountTier("phantom") is MountTier.PHANTOM
        assert MountTier("mounted") is MountTier.MOUNTED
        assert MountTier("materialized") is MountTier.MATERIALIZED


# ---------------------------------------------------------------------------
# MountInfo dataclass
# ---------------------------------------------------------------------------

class TestMountInfo:
    def test_mount_info_creation(self):
        """Construct MountInfo with all fields."""
        info = MountInfo(
            pid=12345,
            mount_type="repo",
            repo_id="owner/name",
            mount_path="/mnt/hf/owner_name",
        )
        assert info.pid == 12345
        assert info.mount_type == "repo"
        assert info.repo_id == "owner/name"
        assert info.mount_path == "/mnt/hf/owner_name"

    def test_mount_info_fields(self):
        """Each field is individually accessible and typed correctly."""
        info = MountInfo(pid=99, mount_type="bucket", repo_id="a/b", mount_path="/x")
        assert isinstance(info.pid, int)
        assert isinstance(info.mount_type, str)
        assert isinstance(info.repo_id, str)
        assert isinstance(info.mount_path, str)

    def test_mount_info_equality(self):
        """Two MountInfo with same values are equal (dataclass default)."""
        a = MountInfo(pid=1, mount_type="repo", repo_id="x/y", mount_path="/p")
        b = MountInfo(pid=1, mount_type="repo", repo_id="x/y", mount_path="/p")
        assert a == b


# ---------------------------------------------------------------------------
# MountResult dataclass
# ---------------------------------------------------------------------------

class TestMountResult:
    def test_mount_result_defaults(self):
        """Default MountResult has success=False, empty strings, error=None."""
        r = MountResult()
        assert r.success is False
        assert r.mount_path == ""
        assert r.method == ""
        assert r.error is None

    def test_mount_result_success(self):
        """Construct a successful MountResult."""
        r = MountResult(
            success=True,
            mount_path="/mnt/hf/repo",
            method="hf-mount",
            error=None,
        )
        assert r.success is True
        assert r.mount_path == "/mnt/hf/repo"
        assert r.method == "hf-mount"
        assert r.error is None

    def test_mount_result_error(self):
        """Construct an error MountResult."""
        r = MountResult(
            success=False,
            mount_path="/mnt/hf/repo",
            method="hf-mount",
            error="Mount timed out after 30s",
        )
        assert r.success is False
        assert r.error == "Mount timed out after 30s"
        assert r.method == "hf-mount"

    def test_mount_result_snapshot_download_method(self):
        """MountResult with snapshot_download method."""
        r = MountResult(
            success=True,
            mount_path="/data/repo",
            method="snapshot_download",
        )
        assert r.method == "snapshot_download"


# ---------------------------------------------------------------------------
# HF_BINARY_EXTENSIONS
# ---------------------------------------------------------------------------

class TestHFBinaryExtensions:
    def test_binary_extensions_is_frozenset(self):
        """HF_BINARY_EXTENSIONS is a frozenset (immutable)."""
        assert isinstance(HF_BINARY_EXTENSIONS, frozenset)

    def test_binary_extensions_contains_safetensors(self):
        """.safetensors is in the binary extensions set."""
        assert ".safetensors" in HF_BINARY_EXTENSIONS

    def test_binary_extensions_contains_gguf(self):
        """.gguf is in the binary extensions set."""
        assert ".gguf" in HF_BINARY_EXTENSIONS

    def test_binary_extensions_contains_bin(self):
        """.bin is in the binary extensions set."""
        assert ".bin" in HF_BINARY_EXTENSIONS

    def test_binary_extensions_contains_onnx(self):
        """.onnx is in the binary extensions set."""
        assert ".onnx" in HF_BINARY_EXTENSIONS

    def test_binary_extensions_contains_pt(self):
        """.pt is in the binary extensions set."""
        assert ".pt" in HF_BINARY_EXTENSIONS

    def test_binary_extensions_contains_pth(self):
        """.pth is in the binary extensions set."""
        assert ".pth" in HF_BINARY_EXTENSIONS

    def test_binary_extensions_contains_h5(self):
        """.h5 is in the binary extensions set."""
        assert ".h5" in HF_BINARY_EXTENSIONS

    def test_binary_extensions_does_not_contain_py(self):
        """.py is NOT in the binary extensions set."""
        assert ".py" not in HF_BINARY_EXTENSIONS

    def test_binary_extensions_does_not_contain_json(self):
        """.json is NOT in the binary extensions set."""
        assert ".json" not in HF_BINARY_EXTENSIONS

    def test_binary_extensions_does_not_contain_md(self):
        """.md is NOT in the binary extensions set."""
        assert ".md" not in HF_BINARY_EXTENSIONS

    def test_binary_extensions_count(self):
        """Binary extensions set has the expected number of entries."""
        assert len(HF_BINARY_EXTENSIONS) == 11


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_statvfs_f_blocks(self):
        """_STATVFS_F_BLOCKS is 2^31."""
        assert _STATVFS_F_BLOCKS == 2147483648
        assert _STATVFS_F_BLOCKS == 2**31

    def test_statvfs_f_bavail(self):
        """_STATVFS_F_BAVAIL is 2^31."""
        assert _STATVFS_F_BAVAIL == 2147483648
        assert _STATVFS_F_BAVAIL == 2**31

    def test_statvfs_f_files(self):
        """_STATVFS_F_FILES is 2^30."""
        assert _STATVFS_F_FILES == 1073741824
        assert _STATVFS_F_FILES == 2**30


# ---------------------------------------------------------------------------
# hf_mount_available()
# ---------------------------------------------------------------------------

class TestHFMountAvailable:
    def test_hf_mount_available_returns_bool(self):
        """hf_mount_available() returns a boolean (real system check)."""
        result = hf_mount_available()
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# is_hf_mount()
# ---------------------------------------------------------------------------

class TestIsHFMount:
    def test_is_hf_mount_regular_path(self):
        """/tmp is NOT an hf-mount filesystem."""
        # /tmp on macOS resolves to /private/tmp -- use os.path.realpath
        result = is_hf_mount(os.path.realpath("/tmp"))
        assert result is False

    def test_is_hf_mount_nonexistent(self):
        """Nonexistent path returns False (OSError caught internally)."""
        result = is_hf_mount("/nonexistent/path/that/does/not/exist")
        assert result is False

    def test_is_hf_mount_temp_dir(self):
        """Freshly created temp directory is NOT an hf-mount."""
        with tempfile.TemporaryDirectory() as td:
            assert is_hf_mount(td) is False

    def test_is_hf_mount_returns_bool(self):
        """Return type is always bool, never None or other."""
        assert isinstance(is_hf_mount("/tmp"), bool)
        assert isinstance(is_hf_mount("/nonexistent"), bool)


# ---------------------------------------------------------------------------
# classify_tier()
# ---------------------------------------------------------------------------

class TestClassifyTier:
    def test_classify_tier_nonexistent(self):
        """Nonexistent path is classified as PHANTOM."""
        result = classify_tier("/path/that/absolutely/does/not/exist")
        assert result is MountTier.PHANTOM

    def test_classify_tier_regular_dir(self):
        """A plain temp directory (no .git, not hf-mount) is MATERIALIZED."""
        with tempfile.TemporaryDirectory() as td:
            result = classify_tier(td)
            assert result is MountTier.MATERIALIZED

    def test_classify_tier_git_dir(self):
        """A directory with .git subdirectory is MATERIALIZED."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            result = classify_tier(td)
            assert result is MountTier.MATERIALIZED

    def test_classify_tier_returns_mount_tier(self):
        """Return type is always a MountTier enum member."""
        assert isinstance(classify_tier("/nonexistent"), MountTier)
        with tempfile.TemporaryDirectory() as td:
            assert isinstance(classify_tier(td), MountTier)


# ---------------------------------------------------------------------------
# mining_strategy()
# ---------------------------------------------------------------------------

class TestMiningStrategy:
    def test_mining_strategy_phantom(self):
        """PHANTOM tier: action='skip'."""
        strat = mining_strategy(MountTier.PHANTOM)
        assert strat["action"] == "skip"
        assert "reason" in strat

    def test_mining_strategy_mounted(self):
        """MOUNTED tier: action='mine', skip_binary=True, source_kind='hf_mount'."""
        strat = mining_strategy(MountTier.MOUNTED)
        assert strat["action"] == "mine"
        assert strat["skip_binary"] is True
        assert strat["source_kind"] == "hf_mount"

    def test_mining_strategy_materialized(self):
        """MATERIALIZED tier: action='mine', skip_binary=True, source_kind='local'."""
        strat = mining_strategy(MountTier.MATERIALIZED)
        assert strat["action"] == "mine"
        assert strat["skip_binary"] is True
        assert strat["source_kind"] == "local"

    def test_mining_strategy_all_tiers_return_dicts(self):
        """All three tiers return valid dicts with at least 'action' key."""
        for tier in MountTier:
            strat = mining_strategy(tier)
            assert isinstance(strat, dict)
            assert "action" in strat

    def test_mining_strategy_mounted_max_file_size(self):
        """MOUNTED tier has a conservative max_file_size (500K for streaming)."""
        strat = mining_strategy(MountTier.MOUNTED)
        assert strat["max_file_size"] == 500_000

    def test_mining_strategy_materialized_max_file_size(self):
        """MATERIALIZED tier has a larger max_file_size (900K for local)."""
        strat = mining_strategy(MountTier.MATERIALIZED)
        assert strat["max_file_size"] == 900_000

    def test_mining_strategy_phantom_has_no_skip_binary(self):
        """PHANTOM tier dict does not contain skip_binary (no mining)."""
        strat = mining_strategy(MountTier.PHANTOM)
        assert "skip_binary" not in strat


# ---------------------------------------------------------------------------
# HFMountAdapter -- construction and attributes
# ---------------------------------------------------------------------------

class TestHFMountAdapterConstruction:
    def test_adapter_creation_defaults(self):
        """Create adapter with defaults, verify attributes exist."""
        adapter = HFMountAdapter()
        assert adapter._mount_base == Path("data/hf_mounts")
        assert adapter._cache_size == 1_073_741_824
        assert adapter._cache_dir == "/tmp/hf-mount-cache"
        assert adapter._hf_token is None
        assert adapter._timeout == 30
        assert adapter._fallback is True
        assert adapter._binary is None

    def test_adapter_custom_params(self):
        """Create adapter with custom parameters."""
        adapter = HFMountAdapter(
            mount_base="/custom/mounts",
            cache_size_bytes=2_000_000_000,
            cache_dir="/custom/cache",
            hf_token="hf_test_token",
            mount_timeout_secs=60,
            fallback_to_download=False,
        )
        assert adapter._mount_base == Path("/custom/mounts")
        assert adapter._cache_size == 2_000_000_000
        assert adapter._cache_dir == "/custom/cache"
        assert adapter._hf_token == "hf_test_token"
        assert adapter._timeout == 60
        assert adapter._fallback is False

    def test_adapter_mount_base_is_path(self):
        """_mount_base is converted to a Path object."""
        adapter = HFMountAdapter(mount_base="/some/path")
        assert isinstance(adapter._mount_base, Path)

    def test_adapter_mount_base_string_input(self):
        """String mount_base is properly converted to Path."""
        adapter = HFMountAdapter(mount_base="relative/path")
        assert adapter._mount_base == Path("relative/path")


# ---------------------------------------------------------------------------
# HFMountAdapter.get_head_sha() -- real git operations
# ---------------------------------------------------------------------------

class TestHFMountAdapterGetHeadSha:
    @pytest.mark.asyncio
    async def test_adapter_get_head_sha_git_repo(self):
        """Create a real temp git repo, call get_head_sha, verify 40-char hex."""
        with tempfile.TemporaryDirectory() as td:
            # Initialize a real git repo with a commit
            subprocess.run(
                ["git", "init"], cwd=td, check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=td, check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=td, check=True, capture_output=True,
            )
            # Create a file and commit it
            test_file = os.path.join(td, "hello.txt")
            with open(test_file, "w") as f:
                f.write("hello world\n")
            subprocess.run(
                ["git", "add", "hello.txt"], cwd=td, check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "initial commit"],
                cwd=td, check=True, capture_output=True,
            )

            adapter = HFMountAdapter()
            sha = await adapter.get_head_sha(td)

            assert sha is not None
            assert len(sha) == 40
            # Verify it is a valid hex string
            int(sha, 16)

    @pytest.mark.asyncio
    async def test_adapter_get_head_sha_no_git(self):
        """Non-git temp directory returns None."""
        with tempfile.TemporaryDirectory() as td:
            adapter = HFMountAdapter()
            sha = await adapter.get_head_sha(td)
            assert sha is None

    @pytest.mark.asyncio
    async def test_adapter_get_head_sha_nonexistent_path(self):
        """Nonexistent path returns None."""
        adapter = HFMountAdapter()
        sha = await adapter.get_head_sha("/nonexistent/path/to/repo")
        assert sha is None

    @pytest.mark.asyncio
    async def test_adapter_get_head_sha_matches_git_rev_parse(self):
        """get_head_sha output matches direct git rev-parse HEAD."""
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(
                ["git", "init"], cwd=td, check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=td, check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=td, check=True, capture_output=True,
            )
            test_file = os.path.join(td, "file.txt")
            with open(test_file, "w") as f:
                f.write("content\n")
            subprocess.run(
                ["git", "add", "file.txt"], cwd=td, check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "commit"], cwd=td, check=True,
                capture_output=True,
            )

            # Get SHA via subprocess directly
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=td, check=True,
                capture_output=True, text=True,
            )
            expected_sha = proc.stdout.strip()

            # Get SHA via adapter
            adapter = HFMountAdapter()
            actual_sha = await adapter.get_head_sha(td)

            assert actual_sha == expected_sha


# ---------------------------------------------------------------------------
# HFMountAdapter.unmount() -- non-hf-mount directory cleanup
# ---------------------------------------------------------------------------

class TestHFMountAdapterUnmount:
    @pytest.mark.asyncio
    async def test_adapter_unmount_removes_temp_dir(self):
        """unmount() on a non-hf-mount directory removes it (fallback path)."""
        td = tempfile.mkdtemp()
        # Write a file into it so it's non-empty
        with open(os.path.join(td, "test.txt"), "w") as f:
            f.write("data")
        assert os.path.exists(td)

        adapter = HFMountAdapter()
        result = await adapter.unmount(td)

        assert result is True
        assert not os.path.exists(td)

    @pytest.mark.asyncio
    async def test_adapter_unmount_nonexistent_returns_true(self):
        """unmount() on a nonexistent path returns True (nothing to remove)."""
        adapter = HFMountAdapter()
        result = await adapter.unmount("/nonexistent/path/should/succeed")
        assert result is True


# ---------------------------------------------------------------------------
# Integration: classify_tier + mining_strategy pipeline
# ---------------------------------------------------------------------------

class TestTierStrategyIntegration:
    def test_nonexistent_path_skips_mining(self):
        """Full pipeline: nonexistent path -> PHANTOM -> skip."""
        tier = classify_tier("/does/not/exist")
        strat = mining_strategy(tier)
        assert strat["action"] == "skip"

    def test_real_temp_dir_mines_locally(self):
        """Full pipeline: temp dir -> MATERIALIZED -> mine with source_kind=local."""
        with tempfile.TemporaryDirectory() as td:
            tier = classify_tier(td)
            strat = mining_strategy(tier)
            assert strat["action"] == "mine"
            assert strat["source_kind"] == "local"

    def test_git_repo_mines_locally(self):
        """Full pipeline: git dir -> MATERIALIZED -> mine with source_kind=local."""
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, ".git"))
            tier = classify_tier(td)
            strat = mining_strategy(tier)
            assert strat["action"] == "mine"
            assert strat["source_kind"] == "local"
