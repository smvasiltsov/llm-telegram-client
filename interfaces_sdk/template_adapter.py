from __future__ import annotations

from typing import Any

from interfaces_sdk.contract import CorePort, InterfaceAdapter


class TemplateInterfaceAdapter(InterfaceAdapter):
    interface_id = "replace_me"

    def __init__(self, *, core_port: CorePort, runtime: Any, config: dict[str, Any]) -> None:
        self._core_port = core_port
        self._runtime = runtime
        self._config = config

    async def start(self) -> None:
        # Start transport client/listeners and forward incoming events to self._core_port.handle_event(...)
        return None

    async def stop(self) -> None:
        # Stop transport client/listeners and flush pending actions.
        return None


def create_adapter(*, core_port: CorePort, runtime: Any, config: dict[str, Any]) -> TemplateInterfaceAdapter:
    return TemplateInterfaceAdapter(core_port=core_port, runtime=runtime, config=config)
