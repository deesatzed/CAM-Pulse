"""Token-level cost tracking for LLM calls.

Intercepts every LLM call and records (input_tokens, output_tokens, cost)
per call, attributed to the active task/agent. Supports both SQLite
persistence and JSONL shadow-logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

from claw.core.models import TokenCostRecord

logger = logging.getLogger("claw.llm.token_tracker")


class TokenTracker:
    """Accumulates per-call token costs and persists to DB + JSONL.

    Usage:
        tracker = TokenTracker(repository=repo)
        tracker.set_context(task_id="...", agent_role="builder", agent_id="claude")
        # After each LLM call:
        await tracker.record(model="...", input_tokens=100, output_tokens=200)
    """

    def __init__(
        self,
        repository: Optional[Any] = None,
        jsonl_path: Optional[str] = None,
        cost_per_1k_input: float = 0.003,
        cost_per_1k_output: float = 0.015,
    ):
        self.repository = repository
        self.jsonl_path = jsonl_path
        self.cost_per_1k_input = cost_per_1k_input
        self.cost_per_1k_output = cost_per_1k_output
        self._task_id: Optional[str] = None
        self._run_id: Optional[str] = None
        self._agent_role: str = ""
        self._agent_id: Optional[str] = None
        self._session_totals: dict[str, Any] = {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "call_count": 0,
        }
        self._task_totals: dict[str, dict[str, Any]] = {}
        self._agent_totals: dict[str, dict[str, Any]] = {}

    def set_context(
        self,
        task_id: Optional[str] = None,
        run_id: Optional[str] = None,
        agent_role: str = "",
        agent_id: Optional[str] = None,
    ) -> None:
        """Set the attribution context for subsequent records."""
        self._task_id = task_id
        self._run_id = run_id
        self._agent_role = agent_role
        self._agent_id = agent_id

    async def record(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        cost_usd: Optional[float] = None,
    ) -> TokenCostRecord:
        """Record a single LLM call's token usage and cost.

        If cost_usd is not provided, it is estimated from token counts
        using the configured per-1k rates.
        """
        if total_tokens == 0:
            total_tokens = input_tokens + output_tokens

        if cost_usd is None:
            cost_usd = (
                (input_tokens / 1000.0) * self.cost_per_1k_input
                + (output_tokens / 1000.0) * self.cost_per_1k_output
            )

        record = TokenCostRecord(
            task_id=self._task_id,
            run_id=self._run_id,
            agent_role=self._agent_role,
            agent_id=self._agent_id,
            model_used=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
        )

        # Update session totals
        self._session_totals["total_input_tokens"] += input_tokens
        self._session_totals["total_output_tokens"] += output_tokens
        self._session_totals["total_tokens"] += total_tokens
        self._session_totals["total_cost_usd"] += cost_usd
        self._session_totals["call_count"] += 1

        # Update per-task totals
        if self._task_id is not None:
            if self._task_id not in self._task_totals:
                self._task_totals[self._task_id] = _empty_totals()
            _accumulate(self._task_totals[self._task_id], input_tokens, output_tokens, total_tokens, cost_usd)

        # Update per-agent totals
        if self._agent_id is not None:
            if self._agent_id not in self._agent_totals:
                self._agent_totals[self._agent_id] = _empty_totals()
            _accumulate(self._agent_totals[self._agent_id], input_tokens, output_tokens, total_tokens, cost_usd)

        # Persist to database (async)
        await self._persist_to_db(record)

        # Shadow-log to JSONL (async to avoid blocking event loop)
        await self._persist_to_jsonl(record)

        logger.debug(
            "Token cost recorded: model=%s in=%d out=%d cost=$%.6f agent=%s",
            model, input_tokens, output_tokens, cost_usd, self._agent_id or self._agent_role,
        )
        return record

    def get_session_totals(self) -> dict[str, Any]:
        """Return accumulated session-level totals."""
        return dict(self._session_totals)

    def get_task_totals(self, task_id: str) -> dict[str, Any]:
        """Return accumulated totals for a specific task."""
        return dict(self._task_totals.get(task_id, _empty_totals()))

    def get_agent_totals(self, agent_id: str) -> dict[str, Any]:
        """Return accumulated totals for a specific agent."""
        return dict(self._agent_totals.get(agent_id, _empty_totals()))

    async def _persist_to_db(self, record: TokenCostRecord) -> None:
        """Write record to the token_costs table."""
        if self.repository is None:
            return
        if not hasattr(self.repository, "save_token_cost"):
            return
        try:
            await self.repository.save_token_cost(record)
        except Exception as e:
            logger.warning("Failed to persist token cost to DB: %s", e)

    async def _persist_to_jsonl(self, record: TokenCostRecord) -> None:
        """Append record to JSONL shadow log without blocking the event loop."""
        if not self.jsonl_path:
            return
        try:
            path = Path(self.jsonl_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "id": record.id,
                "task_id": record.task_id,
                "run_id": record.run_id,
                "agent_role": record.agent_role,
                "agent_id": record.agent_id,
                "model_used": record.model_used,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "total_tokens": record.total_tokens,
                "cost_usd": record.cost_usd,
                "created_at": record.created_at.isoformat(),
            }
            line = json.dumps(entry) + "\n"
            await asyncio.to_thread(self._write_line, path, line)
        except Exception as e:
            logger.warning("Failed to write token cost to JSONL: %s", e)

    @staticmethod
    def _write_line(path: Path, line: str) -> None:
        """Synchronous file append, executed via asyncio.to_thread."""
        with open(path, "a") as f:
            f.write(line)


def _empty_totals() -> dict[str, Any]:
    return {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "call_count": 0,
    }


def _accumulate(
    totals: dict[str, Any],
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    cost_usd: float,
) -> None:
    totals["total_input_tokens"] += input_tokens
    totals["total_output_tokens"] += output_tokens
    totals["total_tokens"] += total_tokens
    totals["total_cost_usd"] += cost_usd
    totals["call_count"] += 1
