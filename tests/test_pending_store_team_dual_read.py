from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.pending_store import PendingStore


class PendingStoreTeamDualReadTests(unittest.TestCase):
    def test_peek_record_and_legacy_peek_are_consistent(self) -> None:
        with TemporaryDirectory() as td:
            store = PendingStore(Path(td) / "pending.sqlite3")
            store.save(
                telegram_user_id=101,
                chat_id=-5001,
                team_id=77,
                message_id=3001,
                role_name="dev",
                content="hello",
                reply_text="ctx",
            )

            record = store.peek_record(101)
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record["team_id"], 77)
            self.assertEqual(record["chat_id"], -5001)

            legacy = store.peek(101)
            self.assertEqual(legacy, (-5001, 3001, "dev", "hello", "ctx"))

            popped = store.pop_record(101)
            self.assertIsNotNone(popped)
            self.assertIsNone(store.peek_record(101))


if __name__ == "__main__":
    unittest.main()
