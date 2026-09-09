#!/usr/bin/env bash
# 跑 slice unit 测试(与全量监护一致的生产环境:先 source 激活脚本)。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
cd "$REPO/stage2_6_1"
python -m pytest tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py \
  -q --no-header 2>&1 | tail -8
