from app.interfaces.runtime.config import InterfaceRuntimeConfig

__all__ = [
    "InterfaceRuntimeConfig",
    "InterfaceRuntimeRunner",
]


def __getattr__(name: str):
    if name == "InterfaceRuntimeRunner":
        from app.interfaces.runtime.runner import InterfaceRuntimeRunner

        return InterfaceRuntimeRunner
    raise AttributeError(name)
