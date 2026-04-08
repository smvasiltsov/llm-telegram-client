from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ApiCursorResponse, ApiSchema


class RoleDTO(ApiSchema):
    role_id: int
    team_role_id: int | None
    role_name: str
    description: str
    base_system_prompt: str
    extra_instruction: str
    llm_model: str | None
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
    is_orchestrator: bool | None = None
    model_override: str | None = None
    display_name: str | None = None
    system_prompt_override: str | None = None
    extra_instruction_override: str | None = None
    user_prompt_suffix: str | None = None
    user_reply_prefix: str | None = None


class MasterRolePatchRequestDTO(ApiSchema):
    role_name: str | None = None
    llm_model: str | None = None
    system_prompt: str | None = None
    extra_instruction: str | None = None


class MasterRolePatchOutcomeDTO(ApiSchema):
    role_id: int
    role_name: str
    llm_model: str | None
    system_prompt: str
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
    system_prompt_override: str | None
    extra_instruction_override: str | None
    user_prompt_suffix: str | None
    user_reply_prefix: str | None


class TeamRoleUserMutationRequestDTO(ApiSchema):
    telegram_user_id: int


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


class TeamRolePrepostPutRequestDTO(ApiSchema):
    enabled: bool
    config: dict[str, object] | None = None


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


class QaCreateQuestionRequestDTO(ApiSchema):
    team_id: int
    text: str
    team_role_id: int | None = None
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
