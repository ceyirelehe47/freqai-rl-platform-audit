#!/usr/bin/env bash
# QProd R4 R01: 对最终新候选(C15=1139887e+)用**既有** r21_full_collection_regression
# 流程采集 261 完整回归证据(collect-only+auditor/lifecycle+分片执行+junit+record+
# 自验)。零新增原生/fit/optimizer。
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
DEPLOY=/home/cryptorl/projects/crypto_rl
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
REPO=/mnt/f/trading/freqai-rl-audit
EVD=$REPO/stage2_6_1/artifacts/repair17/development/qprod_v1/repair_round4_notclosed/evidence/regress_v6
mkdir -p "$EVD"
cd "$DEPLOY"
CAND=$(git -C "$REPO" rev-parse HEAD)
echo "candidate=$CAND" | tee "$EVD/CANDIDATE.txt"
# repo runner → deploy runner 已由 r21_sync 同步;直接以部署面执行
"$PY" stage2_6_1_runner/r21_full_collection_regression.py \
  --repo "$REPO" --commit-a "$CAND" --deploy-root "$DEPLOY" \
  --out-dir "$EVD/full_regression_v6_c15" \
  --target tests/route_c_stage2_6_1 \
  --label r21_full_collection_regression_qprod_r5_c15 \
  > "$EVD/r21_run.stdout.txt" 2> "$EVD/r21_run.stderr.txt"
rc=$?
echo "rc=$rc" | tee -a "$EVD/CANDIDATE.txt"
tail -3 "$EVD/r21_run.stdout.txt"
exit $rc
