from __future__ import annotations

import logging
import httpx

from app.llm_router import LLMRouter
from app.llm_providers import ProviderConfig
from app.security import TokenCipher
from app.session_resolver import SessionResolver
from app.storage import Storage


class AuthService:
    def __init__(
        self,
        storage: Storage,
        cipher: TokenCipher,
        llm_client: LLMRouter,
        session_resolver: SessionResolver,
        provider_registry: dict[str, ProviderConfig],
        default_provider_id: str,
    ) -> None:
        self._storage = storage
        self._cipher = cipher
        self._llm_client = llm_client
        self._session_resolver = session_resolver
        self._provider_registry = provider_registry
        self._default_provider_id = default_provider_id
        self._logger = logging.getLogger("auth")

    async def validate_and_store(
        self,
        telegram_user_id: int,
        token: str,
        group_id: int | None,
    ) -> bool:
        token = self._normalize_token(token)
        provider = self._provider_registry.get(self._default_provider_id)
        uses_user_field = bool(provider and provider.user_fields.get("auth_token"))
        if uses_user_field:
            self._storage.set_provider_user_value(self._default_provider_id, "auth_token", None, token)
        try:
            sessions = await self._llm_client.list_sessions(token)
        except ValueError:
            sessions = []
        except Exception:
            self._logger.exception("Token validation failed")
            if uses_user_field:
                self._storage.delete_provider_user_value(self._default_provider_id, "auth_token", None)
            return False

        existing_session_ids = set(sessions)
        if group_id is not None:
            group_roles = self._storage.list_group_roles(group_id)
            for group_role in group_roles:
                role = self._storage.get_role_by_id(group_role.role_id)
                try:
                    await self._session_resolver.ensure_session(
                        telegram_user_id=telegram_user_id,
                        group_id=group_id,
                        role=role,
                        session_token=token,
                        existing_session_ids=existing_session_ids,
                    )
                except Exception as exc:
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                        self._logger.error(
                            "Session warm-up failed user_id=%s role=%s status=%s body=%r",
                            telegram_user_id,
                            role.role_name,
                            exc.response.status_code,
                            exc.response.text,
                        )
                    else:
                        self._logger.exception(
                            "Session warm-up failed user_id=%s role=%s",
                            telegram_user_id,
                            role.role_name,
                        )
                    return False

        encrypted = self._cipher.encrypt(token)
        self._storage.upsert_auth_token(telegram_user_id, encrypted)
        self._storage.set_user_authorized(telegram_user_id, True)
        return True

    @staticmethod
    def _normalize_token(token: str) -> str:
        value = token.strip()
        lowered = value.lower()
        if lowered.startswith("cookie:"):
            value = value.split(":", 1)[1].strip()
            lowered = value.lower()
        if lowered.startswith("sessionid="):
            value = value.split("=", 1)[1].strip()
        if ";" in value:
            value = value.split(";", 1)[0].strip()
        return value
