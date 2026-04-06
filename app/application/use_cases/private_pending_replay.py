from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from app.application.contracts.errors import ErrorCode
from app.application.contracts.result import Result
from app.models import Role
from app.pending_store import PendingMessageRecord
from app.role_catalog_service import refresh_role_catalog
from app.security import TokenCipher
from app.storage import Storage


@dataclass(frozen=True)
class PendingReplayDispatchPlan:
    action: Literal["skip", "request_token", "dispatch"]
    chat_id: int | None = None
    team_id: int | None = None
    roles: tuple[Role, ...] = ()
    role_name: str | None = None
    content: str | None = None
    reply_text: str | None = None
    message_id: int | None = None
    session_token: str = ""
    should_drop_pending: bool = False
    should_clear_counters: bool = False
    reason: str = ""


def build_pending_replay_dispatch_plan(
    *,
    storage: Storage,
    runtime: Any,
    user_id: int,
    pending_msg: PendingMessageRecord | None,
    roles_require_auth_fn: Callable[..., bool],
    cipher: TokenCipher,
) -> Result[PendingReplayDispatchPlan]:
    try:
        if pending_msg is None:
            return Result.ok(
                PendingReplayDispatchPlan(
                    action="skip",
                    should_clear_counters=True,
                    reason="pending_not_found",
                )
            )
        refresh_role_catalog(runtime=runtime, storage=storage)
        pending_team_id = pending_msg.get("team_id")
        if pending_team_id is None:
            return Result.ok(
                PendingReplayDispatchPlan(
                    action="skip",
                    chat_id=int(pending_msg["chat_id"]),
                    should_drop_pending=True,
                    should_clear_counters=True,
                    reason="missing_team_id",
                )
            )
        team_id = int(pending_team_id)
        role_name = str(pending_msg["role_name"])
        roles = storage.list_roles_for_team(team_id)
        if role_name == "__all__":
            target_roles = tuple(roles)
        else:
            role = next((r for r in roles if r.public_name() == role_name), None)
            if role is None:
                role = next((r for r in roles if r.role_name == role_name), None)
            if role is None:
                return Result.ok(
                    PendingReplayDispatchPlan(
                        action="skip",
                        chat_id=int(pending_msg["chat_id"]),
                        team_id=team_id,
                        role_name=role_name,
                        should_clear_counters=True,
                        reason="role_not_found",
                    )
                )
            target_roles = (role,)
        auth = storage.get_auth_token(user_id)
        requires_auth = roles_require_auth_fn(team_id=team_id, roles=list(target_roles))
        if requires_auth and (not auth or not auth.is_authorized):
            return Result.ok(
                PendingReplayDispatchPlan(
                    action="request_token",
                    chat_id=int(pending_msg["chat_id"]),
                    team_id=team_id,
                    roles=target_roles,
                    role_name=role_name,
                    content=str(pending_msg["content"]),
                    reply_text=pending_msg["reply_text"],
                    message_id=int(pending_msg["message_id"]),
                    reason="auth_required",
                )
            )
        session_token = cipher.decrypt(auth.encrypted_token) if auth and auth.encrypted_token else ""
        return Result.ok(
            PendingReplayDispatchPlan(
                action="dispatch",
                chat_id=int(pending_msg["chat_id"]),
                team_id=team_id,
                roles=target_roles,
                role_name=role_name,
                content=str(pending_msg["content"]),
                reply_text=pending_msg["reply_text"],
                message_id=int(pending_msg["message_id"]),
                session_token=session_token,
                reason="ready",
            )
        )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "pending_replay_dispatch_plan", "id": user_id, "cause": "value_error"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to build pending replay dispatch plan",
            fallback_details={"entity": "pending_replay_dispatch_plan", "id": user_id, "cause": type(exc).__name__},
        )

