#!/bin/bash
# RouteC_QualifiedInput_TrainingBridge_v1: 工程端到端运行
# fixture 构建(v1+v2) -> eng-run(E01 bank + E02 256步 PPO) -> 新进程冷读(E03)
# 固定数据集重放配额:本脚本消耗 1 次(replay #1);reviewer 若复验使用
# 独立 out-dir 且同一 ledger 文件(共享计数)。
set -uo pipefail
DEPLOY=$HOME/projects/crypto_rl
ART=/mnt/f/trading/freqai-rl-audit/stage2_6_2/artifacts/eng_training_bridge_v1
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
cd "$DEPLOY"
source activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1

mkdir -p "$ART"
LEDGER=$ART/ppo262e_quota_ledger.jsonl

echo "=== [1/5] fixture build (v1 + v2) ==="
$PY -m rl_curriculum.ppo262_cli eng-fixture-build --out-dir "$ART" --pack v1_r2_reference
rc1=$?
$PY -m rl_curriculum.ppo262_cli eng-fixture-build --out-dir "$ART" --pack v2_perturbed
rc2=$?
echo "rc_v1=$rc1 rc_v2=$rc2"

echo "=== [2/5] eng-input-lock positive (engineering scope) ==="
$PY -m rl_curriculum.ppo262_cli eng-input-lock \
  --qual-dir "$ART/qualified_input_v1_r2_reference" \
  --auth "$ART/eng_authorization_v1_r2_reference.json" > "$ART/eng_input_lock_v1.json" 2>&1
rc3=$?
echo "rc_input_lock=$rc3"

echo "=== [3/5] eng-route-check (v2 perturbed pack) ==="
$PY -m rl_curriculum.ppo262_cli eng-route-check \
  --qual-dir "$ART/qualified_input_v2_perturbed" \
  --auth "$ART/eng_authorization_v2_perturbed.json" \
  --out-dir "$ART" > "$ART/eng_route_check_stdout.json" 2>&1
rc4=$?
echo "rc_route=$rc4"

echo "=== [3b] G01: formal scope rejection (engineering fixture/auth) ==="
$PY -m rl_curriculum.ppo262_cli eng-input-lock \
  --qual-dir "$ART/qualified_input_v1_r2_reference" \
  --auth "$ART/eng_authorization_v1_r2_reference.json" \
  --scope formal > "$ART/eng_input_lock_formal_reject.json" 2>&1
rc_formal=$?
echo "rc_formal_reject(expect 2)=$rc_formal"

echo "=== [4/5] eng-run (E01 native bank 6 episodes + E02 256-step PPO) ==="
timeout 600 $PY -m rl_curriculum.ppo262_cli eng-run \
  --qual-dir "$ART/qualified_input_v1_r2_reference" \
  --auth "$ART/eng_authorization_v1_r2_reference.json" \
  --out-dir "$ART" --ledger "$LEDGER" 2>&1 | tee "$ART/eng_run_stdout.json"
rc5=${PIPESTATUS[0]}
echo "rc_eng_run=$rc5"

echo "=== [5/5] eng-cold-read (new process, E03) ==="
$PY -m rl_curriculum.ppo262_cli eng-cold-read \
  --qual-dir "$ART/qualified_input_v1_r2_reference" \
  --auth "$ART/eng_authorization_v1_r2_reference.json" \
  --model-dir "$ART" --out-dir "$ART" \
  --profile ppo262_engineering_v1 2>&1 | tee "$ART/eng_cold_read_stdout.json"
rc6=${PIPESTATUS[0]}
echo "rc_cold_read=$rc6"

echo "=== quota ledger ==="
cat "$LEDGER" || true
printf 'rcs: fixture_v1=%s fixture_v2=%s input_lock=%s route=%s formal_reject=%s eng_run=%s cold_read=%s\n' \
  "$rc1" "$rc2" "$rc3" "$rc4" "$rc_formal" "$rc5" "$rc6" > "$ART/eng_run_rcs.txt"
cat "$ART/eng_run_rcs.txt"
