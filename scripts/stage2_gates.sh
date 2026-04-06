#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "[stage2_gates] 1/4 runtime + use-case regression"
python3 -m unittest \
  tests.test_ltc42_group_runtime_use_cases \
  tests.test_ltc42_private_pending_use_cases \
  tests.test_ltc42_callback_use_cases \
  tests.test_ltc46_runtime_error_codes \
  tests.test_ltc46_runtime_transitions_contract \
  tests.test_ltc68_transaction_boundaries

echo "[stage2_gates] 2/4 read-only API contract + integration"
python3 -m unittest \
  tests.test_ltc69_read_only_api_use_cases \
  tests.test_ltc72_read_api_extension_use_cases \
  tests.test_ltc69_read_only_fastapi_contract \
  tests.test_ltc71_read_only_api_e2e_smoke \
  tests.test_ltc48_api_error_mapping

echo "[stage2_gates] 3/4 owner-only HTTP authz"
python3 -m unittest tests.test_ltc69_read_only_fastapi_contract

echo "[stage2_gates] 4/4 DTO + response schema contracts"
python3 -m unittest \
  tests.test_ltc48_api_schema_contract \
  tests.test_ltc48_api_schema_dto

echo "[stage2_gates] 5/5 openapi snapshot (blocking)"
python3 -m unittest tests.test_ltc70_openapi_snapshot

echo "[stage2_gates] done"
