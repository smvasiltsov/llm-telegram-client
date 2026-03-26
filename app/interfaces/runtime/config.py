from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InterfaceRuntimeConfig:
    active_interface: str
    modules_dir: str
    runtime_mode: str
