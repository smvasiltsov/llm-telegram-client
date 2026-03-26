from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import TYPE_CHECKING

from app.core.contracts.interface_io import CorePort, InterfaceAdapter
from app.core.errors.interface import InterfaceConfigError
from app.interfaces.runtime.config import InterfaceRuntimeConfig
from app.interfaces.runtime.loader import load_interface_adapter
from app.interfaces.runtime.registry import build_interface_descriptor

if TYPE_CHECKING:
    from app.runtime import RuntimeContext


@dataclass
class InterfaceRuntimeRunner:
    config: InterfaceRuntimeConfig
    runtime: RuntimeContext
    core_port: CorePort
    adapter_config: dict[str, Any] | None = None
    adapter: InterfaceAdapter | None = None

    def build(self) -> InterfaceAdapter:
        if self.config.runtime_mode != "single":
            raise InterfaceConfigError(f"Unsupported interface runtime mode: {self.config.runtime_mode}")
        descriptor = build_interface_descriptor(self.config.active_interface, self.config.modules_dir)
        self.adapter = load_interface_adapter(
            descriptor=descriptor,
            core_port=self.core_port,
            runtime=self.runtime,
            adapter_config=self.adapter_config,
        )
        return self.adapter

    async def start(self) -> None:
        adapter = self.adapter or self.build()
        await adapter.start()

    async def stop(self) -> None:
        if self.adapter is None:
            return
        await self.adapter.stop()
