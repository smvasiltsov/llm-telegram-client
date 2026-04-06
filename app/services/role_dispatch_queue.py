from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from time import monotonic

from app.application.contracts import NoopMetricsPort
from app.services.dispatch_policy import (
    DispatchPolicy,
    build_dispatch_policy,
)


@dataclass(frozen=True)
class QueueGrant:
    team_role_id: int
    request_id: str
    queued: bool
    queue_position: int
    wait_ms: int
    accepted: bool = True
    reason: str | None = None


class DispatchPolicyRejectedError(RuntimeError):
    def __init__(self, *, mode: str, is_runner: bool, reason: str | None = None) -> None:
        self.mode = str(mode)
        self.is_runner = bool(is_runner)
        self.reason = reason or "dispatch_rejected"
        super().__init__(
            f"Dispatch rejected by policy: mode={self.mode} is_runner={int(self.is_runner)} reason={self.reason}"
        )


@dataclass
class _QueueEntry:
    request_id: str
    enqueued_at: float
    wakeup: asyncio.Future[None]


@dataclass
class _RoleQueueState:
    lock: asyncio.Lock
    active_request_id: str | None
    waiting: deque[_QueueEntry]


class RoleDispatchQueueService:
    def __init__(
        self,
        *,
        dispatch_mode: str = "single-instance",
        dispatch_is_runner: bool = True,
        metrics_port: object | None = None,
        queue_name: str = "role_dispatch",
    ) -> None:
        self._states: dict[int, _RoleQueueState] = {}
        self._states_lock = asyncio.Lock()
        self._dispatch_mode = str(dispatch_mode)
        self._dispatch_is_runner = bool(dispatch_is_runner)
        self._queue_name = str(queue_name)
        self._metrics = metrics_port if hasattr(metrics_port, "observe_ms") else NoopMetricsPort()
        self._dispatch_policy: DispatchPolicy = build_dispatch_policy(
            mode=self._dispatch_mode,
            is_runner=self._dispatch_is_runner,
        )

    @property
    def dispatch_mode(self) -> str:
        return self._dispatch_mode

    @property
    def dispatch_is_runner(self) -> bool:
        return self._dispatch_is_runner

    async def _state(self, team_role_id: int) -> _RoleQueueState:
        async with self._states_lock:
            state = self._states.get(team_role_id)
            if state is None:
                state = _RoleQueueState(lock=asyncio.Lock(), active_request_id=None, waiting=deque())
                self._states[team_role_id] = state
            return state

    async def acquire_execution_slot(self, *, team_role_id: int, request_id: str) -> QueueGrant:
        decision = self._dispatch_policy.can_dispatch(team_role_id=team_role_id, request_id=request_id)
        if not decision.accepted:
            return QueueGrant(
                team_role_id=team_role_id,
                request_id=request_id,
                accepted=False,
                reason=decision.reason,
                queued=False,
                queue_position=0,
                wait_ms=0,
            )
        state = await self._state(team_role_id)
        enqueued_at = monotonic()
        wakeup: asyncio.Future[None] | None = None
        position = 0

        async with state.lock:
            if state.active_request_id is None and not state.waiting:
                state.active_request_id = request_id
                self._emit_queue_depth(len(state.waiting))
                return QueueGrant(
                    team_role_id=team_role_id,
                    request_id=request_id,
                    accepted=True,
                    reason=decision.reason,
                    queued=False,
                    queue_position=0,
                    wait_ms=0,
                )

            wakeup = asyncio.get_running_loop().create_future()
            state.waiting.append(_QueueEntry(request_id=request_id, enqueued_at=enqueued_at, wakeup=wakeup))
            position = len(state.waiting)
            self._emit_queue_depth(position)

        try:
            await wakeup
        except asyncio.CancelledError:
            async with state.lock:
                state.waiting = deque(entry for entry in state.waiting if entry.request_id != request_id)
                self._emit_queue_depth(len(state.waiting))
            raise

        wait_ms = int(max(0.0, (monotonic() - enqueued_at) * 1000.0))
        return QueueGrant(
            team_role_id=team_role_id,
            request_id=request_id,
            accepted=True,
            reason=decision.reason,
            queued=True,
            queue_position=position,
            wait_ms=wait_ms,
        )

    async def release_execution_slot(self, *, team_role_id: int, request_id: str) -> bool:
        state = await self._state(team_role_id)
        to_wakeup: asyncio.Future[None] | None = None
        released = False

        async with state.lock:
            if state.active_request_id != request_id:
                return False

            released = True
            if state.waiting:
                next_entry = state.waiting.popleft()
                state.active_request_id = next_entry.request_id
                to_wakeup = next_entry.wakeup
            else:
                state.active_request_id = None
            self._emit_queue_depth(len(state.waiting))

        if to_wakeup is not None and not to_wakeup.done():
            to_wakeup.set_result(None)
        return released

    async def queue_size(self, *, team_role_id: int) -> int:
        state = await self._state(team_role_id)
        async with state.lock:
            return len(state.waiting)

    def _emit_queue_depth(self, depth: int) -> None:
        self._metrics.observe_ms(
            "runtime_queue_depth",
            value_ms=float(max(0, int(depth))),
            labels={"queue_name": self._queue_name},
        )
