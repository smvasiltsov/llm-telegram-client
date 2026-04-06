from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.config import load_config


class ConfigInterfaceRuntimeTests(unittest.TestCase):
    def test_interface_defaults_are_applied(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text(
                json.dumps(
                    {
                        "telegram_bot_token": "t",
                        "database_path": "./db.sqlite3",
                        "encryption_key": "k",
                        "owner_user_id": 1,
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_config(cfg)
            self.assertEqual(loaded.interface_active, "telegram")
            self.assertEqual(loaded.interface_modules_dir, "app.interfaces")
            self.assertEqual(loaded.interface_runtime_mode, "single")
            self.assertEqual(loaded.dispatch_mode, "single-instance")
            self.assertTrue(loaded.dispatch_is_runner)
            self.assertEqual(loaded.free_transition_delay_sec, 0)
            self.assertEqual(loaded.skills_to_llm_delay_sec, 0)

    def test_interface_runtime_mode_falls_back_to_single_when_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text(
                json.dumps(
                    {
                        "telegram_bot_token": "t",
                        "database_path": "./db.sqlite3",
                        "encryption_key": "k",
                        "owner_user_id": 1,
                        "interface": {
                            "active": "telegram",
                            "modules_dir": "app.interfaces",
                            "runtime_mode": "multi",
                        },
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_config(cfg)
            self.assertEqual(loaded.interface_runtime_mode, "single")

    def test_free_transition_delay_sec_is_parsed_and_clamped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text(
                json.dumps(
                    {
                        "telegram_bot_token": "t",
                        "database_path": "./db.sqlite3",
                        "encryption_key": "k",
                        "owner_user_id": 1,
                        "runtime_status": {"free_transition_delay_sec": -9},
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_config(cfg)
            self.assertEqual(loaded.free_transition_delay_sec, 0)

    def test_dispatch_mode_single_runner_and_runner_flag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text(
                json.dumps(
                    {
                        "telegram_bot_token": "t",
                        "database_path": "./db.sqlite3",
                        "encryption_key": "k",
                        "owner_user_id": 1,
                        "dispatch": {"mode": "single-runner", "is_runner": False},
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_config(cfg)
            self.assertEqual(loaded.dispatch_mode, "single-runner")
            self.assertFalse(loaded.dispatch_is_runner)

    def test_dispatch_single_instance_forces_runner_true(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text(
                json.dumps(
                    {
                        "telegram_bot_token": "t",
                        "database_path": "./db.sqlite3",
                        "encryption_key": "k",
                        "owner_user_id": 1,
                        "dispatch": {"mode": "single-instance", "is_runner": False},
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_config(cfg)
            self.assertEqual(loaded.dispatch_mode, "single-instance")
            self.assertTrue(loaded.dispatch_is_runner)

    def test_skills_to_llm_delay_sec_is_parsed_and_clamped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text(
                json.dumps(
                    {
                        "telegram_bot_token": "t",
                        "database_path": "./db.sqlite3",
                        "encryption_key": "k",
                        "owner_user_id": 1,
                        "runtime_status": {"skills_to_llm_delay_sec": -3},
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_config(cfg)
            self.assertEqual(loaded.skills_to_llm_delay_sec, 0)


if __name__ == "__main__":
    unittest.main()
