from __future__ import annotations

import unittest

from app.application.contracts import ErrorCode, Result, map_exception_to_error, normalize_error_code, resolve_http_status


class LTC43ErrorModelTests(unittest.TestCase):
    def test_error_code_registry_http_status(self) -> None:
        self.assertEqual(resolve_http_status(ErrorCode.STORAGE_NOT_FOUND), 404)
        self.assertEqual(resolve_http_status(ErrorCode.VALIDATION_INVALID_INPUT), 422)
        self.assertEqual(resolve_http_status(ErrorCode.AUTH_UNAUTHORIZED), 401)
        self.assertEqual(resolve_http_status(ErrorCode.CONFLICT_ALREADY_EXISTS), 409)
        self.assertEqual(resolve_http_status(ErrorCode.INTERNAL_UNEXPECTED), 500)

    def test_result_fail_uses_registry_http_status(self) -> None:
        result = Result[None].fail(ErrorCode.AUTH_UNAUTHORIZED, "Unauthorized")
        self.assertTrue(result.is_error)
        assert result.error is not None
        self.assertEqual(result.error.code, "auth.unauthorized")
        self.assertEqual(result.error.http_status, 401)
        self.assertFalse(result.error.retryable)

    def test_result_fail_can_override_http_status(self) -> None:
        result = Result[None].fail("validation.invalid_input", "Bad", http_status=400)
        self.assertTrue(result.is_error)
        assert result.error is not None
        self.assertEqual(result.error.http_status, 400)

    def test_map_exception_value_error(self) -> None:
        code, message, details, http_status, retryable = map_exception_to_error(ValueError("invalid"))
        self.assertEqual(code, "validation.invalid_input")
        self.assertEqual(message, "invalid")
        self.assertIsNone(details)
        self.assertEqual(http_status, 422)
        self.assertFalse(retryable)

    def test_map_exception_fallback_for_unexpected(self) -> None:
        code, message, details, http_status, retryable = map_exception_to_error(
            RuntimeError("boom"),
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_details={"cause": "runtime"},
            retryable=True,
        )
        self.assertEqual(code, "internal.unexpected")
        self.assertEqual(message, "boom")
        self.assertEqual(details, {"cause": "runtime"})
        self.assertEqual(http_status, 500)
        self.assertTrue(retryable)

    def test_result_fail_from_exception(self) -> None:
        result = Result[None].fail_from_exception(ValueError("bad input"))
        self.assertTrue(result.is_error)
        assert result.error is not None
        self.assertEqual(result.error.code, "validation.invalid_input")
        self.assertEqual(result.error.http_status, 422)
        self.assertEqual(result.error.message, "bad input")

    def test_normalize_error_code(self) -> None:
        self.assertEqual(normalize_error_code(ErrorCode.STORAGE_NOT_FOUND), "storage.not_found")
        self.assertEqual(normalize_error_code("custom.error"), "custom.error")


if __name__ == "__main__":
    unittest.main()
