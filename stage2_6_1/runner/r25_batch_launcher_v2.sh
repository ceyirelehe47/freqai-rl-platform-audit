#!/usr/bin/env bash
# R25 批次启动器 v2(RouteC_R25_EntryProvenance_ReadbackClosure_v1)。
#
# 修复目标(监护 run 20260926T132814_7514_448 实测缺口):
#   旧批次脚本把每个工作者置入新进程组,且 guest sampler task_tree 的
#   根后代走查被短路,导致 11 个生成 PID 从未进入任务级遥测(534 样本
#   仅见 bash 502 与末次 python 1117)。本启动器:
#   1) 工作者一律 `timeout --foreground` 包裹——留在本启动器进程组内,
#      pgid 口径直接覆盖;进程组口径同时配合同轮修复的 task_tree 后代
#      走查(r17_guest_sampler.py)双保险;
#   2) 每次 run-coordinate 前先以 execution-binding 实测冻结执行绑定,
#      入口/生成模块/启动器身份不符即零生成拒绝;
#   3) 不放宽任何监护阈值/停止保护。
#
# 用法:
#   r25_batch_launcher_v2.sh study <plan> <out-root> [coord...]   # 未来受监护研究批次(本轮不执行)
#   r25_batch_launcher_v2.sh smoke <plan> <out-root> <coord...>   # 工程 smoke(自动 --allow-smoke)
#   r25_batch_launcher_v2.sh probe <worker.py> <logdir>           # 工程替身探针(不生成任何研究语料)
#
# 本文件必须保持 LF(受控面纪律)。
set -uo pipefail

MODE="${1:?usage: r25_batch_launcher_v2.sh study|smoke|probe ...}"
shift

RUNNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${R25BATCH_PYTHON:-$(command -v python3)}"
ENTRY="$RUNNER_DIR/r25_cue_bias_dev_entry.py"
PER_COORD_TIMEOUT="${R25BATCH_TIMEOUT_SECONDS:-2700}"
FAIL=0

ts() { date -u +%H:%M:%S; }

if grep -q $'\r' "$0"; then
  echo "FATAL: CRLF 检出(LF 合同违反)" >&2
  exit 99
fi

run_coord() {  # plan out_root coord extra...
  local plan="$1" out_root="$2" coord="$3"; shift 3
  echo "R25BATCH start $coord $(ts)"
  local rc=0
  timeout --foreground "$PER_COORD_TIMEOUT" "$PYTHON" "$ENTRY" \
    run-coordinate --plan "$plan" --coordinate "$coord" \
    --out-root "$out_root" --execution-binding "$BINDING_FILE" "$@" \
    || rc=$?
  echo "R25BATCH end $coord rc=$rc $(ts)"
  [ "$rc" -ne 0 ] && FAIL=1
  return 0
}

case "$MODE" in
  study|smoke)
    PLAN="${1:?need plan}"; OUT_ROOT="${2:?need out-root}"; shift 2
    COORDS="${*:?need at least one coordinate}"
    BINDING_FILE="$OUT_ROOT/execution_binding.json"
    mkdir -p "$OUT_ROOT"
    "$PYTHON" "$ENTRY" execution-binding --out "$BINDING_FILE" \
      --plan "$PLAN" --launcher "${BASH_SOURCE[0]}" \
      || { echo "FATAL: execution-binding 失败" >&2; exit 3; }
    if [ "$MODE" = smoke ]; then EXTRA="--allow-smoke"; else EXTRA=""; fi
    for c in $COORDS; do
      # shellcheck disable=SC2086
      run_coord "$PLAN" "$OUT_ROOT" "$c" $EXTRA
    done
    if [ "$MODE" = study ]; then
      echo "R25BATCH cold-read $(ts)"
      "$PYTHON" "$ENTRY" cold-read --plan "$PLAN" \
        --out-root "$OUT_ROOT" \
        --result "$OUT_ROOT/cold_read_result.json" \
        || FAIL=1
    fi
    echo "R25BATCH DONE fail=$FAIL $(date -u +%Y%m%dT%H%M%SZ)"
    exit "$FAIL"
    ;;
  probe)
    WORKER="${1:?need worker script}"; LOGDIR="${2:?need logdir}"
    mkdir -p "$LOGDIR"
    BINDING_FILE="$LOGDIR/probe_binding_note.json"
    echo "{\"note\":\"probe mode 无研究生成;执行绑定机制见 study/smoke 路径\",\"launcher\":\"${BASH_SOURCE[0]}\",\"started_utc\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "$BINDING_FILE"
    PROBE_T="${R25BATCH_PROBE_TIMEOUT_SECONDS:-60}"

    # -- C02:顺序工作者 + 子/孙进程,持续多个采样周期,实际 CPU/RSS --
    echo "R25BATCH probe start w1-burn-with-children $(ts)"
    timeout --foreground "$PROBE_T" "$PYTHON" "$WORKER" \
      --label w1 --mode burn --seconds 45 --spawn-child \
      --heartbeat "$LOGDIR/w1_heartbeat.jsonl" \
      --identity-out "$LOGDIR/w1_identity.json" || FAIL=1
    echo "R25BATCH probe end w1 rc=$? $(ts)"

    echo "R25BATCH probe start w2-burn $(ts)"
    timeout --foreground "$PROBE_T" "$PYTHON" "$WORKER" \
      --label w2 --mode burn --seconds 30 \
      --heartbeat "$LOGDIR/w2_heartbeat.jsonl" \
      --identity-out "$LOGDIR/w2_identity.json" || FAIL=1
    echo "R25BATCH probe end w2 rc=$? $(ts)"

    # -- C03:短超时正反例(受控子树真实退出,无存活后代) --
    echo "R25BATCH probe start w3-sleep-timeout-12s $(ts)"
    rc3=0
    timeout --foreground 12 "$PYTHON" "$WORKER" \
      --label w3 --mode sleep --seconds 300 --spawn-child \
      --heartbeat "$LOGDIR/w3_heartbeat.jsonl" \
      --identity-out "$LOGDIR/w3_identity.json" || rc3=$?
    echo "R25BATCH probe end w3 rc=$rc3 $(ts)"
    if [ "$rc3" -ne 124 ]; then
      echo "R25BATCH w3 EXPECTED timeout rc=124, got $rc3" >&2
      FAIL=1
    fi
    # 子树退出核验:身份文件里的 pid 及其后代必须全部消失
    "$PYTHON" "$WORKER" --check-subtree-gone \
      --identity "$LOGDIR/w3_identity.json" \
      || FAIL=1
    echo "R25BATCH DONE fail=$FAIL $(date -u +%Y%m%dT%H%M%SZ)"
    exit "$FAIL"
    ;;
  *)
    echo "FATAL: 未知 mode $MODE" >&2; exit 2 ;;
esac
