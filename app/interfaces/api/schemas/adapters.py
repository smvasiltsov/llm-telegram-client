from __future__ import annotations

from typing import Any

from app.application.contracts.result import Result
from app.models import Role, Team, TeamBinding, TeamRole, TeamRoleRuntimeStatus, UserRoleSession

from .entities import (
    RoleDTO,
    TeamBindingDTO,
    TeamDTO,
    TeamRoleDTO,
    TeamRoleRuntimeStatusDTO,
    UserRoleSessionDTO,
)
from .operations import (
    DeleteRequestDTO,
    GetRequestDTO,
    ListRequestDTO,
    OperationResultDTO,
    ResetRequestDTO,
    UpdateRequestDTO,
)


def role_to_dto(value: Role) -> RoleDTO:
    return RoleDTO.model_validate(value)


def team_to_dto(value: Team) -> TeamDTO:
    return TeamDTO.model_validate(value)


def team_binding_to_dto(value: TeamBinding) -> TeamBindingDTO:
    return TeamBindingDTO.model_validate(value)


def team_role_to_dto(value: TeamRole) -> TeamRoleDTO:
    return TeamRoleDTO.model_validate(value)


def user_role_session_to_dto(value: UserRoleSession) -> UserRoleSessionDTO:
    return UserRoleSessionDTO.model_validate(value)


def team_role_runtime_status_to_dto(value: TeamRoleRuntimeStatus) -> TeamRoleRuntimeStatusDTO:
    return TeamRoleRuntimeStatusDTO.model_validate(value)


def list_request_to_params(value: ListRequestDTO) -> dict[str, Any]:
    return value.model_dump(exclude_none=True)


def get_request_to_params(value: GetRequestDTO) -> dict[str, Any]:
    return value.model_dump(exclude_none=True)


def update_request_to_patch(value: UpdateRequestDTO) -> dict[str, Any]:
    return value.model_dump(exclude_none=True)


def reset_request_to_params(value: ResetRequestDTO) -> dict[str, Any]:
    return value.model_dump()


def delete_request_to_params(value: DeleteRequestDTO) -> dict[str, Any]:
    return value.model_dump()


def operation_result_to_dto(
    value: Result[Any],
    *,
    message: str | None = None,
) -> OperationResultDTO:
    if value.is_error:
        return OperationResultDTO(ok=False, message=(value.error.message if value.error else message))
    payload = value.value
    if isinstance(payload, TeamRole):
        return OperationResultDTO(ok=True, message=message, team_role=team_role_to_dto(payload))
    if isinstance(payload, UserRoleSession):
        return OperationResultDTO(ok=True, message=message, session=user_role_session_to_dto(payload))
    if isinstance(payload, TeamRoleRuntimeStatus):
        return OperationResultDTO(ok=True, message=message, runtime_status=team_role_runtime_status_to_dto(payload))
    if isinstance(payload, str):
        return OperationResultDTO(ok=True, message=payload)
    return OperationResultDTO(ok=True, message=message)
