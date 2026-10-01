#!/usr/bin/env bash
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
DEPLOY=/home/cryptorl/projects/crypto_rl
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
REPO=/mnt/f/trading/freqai-rl-audit
OUT=/mnt/f/trading/tmp_r8/reviewer
cd "$DEPLOY"

echo "==== [0] E-drive bridge ===="
ls -ld /mnt/e/trading/freqai-rl-audit 2>&1

echo "==== [1] deploy-vs-repo byte identity (changed file + tests) ===="
sha256sum "$DEPLOY/src/rl_curriculum/curriculum261_r17_cue_contract.py" \
          "$REPO/stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py" | awk '{print $1" "NF" "$2}'
sha256sum "$DEPLOY/tests/route_c_stage2_6_1/test_curriculum261_qprod_r8_fixes.py" \
          "$REPO/stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_qprod_r8_fixes.py" | awk '{print $1" "$2}'
sha256sum "$DEPLOY/tests/route_c_stage2_6_1/conftest.py"
git -C "$REPO" rev-parse HEAD

echo "==== [2] extract pre-R8 module (044a0307) for digest comparison ===="
git -C "$REPO" show 044a0307:stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py > /tmp/old_cue_r8_044a0307.py
wc -l /tmp/old_cue_r8_044a0307.py

echo "==== [3] independent probe (own values) ===="
export PYTHONPATH="$DEPLOY/src"
"$PY" /mnt/f/trading/tmp_r8/reviewer/probe_r8_independent.py 2>&1
echo "probe-rc=$?"

echo "==== [4] pinned R8 tests ===="
unset PYTHONPATH
"$PY" -m pytest tests/route_c_stage2_6_1/test_curriculum261_qprod_r8_fixes.py -q 2>&1 | tail -3
echo "pin-rc=$?"

echo "==== [5] qprod face ===="
"$PY" -m pytest tests/route_c_stage2_6_1 -k "qprod" -q 2>&1 | tail -3
echo "qprod-rc=$?"

echo "==== [6] r8/r9/r10/r17 cue-contract face ===="
"$PY" -m pytest \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_r8_fixes.py \
  tests/route_c_stage2_6_1/test_curriculum261_r9_cue_contract.py \
  tests/route_c_stage2_6_1/test_curriculum261_r10_cue_contract.py \
  $("$PY" - << 'PYL'
import glob
print(" ".join(sorted(glob.glob("tests/route_c_stage2_6_1/*r17*cue*"))))
PYL
) -q 2>&1 | tail -3
echo "cue-rc=$?"
