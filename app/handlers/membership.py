from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.runtime import RuntimeContext
from app.roles_registry import seed_group_roles
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
        storage.upsert_group(chat.id, chat.title)
        seed_group_roles(storage, chat.id)
    elif new_status in ("left", "kicked"):
        storage.set_group_active(chat.id, False)


async def handle_group_seen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    chat = update.effective_chat
    if chat.type == "private":
        return
    logger.info("group seen chat_id=%s title=%r", chat.id, chat.title)
    storage: Storage = runtime.storage
    storage.upsert_group(chat.id, chat.title)
    seed_group_roles(storage, chat.id)
