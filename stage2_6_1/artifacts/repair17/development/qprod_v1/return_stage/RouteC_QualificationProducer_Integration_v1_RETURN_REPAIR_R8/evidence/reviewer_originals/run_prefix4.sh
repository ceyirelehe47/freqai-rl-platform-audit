#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
REPO=/mnt/f/trading/freqai-rl-audit
W=/mnt/f/trading/tmp_r8/reviewer/wsl_tmp
D=/home/cryptorl/projects/crypto_rl/src/rl_curriculum
S=$W/shadow_r8/rl_curriculum
rm -rf "$W"
mkdir -p "$S" "$W/cwd_src"
git -C "$REPO" show 044a0307:stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py > "$W/old_cue_r8_044a0307.py"
for f in "$D"/*.py; do
  b=$(basename "$f")
  if [ "$b" != "curriculum261_r17_cue_contract.py" ]; then ln -sf "$f" "$S/$b"; fi
done
[ -f "$D/__init__.py" ] && ln -sf "$D/__init__.py" "$S/__init__.py"
cp "$W/old_cue_r8_044a0307.py" "$S/curriculum261_r17_cue_contract.py"
ln -s "$W/shadow_r8" "$W/cwd_src/src"
echo "shadow modules: $(ls "$S" | wc -l)"
echo "==== pre-fix repro on C17b bytes (expect h1-h7 all=True holes, controls True) ===="
cd "$W/cwd_src"
PYTHONPATH=/home/cryptorl/projects/crypto_rl/src \
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python \
  "$REPO/stage2_6_1/artifacts/repair17/development/qprod_v1/repair_round8_notclosed/REPRO_R8_PRE_FIX.py" 2>&1 | tail -12
