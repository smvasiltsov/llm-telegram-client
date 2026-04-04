from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.application.contracts.errors import ErrorCode
from app.application.contracts.result import Result
from app.core.use_cases import get_team_role_state, set_team_role_enabled, set_team_role_mode
from app.core.use_cases.team_roles import TeamRoleState
from app.storage import Storage


RoleAction = Literal["toggle_enabled", "set_mode_orchestrator", "set_mode_normal"]


@dataclass(frozen=True)
class RoleActionRequest:
    action: RoleAction
    group_id: int
    role_id: int


@dataclass(frozen=True)
class RoleActionOutcome:
    state: TeamRoleState
    previous_orchestrator_role_id: int | None = None


def execute_role_action(storage: Storage, request: RoleActionRequest) -> Result[RoleActionOutcome]:
    try:
        current = get_team_role_state(storage, request.group_id, request.role_id)
        if request.action == "toggle_enabled":
            updated = set_team_role_enabled(
                storage,
                group_id=request.group_id,
                role_id=request.role_id,
                enabled=not current.enabled,
            )
            return Result.ok(RoleActionOutcome(state=updated, previous_orchestrator_role_id=None))
        if request.action == "set_mode_orchestrator":
            updated, previous = set_team_role_mode(
                storage,
                group_id=request.group_id,
                role_id=request.role_id,
                mode="orchestrator",
            )
            return Result.ok(RoleActionOutcome(state=updated, previous_orchestrator_role_id=previous))
        if request.action == "set_mode_normal":
            updated, previous = set_team_role_mode(
                storage,
                group_id=request.group_id,
                role_id=request.role_id,
                mode="normal",
            )
            return Result.ok(RoleActionOutcome(state=updated, previous_orchestrator_role_id=previous))
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            f"Unsupported role action: {request.action}",
            details={"field": "action", "entity": "callback_role_action", "cause": "unsupported_action"},
        )
    except ValueError as exc:
        if request.action == "toggle_enabled":
            return Result.fail_from_exception(
                exc,
                fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
                fallback_message=f"Не удалось изменить статус роли: {exc}",
                fallback_details={"entity": "team_role", "id": request.role_id, "cause": "toggle_enabled"},
            )
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_message=f"Не удалось изменить режим роли: {exc}",
            fallback_details={"entity": "team_role", "id": request.role_id, "cause": request.action},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Не удалось выполнить действие роли.",
            fallback_details={"entity": "team_role", "id": request.role_id, "cause": type(exc).__name__},
        )
