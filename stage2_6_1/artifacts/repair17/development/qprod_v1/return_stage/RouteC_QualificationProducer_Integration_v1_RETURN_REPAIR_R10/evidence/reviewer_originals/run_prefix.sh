#!/bin/bash
set -u
T=/mnt/f/trading/tmp_r10/reviewer/c20_tree
rm -rf "$T"
mkdir -p "$T"
cd ~/projects/crypto_rl || exit 9
cp -r src/rl_curriculum "$T/src_rl_curriculum"
mkdir -p "$T/src"
mv "$T/src_rl_curriculum" "$T/src/rl_curriculum"
git -C /mnt/f/trading/freqai-rl-audit show 52e70a17:stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py > "$T/src/rl_curriculum/curriculum261_r17_cue_contract.py" || exit 8
cd "$T" || exit 7
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python "$T/probe_pre.py" 2>&1 | tail -20
echo "PREFIX_RC=$?"
