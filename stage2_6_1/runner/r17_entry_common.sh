#!/usr/bin/env bash
# R17 launcher 共享入口段(被 r17_formal_chain.sh 与 r17_rt_rehearsal.sh
# source;不直接执行)。提供:启动事件输出/存储天花板/环境激活/
# 解释器与模块来源验证。两个入口共用同一段实现,消除双脚本漂移
# (诊断任务书 §E2:只声称"入口结构相同"不算证明同源)。
#
# 调用方约定(source 之前/之后各一次):
#   先:caller 自行完成 LF 自检(同时检查本文件),再 set -euo pipefail,
#       定义 PROJECT_ROOT 与 RUNNER,然后 source 本文件;
#   后:caller 定义 LAUNCH_EVIDENCE(必须指向本请求独立目录内的
#       launch_evidence.jsonl;R17 诊断轮 E1 修复:请求期输出不再写
#       跨请求共享路径),再 emit_launch "launch_requested" ...
#       并在需要时调用下列函数。

# ---- 启动事件输出(append-only;仅写 caller 指定的请求独立文件) ----
r17_ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
emit_launch() {
  printf '{"event":"%s","utc":"%s","argv":"%s","pid":%s}\n' \
    "$1" "$(r17_ts)" "$2" "$$" >> "$LAUNCH_EVIDENCE"
}

# ---- 存储天花板(用户设定 300GB;超过拒绝启动 fail closed) ----
# WSL 根文件系统已用量(df Used,稀疏感知)超过 300GB 时,任何
# rehearsal/正式链启动被拒绝(防止缓存增长把宿主盘写爆)。
R17_STORAGE_CEILING_GB=300
r17_check_storage_ceiling() {
  local used_kb used_gb
  used_kb=$(df -BK --output=used / | tail -1 | tr -dc '0-9')
  used_gb=$((used_kb / 1024 / 1024))
  if [ "$used_gb" -ge "$R17_STORAGE_CEILING_GB" ]; then
    emit_launch "bootstrap_failed" \
      "storage ceiling: WSL used ${used_gb}GB >= ${R17_STORAGE_CEILING_GB}GB;清理 ~/.cache/rl_builder_bundles 后重试"
    echo "FATAL: WSL 已用 ${used_gb}GB 超过 ${R17_STORAGE_CEILING_GB}GB 天花板;拒绝启动(先清理缓存)" >&2
    exit 96
  fi
  emit_launch "storage_checked" \
    "used=${used_gb}GB ceiling=${R17_STORAGE_CEILING_GB}GB"
}

# ---- 环境激活(失败即拒绝;不用任何吞错兜底) ----
r17_activate_environment() {
  cd "$PROJECT_ROOT"
  if [ ! -f ./activate-freqtrade.sh ]; then
    emit_launch "bootstrap_failed" "activate-freqtrade.sh 缺失"
    echo "FATAL: $PROJECT_ROOT/activate-freqtrade.sh 不存在" >&2
    exit 98
  fi
  # set -e 下 source 失败(返回非零)即终止
  source ./activate-freqtrade.sh
  emit_launch "environment_activated" "conda=$CONDA_DEFAULT_ENV"
}

# ---- 解释器与模块来源验证 ----
r17_verify_interpreter() {
  if python - <<'PYVERIFY'
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
    export PYTHONPATH="$PROJECT_ROOT/src"
    emit_launch "bootstrap_verified" "python=$(python -V 2>&1)"
    return 0
  fi
  emit_launch "bootstrap_failed" "interpreter/module origin 验证失败"
  echo "FATAL: 解释器或模块来源验证失败" >&2
  exit 97
}

# ---- 正式入口观测接线(观测型;任务书 WP1/§5.1) ----
# 仅为正式链请求启动宿主采样器并登记:判定/保护不作用于正式入口的
# 业务编排(该编排进程不是本段启动的,无登记进程组),边界如实声明;
# 会话准入失败时 EXIT trap 调 teardown,被拒请求只关闭自己的观测。
r17_monitored_bootstrap() {
  local req_dir="$1" run_id="$2" ps1_guest ps1_win out_guest out_win pid
  ps1_guest="${R17_RELEASE_REPO:-/mnt/f/trading/freqai-rl-audit}/stage2_6_1/runner/r17_win_sampler.ps1"
  [ -f "$ps1_guest" ] || return 1
  ps1_win="$(wslpath -w "$ps1_guest")" || return 1
  out_guest="$req_dir/obs/win_samples.jsonl"
  mkdir -p "$req_dir/obs"
  out_win="$(wslpath -w "$out_guest")" || return 1
  powershell.exe -NoProfile -ExecutionPolicy Bypass \
    -File "$ps1_win" -RunId "$run_id" -OutFile "$out_win" \
    -MaxSeconds 43200 -Volumes "C:,F:" \
    -EmergencyDir "C:/Users/15027/AppData/Local/r17_supervision_emergency" \
    >/dev/null 2>&1 &
  pid=$!
  printf '{"win_sampler_interop_pid":%s,"out_guest":"%s","started_utc":"%s","mode":"observation_only"}\n' \
    "$pid" "$out_guest" "$(r17_ts)" > "$req_dir/observation.json"
  return 0
}

r17_monitored_teardown() {
  local req_dir="$1" pid
  [ -f "$req_dir/observation.json" ] || return 0
  pid=""
  pid="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['win_sampler_interop_pid'])" "$req_dir/observation.json" 2>/dev/null)" || pid=""
  if [ -n "$pid" ]; then
    # 采样器可能已自行退出(MaxSeconds 兜底);kill 失败仅记录
    if ! kill "$pid" 2>/dev/null; then
      emit_launch "observation_teardown_nopid" "pid=$pid"
    fi
  fi
  emit_launch "observation_closed" "req_dir=$req_dir"
  return 0
}
