from __future__ import annotations

import html
import re
from typing import Any

from telegram.constants import ParseMode
from telegram.error import BadRequest


def format_with_header(header: str | None, text: str) -> str:
    if not header:
        return html.escape(text)
    return f"<b>{html.escape(header)}</b>\n\n{html.escape(text)}"


def format_with_header_raw(header: str | None, text: str) -> str:
    if not header:
        return text
    return f"<b>{html.escape(header)}</b>\n\n{text}"


def _markdown_to_html_simple(text: str) -> str:
    escaped = html.escape(text)

    codeblocks: list[str] = []

    def _codeblock_repl(match: re.Match[str]) -> str:
        codeblocks.append(match.group(1))
        return f"__CODEBLOCK_{len(codeblocks) - 1}__"

    escaped = re.sub(r"```(?:[^\n]*)\n?(.*?)```", _codeblock_repl, escaped, flags=re.S)

    inline_codes: list[str] = []

    def _inline_code_repl(match: re.Match[str]) -> str:
        inline_codes.append(match.group(1))
        return f"__INLINECODE_{len(inline_codes) - 1}__"

    escaped = re.sub(r"`([^`]+)`", _inline_code_repl, escaped)

    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<b>\1</b>", escaped)
    escaped = re.sub(r"~~(.+?)~~", r"<s>\1</s>", escaped)
    escaped = re.sub(r"\*(.+?)\*", r"<i>\1</i>", escaped)
    escaped = re.sub(r"_(.+?)_", r"<i>\1</i>", escaped)

    for i, code in enumerate(inline_codes):
        escaped = escaped.replace(f"__INLINECODE_{i}__", f"<code>{code}</code>")

    for i, code in enumerate(codeblocks):
        escaped = escaped.replace(f"__CODEBLOCK_{i}__", f"<pre><code>{code}</code></pre>")

    return escaped


def render_llm_text(text: str, formatting_mode: str, allow_raw_html: bool) -> str:
    if formatting_mode == "markdown":
        return text
    if not allow_raw_html:
        return html.escape(text)
    return _markdown_to_html_simple(text)


async def send_formatted_with_fallback(
    bot: Any,
    chat_id: int,
    text: str,
    reply_to_message_id: int | None = None,
    reply_markup: Any | None = None,
    allow_raw_html: bool = True,
    formatting_mode: str = "html",
) -> None:
    mode = formatting_mode.lower()
    if mode == "markdown":
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup,
            )
        except BadRequest:
            await bot.send_message(
                chat_id=chat_id,
                text=html.escape(text),
                parse_mode=ParseMode.HTML,
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup,
            )
        return

    if not allow_raw_html:
        await bot.send_message(
            chat_id=chat_id,
            text=html.escape(text),
            parse_mode=ParseMode.HTML,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
        return

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
    except BadRequest:
        await bot.send_message(
            chat_id=chat_id,
            text=html.escape(text),
            parse_mode=ParseMode.HTML,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
