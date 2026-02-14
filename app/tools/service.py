from __future__ import annotations

from typing import Any

from app.tools.base import ToolContext, ToolResult
from app.tools.registry import ToolRegistry


class ToolService:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def list_tools(self) -> list[dict[str, Any]]:
        return self._registry.list_tools()

    async def execute(self, tool_name: str, tool_input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return await self._registry.execute(tool_name, tool_input, ctx)
