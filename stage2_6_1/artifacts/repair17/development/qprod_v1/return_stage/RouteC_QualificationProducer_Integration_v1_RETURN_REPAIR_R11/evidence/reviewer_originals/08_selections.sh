#!/bin/bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/cryptorl/projects/crypto_rl/src
cd /home/cryptorl/projects/crypto_rl
T=tests/route_c_stage2_6_1
echo "== A. five cue files collected (r9cc/r10cc/r9eval/r10eval/r17binding) =="
$PY -m pytest -q -p no:cacheprovider --collect-only "$T/test_curriculum261_r10_cue_contract.py" "$T/test_curriculum261_r9_cue_contract.py" "$T/test_curriculum261_r10_cue_eval.py" "$T/test_curriculum261_r9_cue_eval.py" "$T/test_curriculum261_r17_design_cue_binding.py" 2>&1 | tail -1
echo "== B. contract+binding only =="
$PY -m pytest -q -p no:cacheprovider --collect-only "$T/test_curriculum261_r9_cue_contract.py" "$T/test_curriculum261_r10_cue_contract.py" "$T/test_curriculum261_r17_design_cue_binding.py" 2>&1 | tail -1
echo "== C. def-test counts at R10 seal 58d1a9ce =="
for f in test_curriculum261_r10_cue_contract test_curriculum261_r9_cue_contract test_curriculum261_r10_cue_eval test_curriculum261_r9_cue_eval test_curriculum261_r17_design_cue_binding; do
  echo "$f=$(grep -c '^def test_\|^    def test_' /mnt/f/trading/tmp_r11/reviewer/cuedefs_$f.txt 2>/dev/null || echo na)"
done
