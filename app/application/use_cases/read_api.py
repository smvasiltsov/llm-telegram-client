from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from app.application.contracts import ErrorCode, Result
from app.models import RoleCatalogError, RoleCatalogItem, TeamSessionView
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.storage import Storage

T = TypeVar("T")


@dataclass(frozen=True)
class PagedItems(Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


def list_teams_result(storage: Storage) -> Result[list]:
    try:
        return Result.ok(storage.list_teams())
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to list teams",
            fallback_details={"entity": "team", "cause": "list"},
        )


def list_team_roles_result(storage: Storage, *, team_id: int, include_inactive: bool = False) -> Result[list]:
    try:
        storage.get_team(team_id)
        return Result.ok(storage.list_roles_for_team(team_id, include_inactive=include_inactive))
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "team", "id": team_id, "cause": "roles_list"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to list team roles",
            fallback_details={"entity": "team", "id": team_id, "cause": "roles_list"},
        )


def list_team_runtime_status_result(
    storage: Storage,
    runtime_status_service: RoleRuntimeStatusService,
    *,
    team_id: int,
) -> Result[list]:
    try:
        storage.get_team(team_id)
        return Result.ok(runtime_status_service.list_team_statuses(team_id=team_id, active_only=True))
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "team", "id": team_id, "cause": "runtime_status_list"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to list team runtime statuses",
            fallback_details={"entity": "team", "id": team_id, "cause": "runtime_status_list"},
        )


def list_roles_catalog_result(
    runtime: Any,
    storage: Storage,
    *,
    include_inactive: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> Result[PagedItems[RoleCatalogItem]]:
    try:
        catalog = runtime.role_catalog
        all_items = catalog.list_all()
        issue_by_role = _issues_by_role(catalog.issues)
        orchestrator_roles = set(storage.list_enabled_orchestrator_role_names())
        filtered = [item for item in all_items if include_inactive or item.is_active]
        page = _paginate(filtered, limit=limit, offset=offset)
        return Result.ok(
            PagedItems(
                items=[
                    RoleCatalogItem(
                        role_name=item.role_name,
                        is_active=bool(item.is_active),
                        llm_model=item.llm_model,
                        is_orchestrator=item.role_name.lower() in orchestrator_roles,
                        has_errors=item.role_name.lower() in issue_by_role,
                        source=str(item.source_path),
                    )
                    for item in page.items
                ],
                total=page.total,
                limit=page.limit,
                offset=page.offset,
            )
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to list role catalog",
            fallback_details={"entity": "role_catalog", "cause": "list"},
        )


def list_roles_catalog_errors_result(runtime: Any, storage: Storage) -> Result[list[RoleCatalogError]]:
    try:
        catalog = runtime.role_catalog
        errors: list[RoleCatalogError] = []
        for issue in catalog.issues:
            role_name = _role_name_from_issue_path(issue.path)
            code, message = _split_issue_reason(issue.reason)
            errors.append(
                RoleCatalogError(
                    role_name=role_name,
                    file=str(issue.path),
                    code=code,
                    message=message,
                    details={"source": "catalog"},
                )
            )
        catalog_role_names = {item.role_name.lower() for item in catalog.list_all()}
        missing_role_names = [name for name in storage.list_active_team_role_names() if name not in catalog_role_names]
        for role_name in sorted(missing_role_names):
            errors.append(
                RoleCatalogError(
                    role_name=role_name,
                    file="<db:team_roles>",
                    code="domain.role_missing_in_catalog",
                    message=f"Role '{role_name}' is active in team bindings but missing in role catalog",
                    details={"source": "domain", "entity": "team_roles"},
                )
            )
        return Result.ok(errors)
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to list role catalog errors",
            fallback_details={"entity": "role_catalog", "cause": "errors_list"},
        )


def list_team_sessions_result(
    storage: Storage,
    *,
    team_id: int,
    limit: int = 50,
    offset: int = 0,
) -> Result[PagedItems[TeamSessionView]]:
    try:
        storage.get_team(team_id)
        items, total = storage.list_team_sessions(team_id, limit=limit, offset=offset)
        return Result.ok(
            PagedItems(
                items=items,
                total=total,
                limit=max(1, int(limit)),
                offset=max(0, int(offset)),
            )
        )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "team", "id": team_id, "cause": "sessions_list"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to list team sessions",
            fallback_details={"entity": "team", "id": team_id, "cause": "sessions_list"},
        )


def _issues_by_role(issues: list[Any]) -> dict[str, list[str]]:
    by_role: dict[str, list[str]] = {}
    for issue in issues:
        role_name = _role_name_from_issue_path(issue.path)
        by_role.setdefault(role_name, []).append(str(issue.reason))
    return by_role


def _role_name_from_issue_path(path: Path) -> str:
    return path.stem.strip().lower()


def _split_issue_reason(reason: str) -> tuple[str, str]:
    head, sep, tail = reason.partition(":")
    if sep:
        return head.strip().lower(), tail.strip() or reason
    return reason.strip().lower(), reason


def _paginate(items: list[T], *, limit: int, offset: int) -> PagedItems[T]:
    safe_limit = max(1, int(limit))
    safe_offset = max(0, int(offset))
    total = len(items)
    window = items[safe_offset : safe_offset + safe_limit]
    return PagedItems(items=window, total=total, limit=safe_limit, offset=safe_offset)
