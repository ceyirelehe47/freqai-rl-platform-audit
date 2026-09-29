#!/usr/bin/env bash
set -u
cd /home/cryptorl/projects/crypto_rl
export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
ART=/mnt/f/trading/freqai-rl-audit/stage2_6_2/artifacts/eng_training_bridge_v1
OUT=/mnt/f/trading/tmp_reviewer_tb_v1/eng_run_reviewe
rm -rf "$OUT"; mkdir -p "$OUT"
$PY -m rl_curriculum.ppo262_cli eng-run \
  --qual-dir "$ART/qualified_input_v1_r2_reference" \
  --auth "$ART/eng_authorization_v1_r2_reference.json" \
  --scope engineering \
  --out-dir "$OUT" \
  --ledger "$ART/ppo262e_quota_ledger.jsonl" 2>&1 | tail -3
echo "eng-run rc=$?"
$PY -m rl_curriculum.ppo262_cli eng-cold-read \
  --qual-dir "$ART/qualified_input_v1_r2_reference" \
  --auth "$ART/eng_authorization_v1_r2_reference.json" \
  --model-dir "$OUT" \
  --out-dir "$OUT/cold_read" 2>&1 | tail -3
echo "cold-read rc=$?"
