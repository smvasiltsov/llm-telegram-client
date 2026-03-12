from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, replace
from typing import Awaitable, Callable, Literal
from uuid import uuid4

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.handlers.messages_common import (
    SessionRecoveryResult,
    _handle_missing_user_field,
    _is_unauthorized,
    _recover_stale_session_and_resend,
    _request_token_for_user,
    _runtime,
)
from app.llm_executor import LLMExecutor
from app.llm_router import MissingUserField
from app.models import GroupRole, Role
from prepost_processing_sdk.contract import PrePostProcessingContext, PrePostProcessingResult
from app.services.orchestrator_response import parse_orchestrator_response
from app.services.formatting import format_with_header, format_with_header_raw, render_llm_text, send_formatted_with_fallback
from app.services.plugin_pipeline import build_plugin_reply_markup
from app.services.prompt_builder import build_llm_payload_json, resolve_provider_model, role_requires_auth
from app.services.skill_calling_loop import SkillCallingLoop, SkillStepSendResult
from app.session_resolver import SessionResolver
from app.storage import Storage
from app.utils import extract_role_mentions, split_message

ChainOrigin = Literal["group", "pending"]
DelegationKey = tuple[int, int, str]
logger = logging.getLogger("bot")
DEFAULT_ORCHESTRATOR_MAX_CHAIN_AUTO_STEPS = 30
MAX_SAME_DELEGATION_REPEATS = 3
DEFAULT_PREPOST_PROCESSING_TIMEOUT_SEC = 30
MAX_PREPOST_PROCESSING_TIMEOUT_SEC = 120
MAX_PREPOST_PROCESSING_OUTPUT_CHARS = 12000
ALLOWED_PREPOST_PROCESSING_PERMISSIONS = frozenset(
    {
        "read_context",
        "transform_prompt",
        "transform_response",
    }
)


def normalize_delegation_text(text: str) -> str:
    return " ".join(text.lower().split())


def role_public_name(role: Role) -> str:
    return role.public_name()


@dataclass(frozen=True)
class ChainContext:
    chain_id: str
    hop: int
    max_hops: int
    reply_to_message_id: int
    origin: ChainOrigin
    visited_delegations: tuple[DelegationKey, ...] = field(default_factory=tuple)

    @classmethod
    def create(
        cls,
        *,
        origin: ChainOrigin,
        reply_to_message_id: int,
        max_hops: int = DEFAULT_ORCHESTRATOR_MAX_CHAIN_AUTO_STEPS,
    ) -> "ChainContext":
        return cls(
            chain_id=uuid4().hex[:8],
            hop=0,
            max_hops=max_hops,
            reply_to_message_id=reply_to_message_id,
            origin=origin,
            visited_delegations=(),
        )

    def can_continue(self) -> bool:
        return self.hop < self.max_hops

    def delegation_key(self, source_role_id: int, target_role_id: int, text: str) -> DelegationKey:
        return (source_role_id, target_role_id, normalize_delegation_text(text))

    def same_delegation_count(self, key: DelegationKey) -> int:
        return sum(1 for item in self.visited_delegations if item == key)

    def with_delegation(self, key: DelegationKey) -> "ChainContext":
        return replace(self, visited_delegations=self.visited_delegations + (key,))

    def next_hop(self) -> "ChainContext":
        return replace(self, hop=self.hop + 1)


@dataclass(frozen=True)
class RoleRequestResult:
    response_text: str
    group_role: GroupRole
    model_override: str | None
    recovery: SessionRecoveryResult | None


@dataclass(frozen=True)
class ChainRunResult:
    completed_roles: int
    had_error: bool
    stopped: bool


def resolve_role_model_override(
    *,
    role: Role,
    group_role: GroupRole,
    provider_models: list,
    provider_model_map: dict,
    provider_registry: dict,
) -> str | None:
    if provider_models:
        return resolve_provider_model(
            provider_models,
            provider_model_map,
            provider_registry,
            group_role.model_override or role.llm_model,
        )
    logger.warning("Provider model list is empty for role=%s", role.role_name)
    return group_role.model_override or role.llm_model


def roles_require_auth(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    roles: list[Role],
) -> bool:
    runtime = _runtime(context)
    storage: Storage = runtime.storage
    provider_registry = runtime.provider_registry
    default_provider_id = runtime.default_provider_id
    provider_models = runtime.provider_models
    provider_model_map = runtime.provider_model_map
    for role in roles:
        group_role = storage.get_group_role(chat_id, role.role_id)
        model_override = resolve_role_model_override(
            role=role,
            group_role=group_role,
            provider_models=provider_models,
            provider_model_map=provider_model_map,
            provider_registry=provider_registry,
        )
        if role_requires_auth(provider_registry, model_override, default_provider_id):
            return True
    return False


async def _run_role_prepost_processing_phase(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    role: Role,
    phase: str,
    payload: dict[str, object],
    chain_id: str,
) -> dict[str, object]:
    runtime = _runtime(context)
    storage: Storage = runtime.storage
    registry = runtime.prepost_processing_registry
    role_prepost_processing = storage.list_role_prepost_processing(chat_id, role.role_id, enabled_only=True)
    if not role_prepost_processing:
        return payload

    current = dict(payload)
    for role_prepost_processing in role_prepost_processing:
        record = registry.get(role_prepost_processing.prepost_processing_id)
        if record is None:
            logger.info(
                "pre/post processing skip: not discovered group_id=%s role=%s prepost_processing_id=%s phase=%s",
                chat_id,
                role.role_name,
                role_prepost_processing.prepost_processing_id,
                phase,
            )
            continue
        manifest_permissions = record.manifest.get("permissions")
        if isinstance(manifest_permissions, list):
            declared_permissions = tuple(str(item).strip() for item in manifest_permissions if str(item).strip())
        else:
            declared_permissions = tuple(record.spec.permissions)
        denied_permissions = [perm for perm in declared_permissions if perm not in ALLOWED_PREPOST_PROCESSING_PERMISSIONS]
        if denied_permissions:
            logger.info(
                "pre/post processing skip: unsupported permissions group_id=%s role=%s prepost_processing_id=%s phase=%s denied=%s",
                chat_id,
                role.role_name,
                role_prepost_processing.prepost_processing_id,
                phase,
                denied_permissions,
            )
            continue

        config: dict[str, object] = {}
        if role_prepost_processing.config_json:
            try:
                loaded = json.loads(role_prepost_processing.config_json)
                if isinstance(loaded, dict):
                    config = loaded
            except Exception:
                logger.exception(
                    "pre/post processing config parse failed group_id=%s role=%s prepost_processing_id=%s",
                    chat_id,
                    role.role_name,
                    role_prepost_processing.prepost_processing_id,
                )
                continue

        errors = record.instance.validate_config(config)
        if errors:
            logger.info(
                "pre/post processing skip: invalid config group_id=%s role=%s prepost_processing_id=%s errors=%s",
                chat_id,
                role.role_name,
                role_prepost_processing.prepost_processing_id,
                errors,
            )
            continue

        processing_ctx = PrePostProcessingContext(
            chain_id=chain_id,
            chat_id=chat_id,
            user_id=user_id,
            role_id=role.role_id,
            role_name=role.role_name,
        )
        processing_input = {
            "phase": phase,
            "config": config,
            "data": dict(current),
        }
        timeout_sec = record.manifest.get("timeout_sec", record.spec.timeout_sec)
        try:
            timeout_sec = int(timeout_sec)
        except Exception:
            timeout_sec = DEFAULT_PREPOST_PROCESSING_TIMEOUT_SEC
        timeout_sec = min(MAX_PREPOST_PROCESSING_TIMEOUT_SEC, max(1, timeout_sec))
        try:
            result: PrePostProcessingResult = await asyncio.wait_for(
                asyncio.to_thread(record.instance.run, processing_ctx, processing_input),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            logger.info(
                "pre/post processing timeout group_id=%s role=%s prepost_processing_id=%s phase=%s timeout_sec=%s",
                chat_id,
                role.role_name,
                role_prepost_processing.prepost_processing_id,
                phase,
                timeout_sec,
            )
            continue
        except Exception:
            logger.exception(
                "pre/post processing failed group_id=%s role=%s prepost_processing_id=%s phase=%s",
                chat_id,
                role.role_name,
                role_prepost_processing.prepost_processing_id,
                phase,
            )
            continue

        if result.status != "ok":
            logger.info(
                "pre/post processing skipped status group_id=%s role=%s prepost_processing_id=%s phase=%s status=%s",
                chat_id,
                role.role_name,
                role_prepost_processing.prepost_processing_id,
                phase,
                result.status,
            )
            continue

        output = result.output if isinstance(result.output, dict) else {}
        output_chars = len(json.dumps(output, ensure_ascii=False, default=str))
        if output_chars > MAX_PREPOST_PROCESSING_OUTPUT_CHARS:
            logger.info(
                "pre/post processing skip: output too large group_id=%s role=%s prepost_processing_id=%s phase=%s chars=%s",
                chat_id,
                role.role_name,
                role_prepost_processing.prepost_processing_id,
                phase,
                output_chars,
            )
            continue
        if phase == "pre":
            if isinstance(output.get("user_text"), str):
                current["user_text"] = output["user_text"]
            if "reply_text" in output and (isinstance(output["reply_text"], str) or output["reply_text"] is None):
                current["reply_text"] = output["reply_text"]
        elif phase == "post":
            if isinstance(output.get("response_text"), str):
                current["response_text"] = output["response_text"]

        logger.info(
            "pre/post processing ok group_id=%s role=%s prepost_processing_id=%s phase=%s",
            chat_id,
            role.role_name,
            role_prepost_processing.prepost_processing_id,
            phase,
        )
    return current


async def execute_role_request(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
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
) -> RoleRequestResult:
    runtime = _runtime(context)
    storage: Storage = runtime.storage
    provider_registry = runtime.provider_registry
    provider_models = runtime.provider_models
    provider_model_map = runtime.provider_model_map
    llm_executor: LLMExecutor = runtime.llm_executor
    resolver: SessionResolver = runtime.session_resolver

    group_role = storage.get_group_role(chat_id, role.role_id)
    model_override = resolve_role_model_override(
        role=role,
        group_role=group_role,
        provider_models=provider_models,
        provider_model_map=provider_model_map,
        provider_registry=provider_registry,
    )
    logger.info(
        "execute role request role=%s mode=%s model_override=%s",
        role.role_name,
        group_role.mode,
        model_override,
    )

    base_prompt = group_role.system_prompt_override if group_role.system_prompt_override is not None else role.base_system_prompt
    system_prompt = f"{(base_prompt or '').strip()}\n\n{(role.extra_instruction or '').strip()}".strip() or None
    skill_chain_id = uuid4().hex[:8]
    pre_data = await _run_role_prepost_processing_phase(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        role=role,
        phase="pre",
        payload={
            "user_text": user_text,
            "reply_text": reply_text,
        },
        chain_id=skill_chain_id,
    )
    effective_user_text = str(pre_data.get("user_text", user_text))
    effective_reply_text = pre_data.get("reply_text", reply_text)
    if not (isinstance(effective_reply_text, str) or effective_reply_text is None):
        effective_reply_text = reply_text

    if storage.list_role_skills(chat_id, role.role_id, enabled_only=True):
        logger.info(
            "execute role request via skill loop role=%s mode=%s model_override=%s",
            role.role_name,
            group_role.mode,
            model_override,
        )
        recovery: SessionRecoveryResult | None = None
        skill_loop = SkillCallingLoop(
            storage=storage,
            llm_executor=llm_executor,
            session_resolver=resolver,
            skills_service=runtime.skills_service,
            provider_models=provider_models,
            provider_model_map=provider_model_map,
            provider_registry=provider_registry,
            skills_usage_prompt=str(getattr(runtime, "skills_usage_prompt", "") or ""),
            default_max_steps=max(1, int(getattr(runtime, "skills_max_steps_per_request", 8) or 8)),
            followup_mode=str(getattr(runtime, "skills_followup_mode", "full") or "full"),
        )

        async def _send_skill_step(current_session_id: str, content: str, current_model_override: str | None) -> SkillStepSendResult:
            nonlocal recovery
            try:
                response_text = await llm_executor.send_with_retries(
                    session_id=current_session_id,
                    session_token=session_token,
                    content=content,
                    role=role,
                    model_override=current_model_override,
                )
                return SkillStepSendResult(response_text=response_text, session_id=current_session_id)
            except Exception as exc:
                recovered = await _recover_stale_session_and_resend(
                    exc=exc,
                    user_id=user_id,
                    chat_id=chat_id,
                    role=role,
                    session_id=current_session_id,
                    session_token=session_token,
                    model_override=current_model_override,
                    content=content,
                    context=context,
                )
                if recovered is None:
                    raise
                recovery = recovered
                return SkillStepSendResult(
                    response_text=recovered.response_text,
                    session_id=recovered.new_session_id,
                )

        loop_result = await skill_loop.run(
            chat_id=chat_id,
            user_id=user_id,
            role=role,
            session_token=session_token,
            user_text=effective_user_text,
            reply_text=effective_reply_text,
            actor_username=actor_username,
            trigger_type=trigger_type,
            mentioned_roles=mentioned_roles,
            recipient=recipient,
            llm_answer_text=llm_answer_text,
            llm_answer_role_name=llm_answer_role_name,
            send_step=_send_skill_step,
        )
        response_text = loop_result.final_answer_text
        post_data = await _run_role_prepost_processing_phase(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            role=role,
            phase="post",
            payload={
                "user_text": effective_user_text,
                "reply_text": effective_reply_text,
                "response_text": response_text,
            },
            chain_id=skill_chain_id,
        )
        effective_response_text = post_data.get("response_text", response_text)
        if isinstance(effective_response_text, str):
            response_text = effective_response_text

        return RoleRequestResult(
            response_text=response_text,
            group_role=group_role,
            model_override=loop_result.model_override,
            recovery=recovery,
        )

    full_payload, compact_payload = build_llm_payload_json(
        effective_user_text,
        group_role.user_prompt_suffix,
        group_role.user_reply_prefix,
        effective_reply_text,
        username=actor_username,
        recipient=recipient,
        trigger_type=trigger_type,
        mentioned_roles=mentioned_roles,
        system_prompt=system_prompt,
        llm_answer_text=llm_answer_text,
        llm_answer_role_name=llm_answer_role_name,
    )
    content = "INPUT_JSON:\n" + json.dumps(compact_payload, ensure_ascii=False)
    logger.info(
        "llm payload full chat_id=%s user_id=%s role=%s mode=%s payload=%s",
        chat_id,
        user_id,
        role.role_name,
        group_role.mode,
        json.dumps(full_payload, ensure_ascii=False),
    )
    logger.info(
        "llm payload built chat_id=%s user_id=%s role=%s mode=%s payload_chars=%s trigger=%s pruned_payload=%s",
        chat_id,
        user_id,
        role.role_name,
        group_role.mode,
        len(content),
        trigger_type,
        json.dumps(compact_payload, ensure_ascii=False),
    )

    session_id = await resolver.resolve(
        user_id,
        chat_id,
        role,
        session_token,
        model_override=model_override,
    )
    recovery: SessionRecoveryResult | None = None
    try:
        response_text = await llm_executor.send_with_retries(
            session_id=session_id,
            session_token=session_token,
            content=content,
            role=role,
            model_override=model_override,
        )
    except Exception as exc:
        recovery = await _recover_stale_session_and_resend(
            exc=exc,
            user_id=user_id,
            chat_id=chat_id,
            role=role,
            session_id=session_id,
            session_token=session_token,
            model_override=model_override,
            content=content,
            context=context,
        )
        if recovery is None:
            raise
        response_text = recovery.response_text

    post_data = await _run_role_prepost_processing_phase(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        role=role,
        phase="post",
        payload={
            "user_text": effective_user_text,
            "reply_text": effective_reply_text,
            "response_text": response_text,
        },
        chain_id=skill_chain_id,
    )
    effective_response_text = post_data.get("response_text", response_text)
    if isinstance(effective_response_text, str):
        response_text = effective_response_text

    return RoleRequestResult(
        response_text=response_text,
        group_role=group_role,
        model_override=model_override,
        recovery=recovery,
    )


async def send_role_response(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    role: Role,
    response_text: str,
    reply_to_message_id: int,
    model_override: str | None,
    apply_plugins: bool,
) -> str:
    runtime = _runtime(context)
    role_name = role_public_name(role)
    if not apply_plugins:
        full_text = format_with_header(role_name, response_text)
        for chunk in split_message(full_text):
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                reply_to_message_id=reply_to_message_id,
                parse_mode=ParseMode.HTML,
            )
        return response_text

    storage: Storage = runtime.storage
    plugin_manager = runtime.plugin_manager
    llm_executor: LLMExecutor = runtime.llm_executor
    allow_raw_html = bool(runtime.allow_raw_html)
    formatting_mode = str(runtime.formatting_mode)

    payload = {
        "text": response_text,
        "parse_mode": formatting_mode,
        "reply_markup": None,
    }
    logger.info(
        "plugin pre buffered user_id=%s role=%s provider=%s text_len=%s",
        user_id,
        role_name,
        llm_executor.provider_id_for_model(model_override),
        len(response_text),
    )
    ctx_payload = {
        "chat_id": chat_id,
        "user_id": user_id,
        "role_id": role.role_id,
        "role_name": role_name,
        "provider_id": llm_executor.provider_id_for_model(model_override),
        "model_id": model_override,
        "store_text": storage.save_plugin_text,
    }
    payload = plugin_manager.apply_postprocess(payload, ctx_payload)
    response_text = str(payload.get("text", ""))
    reply_markup = payload.get("reply_markup")
    logger.info(
        "plugin post buffered user_id=%s role=%s text_len=%s reply_markup=%s",
        user_id,
        role_name,
        len(response_text),
        bool(reply_markup),
    )
    final_reply_markup = build_plugin_reply_markup(
        reply_markup,
        is_private=chat_id > 0,
        logger=logger,
        log_ctx={"user_id": user_id, "role": role_name},
    )
    rendered = render_llm_text(response_text, formatting_mode, allow_raw_html)
    full_text = format_with_header_raw(role_name, rendered)
    for idx, chunk in enumerate(split_message(full_text)):
        await send_formatted_with_fallback(
            context.bot,
            chat_id,
            chunk,
            reply_to_message_id=reply_to_message_id,
            reply_markup=final_reply_markup if idx == 0 else None,
            allow_raw_html=allow_raw_html,
            formatting_mode=formatting_mode,
        )
    return response_text


async def send_orchestrator_post_event(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    reply_to_message_id: int,
    actor_username: str | None,
    session_token: str,
    orchestrator_role: Role,
    original_user_text: str,
    original_reply_text: str | None,
    answered_role_name: str,
    role_answer_text: str,
    chain_context: ChainContext | None = None,
    dispatch_mentions_fn: Callable[..., Awaitable[None]] | None = None,
) -> None:
    storage: Storage = _runtime(context).storage
    group_role = storage.get_group_role(chat_id, orchestrator_role.role_id)
    if not group_role.enabled:
        return
    try:
        result = await execute_role_request(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            role=orchestrator_role,
            session_token=session_token,
            user_text=original_user_text,
            reply_text=original_reply_text,
            actor_username=actor_username,
            trigger_type="mention_role",
            mentioned_roles=[answered_role_name],
            recipient="orchestrator",
            llm_answer_text=role_answer_text,
            llm_answer_role_name=answered_role_name,
        )
        response_text = result.response_text
        if result.recovery is not None:
            logger.info(
                "Recovered stale orchestrator session old_session_id=%s new_session_id=%s",
                result.recovery.old_session_id,
                result.recovery.new_session_id,
            )
        parsed = parse_orchestrator_response(response_text)
        if parsed is not None:
            logger.info(
                "orchestrator post-event response parsed role=%s actions=%s tool_calls=%s visibility=%s",
                orchestrator_role.role_name,
                len(parsed.actions),
                len(parsed.tool_calls),
                parsed.visibility,
            )
            response_text = parsed.answer_text
        else:
            logger.info("orchestrator post-event response parse fallback role=%s", orchestrator_role.role_name)
        response_text = await send_role_response(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            role=orchestrator_role,
            response_text=response_text,
            reply_to_message_id=reply_to_message_id,
            model_override=result.model_override,
            apply_plugins=True,
        )
        if chain_context is not None:
            dispatcher = dispatch_mentions_fn or dispatch_mentions
            await dispatcher(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                session_token=session_token,
                source_role=orchestrator_role,
                source_response_text=response_text,
                chain_context=chain_context,
            )
    except Exception:
        logger.exception(
            "Failed to send post-event to orchestrator chat_id=%s orchestrator_role=%s source_role=%s",
            chat_id,
            orchestrator_role.role_name,
            answered_role_name,
        )


def extract_delegation_targets(
    *,
    source_response_text: str,
    available_roles: list[Role],
    source_role: Role,
) -> tuple[list[Role], str]:
    role_map = {role_public_name(role).lower(): role for role in available_roles}
    mention_names = extract_role_mentions(source_response_text, set(role_map.keys()))
    targets: list[Role] = []
    seen_ids: set[int] = set()
    for name in mention_names:
        role = role_map.get(name.lower())
        if not role:
            continue
        if role.role_id == source_role.role_id:
            continue
        if role.role_id in seen_ids:
            continue
        targets.append(role)
        seen_ids.add(role.role_id)
    clean_text = source_response_text
    for name in mention_names:
        clean_text = clean_text.replace(f"@{name}", "").replace(f"@{name.lower()}", "")
    return targets, clean_text.strip()


async def dispatch_mentions(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    session_token: str,
    source_role: Role,
    source_response_text: str,
    chain_context: ChainContext,
) -> None:
    if not chain_context.can_continue():
        logger.info(
            "delegation skip: hop limit reached chain_id=%s source_role=%s hop=%s",
            chain_context.chain_id,
            role_public_name(source_role),
            chain_context.hop,
        )
        return

    runtime = _runtime(context)
    storage: Storage = runtime.storage
    orchestrator_group_role = storage.get_enabled_orchestrator_for_group(chat_id)
    available_roles = storage.list_roles_for_group(chat_id)
    orchestrator_role = (
        next((r for r in available_roles if r.role_id == orchestrator_group_role.role_id), None)
        if orchestrator_group_role
        else None
    )
    if orchestrator_role is None and orchestrator_group_role is not None:
        orchestrator_role = storage.get_role_by_id(orchestrator_group_role.role_id)
    targets, delegated_text = extract_delegation_targets(
        source_response_text=source_response_text,
        available_roles=available_roles,
        source_role=source_role,
    )
    if not targets:
        logger.info(
            "delegation none chain_id=%s source_role=%s hop=%s",
            chain_context.chain_id,
            role_public_name(source_role),
            chain_context.hop,
        )
        return
    if not delegated_text:
        logger.info(
            "delegation skip: empty text chain_id=%s source_role=%s targets=%s",
            chain_context.chain_id,
            role_public_name(source_role),
            [role_public_name(r) for r in targets],
        )
        return
    logger.info(
        "delegation detected chain_id=%s source_role=%s hop=%s targets=%s",
        chain_context.chain_id,
        role_public_name(source_role),
        chain_context.hop,
        [role_public_name(r) for r in targets],
    )

    for target in targets:
        delegation_key = chain_context.delegation_key(source_role.role_id, target.role_id, delegated_text)
        same_count = chain_context.same_delegation_count(delegation_key)
        if same_count >= MAX_SAME_DELEGATION_REPEATS - 1:
            logger.info(
                "delegation skip: same text repeat limit chain_id=%s source_role=%s target_role=%s hop=%s repeats=%s",
                chain_context.chain_id,
                role_public_name(source_role),
                role_public_name(target),
                chain_context.hop,
                same_count + 1,
            )
            continue
        target_group_role = storage.get_group_role(chat_id, target.role_id)
        if target_group_role.mode == "orchestrator":
            logger.info(
                "delegation skip: target is orchestrator chain_id=%s source_role=%s target_role=%s",
                chain_context.chain_id,
                role_public_name(source_role),
                role_public_name(target),
            )
            continue
        try:
            logger.info(
                "delegation sent chain_id=%s source_role=%s target_role=%s hop=%s",
                chain_context.chain_id,
                role_public_name(source_role),
                role_public_name(target),
                chain_context.hop,
            )
            result = await execute_role_request(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                role=target,
                session_token=session_token,
                user_text=delegated_text,
                reply_text=None,
                actor_username=role_public_name(source_role),
                trigger_type="mention_role",
                mentioned_roles=[role_public_name(target)],
                recipient=role_public_name(target),
            )
            response_text = result.response_text
            if result.group_role.mode == "orchestrator":
                parsed = parse_orchestrator_response(response_text)
                if parsed is not None:
                    response_text = parsed.answer_text
            response_text = await send_role_response(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                role=target,
                response_text=response_text,
                reply_to_message_id=chain_context.reply_to_message_id,
                model_override=result.model_override,
                apply_plugins=True,
            )
            if orchestrator_role is not None:
                next_context = chain_context.with_delegation(delegation_key).next_hop()
                await send_orchestrator_post_event(
                    context=context,
                    chat_id=chat_id,
                    user_id=user_id,
                    reply_to_message_id=chain_context.reply_to_message_id,
                    actor_username=role_public_name(target),
                    session_token=session_token,
                    orchestrator_role=orchestrator_role,
                    original_user_text=delegated_text,
                    original_reply_text=None,
                    answered_role_name=role_public_name(target),
                    role_answer_text=response_text,
                    chain_context=next_context,
                    dispatch_mentions_fn=dispatch_mentions,
                )
            await dispatch_mentions(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                session_token=session_token,
                source_role=target,
                source_response_text=response_text,
                chain_context=chain_context.with_delegation(delegation_key).next_hop(),
            )
        except MissingUserField as exc:
            await _handle_missing_user_field(
                user_id=user_id,
                chat_id=chat_id,
                message_id=chain_context.reply_to_message_id,
                role_name=role_public_name(target),
                content=delegated_text,
                reply_text=None,
                exc=exc,
                context=context,
            )
            return
        except Exception as exc:
            if _is_unauthorized(exc):
                storage.set_user_authorized(user_id, False)
                await _request_token_for_user(chat_id, user_id, context)
                return
            logger.exception(
                "delegation failed chain_id=%s source_role=%s target_role=%s hop=%s",
                chain_context.chain_id,
                role_public_name(source_role),
                role_public_name(target),
                chain_context.hop,
            )


async def run_chain(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    session_token: str,
    roles: list[Role],
    user_text: str,
    reply_text: str | None,
    actor_username: str | None,
    reply_to_message_id: int,
    is_all: bool,
    apply_plugins: bool,
    save_pending_on_unauthorized: bool,
    pending_role_name: str | None = None,
    allow_orchestrator_post_event: bool = True,
    trigger_type_orchestrator: str = "orchestrator_all_messages",
    chain_origin: ChainOrigin = "group",
) -> ChainRunResult:
    runtime = _runtime(context)
    storage: Storage = runtime.storage
    pending_store = runtime.pending_store
    orchestrator_group_role = storage.get_enabled_orchestrator_for_group(chat_id)
    roles_for_group = storage.list_roles_for_group(chat_id)
    orchestrator_role = (
        next((r for r in roles_for_group if r.role_id == orchestrator_group_role.role_id), None)
        if orchestrator_group_role
        else None
    )
    if orchestrator_role is None and orchestrator_group_role is not None:
        orchestrator_role = storage.get_role_by_id(orchestrator_group_role.role_id)

    had_error = False
    completed_roles = 0
    for role in roles:
        try:
            group_role = storage.get_group_role(chat_id, role.role_id)
            if group_role.mode == "orchestrator":
                trigger_type = trigger_type_orchestrator
                mentioned_roles = [role_public_name(r) for r in roles if r.role_id != role.role_id]
            else:
                trigger_type = "mention_all" if is_all else "mention_role"
                mentioned_roles = [role_public_name(r) for r in roles] if is_all else [role_public_name(role)]
            result = await execute_role_request(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                role=role,
                session_token=session_token,
                user_text=user_text,
                reply_text=reply_text,
                actor_username=actor_username,
                trigger_type=trigger_type,
                mentioned_roles=mentioned_roles,
                recipient=role_public_name(role) if group_role.mode != "orchestrator" else "orchestrator",
            )
            group_role = result.group_role
            model_override = result.model_override
            response_text = result.response_text
            if result.recovery is not None:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"Обновил session_id для роли @{role_public_name(role)}: "
                        f"{result.recovery.old_session_id} -> {result.recovery.new_session_id}"
                    ),
                    reply_to_message_id=reply_to_message_id,
                )
                logger.info(
                    "Recovered stale session role=%s old_session_id=%s new_session_id=%s",
                    role_public_name(role),
                    result.recovery.old_session_id,
                    result.recovery.new_session_id,
                )
            if group_role.mode == "orchestrator":
                parsed = parse_orchestrator_response(response_text)
                if parsed is not None:
                    logger.info(
                        "orchestrator response parsed role=%s actions=%s tool_calls=%s visibility=%s",
                        role.role_name,
                        len(parsed.actions),
                        len(parsed.tool_calls),
                        parsed.visibility,
                    )
                    response_text = parsed.answer_text
                else:
                    logger.info("orchestrator response parse fallback role=%s", role.role_name)
        except MissingUserField as exc:
            role_name = pending_role_name or ("__all__" if is_all else role_public_name(role))
            await _handle_missing_user_field(
                user_id=user_id,
                chat_id=chat_id,
                message_id=reply_to_message_id,
                role_name=role_name,
                content=user_text,
                reply_text=reply_text,
                exc=exc,
                context=context,
            )
            return ChainRunResult(completed_roles=completed_roles, had_error=True, stopped=True)
        except Exception as exc:
            if _is_unauthorized(exc):
                if save_pending_on_unauthorized:
                    role_name = pending_role_name or ("__all__" if is_all else role_public_name(roles[0]))
                    pending_store.save(
                        user_id,
                        chat_id,
                        reply_to_message_id,
                        role_name,
                        user_text,
                        reply_text=reply_text,
                    )
                storage.set_user_authorized(user_id, False)
                await _request_token_for_user(chat_id, user_id, context)
                return ChainRunResult(completed_roles=completed_roles, had_error=True, stopped=True)
            logger.exception("LLM request failed user_id=%s role=%s", user_id, role.role_name)
            await context.bot.send_message(
                chat_id=chat_id,
                text="Ошибка при запросе к LLM. Попробуй позже.",
                reply_to_message_id=reply_to_message_id,
            )
            had_error = True
            continue

        response_text = await send_role_response(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
            role=role,
            response_text=response_text,
            reply_to_message_id=reply_to_message_id,
            model_override=model_override,
            apply_plugins=apply_plugins,
        )
        chain_context = ChainContext.create(
            origin=chain_origin,
            reply_to_message_id=reply_to_message_id,
            max_hops=max(
                1,
                int(getattr(runtime, "orchestrator_max_chain_auto_steps", DEFAULT_ORCHESTRATOR_MAX_CHAIN_AUTO_STEPS)),
            ),
        )
        if allow_orchestrator_post_event and orchestrator_role is not None and group_role.mode != "orchestrator":
            await send_orchestrator_post_event(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                reply_to_message_id=reply_to_message_id,
                actor_username=role_public_name(role),
                session_token=session_token,
                orchestrator_role=orchestrator_role,
                original_user_text=user_text,
                original_reply_text=reply_text,
                answered_role_name=role_public_name(role),
                role_answer_text=response_text,
                chain_context=chain_context,
                dispatch_mentions_fn=dispatch_mentions,
            )
        if chat_id < 0:
            await dispatch_mentions(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
                session_token=session_token,
                source_role=role,
                source_response_text=response_text,
                chain_context=chain_context,
            )
        completed_roles += 1
    return ChainRunResult(completed_roles=completed_roles, had_error=had_error, stopped=False)
