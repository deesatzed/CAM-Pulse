"""PR Bridge for CAM-PULSE.

Evaluates high-novelty discoveries for enhancement and queues them
into the fleet + task system for automated improvement.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Optional

from claw.core.config import PulseConfig
from claw.db.engine import DatabaseEngine
from claw.fleet import FleetOrchestrator
from claw.pulse.models import PulseDiscovery

logger = logging.getLogger("claw.pulse.pr_bridge")


class PulsePRBridge:
    """Queues high-novelty discoveries for enhancement via the fleet system."""

    def __init__(
        self,
        engine: DatabaseEngine,
        fleet: FleetOrchestrator,
        config: PulseConfig,
    ):
        self.engine = engine
        self.fleet = fleet
        self.config = config

    async def evaluate_for_enhancement(
        self,
        discovery: PulseDiscovery,
        clone_path: Optional[str] = None,
    ) -> bool:
        """If novelty_score exceeds enhance threshold, register in fleet and queue task.

        Args:
            discovery: The assimilated PulseDiscovery.
            clone_path: Path to cloned repo (if still available).

        Returns:
            True if the discovery was queued for enhancement.
        """
        if discovery.novelty_score < self.config.enhance_novelty_threshold:
            logger.debug(
                "Below enhance threshold (%.2f < %.2f): %s",
                discovery.novelty_score,
                self.config.enhance_novelty_threshold,
                discovery.canonical_url,
            )
            return False

        if not self.config.auto_queue_enhance:
            logger.info(
                "auto_queue_enhance disabled — skipping %s (score=%.2f)",
                discovery.canonical_url,
                discovery.novelty_score,
            )
            return False

        repo_path = clone_path or discovery.canonical_url
        repo_name = self._repo_name_from_url(discovery.canonical_url)

        try:
            # Register in fleet
            repo_id = await self.fleet.register_repo(
                repo_path=repo_path,
                repo_name=repo_name,
                priority=discovery.novelty_score,
            )

            # Create enhancement task
            task_id = str(uuid.uuid4())
            await self.engine.execute(
                """INSERT INTO tasks
                   (id, project_id, task_type, title, description, status, priority)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    task_id,
                    "",  # No project yet
                    "pulse_enhance",
                    f"Enhance {repo_name} (pulse discovery)",
                    (
                        f"High-novelty discovery from X (score={discovery.novelty_score:.2f}).\n"
                        f"URL: {discovery.canonical_url}\n"
                        f"Keywords: {', '.join(discovery.keywords_matched)}\n"
                        f"Fleet repo ID: {repo_id}"
                    ),
                    "PENDING",
                    discovery.novelty_score,
                ],
            )

            # Update discovery status
            await self.engine.execute(
                "UPDATE pulse_discoveries SET status = 'queued_enhance' WHERE canonical_url = ?",
                [discovery.canonical_url],
            )

            logger.info(
                "Queued for enhancement: %s (score=%.2f, task=%s)",
                discovery.canonical_url,
                discovery.novelty_score,
                task_id,
            )
            return True

        except Exception as e:
            logger.error(
                "Failed to queue %s for enhancement: %s",
                discovery.canonical_url, e,
            )
            return False

    @staticmethod
    def _repo_name_from_url(canonical_url: str) -> str:
        """Extract owner_repo name from canonical URL."""
        path = canonical_url.replace("https://github.com/", "")
        return path.replace("/", "_")
