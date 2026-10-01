#!/usr/bin/env bash
set -u
cd /home/cryptorl/projects/crypto_rl
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
echo "== R9 pinned =="
"$PY" -m pytest tests/route_c_stage2_6_1/test_curriculum261_qprod_r9_fixes.py -q 2>&1 | tail -3
echo "== qprod face =="
"$PY" -m pytest tests/route_c_stage2_6_1/ -q -k "qprod" 2>&1 | tail -3
echo "== cue-contract faces r8/r9/r10/r17 =="
"$PY" -m pytest tests/route_c_stage2_6_1/test_curriculum261_r8_cue_contract.py tests/route_c_stage2_6_1/test_curriculum261_r9_cue_contract.py tests/route_c_stage2_6_1/test_curriculum261_r10_cue_contract.py tests/route_c_stage2_6_1/test_curriculum261_r17_design_cue_binding.py -q 2>&1 | tail -3
