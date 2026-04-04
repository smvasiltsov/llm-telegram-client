from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.application.contracts.errors import ErrorCode
from app.application.contracts.result import Result
from app.storage import Storage


@dataclass(frozen=True)
class PendingFieldReplayPlan:
    action: Literal[
        "request_again",
        "suppress_and_drop",
        "noop",
        "missing_pending_message",
        "restore_and_request",
    ]
    should_delete_saved_value: bool = False


def is_role_scoped_pending_field(state: dict[str, object]) -> bool:
    return isinstance(state.get("role_id"), int)


def is_same_pending_field_state(left: dict[str, object], right: dict[str, object]) -> bool:
    return (
        str(left.get("provider_id", "")) == str(right.get("provider_id", ""))
        and str(left.get("key", "")) == str(right.get("key", ""))
        and left.get("role_id") == right.get("role_id")
        and left.get("team_id") == right.get("team_id")
    )


def is_root_dir_pending_field(state: dict[str, object]) -> bool:
    return str(state.get("key", "")).strip().lower() == "root_dir"


def normalize_pending_field_value(state: dict[str, object], raw_text: str) -> Result[str]:
    value = raw_text.strip()
    if not value:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "Значение не может быть пустым. Попробуй ещё раз.",
            details={"field": str(state.get("key", "")), "entity": "provider_user_field", "cause": "empty"},
        )

    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1].strip()

    if str(state.get("key", "")).lower() == "auth_token":
        lowered = value.lower()
        if lowered.startswith("cookie:"):
            value = value.split(":", 1)[1].strip()
        lowered = value.lower()
        if lowered.startswith("sessionid="):
            value = value.split("=", 1)[1].strip()
        if ";" in value:
            value = value.split(";", 1)[0].strip()

    return Result.ok(value)


def validate_pending_field_value(state: dict[str, object], value: str) -> str | None:
    key = str(state.get("key", "")).strip().lower()
    if key != "root_dir":
        return None
    root_path = Path(value).expanduser()
    if not root_path.exists():
        return f"Путь не существует: {root_path}"
    if not root_path.is_dir():
        return f"Путь не является директорией: {root_path}"
    return None


def set_provider_user_field_from_pending_state(storage: Storage, state: dict[str, object], value: str) -> None:
    provider_id = str(state["provider_id"])
    key = str(state["key"])
    role_id = state.get("role_id")
    if isinstance(role_id, int):
        team_id = state.get("team_id")
        if not isinstance(team_id, int):
            raise ValueError("pending role-scoped field has no team_id")
        team_role_id = storage.resolve_team_role_id(team_id, role_id, ensure_exists=True)
        if team_role_id is None:
            raise ValueError(f"team_role_id not found for team_id={team_id} role_id={role_id}")
        storage.set_provider_user_value_by_team_role(provider_id, key, int(team_role_id), value)
        return
    storage.set_provider_user_value(provider_id, key, None, value)


def delete_provider_user_field_from_pending_state(storage: Storage, state: dict[str, object]) -> None:
    provider_id = str(state["provider_id"])
    key = str(state["key"])
    role_id = state.get("role_id")
    if isinstance(role_id, int):
        team_id = state.get("team_id")
        if not isinstance(team_id, int):
            return
        team_role_id = storage.resolve_team_role_id(team_id, role_id)
        if team_role_id is None:
            return
        storage.delete_provider_user_value_by_team_role(provider_id, key, int(team_role_id))
        return
    storage.delete_provider_user_value(provider_id, key, None)


def build_pending_field_replay_plan(
    *,
    state: dict[str, object],
    replay_pending_state: dict[str, object] | None,
    pending_msg_exists: bool,
    replay_attempts: int,
    max_retries: int,
) -> PendingFieldReplayPlan:
    role_scoped = is_role_scoped_pending_field(state)
    if replay_pending_state:
        if role_scoped and is_same_pending_field_state(replay_pending_state, state):
            if replay_attempts <= max_retries:
                return PendingFieldReplayPlan(action="request_again")
            return PendingFieldReplayPlan(action="suppress_and_drop")
        return PendingFieldReplayPlan(action="noop", should_delete_saved_value=not role_scoped)

    if not pending_msg_exists:
        return PendingFieldReplayPlan(action="missing_pending_message", should_delete_saved_value=not role_scoped)

    return PendingFieldReplayPlan(action="restore_and_request", should_delete_saved_value=not role_scoped)
