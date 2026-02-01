from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.models import Role
from app.utils import extract_role_mentions, strip_bot_mention


@dataclass(frozen=True)
class RouteResult:
    roles: list[Role]
    content: str
    is_all: bool


def route_message(
    text: str,
    bot_username: str,
    roles: Iterable[Role],
    *,
    owner_user_id: int,
    author_user_id: int,
    require_bot_mention: bool = True,
) -> RouteResult | None:
    if author_user_id != owner_user_id:
        return None
    if require_bot_mention and f"@{bot_username.lower()}" not in text.lower():
        return None

    roles_list = list(roles)
    role_map = {role.role_name.lower(): role for role in roles_list}
    cleaned = strip_bot_mention(text, bot_username)

    is_all = "@all" in cleaned.lower()
    if is_all:
        cleaned = cleaned.replace("@all", "").strip()
        return RouteResult(roles=roles_list, content=cleaned, is_all=True)

    mentioned = extract_role_mentions(cleaned, set(role_map.keys()))
    if mentioned:
        role = role_map[mentioned[0].lower()]
        cleaned = cleaned.replace(f"@{role.role_name}", "", 1).strip()
        return RouteResult(roles=[role], content=cleaned, is_all=False)

    # No explicit role -> no route
    return None
