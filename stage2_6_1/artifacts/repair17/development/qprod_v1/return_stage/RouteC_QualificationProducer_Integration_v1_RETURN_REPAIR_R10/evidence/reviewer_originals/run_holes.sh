#!/bin/bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
OUT=/mnt/f/trading/tmp_r10/reviewer/probe_out
# --- C21 (deployed tree)
cd ~/projects/crypto_rl || exit 9
export PYTHONPATH=src
echo "== C21 (da5655b5 bytes, deployed) fixture-mode holes =="
"$PY" /mnt/f/trading/tmp_r10/reviewer/probe_holes_fixture_lf.py "$OUT" c21 || exit 8
# --- C20 (52e70a17 bytes, isolated tree)
T=/mnt/f/trading/tmp_r10/reviewer/c20_tree
rm -rf "$T/src"
cp -r ~/projects/crypto_rl/src "$T/src"
git -C /mnt/f/trading/freqai-rl-audit show 52e70a17:stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py > "$T/src/rl_curriculum/curriculum261_r17_cue_contract.py" || exit 8
cd "$T" || exit 7
export PYTHONPATH=src
echo "== C20 (52e70a17 bytes, isolated) fixture-mode holes =="
"$PY" /mnt/f/trading/tmp_r10/reviewer/probe_holes_fixture_lf.py "$OUT" c20 || exit 8
