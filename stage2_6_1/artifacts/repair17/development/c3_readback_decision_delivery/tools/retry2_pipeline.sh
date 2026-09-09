#!/usr/bin/env bash
# 失败现场保留(attempt2)并重跑整链(run d)。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
DELIV="$REPO/stage2_6_1/artifacts/repair17/development/c3_readback_decision_delivery"
if [ -d "$DELIV/verification" ]; then
  mv "$DELIV/verification" "$DELIV/verification_attempt2"
  echo "MOVED attempt2"
fi
tr -d '\r' < "$DELIV/tools/run_verification_pipeline.sh" > /home/cryptorl/r17rdd_pipe.sh
bash /home/cryptorl/r17rdd_pipe.sh c3rdd_pkg_build_20260909e
