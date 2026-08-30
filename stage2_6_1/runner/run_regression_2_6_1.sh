#!/usr/bin/env bash
# 阶段 2.6.1 回归入口(full-cold 为最终验收)
set -euo pipefail
cd "$(dirname "$0")"
source "$HOME/projects/crypto_rl/activate-freqtrade.sh"
python3 regression_runner.py "${1:-quick}" ${2:+--workers "$2"}
