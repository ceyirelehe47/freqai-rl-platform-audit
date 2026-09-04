#!/usr/bin/env bash
# R14:正式目录 determinism-matrix(冻结前工程命令;audit 硬前置 A6)
set -uo pipefail
cd "$HOME/projects/crypto_rl"
source activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH="$HOME/projects/crypto_rl/src"
LOG="$HOME/projects/crypto_rl/r14_determinism.log"
{
  date -u +"start %Y-%m-%dT%H:%M:%SZ"
  python -m rl_curriculum.curriculum261_r14_cli determinism-matrix
  echo "determinism_rc=$?"
  date -u +"end %Y-%m-%dT%H:%M:%SZ"
} > "$LOG" 2>&1
tail -6 "$LOG"
