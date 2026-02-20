from __future__ import annotations

import logging
from typing import Any

from app.llm_providers import ProviderConfig

logger = logging.getLogger("bot")


def provider_id_from_model(
    model_override: str | None,
    default_provider_id: str,
    provider_registry: dict[str, ProviderConfig],
) -> str:
    if not model_override:
        return default_provider_id
    if ":" in model_override:
        return model_override.split(":", 1)[0]
    if model_override in provider_registry:
        return model_override
    return default_provider_id


def role_requires_auth(
    provider_registry: dict[str, ProviderConfig],
    model_override: str | None,
    default_provider_id: str,
) -> bool:
    provider_id = provider_id_from_model(model_override, default_provider_id, provider_registry)
    provider = provider_registry.get(provider_id)
    if not provider:
        return True
    return provider.auth_mode != "none"


def resolve_provider_model(
    provider_models: list,
    provider_model_map: dict[str, Any],
    provider_registry: dict[str, ProviderConfig],
    selected_model: str | None,
) -> str:
    if selected_model and selected_model in provider_model_map:
        return selected_model
    if selected_model and selected_model in provider_registry:
        return selected_model
    if selected_model:
        logger.warning("Provider model override not found in registry model=%s", selected_model)
    if not provider_models:
        raise ValueError("No provider models loaded")
    return provider_models[0].full_id


def build_llm_content(
    user_text: str,
    user_prompt_suffix: str | None,
    user_reply_prefix: str | None,
    reply_text: str | None,
) -> str:
    has_general = bool(user_prompt_suffix)
    has_reply = bool(reply_text)
    has_context_instr = bool(user_reply_prefix)
    if not has_general and not has_reply and not has_context_instr:
        return user_text

    parts: list[str] = []
    if has_general:
        parts.append("#GENERAL_INSTRUCTIONS")
        parts.append(user_prompt_suffix or "")
    if has_reply or has_context_instr:
        parts.append("#CONTEXT_INSTRUCTIONS")
        if user_reply_prefix:
            parts.append(user_reply_prefix)
        if reply_text:
            parts.append("#CONTEXT")
            parts.append(reply_text)
    parts.append("#USER_REQUEST")
    parts.append(user_text)
    return "\n\n".join(part for part in parts if part).strip()
