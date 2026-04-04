from __future__ import annotations

import unittest

from app.application.contracts import ErrorCode, Result, resolve_http_status


class LTC46RuntimeErrorCodesTests(unittest.TestCase):
    def test_runtime_error_codes_have_stable_http_mapping(self) -> None:
        self.assertEqual(resolve_http_status(ErrorCode.RUNTIME_BUSY_CONFLICT), 409)
        self.assertEqual(resolve_http_status(ErrorCode.RUNTIME_PENDING_EXISTS), 409)
        self.assertEqual(resolve_http_status(ErrorCode.RUNTIME_REPLAY_FAILED), 424)

    def test_result_fail_uses_runtime_error_http_status(self) -> None:
        busy = Result[object].fail(ErrorCode.RUNTIME_BUSY_CONFLICT, "busy")
        pending = Result[object].fail(ErrorCode.RUNTIME_PENDING_EXISTS, "pending")
        replay = Result[object].fail(ErrorCode.RUNTIME_REPLAY_FAILED, "replay")

        self.assertEqual(busy.error.http_status if busy.error else None, 409)
        self.assertEqual(pending.error.http_status if pending.error else None, 409)
        self.assertEqual(replay.error.http_status if replay.error else None, 424)


if __name__ == "__main__":
    unittest.main()
