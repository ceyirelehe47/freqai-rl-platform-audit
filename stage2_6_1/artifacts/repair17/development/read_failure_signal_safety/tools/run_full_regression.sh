#!/usr/bin/env bash
# 本轮全量回归启动器(wsl.exe 内联变量会被参数重解析吃掉,走脚本文件)。
# 用法(WSL 内): bash run_full_regression.sh
set -euo pipefail
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/read_failure_signal_safety
RUN_ID="final_$(date -u +%Y%m%dT%H%M%S)"
RD="$BASE/full_regression/runs/$RUN_ID"
mkdir -p "$BASE/full_regression/runs"  # 只建父目录;run 目录由入口排他创建
cd "$HOME/projects/crypto_rl"
R17_RUN_DIR="$RD" "$HOME/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh" \
  pytest --max-seconds 3000 -- \
  "$HOME/miniforge3/envs/freqtrade-rl/bin/python" -m pytest \
  tests/route_c_stage2_6_1 -q --no-header -p no:cacheprovider \
  "--junitxml=$RD/junit.xml"
echo "MONITORED_RC=$?"
echo "RUN_DIR=$RD"
