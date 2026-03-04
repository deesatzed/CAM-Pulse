"""Graceful degradation module for CLAW.

Extends the HealthMonitor's per-agent circuit breakers with higher-level
degradation logic: fallback routing, rate-limit tracking, and system-wide
health assessment.

When an agent is unavailable (circuit breaker open or rate-limited), the
DegradationManager finds a healthy alternative. When all agents are down,
it signals the orchestrator to notify a human rather than silently failing.

This module does NOT replace the HealthMonitor -- it builds on top of it.
The HealthMonitor owns the circuit breaker state; DegradationManager reads
that state and adds routing-level decisions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional

from claw.orchestrator.health_monitor import HealthMonitor

if TYPE_CHECKING:
    from claw.dispatcher import Dispatcher

logger = logging.getLogger("claw.degradation")

# Default set of agent identifiers when none are provided.
DEFAULT_AGENT_IDS: list[str] = ["claude", "codex", "gemini", "grok"]


class DegradationManager:
    """Manages graceful degradation when agents become unavailable.

    Responsibilities:
    - Determine which agents are currently healthy.
    - Find fallback agents when the preferred agent is down.
    - Track rate-limit backoff windows per agent.
    - Signal when all agents are down and human intervention is needed.

    Args:
        health_monitor: The HealthMonitor instance that tracks per-agent
                        circuit breaker state.
        dispatcher: Optional Dispatcher for context-aware fallback routing.
                    If provided, fallback selection can consider learned
                    routing scores.
        all_agent_ids: List of all known agent identifiers. Defaults to
                       ``["claude", "codex", "gemini", "grok"]``.
    """

    def __init__(
        self,
        health_monitor: HealthMonitor,
        dispatcher: Optional[Dispatcher] = None,
        all_agent_ids: Optional[list[str]] = None,
    ) -> None:
        self.health_monitor = health_monitor
        self.dispatcher = dispatcher
        self.all_agent_ids: list[str] = (
            list(all_agent_ids) if all_agent_ids is not None else list(DEFAULT_AGENT_IDS)
        )

        # Rate-limit tracking: agent_id -> datetime when backoff expires
        self._rate_limits: dict[str, datetime] = {}

        logger.info(
            "DegradationManager initialized: agents=%s, dispatcher=%s",
            self.all_agent_ids,
            "connected" if dispatcher else "none",
        )

    # -------------------------------------------------------------------
    # Agent health queries
    # -------------------------------------------------------------------

    def get_healthy_agents(self) -> list[str]:
        """Return a list of agents whose circuit breaker is NOT open.

        Also excludes agents that are currently rate-limited (backoff
        window has not expired).

        Returns:
            Sorted list of agent_id strings for healthy agents.
        """
        healthy: list[str] = []
        now = datetime.now(UTC)

        for agent_id in self.all_agent_ids:
            # Check circuit breaker (HealthMonitor handles auto-reset
            # on cooldown expiry internally)
            if self.health_monitor.is_agent_circuit_open(agent_id):
                continue

            # Check rate-limit backoff
            backoff_until = self._rate_limits.get(agent_id)
            if backoff_until is not None and now < backoff_until:
                continue

            healthy.append(agent_id)

        return sorted(healthy)

    def get_fallback_agent(self, preferred: str) -> Optional[str]:
        """Find a healthy agent to use instead of the preferred one.

        If the preferred agent is itself healthy, it is NOT returned --
        this method is specifically for finding an alternative when the
        preferred agent is unavailable.

        Selection order among healthy agents:
        1. Claude (as the most general-purpose agent).
        2. The first alphabetically sorted healthy agent.

        Args:
            preferred: The agent_id that is unavailable.

        Returns:
            A healthy agent_id, or None if no alternative is available.
        """
        healthy = self.get_healthy_agents()

        # Remove the preferred agent from candidates -- we want an alternative
        candidates = [a for a in healthy if a != preferred]

        if not candidates:
            logger.warning(
                "No fallback agent available for preferred='%s'. "
                "Healthy agents (excluding preferred): none",
                preferred,
            )
            return None

        # Prefer "claude" as the general-purpose fallback
        if "claude" in candidates:
            fallback = "claude"
        else:
            fallback = candidates[0]

        logger.info(
            "Fallback for '%s': selected '%s' from %d candidate(s)",
            preferred, fallback, len(candidates),
        )
        return fallback

    async def route_with_fallback(
        self, task_type: str, preferred_agent: str
    ) -> tuple[str, str]:
        """Select an agent with automatic fallback if the preferred is down.

        First checks if the preferred agent is healthy. If so, returns it
        with reason "primary". If not, attempts to find a fallback via
        ``get_fallback_agent()``. If no fallback is available either,
        returns the preferred agent anyway with reason "no_fallback"
        so the caller can decide how to handle it (e.g. queue the task).

        Args:
            task_type: The type of task being routed (used for logging).
            preferred_agent: The agent_id that should ideally handle this task.

        Returns:
            A tuple of (agent_id, reason) where reason is one of:
            - "primary" -- the preferred agent is healthy
            - "fallback_{agent_id}" -- a fallback agent was selected
            - "no_fallback" -- no healthy agent available, returning
              preferred as a last resort
        """
        # Check if preferred is healthy
        is_circuit_open = self.health_monitor.is_agent_circuit_open(preferred_agent)
        is_rate_limited = self._is_rate_limited(preferred_agent)

        if not is_circuit_open and not is_rate_limited:
            logger.debug(
                "Primary agent '%s' is healthy for task_type='%s'",
                preferred_agent, task_type,
            )
            return preferred_agent, "primary"

        # Preferred is down -- find fallback
        status_reason = "circuit_open" if is_circuit_open else "rate_limited"
        logger.info(
            "Preferred agent '%s' is %s for task_type='%s', seeking fallback",
            preferred_agent, status_reason, task_type,
        )

        fallback = self.get_fallback_agent(preferred_agent)
        if fallback is not None:
            logger.info(
                "Routing task_type='%s' to fallback agent '%s' "
                "(preferred '%s' is %s)",
                task_type, fallback, preferred_agent, status_reason,
            )
            return fallback, f"fallback_{fallback}"

        # No fallback available
        logger.warning(
            "No fallback available for task_type='%s'. "
            "Returning preferred '%s' with no_fallback status",
            task_type, preferred_agent,
        )
        return preferred_agent, "no_fallback"

    # -------------------------------------------------------------------
    # System-wide health assessment
    # -------------------------------------------------------------------

    def is_all_down(self) -> bool:
        """Check if every known agent is unavailable.

        Returns:
            True if all agents have open circuit breakers or are
            rate-limited. False if at least one agent is healthy.
        """
        healthy = self.get_healthy_agents()
        all_down = len(healthy) == 0

        if all_down:
            logger.critical(
                "ALL agents are down. Agent count: %d, all unavailable.",
                len(self.all_agent_ids),
            )

        return all_down

    def should_notify_human(self) -> bool:
        """Determine if the situation warrants human notification.

        Returns True if:
        - All agents are down, OR
        - A majority of agents (more than half) are down.

        Returns:
            True if human notification is recommended.
        """
        healthy = self.get_healthy_agents()
        total = len(self.all_agent_ids)

        if total == 0:
            return True

        healthy_count = len(healthy)
        down_count = total - healthy_count

        # All down: definitely notify
        if healthy_count == 0:
            logger.warning(
                "Human notification recommended: all %d agents are down",
                total,
            )
            return True

        # Majority down: notify
        if down_count > total / 2:
            logger.warning(
                "Human notification recommended: %d of %d agents are down "
                "(majority threshold exceeded)",
                down_count, total,
            )
            return True

        return False

    def get_degradation_status(self) -> dict:
        """Build a comprehensive summary of agent health and degradation state.

        Returns:
            Dictionary containing:
            - ``healthy_agents``: List of healthy agent IDs.
            - ``unhealthy_agents``: List of agent IDs that are circuit-open
              or rate-limited.
            - ``all_down``: Boolean, True if no agents are available.
            - ``should_notify_human``: Boolean, True if human notification
              is recommended.
            - ``agent_details``: Per-agent detail dict from HealthMonitor
              augmented with rate-limit info.
            - ``total_agents``: Count of all known agents.
            - ``healthy_count``: Count of healthy agents.
        """
        healthy = self.get_healthy_agents()
        unhealthy = [a for a in self.all_agent_ids if a not in healthy]
        monitor_status = self.health_monitor.get_agent_status()
        now = datetime.now(UTC)

        # Augment monitor status with rate-limit info
        agent_details: dict[str, dict] = {}
        for agent_id in self.all_agent_ids:
            base = monitor_status.get(agent_id, {
                "consecutive_failures": 0,
                "circuit_open": False,
                "circuit_until": None,
                "cooldown_remaining_seconds": None,
            })

            backoff_until = self._rate_limits.get(agent_id)
            rate_limited = backoff_until is not None and now < backoff_until
            rate_limit_remaining: Optional[int] = None
            if rate_limited and backoff_until is not None:
                delta = backoff_until - now
                rate_limit_remaining = max(0, int(delta.total_seconds()))

            agent_details[agent_id] = {
                **base,
                "rate_limited": rate_limited,
                "rate_limit_remaining_seconds": rate_limit_remaining,
                "healthy": agent_id in healthy,
            }

        return {
            "healthy_agents": healthy,
            "unhealthy_agents": unhealthy,
            "all_down": len(healthy) == 0,
            "should_notify_human": self.should_notify_human(),
            "agent_details": agent_details,
            "total_agents": len(self.all_agent_ids),
            "healthy_count": len(healthy),
        }

    # -------------------------------------------------------------------
    # Rate-limit tracking
    # -------------------------------------------------------------------

    def record_rate_limit(self, agent_id: str, backoff_seconds: int) -> None:
        """Record that an agent has been rate-limited.

        Sets a backoff window during which the agent will be considered
        unavailable by ``get_healthy_agents()`` and
        ``route_with_fallback()``.

        Args:
            agent_id: The agent that received a rate-limit response.
            backoff_seconds: How many seconds to wait before retrying.
                             Must be non-negative.
        """
        if backoff_seconds < 0:
            backoff_seconds = 0

        backoff_until = datetime.now(UTC) + timedelta(seconds=backoff_seconds)
        self._rate_limits[agent_id] = backoff_until

        logger.warning(
            "Rate limit recorded for agent '%s': backoff %ds (until %s)",
            agent_id, backoff_seconds, backoff_until.isoformat(),
        )

    def get_rate_limit_backoff(self, agent_id: str) -> int:
        """Get the remaining backoff seconds for a rate-limited agent.

        Args:
            agent_id: The agent to check.

        Returns:
            Remaining seconds to wait before the agent can be retried.
            Returns 0 if the agent is not rate-limited or the backoff
            has expired.
        """
        backoff_until = self._rate_limits.get(agent_id)
        if backoff_until is None:
            return 0

        now = datetime.now(UTC)
        if now >= backoff_until:
            # Backoff expired -- clean up the entry
            del self._rate_limits[agent_id]
            return 0

        remaining = backoff_until - now
        return max(0, int(remaining.total_seconds()))

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _is_rate_limited(self, agent_id: str) -> bool:
        """Check if an agent is currently rate-limited.

        Side effect: cleans up expired backoff entries.

        Args:
            agent_id: The agent to check.

        Returns:
            True if the agent's rate-limit backoff has not yet expired.
        """
        backoff_until = self._rate_limits.get(agent_id)
        if backoff_until is None:
            return False

        now = datetime.now(UTC)
        if now >= backoff_until:
            del self._rate_limits[agent_id]
            return False

        return True
