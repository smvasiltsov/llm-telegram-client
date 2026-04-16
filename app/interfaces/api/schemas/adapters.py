from __future__ import annotations

from typing import Any

from app.application.contracts.result import Result
from app.application.use_cases.write_api import (
    MasterRolePatchOutcome,
    MutationAck,
    TeamRoleBindOutcome,
    TeamRolePatchOutcome,
    TeamRolePrepostOutcome,
    TeamRoleRootDirOutcome,
    TeamRoleSkillOutcome,
    TeamRoleWorkingDirOutcome,
)
from app.application.use_cases.qa_api import QaCreateQuestionOutcome, QaQuestionStatus
from app.application.use_cases.read_api import RegistryItem
from app.models import (
    EventDelivery,
    EventSubscription,
    MasterRoleCatalogItem,
    QaAnswer,
    QaOrchestratorFeedItem,
    QaQuestion,
    Role,
    RoleLinkedItem,
    RoleCatalogError,
    RoleCatalogItem,
    Team,
    TeamBinding,
    TeamRole,
    TeamRoleRuntimeStatus,
    TeamSessionView,
    ThreadEvent,
    UserRoleSession,
)

from .entities import (
    QaAnswerDTO,
    QaCreateQuestionResponseDTO,
    QaOrchestratorFeedItemDTO,
    QaQuestionDTO,
    QaQuestionStatusDTO,
    RoleDTO,
    RoleCatalogErrorDTO,
    RoleCatalogItemDTO,
    MutationAckDTO,
    MasterRoleCatalogItemDTO,
    MasterRolePatchOutcomeDTO,
    EventDeliveryDTO,
    EventSubscriptionDTO,
    ThreadEventDTO,
    PrePostProcessingToolDTO,
    TeamBindingDTO,
    RoleLinkedItemDTO,
    SkillDTO,
    TeamDTO,
    TeamRolePatchOutcomeDTO,
    TeamRolePrepostOutcomeDTO,
    TeamRoleRootDirOutcomeDTO,
    TeamRoleSkillOutcomeDTO,
    TeamRoleDTO,
    TeamRoleRuntimeStatusDTO,
    TeamRoleWorkingDirOutcomeDTO,
    TeamSessionDTO,
    UserRoleSessionDTO,
)
from .operations import (
    DeleteRequestDTO,
    GetRequestDTO,
    ListRequestDTO,
    OperationResultDTO,
    ResetRequestDTO,
    UpdateRequestDTO,
)


def role_to_dto(value: Role) -> RoleDTO:
    return RoleDTO(
        role_id=value.role_id,
        team_role_id=value.team_role_id,
        role_name=value.role_name,
        description=value.description,
        system_prompt=value.base_system_prompt,
        extra_instructions=value.extra_instruction,
        llm_model=value.llm_model,
        working_dir=value.working_dir,
        root_dir=value.root_dir,
        is_active=value.is_active,
        is_orchestrator=value.is_orchestrator,
        mention_name=value.mention_name,
        skills=[_linked_item_to_dto(item) for item in value.skills],
        pre_processing_tools=[_linked_item_to_dto(item) for item in value.pre_processing_tools],
        post_processing_tools=[_linked_item_to_dto(item) for item in value.post_processing_tools],
    )


def team_to_dto(value: Team) -> TeamDTO:
    return TeamDTO.model_validate(value)


def team_binding_to_dto(value: TeamBinding) -> TeamBindingDTO:
    return TeamBindingDTO.model_validate(value)


def team_role_to_dto(value: TeamRole) -> TeamRoleDTO:
    return TeamRoleDTO.model_validate(value)


def user_role_session_to_dto(value: UserRoleSession) -> UserRoleSessionDTO:
    return UserRoleSessionDTO.model_validate(value)


def team_role_runtime_status_to_dto(value: TeamRoleRuntimeStatus) -> TeamRoleRuntimeStatusDTO:
    return TeamRoleRuntimeStatusDTO.model_validate(value)


def role_catalog_item_to_dto(value: RoleCatalogItem) -> RoleCatalogItemDTO:
    return RoleCatalogItemDTO.model_validate(value)


def master_role_catalog_item_to_dto(value: MasterRoleCatalogItem) -> MasterRoleCatalogItemDTO:
    return MasterRoleCatalogItemDTO.model_validate(value)


def role_catalog_error_to_dto(value: RoleCatalogError) -> RoleCatalogErrorDTO:
    return RoleCatalogErrorDTO.model_validate(value)


def team_session_to_dto(value: TeamSessionView) -> TeamSessionDTO:
    return TeamSessionDTO.model_validate(value)


def team_role_patch_outcome_to_dto(value: TeamRolePatchOutcome) -> TeamRolePatchOutcomeDTO:
    return TeamRolePatchOutcomeDTO(
        team_id=value.team_id,
        role_id=value.role_id,
        team_role_id=value.team_role_id,
        enabled=value.enabled,
        is_active=value.is_active,
        mode=value.mode,
        is_orchestrator=value.is_orchestrator,
        model_override=value.model_override,
        display_name=value.display_name,
        system_prompt=value.system_prompt_override,
        extra_instructions=value.extra_instruction_override,
        system_prompt_override=value.system_prompt_override,
        extra_instruction_override=value.extra_instruction_override,
        user_prompt_suffix=value.user_prompt_suffix,
        user_reply_prefix=value.user_reply_prefix,
    )


def team_role_bind_outcome_to_dto(value: TeamRoleBindOutcome) -> TeamRolePatchOutcomeDTO:
    return TeamRolePatchOutcomeDTO(
        team_id=value.team_id,
        role_id=value.role_id,
        team_role_id=value.team_role_id,
        enabled=value.enabled,
        is_active=value.is_active,
        mode=value.mode,
        is_orchestrator=value.is_orchestrator,
        model_override=value.model_override,
        display_name=value.display_name,
        system_prompt=value.system_prompt_override,
        extra_instructions=value.extra_instruction_override,
        system_prompt_override=value.system_prompt_override,
        extra_instruction_override=value.extra_instruction_override,
        user_prompt_suffix=value.user_prompt_suffix,
        user_reply_prefix=value.user_reply_prefix,
    )


def master_role_patch_outcome_to_dto(value: MasterRolePatchOutcome) -> MasterRolePatchOutcomeDTO:
    return MasterRolePatchOutcomeDTO(
        role_id=value.role_id,
        role_name=value.role_name,
        llm_model=value.llm_model,
        system_prompt=value.system_prompt,
        extra_instructions=value.extra_instruction,
        extra_instruction=value.extra_instruction,
    )


def mutation_ack_to_dto(value: MutationAck) -> MutationAckDTO:
    return MutationAckDTO.model_validate(value)


def team_role_skill_outcome_to_dto(value: TeamRoleSkillOutcome) -> TeamRoleSkillOutcomeDTO:
    return TeamRoleSkillOutcomeDTO.model_validate(value)


def team_role_prepost_outcome_to_dto(value: TeamRolePrepostOutcome) -> TeamRolePrepostOutcomeDTO:
    return TeamRolePrepostOutcomeDTO.model_validate(value)


def team_role_working_dir_outcome_to_dto(value: TeamRoleWorkingDirOutcome) -> TeamRoleWorkingDirOutcomeDTO:
    return TeamRoleWorkingDirOutcomeDTO.model_validate(value)


def team_role_root_dir_outcome_to_dto(value: TeamRoleRootDirOutcome) -> TeamRoleRootDirOutcomeDTO:
    return TeamRoleRootDirOutcomeDTO.model_validate(value)


def qa_question_to_dto(value: QaQuestion) -> QaQuestionDTO:
    return QaQuestionDTO(
        question_id=value.question_id,
        thread_id=value.thread_id,
        team_id=value.team_id,
        created_by_user_id=value.created_by_user_id,
        team_role_id=value.target_team_role_id,
        source_question_id=value.source_question_id,
        parent_answer_id=value.parent_answer_id,
        origin_type=value.origin_type,
        status=value.status,
        text=value.text,
        error_code=value.error_code,
        error_message=value.error_message,
        created_at=value.created_at,
        updated_at=value.updated_at,
        answered_at=value.answered_at,
        answer_id=value.answer_id,
    )


def qa_answer_to_dto(value: QaAnswer) -> QaAnswerDTO:
    return QaAnswerDTO.model_validate(value)


def qa_question_status_to_dto(value: QaQuestionStatus) -> QaQuestionStatusDTO:
    return QaQuestionStatusDTO.model_validate(value)


def qa_create_question_outcome_to_dto(value: QaCreateQuestionOutcome) -> QaCreateQuestionResponseDTO:
    return QaCreateQuestionResponseDTO(
        question=qa_question_to_dto(value.question),
        idempotent_replay=bool(value.idempotent_replay),
    )


def qa_orchestrator_feed_item_to_dto(value: QaOrchestratorFeedItem) -> QaOrchestratorFeedItemDTO:
    return QaOrchestratorFeedItemDTO.model_validate(value)


def event_subscription_to_dto(value: EventSubscription) -> EventSubscriptionDTO:
    return EventSubscriptionDTO.model_validate(value)


def thread_event_to_dto(value: ThreadEvent) -> ThreadEventDTO:
    return ThreadEventDTO.model_validate(value)


def event_delivery_to_dto(value: EventDelivery) -> EventDeliveryDTO:
    return EventDeliveryDTO.model_validate(value)


def skill_to_dto(value: RegistryItem) -> SkillDTO:
    return SkillDTO(
        skill_id=value.id,
        name=value.name,
        description=value.description,
        source=value.source,
    )


def prepost_processing_tool_to_dto(value: RegistryItem) -> PrePostProcessingToolDTO:
    return PrePostProcessingToolDTO(
        tool_id=value.id,
        name=value.name,
        description=value.description,
        source=value.source,
    )


def _linked_item_to_dto(value: RoleLinkedItem) -> RoleLinkedItemDTO:
    return RoleLinkedItemDTO(id=value.id, name=value.name)


def list_request_to_params(value: ListRequestDTO) -> dict[str, Any]:
    return value.model_dump(exclude_none=True)


def get_request_to_params(value: GetRequestDTO) -> dict[str, Any]:
    return value.model_dump(exclude_none=True)


def update_request_to_patch(value: UpdateRequestDTO) -> dict[str, Any]:
    return value.model_dump(exclude_none=True)


def reset_request_to_params(value: ResetRequestDTO) -> dict[str, Any]:
    return value.model_dump()


def delete_request_to_params(value: DeleteRequestDTO) -> dict[str, Any]:
    return value.model_dump()


def operation_result_to_dto(
    value: Result[Any],
    *,
    message: str | None = None,
) -> OperationResultDTO:
    if value.is_error:
        return OperationResultDTO(ok=False, message=(value.error.message if value.error else message))
    payload = value.value
    if isinstance(payload, TeamRole):
        return OperationResultDTO(ok=True, message=message, team_role=team_role_to_dto(payload))
    if isinstance(payload, UserRoleSession):
        return OperationResultDTO(ok=True, message=message, session=user_role_session_to_dto(payload))
    if isinstance(payload, TeamRoleRuntimeStatus):
        return OperationResultDTO(ok=True, message=message, runtime_status=team_role_runtime_status_to_dto(payload))
    if isinstance(payload, str):
        return OperationResultDTO(ok=True, message=payload)
    return OperationResultDTO(ok=True, message=message)
