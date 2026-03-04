"""Meta memory — agent performance tracking and Bayesian scoring.

Wraps the ``agent_scores`` table to provide:
- Score recording after each task outcome
- Bayesian score computation (Beta distribution)
- Thompson sampling for routing decisions
- Per-agent and per-task-type performance summaries
"""

from __future__ import annotations

import logging
import random
from typing import Any, Optional

from claw.db.repository import Repository

logger = logging.getLogger("claw.memory.meta")


class MetaMemory:
    """Agent performance tracking and Bayesian scoring.

    Wraps the ``agent_scores`` table to provide:
    - Score recording after each task outcome
    - Bayesian score computation (Beta distribution)
    - Per-agent and per-task-type performance summaries
    """

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def record_outcome(
        self,
        agent_id: str,
        task_type: str,
        success: bool,
        quality_score: float = 0.5,
        cost_usd: float = 0.0,
        duration_seconds: float = 0.0,
    ) -> None:
        """Record the outcome of an agent executing a task.

        Delegates to ``Repository.update_agent_score`` which handles the
        upsert logic (insert on first observation, running-average update
        on subsequent observations).

        Parameters
        ----------
        agent_id:
            Identifier of the agent (e.g. ``"claude"``, ``"codex"``).
        task_type:
            The type of task executed (e.g. ``"bug_fix"``, ``"refactor"``).
        success:
            Whether the task was completed successfully.
        quality_score:
            Quality metric in [0.0, 1.0].
        cost_usd:
            Dollar cost of the agent invocation.
        duration_seconds:
            Wall-clock time taken by the agent.
        """
        await self.repository.update_agent_score(
            agent_id=agent_id,
            task_type=task_type,
            success=success,
            duration_seconds=duration_seconds,
            quality_score=quality_score,
            cost_usd=cost_usd,
        )
        logger.debug(
            "Recorded outcome for agent=%s task_type=%s success=%s quality=%.2f",
            agent_id,
            task_type,
            success,
            quality_score,
        )

    # ------------------------------------------------------------------
    # Read — raw scores
    # ------------------------------------------------------------------

    async def get_agent_scores(
        self, agent_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Get agent scores, optionally filtered by agent_id.

        Each returned dict mirrors the ``agent_scores`` table columns:
        ``id``, ``agent_id``, ``task_type``, ``successes``, ``failures``,
        ``total_attempts``, ``avg_duration_seconds``, ``avg_quality_score``,
        ``avg_cost_usd``, ``last_used_at``, ``created_at``, ``updated_at``.
        """
        rows = await self.repository.get_agent_scores(agent_id=agent_id)
        # Enrich each row with a computed bayesian_score.
        enriched: list[dict[str, Any]] = []
        for row in rows:
            enriched_row = dict(row)
            enriched_row["bayesian_score"] = self.bayesian_score(
                successes=int(row.get("successes", 0)),
                failures=int(row.get("failures", 0)),
            )
            enriched.append(enriched_row)
        return enriched

    # ------------------------------------------------------------------
    # Read — scores for a specific task type
    # ------------------------------------------------------------------

    async def get_scores_for_task_type(
        self, task_type: str
    ) -> list[dict[str, Any]]:
        """Get all agent scores for a given task type.

        Returns a list of score dicts, one per agent that has attempted
        this task type, enriched with ``bayesian_score``.
        """
        rows = await self.repository.engine.fetch_all(
            "SELECT * FROM agent_scores WHERE task_type = ?",
            [task_type],
        )
        enriched: list[dict[str, Any]] = []
        for row in rows:
            enriched_row = dict(row)
            enriched_row["bayesian_score"] = self.bayesian_score(
                successes=int(row.get("successes", 0)),
                failures=int(row.get("failures", 0)),
            )
            enriched.append(enriched_row)
        return enriched

    # ------------------------------------------------------------------
    # Best agent (Thompson sampling)
    # ------------------------------------------------------------------

    async def get_best_agent(self, task_type: str) -> Optional[str]:
        """Return the agent_id with highest score for a task_type using Thompson sampling.

        Draws one Thompson sample per agent that has data for the given
        ``task_type`` and returns the agent with the highest sample.
        If no agents have scores for this task type, returns ``None``.
        """
        rows = await self.repository.engine.fetch_all(
            "SELECT agent_id, successes, failures FROM agent_scores WHERE task_type = ?",
            [task_type],
        )
        if not rows:
            return None

        best_agent: Optional[str] = None
        best_sample = -1.0

        for row in rows:
            agent_id = str(row["agent_id"])
            successes = int(row["successes"])
            failures = int(row["failures"])
            sample = self.thompson_sample(successes, failures)
            if sample > best_sample:
                best_sample = sample
                best_agent = agent_id

        return best_agent

    # ------------------------------------------------------------------
    # Performance summary
    # ------------------------------------------------------------------

    async def get_performance_summary(self) -> dict[str, Any]:
        """Get aggregate performance across all agents.

        Returns a dict with:
        - ``total_agents``: number of distinct agents with recorded scores
        - ``total_task_types``: number of distinct task types
        - ``total_attempts``: grand total of attempts across all agents/types
        - ``overall_success_rate``: aggregate success rate
        - ``per_agent``: dict of agent_id -> agent summary
        - ``per_task_type``: dict of task_type -> task-type summary
        """
        all_scores = await self.repository.get_agent_scores()

        if not all_scores:
            return {
                "total_agents": 0,
                "total_task_types": 0,
                "total_attempts": 0,
                "overall_success_rate": 0.0,
                "per_agent": {},
                "per_task_type": {},
            }

        agents: dict[str, dict[str, Any]] = {}
        task_types: dict[str, dict[str, Any]] = {}
        grand_successes = 0
        grand_failures = 0

        for row in all_scores:
            agent_id = str(row["agent_id"])
            task_type = str(row["task_type"])
            successes = int(row.get("successes", 0))
            failures = int(row.get("failures", 0))
            total = int(row.get("total_attempts", 0))
            avg_quality = float(row.get("avg_quality_score", 0.0))
            avg_cost = float(row.get("avg_cost_usd", 0.0))
            avg_duration = float(row.get("avg_duration_seconds", 0.0))

            grand_successes += successes
            grand_failures += failures

            # Per-agent accumulation
            if agent_id not in agents:
                agents[agent_id] = {
                    "successes": 0,
                    "failures": 0,
                    "total_attempts": 0,
                    "task_types": [],
                    "avg_quality_score": 0.0,
                    "avg_cost_usd": 0.0,
                    "avg_duration_seconds": 0.0,
                    "_quality_sum": 0.0,
                    "_cost_sum": 0.0,
                    "_duration_sum": 0.0,
                }
            agent_entry = agents[agent_id]
            agent_entry["successes"] += successes
            agent_entry["failures"] += failures
            agent_entry["total_attempts"] += total
            agent_entry["task_types"].append(task_type)
            agent_entry["_quality_sum"] += avg_quality * total
            agent_entry["_cost_sum"] += avg_cost * total
            agent_entry["_duration_sum"] += avg_duration * total

            # Per-task-type accumulation
            if task_type not in task_types:
                task_types[task_type] = {
                    "successes": 0,
                    "failures": 0,
                    "total_attempts": 0,
                    "agents": [],
                    "best_agent": None,
                    "best_bayesian_score": 0.0,
                }
            tt_entry = task_types[task_type]
            tt_entry["successes"] += successes
            tt_entry["failures"] += failures
            tt_entry["total_attempts"] += total
            tt_entry["agents"].append(agent_id)
            bscore = self.bayesian_score(successes, failures)
            if bscore > tt_entry["best_bayesian_score"]:
                tt_entry["best_bayesian_score"] = bscore
                tt_entry["best_agent"] = agent_id

        # Finalize per-agent averages
        for agent_id, entry in agents.items():
            total = entry["total_attempts"]
            if total > 0:
                entry["avg_quality_score"] = entry["_quality_sum"] / total
                entry["avg_cost_usd"] = entry["_cost_sum"] / total
                entry["avg_duration_seconds"] = entry["_duration_sum"] / total
            entry["bayesian_score"] = self.bayesian_score(
                entry["successes"], entry["failures"]
            )
            entry["success_rate"] = (
                entry["successes"] / total if total > 0 else 0.0
            )
            # Remove internal accumulators
            del entry["_quality_sum"]
            del entry["_cost_sum"]
            del entry["_duration_sum"]

        # Finalize per-task-type success rates
        for task_type, entry in task_types.items():
            total = entry["total_attempts"]
            entry["success_rate"] = (
                entry["successes"] / total if total > 0 else 0.0
            )

        grand_total = grand_successes + grand_failures
        overall_success_rate = (
            grand_successes / grand_total if grand_total > 0 else 0.0
        )

        return {
            "total_agents": len(agents),
            "total_task_types": len(task_types),
            "total_attempts": grand_total,
            "overall_success_rate": overall_success_rate,
            "per_agent": agents,
            "per_task_type": task_types,
        }

    # ------------------------------------------------------------------
    # Bayesian scoring
    # ------------------------------------------------------------------

    def bayesian_score(
        self,
        successes: int,
        failures: int,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ) -> float:
        """Compute Bayesian score using Beta distribution mean.

        E[Beta(alpha, beta)] = alpha / (alpha + beta)
        where alpha = prior_alpha + successes, beta = prior_beta + failures.

        With uniform priors (1, 1) and zero observations the score is 0.5,
        reflecting maximum uncertainty.
        """
        alpha = prior_alpha + successes
        beta = prior_beta + failures
        return alpha / (alpha + beta)

    def thompson_sample(
        self,
        successes: int,
        failures: int,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ) -> float:
        """Draw a Thompson sample from Beta distribution.

        Uses ``random.betavariate(alpha, beta)`` for sampling.  This
        provides natural exploration: agents with high uncertainty
        (few observations) will occasionally draw high values and get
        selected even if their mean is lower.
        """
        alpha = prior_alpha + successes
        beta = prior_beta + failures
        return random.betavariate(alpha, beta)

    # ------------------------------------------------------------------
    # Score decay
    # ------------------------------------------------------------------

    async def apply_score_decay(
        self,
        agent_id: str,
        decay_factor: float = 0.95,
    ) -> None:
        """Decay scores for an agent to prevent stale data from dominating.

        Multiplies both ``successes`` and ``failures`` by ``decay_factor``
        (truncating to int), effectively shrinking the evidence base so
        that newer observations carry more relative weight.

        This is applied per agent across all task types.
        """
        rows = await self.repository.engine.fetch_all(
            "SELECT id, successes, failures, total_attempts FROM agent_scores WHERE agent_id = ?",
            [agent_id],
        )
        for row in rows:
            old_s = int(row["successes"])
            old_f = int(row["failures"])
            new_s = max(0, int(old_s * decay_factor))
            new_f = max(0, int(old_f * decay_factor))
            new_total = new_s + new_f
            await self.repository.engine.execute(
                """UPDATE agent_scores
                   SET successes = ?, failures = ?, total_attempts = ?
                   WHERE id = ?""",
                [new_s, new_f, new_total, row["id"]],
            )
        logger.debug(
            "Applied decay (factor=%.2f) to agent %s across %d score rows",
            decay_factor,
            agent_id,
            len(rows),
        )
