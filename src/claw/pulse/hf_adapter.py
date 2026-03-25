"""hf-mount adapter for CAM-PULSE.

Wraps the hf-mount CLI tool for mounting HF Hub repositories as local
filesystems. Falls back to huggingface_hub.snapshot_download() when
hf-mount is unavailable.

Reference: /Volumes/WS4TB/Agent_Pidgeon/HF_MOUNT_GUIDE.md
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

logger = logging.getLogger("claw.pulse.hf_adapter")


# ---------------------------------------------------------------------------
# Constants from tested hf-mount behavior (HF_MOUNT_GUIDE.md §6)
# ---------------------------------------------------------------------------
# NFS backend reports these exact statvfs constants, hardcoded in hf-mount
_STATVFS_F_BLOCKS = 2147483648
_STATVFS_F_BAVAIL = 2147483648
_STATVFS_F_FILES = 1073741824

# Binary file extensions to skip when mining HF repos (model weights)
HF_BINARY_EXTENSIONS = frozenset({
    ".bin", ".safetensors", ".gguf", ".onnx", ".pt", ".pth",
    ".h5", ".pb", ".tflite", ".mlmodel", ".msgpack",
})


class MountTier(Enum):
    """Materialization tier for a repository path."""
    PHANTOM = "phantom"          # Metadata only, not mounted or cloned
    MOUNTED = "mounted"          # hf-mount active, lazy streaming
    MATERIALIZED = "materialized"  # Fully cloned to local disk


@dataclass
class MountInfo:
    """Information about an active hf-mount daemon."""
    pid: int
    mount_type: str  # "repo" or "bucket"
    repo_id: str
    mount_path: str


@dataclass
class MountResult:
    """Result of a mount operation."""
    success: bool = False
    mount_path: str = ""
    method: str = ""  # "hf-mount" or "snapshot_download"
    error: str | None = None


# ---------------------------------------------------------------------------
# Detection functions (from HF_MOUNT_GUIDE.md §6, tested on M4 2026-03-25)
# ---------------------------------------------------------------------------

def hf_mount_available() -> bool:
    """Check if hf-mount binary is installed and reachable."""
    local_bin = Path.home() / ".local" / "bin" / "hf-mount"
    if local_bin.exists() and local_bin.stat().st_mode & 0o111:
        return True
    return shutil.which("hf-mount") is not None


def _get_hf_mount_binary() -> str:
    """Return path to hf-mount binary."""
    local_bin = Path.home() / ".local" / "bin" / "hf-mount"
    if local_bin.exists() and local_bin.stat().st_mode & 0o111:
        return str(local_bin)
    which = shutil.which("hf-mount")
    if which:
        return which
    raise FileNotFoundError("hf-mount binary not found")


def is_hf_mount(path: str) -> bool:
    """Detect if a path is an hf-mount NFS filesystem.

    Uses statvfs fingerprint -- hardcoded constants unique to hf-mount.
    Tested and verified on macOS 26.3, M4 64GB (HF_MOUNT_GUIDE.md §6).
    """
    try:
        st = os.statvfs(path)
        return (
            st.f_blocks == _STATVFS_F_BLOCKS
            and st.f_bavail == _STATVFS_F_BAVAIL
            and st.f_files == _STATVFS_F_FILES
        )
    except OSError:
        return False


def classify_tier(path: str) -> MountTier:
    """Classify a repository path into materialization tier."""
    if not os.path.exists(path):
        return MountTier.PHANTOM

    if is_hf_mount(path):
        return MountTier.MOUNTED

    # Has .git dir = fully cloned
    if os.path.isdir(os.path.join(path, ".git")):
        return MountTier.MATERIALIZED

    # Exists locally but not a mount or git clone -- treat as local files
    return MountTier.MATERIALIZED


def mining_strategy(tier: MountTier) -> dict:
    """Return mining parameters based on materialization tier."""
    return {
        MountTier.PHANTOM: {
            "action": "skip",
            "reason": "metadata only, no files to mine",
        },
        MountTier.MOUNTED: {
            "action": "mine",
            "skip_binary": True,
            "max_file_size": 500_000,  # conservative for streaming reads
            "source_kind": "hf_mount",
        },
        MountTier.MATERIALIZED: {
            "action": "mine",
            "skip_binary": True,
            "max_file_size": 900_000,  # full budget for local files
            "source_kind": "local",
        },
    }[tier]


# ---------------------------------------------------------------------------
# HFMountAdapter -- async mount/unmount/status
# ---------------------------------------------------------------------------

class HFMountAdapter:
    """Adapter for hf-mount CLI with fallback to huggingface_hub."""

    def __init__(
        self,
        mount_base: str = "data/hf_mounts",
        cache_size_bytes: int = 1_073_741_824,  # 1GB
        cache_dir: str = "/tmp/hf-mount-cache",
        hf_token: str | None = None,
        mount_timeout_secs: int = 30,
        fallback_to_download: bool = True,
    ):
        self._mount_base = Path(mount_base)
        self._cache_size = cache_size_bytes
        self._cache_dir = cache_dir
        self._hf_token = hf_token
        self._timeout = mount_timeout_secs
        self._fallback = fallback_to_download
        self._binary: str | None = None

    def _get_binary(self) -> str:
        """Lazy-resolve hf-mount binary path."""
        if self._binary is None:
            self._binary = _get_hf_mount_binary()
        return self._binary

    async def mount_repo(
        self,
        repo_id: str,
        revision: str = "main",
        mount_path: str | None = None,
    ) -> MountResult:
        """Mount an HF repo. Falls back to snapshot_download if hf-mount unavailable.

        Args:
            repo_id: HF repo ID (e.g., "d4data/biomedical-ner-all")
            revision: Git revision to mount (branch, tag, or SHA)
            mount_path: Optional explicit mount path. Auto-generated if None.

        Returns:
            MountResult with success status, path, and method used.
        """
        if mount_path is None:
            safe_name = repo_id.replace("/", "_")
            mount_path = str(self._mount_base / safe_name)

        # Ensure mount point directory exists and is empty
        mp = Path(mount_path)
        mp.mkdir(parents=True, exist_ok=True)

        # Try hf-mount first
        if hf_mount_available():
            result = await self._mount_via_hfmount(repo_id, mount_path, revision)
            if result.success:
                return result
            logger.warning(
                "hf-mount failed for %s: %s -- trying fallback",
                repo_id, result.error,
            )

        # Fallback to huggingface_hub download
        if self._fallback:
            return await self._mount_via_download(repo_id, mount_path, revision)

        return MountResult(
            success=False,
            mount_path=mount_path,
            error="hf-mount unavailable and fallback disabled",
        )

    async def _mount_via_hfmount(
        self, repo_id: str, mount_path: str, revision: str
    ) -> MountResult:
        """Mount using hf-mount CLI."""
        try:
            binary = self._get_binary()
        except FileNotFoundError as e:
            return MountResult(success=False, mount_path=mount_path, error=str(e))

        cmd = [binary, "start"]

        if self._hf_token:
            cmd.extend(["--hf-token", self._hf_token])

        cmd.extend([
            "--cache-size", str(self._cache_size),
            "--cache-dir", self._cache_dir,
            "--poll-interval-secs", "0",  # static snapshot for mining
        ])

        if revision != "main":
            cmd.extend(["--revision", revision])

        cmd.extend(["repo", repo_id, mount_path])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )

            if proc.returncode == 0:
                logger.info("Mounted %s at %s via hf-mount", repo_id, mount_path)
                return MountResult(
                    success=True,
                    mount_path=mount_path,
                    method="hf-mount",
                )
            else:
                error = stderr.decode().strip() or stdout.decode().strip()
                return MountResult(
                    success=False,
                    mount_path=mount_path,
                    method="hf-mount",
                    error=error,
                )

        except asyncio.TimeoutError:
            return MountResult(
                success=False,
                mount_path=mount_path,
                method="hf-mount",
                error=f"Mount timed out after {self._timeout}s",
            )
        except Exception as e:
            return MountResult(
                success=False,
                mount_path=mount_path,
                method="hf-mount",
                error=str(e),
            )

    async def _mount_via_download(
        self, repo_id: str, mount_path: str, revision: str
    ) -> MountResult:
        """Fallback: download repo via huggingface_hub."""
        try:
            from huggingface_hub import snapshot_download

            # Run in executor to avoid blocking event loop
            loop = asyncio.get_running_loop()
            local_dir = await loop.run_in_executor(
                None,
                lambda: snapshot_download(
                    repo_id=repo_id,
                    revision=revision,
                    local_dir=mount_path,
                    token=self._hf_token,
                    ignore_patterns=["*.bin", "*.safetensors", "*.gguf",
                                     "*.onnx", "*.pt", "*.pth", "*.h5",
                                     "*.pb", "*.tflite", "*.msgpack"],
                ),
            )

            logger.info(
                "Downloaded %s to %s via huggingface_hub (fallback)",
                repo_id, local_dir,
            )
            return MountResult(
                success=True,
                mount_path=str(local_dir),
                method="snapshot_download",
            )

        except ImportError:
            return MountResult(
                success=False,
                mount_path=mount_path,
                error="Neither hf-mount nor huggingface_hub available",
            )
        except Exception as e:
            return MountResult(
                success=False,
                mount_path=mount_path,
                method="snapshot_download",
                error=str(e),
            )

    async def unmount(self, mount_path: str) -> bool:
        """Unmount an hf-mount path. Returns True on success.

        For snapshot_download fallback paths, removes the directory instead.
        """
        # Normalize macOS /tmp -> /private/tmp
        real_path = os.path.realpath(mount_path)

        if is_hf_mount(real_path):
            return await self._unmount_hfmount(mount_path)
        else:
            # Fallback download -- just remove the directory
            try:
                if os.path.exists(mount_path):
                    shutil.rmtree(mount_path)
                    logger.info("Removed fallback download: %s", mount_path)
                return True
            except Exception as e:
                logger.warning("Failed to remove %s: %s", mount_path, e)
                return False

    async def _unmount_hfmount(self, mount_path: str) -> bool:
        """Unmount via hf-mount CLI."""
        try:
            binary = self._get_binary()
            proc = await asyncio.create_subprocess_exec(
                binary, "stop", mount_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=15
            )

            if proc.returncode == 0:
                logger.info("Unmounted %s", mount_path)
                return True
            else:
                error = stderr.decode().strip()
                logger.warning("Unmount failed for %s: %s", mount_path, error)
                return False

        except Exception as e:
            logger.warning("Unmount error for %s: %s", mount_path, e)
            return False

    async def list_mounts(self) -> list[MountInfo]:
        """List active hf-mount daemons."""
        if not hf_mount_available():
            return []

        try:
            binary = self._get_binary()
            proc = await asyncio.create_subprocess_exec(
                binary, "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=5
            )

            mounts: list[MountInfo] = []
            for line in stdout.decode().strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("No"):
                    continue
                # Format: pid=XXXXX    repo owner/name -> /path
                parts = line.split()
                if len(parts) >= 4 and "=" in parts[0]:
                    try:
                        pid = int(parts[0].split("=")[1])
                        mount_type = parts[1]
                        repo_id = parts[2]
                        # Find the path after arrow character
                        arrow_idx = line.find("\u2192")
                        if arrow_idx >= 0:
                            path = line[arrow_idx + 1:].strip()
                        else:
                            path = parts[-1]

                        mounts.append(MountInfo(
                            pid=pid,
                            mount_type=mount_type,
                            repo_id=repo_id,
                            mount_path=path,
                        ))
                    except (ValueError, IndexError):
                        continue

            return mounts

        except Exception as e:
            logger.warning("Failed to list mounts: %s", e)
            return []

    async def get_head_sha(self, mount_path: str) -> str | None:
        """Get HEAD commit SHA from a mounted or cloned repo.

        For hf-mount paths, reads .git/refs/heads/main or uses the HF API.
        For git clones, runs git rev-parse HEAD.
        """
        clone_path = Path(mount_path)

        # Git clone -- use git rev-parse
        git_dir = clone_path / ".git"
        if git_dir.is_dir():
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "rev-parse", "HEAD",
                    cwd=str(clone_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                if proc.returncode == 0:
                    return stdout.decode().strip()
            except Exception:
                pass

        return None
