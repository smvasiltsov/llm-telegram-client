from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.application.authz import (
    AuthzAction,
    OwnerOnlyAuthzService,
    actor_from_callback,
    actor_from_update,
    resource_ctx_from_callback,
    resource_ctx_from_update,
)


class LTC45AuthzPolicyTests(unittest.TestCase):
    def test_owner_only_policy_allows_owner(self) -> None:
        service = OwnerOnlyAuthzService(owner_user_id=42)
        result = service.authorize(
            action=AuthzAction.TELEGRAM_COMMANDS_ADMIN,
            actor=SimpleNamespace(user_id=42),
            resource_ctx=None,
        )
        self.assertTrue(result.is_ok)
        self.assertIsNotNone(result.value)
        self.assertTrue(bool(result.value and result.value.allowed))

    def test_owner_only_policy_denies_non_owner_with_contract(self) -> None:
        service = OwnerOnlyAuthzService(owner_user_id=42)
        result = service.authorize(
            action=AuthzAction.TELEGRAM_CALLBACKS_ADMIN,
            actor=SimpleNamespace(user_id=7),
            resource_ctx=None,
        )
        self.assertTrue(result.is_error)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.error.code, "auth.unauthorized")
        self.assertEqual(result.error.http_status, 403)
        self.assertEqual((result.error.details or {}).get("action"), AuthzAction.TELEGRAM_CALLBACKS_ADMIN.value)

    def test_telegram_adapter_builds_actor_and_resource(self) -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=1001),
            effective_chat=SimpleNamespace(id=-10012345),
        )
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=1002),
            message=SimpleNamespace(chat=SimpleNamespace(id=-10054321)),
        )
        actor_u = actor_from_update(update)
        actor_c = actor_from_callback(callback)
        ctx_u = resource_ctx_from_update(update)
        ctx_c = resource_ctx_from_callback(callback)

        self.assertIsNotNone(actor_u)
        self.assertEqual(int(actor_u.user_id), 1001)
        self.assertIsNotNone(actor_c)
        self.assertEqual(int(actor_c.user_id), 1002)
        self.assertEqual(ctx_u.group_id, -10012345)
        self.assertEqual(ctx_c.group_id, -10054321)


if __name__ == "__main__":
    unittest.main()
