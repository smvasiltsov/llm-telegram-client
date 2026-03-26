from __future__ import annotations

import unittest

from app.interfaces.runtime.registry import build_interface_descriptor


class InterfaceRuntimeRegistryTests(unittest.TestCase):
    def test_build_descriptor_uses_normalized_interface_and_module_path(self) -> None:
        descriptor = build_interface_descriptor(" Telegram ", " app.interfaces ")
        self.assertEqual(descriptor.interface_id, "telegram")
        self.assertEqual(descriptor.module_path, "app.interfaces.telegram.adapter")

    def test_build_descriptor_uses_default_modules_dir_when_empty(self) -> None:
        descriptor = build_interface_descriptor("telegram", " ")
        self.assertEqual(descriptor.module_path, "interfaces.telegram.adapter")

    def test_build_descriptor_rejects_empty_interface(self) -> None:
        with self.assertRaises(ValueError):
            build_interface_descriptor(" ", "app.interfaces")


if __name__ == "__main__":
    unittest.main()
