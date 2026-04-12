from __future__ import annotations

from typing import Literal

from .common import ApiSchema
from .entities import (
    TeamRoleDTO,
    TeamRoleRuntimeStatusDTO,
    UserRoleSessionDTO,
)


class ListRequestDTO(ApiSchema):
    team_id: int | None = None
    group_id: int | None = None
    active_only: bool = True


class GetRequestDTO(ApiSchema):
    team_id: int | None = None
    group_id: int | None = None
    role_id: int | None = None
    team_role_id: int | None = None
    user_id: int | None = None


class UpdateRequestDTO(ApiSchema):
    group_id: int
    role_id: int
    enabled: bool | None = None
    is_active: bool | None = None
    mode: Literal["normal", "orchestrator"] | None = None
    model_override: str | None = None
    system_prompt_override: str | None = None
    extra_instruction_override: str | None = None
    user_prompt_suffix: str | None = None
    user_reply_prefix: str | None = None


class ResetRequestDTO(ApiSchema):
    group_id: int
    role_id: int
    user_id: int


class DeleteRequestDTO(ApiSchema):
    group_id: int
    role_id: int
    user_id: int


class OperationResultDTO(ApiSchema):
    ok: bool
    message: str | None = None
    team_role: TeamRoleDTO | None = None
    session: UserRoleSessionDTO | None = None
    runtime_status: TeamRoleRuntimeStatusDTO | None = None
