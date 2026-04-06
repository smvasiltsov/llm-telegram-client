from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from app.application.contracts import RuntimeOperation
from app.application.use_cases.runtime_orchestration import execute_run_chain_operation
from app.interfaces.api.dependencies import provide_runtime_dispatch_health
from app.services.role_dispatch_queue import DispatchPolicyRejectedError, RoleDispatchQueueService


class _FakeMetricsPort:
    def __init__(self) -> None:
        self.increments: list[tuple[str, int, dict[str, str]]] = []
        self.observations: list[tuple[str, float, dict[str, str]]] = []

    def increment(self, name: str, *, labels=None, value: int = 1) -> None:  # noqa: ANN001
        self.increments.append((name, int(value), dict(labels or {})))

    def observe_ms(self, name: str, *, value_ms: float, labels=None) -> None:  # noqa: ANN001
        self.observations.append((name, float(value_ms), dict(labels or {})))

    def operation_timer(self, operation: str, *, transport: str):  # noqa: ANN001
        metrics = self

        class _Timer:
            def observe(self, *, result: str, error_code: str | None = None) -> float:
                metrics.observe_ms(
                    "runtime_operation_latency_ms",
                    value_ms=1.0,
                    labels={
                        "operation": operation,
                        "transport": transport,
                        "result": result,
                        "error_code": error_code or "",
                    },
                )
                return 1.0

        return _Timer()


class LTC50MultiInstanceRuntimeModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_depth_metric_emitted(self) -> None:
        metrics = _FakeMetricsPort()
        queue = RoleDispatchQueueService(metrics_port=metrics, queue_name="role_dispatch")
        first = await queue.acquire_execution_slot(team_role_id=300, request_id="r1")
        self.assertTrue(first.accepted)

        second_task = asyncio.create_task(queue.acquire_execution_slot(team_role_id=300, request_id="r2"))
        await asyncio.sleep(0)
        self.assertFalse(second_task.done())

        released = await queue.release_execution_slot(team_role_id=300, request_id="r1")
        self.assertTrue(released)
        second = await second_task
        self.assertTrue(second.accepted)
        await queue.release_execution_slot(team_role_id=300, request_id="r2")

        queue_depth = [item for item in metrics.observations if item[0] == "runtime_queue_depth"]
        self.assertTrue(queue_depth)
        self.assertTrue(all(item[2].get("queue_name") == "role_dispatch" for item in queue_depth))

    async def test_queue_single_instance_default_accepts_dispatch(self) -> None:
        queue = RoleDispatchQueueService()
        grant = await queue.acquire_execution_slot(team_role_id=100, request_id="r1")
        self.assertTrue(grant.accepted)
        self.assertFalse(grant.queued)
        self.assertEqual(grant.reason, "single_instance")
        self.assertTrue(await queue.release_execution_slot(team_role_id=100, request_id="r1"))

    async def test_queue_single_runner_non_runner_rejects_dispatch(self) -> None:
        queue = RoleDispatchQueueService(dispatch_mode="single-runner", dispatch_is_runner=False)
        grant = await queue.acquire_execution_slot(team_role_id=200, request_id="r2")
        self.assertFalse(grant.accepted)
        self.assertEqual(grant.reason, "non_runner_instance")
        self.assertFalse(grant.queued)

    async def test_runtime_operation_maps_dispatch_rejection_to_busy_conflict(self) -> None:
        metrics = _FakeMetricsPort()
        runtime = SimpleNamespace(dispatch_mode="single-runner", dispatch_is_runner=False)
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"metrics_port": metrics, "runtime": runtime}))

        async def run_chain_stub(**_: object):  # noqa: ANN001
            raise DispatchPolicyRejectedError(mode="single-runner", is_runner=False, reason="non_runner_instance")

        result = await execute_run_chain_operation(
            context=context,
            team_id=1,
            chat_id=2,
            user_id=3,
            session_token="t",
            roles=[],
            user_text="u",
            reply_text=None,
            actor_username="user",
            reply_to_message_id=10,
            is_all=False,
            apply_plugins=False,
            save_pending_on_unauthorized=False,
            operation=RuntimeOperation.RUN_CHAIN,
            run_chain_fn=run_chain_stub,
        )

        self.assertTrue(result.is_error)
        self.assertEqual(result.error.code, "runtime_non_runner_reject")
        failed = [
            item
            for item in metrics.increments
            if item[0] == "runtime_operation_total"
            and item[2].get("result") == "failed"
            and item[2].get("error_code") == "runtime_non_runner_reject"
        ]
        self.assertTrue(failed)
        self.assertEqual(failed[0][2].get("mode"), "single-runner")
        self.assertEqual(failed[0][2].get("runner"), "non-runner")

    def test_api_runtime_dispatch_health_contract(self) -> None:
        state = SimpleNamespace(
            runtime=SimpleNamespace(
                dispatch_mode="single-runner",
                dispatch_is_runner=False,
                queue_backend="in-memory",
                started_at="2026-04-05T00:00:00+00:00",
            )
        )
        health = provide_runtime_dispatch_health(state)
        self.assertTrue(health.is_ok)
        self.assertEqual(
            health.value,
            {
                "mode": "single-runner",
                "is_runner": False,
                "queue_backend": "in-memory",
                "started_at": "2026-04-05T00:00:00+00:00",
            },
        )


if __name__ == "__main__":
    unittest.main()
