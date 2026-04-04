from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActorRef:
    user_id: int
    username: str | None = None


@dataclass(frozen=True)
class ChatRef:
    chat_id: int
    chat_type: str
    title: str | None = None


@dataclass(frozen=True)
class MessageRef:
    chat_id: int
    message_id: int
    user_id: int
    text: str
    reply_text: str | None = None


@dataclass(frozen=True)
class GroupDispatchRequest:
    team_id: int
    chat_id: int
    user_id: int
    session_token: str
    role_ids: tuple[int, ...]
    user_text: str
    reply_to_message_id: int
    actor_username: str
    chain_origin: str
    reply_text: str | None = None
    is_all: bool = False


@dataclass(frozen=True)
class PrivateFieldSubmitRequest:
    user_id: int
    chat_id: int
    message_id: int
    text: str


@dataclass(frozen=True)
class CallbackActionRequest:
    user_id: int
    chat_id: int
    data: str
    message_id: int | None = None
