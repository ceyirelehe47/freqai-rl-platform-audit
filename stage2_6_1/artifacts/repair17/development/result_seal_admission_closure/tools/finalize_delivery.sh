#!/usr/bin/env bash
# result-seal closure 轮:全量回归收尾(资源复算+build+篡改反例+verify+blob)
set -euo pipefail
RD="$1"   # 全量 run 目录(monitored_entry 创建,含 run_record.json)
FR="$(dirname "$(dirname "$RD")")"
REPO=/mnt/f/trading/freqai-rl-audit
cd "$REPO"
PY=python3
echo "=== 资源复算(已关闭原始流重算 vs summary):"
"$PY" "$FR/../tools/recompute_resources.py" "$RD" \
  | tee "$FR/resource_recompute.json"
echo "=== build:"
"$PY" stage2_6_1/runner/r17_verify_delivery.py build \
  --run-record "$RD/run_record.json" \
  --manifest-out "$FR/delivery_manifest_v2.jsonl" \
  --anchor-out "$FR/anchors/final.anchor.json" \
  --root "$FR"
echo "=== 验证前篡改反例(追加 1 字节 → 必须检出 → 恢复):"
CP="$RD/telemetry/guest_samples.jsonl"
H0=$(sha256sum "$CP" | cut -d" " -f1)
printf ' ' >> "$CP"
if "$PY" stage2_6_1/runner/r17_verify_delivery.py verify \
  --root "$FR" --manifest "$FR/delivery_manifest_v2.jsonl" \
  --anchor-file "$FR/anchors/final.anchor.json" \
  --run-record "$RD/run_record.json" \
  --receipt-dir "$FR/verify_receipts" >/dev/null 2>&1; then
  echo "FATAL: 篡改未检出"; exit 1
else
  echo "反例检出 rc!=0 OK"
fi
head -c -1 "$CP" > /tmp/_trim && mv /tmp/_trim "$CP"
H1=$(sha256sum "$CP" | cut -d" " -f1)
[ "$H0" = "$H1" ] || { echo "FATAL: 恢复失败"; exit 1; }
echo "反例后恢复一致"
echo "=== verify(正式):"
"$PY" stage2_6_1/runner/r17_verify_delivery.py verify \
  --root "$FR" --manifest "$FR/delivery_manifest_v2.jsonl" \
  --anchor-file "$FR/anchors/final.anchor.json" \
  --run-record "$RD/run_record.json" \
  --receipt-dir "$FR/verify_receipts"
echo "=== 冷读(独立目录,脱离开发绝对路径):"
COLD="$FR/cold_read_final"
rm -rf "$COLD"; mkdir -p "$COLD"
cp "$FR/delivery_manifest_v2.jsonl" "$FR/anchors/final.anchor.json" "$COLD/"
"$PY" stage2_6_1/runner/r17_verify_delivery.py verify \
  --root "$FR" --manifest "$COLD/delivery_manifest_v2.jsonl" \
  --anchor-file "$COLD/final.anchor.json" \
  --run-record "$RD/run_record.json" \
  --receipt-dir "$COLD/verify_receipts"
echo "=== git blob:"
MAN_BLOB=$(git hash-object "$FR/delivery_manifest_v2.jsonl")
printf 'manifest_blob_id=%s\nregistered_utc=%s\n' \
  "$MAN_BLOB" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$FR/anchors/final.anchor.blob.txt"
echo "manifest_blob_id=$MAN_BLOB"
echo FINALIZE_DONE
