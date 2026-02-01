from __future__ import annotations

import logging
import httpx
from uuid import uuid4

from app.llm_router import LLMRouter
from app.models import Role
from app.storage import Storage


class SessionResolver:
    def __init__(self, storage: Storage, llm_client: LLMRouter) -> None:
        self._storage = storage
        self._llm_client = llm_client
        self._logger = logging.getLogger("session_resolver")

    async def ensure_session(
        self,
        telegram_user_id: int,
        group_id: int,
        role: Role,
        session_token: str,
        model_override: str | None = None,
        existing_session_ids: set[str] | None = None,
    ) -> str:
        if not self._llm_client.supports(model_override, "create_session"):
            group_role = self._storage.get_group_role(group_id, role.role_id)
            session = self._storage.get_user_role_session(telegram_user_id, group_id, role.role_id)
            if session:
                self._storage.touch_user_role_session(telegram_user_id, group_id, role.role_id)
                return session.session_id
            local_session_id = uuid4().hex
            self._storage.save_user_role_session(telegram_user_id, group_id, role.role_id, local_session_id)
            if role.base_system_prompt or role.extra_instruction:
                base_prompt = group_role.system_prompt_override or role.base_system_prompt
                system_prompt = f"{base_prompt}\n\n{role.extra_instruction}".strip()
                if system_prompt:
                    self._storage.add_conversation_message(local_session_id, "system", system_prompt)
            self._logger.info(
                "Created local session user_id=%s group_id=%s role=%s",
                telegram_user_id,
                group_id,
                role.role_name,
            )
            return local_session_id
        session = self._storage.get_user_role_session(telegram_user_id, group_id, role.role_id)
        if session and (existing_session_ids is None or session.session_id in existing_session_ids):
            self._storage.touch_user_role_session(telegram_user_id, group_id, role.role_id)
            return session.session_id
        return await self._create_session(telegram_user_id, group_id, role, session_token, model_override)

    async def resolve(
        self,
        telegram_user_id: int,
        group_id: int,
        role: Role,
        session_token: str,
        model_override: str | None = None,
    ) -> str:
        return await self.ensure_session(telegram_user_id, group_id, role, session_token, model_override)

    async def _create_session(
        self,
        telegram_user_id: int,
        group_id: int,
        role: Role,
        session_token: str,
        model_override: str | None = None,
    ) -> str:
        group_role = self._storage.get_group_role(group_id, role.role_id)
        if group_role.system_prompt_override is not None:
            base_prompt = (group_role.system_prompt_override or "").strip()
        else:
            base_prompt = (role.base_system_prompt or "").strip()
        extra_instruction = (role.extra_instruction or "").strip()
        system_prompt = f"{base_prompt}\n\n{extra_instruction}".strip()
        session_id = await self._llm_client.create_session(
            session_token=session_token,
            metadata={
                "telegram_user_id": str(telegram_user_id),
                "role": role.role_name,
                "group_id": str(group_id),
            },
            role_id=role.role_id,
            model_override=model_override,
        )
        group = self._storage.get_group(group_id)
        group_title = group.title if group else None
        chat_name = f"{group_title} / @{role.role_name}" if group_title else f"@{role.role_name}"
        if chat_name and self._llm_client.supports(model_override, "rename_session"):
            try:
                await self._llm_client.rename_session(
                    session_id,
                    session_token,
                    chat_name,
                    role_id=role.role_id,
                    model_override=model_override,
                )
            except Exception:
                self._logger.exception(
                    "Failed to rename session user_id=%s role=%s",
                    telegram_user_id,
                    role.role_name,
                )
        # Send system prompt as a first message after session creation.
        if system_prompt.strip():
            try:
                await self._llm_client.send_message(
                    session_id=session_id,
                    session_token=session_token,
                    content=system_prompt,
                    model_override=model_override or group_role.model_override or role.llm_model,
                    role_id=role.role_id,
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                body = None
                if exc.response is not None:
                    try:
                        await exc.response.aread()
                        body = exc.response.text
                    except Exception:
                        body = "<failed to read response body>"
                self._logger.error(
                    "Failed to warm up session user_id=%s group_id=%s role=%s status=%s body=%r",
                    telegram_user_id,
                    group_id,
                    role.role_name,
                    status,
                    body,
                )
        else:
            self._logger.info(
                "Skip session warm-up (empty prompt) user_id=%s group_id=%s role=%s",
                telegram_user_id,
                group_id,
                role.role_name,
            )
        self._storage.save_user_role_session(telegram_user_id, group_id, role.role_id, session_id)
        self._logger.info(
            "Created session user_id=%s group_id=%s role=%s",
            telegram_user_id,
            group_id,
            role.role_name,
        )
        return session_id
