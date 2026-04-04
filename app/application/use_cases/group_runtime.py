from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from app.application.contracts.errors import ErrorCode
from app.application.contracts.result import Result
from app.models import Role
from app.router import RouteResult, route_message
from app.roles_registry import seed_team_roles
from app.role_catalog_service import refresh_role_catalog
from app.security import TokenCipher
from app.storage import Storage
from app.utils import extract_role_mentions, strip_bot_mention


@dataclass(frozen=True)
class GroupBufferPlan:
    should_process: bool
    should_start: bool
    team_id: int | None
    role_names: tuple[str, ...]
    orchestrator_role_name: str | None


@dataclass(frozen=True)
class GroupFlushInput:
    chat_id: int
    user_id: int
    combined_text: str
    reply_text: str | None
    first_message_id: int
    bot_username: str
    owner_user_id: int
    require_bot_mention: bool


@dataclass(frozen=True)
class GroupFlushPlan:
    action: Literal["skip", "send_hint", "request_token", "dispatch_chain"]
    team_id: int | None = None
    route: RouteResult | None = None
    role_name_for_pending: str | None = None
    content_for_pending: str | None = None
    reply_to_message_id: int | None = None
    session_token: str = ""


def prepare_group_buffer_plan(
    *,
    storage: Storage,
    runtime: Any,
    chat_id: int,
    chat_title: str | None,
    user_id: int,
    text: str,
) -> Result[GroupBufferPlan]:
    try:
        refresh_role_catalog(runtime=runtime, storage=storage)
        with storage.transaction(immediate=True):
            team_id = storage.upsert_telegram_team_binding(chat_id, chat_title, is_active=True)
            seed_team_roles(storage, team_id)

        roles_for_group = storage.list_roles_for_team(team_id)
        orchestrator_group_role = storage.get_enabled_orchestrator_for_team(team_id)
        orchestrator_role = (
            next((r for r in roles_for_group if r.role_id == orchestrator_group_role.role_id), None)
            if orchestrator_group_role
            else None
        )
        if orchestrator_role is None and orchestrator_group_role is not None:
            orchestrator_role = storage.get_role_by_id(orchestrator_group_role.role_id)

        owner_user_id = runtime.owner_user_id
        if user_id != owner_user_id:
            return Result.ok(
                GroupBufferPlan(
                    should_process=False,
                    should_start=False,
                    team_id=team_id,
                    role_names=tuple(role.public_name() for role in roles_for_group),
                    orchestrator_role_name=orchestrator_role.role_name if orchestrator_role else None,
                )
            )

        bot_username = runtime.bot_username
        require_bot_mention = runtime.require_bot_mention
        mentioned = f"@{bot_username.lower()}" in text.lower()
        if orchestrator_role is not None:
            should_start = True
        elif require_bot_mention:
            should_start = mentioned
        else:
            lowered = text.lower()
            should_start = "@all" in lowered or any(f"@{role.public_name().lower()}" in lowered for role in roles_for_group)

        return Result.ok(
            GroupBufferPlan(
                should_process=True,
                should_start=should_start,
                team_id=team_id,
                role_names=tuple(role.public_name() for role in roles_for_group),
                orchestrator_role_name=orchestrator_role.role_name if orchestrator_role else None,
            )
        )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "group_buffer_plan", "id": chat_id, "cause": "value_error"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to prepare group buffer plan",
            fallback_details={"entity": "group_buffer_plan", "id": chat_id, "cause": type(exc).__name__},
        )


def _route_for_orchestrator(
    *,
    roles: list[Role],
    orchestrator_role: Role,
    combined_text: str,
    bot_username: str,
) -> RouteResult:
    cleaned = strip_bot_mention(combined_text, bot_username)
    role_map = {r.public_name().lower(): r for r in roles}
    is_all = "@all" in cleaned.lower()
    mentioned_names = extract_role_mentions(cleaned, set(role_map.keys()))
    selected_roles: list[Role] = []
    if is_all:
        selected_roles = [r for r in roles if r.role_id != orchestrator_role.role_id]
    else:
        seen_ids: set[int] = set()
        for name in mentioned_names:
            target = role_map.get(name.lower())
            if not target:
                continue
            if target.role_id == orchestrator_role.role_id:
                continue
            if target.role_id in seen_ids:
                continue
            selected_roles.append(target)
            seen_ids.add(target.role_id)
    if not selected_roles:
        selected_roles = [orchestrator_role]
    return RouteResult(roles=selected_roles, content=combined_text.strip(), is_all=is_all)


def build_group_flush_plan(
    *,
    storage: Storage,
    runtime: Any,
    data: GroupFlushInput,
    roles_require_auth_fn: Callable[..., bool],
    cipher: TokenCipher,
) -> Result[GroupFlushPlan]:
    try:
        refresh_role_catalog(runtime=runtime, storage=storage)
        team_id = storage.resolve_team_id_by_telegram_chat(data.chat_id)
        if team_id is None:
            return Result.ok(GroupFlushPlan(action="skip", team_id=None))

        roles = storage.list_roles_for_team(team_id)
        orchestrator_group_role = storage.get_enabled_orchestrator_for_team(team_id)
        orchestrator_role = (
            next((r for r in roles if r.role_id == orchestrator_group_role.role_id), None)
            if orchestrator_group_role
            else None
        )
        if orchestrator_role is None and orchestrator_group_role is not None:
            orchestrator_role = storage.get_role_by_id(orchestrator_group_role.role_id)

        if orchestrator_role is not None:
            route = _route_for_orchestrator(
                roles=roles,
                orchestrator_role=orchestrator_role,
                combined_text=data.combined_text,
                bot_username=data.bot_username,
            )
        else:
            route = route_message(
                data.combined_text,
                data.bot_username,
                roles,
                owner_user_id=data.owner_user_id,
                author_user_id=data.user_id,
                require_bot_mention=data.require_bot_mention,
            )

        if not route:
            return Result.ok(GroupFlushPlan(action="skip", team_id=team_id))
        if not route.content:
            return Result.ok(GroupFlushPlan(action="send_hint", team_id=team_id))

        with storage.transaction(immediate=True):
            storage.upsert_user(data.user_id, None)
        auth = storage.get_auth_token(data.user_id)
        requires_auth = roles_require_auth_fn(
            team_id=team_id,
            roles=route.roles,
        )
        if requires_auth and (not auth or not auth.is_authorized):
            role_name = "__all__" if route.is_all else route.roles[0].public_name()
            return Result.ok(
                GroupFlushPlan(
                    action="request_token",
                    team_id=team_id,
                    route=route,
                    role_name_for_pending=role_name,
                    content_for_pending=route.content,
                    reply_to_message_id=data.first_message_id,
                )
            )

        session_token = cipher.decrypt(auth.encrypted_token) if auth and auth.encrypted_token else ""
        return Result.ok(
            GroupFlushPlan(
                action="dispatch_chain",
                team_id=team_id,
                route=route,
                role_name_for_pending="__all__" if route.is_all else route.roles[0].public_name(),
                content_for_pending=route.content,
                reply_to_message_id=data.first_message_id,
                session_token=session_token,
            )
        )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "group_flush_plan", "id": data.chat_id, "cause": "value_error"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to build group flush plan",
            fallback_details={"entity": "group_flush_plan", "id": data.chat_id, "cause": type(exc).__name__},
        )
