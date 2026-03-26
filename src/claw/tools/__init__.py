"""CLAW tools subpackage.

Provides Protocol-based tool registration and a ToolRegistry for dynamic
tool discovery and composition. Inspired by Agent_Pidgeon's MountGateway
Protocol pattern for dependency injection.

Usage:
    from claw.tools import ToolProvider, ToolResult, ToolRegistry

    class MyTool:
        @property
        def name(self) -> str:
            return "my_tool"

        @property
        def description(self) -> str:
            return "Does something useful"

        async def execute(self, **kwargs: Any) -> ToolResult:
            return ToolResult(success=True, data={"key": "value"})

    registry = ToolRegistry()
    registry.register(MyTool())
    result = await registry.execute("my_tool", param="value")
"""

from claw.tools.registry import ToolProvider, ToolResult, ToolRegistry

__all__ = ["ToolProvider", "ToolResult", "ToolRegistry"]
