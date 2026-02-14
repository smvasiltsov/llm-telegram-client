from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.errors import ToolValidationError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.name.strip().lower()
        if not name:
            raise ToolValidationError("Tool name cannot be empty")
        if name in self._tools:
            raise ToolValidationError(f"Tool '{name}' already registered")
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        key = name.strip().lower()
        tool = self._tools.get(key)
        if not tool:
            raise ToolValidationError(f"Tool '{name}' is not registered")
        return tool

    def list_tools(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for name in sorted(self._tools.keys()):
            tool = self._tools[name]
            result.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema(),
                }
            )
        return result

    async def execute(self, name: str, tool_input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        tool = self.get(name)
        return await tool.execute(tool_input, ctx)
