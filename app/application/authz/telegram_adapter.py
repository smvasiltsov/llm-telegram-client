from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .contracts import AuthzAction, AuthzActor, AuthzResourceContext

if TYPE_CHECKING:
    from telegram import CallbackQuery, Update


def action_for_private_owner_command() -> AuthzAction:
    return AuthzAction.TELEGRAM_COMMANDS_ADMIN


def action_for_callback_admin() -> AuthzAction:
    return AuthzAction.TELEGRAM_CALLBACKS_ADMIN


def action_for_bootstrap_admin() -> AuthzAction:
    return AuthzAction.TELEGRAM_BOOTSTRAP_ADMIN


def actor_from_update(update: Any) -> AuthzActor | None:
    user = update.effective_user
    if user is None:
        return None
    return AuthzActor(user_id=int(user.id))


def actor_from_callback(query: Any) -> AuthzActor | None:
    user = query.from_user
    if user is None:
        return None
    return AuthzActor(user_id=int(user.id))


def resource_ctx_from_update(update: Any) -> AuthzResourceContext:
    chat = update.effective_chat
    if chat is None:
        return AuthzResourceContext()
    return AuthzResourceContext(group_id=int(chat.id))


def resource_ctx_from_callback(query: Any) -> AuthzResourceContext:
    msg = query.message
    if msg is None or msg.chat is None:
        return AuthzResourceContext()
    return AuthzResourceContext(group_id=int(msg.chat.id))
