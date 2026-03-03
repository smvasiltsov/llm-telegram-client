from __future__ import annotations

import logging

from telegram import Bot
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut

from app.storage import Storage


logger = logging.getLogger("bot")


async def reconcile_active_groups(bot: Bot, storage: Storage) -> tuple[int, int]:
    groups = storage.list_groups()
    checked = 0
    deactivated = 0
    for group in groups:
        checked += 1
        try:
            member = await bot.get_chat_member(group.group_id, bot.id)
            status = str(member.status)
            is_active_member = status in {
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
            }
            if not is_active_member:
                storage.set_group_active(group.group_id, False)
                deactivated += 1
                logger.info(
                    "startup group deactivated group_id=%s title=%r membership_status=%s",
                    group.group_id,
                    group.title,
                    status,
                )
                continue
            chat = await bot.get_chat(group.group_id)
        except (Forbidden, BadRequest) as exc:
            storage.set_group_active(group.group_id, False)
            deactivated += 1
            logger.info(
                "startup group deactivated group_id=%s title=%r reason=%s",
                group.group_id,
                group.title,
                exc.__class__.__name__,
            )
            continue
        except (TimedOut, NetworkError) as exc:
            logger.warning(
                "startup group check skipped (temporary error) group_id=%s title=%r err=%s",
                group.group_id,
                group.title,
                exc.__class__.__name__,
            )
            continue
        except Exception:
            logger.exception(
                "startup group check failed group_id=%s title=%r",
                group.group_id,
                group.title,
            )
            continue

        storage.upsert_group(chat.id, chat.title)

    logger.info("startup group reconcile checked=%s deactivated=%s", checked, deactivated)
    return checked, deactivated
