"""Central orchestrator for CAM-PULSE.

Manages the full scan → filter → assimilate → bridge pipeline,
with daemon mode for perpetual polling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Optional

from claw.core.config import ClawConfig
from claw.db.engine import DatabaseEngine
from claw.pulse.assimilator import PulseAssimilator
from claw.pulse.models import PulseDiscovery, PulseScanResult
from claw.pulse.novelty import NoveltyFilter
from claw.pulse.scout import XScout

logger = logging.getLogger("claw.pulse.orchestrator")


class PulseOrchestrator:
    """Central brain: manages scouts, filters, assimilation, and self-improvement.

    Dependencies injected at construction:
        - XScout: X search via xAI Responses API
        - NoveltyFilter: scores discoveries against existing knowledge
        - PulseAssimilator: clones + mines discovered repos
        - Optional: PulsePRBridge for auto-enhancement queueing
    """

    def __init__(
        self,
        engine: DatabaseEngine,
        scout: XScout,
        novelty: NoveltyFilter,
        assimilator: PulseAssimilator,
        config: ClawConfig,
        pr_bridge: Optional[object] = None,
    ):
        self.engine = engine
        self.scout = scout
        self.novelty = novelty
        self.assimilator = assimilator
        self.config = config
        self.pr_bridge = pr_bridge
        self._running = False
        self._consecutive_failures = 0
        self._max_failures = 3
        self._cooldown_base_seconds = 30.0
        self._cooldown_cap_seconds = 300.0
        self._daily_cost_usd = 0.0
        self._daily_cost_reset_date = ""
        self._last_self_improve: float = 0.0

    async def run_single_scan(
        self,
        keywords: Optional[list[str]] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        target_project_id: str = "pulse-default",
        dry_run: bool = False,
    ) -> PulseScanResult:
        """One-shot: scan X → filter → assimilate → report.

        Args:
            keywords: Override config keywords.
            from_date: ISO8601 date string. Defaults to today.
            to_date: ISO8601 date string. Defaults to today.
            target_project_id: Project ID for storing findings.
            dry_run: If True, scan and filter but skip assimilation.

        Returns:
            PulseScanResult with counts and any errors.
        """
        scan_id = str(uuid.uuid4())[:8]
        result = PulseScanResult(
            scan_id=scan_id,
            keywords_used=keywords or self.config.pulse.keywords,
        )

        # Log scan start
        await self._log_scan_start(scan_id, result.keywords_used)

        try:
            # 1. Scan X for GitHub repos
            logger.info("PULSE scan %s: searching X...", scan_id)
            discoveries = await self.scout.scan(
                keywords=keywords,
                from_date=from_date,
                to_date=to_date,
            )
            result.discoveries = discoveries
            logger.info("PULSE scan %s: found %d repos", scan_id, len(discoveries))

            if not discoveries:
                await self._log_scan_complete(scan_id, result)
                return result

            # 2. Novelty filter
            logger.info("PULSE scan %s: filtering for novelty...", scan_id)
            novel = await self.novelty.filter_discoveries(discoveries)
            result.novel_count = len(novel)
            result.skipped_count = len(discoveries) - len(novel)
            logger.info(
                "PULSE scan %s: %d novel, %d skipped",
                scan_id, len(novel), result.skipped_count,
            )

            if dry_run:
                logger.info("PULSE scan %s: dry run — skipping assimilation", scan_id)
                await self._log_scan_complete(scan_id, result)
                return result

            # 3. Assimilate novel discoveries
            if self.config.pulse.auto_mine:
                for disc in novel[:self.config.pulse.max_repos_per_scan]:
                    try:
                        # Save discovery to DB first
                        await self.assimilator.save_discovery(disc)

                        # Mine the repo
                        assim_result = await self.assimilator.assimilate(
                            disc, target_project_id
                        )
                        if assim_result.success:
                            result.assimilated_count += 1

                            # 4. PR bridge: queue high-novelty for enhancement
                            if self.pr_bridge and hasattr(self.pr_bridge, "evaluate_for_enhancement"):
                                await self.pr_bridge.evaluate_for_enhancement(disc)
                        else:
                            result.failed_count += 1
                            if assim_result.error:
                                result.errors.append(
                                    f"{disc.canonical_url}: {assim_result.error}"
                                )
                    except Exception as e:
                        result.failed_count += 1
                        result.errors.append(f"{disc.canonical_url}: {e}")
                        logger.error("Assimilation error for %s: %s", disc.canonical_url, e)
            else:
                # Save discoveries without mining
                for disc in novel:
                    await self.assimilator.save_discovery(disc)

            # Reset circuit breaker on success
            self._consecutive_failures = 0

        except Exception as e:
            self._consecutive_failures += 1
            result.errors.append(str(e))
            logger.error("PULSE scan %s failed: %s", scan_id, e)

        await self._log_scan_complete(scan_id, result)
        return result

    async def run_daemon(
        self,
        target_project_id: str = "pulse-default",
    ) -> None:
        """Perpetual polling loop with configurable interval.

        Runs until stopped via stop() or KeyboardInterrupt.
        Implements:
        - Configurable poll interval
        - Budget gate (max_cost_per_day_usd)
        - Circuit breaker with exponential backoff
        """
        self._running = True
        interval = self.config.pulse.poll_interval_minutes * 60

        logger.info(
            "PULSE daemon starting: interval=%dm, budget=$%.2f/day",
            self.config.pulse.poll_interval_minutes,
            self.config.pulse.max_cost_per_day_usd,
        )

        while self._running:
            # Budget gate
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            if today != self._daily_cost_reset_date:
                self._daily_cost_usd = 0.0
                self._daily_cost_reset_date = today

            if self._daily_cost_usd >= self.config.pulse.max_cost_per_day_usd:
                logger.warning(
                    "Daily budget exhausted ($%.2f >= $%.2f) — sleeping until tomorrow",
                    self._daily_cost_usd,
                    self.config.pulse.max_cost_per_day_usd,
                )
                await asyncio.sleep(3600)  # Check again in 1 hour
                continue

            # Circuit breaker
            if self._consecutive_failures >= self._max_failures:
                cooldown = min(
                    self._cooldown_base_seconds * self._consecutive_failures,
                    self._cooldown_cap_seconds,
                )
                logger.warning(
                    "Circuit breaker open (%d failures) — cooling down %.0fs",
                    self._consecutive_failures,
                    cooldown,
                )
                await asyncio.sleep(cooldown)

            # Run scan
            try:
                result = await self.run_single_scan(
                    target_project_id=target_project_id,
                )
                self._daily_cost_usd += result.cost_usd

                logger.info(
                    "PULSE daemon scan complete: %d discovered, %d novel, %d assimilated, %d failed",
                    len(result.discoveries),
                    result.novel_count,
                    result.assimilated_count,
                    result.failed_count,
                )
            except Exception as e:
                logger.error("PULSE daemon scan error: %s", e)

            # Self-improvement check
            self_improve_interval = self.config.pulse.self_improve_interval_hours * 3600
            if (time.monotonic() - self._last_self_improve) >= self_improve_interval:
                await self._self_improve()

            # Sleep until next scan
            if self._running:
                await asyncio.sleep(interval)

    async def _self_improve(self) -> None:
        """Mine CAM-PULSE's own source for knowledge capture.

        Does NOT auto-execute changes — only captures findings as
        methodologies with source_repo='cam-pulse-self'.
        """
        from pathlib import Path

        pulse_src = Path(__file__).parent
        if not pulse_src.exists():
            return

        try:
            logger.info("PULSE self-improvement: mining own source...")
            mine_result = await self.assimilator.miner.mine_repo(
                repo_path=pulse_src.parent,  # src/claw
                repo_name="cam-pulse-self",
                target_project_id="pulse-self-improve",
            )
            self._last_self_improve = time.monotonic()

            if mine_result.findings:
                logger.info(
                    "PULSE self-improvement: %d findings, %d methodologies",
                    len(mine_result.findings),
                    len(mine_result.methodology_ids),
                )
                # Log in governance_log
                await self.engine.execute(
                    """INSERT INTO governance_log (id, action_type, details)
                       VALUES (?, 'pulse_self_improve', ?)""",
                    [
                        str(uuid.uuid4()),
                        json.dumps({
                            "findings": len(mine_result.findings),
                            "methodology_ids": mine_result.methodology_ids,
                        }),
                    ],
                )
            else:
                logger.info("PULSE self-improvement: no new findings")

        except Exception as e:
            logger.warning("PULSE self-improvement failed: %s", e)
            self._last_self_improve = time.monotonic()  # Don't retry immediately

    def stop(self) -> None:
        """Signal the daemon to stop after the current scan."""
        self._running = False
        logger.info("PULSE daemon stop requested")

    def build_scan_report(self, result: PulseScanResult) -> str:
        """Format human-readable scan report."""
        lines = [
            f"=== PULSE Scan Report [{result.scan_id}] ===",
            f"Keywords: {', '.join(result.keywords_used)}",
            f"Discovered: {len(result.discoveries)}",
            f"Novel: {result.novel_count}",
            f"Assimilated: {result.assimilated_count}",
            f"Skipped: {result.skipped_count}",
            f"Failed: {result.failed_count}",
        ]

        if result.errors:
            lines.append(f"Errors: {len(result.errors)}")
            for err in result.errors[:5]:
                lines.append(f"  - {err[:100]}")

        if result.discoveries:
            lines.append("")
            lines.append("Discoveries:")
            for disc in result.discoveries[:20]:
                status = "novel" if disc.novelty_score >= self.config.pulse.novelty_threshold else "skip"
                lines.append(
                    f"  [{status}] {disc.canonical_url} "
                    f"(score={disc.novelty_score:.2f}, kw={','.join(disc.keywords_matched)})"
                )

        return "\n".join(lines)

    async def _log_scan_start(self, scan_id: str, keywords: list[str]) -> None:
        """Log scan session start to pulse_scan_log."""
        await self.engine.execute(
            """INSERT INTO pulse_scan_log (id, keywords)
               VALUES (?, ?)""",
            [scan_id, json.dumps(keywords)],
        )

    async def _log_scan_complete(
        self, scan_id: str, result: PulseScanResult
    ) -> None:
        """Update pulse_scan_log with scan results."""
        await self.engine.execute(
            """UPDATE pulse_scan_log
               SET completed_at = ?,
                   repos_discovered = ?,
                   repos_novel = ?,
                   repos_assimilated = ?,
                   cost_usd = ?,
                   tokens_used = ?,
                   error_detail = ?
               WHERE id = ?""",
            [
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                len(result.discoveries),
                result.novel_count,
                result.assimilated_count,
                result.cost_usd,
                result.tokens_used,
                json.dumps(result.errors) if result.errors else None,
                scan_id,
            ],
        )
