#!/usr/bin/env bash
# read-failure-signal-safety 轮:全量回归收尾(资源复算+build+篡改
# 反例+verify+冷读+blob)。结构与上轮 rsa_closure_delivery.sh 同款。
# 用法(WSL 内): finalize_delivery.sh <全量 run 目录(monitored_entry
# 创建,含 run_record.json)>
set -euo pipefail
RD="$1"
FR="$(dirname "$(dirname "$RD")")"   # full_regression
# run_record 内相对路径基准=full_regression(与上轮交付一致)
ROOT="$FR"
BASE="$(dirname "$(dirname "$FR")")"   # read_failure_signal_safety
RSA="$BASE/read_failure_closure"
REPO=/mnt/f/trading/freqai-rl-audit
cd "$REPO"
PY=python3
mkdir -p "$RSA/anchors" "$RSA/verify_receipts"
echo "=== 资源复算(已关闭原始流重算 vs summary):"
"$PY" "$FR/../tools/recompute_resources.py" "$RD" \
  | tee "$RSA/resource_recompute.json"
echo "=== build:"
"$PY" stage2_6_1/runner/r17_verify_delivery.py build \
  --run-record "$RD/run_record.json" \
  --manifest-out "$RSA/delivery_manifest_v2.jsonl" \
  --anchor-out "$RSA/anchors/final.anchor.json" \
  --root "$ROOT"
echo "=== 验证前篡改反例(追加 1 字节 → 必须检出 → 恢复):"
CP="$RD/telemetry/guest_samples.jsonl"
H0=$(sha256sum "$CP" | cut -d" " -f1)
printf ' ' >> "$CP"
if "$PY" stage2_6_1/runner/r17_verify_delivery.py verify \
  --root "$ROOT" --manifest "$RSA/delivery_manifest_v2.jsonl" \
  --anchor-file "$RSA/anchors/final.anchor.json" \
  --run-record "$RD/run_record.json" \
  --receipt-dir "$RSA/verify_receipts" >/dev/null 2>&1; then
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
  --root "$ROOT" --manifest "$RSA/delivery_manifest_v2.jsonl" \
  --anchor-file "$RSA/anchors/final.anchor.json" \
  --run-record "$RD/run_record.json" \
  --receipt-dir "$RSA/verify_receipts"
echo "=== 冷读(独立目录,脱离开发绝对路径):"
COLD="$RSA/cold_read_final"
rm -rf "$COLD"; mkdir -p "$COLD"
cp "$RSA/delivery_manifest_v2.jsonl" "$RSA/anchors/final.anchor.json" "$COLD/"
"$PY" stage2_6_1/runner/r17_verify_delivery.py verify \
  --root "$ROOT" --manifest "$COLD/delivery_manifest_v2.jsonl" \
  --anchor-file "$COLD/final.anchor.json" \
  --run-record "$RD/run_record.json" \
  --receipt-dir "$COLD/verify_receipts"
echo "=== git blob:"
MAN_BLOB=$(git hash-object "$RSA/delivery_manifest_v2.jsonl")
printf 'manifest_blob_id=%s\nregistered_utc=%s\n' \
  "$MAN_BLOB" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$RSA/anchors/final.anchor.blob.txt"
echo "manifest_blob_id=$MAN_BLOB"
echo FINALIZE_DONE
