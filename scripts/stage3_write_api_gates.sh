#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "[stage3_write_api_gates] 1/6 write use-cases + transaction/idempotency"
python3 -m unittest \
  tests.test_ltc73_write_api_use_cases \
  tests.test_ltc68_transaction_boundaries

echo "[stage3_write_api_gates] 2/6 write HTTP contract + integration"
python3 -m unittest tests.test_ltc74_write_fastapi_contract

echo "[stage3_write_api_gates] 3/6 authz + status/error mapping"
python3 -m unittest \
  tests.test_ltc74_write_fastapi_contract \
  tests.test_ltc48_api_error_mapping

echo "[stage3_write_api_gates] 4/6 openapi snapshot (blocking)"
python3 -m unittest tests.test_ltc70_openapi_snapshot

echo "[stage3_write_api_gates] 5/6 telegram UX regression"
python3 -m unittest \
  tests.test_ltc42_callback_contract_snapshots \
  tests.test_ltc42_callback_use_cases \
  tests.test_ltc66_callbacks_skill_toggle_uow_guard

echo "[stage3_write_api_gates] 6/6 stage2 read regression safety"
./scripts/stage2_read_api_gates.sh

echo "[stage3_write_api_gates] done"
