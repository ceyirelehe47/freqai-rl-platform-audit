#!/usr/bin/env bash
# 阶段 2.6.0j 回归入口:quick -> affected -> full-cold 由开发者按序
# 调用;本脚本提供 full-cold 一键入口(最终 PASS 只认 full-cold)。
set -euo pipefail
cd "$(dirname "$0")"
source "$HOME/projects/crypto_rl/activate-freqtrade.sh"
MODE="${1:-full-cold}"
shift || true
python3 regression_runner.py "$MODE" "$@"
