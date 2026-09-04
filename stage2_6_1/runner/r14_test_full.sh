#!/usr/bin/env bash
# R14:全量测试(stage2_6_1 全部 Route C 测试)
set -euo pipefail
cd "$HOME/projects/crypto_rl"
source activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH="$HOME/projects/crypto_rl/src"
python -m pytest tests/route_c_stage2_6_1 -q 2>&1 | tail -25
