#!/usr/bin/env bash
# 控制路径可靠性轮:全量受监护回归启动器(T24;模式B接收+完整证据)
set -euo pipefail
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
TS=$(date -u +%Y%m%dT%H%M%S)
TAG="${1:-final}"
RUN_DIR=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/control_path_reliability/full_regression/runs/${TAG}_$TS
mkdir -p "$(dirname "$RUN_DIR")"
export R17_RUN_DIR="$RUN_DIR"
bash /home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh pytest \
  --max-seconds 14400 -- \
  bash -c "source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh && cd /home/cryptorl/projects/crypto_rl && python -m pytest tests/route_c_stage2_6_1 --junitxml=$RUN_DIR/junit.xml -q"
echo "MONITORED_RC=$?"
echo "RUN_DIR=$RUN_DIR"
