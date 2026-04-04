from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from telegram import Bot
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut

from app.storage import Storage


logger = logging.getLogger("bot")


@dataclass(frozen=True)
class ReconcileWrite:
    action: Literal["upsert_binding", "set_binding_active"]
    chat_id: int
    title: str | None = None
    is_active: bool = True


@dataclass(frozen=True)
class ReconcilePlan:
    checked: int
    deactivated: int
    writes: tuple[ReconcileWrite, ...]


async def build_reconcile_active_groups_plan(bot: Bot, storage: Storage) -> ReconcilePlan:
    bindings = storage.list_team_bindings(interface_type="telegram", active_only=True)
    checked = 0
    deactivated = 0
    writes: list[ReconcileWrite] = []
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
                writes.append(ReconcileWrite(action="set_binding_active", chat_id=chat_id, is_active=False))
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
            writes.append(ReconcileWrite(action="set_binding_active", chat_id=chat_id, is_active=False))
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

        writes.append(
            ReconcileWrite(
                action="upsert_binding",
                chat_id=int(chat.id),
                title=chat.title,
                is_active=True,
            )
        )

    return ReconcilePlan(checked=checked, deactivated=deactivated, writes=tuple(writes))


def apply_reconcile_active_groups_writes(storage: Storage, writes: tuple[ReconcileWrite, ...]) -> None:
    for write in writes:
        if write.action == "set_binding_active":
            storage.set_telegram_team_binding_active(write.chat_id, write.is_active)
            continue
        if write.action == "upsert_binding":
            storage.upsert_telegram_team_binding(write.chat_id, write.title, is_active=write.is_active)
            continue
        raise ValueError(f"Unsupported reconcile write action: {write.action}")


async def reconcile_active_groups(bot: Bot, storage: Storage) -> tuple[int, int]:
    plan = await build_reconcile_active_groups_plan(bot, storage)
    with storage.transaction(immediate=True):
        apply_reconcile_active_groups_writes(storage, plan.writes)
    logger.info("startup group reconcile checked=%s deactivated=%s", plan.checked, plan.deactivated)
    return plan.checked, plan.deactivated
