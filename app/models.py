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


@dataclass
class UserRoleSession:
    telegram_user_id: int
    group_id: int
    role_id: int
    session_id: str
    created_at: str
    last_used_at: str


@dataclass
class Group:
    group_id: int
    title: str | None
    is_active: bool
    created_at: str


@dataclass
class GroupRole:
    group_id: int
    role_id: int
    system_prompt_override: str | None
    display_name: str | None
    model_override: str | None
    user_prompt_suffix: str | None
    user_reply_prefix: str | None
    is_active: bool


@dataclass
class AuthToken:
    telegram_user_id: int
    encrypted_token: str
    created_at: str
    updated_at: str
    is_authorized: bool
