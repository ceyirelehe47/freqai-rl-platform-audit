#!/usr/bin/env bash
set -u
export PYTHONDONTWRITEBYTECODE=1
cd /home/cryptorl/projects/crypto_rl
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
for f in test_curriculum261_qprod_r8_fixes test_curriculum261_r9_cue_contract test_curriculum261_r10_cue_contract test_curriculum261_r17_design_cue_binding; do
  n=$("$PY" -m pytest "tests/route_c_stage2_6_1/$f.py" --collect-only -q 2>/dev/null | tail -1)
  echo "$f: $n"
done
n2=$("$PY" -m pytest tests/route_c_stage2_6_2/test_ppo262_qprod_export.py --collect-only -q 2>/dev/null | tail -1)
echo "ppo262_qprod_export: $n2"
nq=$("$PY" -m pytest tests/route_c_stage2_6_2/test_ppo262_qprod_export.py -q 2>&1 | tail -1)
echo "export-run: $nq"
