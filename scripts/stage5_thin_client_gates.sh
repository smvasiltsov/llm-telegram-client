#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "[stage5_thin_client_gates] 1/3 runtime client feature-flag resolution"
python3 -m unittest tests.test_ltc87_telegram_runtime_client

echo "[stage5_thin_client_gates] 2/3 telegram thin-path group/private/pending flows"
python3 -m unittest \
  tests.test_ltc42_group_runtime_use_cases \
  tests.test_ltc42_private_pending_use_cases \
  tests.test_ltc42_private_pending_replay_use_case \
  tests.test_root_dir_pending_flow

echo "[stage5_thin_client_gates] 3/3 stage5 contract regression safety"
python3 -m unittest tests.test_ltc78_stage5_fastapi_contract

echo "[stage5_thin_client_gates] done"
