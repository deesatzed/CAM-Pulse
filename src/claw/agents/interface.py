"""Abstract agent interface for CLAW.

All four agents (Claude, Codex, Gemini, Grok) implement this ABC.
Provides lifecycle timing, metrics, and structured TaskOutcome returns.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from claw.core.models import AgentHealth, AgentMode, AgentResult, TaskContext, TaskOutcome


class AgentInterface(ABC):
    """Base class for all CLAW agents.

    Every agent follows the same lifecycle:
    1. Receive task context
    2. Execute (LLM calls, tool execution, etc.)
    3. Return a TaskOutcome with structured results
    4. Log metrics and errors throughout

    Subclasses must implement:
    - execute() — core task processing
    - health_check() — agent availability check
    - supported_modes — property listing modes (cli, api, cloud)
    - instruction_file — property with path to agent instruction file
    """

    def __init__(self, agent_id: str, name: str):
        """Initialize agent with id and name.

        Args:
            agent_id: Machine identifier (e.g., "claude", "codex", "gemini", "grok").
            name: Human-readable agent name (e.g., "Claude Code Agent").
        """
        self.agent_id = agent_id
        self.name = name
        self.logger = logging.getLogger(f"claw.agent.{agent_id}")
        self._metrics: dict[str, Any] = {
            "total_executed": 0,
            "total_errors": 0,
            "total_successes": 0,
            "last_duration_seconds": 0.0,
        }

    @abstractmethod
    async def execute(self, task: TaskContext, context: Optional[Any] = None) -> TaskOutcome:
        """Execute a task and return the outcome.

        Args:
            task: Enriched task context.
            context: Optional additional context (ContextBrief, etc.).

        Returns:
            TaskOutcome with files changed, test results, approach summary, etc.
        """

    @abstractmethod
    async def health_check(self) -> AgentHealth:
        """Check if this agent is available and operational.

        Returns:
            AgentHealth with availability status, mode, version, etc.
        """

    @property
    @abstractmethod
    def supported_modes(self) -> list[AgentMode]:
        """Return the modes this agent supports (cli, api, cloud)."""

    @property
    @abstractmethod
    def instruction_file(self) -> str:
        """Return the filename of this agent's instruction file (e.g., 'CLAUDE.md')."""

    async def run(self, task: TaskContext, context: Optional[Any] = None) -> TaskOutcome:
        """Execute the agent with lifecycle logging and metrics.

        This wraps execute() with start/complete/error tracking.
        Agents should override execute(), not run().
        """
        self._log_start(task)
        start = time.monotonic()

        try:
            result = await self.execute(task, context)
            duration = time.monotonic() - start
            result.duration_seconds = duration
            result.agent_id = self.agent_id
            self._metrics["total_executed"] += 1
            self._metrics["total_successes"] += 1
            self._metrics["last_duration_seconds"] = duration
            self._log_complete(duration, result)
            return result
        except Exception as e:
            duration = time.monotonic() - start
            self._metrics["total_executed"] += 1
            self._metrics["total_errors"] += 1
            self._metrics["last_duration_seconds"] = duration
            self._log_error(e)
            return TaskOutcome(
                agent_id=self.agent_id,
                failure_reason=type(e).__name__,
                failure_detail=str(e),
                duration_seconds=duration,
            )

    def _log_start(self, task: TaskContext) -> None:
        self.logger.info("[%s] Starting: task='%s'", self.name, task.task.title)

    def _log_complete(self, duration: float, result: TaskOutcome) -> None:
        status = "success" if result.tests_passed else "completed"
        self.logger.info(
            "[%s] Complete: status=%s (%.2fs)",
            self.name, status, duration,
        )

    def _log_error(self, error: Exception) -> None:
        self.logger.error(
            "[%s] Error: %s", self.name, error, exc_info=True,
        )

    def _resolve_workspace(self, task: TaskContext) -> Optional[str]:
        """Return a safe cwd for subprocess execution.

        Uses workspace_dir if set and valid. Never falls back to
        task.description to prevent path-traversal via untrusted input.
        """
        ws = getattr(self, "workspace_dir", None)
        if ws and Path(ws).is_dir():
            return ws
        return None

    def get_metrics(self) -> dict[str, Any]:
        """Return a copy of the agent's runtime metrics."""
        return self._metrics.copy()
