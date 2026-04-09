"""Memory governance — quotas, pruning, GC, dedup, and monitoring.

Central governor that orchestrates all memory hygiene operations.
Called periodically (every N cycles) and on startup to keep the
methodology store lean and free of dead weight.

Operations (in order during a sweep):
1. Lifecycle sweep — run_periodic_sweep() from lifecycle.py
2. Garbage collect dead methodologies — remove from all 3 stores
3. Enforce quota — cull lowest-fitness if over limit
4. Prune episodes — apply retention policy
5. Log storage stats — audit trail in governance_log
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from claw.core.config import GovernanceConfig
from claw.db.repository import Repository
from claw.memory.cag_staleness import maybe_mark_cag_stale

logger = logging.getLogger("claw.memory.governance")


@dataclass
class StorageStats:
    """Memory system storage statistics."""
    total_methodologies: int = 0
    by_state: dict[str, int] = field(default_factory=dict)
    total_embeddings: int = 0
    total_episodes: int = 0
    db_size_bytes: int = 0
    quota_limit: int = 0
    quota_used_pct: float = 0.0


@dataclass
class GovernanceReport:
    """Results of a governance sweep."""
    dead_collected: int = 0
    quota_culled: int = 0
    episodes_pruned: int = 0
    lifecycle_transitions: dict[str, int] = field(default_factory=dict)
    storage_stats: Optional[StorageStats] = None
    duplicates_blocked: int = 0
    sweep_duration_seconds: float = 0.0
    health_score: int = 0
    health_breakdown: dict[str, int] = field(default_factory=dict)


class MemoryGovernor:
    """Central memory governance: quotas, pruning, GC, monitoring.

    Dependencies:
        repository: Database access.
        config: GovernanceConfig for thresholds.
    """

    def __init__(
        self,
        repository: Repository,
        config: Optional[GovernanceConfig] = None,
        claw_config: Optional[object] = None,
    ):
        self.repository = repository
        self.config = config or GovernanceConfig()
        self._cycle_count: int = 0
        self._duplicates_blocked: int = 0
        self.claw_config = claw_config

    async def run_full_sweep(self) -> GovernanceReport:
        """Execute all governance operations in sequence.

        Order matters:
        1. Lifecycle sweep (transition time-based states)
        2. Garbage collect dead methodologies
        3. Enforce quotas (if over limit, cull lowest-fitness)
        4. Prune episodic memory
        5. Compute and log storage stats
        """
        start = time.monotonic()
        report = GovernanceReport()

        # 1. Lifecycle sweep
        from claw.memory.lifecycle import run_periodic_sweep
        transitions = await run_periodic_sweep(self.repository, config=self.claw_config)
        report.lifecycle_transitions = transitions

        # 2. Garbage collect dead
        if self.config.gc_dead_on_sweep:
            report.dead_collected = await self.garbage_collect_dead()

        # 2.5. Detect contradictions (after lifecycle, before quota)
        try:
            contradictions = await self.detect_contradictions()
            if contradictions:
                logger.info("Found %d new contradictions during sweep", len(contradictions))
        except Exception as exc:
            logger.warning("Contradiction detection failed: %s", exc)

        # 3. Enforce quota
        report.quota_culled = await self.enforce_methodology_quota()

        # 4. Prune episodes
        report.episodes_pruned = await self._prune_episodes()

        # 5. Storage stats
        report.storage_stats = await self.get_storage_stats()
        report.duplicates_blocked = self._duplicates_blocked
        report.sweep_duration_seconds = time.monotonic() - start

        # Log to governance_log
        await self.repository.log_governance_action(
            action_type="sweep",
            details={
                "dead_collected": report.dead_collected,
                "quota_culled": report.quota_culled,
                "episodes_pruned": report.episodes_pruned,
                "lifecycle_transitions": report.lifecycle_transitions,
                "duration_seconds": round(report.sweep_duration_seconds, 3),
            },
        )

        logger.info(
            "Governance sweep complete: gc=%d, culled=%d, episodes=%d, transitions=%s (%.2fs)",
            report.dead_collected,
            report.quota_culled,
            report.episodes_pruned,
            report.lifecycle_transitions or "none",
            report.sweep_duration_seconds,
        )
        mutations = report.dead_collected + report.quota_culled + sum(report.lifecycle_transitions.values())
        if mutations > 0:
            maybe_mark_cag_stale(self.claw_config)
        return report

    async def garbage_collect_dead(self) -> int:
        """Delete dead methodologies from DB, FTS5, and sqlite-vec.

        Logs each deletion to governance_log before removing.
        """
        dead = await self.repository.get_dead_methodologies(limit=500)
        if not dead:
            return 0

        deleted = 0
        for m in dead:
            await self.repository.log_governance_action(
                action_type="gc_dead",
                methodology_id=m.id,
                details={
                    "problem_description": m.problem_description[:200],
                    "lifecycle_state": m.lifecycle_state,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                },
            )
            success = await self.repository.delete_methodology(m.id)
            if success:
                deleted += 1

        if deleted > 0:
            logger.info("Garbage collected %d dead methodologies", deleted)
        return deleted

    async def enforce_methodology_quota(self) -> int:
        """If total active methodologies exceed quota, cull lowest-fitness.

        Cull order: dormant, declining, embryonic.
        Never culls thriving or viable methodologies.
        """
        active_count = await self.repository.count_active_methodologies()
        quota = self.config.max_methodologies

        if quota <= 0 or active_count <= quota:
            # Check warning threshold (only when quota is set)
            if quota > 0 and active_count >= quota * self.config.quota_warning_pct:
                logger.warning(
                    "Methodology quota warning: %d/%d (%.0f%%)",
                    active_count, quota, (active_count / quota) * 100,
                )
            return 0

        # Need to cull (active_count - quota) methodologies
        to_cull = active_count - quota
        logger.warning(
            "Methodology quota exceeded: %d/%d — culling %d lowest-fitness",
            active_count, quota, to_cull,
        )

        # Get candidates in cull order (dormant, declining, embryonic)
        candidates = await self.repository.get_lowest_fitness_methodologies(
            states=["dormant", "declining", "embryonic"],
            limit=to_cull,
        )

        culled = 0
        for m in candidates:
            if culled >= to_cull:
                break
            await self.repository.log_governance_action(
                action_type="quota_cull",
                methodology_id=m.id,
                details={
                    "problem_description": m.problem_description[:200],
                    "lifecycle_state": m.lifecycle_state,
                    "fitness": m.fitness_vector.get("total", 0.0) if m.fitness_vector else 0.0,
                },
            )
            success = await self.repository.delete_methodology(m.id)
            if success:
                culled += 1

        if culled < to_cull:
            logger.warning(
                "Could only cull %d/%d — remaining %d are thriving/viable (protected)",
                culled, to_cull, to_cull - culled,
            )
        return culled

    async def check_pre_save_dedup(
        self,
        problem_description: str,
        embedding: Optional[list[float]] = None,
        similarity_threshold: Optional[float] = None,
    ) -> tuple[bool, Optional[str]]:
        """Check if a methodology should be saved or is a near-duplicate.

        Called BEFORE save_solution() to catch duplicates at insertion time.

        Returns:
            (should_save, existing_id). If should_save is False,
            existing_id is the matching methodology that already covers this.
        """
        if not self.config.dedup_enabled:
            return True, None

        if embedding is None:
            return True, None

        threshold = similarity_threshold or self.config.dedup_similarity_threshold

        try:
            similar_pairs = await self.repository.find_similar_methodologies(
                embedding=embedding, limit=5,
            )
            for existing, similarity in similar_pairs:
                if similarity >= threshold:
                    # Skip dead/dormant — they don't count as duplicates
                    if existing.lifecycle_state in ("dead", "dormant"):
                        continue
                    self._duplicates_blocked += 1
                    logger.info(
                        "Pre-save dedup: blocked (sim=%.3f >= %.3f) — existing=%s",
                        similarity, threshold, existing.id,
                    )
                    await self.repository.log_governance_action(
                        action_type="dedup_block",
                        methodology_id=existing.id,
                        details={
                            "blocked_description": problem_description[:200],
                            "similarity": round(similarity, 4),
                            "threshold": threshold,
                        },
                    )
                    return False, existing.id
        except Exception as e:
            logger.warning("Pre-save dedup check failed (allowing save): %s", e)

        return True, None

    async def get_storage_stats(self) -> StorageStats:
        """Compute storage statistics for monitoring."""
        by_state = await self.repository.count_methodologies_by_state()
        total = sum(by_state.values())
        active = total - by_state.get("dead", 0)

        episode_count = await self.repository.count_episodes()
        db_size = await self.repository.get_db_size_bytes()

        quota = self.config.max_methodologies
        pct = (active / quota * 100) if quota > 0 else 0.0

        stats = StorageStats(
            total_methodologies=total,
            by_state=by_state,
            total_episodes=episode_count,
            db_size_bytes=db_size,
            quota_limit=quota,
            quota_used_pct=round(pct, 1),
        )

        # DB size warning
        max_bytes = self.config.max_db_size_mb * 1024 * 1024
        if db_size > max_bytes:
            logger.warning(
                "DB size exceeds limit: %d MB > %d MB",
                db_size // (1024 * 1024),
                self.config.max_db_size_mb,
            )

        return stats

    async def maybe_run_sweep(self) -> Optional[GovernanceReport]:
        """Conditionally run governance sweep based on cycle count.

        Called after every MicroClaw cycle. Runs full sweep every
        N cycles (configured via sweep_interval_cycles).
        """
        self._cycle_count += 1
        if self._cycle_count % self.config.sweep_interval_cycles != 0:
            return None
        return await self.run_full_sweep()

    async def compute_health_score(self) -> dict:
        """Compute a 0-100 KB health score with 5-factor breakdown.

        Factors (max points):
            lifecycle  (25): ratio of viable+thriving to total
            freshness  (20): median freshness score across all active
            provenance (10): % of methodologies with source: tags
            dedup      (15): 1 - near_duplicate_ratio (blocked/total)
            coverage   (30): number of distinct categories / expected count

        Returns dict with 'score' (int 0-100) and 'breakdown' dict.
        """
        import json as _json

        by_state = await self.repository.count_methodologies_by_state()
        total = sum(by_state.values())

        if total == 0:
            return {
                "score": 0,
                "breakdown": {
                    "lifecycle": 0,
                    "freshness": 0,
                    "provenance": 0,
                    "dedup": 0,
                    "coverage": 0,
                },
            }

        # Factor 1: Lifecycle health (25 pts) — viable + thriving as fraction of total
        viable_thriving = by_state.get("viable", 0) + by_state.get("thriving", 0)
        lifecycle = round(viable_thriving / total * 25)

        # Factor 2: Freshness (20 pts) — compute median freshness from fitness vectors
        from datetime import UTC, datetime
        import math

        now = datetime.now(UTC)
        freshness_values: list[float] = []
        try:
            rows = await self.repository.engine.fetch_all(
                "SELECT created_at, fitness_vector FROM methodologies "
                "WHERE lifecycle_state NOT IN ('dead')"
            )
            for r in rows:
                fv = r.get("fitness_vector") or "{}"
                try:
                    vec = _json.loads(fv) if isinstance(fv, str) else fv
                    if "freshness" in vec:
                        freshness_values.append(float(vec["freshness"]))
                except (TypeError, ValueError, _json.JSONDecodeError):
                    pass
        except Exception:
            pass

        if freshness_values:
            freshness_values.sort()
            mid = len(freshness_values) // 2
            median_f = freshness_values[mid]
            freshness = round(median_f * 20)
        else:
            freshness = 0

        # Factor 3: Provenance (10 pts) — % with source: tag
        source_count = 0
        try:
            rows = await self.repository.engine.fetch_all(
                "SELECT tags FROM methodologies WHERE lifecycle_state NOT IN ('dead') AND tags IS NOT NULL"
            )
            for r in rows:
                raw = r.get("tags", "[]")
                try:
                    tags = _json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, _json.JSONDecodeError):
                    tags = []
                if any(isinstance(t, str) and t.startswith("source:") for t in tags):
                    source_count += 1
        except Exception:
            pass
        active_total = total - by_state.get("dead", 0)
        provenance = round(source_count / max(1, active_total) * 10) if active_total > 0 else 0

        # Factor 4: Dedup quality (15 pts) — 1 - (blocked / total)
        near_dup_ratio = self._duplicates_blocked / max(1, active_total)
        dedup = round((1.0 - min(1.0, near_dup_ratio)) * 15)

        # Factor 5: Coverage (30 pts) — distinct categories / expected (10 categories)
        cat_set: set[str] = set()
        try:
            rows = await self.repository.engine.fetch_all(
                "SELECT tags FROM methodologies WHERE lifecycle_state NOT IN ('dead') AND tags IS NOT NULL"
            )
            for r in rows:
                raw = r.get("tags", "[]")
                try:
                    tags = _json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, _json.JSONDecodeError):
                    tags = []
                for t in tags:
                    if isinstance(t, str) and t.startswith("category:"):
                        cat_set.add(t.split(":", 1)[1])
        except Exception:
            pass
        expected_categories = 10
        coverage = min(30, round(len(cat_set) / expected_categories * 30))

        score = lifecycle + freshness + provenance + dedup + coverage
        score = max(0, min(100, score))

        return {
            "score": score,
            "breakdown": {
                "lifecycle": lifecycle,
                "freshness": freshness,
                "provenance": provenance,
                "dedup": dedup,
                "coverage": coverage,
            },
        }

    async def detect_contradictions(self) -> list[dict]:
        """Detect contradictory methodology pairs from viable+thriving methodologies.

        A contradiction is when two methodologies address the same problem
        (problem_similarity > 0.80) but propose different solutions
        (solution_divergence > 0.70).

        Detected pairs are persisted into the methodology_contradictions table
        and optionally into methodology_links as 'contradicts' edges.

        Returns list of newly detected contradiction dicts.
        """
        import json as _json
        import uuid as _uuid

        # Fetch viable+thriving methodologies with embeddings
        try:
            rows = await self.repository.engine.fetch_all(
                "SELECT m.id, m.problem_description, m.solution_code, "
                "e.embedding AS problem_embedding "
                "FROM methodologies m "
                "LEFT JOIN methodology_embeddings e ON m.id = e.methodology_id "
                "WHERE m.lifecycle_state IN ('viable', 'thriving') "
                "ORDER BY m.retrieval_count DESC LIMIT 100"
            )
        except Exception as exc:
            logger.warning("detect_contradictions: query failed: %s", exc)
            return []

        if len(rows) < 2:
            return []

        # Build embedding lookup
        import struct

        items: list[dict] = []
        for r in rows:
            emb_raw = r.get("problem_embedding")
            if emb_raw is None:
                continue
            # sqlite-vec stores embeddings as binary blobs
            try:
                if isinstance(emb_raw, bytes):
                    dim = len(emb_raw) // 4
                    emb = list(struct.unpack(f'{dim}f', emb_raw))
                elif isinstance(emb_raw, list):
                    emb = emb_raw
                else:
                    continue
            except Exception:
                continue
            items.append({
                "id": r["id"],
                "problem": r["problem_description"] or "",
                "solution": r["solution_code"] or "",
                "embedding": emb,
            })

        if len(items) < 2:
            return []

        # Pairwise comparison (capped at 100 → max 4950 pairs)
        def _cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            mag_a = sum(x * x for x in a) ** 0.5
            mag_b = sum(x * x for x in b) ** 0.5
            if mag_a == 0 or mag_b == 0:
                return 0.0
            return dot / (mag_a * mag_b)

        def _text_similarity(a: str, b: str) -> float:
            """Jaccard similarity on word tokens."""
            words_a = set(a.lower().split())
            words_b = set(b.lower().split())
            if not words_a or not words_b:
                return 0.0
            return len(words_a & words_b) / len(words_a | words_b)

        new_contradictions: list[dict] = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                problem_sim = _cosine(a["embedding"], b["embedding"])
                if problem_sim <= 0.80:
                    continue
                # Solution divergence: 1 - text similarity
                sol_sim = _text_similarity(a["solution"], b["solution"])
                sol_div = 1.0 - sol_sim
                if sol_div <= 0.70:
                    continue

                # Sort IDs for stable UNIQUE constraint
                id_a, id_b = sorted([a["id"], b["id"]])

                # Check if already exists
                try:
                    existing = await self.repository.engine.fetch_one(
                        "SELECT id FROM methodology_contradictions "
                        "WHERE methodology_a_id = ? AND methodology_b_id = ?",
                        [id_a, id_b],
                    )
                    if existing:
                        continue
                except Exception:
                    pass

                contradiction_id = str(_uuid.uuid4())
                try:
                    await self.repository.engine.execute(
                        "INSERT INTO methodology_contradictions "
                        "(id, methodology_a_id, methodology_b_id, problem_similarity, solution_divergence) "
                        "VALUES (?, ?, ?, ?, ?)",
                        [contradiction_id, id_a, id_b, round(problem_sim, 4), round(sol_div, 4)],
                    )
                    new_contradictions.append({
                        "id": contradiction_id,
                        "methodology_a_id": id_a,
                        "methodology_b_id": id_b,
                        "problem_similarity": round(problem_sim, 4),
                        "solution_divergence": round(sol_div, 4),
                    })

                    # Also persist as methodology_links edge
                    link_id = str(_uuid.uuid4())
                    try:
                        await self.repository.engine.execute(
                            "INSERT OR REPLACE INTO methodology_links "
                            "(id, source_id, target_id, link_type, strength) "
                            "VALUES (?, ?, ?, 'contradicts', ?)",
                            [link_id, id_a, id_b, round(problem_sim, 4)],
                        )
                    except Exception as exc:
                        logger.debug("Failed to persist contradiction edge: %s", exc)

                except Exception as exc:
                    logger.warning("Failed to insert contradiction: %s", exc)

        if new_contradictions:
            logger.info("Detected %d new contradiction pairs", len(new_contradictions))

        return new_contradictions

    async def get_methodology_neighborhood(
        self, methodology_id: str, max_hops: int = 1,
    ) -> dict:
        """Get the 1-hop entity relationship graph around a methodology.

        Returns {nodes: [{id, title, lifecycle_state}], edges: [{source, target, type, strength}]}.
        """
        import json as _json

        # Get edges where this methodology is source or target
        try:
            rows = await self.repository.engine.fetch_all(
                "SELECT source_id, target_id, link_type, strength "
                "FROM methodology_links "
                "WHERE source_id = ? OR target_id = ?",
                [methodology_id, methodology_id],
            )
        except Exception:
            rows = []

        # Collect neighbor IDs
        neighbor_ids: set[str] = set()
        edges: list[dict] = []
        for r in rows:
            edges.append({
                "source": r["source_id"],
                "target": r["target_id"],
                "type": r["link_type"],
                "strength": r["strength"],
            })
            neighbor_ids.add(r["source_id"])
            neighbor_ids.add(r["target_id"])

        # Include self
        neighbor_ids.add(methodology_id)

        # Get node metadata
        nodes: list[dict] = []
        for nid in neighbor_ids:
            try:
                row = await self.repository.engine.fetch_one(
                    "SELECT id, problem_description, lifecycle_state FROM methodologies WHERE id = ?",
                    [nid],
                )
                if row:
                    nodes.append({
                        "id": row["id"],
                        "title": (row["problem_description"] or "")[:100],
                        "lifecycle_state": row["lifecycle_state"],
                    })
            except Exception:
                nodes.append({"id": nid, "title": "", "lifecycle_state": "unknown"})

        return {"nodes": nodes, "edges": edges}

    async def _prune_episodes(self) -> int:
        """Prune old episodes using the configured retention days."""
        from datetime import UTC, datetime, timedelta
        cutoff = (
            datetime.now(UTC) - timedelta(days=self.config.episodic_retention_days)
        ).isoformat()
        return await self.repository.delete_old_episodes(cutoff)
