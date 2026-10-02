#!/bin/bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/cryptorl/projects/crypto_rl/src
cd /home/cryptorl/projects/crypto_rl
T=tests/route_c_stage2_6_1
echo "== R11 pins (expect 7) =="
$PY -m pytest -q -p no:cacheprovider "$T/test_curriculum261_qprod_r11_fixes.py" 2>&1 | tail -3
echo "== qprod face (expect 198) =="
$PY -m pytest -q -p no:cacheprovider $T/test_curriculum261_qprod_*.py 2>&1 | tail -3
echo "== cue-contract r8/r9/r10/r17 (expect 29) =="
$PY -m pytest -q -p no:cacheprovider \
  "$T/test_curriculum261_r10_cue_contract.py" \
  "$T/test_curriculum261_r9_cue_contract.py" \
  "$T/test_curriculum261_r10_cue_eval.py" \
  "$T/test_curriculum261_r9_cue_eval.py" \
  "$T/test_curriculum261_r17_design_cue_binding.py" 2>&1 | tail -3
echo "== pycache residue audit =="
ls -la src/rl_curriculum/__pycache__/curriculum261_r17_cue_contract.cpython-311.pyc
find "$T/__pycache__" -name "*.pyc" | wc -l
