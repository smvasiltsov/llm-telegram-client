from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from uuid import uuid4

_MAX_ID_LEN = 128
_correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def _normalize_correlation_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized[:_MAX_ID_LEN]


def new_correlation_id() -> str:
    return uuid4().hex


def get_correlation_id() -> str | None:
    return _normalize_correlation_id(_correlation_id_var.get())


def set_correlation_id(correlation_id: str | None) -> str:
    normalized = _normalize_correlation_id(correlation_id)
    if normalized is None:
        normalized = new_correlation_id()
    _correlation_id_var.set(normalized)
    return normalized


def ensure_correlation_id(correlation_id: str | None = None) -> str:
    normalized = _normalize_correlation_id(correlation_id)
    if normalized is not None:
        _correlation_id_var.set(normalized)
        return normalized
    existing = get_correlation_id()
    if existing is not None:
        return existing
    generated = new_correlation_id()
    _correlation_id_var.set(generated)
    return generated


def clear_correlation_id() -> None:
    _correlation_id_var.set(None)


@contextmanager
def correlation_scope(correlation_id: str | None = None):
    target = _normalize_correlation_id(correlation_id) or get_correlation_id() or new_correlation_id()
    token: Token[str | None] = _correlation_id_var.set(target)
    try:
        yield target
    finally:
        _correlation_id_var.reset(token)


__all__ = [
    "clear_correlation_id",
    "correlation_scope",
    "ensure_correlation_id",
    "get_correlation_id",
    "new_correlation_id",
    "set_correlation_id",
]
