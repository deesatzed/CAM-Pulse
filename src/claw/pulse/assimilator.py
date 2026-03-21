"""Assimilation pipeline for CAM-PULSE discoveries.

Clones discovered repos, runs them through RepoMiner, and stores
findings in claw.db via the existing memory pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from claw.core.config import ClawConfig
from claw.db.engine import DatabaseEngine
from claw.miner import RepoMiner, RepoMiningResult
from claw.pulse.models import AssimilationResult, PulseDiscovery

logger = logging.getLogger("claw.pulse.assimilator")


class PulseAssimilator:
    """Clones and mines discovered repos, stores results in claw.db."""

    def __init__(
        self,
        engine: DatabaseEngine,
        miner: RepoMiner,
        config: ClawConfig,
    ):
        self.engine = engine
        self.miner = miner
        self.config = config
        self._workspace = Path(config.pulse.clone_workspace)

    async def assimilate(
        self,
        discovery: PulseDiscovery,
        target_project_id: str,
    ) -> AssimilationResult:
        """Clone → mine → store → update status.

        Args:
            discovery: The PulseDiscovery to assimilate.
            target_project_id: Project ID for storing findings.

        Returns:
            AssimilationResult with success status and methodology IDs.
        """
        result = AssimilationResult(discovery=discovery)

        # Update status to 'cloning'
        await self._update_discovery_status(discovery.canonical_url, "cloning")

        clone_path: Optional[Path] = None
        try:
            # 1. Clone
            clone_path = await self._clone_repo(discovery.canonical_url)

            # Update status to 'mining'
            await self._update_discovery_status(discovery.canonical_url, "mining")

            # 2. Mine via existing RepoMiner
            repo_name = self._repo_name_from_url(discovery.canonical_url)
            mine_result: RepoMiningResult = await self.miner.mine_repo(
                repo_path=clone_path,
                repo_name=repo_name,
                target_project_id=target_project_id,
            )

            if mine_result.error:
                result.error = mine_result.error
                await self._update_discovery_status(
                    discovery.canonical_url, "failed", error=mine_result.error
                )
                return result

            # 3. Record results
            result.success = True
            result.methodology_ids = mine_result.methodology_ids
            result.findings_count = len(mine_result.findings)

            # 4. Update pulse_discoveries with results
            await self._update_discovery_assimilated(
                discovery.canonical_url,
                methodology_ids=mine_result.methodology_ids,
                mine_result_summary={
                    "findings": len(mine_result.findings),
                    "files_analyzed": mine_result.files_analyzed,
                    "tokens_used": mine_result.tokens_used,
                    "duration_seconds": round(mine_result.duration_seconds, 2),
                },
            )

            logger.info(
                "Assimilated %s: %d findings, %d methodologies",
                discovery.canonical_url,
                len(mine_result.findings),
                len(mine_result.methodology_ids),
            )

        except Exception as e:
            result.error = str(e)
            await self._update_discovery_status(
                discovery.canonical_url, "failed", error=str(e)
            )
            logger.error("Assimilation failed for %s: %s", discovery.canonical_url, e)

        finally:
            # 5. Cleanup clone
            if clone_path and clone_path.exists():
                await self._cleanup_clone(clone_path)

        return result

    async def _clone_repo(self, canonical_url: str) -> Path:
        """Shallow clone (--depth 1) to workspace directory."""
        self._workspace.mkdir(parents=True, exist_ok=True)

        repo_name = self._repo_name_from_url(canonical_url)
        clone_dir = self._workspace / f"{repo_name}_{uuid.uuid4().hex[:8]}"

        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", canonical_url, str(clone_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode().strip()
            raise RuntimeError(f"git clone failed: {error_msg}")

        logger.info("Cloned %s to %s", canonical_url, clone_dir)
        return clone_dir

    async def _cleanup_clone(self, clone_path: Path) -> None:
        """Remove clone directory after mining."""
        try:
            shutil.rmtree(clone_path)
            logger.debug("Cleaned up clone: %s", clone_path)
        except Exception as e:
            logger.warning("Failed to clean up clone %s: %s", clone_path, e)

    async def _update_discovery_status(
        self,
        canonical_url: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Update the status of a pulse_discovery record."""
        if error:
            await self.engine.execute(
                "UPDATE pulse_discoveries SET status = ?, error_detail = ? WHERE canonical_url = ?",
                [status, error[:1000], canonical_url],
            )
        else:
            await self.engine.execute(
                "UPDATE pulse_discoveries SET status = ? WHERE canonical_url = ?",
                [status, canonical_url],
            )

    async def _update_discovery_assimilated(
        self,
        canonical_url: str,
        methodology_ids: list[str],
        mine_result_summary: dict,
    ) -> None:
        """Mark discovery as assimilated with mining results."""
        await self.engine.execute(
            """UPDATE pulse_discoveries
               SET status = 'assimilated',
                   methodology_ids = ?,
                   mine_result = ?
               WHERE canonical_url = ?""",
            [
                json.dumps(methodology_ids),
                json.dumps(mine_result_summary),
                canonical_url,
            ],
        )

    async def save_discovery(self, discovery: PulseDiscovery) -> None:
        """Persist a PulseDiscovery to the pulse_discoveries table."""
        disc_id = str(uuid.uuid4())
        await self.engine.execute(
            """INSERT OR IGNORE INTO pulse_discoveries
               (id, github_url, canonical_url, x_post_url, x_post_text,
                x_author_handle, novelty_score, scan_id, keywords_matched)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                disc_id,
                discovery.github_url,
                discovery.canonical_url,
                discovery.x_post_url,
                discovery.x_post_text[:500] if discovery.x_post_text else "",
                discovery.x_author_handle,
                discovery.novelty_score,
                discovery.scan_id,
                json.dumps(discovery.keywords_matched),
            ],
        )

    @staticmethod
    def _repo_name_from_url(canonical_url: str) -> str:
        """Extract owner_repo name from canonical URL."""
        # https://github.com/owner/repo -> owner_repo
        path = canonical_url.replace("https://github.com/", "")
        return path.replace("/", "_")
