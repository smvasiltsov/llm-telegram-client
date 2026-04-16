from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ApiCursorResponse, ApiSchema


class RoleDTO(ApiSchema):
    role_id: int
    team_role_id: int | None
    role_name: str
    description: str
    system_prompt: str
    extra_instructions: str
    llm_model: str | None
    working_dir: str | None = None
    root_dir: str | None = None
    is_active: bool
    is_orchestrator: bool = False
    mention_name: str | None = None
    skills: list["RoleLinkedItemDTO"] = Field(default_factory=list)
    pre_processing_tools: list["RoleLinkedItemDTO"] = Field(default_factory=list)
    post_processing_tools: list["RoleLinkedItemDTO"] = Field(default_factory=list)


class RoleLinkedItemDTO(ApiSchema):
    id: str
    name: str


class TeamDTO(ApiSchema):
    team_id: int
    public_id: str
    name: str | None
    is_active: bool
    ext_json: str | None
    created_at: str
    updated_at: str


class TeamBindingDTO(ApiSchema):
    team_id: int
    interface_type: str
    external_id: str
    external_title: str | None
    is_active: bool
    created_at: str
    updated_at: str


class TeamRoleDTO(ApiSchema):
    team_id: int
    role_id: int
    team_role_id: int | None
    system_prompt_override: str | None
    extra_instruction_override: str | None
    display_name: str | None
    model_override: str | None
    user_prompt_suffix: str | None
    user_reply_prefix: str | None
    enabled: bool
    mode: Literal["normal", "orchestrator"]
    is_active: bool


class UserRoleSessionDTO(ApiSchema):
    telegram_user_id: int
    group_id: int
    role_id: int
    session_id: str
    created_at: str
    last_used_at: str
    team_id: int | None = None
    team_role_id: int | None = None


class TeamRoleRuntimeStatusDTO(ApiSchema):
    team_role_id: int
    status: Literal["free", "busy"]
    status_version: int
    busy_request_id: str | None
    busy_owner_user_id: int | None
    busy_origin: str | None
    preview_text: str | None
    preview_source: str | None
    busy_since: str | None
    lease_expires_at: str | None
    last_heartbeat_at: str | None
    free_release_requested_at: str | None
    free_release_delay_until: str | None
    free_release_reason_pending: str | None
    last_release_reason: str | None
    updated_at: str


class TeamRoleRuntimeCurrentQuestionDTO(ApiSchema):
    question_id: str | None = None
    thread_id: str | None = None
    text: str
    status: str | None = None
    updated_at: str | None = None
    source: Literal["question", "preview"] = "question"


class TeamRoleRuntimeOverviewDTO(ApiSchema):
    team_id: int
    role_id: int
    team_role_id: int
    role_name: str
    display_name: str
    status: Literal["free", "busy"]
    busy_request_id: str | None = None
    busy_since: str | None = None
    lease_expires_at: str | None = None
    current_question: TeamRoleRuntimeCurrentQuestionDTO | None = None


class RoleCatalogItemDTO(ApiSchema):
    role_name: str
    is_active: bool
    llm_model: str | None
    is_orchestrator: bool
    has_errors: bool
    source: str


class MasterRoleCatalogItemDTO(ApiSchema):
    role_id: int
    role_name: str
    llm_model: str | None
    system_prompt: str
    extra_instruction: str
    has_errors: bool
    source: str


class RoleCatalogErrorDTO(ApiSchema):
    role_name: str
    file: str
    code: str
    message: str
    details: dict[str, object]


class TeamSessionDTO(ApiSchema):
    telegram_user_id: int
    team_role_id: int | None
    role_name: str
    session_id: str
    updated_at: str


class SkillDTO(ApiSchema):
    skill_id: str
    name: str
    description: str
    source: str | None


class PrePostProcessingToolDTO(ApiSchema):
    tool_id: str
    name: str
    description: str
    source: str | None


class TeamRolePatchRequestDTO(ApiSchema):
    enabled: bool | None = None
    is_active: bool | None = None
    is_orchestrator: bool | None = None
    model_override: str | None = None
    display_name: str | None = None
    system_prompt: str | None = None
    extra_instructions: str | None = None
    system_prompt_override: str | None = None
    extra_instruction_override: str | None = None
    user_prompt_suffix: str | None = None
    user_reply_prefix: str | None = None


class MasterRolePatchRequestDTO(ApiSchema):
    role_name: str | None = None
    llm_model: str | None = None
    system_prompt: str | None = None
    extra_instructions: str | None = None
    extra_instruction: str | None = None


class MasterRoleCreateRequestDTO(ApiSchema):
    role_name: str
    system_prompt: str
    llm_model: str
    description: str | None = None
    extra_instructions: str | None = None


class MasterRoleCreateOutcomeDTO(ApiSchema):
    role_id: int
    role_name: str
    llm_model: str | None
    system_prompt: str
    extra_instructions: str
    description: str
    is_active: bool


class MasterRolePatchOutcomeDTO(ApiSchema):
    role_id: int
    role_name: str
    llm_model: str | None
    system_prompt: str
    extra_instructions: str = ""
    extra_instruction: str


class TeamRolePatchOutcomeDTO(ApiSchema):
    team_id: int
    role_id: int
    team_role_id: int | None
    enabled: bool
    is_active: bool
    mode: str
    is_orchestrator: bool
    model_override: str | None
    display_name: str | None
    system_prompt: str | None = None
    extra_instructions: str | None = None
    system_prompt_override: str | None = None
    extra_instruction_override: str | None = None
    user_prompt_suffix: str | None
    user_reply_prefix: str | None


class TeamRoleUserMutationRequestDTO(ApiSchema):
    telegram_user_id: int


class TeamCreateRequestDTO(ApiSchema):
    name: str


class TeamCreateOutcomeDTO(ApiSchema):
    team_id: int
    public_id: str
    name: str | None
    is_active: bool
    ext_json: str | None
    created_at: str
    updated_at: str


class TeamRenameRequestDTO(ApiSchema):
    name: str


class TeamRenameOutcomeDTO(ApiSchema):
    team_id: int
    public_id: str
    name: str | None
    is_active: bool
    ext_json: str | None
    created_at: str
    updated_at: str


class MutationAckDTO(ApiSchema):
    ok: bool
    team_id: int
    role_id: int
    telegram_user_id: int
    team_role_id: int | None = None
    operation: str


class TeamRoleSkillPutRequestDTO(ApiSchema):
    enabled: bool
    config: dict[str, object] | None = None


class TeamRoleSkillReplaceItemDTO(ApiSchema):
    skill_id: str
    enabled: bool = True
    config: dict[str, object] | None = None


class TeamRoleSkillReplaceRequestDTO(ApiSchema):
    items: list[TeamRoleSkillReplaceItemDTO]


class TeamRolePrepostPutRequestDTO(ApiSchema):
    enabled: bool
    config: dict[str, object] | None = None


class TeamRolePrepostReplaceItemDTO(ApiSchema):
    prepost_id: str
    enabled: bool = True
    config: dict[str, object] | None = None


class TeamRolePrepostReplaceRequestDTO(ApiSchema):
    items: list[TeamRolePrepostReplaceItemDTO]


class TeamRoleWorkingDirPutRequestDTO(ApiSchema):
    working_dir: str


class TeamRoleRootDirPutRequestDTO(ApiSchema):
    root_dir: str


class TeamRoleSkillOutcomeDTO(ApiSchema):
    team_role_id: int
    skill_id: str
    enabled: bool
    config: dict[str, object] | None = None


class TeamRolePrepostOutcomeDTO(ApiSchema):
    team_role_id: int
    prepost_id: str
    enabled: bool
    config: dict[str, object] | None = None


class TeamRoleSkillsReplaceOutcomeDTO(ApiSchema):
    items: list[TeamRoleSkillOutcomeDTO]


class TeamRolePrepostReplaceOutcomeDTO(ApiSchema):
    items: list[TeamRolePrepostOutcomeDTO]


class TeamRoleWorkingDirOutcomeDTO(ApiSchema):
    team_role_id: int
    working_dir: str


class TeamRoleRootDirOutcomeDTO(ApiSchema):
    team_role_id: int
    root_dir: str


class RecoveryQueuesResetScopeDTO(ApiSchema):
    mode: Literal["global", "team"] = "global"
    team_id: int | None = None


class RecoveryQueuesResetSnapshotDTO(ApiSchema):
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


class RecoveryQueuesResetRequestDTO(ApiSchema):
    scope: RecoveryQueuesResetScopeDTO = Field(default_factory=RecoveryQueuesResetScopeDTO)
    dry_run: bool = True


class RecoveryQueuesResetResponseDTO(ApiSchema):
    scope: RecoveryQueuesResetScopeDTO
    dry_run: bool
    applied: bool
    before: RecoveryQueuesResetSnapshotDTO
    after: RecoveryQueuesResetSnapshotDTO
    delta: RecoveryQueuesResetSnapshotDTO
    summary: str | None = None


class QaCreateQuestionRequestDTO(ApiSchema):
    team_id: int
    text: str
    team_role_id: int | None = None
    origin_interface: str | None = None
    origin_type: Literal["user", "role_dispatch", "orchestrator"] = "user"
    source_question_id: str | None = None
    parent_answer_id: str | None = None
    thread_id: str | None = None
    question_id: str | None = None


class QaQuestionDTO(ApiSchema):
    question_id: str
    thread_id: str
    team_id: int
    created_by_user_id: int
    team_role_id: int | None
    source_question_id: str | None
    parent_answer_id: str | None
    origin_type: str
    status: str
    text: str
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str
    answered_at: str | None
    answer_id: str | None = None


class QaCreateQuestionResponseDTO(ApiSchema):
    question: QaQuestionDTO
    idempotent_replay: bool


class QaQuestionStatusDTO(ApiSchema):
    question_id: str
    status: str
    error_code: str | None
    error_message: str | None
    updated_at: str
    answered_at: str | None
    answer_id: str | None = None


class QaAnswerDTO(ApiSchema):
    answer_id: str
    question_id: str
    thread_id: str
    team_id: int
    team_role_id: int | None
    role_name: str | None
    text: str
    created_at: str


class QaOrchestratorFeedItemDTO(ApiSchema):
    feed_id: int
    team_id: int
    thread_id: str
    question_id: str
    answer_id: str
    created_at: str


class QaThreadResponseDTO(ApiSchema):
    questions: ApiCursorResponse
    answers: ApiCursorResponse


class EventSubscriptionDTO(ApiSchema):
    subscription_id: int
    scope: str
    scope_id: str
    interface_type: str
    target_id: str
    mode: str
    is_active: bool
    options_json: str | None
    created_at: str
    updated_at: str


class EventSubscriptionUpsertRequestDTO(ApiSchema):
    scope: str
    scope_id: str
    interface_type: str
    target_id: str
    mode: str = "mirror"
    is_active: bool = True
    options_json: str | None = None


class ThreadEventDTO(ApiSchema):
    event_id: str
    team_id: int
    thread_id: str
    seq: int
    event_type: str
    author_type: str
    author_name: str | None = None
    direction: str
    origin_interface: str | None
    source_ref_type: str | None
    source_ref_id: str | None
    question_id: str | None
    answer_id: str | None
    source_question_id: str | None
    parent_answer_id: str | None
    payload_json: str | None
    idempotency_key: str | None
    created_at: str


class EventDeliveryDTO(ApiSchema):
    delivery_id: int
    event_id: str
    interface_type: str
    target_id: str
    status: str
    attempt_count: int
    max_attempts: int
    next_retry_at: str | None
    last_attempt_at: str | None
    delivered_at: str | None
    last_error_code: str | None
    last_error_message: str | None
    lease_owner: str | None
    lease_expires_at: str | None
    idempotency_key: str | None
    created_at: str
    updated_at: str
    lag_ms: float | None = None


class EventDeliveryActionRequestDTO(ApiSchema):
    reset_attempt_count: bool = False


class ThreadEventTraceDTO(ApiSchema):
    event: ThreadEventDTO
    deliveries: list[EventDeliveryDTO] = Field(default_factory=list)


class EventDeliveriesSummaryDTO(ApiSchema):
    total: int
    pending: int
    in_progress: int
    retry_scheduled: int
    delivered: int
    skipped: int
    failed_dlq: int
    avg_lag_ms: float | None = None
    max_lag_ms: float | None = None
