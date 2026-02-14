from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolContext:
    caller_id: int
    chat_id: int
    source: str
    request_id: str | None = None
    timeout_sec: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    meta: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    def input_schema(self) -> dict[str, Any]: ...

    async def execute(self, tool_input: dict[str, Any], ctx: ToolContext) -> ToolResult: ...
