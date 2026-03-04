"""Bayesian agent routing with Thompson sampling and exploration.

Uses agent_scores from MetaMemory to make routing decisions.
Replaces static routing with learned routing as data accumulates.
Supports a configurable exploration rate (default 10%) to ensure
all agents keep gathering data even when one currently leads.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Optional

from claw.memory.meta import MetaMemory

logger = logging.getLogger("claw.evolution.routing_optimizer")

# Default fallback when no scores exist for any agent.
_DEFAULT_AGENT = "claude"


class BayesianRouter:
    """Bayesian agent routing with Thompson sampling and exploration.

    Uses agent_scores from :class:`MetaMemory` to make routing decisions.
    Replaces static routing with learned routing as data accumulates.
    """

    def __init__(
        self,
        meta_memory: MetaMemory,
        exploration_rate: float = 0.10,
        score_decay: float = 0.95,
    ) -> None:
        """
        Parameters
        ----------
        meta_memory:
            The MetaMemory instance providing access to agent score data.
        exploration_rate:
            Probability of choosing a random agent instead of the
            Thompson-optimal one.  Default is 0.10 (10%).
        score_decay:
            Decay factor applied to agent scores for unused agents each
            cycle, to prevent stale data from dominating routing decisions.
        """
        self.meta_memory = meta_memory
        self.exploration_rate = exploration_rate
        self.score_decay = score_decay

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def route(
        self,
        task_type: str,
        available_agents: list[str],
    ) -> str:
        """Route a task to the best agent using Thompson sampling.

        Algorithm:
        1. With probability ``exploration_rate``, pick a random agent
           from ``available_agents`` (epsilon-greedy exploration).
        2. Otherwise, draw Thompson samples for each available agent
           from their Beta(alpha, beta) posterior and pick the one
           with the highest sample.
        3. If no agent has score data for this ``task_type``, fall back
           to ``"claude"`` if it is in the available list, else pick
           a random available agent.

        Parameters
        ----------
        task_type:
            The type of task being routed (e.g. ``"bug_fix"``).
        available_agents:
            List of agent_ids that are currently available and healthy.

        Returns
        -------
        str
            The selected agent_id.

        Raises
        ------
        ValueError
            If ``available_agents`` is empty.
        """
        if not available_agents:
            raise ValueError("available_agents must be non-empty")

        # Step 1: Exploration check
        if random.random() < self.exploration_rate:
            chosen = random.choice(available_agents)
            logger.info(
                "Routing (exploration): task_type=%s -> agent=%s",
                task_type,
                chosen,
            )
            return chosen

        # Step 2: Get scores for this task type
        scores = await self.meta_memory.get_scores_for_task_type(task_type)
        score_by_agent: dict[str, dict[str, Any]] = {
            str(s["agent_id"]): s for s in scores
        }

        # Step 3: Thompson sampling across available agents
        best_agent: Optional[str] = None
        best_sample = -1.0
        has_any_data = False

        for agent_id in available_agents:
            if agent_id in score_by_agent:
                has_any_data = True
                row = score_by_agent[agent_id]
                sample = self.meta_memory.thompson_sample(
                    successes=int(row.get("successes", 0)),
                    failures=int(row.get("failures", 0)),
                )
            else:
                # No data for this agent on this task type.
                # Draw from the uninformative prior Beta(1,1) = Uniform(0,1).
                sample = self.meta_memory.thompson_sample(
                    successes=0, failures=0
                )

            if sample > best_sample:
                best_sample = sample
                best_agent = agent_id

        # Step 4: Fallback
        if best_agent is None:
            # Shouldn't happen since available_agents is non-empty, but be safe.
            if _DEFAULT_AGENT in available_agents:
                best_agent = _DEFAULT_AGENT
            else:
                best_agent = random.choice(available_agents)

        logger.info(
            "Routing (Thompson): task_type=%s -> agent=%s (sample=%.4f, has_data=%s)",
            task_type,
            best_agent,
            best_sample,
            has_any_data,
        )
        return best_agent

    # ------------------------------------------------------------------
    # Score decay
    # ------------------------------------------------------------------

    async def apply_score_decay(self, agent_id: str) -> None:
        """Decay scores for an unused agent to prevent stale data dominance.

        Delegates to ``MetaMemory.apply_score_decay`` with this router's
        configured ``score_decay`` factor.

        Parameters
        ----------
        agent_id:
            The agent whose scores should be decayed.
        """
        await self.meta_memory.apply_score_decay(
            agent_id=agent_id,
            decay_factor=self.score_decay,
        )
        logger.debug(
            "Applied score decay (factor=%.2f) for agent %s",
            self.score_decay,
            agent_id,
        )

    # ------------------------------------------------------------------
    # Batch decay for unused agents
    # ------------------------------------------------------------------

    async def decay_unused_agents(
        self,
        used_agent_ids: list[str],
        all_agent_ids: list[str],
    ) -> list[str]:
        """Decay scores for all agents not in ``used_agent_ids``.

        Call this after a routing cycle to slowly erode stale score
        advantages for agents that were not recently selected.

        Parameters
        ----------
        used_agent_ids:
            Agents that were used this cycle (will NOT be decayed).
        all_agent_ids:
            Full list of known agent identifiers.

        Returns
        -------
        list[str]
            The list of agent_ids that had decay applied.
        """
        unused = [a for a in all_agent_ids if a not in used_agent_ids]
        for agent_id in unused:
            await self.apply_score_decay(agent_id)
        return unused

    # ------------------------------------------------------------------
    # Debugging / introspection
    # ------------------------------------------------------------------

    async def get_routing_state(self) -> dict[str, Any]:
        """Get current routing state (scores, samples) for debugging.

        Returns a dict with:
        - ``exploration_rate``: the current exploration probability
        - ``score_decay``: the current decay factor
        - ``agents``: dict of agent_id -> per-task-type breakdown
          each containing ``successes``, ``failures``, ``bayesian_score``,
          and a fresh ``thompson_sample``.
        """
        all_scores = await self.meta_memory.get_agent_scores()

        agents: dict[str, dict[str, Any]] = {}
        for row in all_scores:
            agent_id = str(row["agent_id"])
            task_type = str(row["task_type"])
            successes = int(row.get("successes", 0))
            failures = int(row.get("failures", 0))

            if agent_id not in agents:
                agents[agent_id] = {"task_types": {}}

            agents[agent_id]["task_types"][task_type] = {
                "successes": successes,
                "failures": failures,
                "total_attempts": int(row.get("total_attempts", 0)),
                "avg_quality_score": float(row.get("avg_quality_score", 0.0)),
                "avg_cost_usd": float(row.get("avg_cost_usd", 0.0)),
                "avg_duration_seconds": float(
                    row.get("avg_duration_seconds", 0.0)
                ),
                "bayesian_score": self.meta_memory.bayesian_score(
                    successes, failures
                ),
                "thompson_sample": self.meta_memory.thompson_sample(
                    successes, failures
                ),
            }

        return {
            "exploration_rate": self.exploration_rate,
            "score_decay": self.score_decay,
            "agents": agents,
        }
