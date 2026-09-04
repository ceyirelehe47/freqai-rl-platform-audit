#!/usr/bin/env bash
# R14:Commit A 后正式链(§十三顺序;每步独立 CLI 进程 + §十-2 log
# manifest 记录;fail 即停并调用已冻结的 fail-closure 子命令)。
# 用法: bash r14_formal_chain.sh <commit_a_sha> [step]
set -uo pipefail
cd "$HOME/projects/crypto_rl"
source activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH="$HOME/projects/crypto_rl/src"
ART="$HOME/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair14"
LOGD="$HOME/projects/crypto_rl/r14_formal_logs"
RUNNER="/mnt/e/trading/freqai-rl-audit/stage2_6_1/runner"
mkdir -p "$LOGD"
FREEZE_SHA="${1:?需要 Commit A SHA}"
ONLY="${2:-}"

run() {
  local name="$1"; shift
  if [ -n "$ONLY" ] && [ "$ONLY" != "$name" ]; then return 0; fi
  python "$RUNNER/r14_run_step.py" "$name" "$@"
  local rc=$?
  if [ $rc -ne 0 ]; then
    echo "STOP at $name (rc=$rc);调用已冻结 fail-closure(§十四)"
    python -m rl_curriculum.curriculum261_r14_cli fail-closure \
      --out-dir "$ART" --verdict FAIL \
      --reason "formal chain step $name rc=$rc(R14 §十四:停止;只读收尾;不创建新代码;下一轮必须 R15)" \
      >> "$LOGD/fail_closure.log" 2>&1 || true
    exit $rc
  fi
}

# §五:provenance 在任何正式数据前锁定(一次且仅一次;已存在则
# write 拒绝,幂等跳过)
if [ ! -f "$ART/gate_topology_reconciliation.json" ]; then
  run provenance-lock provenance-lock
fi

run determinism-matrix determinism-matrix
run audit            audit --code-freeze-sha "$FREEZE_SHA"
run cue-audit        cue-audit
run plan-roundtrip   plan-roundtrip
run design-plan-lock design-plan-lock
run design           design
run calibrate        calibrate
run preflight-static preflight-static
run lock-plan        lock-plan
run preflight-sealed preflight-sealed
run qualify          qualify
run smoke            smoke --out-dir "$ART"
run full-cold        full-cold-reader-check --artifacts-dir "$ART" \
                       --expect-verdict PASS --out-dir "$ART"

# full-cold 回归套件(final/smoke/reader 全 PASS 后的最终验收)
if [ -z "$ONLY" ] || [ "$ONLY" = "full-cold" ]; then
  echo "=== [regression-full-cold] start $(date -u +%H:%M:%S) ==="
  python "$RUNNER/regression_runner.py" full-cold \
    > "$LOGD/regression_fullcold.log" 2>&1
  rc=$?
  tail -3 "$LOGD/regression_fullcold.log"
  echo "=== [regression-full-cold] rc=$rc ==="
  if [ $rc -ne 0 ]; then
    python -m rl_curriculum.curriculum261_r14_cli fail-closure \
      --out-dir "$ART" --verdict FAIL \
      --reason "regression full-cold rc=$rc(R14 §十四)" \
      >> "$LOGD/fail_closure.log" 2>&1 || true
    exit $rc
  fi
fi

# 成功路径:report reader + raw log 完整性机器检查(§十-2)
if [ -z "$ONLY" ]; then
  python -m rl_curriculum.curriculum261_r14_cli report-read \
    --artifacts-dir "$ART" \
    --out-file "$ART/r14_report_values.json" \
    > "$LOGD/report_read.log" 2>&1
  python -m rl_curriculum.curriculum261_r14_cli verify-formal-logs \
    --manifest "$LOGD/r14_formal_log_manifest.jsonl" \
    --stopped-at full-cold --out-dir "$ART" \
    > "$LOGD/verify_formal_logs.log" 2>&1
  vrc=$?
  echo "verify-formal-logs rc=$vrc"
  if [ $vrc -ne 0 ]; then
    python -m rl_curriculum.curriculum261_r14_cli fail-closure \
      --out-dir "$ART" --verdict FAIL \
      --reason "verify-formal-logs rc=$vrc(raw log multiset 不完整;§十)" \
      >> "$LOGD/fail_closure.log" 2>&1 || true
    exit $vrc
  fi
fi

echo "formal chain complete $(date -u +%Y-%m-%dT%H:%M:%SZ)"
