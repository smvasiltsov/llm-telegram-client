from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

DISPATCH_MODE_SINGLE_INSTANCE = "single-instance"
DISPATCH_MODE_SINGLE_RUNNER = "single-runner"
DISPATCH_MODE_STICKY = "sticky"
DISPATCH_MODE_EXTERNAL_QUEUE = "external-queue"


@dataclass(frozen=True)
class DispatchPolicyDecision:
    accepted: bool
    reason: str | None = None


class DispatchPolicy(Protocol):
    def can_dispatch(self, *, team_role_id: int, request_id: str) -> DispatchPolicyDecision: ...


class SingleInstanceDispatchPolicy:
    def can_dispatch(self, *, team_role_id: int, request_id: str) -> DispatchPolicyDecision:
        _ = (team_role_id, request_id)
        return DispatchPolicyDecision(accepted=True, reason="single_instance")


class SingleRunnerDispatchPolicy:
    def __init__(self, *, is_runner: bool) -> None:
        self._is_runner = bool(is_runner)

    def can_dispatch(self, *, team_role_id: int, request_id: str) -> DispatchPolicyDecision:
        _ = (team_role_id, request_id)
        if self._is_runner:
            return DispatchPolicyDecision(accepted=True, reason="runner")
        return DispatchPolicyDecision(accepted=False, reason="non_runner_instance")


class UnsupportedDispatchPolicy:
    def __init__(self, *, mode: str) -> None:
        self._mode = str(mode)

    def can_dispatch(self, *, team_role_id: int, request_id: str) -> DispatchPolicyDecision:
        _ = (team_role_id, request_id)
        return DispatchPolicyDecision(accepted=False, reason=f"unsupported_mode:{self._mode}")


def build_dispatch_policy(*, mode: str, is_runner: bool) -> DispatchPolicy:
    normalized = str(mode).strip().lower()
    if normalized == DISPATCH_MODE_SINGLE_INSTANCE:
        return SingleInstanceDispatchPolicy()
    if normalized == DISPATCH_MODE_SINGLE_RUNNER:
        return SingleRunnerDispatchPolicy(is_runner=is_runner)
    # Extension points for future milestones (LTC-50+):
    # - sticky instance-affinity routing
    # - external broker-backed queue orchestration
    return UnsupportedDispatchPolicy(mode=normalized or "unknown")


__all__ = [
    "DISPATCH_MODE_EXTERNAL_QUEUE",
    "DISPATCH_MODE_SINGLE_INSTANCE",
    "DISPATCH_MODE_SINGLE_RUNNER",
    "DISPATCH_MODE_STICKY",
    "DispatchPolicy",
    "DispatchPolicyDecision",
    "SingleInstanceDispatchPolicy",
    "SingleRunnerDispatchPolicy",
    "UnsupportedDispatchPolicy",
    "build_dispatch_policy",
]
