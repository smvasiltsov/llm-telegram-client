from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import json
from typing import Any

from app.application.authz import AuthzActor
from app.application.contracts import ErrorCode
from app.application.observability import ensure_correlation_id, get_correlation_id
from app.application.use_cases.read_api import (
    list_master_roles_catalog_result,
    list_prepost_processing_tools_result,
    list_providers_catalog_result,
    list_roles_catalog_errors_result,
    list_skills_result,
    list_team_roles_result,
    list_team_runtime_status_result,
    list_team_sessions_result,
    list_teams_result,
)
from app.application.use_cases.recovery_reset import (
    RecoveryQueuesSnapshot,
    reset_recovery_queues_result,
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
    TeamRenameRequest,
    MasterRoleCreateRequest,
    MasterRolePatchRequest,
    TeamRolePrepostReplaceItem,
    TeamRolePrepostReplaceRequest,
    TeamRoleSkillReplaceItem,
    TeamRoleSkillsReplaceRequest,
    bind_master_role_to_team_result,
    create_master_role_result,
    create_team_result,
    delete_master_role_result,
    delete_team_result,
    rename_team_result,
    TeamRolePatchRequest,
    TeamCreateRequest,
    TeamRolePrepostPutRequest,
    TeamRoleRootDirPutRequest,
    TeamRoleSkillPutRequest,
    TeamRoleWorkingDirPutRequest,
    deactivate_team_role_binding_write_result,
    patch_master_role_result,
    patch_team_role_result,
    replace_team_role_prepost_result,
    replace_team_role_skills_result,
    put_team_role_prepost_result,
    put_team_role_root_dir_result,
    put_team_role_skill_result,
    put_team_role_working_dir_result,
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
    EventDeliveriesSummaryDTO,
    EventDeliveryActionRequestDTO,
    EventDeliveryDTO,
    EventSubscriptionDTO,
    EventSubscriptionUpsertRequestDTO,
    ApiPageMeta,
    ApiPagedResponse,
    MasterRoleCatalogItemDTO,
    MasterRoleCreateOutcomeDTO,
    MasterRoleCreateRequestDTO,
    MasterRolePatchOutcomeDTO,
    MasterRolePatchRequestDTO,
    MutationAckDTO,
    PrePostProcessingToolDTO,
    ProviderCatalogItemDTO,
    QaAnswerDTO,
    QaCreateQuestionRequestDTO,
    QaCreateQuestionResponseDTO,
    QaOrchestratorFeedItemDTO,
    QaQuestionDTO,
    QaQuestionStatusDTO,
    QaThreadResponseDTO,
    RecoveryQueuesResetRequestDTO,
    RecoveryQueuesResetResponseDTO,
    RecoveryQueuesResetSnapshotDTO,
    RoleDTO,
    RoleCatalogErrorDTO,
    SkillDTO,
    TeamDTO,
    TeamRolePatchOutcomeDTO,
    TeamRolePatchRequestDTO,
    TeamRolePrepostReplaceOutcomeDTO,
    TeamRolePrepostReplaceRequestDTO,
    TeamRolePrepostOutcomeDTO,
    TeamRolePrepostPutRequestDTO,
    TeamRoleRootDirOutcomeDTO,
    TeamRoleRootDirPutRequestDTO,
    TeamRoleRuntimeCurrentQuestionDTO,
    TeamRoleRuntimeOverviewDTO,
    TeamRoleSkillReplaceRequestDTO,
    TeamRoleSkillsReplaceOutcomeDTO,
    TeamRoleRuntimeStatusDTO,
    TeamRoleSkillOutcomeDTO,
    TeamRoleSkillPutRequestDTO,
    TeamRoleUserMutationRequestDTO,
    TeamRoleWorkingDirOutcomeDTO,
    TeamRoleWorkingDirPutRequestDTO,
    TeamCreateOutcomeDTO,
    TeamCreateRequestDTO,
    TeamRenameOutcomeDTO,
    TeamRenameRequestDTO,
    ThreadEventTraceDTO,
    ThreadEventDTO,
    master_role_catalog_item_to_dto,
    master_role_patch_outcome_to_dto,
    mutation_ack_to_dto,
    prepost_processing_tool_to_dto,
    provider_catalog_item_to_dto,
    qa_answer_to_dto,
    qa_create_question_outcome_to_dto,
    qa_orchestrator_feed_item_to_dto,
    qa_question_status_to_dto,
    qa_question_to_dto,
    role_catalog_error_to_dto,
    role_to_dto,
    skill_to_dto,
    team_role_patch_outcome_to_dto,
    team_role_bind_outcome_to_dto,
    team_role_prepost_outcome_to_dto,
    team_role_root_dir_outcome_to_dto,
    team_role_skill_outcome_to_dto,
    team_role_working_dir_outcome_to_dto,
    team_session_to_dto,
    team_role_runtime_status_to_dto,
    team_to_dto,
    event_delivery_to_dto,
    event_subscription_to_dto,
    thread_event_to_dto,
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

    def _parse_iso(ts: str | None) -> datetime | None:
        value = str(ts or "").strip()
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _event_delivery_lag_ms(item) -> float | None:
        start = _parse_iso(getattr(item, "created_at", None))
        if start is None:
            return None
        end = _parse_iso(getattr(item, "delivered_at", None)) or datetime.now(timezone.utc)
        return max(0.0, (end - start).total_seconds() * 1000.0)

    def _event_delivery_to_payload(item) -> dict[str, object]:
        payload = event_delivery_to_dto(item).model_dump(mode="json")
        payload["lag_ms"] = _event_delivery_lag_ms(item)
        return payload

    def _resolve_thread_event_author_name(*, storage, item) -> str | None:
        if storage is None:
            return None
        author_type = str(getattr(item, "author_type", "") or "").strip().lower()
        if author_type == "user":
            return "user"
        if author_type != "role":
            return None
        candidate_answer_ids: list[str] = []
        for raw in (
            getattr(item, "answer_id", None),
            getattr(item, "parent_answer_id", None),
            (getattr(item, "source_ref_id", None) if str(getattr(item, "source_ref_type", "") or "").strip().lower() == "answer" else None),
        ):
            value = str(raw or "").strip()
            if value and value not in candidate_answer_ids:
                candidate_answer_ids.append(value)
        for answer_id in candidate_answer_ids:
            answer = storage.get_answer(answer_id)
            if answer is None:
                continue
            role_name = str(getattr(answer, "role_name", "") or "").strip()
            if role_name:
                return role_name
        return "role"

    def _thread_event_to_payload(item, *, storage=None) -> dict[str, object]:
        payload = thread_event_to_dto(item).model_dump(mode="json")
        raw = str(payload.get("payload_json") or "").strip()
        if not raw:
            author_name = _resolve_thread_event_author_name(storage=storage, item=item)
            if author_name is not None:
                payload["author_name"] = author_name
            return payload
        try:
            parsed = json.loads(raw)
            payload["payload_json"] = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            pass
        author_name = _resolve_thread_event_author_name(storage=storage, item=item)
        if author_name is not None:
            payload["author_name"] = author_name
        return payload

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
        "/skills",
        response_model=list[SkillDTO],
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_skills(
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        result = list_skills_result(app_state.runtime)
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return _ok_list(result.value, skill_to_dto)

    @router.get(
        "/prepost_processing_tools",
        response_model=list[PrePostProcessingToolDTO],
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_prepost_processing_tools(
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        result = list_prepost_processing_tools_result(app_state.runtime)
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return _ok_list(result.value, prepost_processing_tool_to_dto)

    @router.get(
        "/providers/catalog",
        response_model=list[ProviderCatalogItemDTO],
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_providers_catalog(
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        result = list_providers_catalog_result(app_state.runtime)
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return _ok_list(result.value, provider_catalog_item_to_dto)

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
            runtime=app_state.runtime,
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

        catalog_result = list_master_roles_catalog_result(
            app_state.runtime,
            deps_result.value.storage,
            limit=limit,
            offset=offset,
        )
        if catalog_result.is_error or catalog_result.value is None:
            mapped = map_result_error_to_api(catalog_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return _ok_paged(
            catalog_result.value.items,
            master_role_catalog_item_to_dto,
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
        "/teams/{team_id}/runtime-status/overview",
        response_model=list[TeamRoleRuntimeOverviewDTO],
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_team_runtime_status_overview(
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

        storage = storage_result.value.storage
        runtime_status_result = list_team_runtime_status_result(
            storage,
            queue_result.value.runtime_status_service,
            team_id=team_id,
        )
        if runtime_status_result.is_error or runtime_status_result.value is None:
            mapped = map_result_error_to_api(runtime_status_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)

        roles_result = list_team_roles_result(
            storage,
            team_id=team_id,
            include_inactive=False,
            runtime=app_state.runtime,
        )
        if roles_result.is_error or roles_result.value is None:
            mapped = map_result_error_to_api(roles_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)

        status_by_team_role_id = {
            int(item.team_role_id): item
            for item in runtime_status_result.value
            if int(getattr(item, "team_role_id", 0) or 0) > 0
        }
        items: list[TeamRoleRuntimeOverviewDTO] = []
        for role in roles_result.value:
            resolved_team_role_id = (
                int(role.team_role_id)
                if role.team_role_id is not None
                else storage.resolve_team_role_id(team_id, int(role.role_id), ensure_exists=False)
            )
            if resolved_team_role_id is None:
                continue
            team_role_id = int(resolved_team_role_id)
            runtime_status = status_by_team_role_id.get(team_role_id)
            status = str(getattr(runtime_status, "status", "free") or "free")
            if status not in {"free", "busy"}:
                status = "free"
            current_question = None
            if status == "busy":
                in_progress, _ = storage.list_qa_journal(
                    team_id=team_id,
                    team_role_id=team_role_id,
                    status="in_progress",
                    limit=1,
                )
                if in_progress:
                    q = in_progress[0]
                    current_question = TeamRoleRuntimeCurrentQuestionDTO(
                        question_id=str(q.question_id),
                        thread_id=str(q.thread_id),
                        text=str(q.text or ""),
                        status=str(q.status or "in_progress"),
                        updated_at=str(q.updated_at or ""),
                        source="question",
                    )
                elif runtime_status is not None and str(getattr(runtime_status, "preview_text", "") or "").strip():
                    current_question = TeamRoleRuntimeCurrentQuestionDTO(
                        question_id=None,
                        thread_id=None,
                        text=str(getattr(runtime_status, "preview_text", "") or ""),
                        status=None,
                        updated_at=str(getattr(runtime_status, "updated_at", "") or ""),
                        source="preview",
                    )
            items.append(
                TeamRoleRuntimeOverviewDTO(
                    team_id=int(team_id),
                    role_id=int(role.role_id),
                    team_role_id=team_role_id,
                    role_name=str(role.role_name),
                    display_name=str(role.public_name()),
                    status=status,  # type: ignore[arg-type]
                    busy_request_id=(str(runtime_status.busy_request_id) if runtime_status and runtime_status.busy_request_id else None),
                    busy_since=(str(runtime_status.busy_since) if runtime_status and runtime_status.busy_since else None),
                    lease_expires_at=(str(runtime_status.lease_expires_at) if runtime_status and runtime_status.lease_expires_at else None),
                    current_question=current_question,
                )
            )
        return [item.model_dump(mode="json") for item in items]

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
        payload_raw: dict[str, Any] = Body(
            ...,
            example={
                "team_id": 101,
                "text": "@dev проверь последние изменения в спецификации",
                "team_role_id": 12,
                "thread_id": "018f6f9a-4a62-7df1-bb44-a0f71e6a1c11",
                "question_id": "018f6f9a-4a63-7a91-bbf5-4f81d9d6f9c2",
                "origin_type": "user",
                "source_question_id": None,
                "parent_answer_id": None,
            },
        ),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        effective_owner_user_id = owner_user_id if owner_user_id is not None else x_owner_user_id
        denied = _owner_guard(effective_owner_user_id)
        if denied is not None:
            return denied
        payload_data = dict(payload_raw or {})
        payload_data.pop("created_by_user_id", None)
        try:
            payload = QaCreateQuestionRequestDTO.model_validate(payload_data)
        except Exception:
            return _error_json(
                status_code=422,
                payload={
                    "code": ErrorCode.VALIDATION_INVALID_INPUT.value,
                    "message": "Invalid question payload",
                    "details": {"entity": "question", "cause": "invalid_payload"},
                    "retryable": False,
                },
            )
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        result = create_question_result(
            deps_result.value.storage,
            request=QaCreateQuestionRequest(
                team_id=payload.team_id,
                created_by_user_id=int(effective_owner_user_id),
                text=payload.text,
                team_role_id=payload.team_role_id,
                origin_interface=payload.origin_interface,
                origin_type=payload.origin_type,
                source_question_id=payload.source_question_id,
                parent_answer_id=payload.parent_answer_id,
                thread_id=payload.thread_id,
                question_id=payload.question_id,
            ),
            idempotency_key=str(idempotency_key or ""),
            provider_registry=dict(getattr(app_state.runtime, "provider_registry", {}) or {}),
            provider_models=list(getattr(app_state.runtime, "provider_models", []) or []),
            provider_model_map=dict(getattr(app_state.runtime, "provider_model_map", {}) or {}),
            default_provider_id=str(getattr(app_state.runtime, "default_provider_id", "") or ""),
            metrics_port=getattr(app_state.runtime, "metrics_port", None),
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
        "/roles/{role_id}",
        response_model=MasterRolePatchOutcomeDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def patch_master_role(
        role_id: int,
        payload: MasterRolePatchRequestDTO = Body(...),
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
        result = patch_master_role_result(
            deps_result.value.storage,
            role_id=role_id,
            patch=MasterRolePatchRequest(
                role_name=payload.role_name,
                llm_model=payload.llm_model,
                system_prompt=payload.system_prompt,
                extra_instruction=(
                    payload.extra_instructions
                    if payload.extra_instructions is not None
                    else payload.extra_instruction
                ),
            ),
            runtime=app_state.runtime,
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return master_role_patch_outcome_to_dto(result.value).model_dump(mode="json")

    @router.post(
        "/roles",
        response_model=MasterRoleCreateOutcomeDTO,
        status_code=201,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def create_master_role(
        payload: MasterRoleCreateRequestDTO = Body(...),
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
        result = create_master_role_result(
            deps_result.value.storage,
            request=MasterRoleCreateRequest(
                role_name=payload.role_name,
                system_prompt=payload.system_prompt,
                llm_model=payload.llm_model,
                description=payload.description,
                extra_instruction=payload.extra_instructions,
            ),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return MasterRoleCreateOutcomeDTO(
            role_id=int(result.value.role_id),
            role_name=str(result.value.role_name),
            llm_model=result.value.llm_model,
            system_prompt=str(result.value.system_prompt),
            extra_instructions=str(result.value.extra_instruction or ""),
            description=str(result.value.description or ""),
            is_active=bool(result.value.is_active),
        ).model_dump(mode="json")

    @router.post(
        "/teams",
        response_model=TeamCreateOutcomeDTO,
        status_code=201,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def create_team(
        payload: TeamCreateRequestDTO = Body(...),
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
        result = create_team_result(
            deps_result.value.storage,
            request=TeamCreateRequest(name=payload.name),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return TeamCreateOutcomeDTO.model_validate(result.value).model_dump(mode="json")

    @router.patch(
        "/teams/{team_id}",
        response_model=TeamRenameOutcomeDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def rename_team(
        team_id: int,
        payload: TeamRenameRequestDTO = Body(...),
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
        result = rename_team_result(
            deps_result.value.storage,
            team_id=team_id,
            request=TeamRenameRequest(name=payload.name),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return TeamRenameOutcomeDTO.model_validate(result.value).model_dump(mode="json")

    @router.delete(
        "/teams/{team_id}",
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
    def delete_team(
        team_id: int,
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
        result = delete_team_result(
            deps_result.value.storage,
            team_id=team_id,
        )
        if result.is_error:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return Response(status_code=204)

    @router.delete(
        "/roles/{role_id}",
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
    def delete_master_role(
        role_id: int,
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
        result = delete_master_role_result(
            deps_result.value.storage,
            role_id=role_id,
        )
        if result.is_error:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return Response(status_code=204)

    @router.post(
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
    def bind_master_role_to_team(
        team_id: int,
        role_id: int,
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
        result = bind_master_role_to_team_result(
            deps_result.value.storage,
            team_id=team_id,
            role_id=role_id,
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return team_role_bind_outcome_to_dto(result.value).model_dump(mode="json")

    @router.patch(
        "/team-roles/{team_role_id}",
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
        team_role_id: int,
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
            team_role_id=team_role_id,
            patch=TeamRolePatchRequest(
                enabled=payload.enabled,
                is_active=payload.is_active,
                is_orchestrator=payload.is_orchestrator,
                model_override=payload.model_override,
                display_name=payload.display_name,
                system_prompt_override=(
                    payload.system_prompt
                    if payload.system_prompt is not None
                    else payload.system_prompt_override
                ),
                extra_instruction_override=(
                    payload.extra_instructions
                    if payload.extra_instructions is not None
                    else payload.extra_instruction_override
                ),
                user_prompt_suffix=payload.user_prompt_suffix,
                user_reply_prefix=payload.user_reply_prefix,
            ),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return team_role_patch_outcome_to_dto(result.value).model_dump(mode="json")

    @router.post(
        "/team-roles/{team_role_id}/reset-session",
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
        team_role_id: int,
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
            team_role_id=team_role_id,
            telegram_user_id=payload.telegram_user_id,
            idempotency_key=str(idempotency_key or ""),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return mutation_ack_to_dto(result.value).model_dump(mode="json")

    @router.delete(
        "/team-roles/{team_role_id}",
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
        team_role_id: int,
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
            team_role_id=team_role_id,
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
        "/team-roles/{team_role_id}/skills",
        response_model=TeamRoleSkillsReplaceOutcomeDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def replace_team_role_skills(
        team_role_id: int,
        payload: TeamRoleSkillReplaceRequestDTO = Body(...),
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
        result = replace_team_role_skills_result(
            app_state.runtime,
            deps_result.value.storage,
            request=TeamRoleSkillsReplaceRequest(
                team_role_id=team_role_id,
                items=tuple(
                    TeamRoleSkillReplaceItem(
                        skill_id=item.skill_id,
                        enabled=bool(item.enabled),
                        config=item.config,
                    )
                    for item in payload.items
                ),
            ),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return TeamRoleSkillsReplaceOutcomeDTO(
            items=[team_role_skill_outcome_to_dto(item) for item in result.value.items]
        ).model_dump(mode="json")

    @router.put(
        "/team-roles/{team_role_id}/working-dir",
        response_model=TeamRoleWorkingDirOutcomeDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def put_team_role_working_dir(
        team_role_id: int,
        payload: TeamRoleWorkingDirPutRequestDTO = Body(...),
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
        result = put_team_role_working_dir_result(
            app_state.runtime,
            deps_result.value.storage,
            request=TeamRoleWorkingDirPutRequest(
                team_role_id=team_role_id,
                working_dir=payload.working_dir,
            ),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return team_role_working_dir_outcome_to_dto(result.value).model_dump(mode="json")

    @router.put(
        "/team-roles/{team_role_id}/root-dir",
        response_model=TeamRoleRootDirOutcomeDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def put_team_role_root_dir(
        team_role_id: int,
        payload: TeamRoleRootDirPutRequestDTO = Body(...),
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
        result = put_team_role_root_dir_result(
            app_state.runtime,
            deps_result.value.storage,
            request=TeamRoleRootDirPutRequest(
                team_role_id=team_role_id,
                root_dir=payload.root_dir,
            ),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return team_role_root_dir_outcome_to_dto(result.value).model_dump(mode="json")

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

    @router.put(
        "/team-roles/{team_role_id}/prepost",
        response_model=TeamRolePrepostReplaceOutcomeDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def replace_team_role_prepost(
        team_role_id: int,
        payload: TeamRolePrepostReplaceRequestDTO = Body(...),
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
        result = replace_team_role_prepost_result(
            app_state.runtime,
            deps_result.value.storage,
            request=TeamRolePrepostReplaceRequest(
                team_role_id=team_role_id,
                items=tuple(
                    TeamRolePrepostReplaceItem(
                        prepost_id=item.prepost_id,
                        enabled=bool(item.enabled),
                        config=item.config,
                    )
                    for item in payload.items
                ),
            ),
        )
        if result.is_error or result.value is None:
            mapped = map_result_error_to_api(result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)
        return TeamRolePrepostReplaceOutcomeDTO(
            items=[team_role_prepost_outcome_to_dto(item) for item in result.value.items]
        ).model_dump(mode="json")

    @router.post(
        "/admin/recovery/queues/reset",
        response_model=RecoveryQueuesResetResponseDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def reset_recovery_queues(
        payload: RecoveryQueuesResetRequestDTO = Body(...),
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
        owner_user_id: int | None = Query(default=None),
    ):
        denied = _owner_guard(owner_user_id if owner_user_id is not None else x_owner_user_id)
        if denied is not None:
            return denied
        blocked = _runtime_write_guard()
        if blocked is not None:
            return blocked
        if payload.scope.mode == "team" and payload.scope.team_id is None:
            return _error_json(
                status_code=422,
                payload={
                    "code": ErrorCode.VALIDATION_INVALID_INPUT.value,
                    "message": "scope.team_id is required when scope.mode=team",
                    "details": {"entity": "recovery_reset", "cause": "team_scope_missing_team_id"},
                    "retryable": False,
                },
            )
        if payload.scope.mode == "global" and payload.scope.team_id is not None:
            return _error_json(
                status_code=422,
                payload={
                    "code": ErrorCode.VALIDATION_INVALID_INPUT.value,
                    "message": "scope.team_id must be omitted when scope.mode=global",
                    "details": {"entity": "recovery_reset", "cause": "global_scope_unexpected_team_id"},
                    "retryable": False,
                },
            )
        deps_result = provide_storage_uow_dependencies(app_state)
        if deps_result.is_error or deps_result.value is None:
            mapped = map_result_error_to_api(deps_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)

        outcome_result = reset_recovery_queues_result(
            deps_result.value.storage,
            scope_mode=payload.scope.mode,
            team_id=payload.scope.team_id,
            dry_run=bool(payload.dry_run),
        )
        if outcome_result.is_error or outcome_result.value is None:
            mapped = map_result_error_to_api(outcome_result)
            return _error_json(status_code=mapped.status_code, payload=mapped.payload)

        def _snapshot_to_dto(snapshot: RecoveryQueuesSnapshot) -> RecoveryQueuesResetSnapshotDTO:
            return RecoveryQueuesResetSnapshotDTO(
                questions_accepted=int(snapshot.questions_accepted),
                questions_queued=int(snapshot.questions_queued),
                questions_in_progress=int(snapshot.questions_in_progress),
                qa_dispatch_bridge_rows=int(snapshot.qa_dispatch_bridge_rows),
                event_deliveries_pending=int(snapshot.event_deliveries_pending),
                event_deliveries_retry_scheduled=int(snapshot.event_deliveries_retry_scheduled),
                event_deliveries_in_progress=int(snapshot.event_deliveries_in_progress),
                runtime_status_busy=int(snapshot.runtime_status_busy),
                runtime_status_free=int(snapshot.runtime_status_free),
                runtime_status_pending=int(snapshot.runtime_status_pending),
            )

        outcome = outcome_result.value
        return RecoveryQueuesResetResponseDTO(
            scope=payload.scope,
            dry_run=bool(outcome.dry_run),
            applied=bool(outcome.applied),
            before=_snapshot_to_dto(outcome.before),
            after=_snapshot_to_dto(outcome.after),
            delta=_snapshot_to_dto(outcome.delta),
            summary=outcome.summary,
        ).model_dump(mode="json")

    @router.get(
        "/admin/event-subscriptions",
        response_model=list[EventSubscriptionDTO],
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def list_event_subscriptions(
        scope: str | None = Query(default=None),
        scope_id: str | None = Query(default=None),
        interface_type: str | None = Query(default=None),
        active_only: bool = Query(default=True),
        limit: int = Query(default=200, ge=1, le=1000),
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
        items = deps_result.value.storage.list_event_subscriptions(
            scope=scope,
            scope_id=scope_id,
            interface_type=interface_type,
            active_only=bool(active_only),
            limit=limit,
        )
        return _ok_list(items, event_subscription_to_dto)

    @router.put(
        "/admin/event-subscriptions",
        response_model=EventSubscriptionDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def upsert_event_subscription(
        payload: EventSubscriptionUpsertRequestDTO = Body(...),
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
        storage = deps_result.value.storage
        with storage.transaction(immediate=True):
            item = storage.upsert_event_subscription(
                scope=payload.scope,
                scope_id=payload.scope_id,
                interface_type=payload.interface_type,
                target_id=payload.target_id,
                mode=payload.mode,
                is_active=payload.is_active,
                options_json=payload.options_json,
            )
        return event_subscription_to_dto(item).model_dump(mode="json")

    @router.delete(
        "/admin/event-subscriptions/{subscription_id}",
        status_code=204,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def delete_event_subscription(
        subscription_id: int,
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
        storage = deps_result.value.storage
        with storage.transaction(immediate=True):
            deleted = storage.delete_event_subscription(subscription_id)
        if not deleted:
            return _error_json(
                status_code=404,
                payload={
                    "code": ErrorCode.QA_NOT_FOUND.value,
                    "message": f"Event subscription not found: {subscription_id}",
                    "details": {"entity": "event_subscription", "id": int(subscription_id), "cause": "not_found"},
                    "retryable": False,
                },
            )
        return Response(status_code=204)

    @router.get(
        "/admin/thread-events",
        response_model=list[ThreadEventDTO],
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def list_thread_events(
        event_id: str | None = Query(default=None),
        thread_id: str | None = Query(default=None),
        team_id: int | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=500),
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
        items = deps_result.value.storage.list_thread_events(
            event_id=event_id,
            thread_id=thread_id,
            team_id=team_id,
            limit=limit,
        )
        return [_thread_event_to_payload(item, storage=deps_result.value.storage) for item in items]

    @router.get(
        "/admin/thread-events/trace",
        response_model=ThreadEventTraceDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_thread_event_trace(
        event_id: str = Query(...),
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
        storage = deps_result.value.storage
        event = storage.get_thread_event(event_id)
        if event is None:
            return _error_json(
                status_code=404,
                payload={
                    "code": ErrorCode.QA_NOT_FOUND.value,
                    "message": f"Thread event not found: {event_id}",
                    "details": {"entity": "thread_event", "id": str(event_id), "cause": "not_found"},
                    "retryable": False,
                },
            )
        deliveries = storage.list_event_deliveries(event_id=event_id, limit=1000)
        return {
            "event": _thread_event_to_payload(event, storage=storage),
            "deliveries": [_event_delivery_to_payload(item) for item in deliveries],
        }

    @router.get(
        "/admin/event-deliveries",
        response_model=list[EventDeliveryDTO],
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def list_event_deliveries(
        event_id: str | None = Query(default=None),
        interface_type: str | None = Query(default=None),
        target_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
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
        items = deps_result.value.storage.list_event_deliveries(
            event_id=event_id,
            interface_type=interface_type,
            target_id=target_id,
            status=status,
            limit=limit,
        )
        return [_event_delivery_to_payload(item) for item in items]

    @router.get(
        "/admin/event-deliveries/summary",
        response_model=EventDeliveriesSummaryDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def get_event_deliveries_summary(
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
        storage = deps_result.value.storage
        statuses = ("pending", "in_progress", "retry_scheduled", "delivered", "skipped", "failed_dlq")
        counts = {name: int(storage.count_event_deliveries(status=name)) for name in statuses}
        recent = storage.list_event_deliveries(limit=1000)
        lags = [lag for lag in (_event_delivery_lag_ms(item) for item in recent) if lag is not None]
        avg_lag = (sum(lags) / len(lags)) if lags else None
        max_lag = max(lags) if lags else None
        return EventDeliveriesSummaryDTO(
            total=int(storage.count_event_deliveries()),
            pending=counts["pending"],
            in_progress=counts["in_progress"],
            retry_scheduled=counts["retry_scheduled"],
            delivered=counts["delivered"],
            skipped=counts["skipped"],
            failed_dlq=counts["failed_dlq"],
            avg_lag_ms=avg_lag,
            max_lag_ms=max_lag,
        ).model_dump(mode="json")

    @router.post(
        "/admin/event-deliveries/{delivery_id}/retry",
        response_model=EventDeliveryDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def retry_event_delivery(
        delivery_id: int,
        payload: EventDeliveryActionRequestDTO | None = Body(default=None),
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
        storage = deps_result.value.storage
        req = payload or EventDeliveryActionRequestDTO()
        with storage.transaction(immediate=True):
            item = storage.requeue_event_delivery(delivery_id, reset_attempt_count=bool(req.reset_attempt_count))
        if item is None:
            return _error_json(
                status_code=404,
                payload={
                    "code": ErrorCode.QA_NOT_FOUND.value,
                    "message": f"Event delivery not found: {delivery_id}",
                    "details": {"entity": "event_delivery", "id": int(delivery_id), "cause": "not_found"},
                    "retryable": False,
                },
            )
        return _event_delivery_to_payload(item)

    @router.post(
        "/admin/event-deliveries/{delivery_id}/skip",
        response_model=EventDeliveryDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def skip_event_delivery(
        delivery_id: int,
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
        storage = deps_result.value.storage
        with storage.transaction(immediate=True):
            item = storage.skip_event_delivery(delivery_id)
        if item is None:
            return _error_json(
                status_code=404,
                payload={
                    "code": ErrorCode.QA_NOT_FOUND.value,
                    "message": f"Event delivery not found: {delivery_id}",
                    "details": {"entity": "event_delivery", "id": int(delivery_id), "cause": "not_found"},
                    "retryable": False,
                },
            )
        return _event_delivery_to_payload(item)

    @router.post(
        "/admin/event-deliveries/{delivery_id}/dlq-requeue",
        response_model=EventDeliveryDTO,
        responses={
            401: {"model": ApiErrorResponse},
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            500: {"model": ApiErrorResponse},
        },
    )
    def requeue_dlq_event_delivery(
        delivery_id: int,
        payload: EventDeliveryActionRequestDTO | None = Body(default=None),
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
        storage = deps_result.value.storage
        current = storage.get_event_delivery(delivery_id)
        if current is None:
            return _error_json(
                status_code=404,
                payload={
                    "code": ErrorCode.QA_NOT_FOUND.value,
                    "message": f"Event delivery not found: {delivery_id}",
                    "details": {"entity": "event_delivery", "id": int(delivery_id), "cause": "not_found"},
                    "retryable": False,
                },
            )
        if str(current.status) != "failed_dlq":
            return _error_json(
                status_code=422,
                payload={
                    "code": ErrorCode.VALIDATION_INVALID_INPUT.value,
                    "message": f"Delivery is not in DLQ state: {current.status}",
                    "details": {"entity": "event_delivery", "id": int(delivery_id), "cause": "status_invalid"},
                    "retryable": False,
                },
            )
        with storage.transaction(immediate=True):
            req = payload or EventDeliveryActionRequestDTO()
            item = storage.requeue_event_delivery(delivery_id, reset_attempt_count=bool(req.reset_attempt_count))
        if item is None:
            return _error_json(
                status_code=404,
                payload={
                    "code": ErrorCode.QA_NOT_FOUND.value,
                    "message": f"Event delivery not found: {delivery_id}",
                    "details": {"entity": "event_delivery", "id": int(delivery_id), "cause": "not_found"},
                    "retryable": False,
                },
            )
        return _event_delivery_to_payload(item)

    return router
