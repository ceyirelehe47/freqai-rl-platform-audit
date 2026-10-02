#!/bin/bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/cryptorl/projects/crypto_rl/src
cd /home/cryptorl/projects/crypto_rl
T=tests/route_c_stage2_6_1
echo "== collect -k cue over dir =="
$PY -m pytest -q -p no:cacheprovider --collect-only -k cue "$T" 2>/dev/null | grep -c "::"
echo "== collect -k contract over 5 cue files =="
$PY -m pytest -q -p no:cacheprovider --collect-only -k contract "$T/test_curriculum261_r10_cue_contract.py" "$T/test_curriculum261_r9_cue_contract.py" "$T/test_curriculum261_r10_cue_eval.py" "$T/test_curriculum261_r9_cue_eval.py" "$T/test_curriculum261_r17_design_cue_binding.py" 2>/dev/null | grep -c "::"
echo "== module-level grep: r17 binding uses which modules =="
grep -n "curriculum261_r._cue_contract\|import" "$T/test_curriculum261_r17_design_cue_binding.py" | head -6
