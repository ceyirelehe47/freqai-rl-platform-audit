#!/usr/bin/env bash
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
D=/home/cryptorl/projects/crypto_rl
cd "$D"
$PY -m pytest \
  tests/route_c_stage2_6_1/test_curriculum261_r9_cue_contract.py \
  tests/route_c_stage2_6_1/test_curriculum261_r9_cue_eval.py \
  tests/route_c_stage2_6_1/test_curriculum261_r10_cue_contract.py \
  tests/route_c_stage2_6_1/test_curriculum261_r10_cue_eval.py \
  tests/route_c_stage2_6_1/test_curriculum261_r17_design_cue_binding.py \
  tests/route_c_stage2_6_1/test_curriculum261_r25_cue_dev_entry.py \
  -q 2>&1 | tail -8
echo "cue_rc=${PIPESTATUS[0]}"
