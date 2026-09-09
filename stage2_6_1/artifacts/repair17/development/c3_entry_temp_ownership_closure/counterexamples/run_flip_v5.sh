#!/usr/bin/env bash
# 阶段二翻转复验:py_compile + 同一反例脚本对新(工作树)reader 复跑。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
DEV="$REPO/stage2_6_1/artifacts/repair17/development"
CE="$DEV/c3_entry_temp_ownership_closure/counterexamples"
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
NEW="$REPO/stage2_6_1/runner/r17_c3_engineering_slice.py"

"$PY" -m py_compile "$NEW" && echo "COMPILE_OK"
sha256sum "$NEW"
tr -d '\r' < "$CE/run_ce_v5.sh" | bash -s -- \
  "$NEW" "$CE/fixed_reader_flip_v5.json"
echo "FLIP_RC=$?"
