#!/usr/bin/env bash
# R13:Commit A 后正式链(每步独立 CLI 进程;fail 即停)
# 用法: bash r13_formal_chain.sh <commit_a_sha> [step]
set -uo pipefail
cd "$HOME/projects/crypto_rl"
source activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH="$HOME/projects/crypto_rl/src"
ART="$HOME/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair13"
LOGD="$HOME/projects/crypto_rl/r13_formal_logs"
mkdir -p "$LOGD"
FREEZE_SHA="${1:?需要 Commit A SHA}"
ONLY="${2:-}"

run() {
  local name="$1"; shift
  if [ -n "$ONLY" ] && [ "$ONLY" != "$name" ]; then return 0; fi
  echo "=== [$name] $(date -u +%H:%M:%S) ==="
  python -m rl_curriculum.curriculum261_r13_cli "$@" \
    > "$LOGD/${name}.log" 2>&1
  local rc=$?
  tail -3 "$LOGD/${name}.log"
  echo "=== [$name] rc=$rc ==="
  if [ $rc -ne 0 ]; then echo "STOP at $name (rc=$rc)"; exit $rc; fi
}

run audit            audit --code-freeze-sha "$FREEZE_SHA"
run cue-audit        cue-audit
run preplan-smoke    preplan-smoke
run plan-roundtrip   plan-roundtrip
run design-plan-lock design-plan-lock
run design           design
run calibrate        calibrate
run preflight-static preflight-static
run lock-plan        lock-plan
run preflight-sealed preflight-sealed
run qualify          qualify
run smoke            smoke
run namespace-integrity namespace-integrity
echo "formal chain complete $(date -u +%Y-%m-%dT%H:%M:%SZ)"
