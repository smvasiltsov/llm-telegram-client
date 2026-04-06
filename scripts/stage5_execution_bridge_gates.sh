#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "[stage5_execution_bridge_gates] 1/4 baseline stage5 qa gates"
./scripts/stage5_qa_api_gates.sh

echo "[stage5_execution_bridge_gates] 2/4 bridge lifecycle foundation"
python3 -m unittest tests.test_ltc80_stage5_dispatch_bridge_foundation

echo "[stage5_execution_bridge_gates] 3/4 bridge worker unit/integration"
python3 -m unittest tests.test_ltc81_stage5_dispatch_bridge_worker

echo "[stage5_execution_bridge_gates] 4/4 bridge e2e smoke"
python3 -m unittest tests.test_ltc82_stage5_execution_bridge_e2e_smoke

echo "[stage5_execution_bridge_gates] done"
