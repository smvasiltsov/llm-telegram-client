from __future__ import annotations

from dataclasses import dataclass


@dataclass
class User:
    telegram_user_id: int
    username: str | None
    is_authorized: bool
    created_at: str


@dataclass
class Role:
    role_id: int
    role_name: str
    description: str
    base_system_prompt: str
    extra_instruction: str
    llm_model: str | None
    is_active: bool
    mention_name: str | None = None

    def public_name(self) -> str:
        return self.mention_name or self.role_name


@dataclass
class UserRoleSession:
    telegram_user_id: int
    group_id: int
    role_id: int
    session_id: str
    created_at: str
    last_used_at: str
    team_id: int | None = None
    team_role_id: int | None = None


@dataclass
class Group:
    group_id: int
    title: str | None
    is_active: bool
    created_at: str
    team_id: int | None = None


@dataclass
class Team:
    team_id: int
    public_id: str
    name: str | None
    is_active: bool
    ext_json: str | None
    created_at: str
    updated_at: str


@dataclass
class TeamBinding:
    team_id: int
    interface_type: str
    external_id: str
    external_title: str | None
    is_active: bool
    created_at: str
    updated_at: str


@dataclass
class TeamRole:
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
    mode: str
    is_active: bool


@dataclass
class GroupRole:
    group_id: int
    role_id: int
    system_prompt_override: str | None
    display_name: str | None
    model_override: str | None
    user_prompt_suffix: str | None
    user_reply_prefix: str | None
    enabled: bool
    mode: str
    is_active: bool


@dataclass
class AuthToken:
    telegram_user_id: int
    encrypted_token: str
    created_at: str
    updated_at: str
    is_authorized: bool


@dataclass
class RolePrePostProcessing:
    group_id: int
    role_id: int
    team_role_id: int | None
    prepost_processing_id: str
    enabled: bool
    config_json: str | None
    created_at: str
    updated_at: str


@dataclass
class RoleSkill:
    group_id: int
    role_id: int
    team_role_id: int | None
    skill_id: str
    enabled: bool
    config_json: str | None
    created_at: str
    updated_at: str


@dataclass
class SkillRun:
    run_id: int
    chain_id: str
    step_index: int
    telegram_user_id: int
    chat_id: int
    role_id: int
    skill_id: str
    arguments_json: str | None
    config_json: str | None
    status: str
    ok: bool
    duration_ms: int | None
    error_text: str | None
    output_json: str | None
    created_at: str
