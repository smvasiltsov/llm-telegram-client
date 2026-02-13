from __future__ import annotations

import importlib.util
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


HookFn = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], Optional[dict[str, Any]]]


@dataclass(frozen=True)
class PluginSpec:
    plugin_id: str
    plugin_type: str
    hooks: dict[str, HookFn]
    config: dict[str, Any]


class PluginManager:
    def __init__(self, plugins: list[PluginSpec]) -> None:
        self._plugins = plugins
        self._logger = logging.getLogger("plugins")

    @property
    def plugins(self) -> list[PluginSpec]:
        return list(self._plugins)

    def apply_postprocess(self, payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        current = dict(payload)
        for plugin in self._plugins:
            if plugin.plugin_type != "postprocess":
                continue
            hook = plugin.hooks.get("on_llm_response")
            if not hook:
                continue
            try:
                result = hook(dict(current), dict(ctx), dict(plugin.config))
            except Exception:
                self._logger.exception("Plugin failed id=%s hook=on_llm_response", plugin.plugin_id)
                continue
            if result is None:
                continue
            if not isinstance(result, dict):
                self._logger.warning("Plugin id=%s returned non-dict result", plugin.plugin_id)
                continue
            if "text" not in result:
                self._logger.warning("Plugin id=%s returned result without text", plugin.plugin_id)
                continue
            before_len = len(str(current.get("text", "")))
            after_len = len(str(result.get("text", "")))
            has_markup = bool(result.get("reply_markup"))
            self._logger.info(
                "Plugin applied id=%s text_len=%s->%s reply_markup=%s",
                plugin.plugin_id,
                before_len,
                after_len,
                has_markup,
            )
            current = result
        return current


def _load_plugin_module(path: Path) -> Any | None:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_plugins(plugins_dir: str | Path) -> PluginManager:
    logger = logging.getLogger("plugins")
    base = Path(plugins_dir)
    plugins: list[PluginSpec] = []
    if not base.exists():
        logger.info("Plugins directory not found: %s", base)
        return PluginManager([])
    for py_path in sorted(base.glob("*.py")):
        if py_path.name.startswith("_"):
            continue
        module = _load_plugin_module(py_path)
        if not module or not hasattr(module, "register"):
            logger.warning("Plugin missing register(): %s", py_path.name)
            continue
        register = getattr(module, "register")
        try:
            meta = register()
        except Exception:
            logger.exception("Plugin register failed: %s", py_path.name)
            continue
        if not isinstance(meta, dict):
            logger.warning("Plugin register returned non-dict: %s", py_path.name)
            continue
        plugin_id = str(meta.get("id") or py_path.stem)
        plugin_type = str(meta.get("type") or "postprocess")
        hooks = meta.get("hooks") if isinstance(meta.get("hooks"), dict) else {}

        config_path = py_path.with_suffix(".json")
        config: dict[str, Any] = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("Failed to load plugin config: %s", config_path.name)
                config = {}

        enabled = config.get("enabled", True)
        if enabled is False:
            logger.info("Plugin disabled: %s", plugin_id)
            continue

        plugins.append(
            PluginSpec(
                plugin_id=plugin_id,
                plugin_type=plugin_type,
                hooks=hooks,
                config=config,
            )
        )
    logger.info("Loaded plugins=%s from %s", len(plugins), base)
    return PluginManager(plugins)
