from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from app.application.contracts import ErrorCode, Result
from app.role_catalog_service import ensure_role_identity_by_name
from app.storage import Storage


@dataclass(frozen=True)
class TelegramGroupRef:
    group_id: int
    title: str | None
    team_id: int


@dataclass(frozen=True)
class TeamRoleState:
    group_id: int
    team_id: int
    role_id: int
    public_name: str
    enabled: bool
    is_active: bool
    mode: str


def list_telegram_groups(storage: Storage) -> list[TelegramGroupRef]:
    groups: list[TelegramGroupRef] = []
    for binding in storage.list_team_bindings(interface_type="telegram", active_only=True):
        try:
            group_id = int(binding.external_id)
        except Exception:
            continue
        groups.append(TelegramGroupRef(group_id=group_id, title=binding.external_title, team_id=binding.team_id))
    groups.sort(key=lambda item: item.group_id)
    return groups


def resolve_team_id(storage: Storage, group_id: int) -> int:
    team_id = storage.resolve_team_id_by_telegram_chat(group_id)
    if team_id is None:
        raise ValueError(f"Telegram group binding not found: {group_id}")
    return team_id


def resolve_team_role_id(storage: Storage, group_id: int, role_id: int, *, ensure_exists: bool = False) -> int:
    team_role_id = storage.resolve_team_role_id(resolve_team_id(storage, group_id), role_id, ensure_exists=ensure_exists)
    if team_role_id is None:
        raise ValueError(f"Team role not found for group_id={group_id} role_id={role_id}")
    return team_role_id


def get_team_role_state(storage: Storage, group_id: int, role_id: int) -> TeamRoleState:
    team_id = resolve_team_id(storage, group_id)
    team_role = storage.get_team_role(team_id, role_id)
    return TeamRoleState(
        group_id=group_id,
        team_id=team_id,
        role_id=role_id,
        public_name=storage.get_team_role_name(team_id, role_id),
        enabled=team_role.is_active,
        is_active=team_role.is_active,
        mode=team_role.mode,
    )


def list_team_role_states(storage: Storage, group_id: int, *, include_inactive: bool = False) -> list[TeamRoleState]:
    team_id = resolve_team_id(storage, group_id)
    rows: list[TeamRoleState] = []
    for team_role in storage.list_team_roles(team_id, include_inactive=include_inactive):
        rows.append(
            TeamRoleState(
                group_id=group_id,
                team_id=team_id,
                role_id=team_role.role_id,
                public_name=storage.get_team_role_name(team_id, team_role.role_id),
                enabled=team_role.is_active,
                is_active=team_role.is_active,
                mode=team_role.mode,
            )
        )
    return rows


def bind_master_role_to_group(runtime: Any, storage: Storage, *, group_id: int, role_name: str) -> tuple[str, bool]:
    with storage.transaction(immediate=True):
        role = ensure_role_identity_by_name(runtime=runtime, storage=storage, role_name=role_name)
        team_id = resolve_team_id(storage, group_id)
        _, created = storage.bind_master_role_to_team(team_id, role.role_id)
        return role.role_name, created


def set_team_role_enabled(storage: Storage, *, group_id: int, role_id: int, enabled: bool) -> TeamRoleState:
    with storage.transaction(immediate=True):
        team_id = resolve_team_id(storage, group_id)
        storage.set_team_role_active(team_id, role_id, enabled)
        return get_team_role_state(storage, group_id, role_id)


def set_team_role_mode(
    storage: Storage,
    *,
    group_id: int,
    role_id: int,
    mode: Literal["normal", "orchestrator"],
) -> tuple[TeamRoleState, int | None]:
    with storage.transaction(immediate=True):
        team_id = resolve_team_id(storage, group_id)
        previous_orchestrator = storage.get_enabled_orchestrator_for_team(team_id)
        storage.set_team_role_mode(team_id, role_id, mode)
        return get_team_role_state(storage, group_id, role_id), (
            previous_orchestrator.role_id if previous_orchestrator else None
        )


def set_team_role_model(storage: Storage, *, group_id: int, role_id: int, model_name: str) -> None:
    with storage.transaction(immediate=True):
        storage.set_team_role_model(resolve_team_id(storage, group_id), role_id, model_name)


def clear_team_role_prompt(storage: Storage, *, group_id: int, role_id: int) -> None:
    with storage.transaction(immediate=True):
        storage.set_team_role_prompt(resolve_team_id(storage, group_id), role_id, "")


def clear_team_role_suffix(storage: Storage, *, group_id: int, role_id: int) -> None:
    with storage.transaction(immediate=True):
        storage.set_team_role_user_prompt_suffix(resolve_team_id(storage, group_id), role_id, None)


def clear_team_role_reply_prefix(storage: Storage, *, group_id: int, role_id: int) -> None:
    with storage.transaction(immediate=True):
        storage.set_team_role_user_reply_prefix(resolve_team_id(storage, group_id), role_id, None)


def _iter_role_scoped_provider_fields(runtime: Any) -> set[tuple[str, str]]:
    items: set[tuple[str, str]] = set()
    provider_registry = getattr(runtime, "provider_registry", {}) or {}
    for provider_id, provider in provider_registry.items():
        user_fields = getattr(provider, "user_fields", {}) or {}
        for key, field in user_fields.items():
            if getattr(field, "scope", None) == "role":
                items.add((str(provider_id), str(key)))
    return items


def delete_team_role_binding(runtime: Any, storage: Storage, *, group_id: int, role_id: int, user_id: int) -> str:
    result = delete_team_role_binding_result(runtime, storage, group_id=group_id, role_id=role_id, user_id=user_id)
    if result.is_error or result.value is None:
        raise ValueError(result.error.message if result.error else "Failed to delete team role binding")
    return result.value


def reset_team_role_session(runtime: Any, storage: Storage, *, group_id: int, role_id: int, user_id: int) -> str:
    result = reset_team_role_session_result(runtime, storage, group_id=group_id, role_id=role_id, user_id=user_id)
    if result.is_error or result.value is None:
        raise ValueError(result.error.message if result.error else "Failed to reset team role session")
    return result.value


def delete_team_role_binding_result(
    runtime: Any,
    storage: Storage,
    *,
    group_id: int,
    role_id: int,
    user_id: int,
) -> Result[str]:
    try:
        with storage.transaction(immediate=True):
            state = get_team_role_state(storage, group_id, role_id)
            team_role_id = storage.resolve_team_role_id(state.team_id, role_id)
            cur = storage._conn.cursor()  # noqa: SLF001 - UoW path uses one shared tx cursor/connection.
            if team_role_id is not None:
                team_identity = storage.resolve_team_role_identity(team_role_id)
                if team_identity is None:
                    raise ValueError(f"Team role not found: team_role_id={team_role_id}")
                team_id, resolved_role_id = team_identity

                # Remove team-scoped provider values.
                if storage.has_provider_user_data_team_role_table():
                    cur.execute(
                        """
                        DELETE FROM provider_user_data_team_role
                        WHERE team_role_id = ?
                        """,
                        (team_role_id,),
                    )

                # Block legacy fallback for removed binding.
                legacy_keys = set(storage.list_provider_user_legacy_keys_for_role(role_id))
                legacy_keys.update(_iter_role_scoped_provider_fields(runtime))
                if storage.has_provider_user_data_team_role_legacy_blocks_table():
                    now = datetime.now(timezone.utc).isoformat()
                    for provider_id, key in legacy_keys:
                        cur.execute(
                            """
                            INSERT INTO provider_user_data_team_role_legacy_blocks (provider_id, key, team_role_id, created_at)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(provider_id, key, team_role_id) DO NOTHING
                            """,
                            (provider_id, key, team_role_id, now),
                        )

                # Remove user session for this team-role.
                if storage.has_session_team_role_id():
                    cur.execute(
                        """
                        DELETE FROM user_role_sessions
                        WHERE telegram_user_id = ? AND team_role_id = ?
                        """,
                        (user_id, team_role_id),
                    )
                else:
                    cur.execute(
                        """
                        DELETE FROM user_role_sessions
                        WHERE telegram_user_id = ? AND team_id = ? AND role_id = ?
                        """,
                        (user_id, team_id, resolved_role_id),
                    )

            # Deactivate binding.
            cur.execute(
                """
                UPDATE team_roles
                SET is_active = 0, enabled = 0, mode = 'normal'
                WHERE team_id = ? AND role_id = ?
                """,
                (state.team_id, role_id),
            )
            return Result.ok(state.public_name)
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "team_role", "id": f"group_id={group_id} role_id={role_id}", "cause": "delete"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to delete team role binding",
            fallback_details={"entity": "team_role", "id": f"group_id={group_id} role_id={role_id}", "cause": "delete"},
        )


def reset_team_role_session_result(
    runtime: Any,
    storage: Storage,
    *,
    group_id: int,
    role_id: int,
    user_id: int,
) -> Result[str]:
    try:
        with storage.transaction(immediate=True):
            state = get_team_role_state(storage, group_id, role_id)
            team_role_id = resolve_team_role_id(storage, group_id, role_id, ensure_exists=True)
            team_identity = storage.resolve_team_role_identity(team_role_id)
            if team_identity is None:
                raise ValueError(f"Team role not found: team_role_id={team_role_id}")
            team_id, resolved_role_id = team_identity
            cur = storage._conn.cursor()  # noqa: SLF001 - UoW path uses one shared tx cursor/connection.

            if storage.has_session_team_role_id():
                cur.execute(
                    """
                    DELETE FROM user_role_sessions
                    WHERE telegram_user_id = ? AND (team_role_id = ? OR (team_id = ? AND role_id = ?))
                    """,
                    (user_id, team_role_id, team_id, resolved_role_id),
                )
            else:
                cur.execute(
                    """
                    DELETE FROM user_role_sessions
                    WHERE telegram_user_id = ? AND team_id = ? AND role_id = ?
                    """,
                    (user_id, team_id, resolved_role_id),
                )

            if storage.has_provider_user_data_team_role_table():
                cur.execute(
                    """
                    DELETE FROM provider_user_data_team_role
                    WHERE team_role_id = ?
                    """,
                    (team_role_id,),
                )
            cur.execute(
                """
                UPDATE team_roles
                SET working_dir = NULL,
                    root_dir = NULL
                WHERE team_role_id = ?
                """,
                (team_role_id,),
            )
            legacy_keys = set(storage.list_provider_user_legacy_keys_for_role(role_id))
            legacy_keys.update(_iter_role_scoped_provider_fields(runtime))
            if storage.has_provider_user_data_team_role_legacy_blocks_table():
                now = datetime.now(timezone.utc).isoformat()
                for provider_id, key in legacy_keys:
                    cur.execute(
                        """
                        INSERT INTO provider_user_data_team_role_legacy_blocks (provider_id, key, team_role_id, created_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(provider_id, key, team_role_id) DO NOTHING
                        """,
                        (provider_id, key, team_role_id, now),
                    )
            return Result.ok(state.public_name)
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "team_role", "id": f"group_id={group_id} role_id={role_id}", "cause": "reset_session"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to reset team role session",
            fallback_details={"entity": "team_role", "id": f"group_id={group_id} role_id={role_id}", "cause": "reset_session"},
        )


def upsert_user_role_session_result(
    storage: Storage,
    *,
    user_id: int,
    group_id: int,
    role_id: int,
    session_id: str,
) -> Result[str]:
    try:
        with storage.transaction(immediate=True):
            team_id = resolve_team_id(storage, group_id)
            team_role_id = storage.resolve_team_role_id(team_id, role_id, ensure_exists=True)
            if team_role_id is None:
                raise ValueError(f"Team role not found: group_id={group_id} role_id={role_id}")
            identity = storage.resolve_team_role_identity(team_role_id)
            if identity is None:
                raise ValueError(f"Team role not found: team_role_id={team_role_id}")
            resolved_team_id, resolved_role_id = identity
            now = datetime.now(timezone.utc).isoformat()
            cur = storage._conn.cursor()  # noqa: SLF001 - UoW raw SQL path.
            if storage.has_session_team_role_id():
                cur.execute(
                    """
                    INSERT INTO user_role_sessions (
                        telegram_user_id, team_id, role_id, team_role_id, session_id, created_at, last_used_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(telegram_user_id, team_id, role_id) DO UPDATE SET
                        team_role_id=excluded.team_role_id,
                        session_id=excluded.session_id,
                        last_used_at=excluded.last_used_at
                    """,
                    (user_id, resolved_team_id, resolved_role_id, team_role_id, session_id, now, now),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO user_role_sessions (telegram_user_id, team_id, role_id, session_id, created_at, last_used_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(telegram_user_id, team_id, role_id) DO UPDATE SET
                        session_id=excluded.session_id,
                        last_used_at=excluded.last_used_at
                    """,
                    (user_id, resolved_team_id, resolved_role_id, session_id, now, now),
                )
            return Result.ok(session_id)
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "session_field", "id": f"group_id={group_id} role_id={role_id}", "cause": "upsert"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to upsert user role session",
            fallback_details={"entity": "session_field", "id": f"group_id={group_id} role_id={role_id}", "cause": "upsert"},
        )


def delete_user_role_session_result(
    storage: Storage,
    *,
    user_id: int,
    group_id: int,
    role_id: int,
) -> Result[bool]:
    try:
        with storage.transaction(immediate=True):
            team_id = resolve_team_id(storage, group_id)
            team_role_id = storage.resolve_team_role_id(team_id, role_id, ensure_exists=False)
            if team_role_id is None:
                return Result.ok(False)
            identity = storage.resolve_team_role_identity(team_role_id)
            if identity is None:
                return Result.ok(False)
            resolved_team_id, resolved_role_id = identity
            cur = storage._conn.cursor()  # noqa: SLF001 - UoW raw SQL path.
            if storage.has_session_team_role_id():
                cur.execute(
                    """
                    DELETE FROM user_role_sessions
                    WHERE telegram_user_id = ? AND (team_role_id = ? OR (team_id = ? AND role_id = ?))
                    """,
                    (user_id, team_role_id, resolved_team_id, resolved_role_id),
                )
            else:
                cur.execute(
                    """
                    DELETE FROM user_role_sessions
                    WHERE telegram_user_id = ? AND team_id = ? AND role_id = ?
                    """,
                    (user_id, resolved_team_id, resolved_role_id),
                )
            return Result.ok(bool(cur.rowcount and cur.rowcount > 0))
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "session_field", "id": f"group_id={group_id} role_id={role_id}", "cause": "delete"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to delete user role session",
            fallback_details={"entity": "session_field", "id": f"group_id={group_id} role_id={role_id}", "cause": "delete"},
        )


def upsert_provider_field_by_team_role_result(
    storage: Storage,
    *,
    group_id: int,
    role_id: int,
    provider_id: str,
    key: str,
    value: str,
) -> Result[str]:
    try:
        with storage.transaction(immediate=True):
            team_id = resolve_team_id(storage, group_id)
            team_role_id = storage.resolve_team_role_id(team_id, role_id, ensure_exists=True)
            if team_role_id is None:
                raise ValueError(f"Team role not found: group_id={group_id} role_id={role_id}")
            if not storage.has_provider_user_data_team_role_table():
                raise ValueError("provider_user_data_team_role table is not available")
            now = datetime.now(timezone.utc).isoformat()
            cur = storage._conn.cursor()  # noqa: SLF001 - UoW raw SQL path.
            cur.execute(
                """
                INSERT INTO provider_user_data_team_role (provider_id, key, team_role_id, value, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id, key, team_role_id) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (provider_id, key, int(team_role_id), value, now, now),
            )
            return Result.ok(value)
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "provider_field", "field": key, "id": f"group_id={group_id} role_id={role_id}", "cause": "upsert"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to upsert provider field",
            fallback_details={"entity": "provider_field", "field": key, "id": f"group_id={group_id} role_id={role_id}", "cause": "upsert"},
        )


def delete_provider_field_by_team_role_result(
    storage: Storage,
    *,
    group_id: int,
    role_id: int,
    provider_id: str,
    key: str,
) -> Result[bool]:
    try:
        with storage.transaction(immediate=True):
            team_id = resolve_team_id(storage, group_id)
            team_role_id = storage.resolve_team_role_id(team_id, role_id, ensure_exists=False)
            if team_role_id is None:
                return Result.ok(False)
            if not storage.has_provider_user_data_team_role_table():
                return Result.ok(False)
            cur = storage._conn.cursor()  # noqa: SLF001 - UoW raw SQL path.
            cur.execute(
                """
                DELETE FROM provider_user_data_team_role
                WHERE provider_id = ? AND key = ? AND team_role_id = ?
                """,
                (provider_id, key, int(team_role_id)),
            )
            return Result.ok(bool(cur.rowcount and cur.rowcount > 0))
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "provider_field", "field": key, "id": f"group_id={group_id} role_id={role_id}", "cause": "delete"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to delete provider field",
            fallback_details={"entity": "provider_field", "field": key, "id": f"group_id={group_id} role_id={role_id}", "cause": "delete"},
        )
