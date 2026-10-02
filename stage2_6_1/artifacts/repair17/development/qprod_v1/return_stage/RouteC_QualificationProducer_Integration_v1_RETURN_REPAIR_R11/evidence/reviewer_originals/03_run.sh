#!/bin/bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
rm -rf /tmp/r11rev_c22_pkg
mkdir -p /tmp/r11rev_c22_pkg/rl_curriculum
SRC=/home/cryptorl/projects/crypto_rl/src/rl_curriculum
for f in "$SRC"/*; do ln -s "$f" /tmp/r11rev_c22_pkg/rl_curriculum/; done
rm /tmp/r11rev_c22_pkg/rl_curriculum/curriculum261_r17_cue_contract.py
cp /tmp/r11rev_c22_cue.py /tmp/r11rev_c22_pkg/rl_curriculum/curriculum261_r17_cue_contract.py
echo "== C22 shadow pkg sha =="
sha256sum /tmp/r11rev_c22_pkg/rl_curriculum/curriculum261_r17_cue_contract.py
echo "== PRE-FIX (C22 bytes) probe =="
$PY /tmp/r11_probe.py c22 2>&1
echo "rc_c22=$?"
echo "== POST-FIX (deployed C23 bytes) probe =="
$PY /tmp/r11_probe.py c23 2>&1
echo "rc_c23=$?"
echo "== pycache residue check in deploy src =="
find /home/cryptorl/projects/crypto_rl/src/rl_curriculum/__pycache__ -name 'curriculum261_r17_cue_contract*' 2>/dev/null | wc -l
ls /tmp/r11rev_c22_pkg/rl_curriculum/__pycache__ 2>/dev/null | wc -l
