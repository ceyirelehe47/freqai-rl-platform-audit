#!/usr/bin/env bash
# R13:先跑 r13 新测试(快速反馈)
set -euo pipefail
cd "$HOME/projects/crypto_rl"
source activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH="$HOME/projects/crypto_rl/src"
python -m pytest tests/route_c_stage2_6_1/test_curriculum261_r13_roundtrip.py \
  tests/route_c_stage2_6_1/test_curriculum261_r13_governance.py \
  -x -q 2>&1 | tail -30
