#!/bin/bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/cryptorl/projects/crypto_rl/src
cd /home/cryptorl/projects/crypto_rl
T=tests/route_c_stage2_6_1
for f in test_curriculum261_qprod_r8_fixes.py test_curriculum261_qprod_r9_fixes.py test_curriculum261_qprod_r10_fixes.py; do
  n=$($PY -m pytest -q -p no:cacheprovider --collect-only -k cue "$T/$f" 2>/dev/null | grep -c "::")
  echo "$f -k cue = $n"
done
echo "== r9cc+r10cc+r17binding total =="
$PY -m pytest -q -p no:cacheprovider --collect-only "$T/test_curriculum261_r9_cue_contract.py" "$T/test_curriculum261_r10_cue_contract.py" "$T/test_curriculum261_r17_design_cue_binding.py" 2>/dev/null | grep -c "::"
