from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol

from app.application.contracts import Result


class AuthzRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class AuthzAction(StrEnum):
    TELEGRAM_COMMANDS_ADMIN = "telegram.commands.admin"
    TELEGRAM_CALLBACKS_ADMIN = "telegram.callbacks.admin"
    TELEGRAM_BOOTSTRAP_ADMIN = "telegram.bootstrap.admin"


@dataclass(frozen=True)
class AuthzActor:
    user_id: int
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthzResourceContext:
    group_id: int | None = None
    team_id: int | None = None
    role_id: int | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class AuthzDecision:
    allowed: bool
    reason: str | None = None
    required_role: str | None = None
    policy: str | None = None


class AuthzService(Protocol):
    def authorize(
        self,
        *,
        action: str | AuthzAction,
        actor: AuthzActor,
        resource_ctx: AuthzResourceContext | None = None,
    ) -> Result[AuthzDecision]: ...

