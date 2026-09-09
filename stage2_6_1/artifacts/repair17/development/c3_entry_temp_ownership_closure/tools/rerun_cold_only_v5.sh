#!/usr/bin/env bash
# 仅重跑冷读(包已构建,一次性 work 换新)。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
DEV="$REPO/stage2_6_1/artifacts/repair17/development"
TOOLS="$DEV/c3_entry_temp_ownership_closure/tools"
VER="$DEV/c3_entry_temp_ownership_closure/verification_v5"
rm -rf /tmp/c3eto_cold_v5_work
tr -d '\r' < "$TOOLS/cold_read_v5.sh" | bash -s -- \
  "$VER/package" /tmp/c3eto_cold_v5_work \
  "$VER/cold_read_report_v5.json"
echo "COLD_RC=$?"
