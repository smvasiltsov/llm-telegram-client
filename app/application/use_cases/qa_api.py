from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar
from uuid import uuid4

from app.application.contracts import ErrorCode, Result
from app.models import QaAnswer, QaOrchestratorFeedItem, QaQuestion
from app.storage import QA_STATUSES, Storage
from app.utils import extract_role_mentions

T = TypeVar("T")

QA_STATUS_ORDER: tuple[str, ...] = (
    "accepted",
    "queued",
    "in_progress",
    "answered",
    "failed",
    "cancelled",
    "timeout",
)

QA_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "accepted": {"queued", "cancelled"},
    "queued": {"in_progress", "cancelled"},
    "in_progress": {"answered", "failed", "cancelled", "timeout"},
    "answered": set(),
    "failed": set(),
    "cancelled": set(),
    "timeout": set(),
}


@dataclass(frozen=True)
class CursorPage(Generic[T]):
    items: list[T]
    next_cursor: str | None
    limit: int


@dataclass(frozen=True)
class QaCreateQuestionRequest:
    team_id: int
    created_by_user_id: int
    text: str
    team_role_id: int | None = None
    origin_type: Literal["user", "role_dispatch", "orchestrator"] = "user"
    source_question_id: str | None = None
    parent_answer_id: str | None = None
    thread_id: str | None = None
    question_id: str | None = None


@dataclass(frozen=True)
class QaCreateQuestionOutcome:
    question: QaQuestion
    idempotent_replay: bool


@dataclass(frozen=True)
class QaQuestionStatus:
    question_id: str
    status: str
    error_code: str | None
    error_message: str | None
    updated_at: str
    answered_at: str | None
    answer_id: str | None = None


@dataclass(frozen=True)
class QaThreadView:
    questions: CursorPage[QaQuestion]
    answers: CursorPage[QaAnswer]


def map_runtime_pending_to_qa_contract(
    *,
    runtime_status: str | None,
    pending_exists: bool,
    pending_replay_failed: bool,
    timed_out: bool,
) -> tuple[str, str | None]:
    status = (runtime_status or "").strip().lower()
    if timed_out:
        return "timeout", ErrorCode.QA_TIMEOUT.value
    if pending_replay_failed:
        return "failed", ErrorCode.QA_TIMEOUT.value
    if pending_exists:
        return "queued", None
    if status == "busy":
        return "in_progress", None
    if status == "free":
        return "queued", None
    return "accepted", None


def create_question_result(
    storage: Storage,
    *,
    request: QaCreateQuestionRequest,
    idempotency_key: str,
    scope: str = "qa.create_question",
) -> Result[QaCreateQuestionOutcome]:
    key = str(idempotency_key or "").strip()
    if not key:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            "Idempotency-Key is required",
            details={"entity": "qa", "cause": "missing_idempotency_key"},
        )
    payload_hash = _fingerprint_request(request)
    try:
        team_exists = storage.get_team(int(request.team_id))
        if team_exists is None:
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                f"Team not found: {request.team_id}",
                details={"entity": "team", "id": request.team_id, "cause": "not_found"},
            )

        existing = storage.get_qa_idempotency(scope=scope, idempotency_key=key)
        if existing is not None:
            if existing.payload_hash != payload_hash:
                return Result.fail(
                    ErrorCode.QA_IDEMPOTENCY_MISMATCH,
                    "Idempotency key is already used with a different payload",
                    details={"entity": "qa", "cause": "idempotency_payload_mismatch", "scope": scope},
                )
            replay = storage.get_question(existing.question_id)
            if replay is None:
                return Result.fail(
                    ErrorCode.QA_NOT_FOUND,
                    "Question for idempotency key was not found",
                    details={"entity": "question", "id": existing.question_id, "cause": "idempotency_orphan"},
                )
            return Result.ok(QaCreateQuestionOutcome(question=replay, idempotent_replay=True))

        target_team_role_id_result = _resolve_target_team_role_id(storage, request=request)
        if target_team_role_id_result.is_error:
            return Result.fail(
                target_team_role_id_result.error.code,
                target_team_role_id_result.error.message,
                details=target_team_role_id_result.error.details,
                http_status=target_team_role_id_result.error.http_status,
                retryable=target_team_role_id_result.error.retryable,
            )
        target_team_role_id = target_team_role_id_result.value
        if target_team_role_id is None:
            return Result.fail(
                ErrorCode.QA_LINEAGE_INVALID,
                "Unable to resolve target team role",
                details={"entity": "question", "cause": "routing_target_missing"},
            )

        with storage.transaction(immediate=True):
            created = storage.create_question(
                question_id=(request.question_id or _new_id()),
                thread_id=(request.thread_id or _new_id()),
                team_id=int(request.team_id),
                created_by_user_id=int(request.created_by_user_id),
                target_team_role_id=int(target_team_role_id),
                source_question_id=request.source_question_id,
                parent_answer_id=request.parent_answer_id,
                origin_type=request.origin_type,
                text=request.text,
                status="accepted",
            )
            storage.upsert_qa_idempotency(
                scope=scope,
                idempotency_key=key,
                payload_hash=payload_hash,
                question_id=created.question_id,
            )
        return Result.ok(QaCreateQuestionOutcome(question=created, idempotent_replay=False))
    except ValueError as exc:
        message = str(exc)
        if "source_question_id not found" in message or "parent_answer_id not found" in message:
            return Result.fail(
                ErrorCode.QA_LINEAGE_INVALID,
                message,
                details={"entity": "question", "cause": "lineage_invalid"},
            )
        if message.startswith("Team not found:"):
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                message,
                details={"entity": "team", "cause": "not_found"},
            )
        if message.startswith("Team role not found:"):
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                message,
                details={"entity": "team_role", "cause": "not_found"},
            )
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "qa", "cause": "create_question_value_error"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to create question",
            fallback_details={"entity": "qa", "cause": "create_question"},
        )


def transition_question_status_result(
    storage: Storage,
    *,
    question_id: str,
    to_status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> Result[QaQuestionStatus]:
    status_value = str(to_status or "").strip().lower()
    if status_value not in QA_STATUSES:
        return Result.fail(
            ErrorCode.VALIDATION_INVALID_INPUT,
            f"Unsupported question status: {to_status}",
            details={"entity": "question", "cause": "unsupported_status", "status": to_status},
        )
    try:
        question = storage.get_question(question_id)
        if question is None:
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                f"Question not found: {question_id}",
                details={"entity": "question", "id": question_id, "cause": "not_found"},
            )
        if status_value not in QA_STATUS_TRANSITIONS.get(question.status, set()):
            return Result.fail(
                ErrorCode.QA_LINEAGE_INVALID,
                f"Invalid status transition: {question.status} -> {status_value}",
                details={
                    "entity": "question",
                    "id": question_id,
                    "cause": "status_transition_invalid",
                    "from": question.status,
                    "to": status_value,
                },
            )
        with storage.transaction(immediate=True):
            updated = storage.transition_question_status(
                question_id=question_id,
                status=status_value,
                error_code=error_code,
                error_message=error_message,
            )
        if updated is None:
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                f"Question not found: {question_id}",
                details={"entity": "question", "id": question_id, "cause": "not_found"},
            )
        return Result.ok(_to_status(storage, updated))
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to transition question status",
            fallback_details={"entity": "question", "id": question_id, "cause": "status_transition"},
        )


def get_question_status_result(storage: Storage, *, question_id: str) -> Result[QaQuestionStatus]:
    try:
        question = storage.get_question(question_id)
        if question is None:
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                f"Question not found: {question_id}",
                details={"entity": "question", "id": question_id, "cause": "not_found"},
            )
        return Result.ok(_to_status(storage, question))
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to get question status",
            fallback_details={"entity": "question", "id": question_id, "cause": "status_get"},
        )


def get_question_result(storage: Storage, *, question_id: str) -> Result[QaQuestion]:
    try:
        question = storage.get_question(question_id)
        if question is None:
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                f"Question not found: {question_id}",
                details={"entity": "question", "id": question_id, "cause": "not_found"},
            )
        return Result.ok(_with_answer_id(storage, question))
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to get question",
            fallback_details={"entity": "question", "id": question_id, "cause": "get"},
        )


def get_answer_result(storage: Storage, *, answer_id: str) -> Result[QaAnswer]:
    try:
        answer = storage.get_answer(answer_id)
        if answer is None:
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                f"Answer not found: {answer_id}",
                details={"entity": "answer", "id": answer_id, "cause": "not_found"},
            )
        return Result.ok(answer)
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to get answer",
            fallback_details={"entity": "answer", "id": answer_id, "cause": "get"},
        )


def resolve_answer_by_question_result(storage: Storage, *, question_id: str) -> Result[QaAnswer]:
    try:
        question = storage.get_question(question_id)
        if question is None:
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                f"Question not found: {question_id}",
                details={"entity": "question", "id": question_id, "cause": "not_found"},
            )
        answer = storage.get_latest_answer_for_question(question_id)
        if answer is None:
            if question.status == "timeout":
                return Result.fail(
                    ErrorCode.QA_TIMEOUT,
                    f"Question timed out: {question_id}",
                    details={"entity": "question", "id": question_id, "status": question.status},
                )
            return Result.fail(
                ErrorCode.QA_ANSWER_NOT_READY,
                f"Answer is not ready for question: {question_id}",
                details={"entity": "question", "id": question_id, "status": question.status},
            )
        return Result.ok(answer)
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to resolve answer by question",
            fallback_details={"entity": "question", "id": question_id, "cause": "answer_resolve"},
        )


def list_qa_journal_result(
    storage: Storage,
    *,
    team_id: int | None = None,
    team_role_id: int | None = None,
    status: str | None = None,
    thread_id: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> Result[CursorPage[QaQuestion]]:
    try:
        items, next_cursor = storage.list_qa_journal(
            team_id=team_id,
            team_role_id=team_role_id,
            status=status,
            thread_id=thread_id,
            cursor=cursor,
            limit=limit,
        )
        enriched_items: list[QaQuestion] = []
        for item in items:
            answer_id: str | None = None
            if str(item.status) == "answered":
                answer = storage.get_latest_answer_for_question(item.question_id)
                answer_id = answer.answer_id if answer is not None else None
            enriched_items.append(
                QaQuestion(
                    question_id=item.question_id,
                    thread_id=item.thread_id,
                    team_id=item.team_id,
                    created_by_user_id=item.created_by_user_id,
                    target_team_role_id=item.target_team_role_id,
                    source_question_id=item.source_question_id,
                    parent_answer_id=item.parent_answer_id,
                    origin_type=item.origin_type,
                    status=item.status,
                    text=item.text,
                    error_code=item.error_code,
                    error_message=item.error_message,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    answered_at=item.answered_at,
                    answer_id=answer_id,
                )
            )
        safe_limit = max(1, min(int(limit), 200))
        return Result.ok(CursorPage(items=enriched_items, next_cursor=next_cursor, limit=safe_limit))
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "qa_journal", "cause": "invalid_query"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to list qa journal",
            fallback_details={"entity": "qa_journal", "cause": "list"},
        )


def get_thread_result(
    storage: Storage,
    *,
    thread_id: str,
    question_cursor: str | None = None,
    answer_cursor: str | None = None,
    limit: int = 50,
) -> Result[QaThreadView]:
    try:
        q_items, q_cursor = storage.list_thread_questions(thread_id=thread_id, cursor=question_cursor, limit=limit)
        a_items, a_cursor = storage.list_thread_answers(thread_id=thread_id, cursor=answer_cursor, limit=limit)
        safe_limit = max(1, min(int(limit), 200))
        return Result.ok(
            QaThreadView(
                questions=CursorPage(items=q_items, next_cursor=q_cursor, limit=safe_limit),
                answers=CursorPage(items=a_items, next_cursor=a_cursor, limit=safe_limit),
            )
        )
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "qa_thread", "id": thread_id, "cause": "invalid_query"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to get thread",
            fallback_details={"entity": "qa_thread", "id": thread_id, "cause": "get"},
        )


def list_orchestrator_feed_result(
    storage: Storage,
    *,
    team_id: int,
    cursor: str | None = None,
    limit: int = 50,
) -> Result[CursorPage[QaOrchestratorFeedItem]]:
    try:
        items, next_cursor = storage.list_orchestrator_feed(team_id=team_id, cursor=cursor, limit=limit)
        safe_limit = max(1, min(int(limit), 200))
        return Result.ok(CursorPage(items=items, next_cursor=next_cursor, limit=safe_limit))
    except ValueError as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.VALIDATION_INVALID_INPUT,
            fallback_details={"entity": "orchestrator_feed", "id": team_id, "cause": "invalid_query"},
        )
    except Exception as exc:
        return Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to list orchestrator feed",
            fallback_details={"entity": "orchestrator_feed", "id": team_id, "cause": "list"},
        )


def _to_status(storage: Storage, question: QaQuestion) -> QaQuestionStatus:
    return QaQuestionStatus(
        question_id=question.question_id,
        status=question.status,
        error_code=question.error_code,
        error_message=question.error_message,
        updated_at=question.updated_at,
        answered_at=question.answered_at,
        answer_id=_resolve_answer_id_if_answered(storage, question),
    )


def _with_answer_id(storage: Storage, question: QaQuestion) -> QaQuestion:
    return QaQuestion(
        question_id=question.question_id,
        thread_id=question.thread_id,
        team_id=question.team_id,
        created_by_user_id=question.created_by_user_id,
        target_team_role_id=question.target_team_role_id,
        source_question_id=question.source_question_id,
        parent_answer_id=question.parent_answer_id,
        origin_type=question.origin_type,
        status=question.status,
        text=question.text,
        error_code=question.error_code,
        error_message=question.error_message,
        created_at=question.created_at,
        updated_at=question.updated_at,
        answered_at=question.answered_at,
        answer_id=_resolve_answer_id_if_answered(storage, question),
    )


def _resolve_answer_id_if_answered(storage: Storage, question: QaQuestion) -> str | None:
    if str(question.status) != "answered":
        return None
    answer = storage.get_latest_answer_for_question(question.question_id)
    return answer.answer_id if answer is not None else None


def _new_id() -> str:
    return str(uuid4())


def _fingerprint_request(request: QaCreateQuestionRequest) -> str:
    payload: dict[str, Any] = {
        "team_id": int(request.team_id),
        "created_by_user_id": int(request.created_by_user_id),
        "text": request.text,
        "team_role_id": request.team_role_id,
        "origin_type": request.origin_type,
        "source_question_id": request.source_question_id,
        "parent_answer_id": request.parent_answer_id,
        "thread_id": request.thread_id,
        "question_id": request.question_id,
    }
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _resolve_target_team_role_id(
    storage: Storage,
    *,
    request: QaCreateQuestionRequest,
) -> Result[int]:
    team_id = int(request.team_id)
    explicit_team_role_id = request.team_role_id
    if explicit_team_role_id is not None:
        identity = storage.resolve_team_role_identity(int(explicit_team_role_id))
        if identity is None:
            return Result.fail(
                ErrorCode.QA_NOT_FOUND,
                f"Team role not found: team_role_id={explicit_team_role_id}",
                details={"entity": "team_role", "id": explicit_team_role_id, "cause": "not_found"},
            )
        role_team_id, _ = identity
        if int(role_team_id) != team_id:
            return Result.fail(
                ErrorCode.QA_LINEAGE_INVALID,
                "team_role_id does not belong to team_id",
                details={
                    "entity": "question",
                    "cause": "team_role_team_mismatch",
                    "team_id": team_id,
                    "team_role_id": int(explicit_team_role_id),
                    "resolved_team_id": int(role_team_id),
                },
            )
        return Result.ok(int(explicit_team_role_id))

    roles = storage.list_roles_for_team(team_id)
    mention_map = {role.public_name().strip().lower(): role for role in roles if role.public_name().strip()}
    mentions = extract_role_mentions(str(request.text or ""), set(mention_map.keys()))
    if not mentions:
        try:
            orchestrator = storage.get_enabled_orchestrator_for_team(team_id)
        except ValueError:
            return Result.fail(
                ErrorCode.QA_ORCHESTRATOR_AMBIGUOUS,
                "Multiple active orchestrator roles found for team",
                details={"entity": "question", "cause": "orchestrator_ambiguous", "team_id": team_id},
            )
        if orchestrator is None:
            return Result.fail(
                ErrorCode.QA_ORCHESTRATOR_NOT_CONFIGURED,
                "No active orchestrator role configured for team",
                details={"entity": "question", "cause": "orchestrator_not_configured", "team_id": team_id},
            )
        return Result.ok(int(orchestrator.team_role_id))
    if len(mentions) > 1:
        return Result.fail(
            ErrorCode.QA_LINEAGE_INVALID,
            "Multiple role tags are not supported in v1",
            details={"entity": "question", "cause": "multiple_role_tags", "tags": list(mentions)},
        )
    selected = mention_map.get(str(mentions[0]).lower())
    if selected is None:
        return Result.fail(
            ErrorCode.QA_NOT_FOUND,
            f"Team role not found for tag: {mentions[0]}",
            details={"entity": "team_role", "cause": "not_found_by_tag", "tag": mentions[0]},
        )
    team_role_id = storage.resolve_team_role_id(team_id, int(selected.role_id))
    if team_role_id is None:
        return Result.fail(
            ErrorCode.QA_NOT_FOUND,
            f"Team role not found for tag: {mentions[0]}",
            details={"entity": "team_role", "cause": "not_found_by_tag", "tag": mentions[0]},
        )
    return Result.ok(int(team_role_id))


__all__ = [
    "CursorPage",
    "QaCreateQuestionOutcome",
    "QaCreateQuestionRequest",
    "QaQuestionStatus",
    "QaThreadView",
    "QA_STATUS_ORDER",
    "QA_STATUS_TRANSITIONS",
    "create_question_result",
    "get_answer_result",
    "get_question_result",
    "get_question_status_result",
    "get_thread_result",
    "list_orchestrator_feed_result",
    "list_qa_journal_result",
    "map_runtime_pending_to_qa_contract",
    "resolve_answer_by_question_result",
    "transition_question_status_result",
]
