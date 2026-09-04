#!/usr/bin/env bash
# R15:Commit A 后正式链(§十三)——泛型编排,零流程列表。
# 步骤顺序的唯一来源 = curriculum261_r15_workflow.R15_WORKFLOW_STEPS
# (经 workflow-plan 展开为 JSON;本脚本只做:生成 plan → chain 执行)。
# R14 缺陷修复:r14_formal_chain.sh 硬编码列表缺 preplan-smoke 步,
# plan-roundtrip 死于 FileNotFoundError——R15 结构上不再可能
# (缺 producer 在 workflow validation/步骤入口即 PrerequisiteError)。
# 用法: bash r15_formal_chain.sh <commit_a_sha>
set -uo pipefail
cd "$HOME/projects/crypto_rl"
source activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH="$HOME/projects/crypto_rl/src"
ART="$HOME/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair15"
LOGD="$HOME/projects/crypto_rl/r15_formal_logs"
RUNNER="/mnt/e/trading/freqai-rl-audit/stage2_6_1/runner"
mkdir -p "$LOGD" "$ART"
FREEZE_SHA="${1:?需要 Commit A SHA}"

echo "=== [chain-plan] $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
python -m rl_curriculum.curriculum261_r15_cli workflow-plan \
  --profile formal --out-dir "$ART" --freeze-sha "$FREEZE_SHA" \
  --out-file "$ART/r15_workflow_plan_formal.json" \
  > "$LOGD/workflow_plan.log" 2>&1
wrc=$?
tail -3 "$LOGD/workflow_plan.log"
if [ $wrc -ne 0 ]; then
  echo "STOP: workflow-plan rc=$wrc(结构校验失败;§十四)"
  python -m rl_curriculum.curriculum261_r15_cli fail-closure \
    --out-dir "$ART" --failed-step provenance-verify --verdict FAIL \
    --reason "workflow-plan rc=$wrc(权威流程结构校验失败;R15 §十四:停止;只读收尾;不创建新代码;下一轮必须 R16)" \
    >> "$LOGD/fail_closure.log" 2>&1 || true
  exit $wrc
fi

echo "=== [chain formal] $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
# 唯一编排调用:权威 chain 执行器(每步独立 subprocess + manifest;
# provenance-verify 恒执行并记录;任一步失败自动调用已冻结的
# 阶段精确 fail-closure 后停止)
python "$RUNNER/r15_run_step.py" chain \
  "$ART/r15_workflow_plan_formal.json" \
  --result-out "$ART/r15_chain_result.json" \
  > "$LOGD/chain.log" 2>&1
crc=$?
tail -5 "$LOGD/chain.log"
echo "=== [chain formal] rc=$crc $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
if [ $crc -ne 0 ]; then
  echo "formal chain FAILED(execute_workflow_chain 已执行 fail-closure)"
fi
exit $crc
