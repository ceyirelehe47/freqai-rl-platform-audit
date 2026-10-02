#!/usr/bin/env bash
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
D=/home/cryptorl/projects/crypto_rl
cd "$D"
for f in test_curriculum261_qprod_r10_fixes.py test_curriculum261_qprod_r11_fixes.py test_curriculum261_qprod_r12_fixes.py; do
  echo -n "$f deploy_sha256="; sha256sum "tests/route_c_stage2_6_1/$f" | cut -d' ' -f1
done
echo "--- run ---"
$PY -m pytest tests/route_c_stage2_6_1/test_curriculum261_qprod_r10_fixes.py tests/route_c_stage2_6_1/test_curriculum261_qprod_r11_fixes.py tests/route_c_stage2_6_1/test_curriculum261_qprod_r12_fixes.py -q 2>&1 | tail -15
echo "pins_rc=${PIPESTATUS[0]}"
