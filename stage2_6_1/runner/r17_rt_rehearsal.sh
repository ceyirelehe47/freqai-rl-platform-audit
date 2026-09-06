#!/usr/bin/env bash
# R17 真实入口 rehearsal(F5 闭合):穿过与正式完全相同的外层
# shell 入口结构(LF 自检/启动请求证据/环境激活/解释器验证/
# 协调者 chain-run;共享段 r17_entry_common.sh 同源),仅三处
# 预登记差异:
#   1) profile = rehearsal(工程 namespace 与样本规模);
#   2) state root = run 目录内隔离(不触碰正式 R17 状态);
#   3) out_dir = run 目录内工程 rehearsal 子目录。
# 所有权/executor 校验/journal 规则/raw logs/artifact 校验不因
# rehearsal 关闭(同一 chain-run 代码路径)。
#
# R17 诊断轮 E2 修复(工程尝试全隔离):此前仅 state 用临时目录,
# artifacts/logs 仍为固定路径,跨次运行互相覆盖 provenance_lock.log/
# chain_run.log/plan/manifest,历史失败证据丢失。现在每次尝试的
# state/artifacts/logs/chain 产物/manifest 全部落在
# r17_rt_runs/<RUN_ID>/ 单一 run 目录内(含 chain-run 派生的
# <out_dir 名>_chain_logs raw log 目录);旧 run 目录保留原始字节,
# 不删除不复用。RUN_ID 只影响路径与请求元数据,不进入任何预登记
# seed 派生。
#
# 用法: bash r17_rt_rehearsal.sh <commit_a_sha_or_dev_head>

# ---- LF 自检(含共享段;必须在 set -euo pipefail 之前) ----
ENTRY_COMMON="$(cd "$(dirname "$0")" && pwd)/r17_entry_common.sh"
if grep -q $'\r' "$0" "$ENTRY_COMMON"; then
  echo "FATAL: $0 或 r17_entry_common.sh 含 CR 字节(CRLF 行尾);拒绝启动。" >&2
  exit 99
fi

set -euo pipefail

PROJECT_ROOT="${R17_PROJECT_ROOT:-$HOME/projects/crypto_rl}"
RUNNER="$PROJECT_ROOT/stage2_6_1_runner"
# shellcheck source=/dev/null
source "$RUNNER/r17_entry_common.sh"

# ---- run 级全隔离目录(E2;先于任何重定向与 emit 建立) ----
RT_ROOT="$PROJECT_ROOT/r17_rt_runs"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)_$$"
RUN_DIR="$RT_ROOT/$RUN_ID"
ART="$RUN_DIR/artifacts"
LOGD="$RUN_DIR/logs"
RT_STATE="$RUN_DIR/state"
mkdir -p "$RT_ROOT" "$ART" "$LOGD" "$RT_STATE"
LAUNCH_EVIDENCE="$LOGD/launch_evidence.jsonl"
emit_launch "launch_requested" "r17_rt_rehearsal.sh $* run_id=$RUN_ID"

r17_check_storage_ceiling
r17_activate_environment
r17_verify_interpreter

FREEZE_SHA="${1:?需要 head/Commit SHA}"

export CURRICULUM261_R17_STATE_ROOT="$RT_STATE"

# ---- pre-freeze provenance-lock(链外;初始化 workflow 前置产物) ----
prc=0
python -m rl_curriculum.curriculum261_r17_cli provenance-lock \
    --out-dir "$ART" \
    > "$LOGD/provenance_lock.log" 2>&1 || prc=$?
if [ "$prc" -ne 0 ]; then
  tail -5 "$LOGD/provenance_lock.log" || true
  emit_launch "prefreeze_failed" "provenance-lock rc=$prc"
  echo "FATAL: pre-freeze provenance-lock 失败" >&2
  exit "$prc"
fi
emit_launch "prefreeze_locked" "provenance-lock ok"

echo "=== [chain-run rehearsal] $(r17_ts) state=$RT_STATE ==="
wrc=0
python -m rl_curriculum.curriculum261_r17_cli chain-run \
    --out-dir "$ART" --freeze-sha "$FREEZE_SHA" --rehearsal \
    > "$LOGD/chain_run.log" 2>&1 || wrc=$?
tail -5 "$LOGD/chain_run.log" || true
emit_launch "chain_finished" "rc=$wrc"
echo "=== [chain-run rehearsal] rc=$wrc $(r17_ts) ==="
echo "rehearsal run 目录(隔离): $RUN_DIR"
exit "$wrc"
