from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from app.application.contracts import ErrorCode, Result
from app.storage import Storage

T = TypeVar("T")


@dataclass(frozen=True)
class TeamRolePatchRequest:
    enabled: bool | None = None
    is_active: bool | None = None
    is_orchestrator: bool | None = None
    model_override: str | None = None
    display_name: str | None = None
    system_prompt_override: str | None = None
    extra_instruction_override: str | None = None
    user_prompt_suffix: str | None = None
    user_reply_prefix: str | None = None


@dataclass(frozen=True)
class TeamRolePatchOutcome:
    team_id: int
    role_id: int
    team_role_id: int | None
    enabled: bool
    is_active: bool
    mode: str
    is_orchestrator: bool
    model_override: str | None
    display_name: str | None
    system_prompt_override: str | None
    extra_instruction_override: str | None
    user_prompt_suffix: str | None
    user_reply_prefix: str | None


@dataclass(frozen=True)
class MutationAck:
    ok: bool
    team_id: int
    role_id: int
    telegram_user_id: int
    team_role_id: int | None = None
    operation: str = ""


@dataclass(frozen=True)
class TeamRoleSkillPutRequest:
    team_role_id: int
    skill_id: str
    enabled: bool
    config: dict[str, Any] | None = None


@dataclass(frozen=True)
class TeamRoleSkillReplaceItem:
    skill_id: str
    enabled: bool = True
    config: dict[str, Any] | None = None


@dataclass(frozen=True)
class TeamRoleSkillsReplaceRequest:
    team_role_id: int
    items: tuple[TeamRoleSkillReplaceItem, ...]


@dataclass(frozen=True)
class TeamRolePrepostPutRequest:
    team_role_id: int
    prepost_id: str
    enabled: bool
    config: dict[str, Any] | None = None


@dataclass(frozen=True)
class TeamRolePrepostReplaceItem:
    prepost_id: str
    enabled: bool = True
    config: dict[str, Any] | None = None


@dataclass(frozen=True)
class TeamRolePrepostReplaceRequest:
    team_role_id: int
    items: tuple[TeamRolePrepostReplaceItem, ...]


@dataclass(frozen=True)
class TeamRoleSkillOutcome:
    team_role_id: int
    skill_id: str
    enabled: bool
    config: dict[str, Any] | None


@dataclass(frozen=True)
class TeamRolePrepostOutcome:
    team_role_id: int
    prepost_id: str
    enabled: bool
    config: dict[str, Any] | None


@dataclass(frozen=True)
class TeamRoleSkillsReplaceOutcome:
    items: tuple[TeamRoleSkillOutcome, ...]


@dataclass(frozen=True)
class TeamRolePrepostReplaceOutcome:
    items: tuple[TeamRolePrepostOutcome, ...]


@dataclass(frozen=True)
class TeamRoleWorkingDirPutRequest:
    team_role_id: int
    working_dir: str


@dataclass(frozen=True)
class TeamRoleRootDirPutRequest:
    team_role_id: int
    root_dir: str


@dataclass(frozen=True)
class TeamRoleWorkingDirOutcome:
    team_role_id: int
    working_dir: str


@dataclass(frozen=True)
class TeamRoleRootDirOutcome:
    team_role_id: int
    root_dir: str


@dataclass(frozen=True)
class MasterRolePatchRequest:
    role_name: str | None = None
    llm_model: str | None = None
    system_prompt: str | None = None
    extra_instruction: str | None = None


@dataclass(frozen=True)
class MasterRoleCreateRequest:
    role_name: str
    system_prompt: str
    llm_model: str
    description: str | None = None
    extra_instruction: str | None = None


@dataclass(frozen=True)
class MasterRolePatchOutcome:
    role_id: int
    role_name: str
    llm_model: str | None
    system_prompt: str
    extra_instruction: str


@dataclass(frozen=True)
class MasterRoleCreateOutcome:
    role_id: int
    role_name: str
    llm_model: str | None
    system_prompt: str
    extra_instruction: str
    description: str
    is_active: bool


@dataclass(frozen=True)
class TeamCreateRequest:
    name: str


@dataclass(frozen=True)
class TeamCreateOutcome:
    team_id: int
    public_id: str
    name: str | None
    is_active: bool
    ext_json: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TeamRenameRequest:
    name: str


@dataclass(frozen=True)
class TeamRenameOutcome:
    team_id: int
    public_id: str
    name: str | None
    is_active: bool
    ext_json: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DeleteTeamOutcome:
    team_id: int


@dataclass(frozen=True)
class DeleteMasterRoleOutcome:
    role_id: int


@dataclass(frozen=True)
class TeamRoleBindOutcome:
    team_id: int
    role_id: int
    team_role_id: int | None
    enabled: bool
    is_active: bool
    mode: str
    is_orchestrator: bool
    model_override: str | None
    display_name: str | None
    system_prompt_override: str | None
    extra_instruction_override: str | None
    user_prompt_suffix: str | None
    user_reply_prefix: str | None
    created_or_reactivated: bool


@dataclass(frozen=True)
class _IdempotencyRecord:
    fingerprint: str
    result: Result[Any]


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], _IdempotencyRecord] = {}

    def execute(
        self,
        *,
        operation: str,
        key: str,
        fingerprint: str,
        apply_fn: Callable[[], Result[T]],
    ) -> Result[T]:
        cache_key = (operation, key)
        existing = self._records.get(cache_key)
        if existing is not None:
            if existing.fingerprint != fingerprint:
                return Result.fail(
                    ErrorCode.VALIDATION_INVALID_INPUT,
                    "Idempotency key is already used with a different payload",
                    details={"entity": "idempotency", "cause": "payload_mismatch", "operation": operation},
                )
            return existing.result  # type: ignore[return-value]

        result = apply_fn()
        self._records[cache_key] = _IdempotencyRecord(fingerprint=fingerprint, result=result)
        return result


def patch_team_role_result(
    storage: Storage,
    *,
    team_role_id: int,
    patch: TeamRolePatchRequest,
) -> Result[TeamRolePatchOutcome]:
    if all(
        value is None
        for value in (
            patch.enabled,
            patch.is_active,
            patch.is_orchestrator,
            patch.model_override,
            patch.display_name,
            patch.system_prompt_override,
            patch.extra_instruction_override,
            patch.user_prompt_suffix,
            patch.user_reply_prefix,
        )
    ):
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "Patch payload is empty",
            details={"entity": "team_role", "cause": "empty_patch"},
        )
    if patch.enabled is not None and patch.is_active is not None and patch.enabled != patch.is_active:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "enabled and is_active must match when both are provided",
            details={"entity": "team_role", "cause": "state_fields_conflict"},
        )
    effective_active = patch.is_active if patch.is_active is not None else patch.enabled
    if patch.is_orchestrator is True and effective_active is False:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "Orchestrator role cannot be disabled in the same patch request",
            details={"entity": "team_role", "cause": "orchestrator_enabled_invariant"},
        )
    try:
        with storage.transaction(immediate=True):
            identity = storage.resolve_team_role_identity(team_role_id)
            if identity is None:
                raise ValueError(f"Team role not found: team_role_id={team_role_id}")
            team_id = int(identity[0])
            role_id = int(identity[1])
            storage.get_team(team_id)
            storage.get_team_role(team_id, role_id)
            if patch.display_name is not None:
                storage.set_team_role_display_name(team_id, role_id, patch.display_name)
            if patch.system_prompt_override is not None:
                storage.set_team_role_prompt(team_id, role_id, patch.system_prompt_override)
            if patch.extra_instruction_override is not None:
                storage.set_team_role_extra_instruction(team_id, role_id, patch.extra_instruction_override)
            if patch.user_prompt_suffix is not None:
                storage.set_team_role_user_prompt_suffix(team_id, role_id, patch.user_prompt_suffix)
            if patch.user_reply_prefix is not None:
                storage.set_team_role_user_reply_prefix(team_id, role_id, patch.user_reply_prefix)
            if patch.model_override is not None:
                storage.set_team_role_model(team_id, role_id, patch.model_override)
            if patch.is_orchestrator is not None:
                storage.set_team_role_mode(team_id, role_id, "orchestrator" if patch.is_orchestrator else "normal")
            if effective_active is not None:
                storage.set_team_role_active(team_id, role_id, effective_active)
            current = storage.get_team_role(team_id, role_id)
            return Result.ok(
                TeamRolePatchOutcome(
                    team_id=team_id,
                    role_id=role_id,
                    team_role_id=current.team_role_id,
                    enabled=current.is_active,
                    is_active=current.is_active,
                    mode=current.mode,
                    is_orchestrator=(current.mode == "orchestrator"),
                    model_override=current.model_override,
                    display_name=current.display_name,
                    system_prompt_override=current.system_prompt_override,
                    extra_instruction_override=current.extra_instruction_override,
                    user_prompt_suffix=current.user_prompt_suffix,
                    user_reply_prefix=current.user_reply_prefix,
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "team_role", "id": f"team_role_id={team_role_id}", "cause": "patch"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to patch team role",
            fallback_details={"entity": "team_role", "id": f"team_role_id={team_role_id}", "cause": "patch"},
        )


def reset_team_role_session_write_result(
    runtime: Any,
    storage: Storage,
    *,
    team_role_id: int,
    telegram_user_id: int,
    idempotency_key: str,
) -> Result[MutationAck]:
    return _execute_with_idempotency(
        runtime=runtime,
        operation="reset_session",
        idempotency_key=idempotency_key,
        fingerprint_payload={"team_role_id": team_role_id, "telegram_user_id": telegram_user_id},
        apply_fn=lambda: _reset_team_role_session_once(
            runtime=runtime,
            storage=storage,
            team_role_id=team_role_id,
            telegram_user_id=telegram_user_id,
        ),
    )


def deactivate_team_role_binding_write_result(
    runtime: Any,
    storage: Storage,
    *,
    team_role_id: int,
    telegram_user_id: int,
    idempotency_key: str,
) -> Result[MutationAck]:
    return _execute_with_idempotency(
        runtime=runtime,
        operation="deactivate_binding",
        idempotency_key=idempotency_key,
        fingerprint_payload={"team_role_id": team_role_id, "telegram_user_id": telegram_user_id},
        apply_fn=lambda: _deactivate_team_role_binding_once(
            runtime=runtime,
            storage=storage,
            team_role_id=team_role_id,
            telegram_user_id=telegram_user_id,
        ),
    )


def put_team_role_skill_result(
    runtime: Any,
    storage: Storage,
    *,
    request: TeamRoleSkillPutRequest,
) -> Result[TeamRoleSkillOutcome]:
    if not _skill_exists(runtime, request.skill_id):
        return Result.fail(
            ErrorCode.STORAGE_NOT_FOUND,
            f"Skill not found: {request.skill_id}",
            details={"entity": "skill", "id": request.skill_id, "cause": "not_found"},
        )
    try:
        with storage.transaction(immediate=True):
            if storage.resolve_team_role_identity(request.team_role_id) is None:
                raise ValueError(f"Team role not found: team_role_id={request.team_role_id}")
            current = storage.get_role_skill_for_team_role(request.team_role_id, request.skill_id)
            if current is None:
                storage.upsert_role_skill_for_team_role(
                    request.team_role_id,
                    request.skill_id,
                    enabled=request.enabled,
                    config=request.config,
                )
            else:
                storage.set_role_skill_enabled_for_team_role(request.team_role_id, request.skill_id, request.enabled)
                if request.config is not None:
                    storage.set_role_skill_config_for_team_role(request.team_role_id, request.skill_id, request.config)
            updated = storage.get_role_skill_for_team_role(request.team_role_id, request.skill_id)
            if updated is None:
                raise RuntimeError("Failed to upsert team role skill")
            return Result.ok(
                TeamRoleSkillOutcome(
                    team_role_id=request.team_role_id,
                    skill_id=request.skill_id,
                    enabled=updated.enabled,
                    config=_json_or_none(updated.config_json),
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "skill_binding", "id": f"{request.team_role_id}:{request.skill_id}", "cause": "put"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to update team-role skill state",
            fallback_details={"entity": "skill_binding", "id": f"{request.team_role_id}:{request.skill_id}", "cause": "put"},
        )


def replace_team_role_skills_result(
    runtime: Any,
    storage: Storage,
    *,
    request: TeamRoleSkillsReplaceRequest,
) -> Result[TeamRoleSkillsReplaceOutcome]:
    seen: set[str] = set()
    normalized_items: list[TeamRoleSkillReplaceItem] = []
    for item in request.items:
        skill_id = str(item.skill_id or "").strip()
        if not skill_id:
            return Result.fail(
                ErrorCode.VALIDATION_INVALID_INPUT,
                "skill_id must be a non-empty string",
                details={"entity": "skill_binding", "cause": "invalid_skill_id"},
            )
        if skill_id in seen:
            return Result.fail(
                ErrorCode.VALIDATION_INVALID_INPUT,
                f"Duplicate skill_id in request: {skill_id}",
                details={"entity": "skill_binding", "id": skill_id, "cause": "duplicate_id"},
            )
        if not _skill_exists(runtime, skill_id):
            return Result.fail(
                ErrorCode.STORAGE_NOT_FOUND,
                f"Skill not found: {skill_id}",
                details={"entity": "skill", "id": skill_id, "cause": "not_found"},
            )
        seen.add(skill_id)
        normalized_items.append(
            TeamRoleSkillReplaceItem(
                skill_id=skill_id,
                enabled=bool(item.enabled),
                config=item.config,
            )
        )
    try:
        with storage.transaction(immediate=True):
            if storage.resolve_team_role_identity(request.team_role_id) is None:
                raise ValueError(f"Team role not found: team_role_id={request.team_role_id}")
            current = storage.list_role_skills_for_team_role(request.team_role_id, enabled_only=False)
            current_ids = {str(item.skill_id) for item in current}
            requested_ids = {item.skill_id for item in normalized_items}
            for skill_id in sorted(current_ids - requested_ids):
                storage.delete_role_skill_for_team_role(request.team_role_id, skill_id)
            for item in normalized_items:
                existing = storage.get_role_skill_for_team_role(request.team_role_id, item.skill_id)
                if existing is None:
                    storage.upsert_role_skill_for_team_role(
                        request.team_role_id,
                        item.skill_id,
                        enabled=item.enabled,
                        config=item.config,
                    )
                    continue
                storage.set_role_skill_enabled_for_team_role(request.team_role_id, item.skill_id, item.enabled)
                if item.config is not None:
                    storage.set_role_skill_config_for_team_role(request.team_role_id, item.skill_id, item.config)
            updated = storage.list_role_skills_for_team_role(request.team_role_id, enabled_only=False)
            return Result.ok(
                TeamRoleSkillsReplaceOutcome(
                    items=tuple(
                        TeamRoleSkillOutcome(
                            team_role_id=request.team_role_id,
                            skill_id=str(item.skill_id),
                            enabled=bool(item.enabled),
                            config=_json_or_none(item.config_json),
                        )
                        for item in updated
                    )
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "skill_binding", "id": f"team_role_id={request.team_role_id}", "cause": "replace"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to replace team-role skills",
            fallback_details={"entity": "skill_binding", "id": f"team_role_id={request.team_role_id}", "cause": "replace"},
        )


def put_team_role_prepost_result(
    runtime: Any,
    storage: Storage,
    *,
    request: TeamRolePrepostPutRequest,
) -> Result[TeamRolePrepostOutcome]:
    if not _prepost_exists(runtime, request.prepost_id):
        return Result.fail(
            ErrorCode.STORAGE_NOT_FOUND,
            f"Pre/post processing not found: {request.prepost_id}",
            details={"entity": "prepost_processing", "id": request.prepost_id, "cause": "not_found"},
        )
    try:
        with storage.transaction(immediate=True):
            if storage.resolve_team_role_identity(request.team_role_id) is None:
                raise ValueError(f"Team role not found: team_role_id={request.team_role_id}")
            current = storage.get_role_prepost_processing_for_team_role(request.team_role_id, request.prepost_id)
            if current is None:
                storage.upsert_role_prepost_processing_for_team_role(
                    request.team_role_id,
                    request.prepost_id,
                    enabled=request.enabled,
                    config=request.config,
                )
            else:
                storage.set_role_prepost_processing_enabled_for_team_role(
                    request.team_role_id,
                    request.prepost_id,
                    request.enabled,
                )
                if request.config is not None:
                    storage.set_role_prepost_processing_config_for_team_role(
                        request.team_role_id,
                        request.prepost_id,
                        request.config,
                    )
            updated = storage.get_role_prepost_processing_for_team_role(request.team_role_id, request.prepost_id)
            if updated is None:
                raise RuntimeError("Failed to upsert team role pre/post processing")
            return Result.ok(
                TeamRolePrepostOutcome(
                    team_role_id=request.team_role_id,
                    prepost_id=request.prepost_id,
                    enabled=updated.enabled,
                    config=_json_or_none(updated.config_json),
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "prepost_binding", "id": f"{request.team_role_id}:{request.prepost_id}", "cause": "put"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to update team-role pre/post processing state",
            fallback_details={"entity": "prepost_binding", "id": f"{request.team_role_id}:{request.prepost_id}", "cause": "put"},
        )


def replace_team_role_prepost_result(
    runtime: Any,
    storage: Storage,
    *,
    request: TeamRolePrepostReplaceRequest,
) -> Result[TeamRolePrepostReplaceOutcome]:
    seen: set[str] = set()
    normalized_items: list[TeamRolePrepostReplaceItem] = []
    for item in request.items:
        prepost_id = str(item.prepost_id or "").strip()
        if not prepost_id:
            return Result.fail(
                ErrorCode.VALIDATION_INVALID_INPUT,
                "prepost_id must be a non-empty string",
                details={"entity": "prepost_binding", "cause": "invalid_prepost_id"},
            )
        if prepost_id in seen:
            return Result.fail(
                ErrorCode.VALIDATION_INVALID_INPUT,
                f"Duplicate prepost_id in request: {prepost_id}",
                details={"entity": "prepost_binding", "id": prepost_id, "cause": "duplicate_id"},
            )
        if not _prepost_exists(runtime, prepost_id):
            return Result.fail(
                ErrorCode.STORAGE_NOT_FOUND,
                f"Pre/post processing not found: {prepost_id}",
                details={"entity": "prepost_processing", "id": prepost_id, "cause": "not_found"},
            )
        seen.add(prepost_id)
        normalized_items.append(
            TeamRolePrepostReplaceItem(
                prepost_id=prepost_id,
                enabled=bool(item.enabled),
                config=item.config,
            )
        )
    try:
        with storage.transaction(immediate=True):
            if storage.resolve_team_role_identity(request.team_role_id) is None:
                raise ValueError(f"Team role not found: team_role_id={request.team_role_id}")
            current = storage.list_role_prepost_processing_for_team_role(request.team_role_id, enabled_only=False)
            current_ids = {str(item.prepost_processing_id) for item in current}
            requested_ids = {item.prepost_id for item in normalized_items}
            for prepost_id in sorted(current_ids - requested_ids):
                storage.delete_role_prepost_processing_for_team_role(request.team_role_id, prepost_id)
            for item in normalized_items:
                existing = storage.get_role_prepost_processing_for_team_role(request.team_role_id, item.prepost_id)
                if existing is None:
                    storage.upsert_role_prepost_processing_for_team_role(
                        request.team_role_id,
                        item.prepost_id,
                        enabled=item.enabled,
                        config=item.config,
                    )
                    continue
                storage.set_role_prepost_processing_enabled_for_team_role(
                    request.team_role_id,
                    item.prepost_id,
                    item.enabled,
                )
                if item.config is not None:
                    storage.set_role_prepost_processing_config_for_team_role(
                        request.team_role_id,
                        item.prepost_id,
                        item.config,
                    )
            updated = storage.list_role_prepost_processing_for_team_role(request.team_role_id, enabled_only=False)
            return Result.ok(
                TeamRolePrepostReplaceOutcome(
                    items=tuple(
                        TeamRolePrepostOutcome(
                            team_role_id=request.team_role_id,
                            prepost_id=str(item.prepost_processing_id),
                            enabled=bool(item.enabled),
                            config=_json_or_none(item.config_json),
                        )
                        for item in updated
                    )
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "prepost_binding", "id": f"team_role_id={request.team_role_id}", "cause": "replace"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to replace team-role pre/post processing",
            fallback_details={"entity": "prepost_binding", "id": f"team_role_id={request.team_role_id}", "cause": "replace"},
        )


def put_team_role_working_dir_result(
    runtime: Any,
    storage: Storage,
    *,
    request: TeamRoleWorkingDirPutRequest,
) -> Result[TeamRoleWorkingDirOutcome]:
    try:
        normalized = _normalize_absolute_path(request.working_dir, field_name="working_dir")
        with storage.transaction(immediate=True):
            team_role = storage.get_team_role_by_id(request.team_role_id)
            storage.set_team_role_working_dir(team_role.team_id, team_role.role_id, normalized)
            updated = storage.get_team_role_by_id(request.team_role_id)
            return Result.ok(
                TeamRoleWorkingDirOutcome(
                    team_role_id=request.team_role_id,
                    working_dir=str(updated.working_dir or normalized),
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_message="Invalid team-role working_dir",
            fallback_details={"entity": "team_role", "id": request.team_role_id, "cause": "working_dir_put"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to update team-role working_dir",
            fallback_details={"entity": "team_role", "id": request.team_role_id, "cause": "working_dir_put"},
        )


def put_team_role_root_dir_result(
    runtime: Any,
    storage: Storage,
    *,
    request: TeamRoleRootDirPutRequest,
) -> Result[TeamRoleRootDirOutcome]:
    try:
        normalized = _normalize_absolute_path(request.root_dir, field_name="root_dir")
        with storage.transaction(immediate=True):
            team_role = storage.get_team_role_by_id(request.team_role_id)
            storage.set_team_role_root_dir(team_role.team_id, team_role.role_id, normalized)
            updated = storage.get_team_role_by_id(request.team_role_id)
            return Result.ok(
                TeamRoleRootDirOutcome(
                    team_role_id=request.team_role_id,
                    root_dir=str(updated.root_dir or normalized),
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_message="Invalid team-role root_dir",
            fallback_details={"entity": "team_role", "id": request.team_role_id, "cause": "root_dir_put"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to update team-role root_dir",
            fallback_details={"entity": "team_role", "id": request.team_role_id, "cause": "root_dir_put"},
        )


def patch_master_role_result(
    storage: Storage,
    *,
    role_id: int,
    patch: MasterRolePatchRequest,
    runtime: Any | None = None,
) -> Result[MasterRolePatchOutcome]:
    if all(
        value is None
        for value in (
            patch.role_name,
            patch.llm_model,
            patch.system_prompt,
            patch.extra_instruction,
        )
    ):
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "Patch payload is empty",
            details={"entity": "master_role", "cause": "empty_patch"},
        )
    normalized_role_name = None
    if patch.role_name is not None:
        normalized_role_name = str(patch.role_name).strip()
        if not normalized_role_name:
            return Result.fail(
                ErrorCode.VALIDATION_INVALID_INPUT,
                "role_name must be a non-empty string",
                details={"entity": "master_role", "cause": "invalid_role_name"},
            )
    try:
        with storage.transaction(immediate=True):
            current = storage.get_role_by_id(role_id)
            next_role_name = normalized_role_name if normalized_role_name is not None else str(current.role_name)
            next_system_prompt = patch.system_prompt if patch.system_prompt is not None else current.base_system_prompt
            next_extra_instruction = (
                patch.extra_instruction
                if patch.extra_instruction is not None
                else current.extra_instruction
            )
            next_llm_model = patch.llm_model if patch.llm_model is not None else current.llm_model
            if next_role_name.lower() != str(current.role_name).lower():
                existing = None
                try:
                    existing = storage.get_role_by_name(next_role_name)
                except ValueError:
                    existing = None
                if existing is not None and int(existing.role_id) != int(role_id):
                    return Result.fail(
                        ErrorCode.CONFLICT_ALREADY_EXISTS,
                        f"Role name already exists: {next_role_name}",
                        details={"entity": "master_role", "cause": "name_conflict", "role_name": next_role_name},
                    )
            _sync_master_role_catalog_file(
                runtime=runtime,
                storage=storage,
                current=current,
                next_role_name=next_role_name,
                next_system_prompt=str(next_system_prompt or ""),
                next_extra_instruction=str(next_extra_instruction or ""),
                next_llm_model=next_llm_model,
            )
            storage.update_master_role(
                role_id=role_id,
                role_name=next_role_name,
                llm_model=next_llm_model,
                base_system_prompt=str(next_system_prompt or ""),
                extra_instruction=str(next_extra_instruction or ""),
            )
            updated = storage.get_role_by_id(role_id)
            return Result.ok(
                MasterRolePatchOutcome(
                    role_id=updated.role_id,
                    role_name=updated.role_name,
                    llm_model=updated.llm_model,
                    system_prompt=updated.base_system_prompt,
                    extra_instruction=updated.extra_instruction,
                )
            )
    except sqlite3.IntegrityError:
        return Result.fail(
            ErrorCode.CONFLICT_ALREADY_EXISTS,
            "Role name conflict",
            details={"entity": "master_role", "id": role_id, "cause": "name_conflict"},
        )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "master_role", "id": role_id, "cause": "patch"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to patch master role",
            fallback_details={"entity": "master_role", "id": role_id, "cause": "patch"},
        )


def create_master_role_result(
    storage: Storage,
    *,
    request: MasterRoleCreateRequest,
) -> Result[MasterRoleCreateOutcome]:
    role_name = str(request.role_name or "").strip()
    system_prompt = str(request.system_prompt or "").strip()
    llm_model = str(request.llm_model or "").strip()
    if not role_name:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "role_name must be a non-empty string",
            details={"entity": "master_role", "cause": "invalid_role_name"},
        )
    if not system_prompt:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "system_prompt must be a non-empty string",
            details={"entity": "master_role", "cause": "invalid_system_prompt"},
        )
    if not llm_model:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "llm_model must be a non-empty string",
            details={"entity": "master_role", "cause": "invalid_llm_model"},
        )
    description = str(request.description or "").strip()
    extra_instruction = str(request.extra_instruction or "").strip()
    try:
        with storage.transaction(immediate=True):
            try:
                _ = storage.get_role_by_name(role_name)
                return Result.fail(
                    ErrorCode.CONFLICT_ALREADY_EXISTS,
                    f"Role name already exists: {role_name}",
                    details={"entity": "master_role", "cause": "name_conflict", "role_name": role_name},
                )
            except ValueError:
                pass
            created = storage.upsert_role(
                role_name=role_name,
                description=description,
                base_system_prompt=system_prompt,
                extra_instruction=extra_instruction,
                llm_model=llm_model,
                is_active=True,
            )
            return Result.ok(
                MasterRoleCreateOutcome(
                    role_id=int(created.role_id),
                    role_name=str(created.role_name),
                    llm_model=created.llm_model,
                    system_prompt=str(created.base_system_prompt),
                    extra_instruction=str(created.extra_instruction or ""),
                    description=str(created.description or ""),
                    is_active=bool(created.is_active),
                )
            )
    except sqlite3.IntegrityError:
        return Result.fail(
            ErrorCode.CONFLICT_ALREADY_EXISTS,
            "Role name conflict",
            details={"entity": "master_role", "cause": "name_conflict", "role_name": role_name},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to create master role",
            fallback_details={"entity": "master_role", "cause": "create"},
        )


def create_team_result(
    storage: Storage,
    *,
    request: TeamCreateRequest,
) -> Result[TeamCreateOutcome]:
    name = str(request.name or "").strip()
    if not name:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "name must be a non-empty string",
            details={"entity": "team", "cause": "invalid_name"},
        )
    try:
        with storage.transaction(immediate=True):
            created = storage.upsert_team(name=name, public_id=None, is_active=True, ext_json=None)
            return Result.ok(
                TeamCreateOutcome(
                    team_id=int(created.team_id),
                    public_id=str(created.public_id),
                    name=created.name,
                    is_active=bool(created.is_active),
                    ext_json=created.ext_json,
                    created_at=str(created.created_at),
                    updated_at=str(created.updated_at),
                )
            )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to create team",
            fallback_details={"entity": "team", "cause": "create"},
        )


def rename_team_result(
    storage: Storage,
    *,
    team_id: int,
    request: TeamRenameRequest,
) -> Result[TeamRenameOutcome]:
    name = str(request.name or "").strip()
    if not name:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "name must be a non-empty string",
            details={"entity": "team", "cause": "invalid_name"},
        )
    try:
        with storage.transaction(immediate=True):
            _ = storage.get_team(team_id)
            now = datetime.now(timezone.utc).isoformat()
            storage._conn.execute(
                """
                UPDATE teams
                SET name = ?, updated_at = ?
                WHERE team_id = ?
                """,
                (name, now, team_id),
            )
            updated = storage.get_team(team_id)
            return Result.ok(
                TeamRenameOutcome(
                    team_id=int(updated.team_id),
                    public_id=str(updated.public_id),
                    name=updated.name,
                    is_active=bool(updated.is_active),
                    ext_json=updated.ext_json,
                    created_at=str(updated.created_at),
                    updated_at=str(updated.updated_at),
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "team", "id": team_id, "cause": "rename"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to rename team",
            fallback_details={"entity": "team", "id": team_id, "cause": "rename"},
        )


def delete_team_result(
    storage: Storage,
    *,
    team_id: int,
) -> Result[DeleteTeamOutcome]:
    dependency_tables = (
        "team_bindings",
        "team_roles",
        "questions",
        "answers",
        "orchestrator_feed",
        "thread_events",
    )
    try:
        with storage.transaction(immediate=True):
            _ = storage.get_team(team_id)
            cur = storage._conn.cursor()
            blocking: list[str] = []
            for table in dependency_tables:
                row = cur.execute(f"SELECT 1 FROM {table} WHERE team_id = ? LIMIT 1", (team_id,)).fetchone()
                if row is not None:
                    blocking.append(table)
            if blocking:
                return Result.fail(
                    ErrorCode.CONFLICT_ALREADY_EXISTS,
                    f"Team {team_id} has dependent entities and cannot be deleted",
                    details={
                        "entity": "team",
                        "id": team_id,
                        "cause": "dependency_conflict",
                        "dependencies": blocking,
                    },
                )
            storage._conn.execute("DELETE FROM teams WHERE team_id = ?", (team_id,))
            return Result.ok(DeleteTeamOutcome(team_id=team_id))
    except sqlite3.IntegrityError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.CONFLICT_ALREADY_EXISTS,
            fallback_message=f"Team {team_id} has dependent entities and cannot be deleted",
            fallback_details={"entity": "team", "id": team_id, "cause": "dependency_conflict"},
        )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "team", "id": team_id, "cause": "delete"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to delete team",
            fallback_details={"entity": "team", "id": team_id, "cause": "delete"},
        )


def delete_master_role_result(
    storage: Storage,
    *,
    role_id: int,
) -> Result[DeleteMasterRoleOutcome]:
    dependency_checks: tuple[tuple[str, str], ...] = (
        ("team_roles", "role_id"),
        ("user_role_sessions", "role_id"),
        ("role_prepost_processing", "role_id"),
        ("role_skills_enabled", "role_id"),
        ("provider_user_data", "role_id"),
        ("skill_runs", "role_id"),
    )
    try:
        with storage.transaction(immediate=True):
            _ = storage.get_role_by_id(role_id)
            cur = storage._conn.cursor()
            blocking: list[str] = []
            for table, column in dependency_checks:
                row = cur.execute(
                    f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1",
                    (role_id,),
                ).fetchone()
                if row is not None:
                    blocking.append(table)
            if blocking:
                return Result.fail(
                    ErrorCode.CONFLICT_ALREADY_EXISTS,
                    f"Role {role_id} has bindings/dependencies and cannot be deleted",
                    details={
                        "entity": "master_role",
                        "id": role_id,
                        "cause": "dependency_conflict",
                        "dependencies": blocking,
                    },
                )
            storage._conn.execute("DELETE FROM roles WHERE role_id = ?", (role_id,))
            return Result.ok(DeleteMasterRoleOutcome(role_id=role_id))
    except sqlite3.IntegrityError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.CONFLICT_ALREADY_EXISTS,
            fallback_message=f"Role {role_id} has bindings/dependencies and cannot be deleted",
            fallback_details={"entity": "master_role", "id": role_id, "cause": "dependency_conflict"},
        )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "master_role", "id": role_id, "cause": "delete"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to delete master role",
            fallback_details={"entity": "master_role", "id": role_id, "cause": "delete"},
        )


def _sync_master_role_catalog_file(
    *,
    runtime: Any | None,
    storage: Storage,
    current: Any,
    next_role_name: str,
    next_system_prompt: str,
    next_extra_instruction: str,
    next_llm_model: str | None,
) -> None:
    catalog = getattr(storage, "_role_catalog", None)
    root_dir = getattr(catalog, "root_dir", None)
    if not isinstance(root_dir, Path):
        return

    catalog_role = catalog.get(str(current.role_name)) if callable(getattr(catalog, "get", None)) else None
    payload = {
        "schema_version": 1,
        "role_name": str(next_role_name),
        "description": str((getattr(catalog_role, "description", None) or current.description) or ""),
        "base_system_prompt": str(next_system_prompt or ""),
        "extra_instruction": str(next_extra_instruction or ""),
        "llm_model": next_llm_model,
        "is_active": bool(getattr(catalog_role, "is_active", current.is_active)),
    }

    old_path = root_dir / f"{current.role_name}.json"
    new_path = root_dir / f"{next_role_name}.json"
    target_path = old_path if old_path.exists() and old_path == new_path else new_path
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if old_path != new_path and old_path.exists():
        old_path.unlink()

    try:
        if runtime is None:
            return
        from app.role_catalog_service import refresh_role_catalog
        refresh_role_catalog(runtime=runtime, storage=storage)
    except Exception:
        # Keep PATCH functional even if shared catalog reload fails; DB update remains authoritative fallback.
        return


def bind_master_role_to_team_result(
    storage: Storage,
    *,
    team_id: int,
    role_id: int,
) -> Result[TeamRoleBindOutcome]:
    try:
        with storage.transaction(immediate=True):
            storage.get_team(team_id)
            storage.get_role_by_id(role_id)
            current, created = storage.bind_master_role_to_team(team_id, role_id)
            return Result.ok(
                TeamRoleBindOutcome(
                    team_id=current.team_id,
                    role_id=current.role_id,
                    team_role_id=current.team_role_id,
                    enabled=current.enabled,
                    is_active=current.is_active,
                    mode=current.mode,
                    is_orchestrator=(current.mode == "orchestrator"),
                    model_override=current.model_override,
                    display_name=current.display_name,
                    system_prompt_override=current.system_prompt_override,
                    extra_instruction_override=current.extra_instruction_override,
                    user_prompt_suffix=current.user_prompt_suffix,
                    user_reply_prefix=current.user_reply_prefix,
                    created_or_reactivated=bool(created),
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "team_role_binding", "id": f"team_id={team_id} role_id={role_id}", "cause": "bind"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to bind master role to team",
            fallback_details={"entity": "team_role_binding", "id": f"team_id={team_id} role_id={role_id}", "cause": "bind"},
        )


def _reset_team_role_session_once(
    runtime: Any,
    storage: Storage,
    *,
    team_role_id: int,
    telegram_user_id: int,
) -> Result[MutationAck]:
    try:
        with storage.transaction(immediate=True):
            identity = storage.resolve_team_role_identity(team_role_id)
            if identity is None:
                raise ValueError(f"Team role not found: team_role_id={team_role_id}")
            team_role = storage.get_team_role_by_id(team_role_id)
            team_id = int(identity[0])
            role_id = int(identity[1])
            existing_session = storage.get_user_role_session_by_team_role(telegram_user_id, team_role_id)
            if existing_session is None:
                return Result.fail(
                    ErrorCode.STORAGE_NOT_FOUND,
                    (
                        "Session not found for reset: "
                        f"team_role_id={team_role_id} telegram_user_id={telegram_user_id}"
                    ),
                    details={
                        "entity": "user_role_session",
                        "cause": "not_found",
                        "team_role_id": int(team_role_id),
                        "telegram_user_id": int(telegram_user_id),
                    },
                )
            if storage.has_session_team_role_id():
                storage._conn.execute(
                    """
                    DELETE FROM user_role_sessions
                    WHERE telegram_user_id = ? AND (team_role_id = ? OR (team_id = ? AND role_id = ?))
                    """,
                    (telegram_user_id, team_role_id, team_id, role_id),
                )
            else:
                storage._conn.execute(
                    """
                    DELETE FROM user_role_sessions
                    WHERE telegram_user_id = ? AND team_id = ? AND role_id = ?
                    """,
                    (telegram_user_id, team_id, role_id),
                )
            if storage.has_provider_user_data_team_role_table():
                storage._conn.execute(
                    """
                    DELETE FROM provider_user_data_team_role
                    WHERE team_role_id = ?
                    """,
                    (team_role_id,),
                )
            storage._conn.execute(
                """
                UPDATE team_roles
                SET working_dir = NULL,
                    root_dir = NULL
                WHERE team_role_id = ?
                """,
                (team_role_id,),
            )
            _apply_legacy_blocks(runtime=runtime, storage=storage, role_id=role_id, team_role_id=team_role_id)
            return Result.ok(
                MutationAck(
                    ok=True,
                    team_id=team_id,
                    role_id=role_id,
                    telegram_user_id=telegram_user_id,
                    team_role_id=team_role.team_role_id,
                    operation="reset_session",
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "team_role", "id": f"team_role_id={team_role_id}", "cause": "reset_session"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to reset team role session",
            fallback_details={"entity": "team_role", "id": f"team_role_id={team_role_id}", "cause": "reset_session"},
        )


def _deactivate_team_role_binding_once(
    runtime: Any,
    storage: Storage,
    *,
    team_role_id: int,
    telegram_user_id: int,
) -> Result[MutationAck]:
    try:
        with storage.transaction(immediate=True):
            identity = storage.resolve_team_role_identity(team_role_id)
            if identity is None:
                raise ValueError(f"Team role not found: team_role_id={team_role_id}")
            team_role = storage.get_team_role_by_id(team_role_id)
            team_id = int(identity[0])
            role_id = int(identity[1])
            if storage.has_provider_user_data_team_role_table():
                storage._conn.execute(
                    """
                    DELETE FROM provider_user_data_team_role
                    WHERE team_role_id = ?
                    """,
                    (team_role_id,),
                )
            if storage.has_provider_user_data_team_role_legacy_blocks_table():
                storage._conn.execute(
                    """
                    DELETE FROM provider_user_data_team_role_legacy_blocks
                    WHERE team_role_id = ?
                    """,
                    (team_role_id,),
                )
            if storage.has_prepost_team_role_id():
                storage._conn.execute(
                    """
                    DELETE FROM role_prepost_processing
                    WHERE team_role_id = ? OR (team_id = ? AND role_id = ?)
                    """,
                    (team_role_id, team_id, role_id),
                )
            else:
                storage._conn.execute(
                    """
                    DELETE FROM role_prepost_processing
                    WHERE team_id = ? AND role_id = ?
                    """,
                    (team_id, role_id),
                )
            if storage.has_skill_team_role_id():
                storage._conn.execute(
                    """
                    DELETE FROM role_skills_enabled
                    WHERE team_role_id = ? OR (team_id = ? AND role_id = ?)
                    """,
                    (team_role_id, team_id, role_id),
                )
            else:
                storage._conn.execute(
                    """
                    DELETE FROM role_skills_enabled
                    WHERE team_id = ? AND role_id = ?
                    """,
                    (team_id, role_id),
                )
            if storage.has_session_team_role_id():
                storage._conn.execute(
                    """
                    DELETE FROM user_role_sessions
                    WHERE team_role_id = ? OR (team_id = ? AND role_id = ?)
                    """,
                    (team_role_id, team_id, role_id),
                )
            else:
                storage._conn.execute(
                    """
                    DELETE FROM user_role_sessions
                    WHERE team_id = ? AND role_id = ?
                    """,
                    (team_id, role_id),
                )
            if storage.has_team_role_runtime_status_table():
                storage._conn.execute(
                    """
                    DELETE FROM team_role_runtime_status
                    WHERE team_role_id = ?
                    """,
                    (team_role_id,),
                )
            if storage.has_role_lock_group_members_table():
                storage._conn.execute(
                    """
                    DELETE FROM role_lock_group_members
                    WHERE team_role_id = ?
                    """,
                    (team_role_id,),
                )
            if storage.has_team_role_surrogate_id():
                storage._conn.execute(
                    """
                    DELETE FROM team_roles
                    WHERE team_role_id = ?
                    """,
                    (team_role_id,),
                )
            else:
                storage._conn.execute(
                    """
                    DELETE FROM team_roles
                    WHERE team_id = ? AND role_id = ?
                    """,
                    (team_id, role_id),
                )
            return Result.ok(
                MutationAck(
                    ok=True,
                    team_id=team_id,
                    role_id=role_id,
                    telegram_user_id=telegram_user_id,
                    team_role_id=team_role.team_role_id,
                    operation="deactivate_binding",
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "team_role", "id": f"team_role_id={team_role_id}", "cause": "deactivate_binding"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to delete team role binding",
            fallback_details={"entity": "team_role", "id": f"team_role_id={team_role_id}", "cause": "deactivate_binding"},
        )


def _apply_legacy_blocks(*, runtime: Any, storage: Storage, role_id: int, team_role_id: int) -> None:
    if not storage.has_provider_user_data_team_role_legacy_blocks_table():
        return
    now = datetime.now(timezone.utc).isoformat()
    legacy_keys = set(storage.list_provider_user_legacy_keys_for_role(role_id))
    legacy_keys.update(_iter_role_scoped_provider_fields(runtime))
    for provider_id, key in legacy_keys:
        storage._conn.execute(
            """
            INSERT INTO provider_user_data_team_role_legacy_blocks (provider_id, key, team_role_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(provider_id, key, team_role_id) DO NOTHING
            """,
            (provider_id, key, team_role_id, now),
        )


def _iter_role_scoped_provider_fields(runtime: Any) -> set[tuple[str, str]]:
    items: set[tuple[str, str]] = set()
    provider_registry = getattr(runtime, "provider_registry", {}) or {}
    for provider_id, provider in provider_registry.items():
        user_fields = getattr(provider, "user_fields", {}) or {}
        for key, field in user_fields.items():
            if getattr(field, "scope", None) == "role":
                items.add((str(provider_id), str(key)))
    return items


def _skill_exists(runtime: Any, skill_id: str) -> bool:
    registry = getattr(runtime, "skills_registry", None)
    if registry is None:
        return True
    return registry.get(skill_id) is not None


def _prepost_exists(runtime: Any, prepost_id: str) -> bool:
    registry = getattr(runtime, "prepost_processing_registry", None)
    if registry is None:
        return True
    return registry.get(prepost_id) is not None


def _json_or_none(payload: str | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    try:
        decoded = json.loads(payload)
    except Exception:
        return None
    return decoded if isinstance(decoded, dict) else None


def _execute_with_idempotency(
    *,
    runtime: Any,
    operation: str,
    idempotency_key: str,
    fingerprint_payload: Mapping[str, Any],
    apply_fn: Callable[[], Result[T]],
) -> Result[T]:
    key = str(idempotency_key or "").strip()
    if not key:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "Idempotency-Key is required",
            details={"entity": "idempotency", "cause": "missing_key", "operation": operation},
        )
    fingerprint = json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    store = getattr(runtime, "_write_idempotency_store", None)
    if store is None:
        store = InMemoryIdempotencyStore()
        setattr(runtime, "_write_idempotency_store", store)
    return store.execute(operation=operation, key=key, fingerprint=fingerprint, apply_fn=apply_fn)


def _normalize_absolute_path(raw_value: str, *, field_name: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    if not Path(value).is_absolute():
        raise ValueError(f"{field_name} must be an absolute path")
    return value
