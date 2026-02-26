from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    name: str
    version: str
    description: str = ""
    permissions: tuple[str, ...] = ()
    timeout_sec: int = 30


@dataclass(frozen=True)
class SkillContext:
    chain_id: str
    chat_id: int
    user_id: int
    role_id: int
    role_name: str


@dataclass(frozen=True)
class SkillResult:
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SkillProtocol(Protocol):
    def describe(self) -> SkillSpec:
        ...

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        ...

    def run(self, ctx: SkillContext, payload: dict[str, Any]) -> SkillResult:
        ...
