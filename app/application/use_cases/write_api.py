from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, TypeVar

from app.application.contracts import ErrorCode, Result
from app.storage import Storage

T = TypeVar("T")


@dataclass(frozen=True)
class TeamRolePatchRequest:
    enabled: bool | None = None
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
class TeamRolePrepostPutRequest:
    team_role_id: int
    prepost_id: str
    enabled: bool
    config: dict[str, Any] | None = None


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
    team_id: int,
    role_id: int,
    patch: TeamRolePatchRequest,
) -> Result[TeamRolePatchOutcome]:
    if all(
        value is None
        for value in (
            patch.enabled,
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
    if patch.is_orchestrator is True and patch.enabled is False:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "Orchestrator role cannot be disabled in the same patch request",
            details={"entity": "team_role", "cause": "orchestrator_enabled_invariant"},
        )
    try:
        with storage.transaction(immediate=True):
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
            if patch.enabled is not None:
                storage.set_team_role_enabled(team_id, role_id, patch.enabled)
            current = storage.get_team_role(team_id, role_id)
            return Result.ok(
                TeamRolePatchOutcome(
                    team_id=team_id,
                    role_id=role_id,
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
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.STORAGE_NOT_FOUND,
            fallback_details={"entity": "team_role", "id": f"team_id={team_id} role_id={role_id}", "cause": "patch"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to patch team role",
            fallback_details={"entity": "team_role", "id": f"team_id={team_id} role_id={role_id}", "cause": "patch"},
        )


def reset_team_role_session_write_result(
    runtime: Any,
    storage: Storage,
    *,
    team_id: int,
    role_id: int,
    telegram_user_id: int,
    idempotency_key: str,
) -> Result[MutationAck]:
    return _execute_with_idempotency(
        runtime=runtime,
        operation="reset_session",
        idempotency_key=idempotency_key,
        fingerprint_payload={"team_id": team_id, "role_id": role_id, "telegram_user_id": telegram_user_id},
        apply_fn=lambda: _reset_team_role_session_once(
            runtime=runtime,
            storage=storage,
            team_id=team_id,
            role_id=role_id,
            telegram_user_id=telegram_user_id,
        ),
    )


def deactivate_team_role_binding_write_result(
    runtime: Any,
    storage: Storage,
    *,
    team_id: int,
    role_id: int,
    telegram_user_id: int,
    idempotency_key: str,
) -> Result[MutationAck]:
    return _execute_with_idempotency(
        runtime=runtime,
        operation="deactivate_binding",
        idempotency_key=idempotency_key,
        fingerprint_payload={"team_id": team_id, "role_id": role_id, "telegram_user_id": telegram_user_id},
        apply_fn=lambda: _deactivate_team_role_binding_once(
            runtime=runtime,
            storage=storage,
            team_id=team_id,
            role_id=role_id,
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


def _reset_team_role_session_once(
    runtime: Any,
    storage: Storage,
    *,
    team_id: int,
    role_id: int,
    telegram_user_id: int,
) -> Result[MutationAck]:
    try:
        with storage.transaction(immediate=True):
            storage.get_team(team_id)
            team_role = storage.get_team_role(team_id, role_id)
            team_role_id = storage.resolve_team_role_id(team_id, role_id, ensure_exists=True)
            if team_role_id is None:
                raise ValueError(f"Team role not found: team_id={team_id} role_id={role_id}")
            if storage.has_session_team_role_id():
                storage._conn.execute(
                    """
                    DELETE FROM user_role_sessions
                    WHERE telegram_user_id = ? AND team_role_id = ?
                    """,
                    (telegram_user_id, team_role_id),
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
            fallback_details={"entity": "team_role", "id": f"team_id={team_id} role_id={role_id}", "cause": "reset_session"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to reset team role session",
            fallback_details={"entity": "team_role", "id": f"team_id={team_id} role_id={role_id}", "cause": "reset_session"},
        )


def _deactivate_team_role_binding_once(
    runtime: Any,
    storage: Storage,
    *,
    team_id: int,
    role_id: int,
    telegram_user_id: int,
) -> Result[MutationAck]:
    try:
        with storage.transaction(immediate=True):
            storage.get_team(team_id)
            team_role = storage.get_team_role(team_id, role_id)
            team_role_id = storage.resolve_team_role_id(team_id, role_id, ensure_exists=True)
            if team_role_id is None:
                raise ValueError(f"Team role not found: team_id={team_id} role_id={role_id}")
            if storage.has_provider_user_data_team_role_table():
                storage._conn.execute(
                    """
                    DELETE FROM provider_user_data_team_role
                    WHERE team_role_id = ?
                    """,
                    (team_role_id,),
                )
            _apply_legacy_blocks(runtime=runtime, storage=storage, role_id=role_id, team_role_id=team_role_id)
            if storage.has_session_team_role_id():
                storage._conn.execute(
                    """
                    DELETE FROM user_role_sessions
                    WHERE telegram_user_id = ? AND team_role_id = ?
                    """,
                    (telegram_user_id, team_role_id),
                )
            else:
                storage._conn.execute(
                    """
                    DELETE FROM user_role_sessions
                    WHERE telegram_user_id = ? AND team_id = ? AND role_id = ?
                    """,
                    (telegram_user_id, team_id, role_id),
                )
            storage.deactivate_team_role(team_id, role_id)
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
            fallback_details={"entity": "team_role", "id": f"team_id={team_id} role_id={role_id}", "cause": "deactivate_binding"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to deactivate team role binding",
            fallback_details={"entity": "team_role", "id": f"team_id={team_id} role_id={role_id}", "cause": "deactivate_binding"},
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
