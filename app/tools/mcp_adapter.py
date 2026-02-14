from __future__ import annotations

from typing import Any

from app.tools.base import ToolContext
from app.tools.service import ToolService


class ToolMCPAdapter:
    """
    Thin adapter for future MCP integration.
    Delegates to ToolService and keeps transport-specific mapping isolated.
    """

    def __init__(self, tool_service: ToolService) -> None:
        self._tool_service = tool_service

    def list_tools(self, *, caller_id: int, owner_user_id: int) -> list[dict[str, Any]]:
        if caller_id != owner_user_id:
            return []
        return self._tool_service.list_tools()

    async def execute_tool(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        caller_id: int,
        owner_user_id: int,
        chat_id: int,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if caller_id != owner_user_id:
            return {
                "ok": False,
                "error": "forbidden",
            }
        ctx = ToolContext(
            caller_id=caller_id,
            chat_id=chat_id,
            source="mcp",
            request_id=request_id,
        )
        result = await self._tool_service.execute(tool_name, tool_input, ctx)
        return {
            "ok": result.ok,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "meta": result.meta,
        }
