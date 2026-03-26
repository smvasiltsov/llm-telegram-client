from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models import TeamRoleRuntimeStatus
from app.storage import Storage

ALLOWED_PREVIEW_SOURCES = {"user", "skill_engine"}
DEFAULT_BUSY_LEASE_SECONDS = 300
MAX_PREVIEW_LEN = 100


@dataclass(frozen=True)
class BusyAcquireResult:
    acquired: bool
    status: TeamRoleRuntimeStatus | None
    blockers: list[TeamRoleRuntimeStatus]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_spaces(value: str) -> str:
    return " ".join(value.split())


def _extract_text_fields(value: Any, *, source: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(_extract_text_fields(item, source=source))
        return parts
    if not isinstance(value, dict):
        return []

    blocked_tokens = {"system", "instruction"}
    if source == "skill_engine":
        preferred_keys = ("summary", "text", "message", "result", "output", "error")
    else:
        preferred_keys = ("user_text", "text", "message", "content", "query")

    parts: list[str] = []
    for key in preferred_keys:
        if key in value and not any(token in key for token in blocked_tokens):
            parts.extend(_extract_text_fields(value.get(key), source=source))
    return parts


class RoleRuntimeStatusService:
    def __init__(
        self,
        storage: Storage,
        *,
        busy_lease_seconds: int = DEFAULT_BUSY_LEASE_SECONDS,
        free_transition_delay_sec: int = 0,
    ) -> None:
        self._storage = storage
        self._busy_lease_seconds = max(30, int(busy_lease_seconds))
        self._free_transition_delay_sec = max(0, int(free_transition_delay_sec))

    def sanitize_preview(self, text: str | None, *, source: str) -> str | None:
        raw = (text or "").strip()
        if not raw:
            return None
        normalized_source = source if source in ALLOWED_PREVIEW_SOURCES else "user"
        body = raw
        for prefix in ("INPUT_JSON:", "SKILL_RESULT:"):
            if body.startswith(prefix):
                body = body[len(prefix) :].strip()
                break

        preview = body
        if body.startswith("{") or body.startswith("["):
            try:
                payload = json.loads(body)
            except Exception:
                payload = None
            if payload is not None:
                chunks = _extract_text_fields(payload, source=normalized_source)
                if chunks:
                    preview = " ".join(chunks)
                else:
                    preview = ""

        preview = _normalize_spaces(preview).replace("{", "").replace("}", "")
        if not preview:
            return None
        if len(preview) <= MAX_PREVIEW_LEN:
            return preview
        return preview[:MAX_PREVIEW_LEN]

    def acquire_busy(
        self,
        *,
        team_role_id: int,
        busy_request_id: str,
        busy_owner_user_id: int | None,
        busy_origin: str | None,
        preview_text: str | None,
        preview_source: str = "user",
    ) -> BusyAcquireResult:
        now_dt = _utc_now()
        lease_until = now_dt + timedelta(seconds=self._busy_lease_seconds)
        sanitized_preview = self.sanitize_preview(preview_text, source=preview_source)
        ok, status, blockers = self._storage.try_acquire_team_role_busy(
            team_role_id,
            busy_request_id=busy_request_id,
            busy_owner_user_id=busy_owner_user_id,
            busy_origin=busy_origin,
            preview_text=sanitized_preview,
            preview_source=preview_source if preview_source in ALLOWED_PREVIEW_SOURCES else "user",
            busy_since=now_dt.isoformat(),
            lease_expires_at=lease_until.isoformat(),
            free_transition_delay_sec=self._free_transition_delay_sec,
            now=now_dt.isoformat(),
        )
        return BusyAcquireResult(acquired=ok, status=status, blockers=blockers)

    def release_busy(self, *, team_role_id: int, release_reason: str) -> TeamRoleRuntimeStatus:
        if self._free_transition_delay_sec <= 0:
            return self._storage.mark_team_role_runtime_free(team_role_id, release_reason=release_reason)
        now_dt = _utc_now()
        delay_until = now_dt + timedelta(seconds=self._free_transition_delay_sec)
        return self._storage.mark_team_role_runtime_release_requested(
            team_role_id,
            release_reason=release_reason,
            requested_at=now_dt.isoformat(),
            delay_until=delay_until.isoformat(),
        )

    def heartbeat_busy(self, *, team_role_id: int) -> None:
        now_dt = _utc_now()
        lease_until = now_dt + timedelta(seconds=self._busy_lease_seconds)
        self._storage.heartbeat_team_role_runtime_status(
            team_role_id,
            lease_expires_at=lease_until.isoformat(),
            now=now_dt.isoformat(),
        )

    def update_preview(self, *, team_role_id: int, preview_text: str | None, preview_source: str = "user") -> None:
        sanitized_preview = self.sanitize_preview(preview_text, source=preview_source)
        self._storage.update_team_role_runtime_preview(
            team_role_id,
            preview_text=sanitized_preview,
            preview_source=preview_source if preview_source in ALLOWED_PREVIEW_SOURCES else "user",
        )

    def get_status(self, *, team_role_id: int) -> TeamRoleRuntimeStatus:
        self.finalize_due_releases()
        status = self._storage.get_team_role_runtime_status(team_role_id)
        if status is None:
            status = self._storage.ensure_team_role_runtime_status(team_role_id)
        return status

    def list_team_statuses(self, *, team_id: int, active_only: bool = True) -> list[TeamRoleRuntimeStatus]:
        self.finalize_due_releases()
        return self._storage.list_team_role_runtime_statuses(team_id, active_only=active_only)

    def cleanup_stale(self) -> int:
        stale_cleaned = self._storage.cleanup_stale_busy_team_roles(
            free_transition_delay_sec=self._free_transition_delay_sec
        )
        delayed_cleaned = self.finalize_due_releases()
        return stale_cleaned + delayed_cleaned

    def finalize_due_releases(self, *, now: str | None = None, limit: int = 100) -> int:
        return self._storage.finalize_due_team_role_runtime_releases(now=now, limit=limit)
