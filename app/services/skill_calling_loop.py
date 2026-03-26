from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from app.llm_providers import ProviderUserField
from app.llm_router import MissingUserField
from app.models import Role
from app.services.prompt_builder import build_llm_payload_json, provider_id_from_model, resolve_provider_model
from app.services.skill_response import SkillCallRequest, parse_skill_response
from app.skills.service import SkillService
from app.storage import Storage
from skills_sdk.contract import SkillContext, SkillResult

if TYPE_CHECKING:
    from app.llm_executor import LLMExecutor
    from app.session_resolver import SessionResolver


logger = logging.getLogger("skill_calling_loop")
DEFAULT_MAX_SKILL_STEPS = 8
MAX_SAME_SKILL_CALL_REPEATS = 3
DEFAULT_SKILL_TIMEOUT_SEC = 30
MAX_SKILL_TIMEOUT_SEC = 120
DEFAULT_SKILL_ERROR_TEXT = "Skill loop stopped because the assistant kept repeating the same skill call."
SKILLS_PROVIDER_ID = "skills"
SKILLS_ROOT_DIR_KEY = "root_dir"
ALLOWED_FOLLOWUP_MODES = {"full", "compact"}


@dataclass(frozen=True)
class SkillExecutionRecord:
    step_index: int
    skill_id: str
    ok: bool
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    error_text: str | None = None


@dataclass(frozen=True)
class SkillLoopResult:
    status: str
    final_answer_text: str
    session_id: str
    steps_taken: int
    raw_responses: tuple[str, ...] = field(default_factory=tuple)
    executed_skills: tuple[SkillExecutionRecord, ...] = field(default_factory=tuple)
    model_override: str | None = None


@dataclass(frozen=True)
class SkillStepSendResult:
    response_text: str
    session_id: str


class SkillCallingLoop:
    def __init__(
        self,
        *,
        storage: Storage,
        llm_executor: "LLMExecutor",
        session_resolver: "SessionResolver",
        skills_service: SkillService,
        provider_models: list[Any],
        provider_model_map: dict[str, Any],
        provider_registry: dict[str, Any],
        skills_usage_prompt: str = "",
        default_max_steps: int = DEFAULT_MAX_SKILL_STEPS,
        followup_mode: str = "full",
    ) -> None:
        self._storage = storage
        self._llm_executor = llm_executor
        self._session_resolver = session_resolver
        self._skills_service = skills_service
        self._provider_models = provider_models
        self._provider_model_map = provider_model_map
        self._provider_registry = provider_registry
        self._skills_usage_prompt = str(skills_usage_prompt or "").strip()
        self._default_max_steps = default_max_steps
        normalized_followup_mode = str(followup_mode or "full").strip().lower()
        if normalized_followup_mode not in ALLOWED_FOLLOWUP_MODES:
            normalized_followup_mode = "full"
        self._followup_mode = normalized_followup_mode

    async def run(
        self,
        *,
        team_id: int,
        user_id: int,
        role: Role,
        session_token: str,
        user_text: str,
        reply_text: str | None,
        actor_username: str | None,
        trigger_type: str,
        mentioned_roles: list[str],
        recipient: str,
        llm_answer_text: str | None = None,
        llm_answer_role_name: str | None = None,
        max_steps: int | None = None,
        send_step: Callable[[str, str, str | None], Awaitable[SkillStepSendResult]] | None = None,
        on_skill_progress: Callable[[str], None] | None = None,
    ) -> SkillLoopResult:
        chat_id = team_id
        group_role = self._storage.get_team_role(team_id, role.role_id)
        model_override = resolve_provider_model(
            self._provider_models,
            self._provider_model_map,
            self._provider_registry,
            group_role.model_override or role.llm_model,
        )
        base_prompt = group_role.system_prompt_override if group_role.system_prompt_override is not None else role.base_system_prompt
        system_prompt = f"{(base_prompt or '').strip()}\n\n{(role.extra_instruction or '').strip()}".strip()
        if self._skills_usage_prompt:
            system_prompt = f"{system_prompt}\n\n{self._skills_usage_prompt}".strip()
        system_prompt = system_prompt or None
        enabled_skills = self._load_enabled_skills(
            team_id=team_id,
            role=role,
            model_override=model_override,
        )
        skill_catalog = [entry["catalog"] for entry in enabled_skills.values()]

        session_id = await self._session_resolver.resolve(
            telegram_user_id=user_id,
            team_id=team_id,
            role=role,
            session_token=session_token,
            model_override=model_override,
        )

        step_limit = max(1, int(max_steps or self._default_max_steps))
        repeated_calls: dict[str, int] = {}
        skill_history: list[dict[str, Any]] = []
        raw_responses: list[str] = []
        executed_skills: list[SkillExecutionRecord] = []

        for step_index in range(step_limit):
            full_payload, compact_payload = build_llm_payload_json(
                user_text,
                group_role.user_prompt_suffix,
                group_role.user_reply_prefix,
                reply_text,
                username=actor_username,
                recipient=recipient,
                trigger_type=trigger_type,
                mentioned_roles=mentioned_roles,
                system_prompt=system_prompt,
                llm_answer_text=llm_answer_text,
                llm_answer_role_name=llm_answer_role_name,
                skills_prompt=self._skills_usage_prompt,
                skills_available=skill_catalog,
                skill_history=skill_history,
            )
            content = self._build_step_content(
                compact_payload=compact_payload,
                skill_history=skill_history,
                step_index=step_index,
            )
            logger.info(
                "skill loop payload team_id=%s user_id=%s role=%s step=%s followup_mode=%s payload=%s",
                team_id,
                user_id,
                role.role_name,
                step_index,
                self._followup_mode,
                json.dumps(full_payload, ensure_ascii=False),
            )
            if send_step is None:
                raw_response = await self._llm_executor.send_with_retries(
                    session_id=session_id,
                    session_token=session_token,
                    content=content,
                    role=role,
                    model_override=model_override,
                )
            else:
                step_result = await send_step(session_id, content, model_override)
                raw_response = step_result.response_text
                session_id = step_result.session_id
            raw_responses.append(raw_response)
            parsed = parse_skill_response(raw_response)
            if parsed is None:
                fallback_text = raw_response.strip() or "Assistant response could not be parsed."
                return SkillLoopResult(
                    status="parse_fallback",
                    final_answer_text=fallback_text,
                    session_id=session_id,
                    steps_taken=step_index + 1,
                    raw_responses=tuple(raw_responses),
                    executed_skills=tuple(executed_skills),
                    model_override=model_override,
                )

            if parsed.decision_type == "final_answer":
                return SkillLoopResult(
                    status="final_answer",
                    final_answer_text=parsed.answer_text or "",
                    session_id=session_id,
                    steps_taken=step_index + 1,
                    raw_responses=tuple(raw_responses),
                    executed_skills=tuple(executed_skills),
                    model_override=model_override,
                )

            assert parsed.skill_call is not None
            logger.info(
                "skill loop decision chat_id=%s user_id=%s role=%s step=%s skill_id=%s",
                chat_id,
                user_id,
                role.role_name,
                step_index,
                parsed.skill_call.skill_id,
            )
            call_key = self._call_key(parsed.skill_call)
            repeated_calls[call_key] = repeated_calls.get(call_key, 0) + 1
            if repeated_calls[call_key] > MAX_SAME_SKILL_CALL_REPEATS:
                return SkillLoopResult(
                    status="guard_repeated_call",
                    final_answer_text=DEFAULT_SKILL_ERROR_TEXT,
                    session_id=session_id,
                    steps_taken=step_index + 1,
                    raw_responses=tuple(raw_responses),
                    executed_skills=tuple(executed_skills),
                    model_override=model_override,
                )

            execution = await self._execute_skill_call(
                chat_id=chat_id,
                user_id=user_id,
                role=role,
                chain_id=session_id,
                step_index=step_index,
                enabled_skills=enabled_skills,
                request=parsed.skill_call,
            )
            executed_skills.append(execution)
            skill_history.append(
                {
                    "skill_id": execution.skill_id,
                    "ok": execution.ok,
                    "status": execution.status,
                    "output": execution.output,
                    "error": execution.error_text,
                }
            )
            if on_skill_progress is not None:
                summary = execution.error_text if execution.error_text else json.dumps(execution.output, ensure_ascii=False)
                on_skill_progress(f"{execution.skill_id}: {summary}")

        return SkillLoopResult(
            status="max_steps",
            final_answer_text="Skill loop stopped after reaching the step limit.",
            session_id=session_id,
            steps_taken=step_limit,
            raw_responses=tuple(raw_responses),
            executed_skills=tuple(executed_skills),
            model_override=model_override,
        )

    def _build_step_content(
        self,
        *,
        compact_payload: dict[str, Any],
        skill_history: list[dict[str, Any]],
        step_index: int,
    ) -> str:
        if self._followup_mode == "compact" and step_index > 0 and skill_history:
            return "SKILL_RESULT:\n" + json.dumps(skill_history[-1], ensure_ascii=False)
        return "INPUT_JSON:\n" + json.dumps(compact_payload, ensure_ascii=False)

    def _load_enabled_skills(
        self,
        *,
        team_id: int,
        role: Role,
        model_override: str | None,
    ) -> dict[str, dict[str, Any]]:
        team_role_id = self._storage.resolve_team_role_id(team_id, role.role_id)
        if team_role_id is None:
            return {}
        enabled = self._storage.list_role_skills_for_team_role(team_role_id, enabled_only=True)
        result: dict[str, dict[str, Any]] = {}
        for role_skill in enabled:
            record = self._skills_service.get(role_skill.skill_id)
            if record is None:
                logger.info(
                    "skill loop skip undiscovered skill group_id=%s role=%s skill_id=%s",
                    team_id,
                    role.role_name,
                    role_skill.skill_id,
                )
                continue
            config = self._resolve_skill_config(
                role=role,
                model_override=model_override,
                skill_id=role_skill.skill_id,
                config=self._parse_config(role_skill.config_json),
            )
            result[role_skill.skill_id] = {
                "record": record,
                "config": config,
                "catalog": {
                    "skill_id": record.spec.skill_id,
                    "name": record.spec.name,
                    "description": record.spec.description,
                    "input_schema": record.spec.input_schema,
                    "mode": record.spec.mode,
                },
            }
        return result

    def _resolve_skill_config(
        self,
        *,
        role: Role,
        model_override: str | None,
        skill_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = dict(config)
        if not self._is_filesystem_skill(skill_id):
            return resolved
        root_dir = str(resolved.get("root_dir", "") or "").strip()
        if root_dir:
            return resolved

        provider_root = self._resolve_provider_working_dir(role_id=role.role_id, model_override=model_override)
        if provider_root:
            resolved["root_dir"] = provider_root
            return resolved

        shared_root = str(
            self._storage.get_provider_user_value(SKILLS_PROVIDER_ID, SKILLS_ROOT_DIR_KEY, role.role_id) or ""
        ).strip()
        if shared_root:
            resolved["root_dir"] = shared_root
            return resolved

        raise MissingUserField(
            SKILLS_PROVIDER_ID,
            ProviderUserField(
                key=SKILLS_ROOT_DIR_KEY,
                prompt=(
                    f"Введите корневую директорию для файловых skills роли @{role.public_name()}. "
                    "Пример: /home/user/project"
                ),
                scope="role",
            ),
            role.role_id,
        )

    def _resolve_provider_working_dir(self, *, role_id: int, model_override: str | None) -> str | None:
        if not model_override:
            return None
        default_provider_id = next(iter(self._provider_registry.keys()), "")
        provider_id = provider_id_from_model(model_override, default_provider_id, self._provider_registry)
        provider = self._provider_registry.get(provider_id)
        if provider is None:
            return None
        field = provider.user_fields.get("working_dir")
        if field is None or field.scope != "role":
            return None
        value = self._storage.get_provider_user_value(provider_id, "working_dir", role_id)
        return str(value).strip() if value else None

    @staticmethod
    def _is_filesystem_skill(skill_id: str) -> bool:
        return skill_id.startswith("fs.")

    async def _execute_skill_call(
        self,
        *,
        chat_id: int,
        user_id: int,
        role: Role,
        chain_id: str,
        step_index: int,
        enabled_skills: dict[str, dict[str, Any]],
        request: SkillCallRequest,
    ) -> SkillExecutionRecord:
        enabled_entry = enabled_skills.get(request.skill_id)
        if enabled_entry is None:
            logger.info(
                "skill loop rejected disabled skill chat_id=%s user_id=%s role=%s step=%s skill_id=%s",
                chat_id,
                user_id,
                role.role_name,
                step_index,
                request.skill_id,
            )
            return self._log_error_result(
                chain_id=chain_id,
                step_index=step_index,
                user_id=user_id,
                chat_id=chat_id,
                role=role,
                skill_id=request.skill_id,
                arguments=request.arguments,
                config=None,
                status="not_enabled",
                error_text=f"Skill '{request.skill_id}' is not enabled for this role.",
            )

        record = enabled_entry["record"]
        config = enabled_entry["config"]
        config_errors = record.instance.validate_config(config)
        if config_errors:
            logger.info(
                "skill loop invalid config chat_id=%s user_id=%s role=%s step=%s skill_id=%s errors=%s",
                chat_id,
                user_id,
                role.role_name,
                step_index,
                request.skill_id,
                config_errors,
            )
            return self._log_error_result(
                chain_id=chain_id,
                step_index=step_index,
                user_id=user_id,
                chat_id=chat_id,
                role=role,
                skill_id=request.skill_id,
                arguments=request.arguments,
                config=config,
                status="invalid_config",
                error_text="; ".join(str(item) for item in config_errors),
            )

        timeout_sec = min(MAX_SKILL_TIMEOUT_SEC, max(1, int(record.spec.timeout_sec or DEFAULT_SKILL_TIMEOUT_SEC)))
        skill_ctx = SkillContext(
            chain_id=chain_id,
            chat_id=chat_id,
            user_id=user_id,
            role_id=role.role_id,
            role_name=role.role_name,
        )
        try:
            logger.info(
                "skill loop execute chat_id=%s user_id=%s role=%s step=%s skill_id=%s",
                chat_id,
                user_id,
                role.role_name,
                step_index,
                request.skill_id,
            )
            result = await asyncio.wait_for(
                asyncio.to_thread(record.instance.run, skill_ctx, request.arguments, config),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            return self._log_error_result(
                chain_id=chain_id,
                step_index=step_index,
                user_id=user_id,
                chat_id=chat_id,
                role=role,
                skill_id=request.skill_id,
                arguments=request.arguments,
                config=config,
                status="timeout",
                error_text=f"Skill '{request.skill_id}' timed out after {timeout_sec} seconds.",
            )
        except Exception as exc:
            logger.exception(
                "skill execution failed chat_id=%s user_id=%s role=%s skill_id=%s step=%s",
                chat_id,
                user_id,
                role.role_name,
                request.skill_id,
                step_index,
            )
            return self._log_error_result(
                chain_id=chain_id,
                step_index=step_index,
                user_id=user_id,
                chat_id=chat_id,
                role=role,
                skill_id=request.skill_id,
                arguments=request.arguments,
                config=config,
                status="exception",
                error_text=str(exc),
            )

        if not isinstance(result, SkillResult):
            return self._log_error_result(
                chain_id=chain_id,
                step_index=step_index,
                user_id=user_id,
                chat_id=chat_id,
                role=role,
                skill_id=request.skill_id,
                arguments=request.arguments,
                config=config,
                status="invalid_result",
                error_text="Skill did not return SkillResult.",
            )

        stored = self._storage.log_skill_run(
            chain_id=chain_id,
            step_index=step_index,
            telegram_user_id=user_id,
            chat_id=chat_id,
            role_id=role.role_id,
            skill_id=request.skill_id,
            arguments=request.arguments,
            config=config,
            status="ok" if result.ok else "error",
            ok=result.ok,
            error_text=result.error,
            output=result.output,
        )
        logger.info(
            "skill loop result chat_id=%s user_id=%s role=%s step=%s skill_id=%s status=%s ok=%s",
            chat_id,
            user_id,
            role.role_name,
            step_index,
            request.skill_id,
            stored.status,
            result.ok,
        )
        return SkillExecutionRecord(
            step_index=step_index,
            skill_id=request.skill_id,
            ok=result.ok,
            status=stored.status,
            output=result.output if isinstance(result.output, dict) else {},
            error_text=result.error,
        )

    def _log_error_result(
        self,
        *,
        chain_id: str,
        step_index: int,
        user_id: int,
        chat_id: int,
        role: Role,
        skill_id: str,
        arguments: dict[str, Any],
        config: dict[str, Any] | None,
        status: str,
        error_text: str,
    ) -> SkillExecutionRecord:
        self._storage.log_skill_run(
            chain_id=chain_id,
            step_index=step_index,
            telegram_user_id=user_id,
            chat_id=chat_id,
            role_id=role.role_id,
            skill_id=skill_id,
            arguments=arguments,
            config=config,
            status=status,
            ok=False,
            error_text=error_text,
            output={},
        )
        return SkillExecutionRecord(
            step_index=step_index,
            skill_id=skill_id,
            ok=False,
            status=status,
            output={},
            error_text=error_text,
        )

    @staticmethod
    def _parse_config(config_json: str | None) -> dict[str, Any]:
        if not config_json:
            return {}
        try:
            value = json.loads(config_json)
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _call_key(request: SkillCallRequest) -> str:
        return json.dumps(
            {
                "skill_id": request.skill_id,
                "arguments": request.arguments,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
