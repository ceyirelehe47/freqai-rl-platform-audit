#!/bin/bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/cryptorl/projects/crypto_rl/src
cd /home/cryptorl/projects/crypto_rl
T=tests/route_c_stage2_6_1
for f in test_curriculum261_r10_cue_contract.py test_curriculum261_r9_cue_contract.py test_curriculum261_r10_cue_eval.py test_curriculum261_r9_cue_eval.py test_curriculum261_r17_design_cue_binding.py test_curriculum261_r25_cue_dev_entry.py; do
  n=$($PY -m pytest -q -p no:cacheprovider --collect-only "$T/$f" 2>/dev/null | grep -c "::")
  echo "$f collected=$n"
done
