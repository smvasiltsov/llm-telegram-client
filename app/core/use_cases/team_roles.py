from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

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
        enabled=team_role.enabled,
        mode=team_role.mode,
    )


def list_team_role_states(storage: Storage, group_id: int) -> list[TeamRoleState]:
    team_id = resolve_team_id(storage, group_id)
    rows: list[TeamRoleState] = []
    for team_role in storage.list_team_roles(team_id):
        rows.append(
            TeamRoleState(
                group_id=group_id,
                team_id=team_id,
                role_id=team_role.role_id,
                public_name=storage.get_team_role_name(team_id, team_role.role_id),
                enabled=team_role.enabled,
                mode=team_role.mode,
            )
        )
    return rows


def bind_master_role_to_group(runtime: Any, storage: Storage, *, group_id: int, role_name: str) -> tuple[str, bool]:
    role = ensure_role_identity_by_name(runtime=runtime, storage=storage, role_name=role_name)
    team_id = resolve_team_id(storage, group_id)
    _, created = storage.bind_master_role_to_team(team_id, role.role_id)
    return role.role_name, created


def set_team_role_enabled(storage: Storage, *, group_id: int, role_id: int, enabled: bool) -> TeamRoleState:
    team_id = resolve_team_id(storage, group_id)
    storage.set_team_role_enabled(team_id, role_id, enabled)
    return get_team_role_state(storage, group_id, role_id)


def set_team_role_mode(
    storage: Storage,
    *,
    group_id: int,
    role_id: int,
    mode: Literal["normal", "orchestrator"],
) -> tuple[TeamRoleState, int | None]:
    team_id = resolve_team_id(storage, group_id)
    previous_orchestrator = storage.get_enabled_orchestrator_for_team(team_id)
    storage.set_team_role_mode(team_id, role_id, mode)
    return get_team_role_state(storage, group_id, role_id), (
        previous_orchestrator.role_id if previous_orchestrator else None
    )


def set_team_role_model(storage: Storage, *, group_id: int, role_id: int, model_name: str) -> None:
    storage.set_team_role_model(resolve_team_id(storage, group_id), role_id, model_name)


def clear_team_role_prompt(storage: Storage, *, group_id: int, role_id: int) -> None:
    storage.set_team_role_prompt(resolve_team_id(storage, group_id), role_id, "")


def clear_team_role_suffix(storage: Storage, *, group_id: int, role_id: int) -> None:
    storage.set_team_role_user_prompt_suffix(resolve_team_id(storage, group_id), role_id, None)


def clear_team_role_reply_prefix(storage: Storage, *, group_id: int, role_id: int) -> None:
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
    state = get_team_role_state(storage, group_id, role_id)
    team_role_id = storage.resolve_team_role_id(state.team_id, role_id)
    if team_role_id is not None:
        # Remove team-scoped values for removed binding and prevent legacy fallback for this binding.
        storage.delete_all_provider_user_values_by_team_role(team_role_id)
        legacy_keys = set(storage.list_provider_user_legacy_keys_for_role(role_id))
        legacy_keys.update(_iter_role_scoped_provider_fields(runtime))
        for provider_id, key in legacy_keys:
            storage.block_provider_user_legacy_fallback(provider_id, key, team_role_id)
        storage.delete_user_role_session_by_team_role(user_id, team_role_id)
    storage.deactivate_team_role(state.team_id, role_id)
    return state.public_name


def reset_team_role_session(runtime: Any, storage: Storage, *, group_id: int, role_id: int, user_id: int) -> str:
    state = get_team_role_state(storage, group_id, role_id)
    team_role_id = resolve_team_role_id(storage, group_id, role_id, ensure_exists=True)
    storage.delete_user_role_session_by_team_role(user_id, team_role_id)
    storage.delete_all_provider_user_values_by_team_role(team_role_id)
    legacy_keys = set(storage.list_provider_user_legacy_keys_for_role(role_id))
    legacy_keys.update(_iter_role_scoped_provider_fields(runtime))
    for provider_id, key in legacy_keys:
        storage.block_provider_user_legacy_fallback(provider_id, key, team_role_id)
    return state.public_name
