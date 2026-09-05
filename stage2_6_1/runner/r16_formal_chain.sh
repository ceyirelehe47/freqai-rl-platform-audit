#!/usr/bin/env bash
# R16:Commit A 后正式链——泛型编排,零流程列表,LF 执行面。
# 步骤顺序的唯一来源 = curriculum261_r16_workflow.R16_WORKFLOW_STEPS
# (经 workflow-plan 展开为 JSON;本脚本只做:启动证据 → 环境验证 →
# workflow-plan → chain 执行)。
#
# R15 缺陷的全部修复(§5):
# - CRLF 启动失败:本脚本自检 CR 字节,含 CR 立即退出并报告
#   (R15 事故:Agent Windows Write 工具产物 CRLF,bash 解析失败,
#   17 步链在第一步之前未启动);
# - 环境激活失败被吞(source ... || true):改为激活失败即拒绝,
#   不使用未知解释器继续;
# - /mnt/e 硬编码 RUNNER:执行面全部从 WSL 本地 PROJECT_ROOT 解析
#   (r16_sync.sh 同步;§4.3 正式协调限定已验证本地文件系统);
# - bootstrap 失败被写成 provenance-verify 已执行失败:改为
#   --failed-step bootstrap(workflow 前缀为空;§5.4);
# - 无入口证据:启动请求证据先于任何 python 调用,由 bash 原生
#   追加(不依赖 workflow 成功导入;interpreter 起不来时证据仍在)。
#
# 用法: bash r16_formal_chain.sh <commit_a_sha>
# 环境: R16_PROJECT_ROOT(缺省 $HOME/projects/crypto_rl)

# ---- LF 自检(R15 事故防御;必须在 set -euo pipefail 之前) ----
# R15 实证:全 CRLF 脚本死于 "set: pipefail: invalid option name"
# (第 22 行),自检若在 set 之后永远执行不到。本自检防的是混合
# 行尾(恰好可解析但污染变量);全 CRLF 场景 bash 自身拒绝解析,
# 真正防线在上游字节检查(.gitattributes + sync tr -d CR +
# freeze 前执行面字节验证)。
if grep -q $'\r' "$0"; then
  echo "FATAL: $0 含 CR 字节(CRLF 行尾);拒绝启动。" >&2
  echo "R15 同款缺陷;执行面字节检查失败。" >&2
  exit 99
fi

set -euo pipefail

PROJECT_ROOT="${R16_PROJECT_ROOT:-$HOME/projects/crypto_rl}"
RUNNER="$PROJECT_ROOT/stage2_6_1_runner"
ART="$PROJECT_ROOT/artifacts/route_c_stage2_6_1_repair16"
LOGD="$PROJECT_ROOT/r16_formal_logs"
LAUNCH_EVIDENCE="$LOGD/r16_launch_evidence.jsonl"
mkdir -p "$LOGD" "$ART"

# ---- 启动请求证据(bash 原生;先于任何 python;§5.4) ----
# 语义 = "启动请求已发生",不是"正式会话已被接受"(后者由
# r16_bootstrap_accepted.json 表达;两个文件分开,避免被拒绝的
# 请求写入正在运行的正式 manifest)。
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
emit_launch() {
  printf '{"event":"%s","utc":"%s","argv":"%s","pid":%s}\n' \
    "$1" "$(ts)" "$2" "$$" >> "$LAUNCH_EVIDENCE"
}
emit_launch "launch_requested" "r16_formal_chain.sh $*"

# ---- 环境激活:失败即拒绝(不 || true;§5.2) ----
cd "$PROJECT_ROOT"
if [ ! -f ./activate-freqtrade.sh ]; then
  emit_launch "bootstrap_failed" "activate-freqtrade.sh 缺失"
  echo "FATAL: $PROJECT_ROOT/activate-freqtrade.sh 不存在" >&2
  exit 98
fi
# set -e 下 source 失败(返回非零)即终止;activate 脚本内部
# conda activate 失败会以非零退出。
source ./activate-freqtrade.sh
emit_launch "environment_activated" "conda=$CONDA_DEFAULT_ENV"

# ---- 解释器与模块来源验证(§5.2) ----
if ! python - <<'PYVERIFY'
import sys
sys.path.insert(0, "src")
import rl_curriculum
path = rl_curriculum.__file__
assert "crypto_rl/src" in path, f"module origin 异常: {path}"
from rl_curriculum.curriculum261_r16_workflow import (
    R16_WORKFLOW_VERSION)
assert R16_WORKFLOW_VERSION == "AuthoritativeWorkflow-v1"
PYVERIFY
then
  emit_launch "bootstrap_failed" "interpreter/module origin 验证失败"
  echo "FATAL: 解释器或模块来源验证失败" >&2
  exit 97
fi
export PYTHONPATH="$PROJECT_ROOT/src"
emit_launch "bootstrap_verified" "python=$(python -V 2>&1)"

FREEZE_SHA="${1:?需要 Commit A SHA}"

# ---- workflow-plan(仍在 bootstrap 边界;失败 = bootstrap 失败) ----
echo "=== [chain-plan] $(ts) ==="
wrc=0
python -m rl_curriculum.curriculum261_r16_cli workflow-plan \
    --profile formal --out-dir "$ART" --freeze-sha "$FREEZE_SHA" \
    --out-file "$ART/r16_workflow_plan_formal.json" \
    > "$LOGD/workflow_plan.log" 2>&1 || wrc=$?
if [ "$wrc" -ne 0 ]; then
  tail -3 "$LOGD/workflow_plan.log" || true
  emit_launch "bootstrap_failed" "workflow-plan rc=$wrc(结构校验失败)"
  echo "STOP: workflow-plan 失败;按 bootstrap 边界封口(§5.4)" >&2
  python -m rl_curriculum.curriculum261_r16_cli fail-closure \
    --out-dir "$ART" --failed-step bootstrap --verdict FAIL \
    --reason "workflow-plan rc=$wrc(权威流程结构校验失败;R16 §5.4:失败发生在 bootstrap,workflow 前缀为空,首个未执行节点 provenance-verify 未开始;停止;只读收尾;不创建新代码)" \
    >> "$LOGD/fail_closure.log" 2>&1 || true
  exit "$wrc"
fi
tail -3 "$LOGD/workflow_plan.log"

# ---- 唯一编排调用:权威 chain 执行器 ----
# (每步独立 subprocess + manifest;provenance-verify 恒执行并记录;
# 任一步失败自动调用已冻结的阶段精确 fail-closure 后停止)
echo "=== [chain formal] $(ts) ==="
if python "$RUNNER/r16_run_step.py" chain \
  "$ART/r16_workflow_plan_formal.json" \
  --result-out "$ART/r16_chain_result.json" \
  > "$LOGD/chain.log" 2>&1; then
  crc=0
else
  crc=$?
fi
tail -5 "$LOGD/chain.log" || true
emit_launch "chain_finished" "rc=$crc"
echo "=== [chain formal] rc=$crc $(ts) ==="
if [ "$crc" -ne 0 ]; then
  echo "formal chain FAILED(execute_workflow_chain 已执行 fail-closure)" >&2
fi
exit "$crc"
