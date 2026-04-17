"""Semantic memory for solution persistence and retrieval.

Wraps Repository and EmbeddingEngine to provide a higher-level API
for saving solutions (with automatic embedding) and finding similar
past solutions via hybrid search.

This is the persistence layer for CLAW's accumulated knowledge --
every successfully completed task saves its methodology here so future
tasks can benefit from past experience.

MEE extensions: outcome feedback, fitness recalculation, stigmergic links,
competitive exclusion, and lifecycle transitions.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from claw.core.models import ComponentCard, ComponentCardSummary, Methodology, Task
from claw.db.embeddings import EmbeddingEngine
from claw.db.repository import Repository
from claw.memory.fitness import compute_fitness, log_fitness_change
from claw.memory.hybrid_search import HybridSearch, HybridSearchResult

logger = logging.getLogger("claw.memory.semantic")


class SemanticMemory:
    """High-level API for methodology persistence and retrieval.

    Injected dependencies:
        repository: Database access for CRUD operations.
        embedding_engine: Encodes problem descriptions to vectors.
        hybrid_search: Two-Key search for finding similar methodologies.
    """

    def __init__(
        self,
        repository: Repository,
        embedding_engine: EmbeddingEngine,
        hybrid_search: HybridSearch,
        prism_engine: Any = None,
        governance: Any = None,
    ):
        self.repository = repository
        self.embedding_engine = embedding_engine
        self.hybrid_search = hybrid_search
        self.prism_engine = prism_engine
        self.governance = governance
        # Path C Fix 2: GanglionRepositoryPool injected by factory so that
        # record_retrieval / record_outcome can route writes back to the
        # source ganglion DB when a methodology came from federation.
        self._ganglion_pool: Any = None

    def set_ganglion_pool(self, pool: Any) -> None:
        """Attach a GanglionRepositoryPool for federation write-back.

        Called by the factory after construction so SemanticMemory can
        resolve ``source_db_path`` → ganglion Repository at outcome time.
        """
        self._ganglion_pool = pool

    # Quality filter thresholds (Item 5)
    MIN_SOLUTION_LENGTH = 50
    MIN_ATTEMPTS_FOR_TRIVIAL = 1

    async def save_solution(
        self,
        problem_description: str,
        solution_code: str,
        source_task_id: Optional[str] = None,
        methodology_notes: Optional[str] = None,
        tags: Optional[list[str]] = None,
        language: Optional[str] = None,
        scope: str = "project",
        methodology_type: Optional[str] = None,
        files_affected: Optional[list[str]] = None,
    ) -> Methodology:
        """Save a solution with automatic embedding.

        Args:
            problem_description: Natural language description of the problem solved.
            solution_code: The code that solved the problem.
            source_task_id: ID of the task that produced this solution.
            methodology_notes: Optional notes about the approach.
            tags: Optional tags for filtering.
            language: Programming language of the solution.
            scope: "project" or "global" (Item 2).
            methodology_type: BUG_FIX/PATTERN/DECISION/GOTCHA (Item 3).
            files_affected: List of file paths this solution touched (Item 4).

        Returns:
            The saved Methodology model.
        """
        # Generate embedding for the problem description (async to avoid blocking event loop)
        try:
            embedding = await self.embedding_engine.async_encode(problem_description)
            logger.debug(
                "Generated embedding (%d dims) for: %s",
                len(embedding), problem_description[:50],
            )
        except Exception as e:
            logger.warning("Embedding generation failed -- saving without vector: %s", e)
            embedding = None

        # Pre-save dedup check
        if self.governance and embedding is not None:
            should_save, existing_id = await self.governance.check_pre_save_dedup(
                problem_description, embedding
            )
            if not should_save and existing_id:
                logger.info(
                    "Dedup blocked: too similar to existing %s — returning existing",
                    existing_id,
                )
                existing = await self.repository.get_methodology(existing_id)
                if existing:
                    return existing

        # Compute PRISM multi-scale representation if engine is available
        prism_data = None
        if self.prism_engine and embedding is not None:
            try:
                prism_emb = self.prism_engine.enhance(
                    embedding,
                    metadata={"lifecycle_state": "embryonic"},
                )
                prism_data = prism_emb.to_dict()
                logger.debug("PRISM embedding computed for new methodology")
            except Exception as e:
                logger.warning("PRISM computation failed -- saving without PRISM data: %s", e)

        methodology = Methodology(
            problem_description=problem_description,
            problem_embedding=embedding,
            solution_code=solution_code,
            methodology_notes=methodology_notes,
            source_task_id=source_task_id,
            tags=tags or [],
            language=language,
            scope=scope,
            methodology_type=methodology_type,
            files_affected=files_affected or [],
            lifecycle_state="embryonic",
            prism_data=prism_data,
        )

        saved = await self.repository.save_methodology(methodology)
        logger.info(
            "Saved methodology %s (scope=%s, type=%s) for: %s",
            saved.id, scope, methodology_type, problem_description[:80],
        )
        return saved

    async def save_from_task(
        self,
        task: Task,
        solution_code: str,
        methodology_notes: Optional[str] = None,
        tags: Optional[list[str]] = None,
        language: Optional[str] = None,
        files_affected: Optional[list[str]] = None,
        methodology_type: Optional[str] = None,
        scope: str = "project",
    ) -> Optional[Methodology]:
        """Save a methodology derived from a completed task.

        Applies quality filter (Item 5): only saves if the task was non-trivial
        (attempt_count >= MIN_ATTEMPTS_FOR_TRIVIAL) or the solution code exceeds
        MIN_SOLUTION_LENGTH. Returns None if filtered out.

        Args:
            task: The completed task.
            solution_code: The code that completed the task.
            methodology_notes: Optional notes about the approach.
            tags: Optional tags for filtering.
            language: Programming language of the solution.
            files_affected: File paths changed by this solution (Item 4).
            methodology_type: BUG_FIX/PATTERN/DECISION/GOTCHA (Item 3).
            scope: "project" or "global" (Item 2).

        Returns:
            The saved Methodology model, or None if quality filter rejected it.
        """
        # Quality filter (Item 5)
        if not self._passes_quality_filter(task, solution_code):
            logger.info(
                "Methodology for task '%s' filtered out (trivial, %d chars, %d attempts)",
                task.title, len(solution_code), task.attempt_count,
            )
            return None

        # Infer methodology_type from attempt history if not provided (Item 3)
        if methodology_type is None:
            methodology_type = self._infer_methodology_type(task)

        problem = f"{task.title}: {task.description}"
        return await self.save_solution(
            problem_description=problem,
            solution_code=solution_code,
            source_task_id=task.id,
            methodology_notes=methodology_notes,
            tags=tags,
            language=language,
            scope=scope,
            methodology_type=methodology_type,
            files_affected=files_affected,
        )

    def _passes_quality_filter(self, task: Task, solution_code: str) -> bool:
        """Check if a methodology passes the quality gate (Item 5).

        Saves are allowed when:
        - Task had at least MIN_ATTEMPTS_FOR_TRIVIAL attempts (non-trivial), OR
        - Solution code exceeds MIN_SOLUTION_LENGTH chars
        """
        if task.attempt_count >= self.MIN_ATTEMPTS_FOR_TRIVIAL:
            return True
        if len(solution_code) > self.MIN_SOLUTION_LENGTH:
            return True
        return False

    def _infer_methodology_type(self, task: Task) -> str:
        """Infer methodology type from task characteristics (Item 3)."""
        title_lower = task.title.lower()
        desc_lower = task.description.lower()
        combined = f"{title_lower} {desc_lower}"

        if any(kw in combined for kw in ("fix", "bug", "error", "crash", "broken", "issue")):
            return "BUG_FIX"
        if any(kw in combined for kw in ("decide", "choose", "select", "adr", "architecture")):
            return "DECISION"
        if any(kw in combined for kw in ("gotcha", "caveat", "warning", "pitfall", "trap")):
            return "GOTCHA"
        return "PATTERN"

    async def find_similar(
        self,
        query: str,
        limit: int = 3,
        language: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> list[HybridSearchResult]:
        """Find similar past methodologies using hybrid search.

        Args:
            query: Problem description or task description to search for.
            limit: Maximum number of results.
            language: Optional filter by programming language.
            tags: Optional filter by tags.

        Returns:
            List of HybridSearchResult sorted by relevance.
        """
        results = await self.hybrid_search.search(
            query=query,
            limit=limit,
            language=language,
            tags=tags,
        )
        logger.info(
            "Found %d similar methodologies for: %s",
            len(results), query[:80],
        )
        return results

    async def find_similar_with_signals(
        self,
        query: str,
        limit: int = 3,
        language: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> tuple[list[HybridSearchResult], dict[str, Any]]:
        """Find similar methodologies and aggregate retrieval confidence/conflicts."""
        results = await self.find_similar(
            query=query,
            limit=limit,
            language=language,
            tags=tags,
        )
        signals = self.hybrid_search.summarize_signals(results)
        return results, signals

    async def get_total_count(self) -> int:
        """Return the total number of non-dead methodologies."""
        return await self.repository.count_methodologies()

    async def get_thriving(
        self,
        limit: int = 3,
    ) -> list[Methodology]:
        """Return thriving methodologies ordered by fitness desc."""
        thriving = await self.repository.get_methodologies_by_state("thriving", limit=limit)
        # Sort by fitness score descending
        thriving.sort(key=lambda m: get_fitness_score_safe(m), reverse=True)
        return thriving

    async def get_by_task(self, task_id: str) -> list[Methodology]:
        """Get all methodologies saved from a specific task.

        Args:
            task_id: The source task ID.

        Returns:
            List of Methodology models linked to this task.
        """
        # Search text for the task ID reference
        all_results = await self.repository.search_methodologies_text(str(task_id), limit=20)
        return [m for m, _rank in all_results if m.source_task_id == task_id]

    # -------------------------------------------------------------------
    # CAM-SEQ: Component memory bridge
    # -------------------------------------------------------------------

    async def search_components(
        self,
        query: str,
        limit: int = 20,
        language: Optional[str] = None,
    ) -> list[ComponentCardSummary]:
        """Search component memory without changing methodology retrieval behavior."""
        return await self.repository.search_component_cards_text(
            query,
            limit=limit,
            language=language,
        )

    async def get_component(self, component_id: str) -> Optional[ComponentCard]:
        """Fetch a component card by ID."""
        return await self.repository.get_component_card(component_id)

    async def get_component_history(self, component_id: str) -> dict[str, Any]:
        """Return component packet/fit/lineage history for future planning surfaces."""
        component = await self.repository.get_component_card(component_id)
        if component is None:
            return {}
        return {
            "component": component,
            "fit_history": await self.repository.list_component_fit(component_id),
            "packet_history": await self.repository.list_packet_history_for_component(component_id),
            "lineage_components": await self.repository.list_lineage_components(
                component.receipt.lineage_id
            ),
        }

    # -------------------------------------------------------------------
    # MEE: Outcome feedback loop
    # -------------------------------------------------------------------

    async def _resolve_repository(
        self, source_db_path: Optional[str]
    ) -> Repository:
        """Return the correct Repository to write to for a given source.

        Path C Fix 2: if ``source_db_path`` points at a ganglion DB,
        return the pooled ganglion Repository so outcome writes land in
        the right place; otherwise return the primary Repository.

        Failures to open a ganglion (missing file, schema error) fall
        back to the primary repository and log a warning — the primary
        write is still preferable to silently dropping the outcome.
        """
        if not source_db_path or self._ganglion_pool is None:
            return self.repository
        if self._ganglion_pool.is_primary(source_db_path):
            return self.repository
        try:
            ganglion_repo = await self._ganglion_pool.get_repository(source_db_path)
        except FileNotFoundError as e:
            logger.warning(
                "Ganglion DB missing for outcome write, falling back to primary: %s", e,
            )
            return self.repository
        except Exception as e:
            logger.warning(
                "Failed to open ganglion repository (%s); falling back to primary: %s",
                source_db_path, e,
            )
            return self.repository
        return ganglion_repo if ganglion_repo is not None else self.repository

    async def record_retrieval(
        self,
        methodology_id: str,
        source_db_path: Optional[str] = None,
    ) -> None:
        """Record that a methodology was retrieved for use.

        Increments retrieval_count and updates last_retrieved_at.
        Called by the orchestrator after Librarian returns past_solutions.

        Args:
            methodology_id: The methodology that was retrieved.
            source_db_path: Optional absolute path to the source DB when
                the methodology came from a sibling ganglion via federation.
                When None, writes go to the primary repository.
        """
        try:
            repo = await self._resolve_repository(source_db_path)
            await repo.update_methodology_retrieval(methodology_id)
            logger.debug(
                "Recorded retrieval for methodology %s (source=%s)",
                methodology_id,
                source_db_path or "primary",
            )
        except Exception as e:
            logger.warning("Failed to record retrieval for %s: %s", methodology_id, e)

    async def record_outcome(
        self,
        methodology_id: str,
        success: bool,
        retrieval_relevance: float = 0.5,
        source_db_path: Optional[str] = None,
    ) -> None:
        """Record the outcome of using a retrieved methodology.

        Updates success/failure counters, recalculates fitness vector,
        and evaluates lifecycle transitions.

        Args:
            methodology_id: The methodology that was used.
            success: True if the task succeeded, False if it failed.
            retrieval_relevance: The combined_score from the retrieval.
            source_db_path: Optional absolute path to the source DB when
                the methodology came from a sibling ganglion via federation.
                When None or pointing at the primary DB, writes go to
                ``self.repository``; otherwise they route through the
                injected GanglionRepositoryPool.
        """
        try:
            repo = await self._resolve_repository(source_db_path)
            await repo.update_methodology_outcome(methodology_id, success)

            # Reload to get updated counters from the *correct* DB
            methodology = await repo.get_methodology(methodology_id)
            if methodology is None:
                return

            # Recalculate fitness (pass latest_outcome for EMA update).
            # max_retrieval is scoped to the same DB we're writing to so
            # the normalization is consistent for that ganglion's corpus.
            max_retrieval = await self._get_max_retrieval_count(repo=repo)
            _, fitness_vector = compute_fitness(
                methodology,
                retrieval_relevance=retrieval_relevance,
                max_retrieval_count=max_retrieval,
                latest_outcome=success,
            )
            await repo.update_methodology_fitness(methodology_id, fitness_vector)

            # Log fitness change for time-series tracking on the same DB
            trigger = "outcome_success" if success else "outcome_failure"
            await log_fitness_change(
                repo.engine,
                methodology_id,
                fitness_vector.get("total", 0.0),
                fitness_vector,
                trigger_event=trigger,
            )

            # Evaluate lifecycle transition against the correct repository.
            # apply_transition persists the new state via repo.update_*,
            # so ganglion rows get promoted in the ganglion DB — not main.
            from claw.memory.lifecycle import apply_transition
            await apply_transition(methodology, repo)

            logger.debug(
                "Recorded outcome (success=%s) for methodology %s in %s, fitness=%.3f",
                success,
                methodology_id,
                source_db_path or "primary",
                fitness_vector.get("total", 0.0),
            )
        except Exception as e:
            logger.warning(
                "Failed to record outcome for %s: %s", methodology_id, e
            )

    async def record_co_retrieval_outcome(
        self,
        methodology_ids: list[str],
        success: bool,
    ) -> None:
        """Update stigmergic links between co-retrieved methodologies.

        When multiple methodologies are retrieved together:
        - Success: strengthen links (+0.1)
        - Failure: weaken links (-0.05)

        Args:
            methodology_ids: IDs of methodologies retrieved together.
            success: Whether the task succeeded.
        """
        delta = 0.1 if success else -0.05
        pairs_updated = 0

        for i, src_id in enumerate(methodology_ids):
            for tgt_id in methodology_ids[i + 1:]:
                try:
                    await self.repository.upsert_methodology_link(
                        source_id=src_id,
                        target_id=tgt_id,
                        strength=delta,
                    )
                    pairs_updated += 1
                except Exception as e:
                    logger.warning(
                        "Failed to update link %s<->%s: %s", src_id, tgt_id, e
                    )

        if pairs_updated > 0:
            logger.debug(
                "Updated %d co-retrieval links (success=%s, delta=%.2f)",
                pairs_updated, success, delta,
            )

    async def backfill_prism_embeddings(self) -> dict[str, int]:
        """Compute and store PRISM data for all methodologies that lack it.

        Returns:
            Dict with counts: processed, skipped, errors.
        """
        if self.prism_engine is None:
            return {"processed": 0, "skipped": 0, "errors": 0}

        stats: dict[str, int] = {"processed": 0, "skipped": 0, "errors": 0}
        for state in ("embryonic", "viable", "thriving", "declining", "dormant"):
            batch = await self.repository.get_methodologies_by_state(state, limit=500)
            for m in batch:
                if m.prism_data is not None:
                    stats["skipped"] += 1
                    continue
                if m.problem_embedding is None:
                    stats["skipped"] += 1
                    continue
                try:
                    prism_emb = self.prism_engine.enhance(
                        m.problem_embedding,
                        {"lifecycle_state": m.lifecycle_state},
                    )
                    await self.repository.update_methodology_prism_data(
                        m.id, prism_emb.to_dict()
                    )
                    stats["processed"] += 1
                except Exception as e:
                    logger.warning("PRISM backfill failed for %s: %s", m.id, e)
                    stats["errors"] += 1

        logger.info("PRISM backfill complete: %s", stats)
        return stats

    async def _get_max_retrieval_count(
        self,
        repo: Optional[Repository] = None,
    ) -> int:
        """Get the maximum retrieval_count across active methodologies.

        Args:
            repo: Repository to query. Defaults to the primary repository
                so existing callers keep working; Path C Fix 2 passes
                a ganglion Repository so fitness normalization is scoped
                to that ganglion's corpus.
        """
        target = repo if repo is not None else self.repository
        try:
            active: list[Methodology] = []
            for state in ("viable", "thriving", "embryonic"):
                batch = await target.get_methodologies_by_state(state, limit=500)
                active.extend(batch)
            if not active:
                return 1
            return max(m.retrieval_count for m in active) or 1
        except Exception:
            return 1


def get_fitness_score_safe(methodology: Methodology) -> float:
    """Extract stored fitness score with fallback, for sorting."""
    fv = methodology.fitness_vector
    if fv and "total" in fv:
        try:
            return float(fv["total"])
        except (TypeError, ValueError):
            pass
    return 0.5
