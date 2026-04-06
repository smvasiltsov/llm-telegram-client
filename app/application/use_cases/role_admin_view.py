from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.contracts.errors import ErrorCode
from app.application.contracts.result import Result
from app.core.use_cases import TeamRoleState, list_team_role_states, master_roles_list_text
from app.role_catalog_service import refresh_role_catalog
from app.storage import Storage


@dataclass(frozen=True)
class MasterRolesView:
    text: str
    role_names: tuple[str, ...]


@dataclass(frozen=True)
class TeamRolesView:
    group_id: int
    roles: tuple[TeamRoleState, ...]


def build_master_roles_view(*, runtime: Any, storage: Storage) -> Result[MasterRolesView]:
    try:
        refresh_role_catalog(runtime=runtime, storage=storage)
        role_names = tuple(role.role_name for role in runtime.role_catalog.list_active())
        return Result.ok(MasterRolesView(text=master_roles_list_text(runtime), role_names=role_names))
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to build master roles view",
            fallback_details={"entity": "role_admin_view", "cause": "master_roles"},
        )


def build_team_roles_view(*, storage: Storage, group_id: int) -> Result[TeamRolesView]:
    try:
        rows = tuple(list_team_role_states(storage, group_id))
        return Result.ok(TeamRolesView(group_id=group_id, roles=rows))
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "team_binding", "id": group_id, "cause": "group_not_found"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to build team roles view",
            fallback_details={"entity": "role_admin_view", "id": group_id, "cause": "team_roles"},
        )

