from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from app.llm_providers import ProviderConfig, ProviderUserField
from app.storage import Storage


class MissingUserField(Exception):
    def __init__(self, provider_id: str, field: ProviderUserField, role_id: int | None) -> None:
        super().__init__(f"Missing user field {field.key} for provider {provider_id}")
        self.provider_id = provider_id
        self.field = field
        self.role_id = role_id


class LLMRouter:
    def __init__(
        self,
        provider_registry: dict[str, ProviderConfig],
        clients: dict[str, httpx.AsyncClient],
        storage: Storage,
        default_provider_id: str = "alfagen",
    ) -> None:
        self._provider_registry = provider_registry
        self._clients = clients
        self._storage = storage
        self._default_provider_id = default_provider_id
        self._logger = logging.getLogger("llm_router")

    def _split_model(self, model_override: str | None) -> tuple[str, str | None]:
        if not model_override:
            return self._default_provider_id, None
        if ":" not in model_override:
            if model_override in self._provider_registry:
                return model_override, None
            return self._default_provider_id, model_override
        provider_id, model_id = model_override.split(":", 1)
        return provider_id, model_id or None

    def _get_provider(self, provider_id: str) -> ProviderConfig:
        provider = self._provider_registry.get(provider_id)
        if not provider:
            raise ValueError(f"Provider '{provider_id}' is not registered")
        return provider

    def _get_client(self, provider_id: str) -> httpx.AsyncClient:
        client = self._clients.get(provider_id)
        if not client:
            raise ValueError(f"Provider '{provider_id}' has no client")
        return client

    def _ensure_capability(self, provider_id: str, capability: str) -> None:
        provider = self._get_provider(provider_id)
        if provider.adapter != "generic":
            raise ValueError(f"Provider '{provider_id}' uses unsupported adapter '{provider.adapter}'")
        if not provider.capabilities.get(capability, False):
            raise ValueError(f"Provider '{provider_id}' does not support '{capability}'")

    def provider_id_for_model(self, model_override: str | None) -> str:
        provider_id, _ = self._split_model(model_override)
        return provider_id

    def supports(self, model_override: str | None, capability: str) -> bool:
        provider_id = self.provider_id_for_model(model_override)
        provider = self._get_provider(provider_id)
        return bool(provider.capabilities.get(capability, False))

    def auth_mode_for_model(self, model_override: str | None) -> str:
        provider_id = self.provider_id_for_model(model_override)
        provider = self._get_provider(provider_id)
        return provider.auth_mode or "none"

    async def list_sessions(self, session_token: str, model_override: str | None = None) -> list[str]:
        provider_id, _ = self._split_model(model_override)
        self._ensure_capability(provider_id, "list_sessions")
        provider = self._get_provider(provider_id)
        return await self._list_sessions_generic(provider)

    async def create_session(
        self,
        session_token: str,
        metadata: dict[str, str] | None = None,
        role_id: int | None = None,
        model_override: str | None = None,
    ) -> str:
        provider_id, _ = self._split_model(model_override)
        self._ensure_capability(provider_id, "create_session")
        provider = self._get_provider(provider_id)
        return await self._create_session_generic(provider, role_id)

    async def rename_session(
        self,
        session_id: str,
        session_token: str,
        name: str,
        role_id: int | None = None,
        model_override: str | None = None,
    ) -> None:
        provider_id, _ = self._split_model(model_override)
        self._ensure_capability(provider_id, "rename_session")
        provider = self._get_provider(provider_id)
        await self._rename_session_generic(provider, session_id, name, role_id)

    async def send_message(
        self,
        session_id: str,
        session_token: str,
        content: str,
        model_override: str | None = None,
        role_id: int | None = None,
    ) -> str:
        provider_id, model_id = self._split_model(model_override)
        provider = self._get_provider(provider_id)
        if model_override and ":" in model_override:
            self._logger.debug("Resolved model override %s -> %s", model_override, model_id)
        if not provider.capabilities.get("model_select", False):
            model_id = None
        client = self._get_client(provider_id)
        response_text = await self._send_generic(provider, client, session_id, content, model_id, role_id)
        self._storage.add_conversation_message(session_id, "user", content)
        self._storage.add_conversation_message(session_id, "assistant", response_text)
        return response_text

    def _render_template(
        self,
        value: Any,
        context: dict[str, Any],
        provider: ProviderConfig,
        role_id: int | None,
    ) -> Any:
        if isinstance(value, str):
            if value.startswith("[[[") and value.endswith("]]]"):
                key = value[3:-3].strip()
                return self._resolve_user_field(provider, key, role_id)
            if value.startswith("{{") and value.endswith("}}"):
                key = value[2:-2].strip()
                if key in context:
                    return context[key]
            result = value
            if "[[[" in result:
                for key in re.findall(r"\[\[\[(.+?)\]\]\]", result):
                    replacement = self._resolve_user_field(provider, key.strip(), role_id)
                    result = result.replace(f"[[[{key}]]]", replacement)
            for key, ctx_value in context.items():
                if isinstance(ctx_value, (str, int, float)):
                    result = result.replace(f"{{{{{key}}}}}", str(ctx_value))
            return result
        if isinstance(value, list):
            return [self._render_template(item, context, provider, role_id) for item in value]
        if isinstance(value, dict):
            return {k: self._render_template(v, context, provider, role_id) for k, v in value.items()}
        return value

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            if len(value) > 8:
                return value[:4] + "…" + value[-4:]
            return "***"
        return "***"

    def _redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        redacted: dict[str, Any] = {}
        for key, val in data.items():
            key_lower = key.lower()
            if any(token in key_lower for token in ("token", "cookie", "authorization", "session")):
                redacted[key] = self._redact(val)
            elif isinstance(val, dict):
                redacted[key] = self._redact_dict(val)
            elif isinstance(val, list):
                redacted[key] = [self._redact(v) for v in val]
            else:
                redacted[key] = val
        return redacted

    def _extract_path(self, data: Any, path: str | None) -> Any:
        if path is None:
            return None
        current: Any = data
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _resolve_user_field(self, provider: ProviderConfig, key: str, role_id: int | None) -> str:
        field = provider.user_fields.get(key)
        if not field:
            raise ValueError(f"Unknown user field '{key}' for provider {provider.provider_id}")
        scoped_role_id = None if field.scope == "provider" else role_id
        if field.scope == "role" and scoped_role_id is None:
            raise MissingUserField(provider.provider_id, field, role_id)
        value = self._storage.get_provider_user_value(provider.provider_id, key, scoped_role_id)
        if value is None:
            raise MissingUserField(provider.provider_id, field, scoped_role_id)
        return value

    async def _list_sessions_generic(self, provider: ProviderConfig) -> list[str]:
        endpoint = provider.endpoints.get("list_sessions") or {}
        path = endpoint.get("path")
        if not path:
            raise ValueError("list_sessions path is not configured")
        client = self._get_client(provider.provider_id)
        request_cfg = endpoint.get("request", {}) or {}
        headers_template = request_cfg.get("headers") or endpoint.get("headers")
        headers = self._render_template(headers_template or {}, {}, provider, None)
        self._logger.info(
            "LLM generic list_sessions provider=%s method=%s path=%s headers=%s",
            provider.provider_id,
            endpoint.get("method", "GET"),
            path,
            self._redact_dict(headers) if isinstance(headers, dict) else headers,
        )
        resp = await client.request(endpoint.get("method", "GET"), path, headers=headers or None)
        resp.raise_for_status()
        data = resp.json()
        response_cfg = endpoint.get("response", {}) or {}
        list_path = response_cfg.get("list_path")
        item_id_path = response_cfg.get("item_id_path")
        items = self._extract_path(data, list_path) if list_path else data
        if not isinstance(items, list):
            raise ValueError("list_sessions response is not a list")
        result: list[str] = []
        for item in items:
            if not item_id_path:
                result.append(str(item))
                continue
            value = self._extract_path(item, item_id_path)
            if value is not None:
                result.append(str(value))
        return result

    async def _create_session_generic(self, provider: ProviderConfig, role_id: int | None) -> str:
        endpoint = provider.endpoints.get("create_session") or {}
        path = endpoint.get("path")
        if not path:
            raise ValueError("create_session path is not configured")
        request_cfg = endpoint.get("request", {}) or {}
        body_template = request_cfg.get("body_template") or endpoint.get("body")
        headers_template = request_cfg.get("headers") or endpoint.get("headers")
        client = self._get_client(provider.provider_id)
        payload = self._render_template(body_template or {}, {}, provider, role_id)
        headers = self._render_template(headers_template or {}, {}, provider, role_id)
        self._logger.info(
            "LLM generic create_session provider=%s method=%s path=%s headers=%s payload=%s",
            provider.provider_id,
            endpoint.get("method", "POST"),
            path,
            self._redact_dict(headers) if isinstance(headers, dict) else headers,
            self._redact_dict(payload) if isinstance(payload, dict) else payload,
        )
        resp = await client.request(endpoint.get("method", "POST"), path, json=payload, headers=headers or None)
        resp.raise_for_status()
        data = resp.json()
        response_cfg = endpoint.get("response", {}) or {}
        session_id_path = response_cfg.get("session_id_path") or endpoint.get("response_session_id_field")
        session_id = self._extract_path(data, session_id_path)
        if not session_id:
            raise ValueError("create_session response missing session_id")
        return str(session_id)

    async def _rename_session_generic(
        self,
        provider: ProviderConfig,
        session_id: str,
        name: str,
        role_id: int | None,
    ) -> None:
        endpoint = provider.endpoints.get("rename_session") or {}
        path = endpoint.get("path")
        if not path:
            raise ValueError("rename_session path is not configured")
        client = self._get_client(provider.provider_id)
        request_cfg = endpoint.get("request", {}) or {}
        body_template = request_cfg.get("body_template") or endpoint.get("body")
        headers_template = request_cfg.get("headers") or endpoint.get("headers")
        payload = self._render_template(
            body_template or {},
            {"session_id": session_id, "name": name},
            provider,
            role_id,
        )
        headers = self._render_template(headers_template or {}, {"session_id": session_id, "name": name}, provider, role_id)
        self._logger.info(
            "LLM generic rename_session provider=%s method=%s path=%s headers=%s payload=%s",
            provider.provider_id,
            endpoint.get("method", "POST"),
            path,
            self._redact_dict(headers) if isinstance(headers, dict) else headers,
            self._redact_dict(payload) if isinstance(payload, dict) else payload,
        )
        resp = await client.request(
            endpoint.get("method", "POST"),
            path.format(session_id=session_id),
            json=payload,
            headers=headers or None,
        )
        resp.raise_for_status()

    async def _send_generic(
        self,
        provider: ProviderConfig,
        client: httpx.AsyncClient,
        session_id: str,
        content: str,
        model_id: str | None,
        role_id: int | None,
    ) -> str:
        endpoint = provider.endpoints.get("send_message") or {}
        path = endpoint.get("path")
        if not path:
            raise ValueError("send_message path is not configured")
        history: list[tuple[str, str]] = []
        if provider.history_enabled:
            history = self._storage.list_conversation_messages(session_id, limit=provider.history_limit)
        messages = [{"role": role, "content": text} for role, text in history]
        context = {
            "session_id": session_id,
            "content": content,
            "model": model_id,
            "messages": messages,
        }
        request_cfg = endpoint.get("request", {}) or {}
        body_template = request_cfg.get("body_template") or {}
        headers_template = request_cfg.get("headers") or endpoint.get("headers")
        payload = self._render_template(body_template, context, provider, role_id)
        method = endpoint.get("method", "POST")
        headers = self._render_template(headers_template or {}, context, provider, role_id)
        response_cfg = endpoint.get("response", {}) or {}
        if response_cfg.get("stream"):
            content_path = response_cfg.get("stream_content_path")
            done_path = response_cfg.get("stream_done_path")
            line_prefix = response_cfg.get("stream_line_prefix")
            done_value = response_cfg.get("stream_done_value")
            self._logger.info(
                "LLM generic send_message stream provider=%s method=%s path=%s headers=%s payload=%s",
                provider.provider_id,
                method,
                path,
                self._redact_dict(headers) if isinstance(headers, dict) else headers,
                self._redact_dict(payload) if isinstance(payload, dict) else payload,
            )
            parts: list[str] = []
            async with client.stream(
                method,
                path.format(session_id=session_id),
                json=payload,
                headers=headers or None,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line_prefix and line.startswith(line_prefix):
                        line = line[len(line_prefix):].strip()
                    if done_value is not None and line == done_value:
                        break
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = self._extract_path(data, content_path) if content_path else None
                    if chunk:
                        parts.append(str(chunk))
                    done = self._extract_path(data, done_path) if done_path else None
                    if done:
                        break
            result = "".join(parts).strip()
            if not result:
                raise ValueError("stream response empty")
            self._logger.info(
                "LLM generic response provider=%s chars=%s",
                provider.provider_id,
                len(result),
            )
            return result
        self._logger.info(
            "LLM generic send_message provider=%s method=%s path=%s headers=%s payload=%s",
            provider.provider_id,
            method,
            path,
            self._redact_dict(headers) if isinstance(headers, dict) else headers,
            self._redact_dict(payload) if isinstance(payload, dict) else payload,
        )
        resp = await client.request(
            method,
            path.format(session_id=session_id),
            json=payload,
            headers=headers or None,
        )
        resp.raise_for_status()
        data = resp.json()
        content_path = response_cfg.get("content_path")
        content_value = self._extract_path(data, content_path) if content_path else data
        if not content_value:
            raise ValueError("send_message response missing content")
        result = str(content_value)
        self._logger.info(
            "LLM generic response provider=%s chars=%s",
            provider.provider_id,
            len(result),
        )
        return result
