"""Tool registry with Protocol-based dependency injection.

Provides a dynamic tool registration system using Python typing.Protocol
for loose coupling. Agents can discover and invoke tools without hard
dependencies on specific implementations.

Design inspired by Agent_Pidgeon's MountGateway Protocol pattern:
- Tools implement ToolProvider (a Protocol, not an ABC)
- ToolRegistry holds registered tools and dispatches by name
- ToolResult is a frozen dataclass for immutable results
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("claw.tools")


@dataclass(frozen=True)
class ToolResult:
    """Immutable result from a tool execution.

    frozen=True prevents mutation after creation, ensuring results
    are safe to pass between async contexts without defensive copies.
    """

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def __post_init__(self):
        """Validate result invariants."""
        if not self.success and not self.error:
            # Use object.__setattr__ since frozen
            object.__setattr__(self, "error", "Tool execution failed (no detail)")


@runtime_checkable
class ToolProvider(Protocol):
    """Protocol for tools that can be registered with ToolRegistry.

    Using Protocol (not ABC) allows any class with matching attributes
    to be registered — no inheritance required. This enables third-party
    tools to participate without importing claw.tools.
    """

    @property
    def name(self) -> str:
        """Unique tool identifier."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description of what this tool does."""
        ...

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with given parameters."""
        ...


class ToolRegistry:
    """Registry for dynamic tool discovery and dispatch.

    Thread-safe for registration (append-only dict). Agents can query
    available tools and invoke them by name.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolProvider] = {}

    def register(self, tool: ToolProvider) -> None:
        """Register a tool. Overwrites if name already exists."""
        if not isinstance(tool, ToolProvider):
            raise TypeError(
                f"Tool must implement ToolProvider protocol, got {type(tool).__name__}"
            )
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if it existed."""
        removed = self._tools.pop(name, None)
        if removed:
            logger.info("Unregistered tool: %s", name)
        return removed is not None

    def get(self, name: str) -> ToolProvider | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, str]]:
        """Return metadata for all registered tools."""
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """Execute a tool by name. Returns error result if not found."""
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(
                success=False,
                error=f"Tool not found: {tool_name}",
            )
        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            logger.error("Tool %s failed: %s", tool_name, e)
            return ToolResult(success=False, error=str(e))

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
