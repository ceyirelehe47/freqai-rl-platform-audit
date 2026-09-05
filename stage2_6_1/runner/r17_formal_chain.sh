#!/usr/bin/env bash
# R17:Commit A 后正式链——薄 shell 入口 + 单协调者。
# 步骤顺序的唯一来源 = curriculum261_r17_workflow.R17_WORKFLOW_STEPS
# (由协调者 cli chain-run 展开执行;本脚本只做:LF 自检 → 启动请求
# 证据 → 环境验证 → chain-run)。
#
# R16 五缺陷(F1-F5)的入口侧闭合:
# - F1 全链所有权:chain-run 在任何正式可变写入之前取得链会话
#   (workflow plan/bootstrap accepted/步骤 artifact/raw log/
#   manifest 全部在会话内);qualify 只是会话内的资格窗口;
# - F3 单写者:journal 只有协调者一个写者;被拒请求写独立
#   rejected_requests/ 区(链会话获取失败 = bootstrap 边界失败,
#   经 fail-closure --failed-step bootstrap 封口);
# - F5 真实入口:rehearsal(r17_rt_rehearsal.sh)与正式走同一
#   shell 入口结构/解释器验证/协调者命令,仅 state root 与
#   profile 不同;
# - 启动请求证据保持链外独立文件(被拒请求不写正式 manifest;
#   与 r16_bootstrap_accepted 的分离语义保留)。
#
# 用法: bash r17_formal_chain.sh <commit_a_sha>
# 环境: R17_PROJECT_ROOT(缺省 $HOME/projects/crypto_rl)

# ---- LF 自检(R15 事故防御;必须在 set -euo pipefail 之前) ----
if grep -q $'\r' "$0"; then
  echo "FATAL: $0 含 CR 字节(CRLF 行尾);拒绝启动。" >&2
  echo "R15 同款缺陷;执行面字节检查失败。" >&2
  exit 99
fi

set -euo pipefail

PROJECT_ROOT="${R17_PROJECT_ROOT:-$HOME/projects/crypto_rl}"
RUNNER="$PROJECT_ROOT/stage2_6_1_runner"
ART="$PROJECT_ROOT/artifacts/route_c_stage2_6_1_repair17"
LOGD="$PROJECT_ROOT/r17_formal_logs"
LAUNCH_EVIDENCE="$LOGD/r17_launch_evidence.jsonl"
mkdir -p "$LOGD" "$ART"

# ---- 启动请求证据(bash 原生;先于任何 python;链外) ----
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
emit_launch() {
  printf '{"event":"%s","utc":"%s","argv":"%s","pid":%s}\n' \
    "$1" "$(ts)" "$2" "$$" >> "$LAUNCH_EVIDENCE"
}
emit_launch "launch_requested" "r17_formal_chain.sh $*"

# ---- 环境激活:失败即拒绝(不 || true) ----

# ---- 存储天花板检查(用户设定 300GB;超过拒绝启动 fail closed) ----
# WSL 根文件系统已用量(df Used,稀疏感知)超过 300GB 时,任何
# rehearsal/正式链启动被拒绝(防止缓存增长把宿主盘写爆)。
STORAGE_CEILING_GB=300
USED_KB=$(df -BK --output=used / | tail -1 | tr -dc '0-9')
USED_GB=$((USED_KB / 1024 / 1024))
if [ "$USED_GB" -ge "$STORAGE_CEILING_GB" ]; then
  emit_launch "bootstrap_failed" "storage ceiling: WSL used ${USED_GB}GB >= ${STORAGE_CEILING_GB}GB;清理 ~/.cache/rl_builder_bundles 后重试"
  echo "FATAL: WSL 已用 ${USED_GB}GB 超过 ${STORAGE_CEILING_GB}GB 天花板;拒绝启动(先清理缓存)" >&2
  exit 96
fi
emit_launch "storage_checked" "used=${USED_GB}GB ceiling=${STORAGE_CEILING_GB}GB"

cd "$PROJECT_ROOT"
if [ ! -f ./activate-freqtrade.sh ]; then
  emit_launch "bootstrap_failed" "activate-freqtrade.sh 缺失"
  echo "FATAL: $PROJECT_ROOT/activate-freqtrade.sh 不存在" >&2
  exit 98
fi
source ./activate-freqtrade.sh
emit_launch "environment_activated" "conda=$CONDA_DEFAULT_ENV"

# ---- 解释器与模块来源验证 ----
if ! python - <<'PYVERIFY'
import sys
sys.path.insert(0, "src")
import rl_curriculum
path = rl_curriculum.__file__
assert "crypto_rl/src" in path, f"module origin 异常: {path}"
from rl_curriculum.curriculum261_r17_workflow import (
    R17_WORKFLOW_VERSION)
assert R17_WORKFLOW_VERSION == "AuthoritativeWorkflow-v1"
PYVERIFY
then
  emit_launch "bootstrap_failed" "interpreter/module origin 验证失败"
  echo "FATAL: 解释器或模块来源验证失败" >&2
  exit 97
fi
export PYTHONPATH="$PROJECT_ROOT/src"
emit_launch "bootstrap_verified" "python=$(python -V 2>&1)"

FREEZE_SHA="${1:?需要 Commit A SHA}"

# ---- 部署状态根绑定(准入解析;正式唯一) ----
export CURRICULUM261_R17_DEPLOYED_STATE_ROOT="${R17_STATE_ROOT:-$ART/state}"
export CURRICULUM261_R17_STATE_ROOT="$CURRICULUM261_R17_DEPLOYED_STATE_ROOT"

# ---- 唯一编排调用:协调者 chain-run(会话 → plan → 17 步 → 终态) ----
# workflow plan 由协调者在会话内生成;plan 结构校验失败 =
# 协调者自身失败,按 bootstrap 边界封口(§5.4:workflow 前缀为空)。
echo "=== [chain-run formal] $(ts) ==="
wrc=0
python -m rl_curriculum.curriculum261_r17_cli chain-run \
    --out-dir "$ART" --freeze-sha "$FREEZE_SHA" \
    > "$LOGD/chain_run.log" 2>&1 || wrc=$?
tail -5 "$LOGD/chain_run.log" || true
if [ "$wrc" -ne 0 ]; then
  # 协调者失败(会话获取被拒/plan 失败/步骤失败)——被拒与
  # 失败的区分由协调者落盘(request 证据 vs journal 事件);
  # 入口只按 bootstrap 边界封口 workflow 前缀为空的情形:
  # plan 文件不存在 ⇒ 任何步骤都未启动。
  if [ ! -f "$ART/r17_workflow_plan_formal.json" ]; then
    python -m rl_curriculum.curriculum261_r17_cli fail-closure \
      --out-dir "$ART" --failed-step bootstrap --verdict FAIL \
      --reason "chain-run rc=$wrc 且 workflow plan 未生成(协调者会话获取或结构校验失败;R17 §5.4:失败发生在 bootstrap,workflow 前缀为空,首个未执行节点 provenance-verify 未开始;停止;只读收尾)" \
      >> "$LOGD/fail_closure.log" 2>&1 || true
  fi
fi
emit_launch "chain_finished" "rc=$wrc"
echo "=== [chain-run formal] rc=$wrc $(ts) ==="
exit "$wrc"
