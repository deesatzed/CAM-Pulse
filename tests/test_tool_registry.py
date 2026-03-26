"""Tests for the tool registry (Protocol-based DI pattern).

Validates:
- ToolProvider Protocol compliance
- ToolResult frozen dataclass behavior
- ToolRegistry register/unregister/execute/list
- Error handling for missing tools and execution failures
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from claw.tools.registry import ToolProvider, ToolRegistry, ToolResult


# ---------------------------------------------------------------------------
# Concrete tool implementations for testing (real, not mock)
# ---------------------------------------------------------------------------

class EchoTool:
    """A simple tool that echoes input."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes the input text back"

    async def execute(self, **kwargs: Any) -> ToolResult:
        text = kwargs.get("text", "")
        return ToolResult(success=True, data={"echo": text})


class FailingTool:
    """A tool that always raises."""

    @property
    def name(self) -> str:
        return "failing"

    @property
    def description(self) -> str:
        return "Always fails"

    async def execute(self, **kwargs: Any) -> ToolResult:
        raise RuntimeError("Intentional failure for testing")


class CounterTool:
    """A stateful tool that counts invocations."""

    def __init__(self):
        self.call_count = 0

    @property
    def name(self) -> str:
        return "counter"

    @property
    def description(self) -> str:
        return "Counts how many times it was called"

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.call_count += 1
        return ToolResult(success=True, data={"count": self.call_count})


# ---------------------------------------------------------------------------
# ToolResult tests
# ---------------------------------------------------------------------------

class TestToolResult:
    """Frozen dataclass behavior and validation."""

    def test_success_result(self):
        r = ToolResult(success=True, data={"key": "value"})
        assert r.success is True
        assert r.data == {"key": "value"}
        assert r.error == ""

    def test_failure_result_auto_fills_error(self):
        r = ToolResult(success=False)
        assert r.success is False
        assert r.error == "Tool execution failed (no detail)"

    def test_failure_result_preserves_explicit_error(self):
        r = ToolResult(success=False, error="Custom error")
        assert r.error == "Custom error"

    def test_frozen_prevents_mutation(self):
        r = ToolResult(success=True)
        with pytest.raises(AttributeError):
            r.success = False  # type: ignore[misc]

    def test_default_data_is_empty_dict(self):
        r = ToolResult(success=True)
        assert r.data == {}


# ---------------------------------------------------------------------------
# ToolProvider Protocol tests
# ---------------------------------------------------------------------------

class TestToolProvider:
    """Protocol compliance checks."""

    def test_echo_tool_is_provider(self):
        assert isinstance(EchoTool(), ToolProvider)

    def test_failing_tool_is_provider(self):
        assert isinstance(FailingTool(), ToolProvider)

    def test_counter_tool_is_provider(self):
        assert isinstance(CounterTool(), ToolProvider)

    def test_non_provider_rejected(self):
        class NotATool:
            pass
        assert not isinstance(NotATool(), ToolProvider)


# ---------------------------------------------------------------------------
# ToolRegistry tests
# ---------------------------------------------------------------------------

class TestToolRegistry:
    """Registry operations."""

    def test_register_and_lookup(self):
        reg = ToolRegistry()
        tool = EchoTool()
        reg.register(tool)
        assert reg.get("echo") is tool
        assert "echo" in reg
        assert len(reg) == 1

    def test_register_overwrites(self):
        reg = ToolRegistry()
        tool1 = EchoTool()
        tool2 = EchoTool()
        reg.register(tool1)
        reg.register(tool2)
        assert reg.get("echo") is tool2
        assert len(reg) == 1

    def test_unregister(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        assert reg.unregister("echo") is True
        assert reg.get("echo") is None
        assert len(reg) == 0

    def test_unregister_missing(self):
        reg = ToolRegistry()
        assert reg.unregister("nonexistent") is False

    def test_list_tools(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(CounterTool())
        tools = reg.list_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"echo", "counter"}

    def test_register_rejects_non_provider(self):
        reg = ToolRegistry()
        with pytest.raises(TypeError, match="ToolProvider protocol"):
            reg.register("not a tool")  # type: ignore[arg-type]

    def test_execute_success(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        result = asyncio.run(reg.execute("echo", text="hello"))
        assert result.success is True
        assert result.data == {"echo": "hello"}

    def test_execute_missing_tool(self):
        reg = ToolRegistry()
        result = asyncio.run(reg.execute("nonexistent"))
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_execute_failing_tool(self):
        reg = ToolRegistry()
        reg.register(FailingTool())
        result = asyncio.run(reg.execute("failing"))
        assert result.success is False
        assert "Intentional failure" in result.error

    def test_stateful_tool(self):
        reg = ToolRegistry()
        counter = CounterTool()
        reg.register(counter)
        asyncio.run(reg.execute("counter"))
        asyncio.run(reg.execute("counter"))
        result = asyncio.run(reg.execute("counter"))
        assert result.data["count"] == 3
        assert counter.call_count == 3

    def test_empty_registry(self):
        reg = ToolRegistry()
        assert len(reg) == 0
        assert reg.list_tools() == []
        assert reg.get("anything") is None
