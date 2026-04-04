from __future__ import annotations

from typing import Any, Protocol


class StoragePort(Protocol):
    """Port for storage operations used by application use-cases."""


class RolePipelinePort(Protocol):
    """Port for role pipeline orchestration.

    NOTE: keep transport-agnostic signatures; no Telegram Update/Context types.
    """

    async def run_chain(self, **kwargs: Any) -> None: ...

    def roles_require_auth(self, **kwargs: Any) -> bool: ...


class RuntimeStatusPort(Protocol):
    """Port for runtime busy/free state operations."""


class QueuePort(Protocol):
    """Port for role dispatch queue operations."""


class PendingPort(Protocol):
    """Port for pending message/field state operations."""


# TODO(LTC-42): introduce transaction boundary / unit-of-work abstractions
# for multi-step use-cases before write API rollout (LTC-36 recommendations).
