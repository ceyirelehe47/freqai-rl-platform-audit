#!/bin/bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
cd ~/projects/crypto_rl || exit 9
export PYTHONPATH=src
"$PY" /mnt/f/trading/tmp_r10/reviewer/digest_probe.py C21
T=/mnt/f/trading/tmp_r10/reviewer/c20_tree
rm -rf "$T/src"
cp -r ~/projects/crypto_rl/src "$T/src"
git -C /mnt/f/trading/freqai-rl-audit show 52e70a17:stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py > "$T/src/rl_curriculum/curriculum261_r17_cue_contract.py"
cd "$T"
export PYTHONPATH=src
"$PY" /mnt/f/trading/tmp_r10/reviewer/digest_probe.py C20
