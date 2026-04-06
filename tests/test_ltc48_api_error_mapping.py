from __future__ import annotations

import unittest

from app.application.contracts import ErrorCode, Result
from app.application.observability import clear_correlation_id
from app.interfaces.api.error_mapping import map_exception_to_api_error, map_result_error_to_api


class LTC48ApiErrorMappingTests(unittest.TestCase):
    def test_map_result_error_to_api_uses_unified_contract(self) -> None:
        clear_correlation_id()
        result = Result[None].fail(
            ErrorCode.STORAGE_NOT_FOUND,
            "Role not found",
            details={"entity": "role", "id": "dev"},
        )
        mapped = map_result_error_to_api(result)
        self.assertEqual(mapped.status_code, 404)
        self.assertEqual(mapped.payload["code"], "storage.not_found")
        self.assertEqual(mapped.payload["message"], "Role not found")
        self.assertEqual(mapped.payload["details"].get("entity"), "role")
        self.assertEqual(mapped.payload["details"].get("id"), "dev")
        self.assertIsInstance(mapped.payload["details"].get("correlation_id"), str)
        self.assertEqual(mapped.payload["http_status"], 404)

    def test_map_result_error_to_api_respects_status_override(self) -> None:
        clear_correlation_id()
        result = Result[None].fail(
            ErrorCode.AUTH_UNAUTHORIZED,
            "Forbidden",
            http_status=403,
        )
        mapped = map_result_error_to_api(result)
        self.assertEqual(mapped.status_code, 403)
        self.assertEqual(mapped.payload["code"], "auth.unauthorized")
        self.assertEqual(mapped.payload["http_status"], 403)

    def test_map_exception_to_api_error_uses_domain_mapping(self) -> None:
        clear_correlation_id()
        mapped = map_exception_to_api_error(ValueError("Role not found: dev"))
        self.assertEqual(mapped.status_code, 404)
        self.assertEqual(mapped.payload["code"], "storage.not_found")
        self.assertEqual(mapped.payload["details"].get("entity"), "role")
        self.assertIsInstance(mapped.payload["details"].get("correlation_id"), str)


if __name__ == "__main__":
    unittest.main()
