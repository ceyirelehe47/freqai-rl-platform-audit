#!/usr/bin/env bash
# R17 stop-publication 轮:完整副本冷读(任务书 §9.3——复用既有隔离
# 工具,不新建验证平台)。
# 流程:正常已关闭包(非 replay、真实 Windows 采样器、快速业务)
#   → r17_verify_delivery build(run_record→manifest+anchor)
#   → 物理复制交付集合到新根(隔离目录,不回读原件)
#   → verify 仅新根只读核验
#   → 负例:一次性副本缺件/篡改 → verify 必须失败(操作后不恢复)
set -euo pipefail

PROJ="$HOME/projects/crypto_rl"
RUNNER="$PROJ/stage2_6_1_runner"
PS1="${R17_WIN_SAMPLER_PS1:-/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/r17_win_sampler.ps1}"
WORK="${1:-$HOME/r17sp_coldread}"

rm -rf "$WORK"
mkdir -p "$WORK/src_pkg"

echo "== 1. 正常已关闭包(真实采样器;业务=快速成功) =="
SUP_RC=0
python3 "$RUNNER/r17_supervision.py" \
  --run-dir "$WORK/src_pkg/run" \
  --task-kind fixture \
  --win-sampler-ps1 "$PS1" \
  -- bash -c "echo cold_read_ok" > "$WORK/sup_stdout.log" 2>&1 || SUP_RC=$?
echo "supervisor rc=$SUP_RC (stdout 见 $WORK/sup_stdout.log)"
[ "$SUP_RC" -eq 0 ] || { echo "FATAL: 正常 run 非成功" >&2; exit 1; }

python3 - "$WORK/src_pkg/run/run_record.json" <<'PYEOF'
import json, sys
rr = json.load(open(sys.argv[1]))
assert rr["finalized"] is True, "finalized"
assert rr["evidence_complete"] is True, "evidence_complete"
w = rr.get("writers") or {}
assert w.get("guest", {}).get("joined") is True, "guest joined"
assert w.get("win", {}).get("exited") is True, "win exited"
assert w.get("io", {}).get("joined") is True, "io joined"
print("run_record: finalized+evidence_complete+三组写者确认关闭 OK")
PYEOF

echo "== 2. build(run_record→manifest+anchor;root=supervisor 祖父层) =="
python3 "$RUNNER/r17_verify_delivery.py" build \
  --run-record "$WORK/src_pkg/run/run_record.json" \
  --root "$WORK" \
  --manifest-out "$WORK/src_pkg/manifest.jsonl" \
  --anchor-out "$WORK/src_pkg/anchor.json"

echo "== 3. 复制交付集合到新根(隔离;不回读原件) =="
NEWT="$WORK/newroot"
mkdir -p "$NEWT"
# manifest 各行(相对 $WORK 根)+manifest+anchor+run_record
while IFS= read -r line; do
  rel=$(printf '%s' "$line" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["path"])')
  mkdir -p "$NEWT/$(dirname "$rel")"
  cp "$WORK/$rel" "$NEWT/$rel"
done < "$WORK/src_pkg/manifest.jsonl"
cp "$WORK/src_pkg/manifest.jsonl" "$NEWT/manifest.jsonl"
cp "$WORK/src_pkg/anchor.json" "$NEWT/anchor.json"

echo "== 4. 新根只读 verify =="
python3 "$RUNNER/r17_verify_delivery.py" verify \
  --root "$NEWT" \
  --manifest "$NEWT/manifest.jsonl" \
  --anchor-file "$NEWT/anchor.json" \
  --run-record "$NEWT/src_pkg/run/run_record.json" \
  --receipt-dir "$WORK/receipts"
echo "verify(新根只读) rc=0"

echo "== 5. 负例(一次性副本;操作后不恢复) =="
# 5a 缺件:删一个必需角色文件
NEG1="$WORK/neg_missing"
cp -r "$NEWT" "$NEG1"
rm "$NEG1/src_pkg/run/summary.json"
if python3 "$RUNNER/r17_verify_delivery.py" verify \
     --root "$NEG1" --manifest "$NEG1/manifest.jsonl" \
     --anchor-file "$NEG1/anchor.json" \
     --run-record "$NEG1/src_pkg/run/run_record.json" \
     --receipt-dir "$WORK/receipts_neg1" >/dev/null 2>&1; then
  echo "FATAL: 缺件副本 verify 不应通过" >&2; exit 1
fi
echo "负例a(缺件) verify 如实失败 OK"
# 5b 篡改:改一个角色文件字节
NEG2="$WORK/neg_tamper"
cp -r "$NEWT" "$NEG2"
printf 'tampered\n' >> "$NEG2/src_pkg/run/telemetry/guest_samples.jsonl"
if python3 "$RUNNER/r17_verify_delivery.py" verify \
     --root "$NEG2" --manifest "$NEG2/manifest.jsonl" \
     --anchor-file "$NEG2/anchor.json" \
     --run-record "$NEG2/src_pkg/run/run_record.json" \
     --receipt-dir "$WORK/receipts_neg2" >/dev/null 2>&1; then
  echo "FATAL: 篡改副本 verify 不应通过" >&2; exit 1
fi
echo "负例b(篡改) verify 如实失败 OK"

echo "== cold_read_sp: ALL OK =="
