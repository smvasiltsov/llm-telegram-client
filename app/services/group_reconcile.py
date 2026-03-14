from __future__ import annotations

import logging

from telegram import Bot
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut

from app.storage import Storage


logger = logging.getLogger("bot")


async def reconcile_active_groups(bot: Bot, storage: Storage) -> tuple[int, int]:
    bindings = storage.list_team_bindings(interface_type="telegram", active_only=True)
    checked = 0
    deactivated = 0
    for binding in bindings:
        try:
            chat_id = int(binding.external_id)
        except Exception:
            logger.warning("startup group check skipped invalid external_id=%r", binding.external_id)
            continue
        checked += 1
        try:
            member = await bot.get_chat_member(chat_id, bot.id)
            status = str(member.status)
            is_active_member = status in {
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
            }
            if not is_active_member:
                storage.set_telegram_team_binding_active(chat_id, False)
                deactivated += 1
                logger.info(
                    "startup group deactivated group_id=%s title=%r membership_status=%s",
                    chat_id,
                    binding.external_title,
                    status,
                )
                continue
            chat = await bot.get_chat(chat_id)
        except (Forbidden, BadRequest) as exc:
            storage.set_telegram_team_binding_active(chat_id, False)
            deactivated += 1
            logger.info(
                "startup group deactivated group_id=%s title=%r reason=%s",
                chat_id,
                binding.external_title,
                exc.__class__.__name__,
            )
            continue
        except (TimedOut, NetworkError) as exc:
            logger.warning(
                "startup group check skipped (temporary error) group_id=%s title=%r err=%s",
                chat_id,
                binding.external_title,
                exc.__class__.__name__,
            )
            continue
        except Exception:
            logger.exception(
                "startup group check failed group_id=%s title=%r",
                chat_id,
                binding.external_title,
            )
            continue

        storage.upsert_telegram_team_binding(chat.id, chat.title, is_active=True)

    logger.info("startup group reconcile checked=%s deactivated=%s", checked, deactivated)
    return checked, deactivated
