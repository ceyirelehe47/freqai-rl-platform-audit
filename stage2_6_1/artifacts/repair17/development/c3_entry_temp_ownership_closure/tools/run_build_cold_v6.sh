#!/usr/bin/env bash
# v6 包构建 + 隔离冷读(一次性合同;交接包路线 E01)。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
DEV="$REPO/stage2_6_1/artifacts/repair17/development"
TOOLS="$DEV/c3_entry_temp_ownership_closure/tools"
VER="$DEV/c3_entry_temp_ownership_closure/verification_v6"
CONDA_PY="$HOME/miniforge3/envs/freqtrade-rl/bin/python"

mkdir -p "$VER"
"$CONDA_PY" "$TOOLS/build_v6_package.py" build --repo "$REPO" \
  --out "$VER/package" --authority-src "$HOME/projects/crypto_rl/src"
BUILD_RC=$?
echo "BUILD_RC=$BUILD_RC"
if [ "$BUILD_RC" != "0" ]; then exit "$BUILD_RC"; fi

tr -d '\r' < "$TOOLS/cold_read_v6.sh" | bash -s -- \
  "$VER/package" /tmp/c3eto_cold_v6_work \
  "$VER/cold_read_report_v6.json"
echo "COLD_RC=$?"
