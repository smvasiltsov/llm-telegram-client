from __future__ import annotations

import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def build_plugin_reply_markup(
    reply_markup: Any | None,
    *,
    is_private: bool,
    logger: logging.Logger,
    log_ctx: dict[str, Any],
) -> Any | None:
    if not isinstance(reply_markup, dict) or reply_markup.get("type") != "web_app_button":
        return reply_markup

    button_text = str(reply_markup.get("text") or "Открыть полностью")
    url = str(reply_markup.get("url") or "")
    if not url:
        logger.info("plugin button skipped: empty url %s", log_ctx)
        return None
    if len(url) > 1000:
        logger.info("plugin button skipped: url too long len=%s %s", len(url), log_ctx)
        return None

    if is_private:
        logger.info("plugin button private web_app url_len=%s %s", len(url), log_ctx)
        return InlineKeyboardMarkup([[InlineKeyboardButton(text=button_text, web_app=WebAppInfo(url=url))]])

    logger.info("plugin button group url_len=%s %s", len(url), log_ctx)
    return InlineKeyboardMarkup([[InlineKeyboardButton(text=button_text, url=url)]])
