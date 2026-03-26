from __future__ import annotations

from importlib import import_module
from typing import Any


def validate_adapter_contract(module_path: str, expected_interface_id: str) -> list[str]:
    errors: list[str] = []
    try:
        module = import_module(module_path)
    except Exception as exc:
        return [f"import_error:{exc}"]

    factory = getattr(module, "create_adapter", None)
    if not callable(factory):
        return ["missing_factory:create_adapter"]

    class _CorePort:
        async def handle_event(self, event: object):
            return []

    try:
        adapter = factory(core_port=_CorePort(), runtime=object(), config={})
    except Exception as exc:
        return [f"factory_error:{exc}"]

    if not hasattr(adapter, "start") or not callable(adapter.start):
        errors.append("missing_method:start")
    if not hasattr(adapter, "stop") or not callable(adapter.stop):
        errors.append("missing_method:stop")
    interface_id = getattr(adapter, "interface_id", None)
    if not isinstance(interface_id, str) or not interface_id.strip():
        errors.append("invalid_interface_id")
    elif interface_id.strip().lower() != expected_interface_id.strip().lower():
        errors.append(f"interface_id_mismatch:expected={expected_interface_id} actual={interface_id}")
    return errors
