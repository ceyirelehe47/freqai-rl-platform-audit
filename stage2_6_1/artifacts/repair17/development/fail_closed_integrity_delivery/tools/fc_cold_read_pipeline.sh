#!/usr/bin/env bash
# WP3 完整交付复验一条龙(fail-closed-integrity-delivery 轮)。
#
# 输入:本轮受监护全量 run 的 run_record(已关闭原件)。
# 流程(§7):
#   1) build:固定必需集合(manifest+anchor;不枚举现存文件)
#   2) build_cold_copy:逐项物理复制 payload/metadata/verifier 到
#      一次性新根(排他创建;不 rm -rf 复用路径)
#   3) cold_read_isolated_fc:双原根(/mnt + /home/cryptorl/projects)
#      遮蔽,副本 verifier 只读新根验证;payload 只读快照前后不变
#   4) cold_read_negative_fc:缺件/篡改负例(独立副本;预期内容错误)
#      + 可选故障包(控制失败 run 副本,verify 因 control_failures 拒绝)
#
# 用法: bash fc_cold_read_pipeline.sh <run_record.json> <work_dir> \
#           [故障包run_record.json]
set -euo pipefail
RR="$(readlink -f "${1:?用法: fc_cold_read_pipeline.sh <run_record> <work_dir> [故障包rr]}")"
WORK="$(readlink -f "${2:?缺少 work_dir}")"
FAULT_RR="${3:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ORIG_TOOLS="$HERE/../../unified_shutdown_cold_read/tools"
PY=python3

# 源根=run_record 的相对基准(与 supervisor _prepare_run_record_entries
# 同式 run_dir.parent.parent,即 run_supervision 根;RR 三层 dirname:
# run_record→run目录→runs→run_supervision)
RUN_DIR="$(dirname "$RR")"
ROOT="$(dirname "$(dirname "$RUN_DIR")")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

# 一次性工作根(排他创建)
if ! mkdir "$WORK"; then
  echo "FATAL: 工作目录已存在(一次性合同,拒绝覆盖): $WORK" >&2
  exit 2
fi

echo "== [1/5] build 固定集合 =="
MAN="$WORK/manifest.jsonl"
ANCHOR="$WORK/anchor.json"
VERIFIER="/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/r17_verify_delivery.py"
"$PY" "$VERIFIER" build \
  --run-record "$RR" --manifest-out "$MAN" --anchor-out "$ANCHOR" \
  --root "$ROOT" | tee "$WORK/build.log"

echo "== [2/5] 物理复制到新根 =="
COPY="$WORK/coldcopy"
# record 相对路径以 manifest 的 role=record 行为准(与 build 的
# _rel_within 同源;不从目录名猜测)
RECORD_REL="$(python3 -c 'import json,sys
for ln in open(sys.argv[1], encoding="utf-8"):
    d = json.loads(ln)
    if d.get("role") == "record":
        print(d["path"]); break' "$MAN")"
[ -n "$RECORD_REL" ] || { echo "FATAL: manifest 无 record 行" >&2; exit 2; }
"$PY" "$ORIG_TOOLS/build_cold_copy.py" \
  --source-root "$ROOT" --manifest "$MAN" --anchor "$ANCHOR" \
  --record-rel "$RECORD_REL" \
  --verifier "$VERIFIER" \
  --dest "$COPY" | tee "$WORK/copy.log"

echo "== [3/5] 双原根隔离冷读 =="
bash "$HERE/cold_read_isolated_fc.sh" "$COPY" "$WORK/receipts" \
  2>&1 | tee "$WORK/isolated.log"
ISO_RC=${PIPESTATUS[0]}
echo "isolated_rc=$ISO_RC" | tee -a "$WORK/isolated.log"

echo "== [4/5] 负例(缺件/篡改) =="
FAULT_ARG=""
FAULT_COPY=""
if [ -n "$FAULT_RR" ]; then
  FAULT_RR="$(readlink -f "$FAULT_RR")"
  FRUN_DIR="$(dirname "$FAULT_RR")"
  FROOT="$(dirname "$(dirname "$FRUN_DIR")")"
  FMAN="$WORK/fault_manifest.jsonl"
  FANCHOR="$WORK/fault_anchor.json"
  "$PY" "$VERIFIER" build \
    --run-record "$FAULT_RR" --manifest-out "$FMAN" \
    --anchor-out "$FANCHOR" --root "$FROOT" | tee "$WORK/fault_build.log"
  FAULT_COPY="$WORK/fault_coldcopy"
  F_RECORD_REL="$(python3 -c 'import json,sys
for ln in open(sys.argv[1], encoding="utf-8"):
    d = json.loads(ln)
    if d.get("role") == "record":
        print(d["path"]); break' "$FMAN")"
  [ -n "$F_RECORD_REL" ] || { echo "FATAL: fault manifest 无 record 行" >&2; exit 2; }
  "$PY" "$ORIG_TOOLS/build_cold_copy.py" \
    --source-root "$FROOT" --manifest "$FMAN" --anchor "$FANCHOR" \
    --record-rel "$F_RECORD_REL" \
    --verifier "$VERIFIER" \
    --dest "$FAULT_COPY" | tee "$WORK/fault_copy.log"
  FAULT_ARG="$FAULT_COPY"
fi
NEG_RC=0
bash "$HERE/cold_read_negative_fc.sh" "$COPY" "$WORK/receipts_neg" \
  ${FAULT_ARG:+"$FAULT_ARG"} 2>&1 | tee "$WORK/negative.log" \
  || NEG_RC=$?

echo "== [5/5] 汇总 =="
"$PY" - "$WORK" "$ISO_RC" "$NEG_RC" <<'PYEOF'
import json, sys
work, iso_rc, neg_rc = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
rec = {"schema": "r17-fc-cold-read-pipeline-v1", "work": work,
       "isolated_rc": iso_rc, "negative_rc": neg_rc,
       "rc": 0 if iso_rc == 0 and neg_rc == 0 else 1}
open(f"{work}/pipeline_result.json", "w", encoding="utf-8").write(
    json.dumps(rec, ensure_ascii=False, indent=1))
print(json.dumps(rec, ensure_ascii=False))
sys.exit(rec["rc"])
PYEOF
