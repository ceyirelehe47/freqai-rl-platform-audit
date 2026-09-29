#!/usr/bin/env bash
set -u
cd /home/cryptorl/projects/crypto_rl
export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
ART=/mnt/f/trading/freqai-rl-audit/stage2_6_2/artifacts/eng_training_bridge_v1
OUT=/mnt/f/trading/tmp_reviewer_tb_v1/cold_read_orig
rm -rf "$OUT"; mkdir -p "$OUT"
$PY -m rl_curriculum.ppo262_cli eng-cold-read \
  --qual-dir "$ART/qualified_input_v1_r2_reference" \
  --auth "$ART/eng_authorization_v1_r2_reference.json" \
  --model-dir "$ART" \
  --out-dir "$OUT" 2>&1 | tail -2
echo "rc=$?"
