#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "[stage2_read_api_gates] running mandatory Stage 2 v1 gate set"
./scripts/stage2_gates.sh
echo "[stage2_read_api_gates] done"

