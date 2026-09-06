#!/usr/bin/env bash
# 监护接线闭合轮:全量受监护回归启动器(C13 模式B接收 + C18 完整证据)
set -euo pipefail
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
TS=$(date -u +%Y%m%dT%H%M%S)
TAG="${1:-final}"
RUN_DIR=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/supervision_closure/full_regression/runs/${TAG}_$TS
mkdir -p "$(dirname "$RUN_DIR")"
export R17_RUN_DIR="$RUN_DIR"
bash /home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh pytest \
  --max-seconds 14400 -- \
  bash -c "source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh && cd /home/cryptorl/projects/crypto_rl && python -m pytest tests/route_c_stage2_6_1 --junitxml=$RUN_DIR/junit.xml -q"
