#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "[stage5_qa_api_gates] 1/8 stage4 baseline gates"
./scripts/stage4_runtime_api_hardening_gates.sh

echo "[stage5_qa_api_gates] 2/8 stage5 schema/storage + lineage/thread invariants"
python3 -m unittest \
  tests.test_ltc76_stage5_storage_foundation \
  tests.test_ltc77_stage5_qa_use_cases

echo "[stage5_qa_api_gates] 3/8 stage5 endpoint contract/integration"
python3 -m unittest tests.test_ltc78_stage5_fastapi_contract

echo "[stage5_qa_api_gates] 4/8 idempotency/cursor/orchestrator feed coverage"
python3 -m unittest \
  tests.test_ltc77_stage5_qa_use_cases \
  tests.test_ltc78_stage5_fastapi_contract

echo "[stage5_qa_api_gates] 5/8 authz + status mapping"
python3 -m unittest \
  tests.test_ltc78_stage5_fastapi_contract \
  tests.test_ltc48_api_error_mapping

echo "[stage5_qa_api_gates] 6/8 openapi snapshot (blocking)"
python3 -m unittest tests.test_ltc70_openapi_snapshot

echo "[stage5_qa_api_gates] 7/8 e2e smoke"
python3 -m unittest \
  tests.test_ltc71_read_only_api_e2e_smoke \
  tests.test_ltc79_stage5_api_e2e_smoke

echo "[stage5_qa_api_gates] 8/8 telegram UX regression safety"
python3 -m unittest \
  tests.test_ltc42_callback_contract_snapshots \
  tests.test_ltc42_callback_use_cases \
  tests.test_ltc66_callbacks_skill_toggle_uow_guard

echo "[stage5_qa_api_gates] done"
