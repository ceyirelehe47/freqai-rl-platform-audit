#!/usr/bin/env bash
# 本轮交付封口(unified_shutdown_cold_read)。
# 与旧脚本的本质差异(任务书 §6.5):
#   - 篡改反例只在一次性冷副本上(不再修改原始运行文件再"恢复");
#   - 独立验收=冷副本+原根不可访问的隔离 verify(不只复验原根);
#   - 原根 verify 仅作构建自校验(如实标注为"原根复验")。
# 用法(WSL 内): tr -d '\r' < finalize_delivery.sh | bash -s -- <run_dir>
set -euo pipefail
RD="$(readlink -f "${1:?用法: finalize_delivery.sh <run_dir>}")"
BASE="$(dirname "$(dirname "$RD")")"         # .../unified_shutdown_cold_read
ROOT="$BASE"                                 # manifest 相对基准(含 runs/)
DEL="$BASE/delivery_closure"
DEV="$HOME/projects/crypto_rl/stage2_6_1_runner"
RUN_ID="$(basename "$RD")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$DEL/anchors" "$DEL/verify_receipts" \
  "$BASE/receipts/${RUN_ID}" "$DEL/cold_copies"

echo "== 1) 资源复算(已关闭流) =="
python3 "$BASE/tools/recompute_resources.py" "$RD" \
  | tee "$DEL/resource_recompute.json"

echo "== 2) build 固定清单+锚(原根;构建自校验) =="
python3 "$DEV/r17_verify_delivery.py" build \
  --run-record "$RD/run_record.json" \
  --manifest-out "$DEL/delivery_manifest_v2.jsonl" \
  --anchor-out "$DEL/anchors/final.anchor.json" \
  --root "$ROOT"

echo "== 3) 原根复验(构建自校验;非独立冷读) =="
python3 "$DEV/r17_verify_delivery.py" verify \
  --root "$ROOT" \
  --manifest "$DEL/delivery_manifest_v2.jsonl" \
  --anchor-file "$DEL/anchors/final.anchor.json" \
  --run-record "$RD/run_record.json" \
  --receipt-dir "$DEL/verify_receipts" | tee "$DEL/verify_receipts/orig_root_reverify_${STAMP}.txt"

echo "== 4) 冷读副本(完整必要字节→家目录) =="
COPY="$HOME/r17u_cold_${RUN_ID}"
rm -rf "$COPY"
python3 "$BASE/tools/build_cold_copy.py" \
  --source-root "$ROOT" \
  --manifest "$DEL/delivery_manifest_v2.jsonl" \
  --anchor "$DEL/anchors/final.anchor.json" \
  --record-rel "runs/${RUN_ID}/run_record.json" \
  --verifier "$DEV/r17_verify_delivery.py" \
  --dest "$COPY" | tee "$DEL/cold_build_${STAMP}.json"

echo "== 5) 独立冷读(原根不可访问的隔离 verify) =="
bash "$BASE/tools/cold_read_isolated.sh" "$COPY" \
  "$BASE/receipts/${RUN_ID}" \
  | tee "$BASE/receipts/${RUN_ID}/cold_read_stdout.txt"

echo "== 6) 负例(缺件/篡改;一次性副本;原件不动) =="
bash "$BASE/tools/cold_read_negative.sh" "$COPY" \
  "$BASE/receipts/${RUN_ID}" \
  | tee "$BASE/receipts/${RUN_ID}/negative_stdout.txt"

echo "== 7) 篡改检出证明(冷副本上的 manifest 对应文件改 1 字节) =="
NEG="$HOME/r17u_cold_negtamper_${RUN_ID}"
rm -rf "$NEG"
cp -r "$COPY" "$NEG"
V=$(cd "$NEG/payload" && find . -type f | sort | tail -1)
printf 'X' >> "$NEG/payload/$V"
set +e
bash "$BASE/tools/cold_read_isolated.sh" "$NEG" \
  "$BASE/receipts/${RUN_ID}/tamper" >/dev/null 2>&1
TRC=$?
set -e
[ "$TRC" -ne 0 ] || { echo "FAIL: 篡改副本未被检出"; exit 1; }
echo "tamper_detected_isolated_rc=$TRC (原件与正副本未动)"

echo "== 8) 归档冷副本 =="
cp -r "$COPY" "$DEL/cold_copies/${RUN_ID}"
rm -rf "$NEG"
echo "== DONE $(date -u +%Y%m%dT%H%M%SZ) run=$RUN_ID =="
echo "注: git blob 登记(register-git)在 manifest 入库后的提交步骤"
echo "    由 register_anchor.sh 完成(两段式:先 commit manifest,后登记)"
