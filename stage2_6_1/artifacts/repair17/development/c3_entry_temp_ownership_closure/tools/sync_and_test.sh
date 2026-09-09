#!/usr/bin/env bash
# 同步本轮 reader 修改到部署树,在部署树(完整 src)跑 slice unit 既有测试。
# 用法: tr -d '\r' < sync_and_test.sh | bash
set -uo pipefail
PUB=/mnt/f/trading/freqai-rl-audit
DEP=/home/cryptorl/projects/crypto_rl
cp "$PUB/stage2_6_1/runner/r17_c3_engineering_slice.py" \
   "$DEP/stage2_6_1_runner/r17_c3_engineering_slice.py"
sha256sum "$DEP/stage2_6_1_runner/r17_c3_engineering_slice.py"
source "$DEP/activate-freqtrade.sh"
cd "$DEP"
python -m pytest tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py \
  -q --no-header 2>&1 | tail -6
