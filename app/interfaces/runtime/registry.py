from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InterfaceDescriptor:
    interface_id: str
    module_path: str


def build_interface_descriptor(active_interface: str, modules_dir: str) -> InterfaceDescriptor:
    interface_id = str(active_interface).strip().lower()
    if not interface_id:
        raise ValueError("active_interface must not be empty")
    modules_root = str(modules_dir).strip().strip(".")
    if not modules_root:
        modules_root = "interfaces"
    return InterfaceDescriptor(interface_id=interface_id, module_path=f"{modules_root}.{interface_id}.adapter")
