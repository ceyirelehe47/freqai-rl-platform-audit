#!/usr/bin/env bash
# R15:先跑全部 r15 测试(快速反馈;11 文件)
set -uo pipefail
cd "$HOME/projects/crypto_rl"
source activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH="$HOME/projects/crypto_rl/src"
python -m pytest \
  tests/route_c_stage2_6_1/test_curriculum261_r15_gate_topology.py \
  tests/route_c_stage2_6_1/test_curriculum261_r15_freeze.py \
  tests/route_c_stage2_6_1/test_curriculum261_r15_no_post_exposure.py \
  tests/route_c_stage2_6_1/test_curriculum261_r15_identity.py \
  tests/route_c_stage2_6_1/test_curriculum261_r15_full_cold_reader.py \
  tests/route_c_stage2_6_1/test_curriculum261_r15_allowlist.py \
  tests/route_c_stage2_6_1/test_curriculum261_r15_roundtrip.py \
  tests/route_c_stage2_6_1/test_curriculum261_r15_governance.py \
  tests/route_c_stage2_6_1/test_curriculum261_r15_workflow.py \
  tests/route_c_stage2_6_1/test_curriculum261_r15_lineage.py \
  tests/route_c_stage2_6_1/test_curriculum261_r15_fail_closure_phases.py \
  -q 2>&1 | tail -30
