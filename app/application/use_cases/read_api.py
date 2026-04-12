from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from app.application.contracts import ErrorCode, Result
from app.models import MasterRoleCatalogItem, RoleCatalogError, RoleCatalogItem, RoleLinkedItem, TeamSessionView
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.storage import Storage

T = TypeVar("T")


@dataclass(frozen=True)
class PagedItems(Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class RegistryItem:
    id: str
    name: str
    description: str
    source: str | None


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


def list_team_roles_result(
    storage: Storage,
    *,
    team_id: int,
    include_inactive: bool = False,
    runtime: Any | None = None,
) -> Result[list]:
    try:
        storage.get_team(team_id)
        roles = list(storage.list_roles_for_team(team_id, include_inactive=include_inactive))
        if runtime is None:
            return Result.ok(roles)
        skills_by_id = _skill_names_by_id(runtime)
        prepost_by_id = _prepost_names_by_id(runtime)
        enriched = []
        for role in roles:
            team_role_id = storage.resolve_team_role_id(team_id, role.role_id)
            if team_role_id is None:
                enriched.append(role)
                continue
            skills = sorted(
                (
                    RoleLinkedItem(
                        id=str(item.skill_id),
                        name=str(skills_by_id.get(str(item.skill_id), str(item.skill_id))),
                    )
                    for item in storage.list_role_skills_for_team_role(team_role_id, enabled_only=True)
                    if bool(item.enabled)
                ),
                key=lambda item: item.id,
            )
            prepost = sorted(
                (
                    RoleLinkedItem(
                        id=str(item.prepost_processing_id),
                        name=str(prepost_by_id.get(str(item.prepost_processing_id), str(item.prepost_processing_id))),
                    )
                    for item in storage.list_role_prepost_processing_for_team_role(team_role_id, enabled_only=True)
                    if bool(item.enabled)
                ),
                key=lambda item: item.id,
            )
            enriched.append(
                type(role)(
                    role_id=role.role_id,
                    role_name=role.role_name,
                    description=role.description,
                    base_system_prompt=role.base_system_prompt,
                    extra_instruction=role.extra_instruction,
                    llm_model=role.llm_model,
                    is_active=role.is_active,
                    mention_name=role.mention_name,
                    is_orchestrator=role.is_orchestrator,
                    team_role_id=role.team_role_id,
                    working_dir=role.working_dir,
                    root_dir=role.root_dir,
                    skills=tuple(skills),
                    pre_processing_tools=tuple(prepost),
                    post_processing_tools=tuple(prepost),
                )
            )
        return Result.ok(enriched)
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


def list_master_roles_catalog_result(
    runtime: Any,
    storage: Storage,
    *,
    include_inactive: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> Result[PagedItems[MasterRoleCatalogItem]]:
    try:
        catalog = runtime.role_catalog
        all_items = list(catalog.list_all())
        issue_by_role = _issues_by_role(catalog.issues)
        roles_by_name = {item.role_name.lower(): item for item in storage.list_roles()}
        # Backward compatibility: keep query param accepted but ignore for master-role catalog contract.
        _ = include_inactive
        filtered = all_items
        page = _paginate(filtered, limit=limit, offset=offset)
        return Result.ok(
            PagedItems(
                items=[
                    MasterRoleCatalogItem(
                        role_id=int(getattr(roles_by_name.get(item.role_name.lower()), "role_id", 0) or 0),
                        role_name=item.role_name,
                        llm_model=item.llm_model,
                        system_prompt=item.base_system_prompt,
                        extra_instruction=item.extra_instruction,
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
            fallback_message="Failed to list master role catalog",
            fallback_details={"entity": "master_role_catalog", "cause": "list"},
        )


def list_skills_result(runtime: Any) -> Result[list[RegistryItem]]:
    try:
        registry = getattr(runtime, "skills_registry", None)
        specs = list(getattr(registry, "list_specs", lambda: [])())
        items = sorted(
            (
                RegistryItem(
                    id=str(spec.skill_id),
                    name=str(spec.name),
                    description=str(getattr(spec, "description", "") or ""),
                    source=_registry_source(registry, str(spec.skill_id), root_package="skills"),
                )
                for spec in specs
            ),
            key=lambda item: item.id,
        )
        return Result.ok(items)
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to list skills",
            fallback_details={"entity": "skills_registry", "cause": "list"},
        )


def list_pre_processing_tools_result(runtime: Any) -> Result[list[RegistryItem]]:
    return list_prepost_processing_tools_result(runtime)


def list_post_processing_tools_result(runtime: Any) -> Result[list[RegistryItem]]:
    return list_prepost_processing_tools_result(runtime)


def list_prepost_processing_tools_result(runtime: Any) -> Result[list[RegistryItem]]:
    return _list_prepost_tools_result(runtime)


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


def _skill_names_by_id(runtime: Any) -> dict[str, str]:
    registry = getattr(runtime, "skills_registry", None)
    specs = list(getattr(registry, "list_specs", lambda: [])())
    return {str(spec.skill_id): str(spec.name) for spec in specs}


def _prepost_names_by_id(runtime: Any) -> dict[str, str]:
    registry = getattr(runtime, "prepost_processing_registry", None)
    specs = list(getattr(registry, "list_specs", lambda: [])())
    return {str(spec.prepost_processing_id): str(spec.name) for spec in specs}


def _list_prepost_tools_result(runtime: Any) -> Result[list[RegistryItem]]:
    try:
        registry = getattr(runtime, "prepost_processing_registry", None)
        specs = list(getattr(registry, "list_specs", lambda: [])())
        items = sorted(
            (
                RegistryItem(
                    id=str(spec.prepost_processing_id),
                    name=str(spec.name),
                    description=str(getattr(spec, "description", "") or ""),
                    source=_registry_source(
                        registry,
                        str(spec.prepost_processing_id),
                        root_package="prepost_processing",
                    ),
                )
                for spec in specs
            ),
            key=lambda item: item.id,
        )
        return Result.ok(items)
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to list pre/post processing tools",
            fallback_details={"entity": "prepost_processing_registry", "cause": "list"},
        )


def _registry_source(registry: Any, item_id: str, *, root_package: str) -> str | None:
    if registry is None:
        return None
    record = getattr(registry, "get", lambda _id: None)(item_id)
    if record is None:
        return None
    module_name = str(getattr(getattr(record, "instance", None), "__class__", object).__module__ or "").strip()
    prefix = f"{root_package}."
    if not module_name.startswith(prefix):
        return None
    parts = module_name.split(".")
    if len(parts) < 2:
        return None
    folder_name = str(parts[1]).strip()
    if not folder_name:
        return None
    root = Path(__file__).resolve().parents[3]
    candidate = (root / root_package / folder_name).resolve()
    try:
        rel = candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.exists() or not candidate.is_dir():
        return None
    return rel.as_posix()
