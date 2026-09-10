#!/usr/bin/env bash
# R17 原生采样器验证C启动器:mode = fg | setsid
set -uo pipefail
MODE="${1:-fg}"
source ~/projects/crypto_rl/activate-freqtrade.sh >/dev/null 2>&1
cd ~/projects/crypto_rl
SUPERV_ROOT=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision
RUN_ID="r17ns_${MODE}_$(date -u +%Y%m%dT%H%M%S)"
RUN_DIR="$SUPERV_ROOT/runs/$RUN_ID"
export R17_RUN_DIR="$RUN_DIR"
echo "RUN_DIR=$RUN_DIR"
bash stage2_6_1_runner/r17_monitored_entry.sh pytest -- \
  python -m pytest -q tests/route_c_stage2_6_1/test_curriculum261_r17_receipt_entry_cleanup_unit.py \
  --junitxml="$RUN_DIR/junit.xml"
RC=$?
echo "ENTRY_RC=$RC"
exit $RC
