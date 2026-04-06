from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.contracts import ErrorCode, Result
from app.core.use_cases.team_roles import (
    delete_team_role_binding_result,
    reset_team_role_session_result,
    resolve_team_role_id,
)
from app.pending_store import PendingMessageRecord, PendingStore
from app.storage import Storage


@dataclass(frozen=True)
class TransactionBoundary:
    scenario: str
    boundary_kind: str
    begin: str
    end: str
    owner: str


MANDATORY_STAGE2_TRANSACTION_BOUNDARIES: tuple[TransactionBoundary, ...] = (
    TransactionBoundary(
        scenario="reset session",
        boundary_kind="storage.transaction",
        begin="core.use_cases.team_roles.reset_team_role_session_result",
        end="Result[str] finalized",
        owner="core.use_cases.team_roles",
    ),
    TransactionBoundary(
        scenario="delete/deactivate binding",
        boundary_kind="storage.transaction",
        begin="core.use_cases.team_roles.delete_team_role_binding_result",
        end="Result[str] finalized",
        owner="core.use_cases.team_roles",
    ),
    TransactionBoundary(
        scenario="pending replay",
        boundary_kind="runtime op + pending store compare-and-pop",
        begin="application.use_cases.runtime_orchestration.execute_run_chain_operation",
        end="pending store pop only when original payload is unchanged",
        owner="handlers.messages_private + application.use_cases.runtime_orchestration",
    ),
    TransactionBoundary(
        scenario="skill toggle",
        boundary_kind="storage.transaction",
        begin="application.use_cases.transaction_boundaries.toggle_team_role_skill_result",
        end="Result[SkillToggleOutcome] finalized",
        owner="application.use_cases.transaction_boundaries",
    ),
    TransactionBoundary(
        scenario="runtime status transitions",
        boundary_kind="storage.transaction / explicit BEGIN IMMEDIATE",
        begin="services.role_runtime_status + storage.try_acquire_team_role_busy",
        end="status row updated and committed",
        owner="services.role_runtime_status + storage",
    ),
)

MANDATORY_STAGE3_TRANSACTION_BOUNDARIES: tuple[TransactionBoundary, ...] = (
    TransactionBoundary(
        scenario="reset session",
        boundary_kind="storage.transaction",
        begin="application.use_cases.write_api.reset_team_role_session_write_result",
        end="idempotent Result[MutationAck] finalized",
        owner="application.use_cases.write_api",
    ),
    TransactionBoundary(
        scenario="deactivate binding",
        boundary_kind="storage.transaction",
        begin="application.use_cases.write_api.deactivate_team_role_binding_write_result",
        end="idempotent Result[MutationAck] finalized",
        owner="application.use_cases.write_api",
    ),
    TransactionBoundary(
        scenario="skill toggle",
        boundary_kind="storage.transaction",
        begin="application.use_cases.write_api.put_team_role_skill_result",
        end="Result[TeamRoleSkillOutcome] finalized",
        owner="application.use_cases.write_api",
    ),
    TransactionBoundary(
        scenario="prepost toggle/config-lite",
        boundary_kind="storage.transaction",
        begin="application.use_cases.write_api.put_team_role_prepost_result",
        end="Result[TeamRolePrepostOutcome] finalized",
        owner="application.use_cases.write_api",
    ),
    TransactionBoundary(
        scenario="runtime status transitions",
        boundary_kind="storage.transaction / explicit BEGIN IMMEDIATE",
        begin="services.role_runtime_status + storage.try_acquire_team_role_busy",
        end="status row updated and committed",
        owner="services.role_runtime_status + storage",
    ),
)


@dataclass(frozen=True)
class SkillToggleOutcome:
    state_note: str
    skill_enabled: bool
    team_role_id: int


def reset_team_role_session_uow(
    runtime: Any,
    storage: Storage,
    *,
    group_id: int,
    role_id: int,
    user_id: int,
) -> Result[str]:
    return reset_team_role_session_result(
        runtime,
        storage,
        group_id=group_id,
        role_id=role_id,
        user_id=user_id,
    )


def delete_team_role_binding_uow(
    runtime: Any,
    storage: Storage,
    *,
    group_id: int,
    role_id: int,
    user_id: int,
) -> Result[str]:
    return delete_team_role_binding_result(
        runtime,
        storage,
        group_id=group_id,
        role_id=role_id,
        user_id=user_id,
    )


def toggle_team_role_skill_result(
    *,
    storage: Storage,
    skills_registry: Any,
    group_id: int,
    role_id: int,
    skill_id: str,
) -> Result[SkillToggleOutcome]:
    try:
        if skills_registry.get(skill_id) is None:
            return Result.fail(
                ErrorCode.STORAGE_NOT_FOUND,
                f"Skill {skill_id} не найден в реестре.",
                details={"entity": "skill", "id": skill_id, "cause": "not_found"},
            )

        with storage.transaction(immediate=True):
            team_role_id = int(resolve_team_role_id(storage, group_id, role_id, ensure_exists=True))
            current = storage.get_role_skill_for_team_role(team_role_id, skill_id)
            if current is None:
                storage.upsert_role_skill_for_team_role(team_role_id, skill_id, enabled=True, config=None)
                return Result.ok(
                    SkillToggleOutcome(
                        state_note=f"Skill {skill_id} включен.",
                        skill_enabled=True,
                        team_role_id=team_role_id,
                    )
                )
            new_enabled = not current.enabled
            storage.set_role_skill_enabled_for_team_role(team_role_id, skill_id, new_enabled)
            return Result.ok(
                SkillToggleOutcome(
                    state_note=f"Skill {skill_id} {'включен' if new_enabled else 'выключен'}.",
                    skill_enabled=new_enabled,
                    team_role_id=team_role_id,
                )
            )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "skill_binding", "id": f"{group_id}:{role_id}:{skill_id}", "cause": "toggle"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Не удалось переключить skill.",
            fallback_details={"entity": "skill_binding", "id": f"{group_id}:{role_id}:{skill_id}", "cause": "toggle"},
        )


def pop_pending_replay_if_unchanged(
    *,
    pending_store: PendingStore,
    user_id: int,
    original_pending_msg: PendingMessageRecord,
) -> tuple[bool, PendingMessageRecord | None]:
    current_pending_msg = pending_store.peek_record(user_id)
    if current_pending_msg == original_pending_msg:
        pending_store.pop_record(user_id)
        return True, None
    return False, current_pending_msg
