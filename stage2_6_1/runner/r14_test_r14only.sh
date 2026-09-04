#!/usr/bin/env bash
# R14:先跑全部 r14 新测试(快速反馈)
set -uo pipefail
cd "$HOME/projects/crypto_rl"
source activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH="$HOME/projects/crypto_rl/src"
python -m pytest tests/route_c_stage2_6_1/test_curriculum261_r14_gate_topology.py \
  tests/route_c_stage2_6_1/test_curriculum261_r14_freeze.py \
  tests/route_c_stage2_6_1/test_curriculum261_r14_no_post_exposure.py \
  tests/route_c_stage2_6_1/test_curriculum261_r14_identity.py \
  tests/route_c_stage2_6_1/test_curriculum261_r14_full_cold_reader.py \
  tests/route_c_stage2_6_1/test_curriculum261_r14_allowlist.py \
  tests/route_c_stage2_6_1/test_curriculum261_r14_roundtrip.py \
  tests/route_c_stage2_6_1/test_curriculum261_r14_governance.py \
  -q 2>&1 | tail -30
