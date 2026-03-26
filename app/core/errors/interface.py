from __future__ import annotations


class InterfaceRuntimeError(RuntimeError):
    pass


class InterfaceConfigError(InterfaceRuntimeError):
    pass


class InterfaceLoadError(InterfaceRuntimeError):
    pass


class InterfaceContractError(InterfaceRuntimeError):
    pass
