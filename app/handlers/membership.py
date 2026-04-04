from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.runtime import RuntimeContext
from app.roles_registry import seed_team_roles
from app.storage import Storage

logger = logging.getLogger("bot")


async def handle_bot_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.my_chat_member or not update.effective_chat:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    chat = update.effective_chat
    if chat.type == "private":
        return
    new_status = update.my_chat_member.new_chat_member.status
    old_status = update.my_chat_member.old_chat_member.status
    storage: Storage = runtime.storage
    if new_status in ("member", "administrator") and old_status in ("left", "kicked"):
        with storage.transaction(immediate=True):
            team_id = storage.upsert_telegram_team_binding(chat.id, chat.title, is_active=True)
            seed_team_roles(storage, team_id)
    elif new_status in ("left", "kicked"):
        with storage.transaction(immediate=True):
            storage.set_telegram_team_binding_active(chat.id, False)


async def handle_group_seen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    chat = update.effective_chat
    if chat.type == "private":
        return
    logger.info("group seen chat_id=%s title=%r", chat.id, chat.title)
    storage: Storage = runtime.storage
    with storage.transaction(immediate=True):
        team_id = storage.upsert_telegram_team_binding(chat.id, chat.title, is_active=True)
        seed_team_roles(storage, team_id)
