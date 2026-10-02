#!/bin/bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
D=/home/cryptorl/projects/crypto_rl
echo "== interpreter =="
$PY -c "import sys; print(sys.version.split()[0], sys.executable)"
echo "== deployed file sha256 =="
sha256sum "$D/stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py" "$D/stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_qprod_r11_fixes.py" 2>&1
echo "== pycache audit (probe residue check) =="
ls "$D/stage2_6_1/src/rl_curriculum/__pycache__/" 2>/dev/null | grep -c "curriculum261_r17_cue_contract" || true
find "$D/stage2_6_1/tests/route_c_stage2_6_1/__pycache__" -name "*.pyc" 2>/dev/null | wc -l
