#!/usr/bin/env bash
# 同步部署树并运行 slice unit 测试(本轮 R/M/E 矩阵)。
set -euo pipefail
tr -d '\r' < /mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/r17_sync.sh | bash
source ~/projects/crypto_rl/activate-freqtrade.sh
cd ~/projects/crypto_rl
python -m pytest tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py \
  -q --no-header 2>&1 | tail -30
