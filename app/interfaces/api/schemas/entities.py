from __future__ import annotations

from typing import Literal

from .common import ApiSchema


class RoleDTO(ApiSchema):
    role_id: int
    role_name: str
    description: str
    base_system_prompt: str
    extra_instruction: str
    llm_model: str | None
    is_active: bool
    mention_name: str | None = None


class TeamDTO(ApiSchema):
    team_id: int
    public_id: str
    name: str | None
    is_active: bool
    ext_json: str | None
    created_at: str
    updated_at: str


class TeamBindingDTO(ApiSchema):
    team_id: int
    interface_type: str
    external_id: str
    external_title: str | None
    is_active: bool
    created_at: str
    updated_at: str


class TeamRoleDTO(ApiSchema):
    team_id: int
    role_id: int
    team_role_id: int | None
    system_prompt_override: str | None
    extra_instruction_override: str | None
    display_name: str | None
    model_override: str | None
    user_prompt_suffix: str | None
    user_reply_prefix: str | None
    enabled: bool
    mode: Literal["normal", "orchestrator"]
    is_active: bool


class UserRoleSessionDTO(ApiSchema):
    telegram_user_id: int
    group_id: int
    role_id: int
    session_id: str
    created_at: str
    last_used_at: str
    team_id: int | None = None
    team_role_id: int | None = None


class TeamRoleRuntimeStatusDTO(ApiSchema):
    team_role_id: int
    status: Literal["free", "busy"]
    status_version: int
    busy_request_id: str | None
    busy_owner_user_id: int | None
    busy_origin: str | None
    preview_text: str | None
    preview_source: str | None
    busy_since: str | None
    lease_expires_at: str | None
    last_heartbeat_at: str | None
    free_release_requested_at: str | None
    free_release_delay_until: str | None
    free_release_reason_pending: str | None
    last_release_reason: str | None
    updated_at: str
