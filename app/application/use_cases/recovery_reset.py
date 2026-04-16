from __future__ import annotations

from dataclasses import dataclass

from app.application.contracts import ErrorCode, Result
from app.storage import Storage


@dataclass(frozen=True)
class RecoveryQueuesSnapshot:
    questions_accepted: int = 0
    questions_queued: int = 0
    questions_in_progress: int = 0
    qa_dispatch_bridge_rows: int = 0
    event_deliveries_pending: int = 0
    event_deliveries_retry_scheduled: int = 0
    event_deliveries_in_progress: int = 0
    runtime_status_busy: int = 0
    runtime_status_free: int = 0
    runtime_status_pending: int = 0

    @classmethod
    def from_mapping(cls, data: dict[str, int]) -> "RecoveryQueuesSnapshot":
        return cls(
            questions_accepted=int(data.get("questions_accepted", 0)),
            questions_queued=int(data.get("questions_queued", 0)),
            questions_in_progress=int(data.get("questions_in_progress", 0)),
            qa_dispatch_bridge_rows=int(data.get("qa_dispatch_bridge_rows", 0)),
            event_deliveries_pending=int(data.get("event_deliveries_pending", 0)),
            event_deliveries_retry_scheduled=int(data.get("event_deliveries_retry_scheduled", 0)),
            event_deliveries_in_progress=int(data.get("event_deliveries_in_progress", 0)),
            runtime_status_busy=int(data.get("runtime_status_busy", 0)),
            runtime_status_free=int(data.get("runtime_status_free", 0)),
            runtime_status_pending=int(data.get("runtime_status_pending", 0)),
        )


@dataclass(frozen=True)
class RecoveryQueuesResetOutcome:
    dry_run: bool
    applied: bool
    before: RecoveryQueuesSnapshot
    after: RecoveryQueuesSnapshot
    delta: RecoveryQueuesSnapshot
    summary: str


def _diff(before: RecoveryQueuesSnapshot, after: RecoveryQueuesSnapshot) -> RecoveryQueuesSnapshot:
    return RecoveryQueuesSnapshot(
        questions_accepted=before.questions_accepted - after.questions_accepted,
        questions_queued=before.questions_queued - after.questions_queued,
        questions_in_progress=before.questions_in_progress - after.questions_in_progress,
        qa_dispatch_bridge_rows=before.qa_dispatch_bridge_rows - after.qa_dispatch_bridge_rows,
        event_deliveries_pending=before.event_deliveries_pending - after.event_deliveries_pending,
        event_deliveries_retry_scheduled=before.event_deliveries_retry_scheduled - after.event_deliveries_retry_scheduled,
        event_deliveries_in_progress=before.event_deliveries_in_progress - after.event_deliveries_in_progress,
        runtime_status_busy=before.runtime_status_busy - after.runtime_status_busy,
        runtime_status_free=before.runtime_status_free - after.runtime_status_free,
        runtime_status_pending=before.runtime_status_pending - after.runtime_status_pending,
    )


def reset_recovery_queues_result(
    storage: Storage,
    *,
    scope_mode: str,
    team_id: int | None,
    dry_run: bool,
) -> Result[RecoveryQueuesResetOutcome]:
    mode = str(scope_mode or "").strip().lower()
    if mode not in {"global", "team"}:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "Unsupported recovery scope mode",
            details={"entity": "recovery_reset", "cause": "scope_mode_invalid", "scope_mode": scope_mode},
        )
    if mode == "team":
        if team_id is None:
            return Result.fail(
                ErrorCode.VALIDATION_INVALID_INPUT,
                "scope.team_id is required when scope.mode=team",
                details={"entity": "recovery_reset", "cause": "team_scope_missing_team_id"},
            )
        try:
            storage.get_team(int(team_id))
        except ValueError as exc:
            return Result.fail_from_exception(
                exc,
                fallback_code=ErrorCode.STORAGE_NOT_FOUND,
                fallback_details={"entity": "team", "id": int(team_id), "cause": "not_found"},
            )
    else:
        team_id = None

    try:
        before = RecoveryQueuesSnapshot.from_mapping(
            storage.snapshot_recovery_queues(scope_mode=mode, team_id=team_id)
        )
        if dry_run:
            after = before
            return Result.ok(
                RecoveryQueuesResetOutcome(
                    dry_run=True,
                    applied=False,
                    before=before,
                    after=after,
                    delta=_diff(before, after),
                    summary="Dry-run completed. No changes were applied.",
                )
            )
        with storage.transaction(immediate=True):
            storage.reset_recovery_queues(scope_mode=mode, team_id=team_id)
        after = RecoveryQueuesSnapshot.from_mapping(
            storage.snapshot_recovery_queues(scope_mode=mode, team_id=team_id)
        )
        return Result.ok(
            RecoveryQueuesResetOutcome(
                dry_run=False,
                applied=True,
                before=before,
                after=after,
                delta=_diff(before, after),
                summary="Recovery reset applied.",
            )
        )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "recovery_reset", "cause": "value_error"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to reset recovery queues",
            fallback_details={"entity": "recovery_reset", "cause": "unexpected"},
        )

