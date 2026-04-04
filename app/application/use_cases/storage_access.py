from __future__ import annotations

from app.application.contracts.errors import ErrorCode
from app.application.contracts.result import Result
from app.models import Role, TeamRole
from app.storage import Storage


def safe_get_role_by_name(storage: Storage, role_name: str) -> Result[Role]:
    try:
        return Result.ok(storage.get_role_by_name(role_name))
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "role", "id": role_name, "cause": "lookup_failed"},
        )


def safe_get_team_role(storage: Storage, team_id: int, role_id: int) -> Result[TeamRole]:
    try:
        return Result.ok(storage.get_team_role(team_id, role_id))
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "team_role", "id": f"team_id={team_id} role_id={role_id}", "cause": "lookup_failed"},
        )


__all__ = ["safe_get_role_by_name", "safe_get_team_role"]
