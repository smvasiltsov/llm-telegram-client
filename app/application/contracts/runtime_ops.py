from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .result import Result


class RuntimeOperation(StrEnum):
    RUN_CHAIN = "runtime.run_chain"
    DISPATCH_MENTIONS = "runtime.dispatch_mentions"
    ORCHESTRATOR_POST_EVENT = "runtime.orchestrator_post_event"
    PENDING_REPLAY = "runtime.pending_replay"


class RuntimeState(StrEnum):
    QUEUED = "queued"
    BUSY = "busy"
    PENDING = "pending"
    FREE = "free"


@dataclass(frozen=True)
class RuntimeTransition:
    operation: str
    trigger: str
    from_state: str
    to_state: str
    team_role_id: int | None
    request_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RuntimeOperationRequest:
    operation: str
    team_id: int
    team_role_id: int | None
    user_id: int
    chat_id: int
    request_id: str
    trigger: str
    role_name: str | None = None
    pending_message_id: int | None = None


@dataclass(frozen=True)
class RuntimeOperationResult:
    operation: str
    request_id: str
    completed: bool
    queued: bool
    busy_acquired: bool
    pending_saved: bool
    replay_scheduled: bool
    transitions: tuple[RuntimeTransition, ...]


class RuntimeOrchestrationPort(Protocol):
    async def run(self, request: RuntimeOperationRequest) -> Result[RuntimeOperationResult]: ...

