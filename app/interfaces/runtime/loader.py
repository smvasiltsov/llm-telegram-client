from __future__ import annotations

from importlib import import_module
from typing import Any
from typing import TYPE_CHECKING

from app.core.contracts.interface_io import CorePort, InterfaceAdapter
from app.core.errors.interface import InterfaceContractError, InterfaceLoadError
from app.interfaces.runtime.registry import InterfaceDescriptor

if TYPE_CHECKING:
    from app.runtime import RuntimeContext


def load_interface_adapter(
    *,
    descriptor: InterfaceDescriptor,
    core_port: CorePort,
    runtime: RuntimeContext,
    adapter_config: dict[str, Any] | None = None,
) -> InterfaceAdapter:
    try:
        module = import_module(descriptor.module_path)
    except Exception as exc:
        raise InterfaceLoadError(f"Failed to import interface module: {descriptor.module_path}") from exc

    factory = getattr(module, "create_adapter", None)
    if not callable(factory):
        raise InterfaceContractError(
            f"Interface module {descriptor.module_path} must expose callable create_adapter(...)"
        )

    adapter = factory(core_port=core_port, runtime=runtime, config=adapter_config or {})
    _validate_adapter(adapter, descriptor.interface_id)
    return adapter


def _validate_adapter(adapter: Any, expected_interface_id: str) -> None:
    if not hasattr(adapter, "start") or not callable(adapter.start):
        raise InterfaceContractError("Interface adapter must provide async start()")
    if not hasattr(adapter, "stop") or not callable(adapter.stop):
        raise InterfaceContractError("Interface adapter must provide async stop()")
    interface_id = getattr(adapter, "interface_id", None)
    if not isinstance(interface_id, str) or not interface_id.strip():
        raise InterfaceContractError("Interface adapter must provide non-empty interface_id")
    if interface_id.strip().lower() != expected_interface_id:
        raise InterfaceContractError(
            f"Interface adapter id mismatch: expected={expected_interface_id} got={interface_id}"
        )
