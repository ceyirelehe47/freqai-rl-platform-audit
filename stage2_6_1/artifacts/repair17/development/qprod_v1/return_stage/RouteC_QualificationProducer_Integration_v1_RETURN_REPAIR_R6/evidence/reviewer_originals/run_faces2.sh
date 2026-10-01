#!/usr/bin/env bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
cd /home/cryptorl/projects/crypto_rl
T=tests/route_c_stage2_6_1
echo "=== cue face r9/r10 contract+eval, r12 global_k ==="
"$PY" -m pytest \
  "$T/test_curriculum261_r9_cue_contract.py" \
  "$T/test_curriculum261_r9_cue_eval.py" \
  "$T/test_curriculum261_r10_cue_contract.py" \
  "$T/test_curriculum261_r10_cue_eval.py" \
  "$T/test_curriculum261_r12_global_k.py" \
  -q --no-header 2>&1 | tail -2
echo "=== 262 qprod export face ==="
ls tests/route_c_stage2_6_2/ 2>/dev/null | head
"$PY" -m pytest tests/route_c_stage2_6_2/test_ppo262_qprod_export.py -q --no-header 2>&1 | tail -2
