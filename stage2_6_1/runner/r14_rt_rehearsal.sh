#!/usr/bin/env bash
# R14:R14RealArtifactCliRoundTrip-v1 真实 CLI 全链 rehearsal(长任务)
# 先清理 rehearsal 目录(允许 Commit A 前的工程重跑),再一次性执行。
set -uo pipefail
cd "$HOME/projects/crypto_rl"
source activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH="$HOME/projects/crypto_rl/src"
ART="$HOME/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair14"
LOG="$HOME/projects/crypto_rl/r14_rt_rehearsal.log"

if [ "${R14_RT_FRESH:-1}" = "1" ]; then
  rm -rf "$ART/real_artifact_rehearsal"
fi

{
  date -u +"start %Y-%m-%dT%H:%M:%SZ"
  python -m rl_curriculum.curriculum261_r14_cli real-artifact-rehearsal
  echo "rehearsal_rc=$?"
  date -u +"end %Y-%m-%dT%H:%M:%SZ"
} > "$LOG" 2>&1
tail -5 "$LOG"
