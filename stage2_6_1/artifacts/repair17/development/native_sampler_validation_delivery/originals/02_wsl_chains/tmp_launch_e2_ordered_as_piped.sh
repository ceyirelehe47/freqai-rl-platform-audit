#!/usr/bin/env bash
# R17 验证E(重启):按既有 full_run_ordered.sh 机制(R17 系先跑)的受监护全量
set -uo pipefail
source ~/projects/crypto_rl/activate-freqtrade.sh >/dev/null 2>&1
cd ~/projects/crypto_rl
SUPERV_ROOT=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision
RUN_ID="r17ns_full2_$(date -u +%Y%m%dT%H%M%S)"
RUN_DIR="$SUPERV_ROOT/runs/$RUN_ID"
export R17_RUN_DIR="$RUN_DIR"
echo "RUN_DIR=$RUN_DIR"
bash stage2_6_1_runner/r17_monitored_entry.sh pytest -- \
  bash /home/cryptorl/r17eto_full/full_run_ordered.sh \
    --junitxml="$RUN_DIR/junit.xml"
RC=$?
echo "ENTRY_RC=$RC"
exit $RC
