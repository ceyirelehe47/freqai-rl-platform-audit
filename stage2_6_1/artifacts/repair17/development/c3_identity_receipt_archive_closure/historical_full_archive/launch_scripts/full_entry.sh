#!/usr/bin/env bash
# 阶段五受监护全量入口(R17 系先跑排序;c3rdd_full_20260909)。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
RUN_DIR_REL="stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3rdd_full_20260909"
if [ -e "$REPO/$RUN_DIR_REL" ]; then
  echo "FATAL: run 目录已存在(一次性): $RUN_DIR_REL" >&2; exit 2
fi
export R17_RUN_DIR="$REPO/$RUN_DIR_REL"
bash ~/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh pytest \
  --max-seconds 3600 -- bash /home/cryptorl/r17rdd_full/full_run_ordered.sh \
  --junitxml="$REPO/$RUN_DIR_REL/junit.xml"
rc=$?
echo "OUTER_RC=$rc"
exit $rc
