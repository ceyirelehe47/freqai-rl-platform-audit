#!/usr/bin/env bash
# RouteC_FormalLaunch_Preparation_v1: 对最终候选 e1f23d7e 用既有
# r21_full_collection_regression 流程采集 261 完整回归证据
# (collect-only+auditor/lifecycle+分片执行+junit+record+自验)。
# 零新增原生生成/fit/optimizer/模型加载。
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
DEPLOY=/home/cryptorl/projects/crypto_rl
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
REPO=/mnt/f/trading/freqai-rl-audit
EVD=$REPO/stage2_6_1/artifacts/repair17/development/formal_launch_prep_v1/evidence/regress261
mkdir -p "$EVD"
cd "$DEPLOY"
CAND=$(git -C "$REPO" rev-parse HEAD)
echo "candidate=$CAND" | tee "$EVD/CANDIDATE.txt"
"$PY" stage2_6_1_runner/r21_full_collection_regression.py \
  --repo "$REPO" --commit-a "$CAND" --deploy-root "$DEPLOY" \
  --out-dir "$EVD/full_regression_v1_c26" \
  --target tests/route_c_stage2_6_1 \
  --label r21_full_collection_regression_qprod_flp_v1_c26 \
  > "$EVD/r21_run.stdout.txt" 2> "$EVD/r21_run.stderr.txt"
rc=$?
echo "rc=$rc" | tee -a "$EVD/CANDIDATE.txt"
tail -3 "$EVD/r21_run.stdout.txt"
exit $rc
