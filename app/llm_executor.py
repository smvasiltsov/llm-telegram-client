from __future__ import annotations

import asyncio
import logging

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
        retries: int = 2,
    ) -> str:
        attempt = 0
        last_exc: Exception | None = None
        while attempt <= retries:
            try:
                response_text = await self._client.send_message(
                    session_id=session_id,
                    session_token=session_token,
                    content=content,
                    model_override=model_override or role.llm_model,
                    role_id=role.role_id,
                )
                self._logger.info("LLM response received role=%s chars=%s", role.role_name, len(response_text))
                return response_text
            except Exception as exc:
                last_exc = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code == 404:
                    break
                self._logger.exception("LLM send failed attempt=%s", attempt + 1)
                if attempt == retries:
                    break
                await asyncio.sleep(0.5 * (attempt + 1))
                attempt += 1
        raise last_exc if last_exc else RuntimeError("LLM send failed")

    def provider_id_for_model(self, model_override: str | None) -> str:
        return self._client.provider_id_for_model(model_override)
