from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, TypeVar

from app.application.contracts import ErrorCode, Result, to_api_error_payload
from app.application.observability import ensure_correlation_id, get_correlation_id

T = TypeVar("T")


@dataclass(frozen=True)
class ApiMappedError:
    status_code: int
    payload: dict[str, Any]


def map_result_error_to_api(result: Result[Any]) -> ApiMappedError:
    """Canonical mapper from application Result.error to API contract payload/status."""
    if not result.is_error or result.error is None:
        raise ValueError("map_result_error_to_api requires Result with error")
    payload = to_api_error_payload(result.error)
    details = dict(payload.get("details") or {})
    details["correlation_id"] = ensure_correlation_id(get_correlation_id())
    payload["details"] = details
    return ApiMappedError(status_code=int(result.error.http_status), payload=payload)


def map_exception_to_api_error(
    exc: Exception,
    *,
    fallback_code: str | ErrorCode = ErrorCode.INTERNAL_UNEXPECTED,
    fallback_message: str | None = None,
    fallback_details: Mapping[str, Any] | None = None,
    retryable: bool = False,
) -> ApiMappedError:
    result = Result[None].fail_from_exception(
        exc,
        fallback_code=fallback_code,
        fallback_message=fallback_message,
        fallback_details=fallback_details,
        retryable=retryable,
    )
    return map_result_error_to_api(result)
