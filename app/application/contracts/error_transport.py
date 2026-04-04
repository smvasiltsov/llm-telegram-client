from __future__ import annotations

import logging
from typing import Any, Mapping

from .result import AppError


def to_api_error_payload(error: AppError) -> dict[str, Any]:
    """FastAPI-ready error payload shape (transport-agnostic)."""
    return {
        "code": error.code,
        "message": error.message,
        "details": dict(error.details or {}),
        "http_status": int(error.http_status),
        "retryable": bool(error.retryable),
    }


def to_telegram_message(error: AppError | None, fallback_message: str) -> str:
    """Telegram transport keeps existing UX text contract by default."""
    if error is None:
        return fallback_message
    return error.message or fallback_message


def log_structured_error(
    logger: logging.Logger,
    *,
    event: str,
    error: AppError | None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    payload = {
        "error_code": error.code if error else "internal.unexpected",
        "http_status": int(error.http_status) if error else 500,
        "retryable": bool(error.retryable) if error else False,
        "details": dict(error.details or {}) if error else {},
    }
    if extra:
        payload.update(dict(extra))
    logger.warning("%s %s", event, payload)


__all__ = [
    "log_structured_error",
    "to_api_error_payload",
    "to_telegram_message",
]
