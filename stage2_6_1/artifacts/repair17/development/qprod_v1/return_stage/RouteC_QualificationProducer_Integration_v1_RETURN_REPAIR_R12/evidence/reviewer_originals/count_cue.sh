#!/usr/bin/env bash
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
cd /home/cryptorl/projects/crypto_rl
for f in r9_cue_contract r9_cue_eval r10_cue_contract r10_cue_eval r17_design_cue_binding r25_cue_dev_entry; do
  n=$($PY -m pytest tests/route_c_stage2_6_1/test_curriculum261_$f.py --collect-only -q 2>/dev/null | tail -1)
  echo "$f : $n"
done
