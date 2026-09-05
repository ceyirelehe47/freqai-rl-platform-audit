#!/usr/bin/env bash
# R16 全量测试运行器(WSL home;pytest 全 route_c_stage2_6_1)
set -uo pipefail
D="$HOME/projects/crypto_rl"
cd "$D"
source activate-freqtrade.sh
export PYTHONPATH="$D/src"
OUT="$1:?需要输出文件参数"
python -m pytest tests/route_c_stage2_6_1 -q \
  --junitxml="$D/r16_full_junit.xml" 2>&1 | tail -40 | tee "$OUT"
