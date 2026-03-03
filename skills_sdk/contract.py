from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    name: str
    version: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    mode: str = "read_only"
    permissions: tuple[str, ...] = ()
    timeout_sec: int = 30
    max_result_bytes: int = 65536


@dataclass(frozen=True)
class SkillContext:
    chain_id: str
    chat_id: int
    user_id: int
    role_id: int
    role_name: str


@dataclass(frozen=True)
class SkillResult:
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SkillProtocol(Protocol):
    def describe(self) -> SkillSpec:
        ...

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        ...

    def run(self, ctx: SkillContext, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        ...
