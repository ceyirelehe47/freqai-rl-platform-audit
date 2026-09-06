#!/usr/bin/env bash
# R17:Commit A 后正式链——薄 shell 入口 + 单协调者。
# 步骤顺序的唯一来源 = curriculum261_r17_workflow.R17_WORKFLOW_STEPS
# (由协调者 cli chain-run 展开执行;本脚本只做:LF 自检 → 启动请求
# 证据 → 环境验证 → chain-run)。
#
# R17 诊断轮 E1 修复(请求日志先隔离):本脚本全部"会话准入前"的
# shell 层输出(chain_run.log/fail_closure.log/launch_evidence.jsonl)
# 只写本请求独立目录 r17_formal_requests/<RUN_ID>/,不写跨请求共享
# 路径——第二个并发请求即使随后被链会话锁拒绝,也不可能截断或
# 混写第一个请求的日志(bash 在命令执行前打开重定向,共享路径的
# `>` 会先截断;这是 E1 缺陷的机制)。被拒请求的 python 层证据由
# 协调者写入部署状态根的 rejected_requests/ 区,与请求目录互补。
# 共享入口段(LF 自检后)见 r17_entry_common.sh;正式产物根 ART 与
# 部署状态根绑定不变(冻结面)。
#
# 用法: bash r17_formal_chain.sh <commit_a_sha>
# 环境: R17_PROJECT_ROOT(缺省 $HOME/projects/crypto_rl)

# ---- LF 自检(R15 事故防御;必须在 set -euo pipefail 之前;含共享段) ----
ENTRY_COMMON="$(cd "$(dirname "$0")" && pwd)/r17_entry_common.sh"
if grep -q $'\r' "$0" "$ENTRY_COMMON"; then
  echo "FATAL: $0 或 r17_entry_common.sh 含 CR 字节(CRLF 行尾);拒绝启动。" >&2
  echo "R15 同款缺陷;执行面字节检查失败。" >&2
  exit 99
fi

set -euo pipefail

PROJECT_ROOT="${R17_PROJECT_ROOT:-$HOME/projects/crypto_rl}"
RUNNER="$PROJECT_ROOT/stage2_6_1_runner"
# shellcheck source=/dev/null
source "$RUNNER/r17_entry_common.sh"

# 正式产物根(冻结面:部署状态根缺省锚定 $ART/state,不可变);
# R17_ART_ROOT 仅供工程测试把 chain-run 顶层产物重定向到隔离区
# (真实正式运行不设置该变量;缺省行为逐位不变)。
ART="${R17_ART_ROOT:-$PROJECT_ROOT/artifacts/route_c_stage2_6_1_repair17}"

# ---- 请求级隔离目录(E1;先于任何重定向与 emit 建立) ----
REQ_ROOT="$PROJECT_ROOT/r17_formal_requests"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)_$$"
REQ_DIR="$REQ_ROOT/$RUN_ID"
mkdir -p "$REQ_DIR" "$ART"
LAUNCH_EVIDENCE="$REQ_DIR/launch_evidence.jsonl"
emit_launch "launch_requested" "r17_formal_chain.sh $* run_id=$RUN_ID"

# ---- 存储天花板 → 环境激活 → 解释器验证(共享入口段) ----
r17_check_storage_ceiling
r17_activate_environment
r17_verify_interpreter

FREEZE_SHA="${1:?需要 Commit A SHA}"

# ---- 部署状态根绑定(准入解析;正式唯一) ----
export CURRICULUM261_R17_DEPLOYED_STATE_ROOT="${R17_STATE_ROOT:-$ART/state}"
export CURRICULUM261_R17_STATE_ROOT="$CURRICULUM261_R17_DEPLOYED_STATE_ROOT"

# ---- 观测接线(观测型;WP1/§5.1) ----
# 仅启动宿主采样器并登记;判定/保护不作用于本入口的业务编排(其进程
# 非本段启动,无登记进程组)。观测不可用时链继续并记录降级(不吞其它
# 失败);EXIT trap 保证被拒请求只关闭自己的观测(M16 被拒者路径)。
if ! r17_monitored_bootstrap "$REQ_DIR" "$RUN_ID"; then
  emit_launch "monitored_bootstrap_degraded" "win observation unavailable"
fi
trap 'r17_monitored_teardown "$REQ_DIR"' EXIT

# ---- 唯一编排调用:协调者 chain-run(会话 → plan → 17 步 → 终态) ----
# workflow plan 由协调者在会话内生成;plan 结构校验失败 =
# 协调者自身失败,按 bootstrap 边界封口(§5.4:workflow 前缀为空)。
echo "=== [chain-run formal] $(r17_ts) ==="
wrc=0
python -m rl_curriculum.curriculum261_r17_cli chain-run \
    --out-dir "$ART" --freeze-sha "$FREEZE_SHA" \
    > "$REQ_DIR/chain_run.log" 2>&1 || wrc=$?
tail -5 "$REQ_DIR/chain_run.log" || true
if [ "$wrc" -ne 0 ]; then
  # 协调者失败(会话获取被拒/plan 失败/步骤失败)——被拒与
  # 失败的区分由协调者落盘(请求证据 vs journal 事件);
  # 入口只按 bootstrap 边界封口 workflow 前缀为空的情形:
  # plan 文件不存在 ⇒ 任何步骤都未启动。
  if [ ! -f "$ART/r17_workflow_plan_formal.json" ]; then
    python -m rl_curriculum.curriculum261_r17_cli fail-closure \
      --out-dir "$ART" --failed-step bootstrap --verdict FAIL \
      --reason "chain-run rc=$wrc 且 workflow plan 未生成(协调者会话获取或结构校验失败;R17 §5.4:失败发生在 bootstrap,workflow 前缀为空,首个未执行节点 provenance-verify 未开始;停止;只读收尾)" \
      >> "$REQ_DIR/fail_closure.log" 2>&1 || true
  fi
fi
emit_launch "chain_finished" "rc=$wrc"
echo "=== [chain-run formal] rc=$wrc $(r17_ts) ==="
exit "$wrc"
