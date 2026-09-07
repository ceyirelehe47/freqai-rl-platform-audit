#!/usr/bin/env bash
# R17 续轮(RSA closure):全量回归收尾(资源复算+build+篡改反例+verify+blob)
# 交付文件独立放 rsa_closure/;build/verify 的 --root 为
# result_seal_admission_closure(run_record 相对路径解析所需父级)。
set -euo pipefail
RD="$1"   # 全量 run 目录(final_2026...,含 run_record.json)
ROOT="$(dirname "$(dirname "$RD")")"   # =full_regression(run_record 相对路径基准)
BASE="$(dirname "$ROOT")"              # =result_seal_admission_closure
RSA="$BASE/rsa_closure"
REPO=/mnt/f/trading/freqai-rl-audit
cd "$REPO"
PY=python3
mkdir -p "$RSA/anchors" "$RSA/verify_receipts"
echo "=== 资源复算(已关闭原始流重算 vs summary):"
"$PY" "$BASE/tools/recompute_resources.py" "$RD" \
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
head -c -1 "$CP" > /tmp/_trim_rsa && mv /tmp/_trim_rsa "$CP"
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
echo RSA_FINALIZE_DONE
