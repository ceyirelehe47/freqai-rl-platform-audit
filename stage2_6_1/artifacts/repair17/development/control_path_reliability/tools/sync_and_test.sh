#!/usr/bin/env bash
# 同步 F 盘发布仓库改动到 WSL 部署面,再跑指定测试。
# 用法: sync_and_test.sh [pytest 参数...]
set -euo pipefail
SRC=/mnt/f/trading/freqai-rl-audit/stage2_6_1
DST=/home/cryptorl/projects/crypto_rl
cp -f "$SRC"/runner/r17_supervision.py "$DST"/stage2_6_1_runner/
for f in "$SRC"/runner/r17_control_fixture_worker.py; do
  [ -f "$f" ] && cp -f "$f" "$DST"/stage2_6_1_runner/ || true
done
cp -f "$SRC"/src/rl_curriculum/curriculum261_r17_*.py "$DST"/src/rl_curriculum/
mkdir -p "$DST"/tests/route_c_stage2_6_1
cp -f "$SRC"/tests/route_c_stage2_6_1/*.py "$DST"/tests/route_c_stage2_6_1/
cp -f "$SRC"/runner/r17_verify_delivery.py "$DST"/stage2_6_1_runner/ 2>/dev/null || true
source "$DST"/activate-freqtrade.sh
cd "$DST"
python -m pytest "$@"
