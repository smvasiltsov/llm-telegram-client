from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.application.authz import AuthzActor
from app.application.contracts import ErrorCode
from app.application.observability import ensure_correlation_id, get_correlation_id
from app.application.use_cases.read_api import (
    list_roles_catalog_errors_result,
    list_roles_catalog_result,
    list_team_roles_result,
    list_team_runtime_status_result,
    list_team_sessions_result,
    list_teams_result,
)
from app.application.use_cases.qa_api import (
    QaCreateQuestionRequest,
    create_question_result,
    get_answer_result,
    get_question_result,
    get_question_status_result,
    get_thread_result,
    list_orchestrator_feed_result,
    list_qa_journal_result,
    resolve_answer_by_question_result,
)
from app.application.use_cases.write_api import (
    TeamRolePatchRequest,
    TeamRolePrepostPutRequest,
    TeamRoleSkillPutRequest,
    deactivate_team_role_binding_write_result,
    patch_team_role_result,
    put_team_role_prepost_result,
    put_team_role_skill_result,
    reset_team_role_session_write_result,
)
from app.interfaces.api.dependencies import (
    provide_authz_dependencies,
    provide_runtime_dispatch_health,
    provide_queue_status_dependencies,
    provide_storage_uow_dependencies,
)
from app.interfaces.api.error_mapping import map_result_error_to_api
from app.interfaces.api.schemas import (
    ApiCursorMeta,
    ApiCursorResponse,
    ApiErrorBody,
    ApiErrorResponse,
    ApiPageMeta,
    ApiPagedResponse,
    MutationAckDTO,
    QaAnswerDTO,
    QaCreateQuestionRequestDTO,
    QaCreateQuestionResponseDTO,
    QaOrchestratorFeedItemDTO,
    QaQuestionDTO,
    QaQuestionStatusDTO,
    QaThreadResponseDTO,
    RoleDTO,
    RoleCatalogErrorDTO,
    TeamDTO,
    TeamRolePatchOutcomeDTO,
    TeamRolePatchRequestDTO,
    TeamRolePrepostOutcomeDTO,
    TeamRolePrepostPutRequestDTO,
    TeamRoleRuntimeStatusDTO,
    TeamRoleSkillOutcomeDTO,
    TeamRoleSkillPutRequestDTO,
    TeamRoleUserMutationRequestDTO,
    mutation_ack_to_dto,
    qa_answer_to_dto,
    qa_create_question_outcome_to_dto,
    qa_orchestrator_feed_item_to_dto,
    qa_question_status_to_dto,
    qa_question_to_dto,
    role_catalog_error_to_dto,
    role_catalog_item_to_dto,
    role_to_dto,
    team_role_patch_outcome_to_dto,
    team_role_prepost_outcome_to_dto,
    team_role_skill_outcome_to_dto,
    team_session_to_dto,
    team_role_runtime_status_to_dto,
    team_to_dto,
)


def build_read_only_v1_router(*, app_state: Any):
    from fastapi import APIRouter, Body, Header, Query, Response
    from fastapi.responses import JSONResponse

    router = APIRouter(prefix="/api/v1", tags=["read-only"])

    def _ok_list(items: Sequence[object], dto_builder):
        return [dto_builder(item).model_dump(mode="json") for item in items]

    def _ok_paged(items: Sequence[object], dto_builder, *, total: int, limit: int, offset: int):
        payload_items = _ok_list(items, dto_builder)
        return ApiPagedResponse(
            items=payload_items,
            meta=ApiPageMeta(
                total=int(total),
                limit=int(limit),
                offset=int(offset),
                returned=len(payload_items),
            ),
        ).model_dump(mode="json")

    def _error_json(*, status_code: int, payload: dict[str, object]) -> JSONResponse:
        details = dict(payload.get("details") or {})
        details["correlation_id"] = ensure_correlation_id(get_correlation_id())
        body = ApiErrorResponse(
            error=ApiErrorBody(
                code=str(payload.get("code", "internal.unexpected")),
                message=str(payload.get("message", "Unexpected error")),
                details=details,
                retryable=bool(payload.get("retryable", False)),
            )
        )
        return JSONResponse(status_code=int(status_code), content=body.model_dump(mode="json"))

    def _ok_cursor(items: Sequence[object], dto_builder, *, limit: int, next_cursor: str | None):
        payload_items = _ok_list(items, dto_builder)
        return ApiCursorResponse(
            items=payload_items,
            meta=ApiCursorMeta(
                limit=int(limit),
                returned=len(payload_items),
                next_cursor=next_cursor,
            ),
        ).model_dump(mode="json")

    def _owner_guard(user_id: int | None) -> JSONResponse | None:
        if user_id is None:
            return _error_json(
                status_code=401,
                payload={
                    "code": "auth.unauthorized",
                    "message": "Missing owner credentials",
                    "details": {"entity": "auth", "cause": "missing_owner_user_id"},
                    "retryable": False,
                },
            )
        authz_result = provide_authz_dependencies(app_state)
        if authz_result.is_error or authz_result.value is None:
            mapped = map_result_error_to_api(authz_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        decision_result = authz_result.value.authz_service.authorize(
            action="http.read.owner",
            actor=AuthzActor(user_id=int(user_id)),
            resource_ctx=None,
        )
        if decision_result.is_error or decision_result.value is None or not decision_result.value.allowed:
            mapped = map_result_error_to_api(decision_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return None

    def _runtime_write_guard() -> JSONResponse | None:
        health_result = provide_runtime_dispatch_health(app_state)
        if health_result.is_error or health_result.value is None:
            mapped = map_result_error_to_api(health_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        health = dict(health_result.value)
        mode = str(health.get("mode", "single-instance"))
        is_runner = bool(health.get("is_runner", True))
        if mode == "single-runner" and not is_runner:
            return _error_json(
                status_code=409,
                payload={
                    "code": ErrorCode.RUNTIME_NON_RUNNER_REJECT.value,
                    "message": "Runtime write operation is unavailable on non-runner instance",
                    "details": {
                        "entity": "runtime_dispatch",
                        "cause": "non_runner_instance",
                        "mode": mode,
                        "is_runner": is_runner,
                    },
                    "retryable": False,
                },
            )
        return None

    @router.get(
        "/teams",
        response_model=ApiPagedResponse,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_teams(
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)

        teams_result = list_teams_result(deps_result.value.storage)
        if teams_result.is_error or teams_result.value is None:
            mapped = map_result_error_to_api(teams_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        teams = list(teams_result.value)
        total = len(teams)
        window = teams[offset : offset + limit]
        return _ok_paged(window, team_to_dto, total=total, limit=limit, offset=offset)

    @router.get(
        "/teams/{team_id}/roles",
        response_model=list[RoleDTO],
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_team_roles(
        team_id: int,
        include_inactive: bool = Query(default=False),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)

        roles_result = list_team_roles_result(
            deps_result.value.storage,
            team_id=team_id,
            include_inactive=include_inactive,
        )
        if roles_result.is_error or roles_result.value is None:
            mapped = map_result_error_to_api(roles_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return _ok_list(roles_result.value, role_to_dto)

    @router.get(
        "/roles/catalog",
        response_model=ApiPagedResponse,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_roles_catalog(
        include_inactive: bool = Query(default=False),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)

        catalog_result = list_roles_catalog_result(
            app_state.runtime,
            deps_result.value.storage,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )
        if catalog_result.is_error or catalog_result.value is None:
            mapped = map_result_error_to_api(catalog_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return _ok_paged(
            catalog_result.value.items,
            role_catalog_item_to_dto,
            total=catalog_result.value.total,
            limit=catalog_result.value.limit,
            offset=catalog_result.value.offset,
        )

    @router.get(
        "/roles/catalog/errors",
        response_model=list[RoleCatalogErrorDTO],
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_roles_catalog_errors(
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)

        errors_result = list_roles_catalog_errors_result(app_state.runtime, deps_result.value.storage)
        if errors_result.is_error or errors_result.value is None:
            mapped = map_result_error_to_api(errors_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return _ok_list(errors_result.value, role_catalog_error_to_dto)

    @router.get(
        "/teams/{team_id}/runtime-status",
        response_model=list[TeamRoleRuntimeStatusDTO],
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_team_runtime_status(
        team_id: int,
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        storage_result = provide_storage_uow_dependencies(app_state)
        if storage_result.is_error or storage_result.value is None:
            mapped = map_result_error_to_api(storage_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        queue_result = provide_queue_status_dependencies(app_state)
        if queue_result.is_error or queue_result.value is None:
            mapped = map_result_error_to_api(queue_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)

        runtime_status_result = list_team_runtime_status_result(
            storage_result.value.storage,
            queue_result.value.runtime_status_service,
            team_id=team_id,
        )
        if runtime_status_result.is_error or runtime_status_result.value is None:
            mapped = map_result_error_to_api(runtime_status_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return _ok_list(runtime_status_result.value, team_role_runtime_status_to_dto)

    @router.get(
        "/teams/{team_id}/sessions",
        response_model=ApiPagedResponse,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_team_sessions(
        team_id: int,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        sessions_result = list_team_sessions_result(
            deps_result.value.storage,
            team_id=team_id,
            limit=limit,
            offset=offset,
        )
        if sessions_result.is_error or sessions_result.value is None:
            mapped = map_result_error_to_api(sessions_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return _ok_paged(
            sessions_result.value.items,
            team_session_to_dto,
            total=sessions_result.value.total,
            limit=sessions_result.value.limit,
            offset=sessions_result.value.offset,
        )

    @router.get(
        "/runtime/dispatch-health",
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_runtime_dispatch_health(
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        health_result = provide_runtime_dispatch_health(app_state)
        if health_result.is_error or health_result.value is None:
            mapped = map_result_error_to_api(health_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return health_result.value

    @router.post(
        "/questions",
        response_model=QaCreateQuestionResponseDTO,
        status_code=202,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def create_question(
        payload: QaCreateQuestionRequestDTO = Body(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = create_question_result(
            deps_result.value.storage,
            request=QaCreateQuestionRequest(
                team_id=payload.team_id,
                created_by_user_id=payload.created_by_user_id,
                text=payload.text,
                team_role_id=payload.team_role_id,
                origin_type=payload.origin_type,
                source_question_id=payload.source_question_id,
                parent_answer_id=payload.parent_answer_id,
                thread_id=payload.thread_id,
                question_id=payload.question_id,
            ),
            idempotency_key=str(idempotency_key or ""),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        worker = getattr(app_state, "qa_dispatch_bridge_worker", None)
        if worker is not None:
            try:
                worker.enqueue_question(result.value.question.question_id)
            except Exception:
                # Bridge enqueue failures are non-fatal for HTTP contract.
                pass
        return qa_create_question_outcome_to_dto(result.value).model_dump(mode="json")

    @router.get(
        "/questions/{question_id}/status",
        response_model=QaQuestionStatusDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_question_status(
        question_id: str,
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = get_question_status_result(deps_result.value.storage, question_id=question_id)
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return qa_question_status_to_dto(result.value).model_dump(mode="json")

    @router.get(
        "/questions/{question_id}",
        response_model=QaQuestionDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_question(
        question_id: str,
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = get_question_result(deps_result.value.storage, question_id=question_id)
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return qa_question_to_dto(result.value).model_dump(mode="json")

    @router.get(
        "/answers/{answer_id}",
        response_model=QaAnswerDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_answer(
        answer_id: str,
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = get_answer_result(deps_result.value.storage, answer_id=answer_id)
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return qa_answer_to_dto(result.value).model_dump(mode="json")

    @router.get(
        "/questions/{question_id}/answer",
        response_model=QaAnswerDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_answer_by_question(
        question_id: str,
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = resolve_answer_by_question_result(deps_result.value.storage, question_id=question_id)
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return qa_answer_to_dto(result.value).model_dump(mode="json")

    @router.get(
        "/qa-journal",
        response_model=ApiCursorResponse,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_qa_journal(
        team_id: int | None = Query(default=None),
        team_role_id: int | None = Query(default=None),
        status: str | None = Query(default=None),
        thread_id: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = list_qa_journal_result(
            deps_result.value.storage,
            team_id=team_id,
            team_role_id=team_role_id,
            status=status,
            thread_id=thread_id,
            cursor=cursor,
            limit=limit,
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return _ok_cursor(
            result.value.items,
            qa_question_to_dto,
            limit=result.value.limit,
            next_cursor=result.value.next_cursor,
        )

    @router.get(
        "/threads/{thread_id}",
        response_model=QaThreadResponseDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_thread(
        thread_id: str,
        question_cursor: str | None = Query(default=None),
        answer_cursor: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = get_thread_result(
            deps_result.value.storage,
            thread_id=thread_id,
            question_cursor=question_cursor,
            answer_cursor=answer_cursor,
            limit=limit,
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return {
            "questions": _ok_cursor(
                result.value.questions.items,
                qa_question_to_dto,
                limit=result.value.questions.limit,
                next_cursor=result.value.questions.next_cursor,
            ),
            "answers": _ok_cursor(
                result.value.answers.items,
                qa_answer_to_dto,
                limit=result.value.answers.limit,
                next_cursor=result.value.answers.next_cursor,
            ),
        }

    @router.get(
        "/orchestrator/feed",
        response_model=ApiCursorResponse,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_orchestrator_feed(
        team_id: int = Query(...),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = list_orchestrator_feed_result(
            deps_result.value.storage,
            team_id=team_id,
            cursor=cursor,
            limit=limit,
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return _ok_cursor(
            result.value.items,
            qa_orchestrator_feed_item_to_dto,
            limit=result.value.limit,
            next_cursor=result.value.next_cursor,
        )

    @router.patch(
        "/teams/{team_id}/roles/{role_id}",
        response_model=TeamRolePatchOutcomeDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def patch_team_role(
        team_id: int,
        role_id: int,
        payload: TeamRolePatchRequestDTO = Body(...),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        blocked = _runtime_write_guard()
        if blocked is not None:
            return blocked
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = patch_team_role_result(
            deps_result.value.storage,
            team_id=team_id,
            role_id=role_id,
            patch=TeamRolePatchRequest(
                enabled=payload.enabled,
                is_orchestrator=payload.is_orchestrator,
                model_override=payload.model_override,
                display_name=payload.display_name,
                system_prompt_override=payload.system_prompt_override,
                extra_instruction_override=payload.extra_instruction_override,
                user_prompt_suffix=payload.user_prompt_suffix,
                user_reply_prefix=payload.user_reply_prefix,
            ),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return team_role_patch_outcome_to_dto(result.value).model_dump(mode="json")

    @router.post(
        "/teams/{team_id}/roles/{role_id}/reset-session",
        response_model=MutationAckDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def reset_team_role_session(
        team_id: int,
        role_id: int,
        payload: TeamRoleUserMutationRequestDTO = Body(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        blocked = _runtime_write_guard()
        if blocked is not None:
            return blocked
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = reset_team_role_session_write_result(
            app_state.runtime,
            deps_result.value.storage,
            team_id=team_id,
            role_id=role_id,
            telegram_user_id=payload.telegram_user_id,
            idempotency_key=str(idempotency_key or ""),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return mutation_ack_to_dto(result.value).model_dump(mode="json")

    @router.delete(
        "/teams/{team_id}/roles/{role_id}",
        status_code=204,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def deactivate_team_role_binding(
        team_id: int,
        role_id: int,
        payload: TeamRoleUserMutationRequestDTO = Body(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        blocked = _runtime_write_guard()
        if blocked is not None:
            return blocked
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = deactivate_team_role_binding_write_result(
            app_state.runtime,
            deps_result.value.storage,
            team_id=team_id,
            role_id=role_id,
            telegram_user_id=payload.telegram_user_id,
            idempotency_key=str(idempotency_key or ""),
        )
        if result.is_error:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return Response(status_code=204)

    @router.put(
        "/team-roles/{team_role_id}/skills/{skill_id}",
        response_model=TeamRoleSkillOutcomeDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def put_team_role_skill(
        team_role_id: int,
        skill_id: str,
        payload: TeamRoleSkillPutRequestDTO = Body(...),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        blocked = _runtime_write_guard()
        if blocked is not None:
            return blocked
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = put_team_role_skill_result(
            app_state.runtime,
            deps_result.value.storage,
            request=TeamRoleSkillPutRequest(
                team_role_id=team_role_id,
                skill_id=skill_id,
                enabled=payload.enabled,
                config=payload.config,
            ),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return team_role_skill_outcome_to_dto(result.value).model_dump(mode="json")

    @router.put(
        "/team-roles/{team_role_id}/prepost/{prepost_id}",
        response_model=TeamRolePrepostOutcomeDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def put_team_role_prepost(
        team_role_id: int,
        prepost_id: str,
        payload: TeamRolePrepostPutRequestDTO = Body(...),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        blocked = _runtime_write_guard()
        if blocked is not None:
            return blocked
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = put_team_role_prepost_result(
            app_state.runtime,
            deps_result.value.storage,
            request=TeamRolePrepostPutRequest(
                team_role_id=team_role_id,
                prepost_id=prepost_id,
                enabled=payload.enabled,
                config=payload.config,
            ),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return team_role_prepost_outcome_to_dto(result.value).model_dump(mode="json")

    return router
