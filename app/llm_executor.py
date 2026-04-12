from __future__ import annotations

import asyncio
import logging
import time

import httpx

from app.llm_router import LLMRouter
from app.models import Role


class LLMExecutor:
    def __init__(self, client: LLMRouter) -> None:
        self._client = client
        self._logger = logging.getLogger("llm_executor")

    async def send_with_retries(
        self,
        session_id: str,
        session_token: str,
        content: str,
        role: Role,
        model_override: str | None = None,
        team_role_id: int | None = None,
        retries: int = 2,
    ) -> str:
        attempt = 0
        last_exc: Exception | None = None
        provider_id = self._client.provider_id_for_model(model_override or role.llm_model)
        while attempt <= retries:
            started_at = time.monotonic()
            try:
                self._logger.info(
                    "LLM send start provider=%s role=%s session_id=%s attempt=%s/%s content_chars=%s",
                    provider_id,
                    role.role_name,
                    session_id,
                    attempt + 1,
                    retries + 1,
                    len(content),
                )
                response_text = await self._client.send_message(
                    session_id=session_id,
                    session_token=session_token,
                    content=content,
                    model_override=model_override or role.llm_model,
                    role_id=role.role_id,
                    team_role_id=team_role_id,
                )
                self._logger.info(
                    "LLM response received provider=%s role=%s session_id=%s attempt=%s/%s chars=%s elapsed_ms=%s",
                    provider_id,
                    role.role_name,
                    session_id,
                    attempt + 1,
                    retries + 1,
                    len(response_text),
                    int((time.monotonic() - started_at) * 1000),
                )
                return response_text
            except Exception as exc:
                last_exc = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code == 404:
                    break
                sleep_sec = 0.5 * (attempt + 1)
                status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None else None
                self._logger.exception(
                    "LLM send failed provider=%s role=%s session_id=%s attempt=%s/%s elapsed_ms=%s status=%s retry_in_sec=%s",
                    provider_id,
                    role.role_name,
                    session_id,
                    attempt + 1,
                    retries + 1,
                    int((time.monotonic() - started_at) * 1000),
                    status_code,
                    sleep_sec if attempt < retries else 0,
                )
                if attempt == retries:
                    break
                await asyncio.sleep(sleep_sec)
                attempt += 1
        raise last_exc if last_exc else RuntimeError("LLM send failed")

    def provider_id_for_model(self, model_override: str | None) -> str:
        return self._client.provider_id_for_model(model_override)
