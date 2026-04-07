#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "[stage4_runtime_api_hardening_gates] 1/5 stage2 baseline gates"
./scripts/stage2_read_api_gates.sh

echo "[stage4_runtime_api_hardening_gates] 2/5 stage3 baseline gates"
./scripts/stage3_write_api_gates.sh

echo "[stage4_runtime_api_hardening_gates] 3/5 stage4 observability + single-instance"
python3 -m unittest \
  tests.test_ltc47_dependency_providers \
  tests.test_ltc48_api_error_mapping \
  tests.test_ltc49_observability_correlation_metrics \
  tests.test_ltc50_multi_instance_runtime_mode

echo "[stage4_runtime_api_hardening_gates] 4/5 stage4 API smoke/integration"
python3 -m unittest \
  tests.test_ltc69_read_only_fastapi_contract \
  tests.test_ltc71_read_only_api_e2e_smoke \
  tests.test_ltc74_write_fastapi_contract \
  tests.test_ltc84_runtime_service_process_smoke

echo "[stage4_runtime_api_hardening_gates] 5/5 rollback drill"
python3 -m unittest tests.test_ltc75_stage4_runtime_hardening

echo "[stage4_runtime_api_hardening_gates] done"
