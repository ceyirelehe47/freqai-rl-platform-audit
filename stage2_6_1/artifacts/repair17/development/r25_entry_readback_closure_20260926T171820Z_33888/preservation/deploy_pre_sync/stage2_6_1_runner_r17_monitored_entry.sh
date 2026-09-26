#!/usr/bin/env bash
# R17 受监护重任务统一启动入口(任务书 WP1/§5)。
# 全量 pytest / 工程 rehearsal / C3 固定坐标诊断 / design-calibration
# 局部工程任务都经本入口启动:自动创建 run 身份→启动 host/guest 观测→
# 由 supervisor(任务控制者)登记并启动业务任务树→监测/告警/保护→
# 有限收尾关闭采样器。不依赖手工开采样器或登记 PID。
#
# 用法(WSL 内):
#   r17_monitored_entry.sh <task-kind> [--max-seconds N] -- <argv...>
# task-kind: pytest|rehearsal|c3diag|engineering|fixture
# 边界(审查 §7-12):formal 拒绝(正式入口走自身观测接线,避免双重监护;
# 本轮不运行任何正式分支)。
#
# 运行身份(§5.3):RUN_ID=UTC 纳秒+PID;目录排他创建拒绝碰撞;run_id
# 不进业务 RNG/namespace,不向业务注入环境键;旧 run 不复用。

# ---- LF 自检(本文件+共享入口段;冻结面纪律) ----
if grep -q $'\r' "$0" "${BASH_SOURCE[0]%/*}/r17_entry_common.sh" 2>/dev/null; then
  echo "FATAL: CRLF 检出(LF 合同违反)" >&2
  exit 99
fi
set -euo pipefail

RUNNER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${R17_PROJECT_ROOT:-$(cd "$RUNNER/.." && pwd)}"
RELEASE_REPO="${RELEASE_REPO:-/mnt/f/trading/freqai-rl-audit}"
SUPERV_ROOT="$RELEASE_REPO/stage2_6_1/artifacts/repair17/development/run_supervision"
# shellcheck source=r17_entry_common.sh
source "$RUNNER/r17_entry_common.sh"

TASK_KIND="${1:-}"
[ -n "$TASK_KIND" ] || { echo "用法: $0 <task-kind> [--max-seconds N] -- <argv...>" >&2; exit 2; }
shift
if [ "$TASK_KIND" = "formal" ]; then
  echo "FATAL: formal 经自身观测接线启动,不经本入口(双重监护防护)" >&2
  exit 2
fi
case "$TASK_KIND" in
  pytest|rehearsal|c3diag|engineering|fixture) ;;
  *) echo "FATAL: 未知 task-kind $TASK_KIND" >&2; exit 2 ;;
esac

MAX_SECONDS=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --max-seconds) MAX_SECONDS="$2"; shift 2 ;;
    --) shift; break ;;
    *) echo "FATAL: 未知参数 $1" >&2; exit 2 ;;
  esac
done
[ "$#" -gt 0 ] || { echo "FATAL: 缺业务命令(-- <argv...>)" >&2; exit 2; }

# ---- 单例(本轮同时最多一个业务重任务;§5.4) ----
# 锁随 supervisor 进程生命周期(fd 继承,进程退出即释放);
# 被拒请求只写自己的 rejected 记录,不影响活跃 owner(监护面目录,
# 不触碰资格证据区)。
mkdir -p "$SUPERV_ROOT/runs" "$SUPERV_ROOT/rejected"
LOCK_PATH="${R17_SUPERVISION_LOCK:-$SUPERV_ROOT/supervision.lock}"
exec 9>"$LOCK_PATH"
if ! flock -n 9; then
  REJ_ID="$(date -u +%Y%m%dT%H%M%SZ)_$$"
  printf '{"event":"rejected_concurrent","utc":"%s","run_id":"%s","task_kind":"%s","argv":"%s"}\n' \
    "$(r17_ts)" "$REJ_ID" "$TASK_KIND"$'\t'"$(printf '%s ' "$@")" \
    >> "$SUPERV_ROOT/rejected/rejected.jsonl"
  echo "FATAL: 已有活跃受监护任务(单例约束);本请求被拒(记录于 rejected/)" >&2
  exit 95
fi

# ---- run 身份(排他创建;碰撞拒绝,不靠时间戳唯一性假设) ----
# R17_RUN_DIR(可选,工程调用方预指定 run 目录;使 --junitxml 等
# 业务产物路径先验可知,S5 运行前登记闭环)。缺省自动生成,行为
# 不变;两种来源同样排他创建、同样拒绝碰撞。
if [ -n "${R17_RUN_DIR:-}" ]; then
  RUN_DIR="${R17_RUN_DIR%/}"
  RUN_ID="$(basename "$RUN_DIR")"
else
  RUN_ID="$(date -u +%Y%m%dT%H%M%S)_$(date +%N | tail -c 5)_$$"
  RUN_DIR="$SUPERV_ROOT/runs/$RUN_ID"
fi
if ! mkdir "$RUN_DIR" 2>/dev/null; then
  echo "FATAL: run 目录碰撞: $RUN_DIR" >&2
  exit 96
fi
# R17_RUN_DIR 只作用于本入口自身;不得泄入 supervisor→业务环境
# (嵌套受监护任务会误撞同一目录;M16 全量回归真实暴露)
unset R17_RUN_DIR
LAUNCH_EVIDENCE="$RUN_DIR/launch_evidence.jsonl"
export LAUNCH_EVIDENCE
emit_launch "monitored_entry_start" "task_kind=$TASK_KIND run_id=$RUN_ID"

# ---- 存储天花板 + 环境激活 + 解释器验证(复用共享入口段) ----
r17_check_storage_ceiling
r17_activate_environment
r17_verify_interpreter

# ---- 业务命令解析(记录后启动 supervisor) ----
emit_launch "business_argv" "$(printf '%s ' "$@")"
echo "R17 monitored run: $RUN_ID kind=$TASK_KIND"
echo "run_dir: $RUN_DIR"
exec python3 "$RUNNER/r17_supervision.py" \
  --run-dir "$RUN_DIR" \
  --task-kind "$TASK_KIND" \
  ${MAX_SECONDS:+--max-seconds "$MAX_SECONDS"} \
  --win-sampler-ps1 "$RELEASE_REPO/stage2_6_1/runner/r17_win_sampler.ps1" \
  --task-cwd "$PROJECT_ROOT" \
  -- "$@"
