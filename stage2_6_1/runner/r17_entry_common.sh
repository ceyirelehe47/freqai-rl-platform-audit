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
