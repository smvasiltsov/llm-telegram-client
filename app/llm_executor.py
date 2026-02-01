from __future__ import annotations

import asyncio
import logging

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
                return await self._client.send_message(
                    session_id=session_id,
                    session_token=session_token,
                    content=content,
                    model_override=model_override or role.llm_model,
                    role_id=role.role_id,
                )
            except Exception as exc:
                last_exc = exc
                self._logger.exception("LLM send failed attempt=%s", attempt + 1)
                if attempt == retries:
                    break
                await asyncio.sleep(0.5 * (attempt + 1))
                attempt += 1
        raise last_exc if last_exc else RuntimeError("LLM send failed")
