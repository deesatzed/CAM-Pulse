"""Local LLM Agent for CLAW.

Dedicated agent for local inference backends (Atomic-Chat, mlx-server,
Ollama, llama.cpp). Uses the OpenAI-compatible /v1/chat/completions
endpoint that all local providers expose.

All inference logic lives in AgentInterface.execute_local() — this class
just wires the config and constrains the mode to LOCAL.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from claw.agents.interface import AgentInterface
from claw.core.models import AgentHealth, AgentMode, TaskContext, TaskOutcome

logger = logging.getLogger("claw.agent.local")


class LocalAgent(AgentInterface):
    """Local inference agent — Atomic-Chat, mlx-server, Ollama, llama.cpp."""

    def __init__(
        self,
        model: Optional[str] = None,
        local_base_url: str = "http://localhost:11434/v1",
        timeout: int = 300,
        max_tokens: int = 16384,
        workspace_dir: Optional[str] = None,
    ):
        super().__init__(agent_id="local", name="Local LLM Agent")
        self.mode = AgentMode.LOCAL
        self.model = model
        self.local_base_url = local_base_url
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.workspace_dir = workspace_dir

    @property
    def supported_modes(self) -> list[AgentMode]:
        return [AgentMode.LOCAL]

    @property
    def instruction_file(self) -> str:
        return ""

    async def health_check(self) -> AgentHealth:
        return await self._local_health_check("local")

    async def execute(
        self, task: TaskContext, context: Optional[Any] = None
    ) -> TaskOutcome:
        return await self.execute_local(task, context)
