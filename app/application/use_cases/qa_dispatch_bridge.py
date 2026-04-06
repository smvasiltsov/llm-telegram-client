from __future__ import annotations

from dataclasses import dataclass

from app.application.contracts import ErrorCode, Result
from app.models import QaAnswer, QaOrchestratorFeedItem, QaQuestion
from app.storage import Storage


@dataclass(frozen=True)
class QaBridgeTerminalOutcome:
    question: QaQuestion
    answer: QaAnswer | None
    orchestrator_feed_item: QaOrchestratorFeedItem | None


@dataclass(frozen=True)
class QaBridgeLeaseSweepOutcome:
    requeued: list[QaQuestion]
    timed_out: list[QaQuestion]


def claim_questions_for_dispatch_result(
    storage: Storage,
    *,
    limit: int = 20,
    max_attempts: int = 3,
) -> Result[list[QaQuestion]]:
    try:
        with storage.transaction(immediate=True):
            claimed = storage.claim_questions_for_dispatch(limit=limit, max_attempts=max_attempts)
        return Result.ok(claimed)
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "qa_dispatch_bridge", "cause": "claim_invalid_input"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to claim questions for dispatch",
            fallback_details={"entity": "qa_dispatch_bridge", "cause": "claim_failed"},
        )


def start_question_dispatch_attempt_result(
    storage: Storage,
    *,
    question_id: str,
    lease_ttl_sec: int = 120,
    max_attempts: int = 3,
) -> Result[QaQuestion]:
    try:
        with storage.transaction(immediate=True):
            started = storage.start_question_dispatch_attempt(
                question_id=question_id,
                lease_ttl_sec=lease_ttl_sec,
                max_attempts=max_attempts,
            )
        if started is None:
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                f"Question is not dispatch-ready: {question_id}",
                details={"entity": "question", "id": question_id, "cause": "not_dispatch_ready"},
            )
        return Result.ok(started)
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "qa_dispatch_bridge", "id": question_id, "cause": "start_invalid_input"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to start question dispatch attempt",
            fallback_details={"entity": "qa_dispatch_bridge", "id": question_id, "cause": "start_failed"},
        )


def persist_question_terminal_outcome_result(
    storage: Storage,
    *,
    question_id: str,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    answer_id: str | None = None,
    answer_text: str | None = None,
    answer_team_role_id: int | None = None,
    answer_role_name: str | None = None,
    append_orchestrator_feed: bool = False,
) -> Result[QaBridgeTerminalOutcome]:
    try:
        with storage.transaction(immediate=True):
            question, answer, feed_item = storage.persist_question_terminal_outcome(
                question_id=question_id,
                status=status,
                error_code=error_code,
                error_message=error_message,
                answer_id=answer_id,
                answer_text=answer_text,
                answer_team_role_id=answer_team_role_id,
                answer_role_name=answer_role_name,
                append_orchestrator_feed=append_orchestrator_feed,
            )
        if question is None:
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                f"Question not found: {question_id}",
                details={"entity": "question", "id": question_id, "cause": "not_found"},
            )
        return Result.ok(
            QaBridgeTerminalOutcome(
                question=question,
                answer=answer,
                orchestrator_feed_item=feed_item,
            )
        )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "qa_dispatch_bridge", "id": question_id, "cause": "terminal_invalid_input"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to persist question terminal outcome",
            fallback_details={"entity": "qa_dispatch_bridge", "id": question_id, "cause": "terminal_failed"},
        )


def sweep_expired_question_dispatch_leases_result(
    storage: Storage,
    *,
    max_attempts: int = 3,
    attempt_ttl_sec: int = 120,
    now: str | None = None,
) -> Result[QaBridgeLeaseSweepOutcome]:
    try:
        with storage.transaction(immediate=True):
            requeued, timed_out = storage.sweep_expired_question_dispatch_leases(
                max_attempts=max_attempts,
                attempt_ttl_sec=attempt_ttl_sec,
                now=now,
            )
        return Result.ok(QaBridgeLeaseSweepOutcome(requeued=requeued, timed_out=timed_out))
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "qa_dispatch_bridge", "cause": "sweep_invalid_input"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to sweep expired question dispatch leases",
            fallback_details={"entity": "qa_dispatch_bridge", "cause": "sweep_failed"},
        )


def finalize_question_dispatch_attempt_failure_result(
    storage: Storage,
    *,
    question_id: str,
    error_code: str,
    error_message: str,
    max_attempts: int = 3,
    retry_delay_sec: int = 0,
) -> Result[QaQuestion]:
    try:
        with storage.transaction(immediate=True):
            item = storage.finalize_question_dispatch_attempt_failure(
                question_id=question_id,
                error_code=error_code,
                error_message=error_message,
                max_attempts=max_attempts,
                retry_delay_sec=retry_delay_sec,
            )
        if item is None:
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                f"Question not found: {question_id}",
                details={"entity": "question", "id": question_id, "cause": "not_found"},
            )
        return Result.ok(item)
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "qa_dispatch_bridge", "id": question_id, "cause": "finalize_failed_invalid"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to finalize question dispatch attempt failure",
            fallback_details={"entity": "qa_dispatch_bridge", "id": question_id, "cause": "finalize_failed"},
        )


__all__ = [
    "QaBridgeLeaseSweepOutcome",
    "QaBridgeTerminalOutcome",
    "claim_questions_for_dispatch_result",
    "persist_question_terminal_outcome_result",
    "finalize_question_dispatch_attempt_failure_result",
    "start_question_dispatch_attempt_result",
    "sweep_expired_question_dispatch_leases_result",
]
