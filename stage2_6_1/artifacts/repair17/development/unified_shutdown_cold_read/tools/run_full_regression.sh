#!/usr/bin/env bash
# 本轮全量回归启动器(unified_shutdown_cold_read;沿用上轮监护形态:
# R17_RUN_DIR 预指定使 junitxml 先验可知;freqtrade-rl 解释器;
# 只建父目录,run 目录由入口排他创建)。
set -euo pipefail
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/unified_shutdown_cold_read
RUN_ID="final_$(date -u +%Y%m%dT%H%M%S)"
RD="$BASE/runs/$RUN_ID"
mkdir -p "$BASE/runs"  # 只建父目录;run 目录由入口排他创建
cd "$HOME/projects/crypto_rl"
R17_RUN_DIR="$RD" "$HOME/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh" \
  pytest --max-seconds 3000 -- \
  "$HOME/miniforge3/envs/freqtrade-rl/bin/python" -m pytest \
  tests/route_c_stage2_6_1 -q --no-header -p no:cacheprovider \
  "--junitxml=$RD/junit.xml"
echo "MONITORED_RC=$?"
echo "RUN_DIR=$RD"
