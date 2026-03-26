from __future__ import annotations

import asyncio
import unittest

from app.services.role_dispatch_queue import RoleDispatchQueueService


class LTC22RoleDispatchQueueServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_request_gets_slot_immediately(self) -> None:
        service = RoleDispatchQueueService()
        grant = await service.acquire_execution_slot(team_role_id=101, request_id="r1")
        self.assertFalse(grant.queued)
        self.assertEqual(grant.queue_position, 0)
        released = await service.release_execution_slot(team_role_id=101, request_id="r1")
        self.assertTrue(released)

    async def test_fifo_order_for_same_team_role(self) -> None:
        service = RoleDispatchQueueService()

        g1 = await service.acquire_execution_slot(team_role_id=202, request_id="r1")
        self.assertFalse(g1.queued)

        order: list[str] = []

        async def _run(req: str) -> None:
            grant = await service.acquire_execution_slot(team_role_id=202, request_id=req)
            order.append(grant.request_id)
            await service.release_execution_slot(team_role_id=202, request_id=req)

        t2 = asyncio.create_task(_run("r2"))
        t3 = asyncio.create_task(_run("r3"))
        await asyncio.sleep(0.05)
        self.assertEqual(await service.queue_size(team_role_id=202), 2)

        await service.release_execution_slot(team_role_id=202, request_id="r1")
        await asyncio.gather(t2, t3)
        self.assertEqual(order, ["r2", "r3"])

    async def test_different_team_roles_do_not_block_each_other(self) -> None:
        service = RoleDispatchQueueService()
        g1 = await service.acquire_execution_slot(team_role_id=301, request_id="a1")
        g2 = await service.acquire_execution_slot(team_role_id=302, request_id="b1")
        self.assertFalse(g1.queued)
        self.assertFalse(g2.queued)
        await service.release_execution_slot(team_role_id=301, request_id="a1")
        await service.release_execution_slot(team_role_id=302, request_id="b1")


if __name__ == "__main__":
    unittest.main()

