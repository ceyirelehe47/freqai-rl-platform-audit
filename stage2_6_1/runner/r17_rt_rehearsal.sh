#!/usr/bin/env bash
# R17 真实入口 rehearsal(F5 闭合):穿过与正式完全相同的外层
# shell 入口结构(LF 自检/启动请求证据/环境激活/解释器验证/
# 协调者 chain-run),仅三处预登记差异:
#   1) profile = rehearsal(工程 namespace 与样本规模);
#   2) state root = 隔离临时目录(不触碰正式 R17 状态);
#   3) out_dir = 工程 rehearsal 目录。
# 所有权/executor 校验/journal 规则/raw logs/artifact 校验不因
# rehearsal 关闭(同一 chain-run 代码路径)。
#
# 用法: bash r17_rt_rehearsal.sh <commit_a_sha_or_dev_head>

if grep -q $'\r' "$0"; then
  echo "FATAL: $0 含 CR 字节(CRLF 行尾);拒绝启动。" >&2
  exit 99
fi

set -euo pipefail

PROJECT_ROOT="${R17_PROJECT_ROOT:-$HOME/projects/crypto_rl}"
ART="$PROJECT_ROOT/artifacts/route_c_stage2_6_1_repair17_rt"
LOGD="$PROJECT_ROOT/r17_rt_rehearsal_logs"
RT_STATE="$(mktemp -d "${TMPDIR:-/tmp}/r17_rt_state_XXXXXX")"
mkdir -p "$LOGD" "$ART"
LAUNCH_EVIDENCE="$LOGD/r17_rt_launch_evidence.jsonl"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
emit_launch() {
  printf '{"event":"%s","utc":"%s","argv":"%s","pid":%s}\n' \
    "$1" "$(ts)" "$2" "$$" >> "$LAUNCH_EVIDENCE"
}
emit_launch "launch_requested" "r17_rt_rehearsal.sh $* state=$RT_STATE"


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
  exit 98
fi
source ./activate-freqtrade.sh
emit_launch "environment_activated" "conda=$CONDA_DEFAULT_ENV"

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
  exit 97
fi
export PYTHONPATH="$PROJECT_ROOT/src"
emit_launch "bootstrap_verified" "python=$(python -V 2>&1)"

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

echo "=== [chain-run rehearsal] $(ts) state=$RT_STATE ==="
wrc=0
python -m rl_curriculum.curriculum261_r17_cli chain-run \
    --out-dir "$ART" --freeze-sha "$FREEZE_SHA" --rehearsal \
    > "$LOGD/chain_run.log" 2>&1 || wrc=$?
tail -5 "$LOGD/chain_run.log" || true
emit_launch "chain_finished" "rc=$wrc"
echo "=== [chain-run rehearsal] rc=$wrc $(ts) ==="
echo "rehearsal state root(隔离): $RT_STATE"
exit "$wrc"
