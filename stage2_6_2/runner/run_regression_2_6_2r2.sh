#!/usr/bin/env bash
# 阶段 2.6.2 Repair R2 诊断回归(非 official PASS closure,不跑 full-cold)
# 层级:targeted(r2) -> stage2_6_2 -> affected 2.6.1 -> Route C 代表
set -uo pipefail
cd "$(dirname "$0")"
source "$HOME/projects/crypto_rl/activate-freqtrade.sh"
export PYTHONPATH=src

run() {
  local name="$1"; shift
  echo "=== [$name] ==="
  python -m pytest "$@" -q 2>&1 | tail -2
}

run "targeted-r2" \
  tests/route_c_stage2_6_2/test_ppo262_r2_namespaces.py \
  tests/route_c_stage2_6_2/test_ppo262_r2_evaluator.py \
  tests/route_c_stage2_6_2/test_ppo262_r2_scaling.py \
  tests/route_c_stage2_6_2/test_ppo262_r2_checkpoints.py \
  tests/route_c_stage2_6_2/test_ppo262_r2_gradients.py \
  tests/route_c_stage2_6_2/test_ppo262_r2_bc.py \
  tests/route_c_stage2_6_2/test_ppo262_r2_c2_imbalance.py \
  tests/route_c_stage2_6_2/test_ppo262_r2_branch.py \
  tests/route_c_stage2_6_2/test_ppo262_r2_preservation.py
run "stage2_6_2" tests/route_c_stage2_6_2
run "stage2_6_1-affected" tests/route_c_stage2_6_1
run "route-c-representative" tests/route_c_stage2_6_0 tests/route_c_stage2_6_0j
