from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping


class ErrorCode(StrEnum):
    STORAGE_NOT_FOUND = "storage.not_found"
    VALIDATION_INVALID_INPUT = "validation.invalid_input"
    AUTH_UNAUTHORIZED = "auth.unauthorized"
    CONFLICT_ALREADY_EXISTS = "conflict.already_exists"
    RUNTIME_BUSY_CONFLICT = "runtime.busy_conflict"
    RUNTIME_PENDING_EXISTS = "runtime.pending_exists"
    RUNTIME_REPLAY_FAILED = "runtime.replay_failed"
    INTERNAL_UNEXPECTED = "internal.unexpected"


_ERROR_HTTP_STATUS: dict[str, int] = {
    ErrorCode.STORAGE_NOT_FOUND.value: 404,
    ErrorCode.VALIDATION_INVALID_INPUT.value: 422,
    ErrorCode.AUTH_UNAUTHORIZED.value: 401,
    ErrorCode.CONFLICT_ALREADY_EXISTS.value: 409,
    ErrorCode.RUNTIME_BUSY_CONFLICT.value: 409,
    ErrorCode.RUNTIME_PENDING_EXISTS.value: 409,
    ErrorCode.RUNTIME_REPLAY_FAILED.value: 424,
    ErrorCode.INTERNAL_UNEXPECTED.value: 500,
}


def normalize_error_code(code: str | ErrorCode) -> str:
    return code.value if isinstance(code, ErrorCode) else str(code)


def resolve_http_status(code: str | ErrorCode) -> int:
    return _ERROR_HTTP_STATUS.get(normalize_error_code(code), 500)


def map_exception_to_error(
    exc: Exception,
    *,
    fallback_code: str | ErrorCode = ErrorCode.INTERNAL_UNEXPECTED,
    fallback_message: str | None = None,
    fallback_details: Mapping[str, Any] | None = None,
    retryable: bool = False,
) -> tuple[str, str, Mapping[str, Any] | None, int, bool]:
    message = str(exc)
    if isinstance(exc, ValueError):
        details: dict[str, Any] = dict(fallback_details or {})
        # Storage-origin not-found errors that must map to API-ready 404 contract.
        if message.startswith("Role not found:"):
            details.setdefault("entity", "role")
            details.setdefault("cause", "not_found")
            details.setdefault("id", message.split(":", 1)[1].strip())
            code = ErrorCode.STORAGE_NOT_FOUND
            return normalize_error_code(code), (fallback_message or message), details, resolve_http_status(code), retryable
        if message.startswith("Team role not found:"):
            details.setdefault("entity", "team_role")
            details.setdefault("cause", "not_found")
            details.setdefault("id", message.split(":", 1)[1].strip())
            code = ErrorCode.STORAGE_NOT_FOUND
            return normalize_error_code(code), (fallback_message or message), details, resolve_http_status(code), retryable
        if message.startswith("Telegram group binding not found:"):
            details.setdefault("entity", "team_binding")
            details.setdefault("cause", "not_found")
            details.setdefault("id", message.split(":", 1)[1].strip())
            code = ErrorCode.STORAGE_NOT_FOUND
            return normalize_error_code(code), (fallback_message or message), details, resolve_http_status(code), retryable

        code = ErrorCode.VALIDATION_INVALID_INPUT
        message = fallback_message or message or "Invalid input"
        details = details or None
        return normalize_error_code(code), message, details, resolve_http_status(code), retryable

    code = fallback_code
    message = fallback_message or message or "Unexpected error"
    details = fallback_details
    return normalize_error_code(code), message, details, resolve_http_status(code), retryable


__all__ = [
    "ErrorCode",
    "map_exception_to_error",
    "normalize_error_code",
    "resolve_http_status",
]
