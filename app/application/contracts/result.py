from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Mapping, TypeVar

from .errors import ErrorCode, map_exception_to_error, normalize_error_code, resolve_http_status

T = TypeVar("T")


@dataclass(frozen=True)
class AppError:
    """Unified error object for application-layer use-cases."""

    code: str
    message: str
    details: Mapping[str, Any] | None = None
    http_status: int = 500
    retryable: bool = False


@dataclass(frozen=True)
class Result(Generic[T]):
    """Use-case result container without transport dependencies."""

    value: T | None = None
    error: AppError | None = None

    @property
    def is_ok(self) -> bool:
        return self.error is None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    @classmethod
    def ok(cls, value: T) -> "Result[T]":
        return cls(value=value, error=None)

    @classmethod
    def fail(
        cls,
        code: str | ErrorCode,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        http_status: int | None = None,
        retryable: bool = False,
    ) -> "Result[T]":
        normalized_code = normalize_error_code(code)
        status = int(http_status) if http_status is not None else resolve_http_status(normalized_code)
        return cls(
            value=None,
            error=AppError(
                code=normalized_code,
                message=message,
                details=details,
                http_status=status,
                retryable=retryable,
            ),
        )

    @classmethod
    def fail_from_exception(
        cls,
        exc: Exception,
        *,
        fallback_code: str | ErrorCode = ErrorCode.INTERNAL_UNEXPECTED,
        fallback_message: str | None = None,
        fallback_details: Mapping[str, Any] | None = None,
        retryable: bool = False,
    ) -> "Result[T]":
        code, message, details, http_status, retry = map_exception_to_error(
            exc,
            fallback_code=fallback_code,
            fallback_message=fallback_message,
            fallback_details=fallback_details,
            retryable=retryable,
        )
        return cls.fail(
            code,
            message,
            details=details,
            http_status=http_status,
            retryable=retry,
        )
