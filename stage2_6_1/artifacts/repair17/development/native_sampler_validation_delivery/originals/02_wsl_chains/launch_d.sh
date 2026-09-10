#!/usr/bin/env bash
# R17 验证D短正例:业务含 c3_slice(108)+receipt(54)+r16_gov(4+3skip)
set -uo pipefail
source ~/projects/crypto_rl/activate-freqtrade.sh >/dev/null 2>&1
cd ~/projects/crypto_rl
SUPERV_ROOT=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision
RUN_ID="r17ns_dpos_$(date -u +%Y%m%dT%H%M%S)"
RUN_DIR="$SUPERV_ROOT/runs/$RUN_ID"
export R17_RUN_DIR="$RUN_DIR"
echo "RUN_DIR=$RUN_DIR"
bash stage2_6_1_runner/r17_monitored_entry.sh pytest -- \
  python -m pytest -q \
    tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py \
    tests/route_c_stage2_6_1/test_curriculum261_r17_receipt_entry_cleanup_unit.py \
    tests/route_c_stage2_6_1/test_curriculum261_r16_governance.py \
    --junitxml="$RUN_DIR/junit.xml"
RC=$?
echo "ENTRY_RC=$RC"
exit $RC
