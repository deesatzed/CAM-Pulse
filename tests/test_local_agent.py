"""Tests for the dedicated LocalAgent."""
from __future__ import annotations

import asyncio

import pytest

from claw.agents.local_agent import LocalAgent
from claw.core.models import AgentHealth, AgentMode, Task, TaskContext


def _make_task_context(title="Test", description="Do it") -> TaskContext:
    task = Task(project_id="proj-1", title=title, description=description)
    return TaskContext(task=task)


class TestLocalAgentInit:
    def test_agent_id_is_local(self):
        agent = LocalAgent(model="test-model", local_base_url="http://localhost:1337/v1")
        assert agent.agent_id == "local"

    def test_mode_is_always_local(self):
        agent = LocalAgent(model="test-model", local_base_url="http://localhost:1337/v1")
        assert agent.mode == AgentMode.LOCAL

    def test_supported_modes_only_local(self):
        agent = LocalAgent(model="test-model", local_base_url="http://localhost:1337/v1")
        assert agent.supported_modes == [AgentMode.LOCAL]

    def test_custom_base_url_stored(self):
        agent = LocalAgent(model="m", local_base_url="http://localhost:8080/v1")
        assert agent.local_base_url == "http://localhost:8080/v1"

    def test_no_model_raises_on_execute(self):
        """Agent with empty model returns failure outcome."""
        agent = LocalAgent(model="", local_base_url="http://localhost:1337/v1")
        tc = _make_task_context()
        result = asyncio.run(agent.execute(tc))
        assert result.failure_reason == "no_model"
