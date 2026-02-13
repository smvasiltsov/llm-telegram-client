# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse



def generate_mini_app_url(
    text_id: str,
    web_app_url: str,
    id_param: str = "id",
    extra_query: dict[str, str] | None = None,
) -> str:
    if not text_id:
        raise ValueError("text_id не может быть пустым.")
    is_local = web_app_url.startswith("http://localhost") or web_app_url.startswith("http://127.0.0.1")
    is_http = web_app_url.startswith("http://")
    is_https = web_app_url.startswith("https://")
    if not (is_local or is_http or is_https):
        raise ValueError(
            "URL веб-приложения должен начинаться с 'https://' (или 'http://localhost' для тестов)."
        )
    parsed = urlparse(web_app_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[id_param] = text_id
    if extra_query:
        query.update(extra_query)
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _find_code_blocks(text: str) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    fence = "```"
    i = 0
    while True:
        start = text.find(fence, i)
        if start == -1:
            break
        end = text.find(fence, start + len(fence))
        if end == -1:
            break
        end += len(fence)
        blocks.append((start, end))
        i = end
    return blocks


def _safe_cut_index(text: str, limit: int) -> int:
    if len(text) <= limit:
        return len(text)
    cut = limit
    for start, end in _find_code_blocks(text):
        if start < cut < end:
            return max(0, start)
    return cut


def on_llm_response(payload: dict[str, Any], ctx: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    logger = logging.getLogger("plugins.markdown_answers")
    text = str(payload.get("text") or "")
    if not text:
        return payload

    web_app_url = str(config.get("web_app_url") or "").strip()
    if not web_app_url:
        logger.info("skip: web_app_url is empty text_len=%s", len(text))
        return payload

    max_inline_chars = int(config.get("max_inline_chars", 3500))
    min_chars_for_button = int(config.get("min_chars_for_button", 1200))
    if min_chars_for_button > max_inline_chars:
        logger.info(
            "adjust: min_chars_for_button=%s > max_inline_chars=%s",
            min_chars_for_button,
            max_inline_chars,
        )
        min_chars_for_button = max_inline_chars

    if len(text) <= max_inline_chars:
        logger.info(
            "skip: text_len=%s <= max_inline_chars=%s",
            len(text),
            max_inline_chars,
        )
        return payload

    limit = max_inline_chars
    cut = _safe_cut_index(text, limit)
    if cut <= 0:
        cut = min(limit, len(text))

    first_text = text[:cut].rstrip()
    if len(first_text) < min_chars_for_button:
        logger.info(
            "skip: first_text_len=%s < min_chars_for_button=%s",
            len(first_text),
            min_chars_for_button,
        )
        return payload

    store_text = ctx.get("store_text")
    if not callable(store_text):
        logger.info("skip: store_text missing text_len=%s", len(text))
        return payload
    try:
        text_id = str(store_text("markdown_answers", text))
    except Exception:
        logger.exception("store_text failed")
        return payload

    id_param = str(config.get("id_query_param") or "id")
    api_base_url = str(config.get("api_base_url") or "").strip()
    extra_query = {"api_base": api_base_url} if api_base_url else None
    url = generate_mini_app_url(text_id, web_app_url, id_param=id_param, extra_query=extra_query)
    logger.info(
        "apply: text_len=%s first_len=%s url_len=%s",
        len(text),
        len(first_text),
        len(url),
    )
    return {
        "text": first_text,
        "parse_mode": payload.get("parse_mode"),
        "reply_markup": {
            "type": "web_app_button",
            "text": str(config.get("button_text") or "Открыть полностью"),
            "url": url,
        },
    }


def register() -> dict[str, Any]:
    return {
        "id": "markdown_answers",
        "type": "postprocess",
        "version": "1.0",
        "hooks": {
            "on_llm_response": on_llm_response,
        },
    }
