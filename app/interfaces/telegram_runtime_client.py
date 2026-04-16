from __future__ import annotations

import asyncio
import logging
from uuid import uuid4
from typing import Any, Awaitable, Callable, Mapping, Protocol

import httpx

from app.application.contracts import Result
from app.application.contracts.runtime_ops import RuntimeOperationResult, RuntimeTransition
from app.application.contracts import ErrorCode, log_structured_error, RuntimeOperation
from app.application.dependencies import (
    resolve_pending_replay_dependencies,
    resolve_runtime_orchestration_dependencies,
    resolve_storage_uow_dependencies,
)
from app.application.use_cases.group_runtime import GroupFlushInput, build_group_flush_plan, prepare_group_buffer_plan
from app.application.use_cases.private_pending_replay import build_pending_replay_dispatch_plan
from app.application.use_cases.runtime_orchestration import execute_run_chain_operation
from app.application.use_cases.transaction_boundaries import pop_pending_replay_if_unchanged
from app.llm_providers import ProviderUserField
from app.llm_router import MissingUserField
from app.pending_store import PendingStore
from app.services.runtime_message_flow import handle_missing_user_field as save_missing_user_field_pending
from app.services.role_pipeline import roles_require_auth

logger = logging.getLogger("bot")


class RuntimeClientPort(Protocol):
    async def execute_run_chain(self, **kwargs: Any) -> Result[RuntimeOperationResult]: ...
    def prepare_group_buffer(self, **kwargs: Any): ...
    async def flush_group_buffered(self, **kwargs: Any) -> None: ...
    async def process_pending_replay(self, **kwargs: Any) -> bool: ...


def _resolve_storage(context: Any):
    storage_result = resolve_storage_uow_dependencies(context.application.bot_data)
    if storage_result.is_ok and storage_result.value is not None:
        return storage_result.value.storage
    return context.application.bot_data["runtime"].storage


def _resolve_pending_store(context: Any) -> PendingStore:
    pending_result = resolve_pending_replay_dependencies(context.application.bot_data)
    if pending_result.is_ok and pending_result.value is not None:
        return pending_result.value.pending_store
    return context.application.bot_data["runtime"].pending_store


def _resolve_cipher(context: Any):
    orchestration_result = resolve_runtime_orchestration_dependencies(context.application.bot_data)
    if orchestration_result.is_ok and orchestration_result.value is not None:
        return orchestration_result.value.cipher
    return context.application.bot_data["runtime"].cipher


def _runtime(context: Any):
    return context.application.bot_data["runtime"]


def _skill_entry_id(entry: object) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, Mapping):
        raw = entry.get("id") or entry.get("skill_id") or entry.get("name")
        return str(raw or "").strip()
    return ""


def _has_fs_skills(entries: object) -> bool:
    if not isinstance(entries, list):
        return False
    return any(_skill_entry_id(item).startswith("fs.") for item in entries)


class ThinRuntimeClient:
    mode = "thin"

    @staticmethod
    def _register_background_task(runtime: Any, task: asyncio.Task[Any]) -> None:
        tasks = getattr(runtime, "_thin_answer_tasks", None)
        if not isinstance(tasks, set):
            tasks = set()
            setattr(runtime, "_thin_answer_tasks", tasks)
        tasks.add(task)

        def _cleanup(done_task: asyncio.Task[Any]) -> None:
            try:
                tasks.discard(done_task)
            except Exception:
                pass
            try:
                done_task.result()
            except Exception:
                logger.exception("thin_api_async_answer_task_failed")

        task.add_done_callback(_cleanup)

    async def _deliver_answer_async(
        self,
        *,
        base_url: str,
        timeout_sec: int,
        headers: dict[str, str],
        question_id: str,
        chat_id: int,
        reply_to_message_id: int,
        context: Any,
        correlation_id: str,
        max_wait_sec: int,
    ) -> None:
        runtime = _runtime(context)
        poll_interval = float(getattr(runtime, "telegram_api_answer_poll_interval_sec", 1.0) or 1.0)
        poll_interval = max(0.1, poll_interval)
        attempts = max(1, int(max_wait_sec / poll_interval))

        async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=float(timeout_sec)) as client:
            for _ in range(attempts):
                answer_resp = await client.get(f"/api/v1/questions/{question_id}/answer", headers=headers)
                if answer_resp.status_code == 200:
                    answer_payload = answer_resp.json()
                    answer_text = str(answer_payload.get("text") or "").strip()
                    if answer_text:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=answer_text,
                            reply_to_message_id=reply_to_message_id,
                        )
                        logger.info(
                            "thin_api_async_answer_delivered correlation_id=%s question_id=%s chat_id=%s",
                            correlation_id,
                            question_id,
                            chat_id,
                        )
                    return
                if answer_resp.status_code == 409:
                    await asyncio.sleep(poll_interval)
                    continue
                logger.warning(
                    "thin_api_async_answer_poll_failed correlation_id=%s question_id=%s status=%s body=%s",
                    correlation_id,
                    question_id,
                    answer_resp.status_code,
                    answer_resp.text[:300],
                )
                return
        logger.warning(
            "thin_api_async_answer_timeout correlation_id=%s question_id=%s wait_sec=%s",
            correlation_id,
            question_id,
            max_wait_sec,
        )

    async def execute_run_chain(self, **kwargs: Any) -> Result[RuntimeOperationResult]:
        context = kwargs.get("context")
        if context is not None:
            api_result = await self._execute_run_chain_via_api(**kwargs)
            if api_result is not None:
                return api_result
        return await execute_run_chain_operation(**kwargs)

    async def _execute_run_chain_via_api(self, **kwargs: Any) -> Result[RuntimeOperationResult] | None:
        context = kwargs["context"]
        runtime = _runtime(context)
        base_url = str(getattr(runtime, "telegram_api_base_url", "") or "").strip()
        timeout_sec = max(1, int(getattr(runtime, "telegram_api_timeout_sec", 30) or 30))
        answer_wait_sec = max(timeout_sec, int(getattr(runtime, "telegram_api_answer_timeout_sec", 300) or 300))
        if not base_url:
            return None

        roles = list(kwargs.get("roles") or [])
        is_all = bool(kwargs.get("is_all"))
        if is_all or len(roles) != 1:
            logger.info("thin_api_fallback_inprocess reason=unsupported_route is_all=%s roles_count=%s", is_all, len(roles))
            return None

        role = roles[0]
        role_id = getattr(role, "role_id", None)
        if role_id is None:
            logger.info("thin_api_fallback_inprocess reason=missing_role_id")
            return None

        team_id = int(kwargs["team_id"])
        chat_id = int(kwargs["chat_id"])
        user_text = str(kwargs["user_text"])
        reply_to_message_id = int(kwargs["reply_to_message_id"])
        operation = kwargs.get("operation", RuntimeOperation.RUN_CHAIN)
        op_name = operation.value if isinstance(operation, RuntimeOperation) else str(operation)
        corr_id = str(kwargs.get("correlation_id") or uuid4().hex)
        request_id = str(kwargs.get("request_id") or uuid4().hex)

        team_role_id = _resolve_storage(context).resolve_team_role_id(team_id, int(role_id))
        if team_role_id is None:
            logger.warning("thin_api_fallback_inprocess reason=team_role_not_found team_id=%s role_id=%s", team_id, role_id)
            return None

        headers = {
            "X-Owner-User-Id": str(int(runtime.owner_user_id)),
            "X-Correlation-Id": corr_id,
            "Idempotency-Key": f"tg-{request_id}",
        }
        payload = {
            "team_id": team_id,
            "team_role_id": int(team_role_id),
            "text": user_text,
            "origin_interface": "telegram",
            "origin_type": "user",
        }

        try:
            async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=float(timeout_sec)) as client:
                missing_field_exc = await self._resolve_missing_required_field(
                    context=context,
                    client=client,
                    headers=headers,
                    team_id=team_id,
                    team_role_id=int(team_role_id),
                    role=role,
                )
                if missing_field_exc is not None:
                    await self._save_missing_field_pending_and_request_dm(
                        context=context,
                        team_id=team_id,
                        chat_id=chat_id,
                        user_id=int(kwargs["user_id"]),
                        message_id=reply_to_message_id,
                        role_name=str(kwargs.get("pending_role_name") or role.public_name()),
                        content=user_text,
                        reply_text=(str(kwargs.get("reply_text")) if kwargs.get("reply_text") is not None else None),
                        exc=missing_field_exc,
                    )
                    return Result.ok(
                        RuntimeOperationResult(
                            operation=op_name,
                            request_id=request_id,
                            completed=False,
                            queued=False,
                            busy_acquired=False,
                            pending_saved=True,
                            replay_scheduled=False,
                            transitions=(),
                        )
                    )
                create_resp = await client.post("/api/v1/questions", json=payload, headers=headers)
                if create_resp.status_code not in {200, 202}:
                    logger.warning(
                        "thin_api_fallback_inprocess reason=create_failed status=%s body=%s",
                        create_resp.status_code,
                        create_resp.text[:300],
                    )
                    return None
                create_payload = create_resp.json()
                question_payload = create_payload.get("question") or {}
                question_id = str(((create_payload.get("question") or {}).get("question_id")) or "").strip()
                thread_id = str((question_payload.get("thread_id")) or "").strip()
                if not question_id:
                    logger.warning("thin_api_fallback_inprocess reason=missing_question_id")
                    return None
                if thread_id:
                    try:
                        _ = await client.put(
                            "/api/v1/admin/event-subscriptions",
                            json={
                                "scope": "thread",
                                "scope_id": thread_id,
                                "interface_type": "telegram",
                                "target_id": str(chat_id),
                                "mode": "mirror",
                                "is_active": True,
                            },
                            headers=headers,
                        )
                    except Exception:
                        logger.exception(
                            "thin_api_thread_subscription_upsert_failed correlation_id=%s thread_id=%s chat_id=%s",
                            corr_id,
                            thread_id,
                            chat_id,
                        )

                event_bus_delivery_enabled = bool(getattr(runtime, "telegram_event_bus_delivery_enabled", False))
                if event_bus_delivery_enabled:
                    logger.info(
                        "thin_api_event_bus_delivery_enabled correlation_id=%s question_id=%s thread_id=%s",
                        corr_id,
                        question_id,
                        thread_id,
                    )
                    return Result.ok(
                        RuntimeOperationResult(
                            operation=op_name,
                            request_id=request_id,
                            completed=True,
                            queued=True,
                            busy_acquired=True,
                            pending_saved=False,
                            replay_scheduled=False,
                            transitions=(
                                RuntimeTransition(
                                    operation=op_name,
                                    trigger=str(kwargs.get("chain_origin") or "telegram"),
                                    from_state="accepted",
                                    to_state="queued",
                                    team_role_id=int(team_role_id),
                                    request_id=request_id,
                                    reason="thin_api_event_bus_dispatch",
                                ),
                            ),
                        )
                    )

                answer_text: str | None = None
                for _ in range(timeout_sec):
                    answer_resp = await client.get(f"/api/v1/questions/{question_id}/answer", headers=headers)
                    if answer_resp.status_code == 200:
                        answer_payload = answer_resp.json()
                        answer_text = str(answer_payload.get("text") or "").strip()
                        break
                    if answer_resp.status_code == 409:
                        await asyncio.sleep(1.0)
                        continue
                    logger.warning(
                        "thin_api_fallback_inprocess reason=answer_poll_failed status=%s body=%s",
                        answer_resp.status_code,
                        answer_resp.text[:300],
                    )
                    return None

                if not answer_text:
                    task = asyncio.create_task(
                        self._deliver_answer_async(
                            base_url=base_url,
                            timeout_sec=timeout_sec,
                            headers=headers,
                            question_id=question_id,
                            chat_id=chat_id,
                            reply_to_message_id=reply_to_message_id,
                            context=context,
                            correlation_id=corr_id,
                            max_wait_sec=answer_wait_sec,
                        ),
                        name=f"thin-answer-{question_id}",
                    )
                    self._register_background_task(runtime, task)
                    logger.info(
                        "thin_api_async_answer_scheduled correlation_id=%s question_id=%s wait_sec=%s",
                        corr_id,
                        question_id,
                        answer_wait_sec,
                    )
                    return Result.ok(
                        RuntimeOperationResult(
                            operation=op_name,
                            request_id=request_id,
                            completed=True,
                            queued=True,
                            busy_acquired=True,
                            pending_saved=False,
                            replay_scheduled=False,
                            transitions=(
                                RuntimeTransition(
                                    operation=op_name,
                                    trigger=str(kwargs.get("chain_origin") or "telegram"),
                                    from_state="accepted",
                                    to_state="queued",
                                    team_role_id=int(team_role_id),
                                    request_id=request_id,
                                    reason="thin_api_async_delivery_scheduled",
                                ),
                            ),
                        )
                    )

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=answer_text,
                    reply_to_message_id=reply_to_message_id,
                )
                return Result.ok(
                    RuntimeOperationResult(
                        operation=op_name,
                        request_id=request_id,
                        completed=True,
                        queued=True,
                        busy_acquired=True,
                        pending_saved=False,
                        replay_scheduled=False,
                        transitions=(
                            RuntimeTransition(
                                operation=op_name,
                                trigger=str(kwargs.get("chain_origin") or "telegram"),
                                from_state="accepted",
                                to_state="answered",
                                team_role_id=int(team_role_id),
                                request_id=request_id,
                                reason="thin_api_dispatch",
                            ),
                        ),
                    )
                )
        except Exception as exc:  # pragma: no cover - network/runtime failures
            logger.exception("thin_api_fallback_inprocess reason=api_exception error=%s", type(exc).__name__)
            return None

    async def _resolve_missing_required_field(
        self,
        *,
        context: Any,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        team_id: int,
        team_role_id: int,
        role: Any,
    ) -> MissingUserField | None:
        runtime = _runtime(context)
        response = await client.get(
            f"/api/v1/teams/{team_id}/roles",
            params={"include_inactive": "true"},
            headers=headers,
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        if not isinstance(payload, list):
            return None
        role_payload = next(
            (
                item
                for item in payload
                if int(item.get("team_role_id") or -1) == int(team_role_id)
            ),
            None,
        )
        if not isinstance(role_payload, dict):
            return None

        working_dir_required = self._resolve_working_dir_requirement(runtime=runtime, role=role)
        if working_dir_required is not None and not str(role_payload.get("working_dir") or "").strip():
            provider_id, prompt = working_dir_required
            return MissingUserField(
                provider_id,
                ProviderUserField(key="working_dir", prompt=prompt, scope="role"),
                int(getattr(role, "role_id", 0) or 0),
            )

        if _has_fs_skills(role_payload.get("skills")) and not str(role_payload.get("root_dir") or "").strip():
            return MissingUserField(
                "skills",
                ProviderUserField(
                    key="root_dir",
                    prompt="Введи абсолютный root_dir для fs.* навыков.",
                    scope="role",
                ),
                int(getattr(role, "role_id", 0) or 0),
            )
        return None

    def _resolve_working_dir_requirement(self, *, runtime: Any, role: Any) -> tuple[str, str] | None:
        model_override = str(getattr(role, "llm_model", "") or "").strip() or None
        llm_router = getattr(runtime, "llm_router", None)
        provider_registry = dict(getattr(runtime, "provider_registry", {}) or {})
        if llm_router is None or not provider_registry:
            return None
        try:
            provider_id = str(llm_router.provider_id_for_model(model_override))
        except Exception:
            return None
        provider = provider_registry.get(provider_id)
        if provider is None:
            return None
        field = (getattr(provider, "user_fields", {}) or {}).get("working_dir")
        if field is None or str(getattr(field, "scope", "")).strip().lower() != "role":
            return None
        prompt = str(getattr(field, "prompt", "") or "").strip() or "Введи working_dir (абсолютный путь)."
        return provider_id, prompt

    async def _save_missing_field_pending_and_request_dm(
        self,
        *,
        context: Any,
        team_id: int,
        chat_id: int,
        user_id: int,
        message_id: int,
        role_name: str,
        content: str,
        reply_text: str | None,
        exc: MissingUserField,
    ) -> None:
        await save_missing_user_field_pending(
            runtime=_runtime(context),
            user_id=user_id,
            chat_id=chat_id,
            team_id=team_id,
            message_id=message_id,
            role_name=role_name,
            content=content,
            reply_text=reply_text,
            exc=exc,
            request_user_field_fn=lambda req_chat_id, req_user_id, field: self._request_user_field_dm(
                context=context,
                chat_id=req_chat_id,
                user_id=req_user_id,
                field=field,
            ),
        )

    async def _request_user_field_dm(self, *, context: Any, chat_id: int, user_id: int, field: ProviderUserField) -> None:
        try:
            await context.bot.send_message(chat_id=user_id, text=field.prompt)
        except Exception:
            logger.exception("thin_api_pending_field_dm_failed user_id=%s key=%s", user_id, field.key)
            await context.bot.send_message(
                chat_id=chat_id,
                text="Не смог написать в личку. Напиши боту в личные сообщения.",
            )

    def prepare_group_buffer(self, **kwargs: Any):
        context = kwargs["context"]
        storage = _resolve_storage(context)
        runtime = _runtime(context)
        return prepare_group_buffer_plan(
            storage=storage,
            runtime=runtime,
            chat_id=int(kwargs["chat_id"]),
            chat_title=kwargs.get("chat_title"),
            user_id=int(kwargs["user_id"]),
            text=str(kwargs["text"]),
        )

    async def flush_group_buffered(self, **kwargs: Any) -> None:
        context = kwargs["context"]
        chat_id = int(kwargs["chat_id"])
        user_id = int(kwargs["user_id"])
        combined_text = str(kwargs["combined_text"])
        reply_text = kwargs.get("reply_text")
        first_message_id = int(kwargs["first_message_id"])
        correlation_id = str(kwargs["correlation_id"])
        request_token_fn = kwargs["request_token_fn"]

        runtime = _runtime(context)
        storage = _resolve_storage(context)
        flush_result = build_group_flush_plan(
            storage=storage,
            runtime=runtime,
            data=GroupFlushInput(
                chat_id=chat_id,
                user_id=user_id,
                combined_text=combined_text,
                reply_text=reply_text,
                first_message_id=first_message_id,
                bot_username=runtime.bot_username,
                owner_user_id=runtime.owner_user_id,
                require_bot_mention=runtime.require_bot_mention,
            ),
            roles_require_auth_fn=lambda **auth_kwargs: roles_require_auth(context=context, **auth_kwargs),
            cipher=_resolve_cipher(context),
        )
        if flush_result.is_error or flush_result.value is None:
            log_structured_error(
                logger,
                event="group_flush_failed",
                error=flush_result.error,
                extra={"chat_id": chat_id, "user_id": user_id},
            )
            return
        plan = flush_result.value
        if plan.action == "skip":
            return
        if plan.action == "send_hint":
            await context.bot.send_message(chat_id=chat_id, text="Напиши сообщение после роли.")
            return
        if plan.action == "request_token":
            if plan.team_id is None or plan.route is None or plan.role_name_for_pending is None or plan.content_for_pending is None:
                logger.warning("flush token request skipped due to incomplete plan chat_id=%s user_id=%s", chat_id, user_id)
                return
            pending = _resolve_pending_store(context)
            pending.save(
                user_id,
                chat_id,
                first_message_id,
                plan.role_name_for_pending,
                plan.content_for_pending,
                reply_text=reply_text,
                team_id=plan.team_id,
            )
            await request_token_fn(chat_id, user_id, context)
            return
        if plan.action != "dispatch_chain" or plan.team_id is None or plan.route is None:
            logger.warning("flush dispatch skipped due to incomplete plan chat_id=%s user_id=%s", chat_id, user_id)
            return
        reply_to_message_id = plan.reply_to_message_id if plan.reply_to_message_id is not None else first_message_id
        await self.execute_run_chain(
            context=context,
            team_id=plan.team_id,
            chat_id=chat_id,
            user_id=user_id,
            session_token=plan.session_token,
            roles=plan.route.roles,
            user_text=plan.route.content,
            reply_text=reply_text,
            actor_username="user",
            reply_to_message_id=reply_to_message_id,
            is_all=plan.route.is_all,
            apply_plugins=True,
            save_pending_on_unauthorized=True,
            pending_role_name=plan.role_name_for_pending or ("__all__" if plan.route.is_all else plan.route.roles[0].public_name()),
            allow_orchestrator_post_event=True,
            chain_origin="group",
            correlation_id=correlation_id,
        )

    async def process_pending_replay(self, **kwargs: Any) -> bool:
        context = kwargs["context"]
        user_id = int(kwargs["user_id"])
        correlation_id = str(kwargs["correlation_id"])
        clear_counters_fn: Callable[[int], None] = kwargs["clear_counters_fn"]
        pending = _resolve_pending_store(context)
        pending_msg = pending.peek_record(user_id)
        if not pending_msg:
            clear_counters_fn(user_id)
            logger.info("pending message not found user_id=%s", user_id)
            return False
        original_pending_msg = pending_msg
        storage = _resolve_storage(context)
        plan_result = build_pending_replay_dispatch_plan(
            storage=storage,
            runtime=_runtime(context),
            user_id=user_id,
            pending_msg=pending_msg,
            roles_require_auth_fn=lambda **auth_kwargs: roles_require_auth(context=context, **auth_kwargs),
            cipher=_resolve_cipher(context),
        )
        if plan_result.is_error or plan_result.value is None:
            log_structured_error(
                logger,
                event="private_pending_replay_plan_failed",
                error=plan_result.error,
                extra={"user_id": user_id},
            )
            return False
        plan = plan_result.value
        if plan.action == "skip":
            if plan.should_drop_pending:
                pending.pop_record(user_id)
            if plan.should_clear_counters:
                clear_counters_fn(user_id)
            if plan.reason == "missing_team_id" and plan.chat_id is not None:
                logger.warning("pending message dropped (missing team_id) user_id=%s chat_id=%s", user_id, plan.chat_id)
            elif plan.reason == "role_not_found":
                logger.info("pending role not found user_id=%s role_name=%s", user_id, plan.role_name)
            return False
        if plan.action == "request_token":
            request_token_fn: Callable[[int, int, Any], Awaitable[None]] = kwargs["request_token_fn"]
            if plan.chat_id is not None:
                await request_token_fn(plan.chat_id, user_id, context)
            return False
        if (
            plan.action != "dispatch"
            or plan.chat_id is None
            or plan.team_id is None
            or plan.message_id is None
            or plan.role_name is None
            or plan.content is None
        ):
            return False
        runtime_result = await self.execute_run_chain(
            context=context,
            team_id=plan.team_id,
            chat_id=plan.chat_id,
            user_id=user_id,
            session_token=plan.session_token,
            roles=list(plan.roles),
            user_text=plan.content,
            reply_text=plan.reply_text,
            actor_username="user",
            reply_to_message_id=plan.message_id,
            is_all=plan.role_name == "__all__",
            apply_plugins=False,
            save_pending_on_unauthorized=False,
            pending_role_name=plan.role_name,
            allow_orchestrator_post_event=plan.chat_id < 0,
            chain_origin="pending",
            operation=RuntimeOperation.PENDING_REPLAY,
            request_id=f"pending-{user_id}-{plan.message_id}",
            correlation_id=correlation_id,
        )
        if runtime_result.is_ok and runtime_result.value and (runtime_result.value.completed or runtime_result.value.queued):
            clear_counters_fn(user_id)
            removed, current_pending_msg = pop_pending_replay_if_unchanged(
                pending_store=pending,
                user_id=user_id,
                original_pending_msg=original_pending_msg,
            )
            if (not removed) and current_pending_msg is not None:
                logger.info(
                    "pending message preserved user_id=%s old_role=%s new_role=%s",
                    user_id,
                    original_pending_msg.get("role_name"),
                    current_pending_msg.get("role_name"),
                )
            return True
        return False


class LegacyRuntimeClient:
    mode = "legacy"

    async def execute_run_chain(self, **kwargs: Any) -> Result[RuntimeOperationResult]:
        return await execute_run_chain_operation(**kwargs)

    def prepare_group_buffer(self, **kwargs: Any):
        thin = ThinRuntimeClient()
        return thin.prepare_group_buffer(**kwargs)

    async def flush_group_buffered(self, **kwargs: Any) -> None:
        thin = ThinRuntimeClient()
        await thin.flush_group_buffered(**kwargs)

    async def process_pending_replay(self, **kwargs: Any) -> bool:
        thin = ThinRuntimeClient()
        return await thin.process_pending_replay(**kwargs)


def build_runtime_client(*, thin_enabled: bool) -> RuntimeClientPort:
    if thin_enabled:
        return ThinRuntimeClient()
    return LegacyRuntimeClient()


def resolve_runtime_client(bot_data: Mapping[str, Any]) -> RuntimeClientPort:
    direct = bot_data.get("runtime_client")
    if direct is not None and callable(getattr(direct, "execute_run_chain", None)):
        return direct
    runtime = bot_data.get("runtime")
    thin_enabled = bool(getattr(runtime, "telegram_thin_client_enabled", True))
    return build_runtime_client(thin_enabled=thin_enabled)


__all__ = [
    "RuntimeClientPort",
    "ThinRuntimeClient",
    "LegacyRuntimeClient",
    "build_runtime_client",
    "resolve_runtime_client",
]
