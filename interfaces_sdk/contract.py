from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol


EventType = Literal["message", "command", "callback", "membership", "system"]
ActionType = Literal["send_message", "edit_message", "ack", "request_input", "show_menu"]


@dataclass(frozen=True)
class InboundEvent:
    event_id: str
    interface_id: str
    channel_id: str
    actor_id: str
    actor_username: str | None
    event_type: EventType
    text: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    reply_to_event_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class OutboundAction:
    action_id: str
    action_type: ActionType
    target_channel_id: str
    target_actor_id: str | None
    text: str | None
    structured_payload: dict[str, Any] = field(default_factory=dict)
    correlation_event_id: str | None = None


class CorePort(Protocol):
    async def handle_event(self, event: InboundEvent) -> list[OutboundAction]:
        ...


class InterfaceAdapter(Protocol):
    interface_id: str

    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...
