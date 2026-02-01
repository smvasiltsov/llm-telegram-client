from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderModel:
    provider_id: str
    model_id: str
    label: str

    @property
    def full_id(self) -> str:
        return f"{self.provider_id}:{self.model_id}"

    @property
    def label_full(self) -> str:
        return f"{self.provider_id} / {self.label}"


@dataclass(frozen=True)
class ProviderUserField:
    key: str
    prompt: str
    scope: str


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    label: str
    base_url: str
    tls_ca_cert_path: str | None
    adapter: str
    capabilities: dict[str, bool]
    auth_mode: str
    endpoints: dict[str, Any]
    models: list[ProviderModel]
    history_enabled: bool
    history_limit: int | None
    user_fields: dict[str, ProviderUserField]


def _parse_provider_file(path: Path, logger: logging.Logger) -> ProviderConfig | None:
    try:
        raw = json.loads(path.read_text())
    except Exception:
        logger.exception("Failed to read provider config: %s", path)
        return None

    provider_id = str(raw.get("id", "")).strip()
    if not provider_id:
        logger.error("Provider config missing id: %s", path)
        return None
    label = str(raw.get("label", provider_id))
    base_url = str(raw.get("base_url", "")).strip()
    if not base_url:
        logger.error("Provider %s missing base_url", provider_id)
        return None

    tls = raw.get("tls", {}) or {}
    tls_ca_cert_path = tls.get("ca_cert_path")

    capabilities = raw.get("capabilities", {}) or {}
    auth = raw.get("auth", {}) or {}
    auth_mode = str(auth.get("mode", "none"))
    endpoints = raw.get("endpoints", {}) or {}
    adapter = str(raw.get("adapter", "generic"))

    models_raw = raw.get("models", []) or []
    user_fields_raw = raw.get("user_fields", {}) or {}
    user_fields: dict[str, ProviderUserField] = {}
    for key, value in user_fields_raw.items():
        if not isinstance(value, dict):
            continue
        prompt = str(value.get("prompt", "")).strip()
        scope = str(value.get("scope", "provider")).strip() or "provider"
        if scope not in {"provider", "role"}:
            logger.warning("Provider %s user_field %s has invalid scope %r, using provider", provider_id, key, scope)
            scope = "provider"
        if not prompt:
            continue
        user_fields[str(key)] = ProviderUserField(key=str(key), prompt=prompt, scope=scope)
    history_raw = raw.get("history", {}) or {}
    history_enabled = bool(history_raw.get("enabled", False))
    history_limit = history_raw.get("max_messages")
    if history_limit is not None:
        try:
            history_limit = int(history_limit)
        except (TypeError, ValueError):
            history_limit = None
    models: list[ProviderModel] = []
    for model in models_raw:
        model_id = str(model.get("id", "")).strip()
        if not model_id:
            logger.error("Provider %s has model without id in %s", provider_id, path)
            continue
        label_value = str(model.get("label", model_id))
        models.append(ProviderModel(provider_id=provider_id, model_id=model_id, label=label_value))

    return ProviderConfig(
        provider_id=provider_id,
        label=label,
        base_url=base_url,
        tls_ca_cert_path=tls_ca_cert_path,
        adapter=adapter,
        capabilities={str(k): bool(v) for k, v in capabilities.items()},
        auth_mode=auth_mode,
        endpoints=endpoints,
        models=models,
        history_enabled=history_enabled,
        history_limit=history_limit,
        user_fields=user_fields,
    )


def load_provider_registry(providers_dir: Path) -> tuple[dict[str, ProviderConfig], list[ProviderModel]]:
    logger = logging.getLogger("llm_providers")
    registry: dict[str, ProviderConfig] = {}
    models: list[ProviderModel] = []

    if not providers_dir.exists() or not providers_dir.is_dir():
        logger.info("Providers dir not found: %s", providers_dir)
        return registry, models

    for path in sorted(providers_dir.glob("*.json")):
        config = _parse_provider_file(path, logger)
        if not config:
            continue
        if config.provider_id in registry:
            logger.error("Duplicate provider id '%s' in %s", config.provider_id, path)
            continue
        registry[config.provider_id] = config
        models.extend(config.models)

    logger.info("Loaded providers=%s models=%s from %s", len(registry), len(models), providers_dir)
    return registry, models


def model_label(model: ProviderModel, provider: ProviderConfig | None) -> str:
    if provider and provider.label:
        return f"{provider.label} / {model.label}"
    return model.label_full
