from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class QueueGrant:
    team_role_id: int
    request_id: str
    queued: bool
    queue_position: int
    wait_ms: int


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
    def __init__(self) -> None:
        self._states: dict[int, _RoleQueueState] = {}
        self._states_lock = asyncio.Lock()

    async def _state(self, team_role_id: int) -> _RoleQueueState:
        async with self._states_lock:
            state = self._states.get(team_role_id)
            if state is None:
                state = _RoleQueueState(lock=asyncio.Lock(), active_request_id=None, waiting=deque())
                self._states[team_role_id] = state
            return state

    async def acquire_execution_slot(self, *, team_role_id: int, request_id: str) -> QueueGrant:
        state = await self._state(team_role_id)
        enqueued_at = monotonic()
        wakeup: asyncio.Future[None] | None = None
        position = 0

        async with state.lock:
            if state.active_request_id is None and not state.waiting:
                state.active_request_id = request_id
                return QueueGrant(
                    team_role_id=team_role_id,
                    request_id=request_id,
                    queued=False,
                    queue_position=0,
                    wait_ms=0,
                )

            wakeup = asyncio.get_running_loop().create_future()
            state.waiting.append(_QueueEntry(request_id=request_id, enqueued_at=enqueued_at, wakeup=wakeup))
            position = len(state.waiting)

        try:
            await wakeup
        except asyncio.CancelledError:
            async with state.lock:
                state.waiting = deque(entry for entry in state.waiting if entry.request_id != request_id)
            raise

        wait_ms = int(max(0.0, (monotonic() - enqueued_at) * 1000.0))
        return QueueGrant(
            team_role_id=team_role_id,
            request_id=request_id,
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

        if to_wakeup is not None and not to_wakeup.done():
            to_wakeup.set_result(None)
        return released

    async def queue_size(self, *, team_role_id: int) -> int:
        state = await self._state(team_role_id)
        async with state.lock:
            return len(state.waiting)

