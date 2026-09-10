#!/usr/bin/env bash
# [新执行 2026-09-10] 第4项补件之三:隔离包三类篡改负例(缺件/追加/同长度篡改)
# 在本目录的工作副本(work_pkg)上复演,每例后恢复,最后做恢复后健康复核。
# 与原件 build_pkg.sh 第6/7步同机制;归档包(originals/04_full2_pkg)不被触碰。
# 预期:三负例 audit rc 均!=0,恢复后 rc=0。
set -uo pipefail
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development
DELIV=$BASE/native_sampler_validation_delivery
NEW=$DELIV/new_executions_20260910
HERE=$NEW/05_pkg_negatives
W=$HERE/work_pkg
ID=r17ns_full2_20260909T174348

rm -rf "$W"
cp -r "$DELIV/originals/04_full2_pkg" "$W"
TEL="$W/runs/$ID/telemetry/win_samples.jsonl"
cp "$TEL" "$W/tel_pristine.bak"

audit() {
  python3 "$W/code/r17_required_bytes.py" \
    --root "$W" \
    --record "$W/runs/$ID/run_record.json"
}

# 6a 缺件
mv "$TEL" "$TEL.hidden"
audit > "$HERE/neg_missing/audit_stdout.json" 2> "$HERE/neg_missing/audit_stderr.log"
NEG_MISSING_RC=$?
echo "$NEG_MISSING_RC" > "$HERE/neg_missing/rc.txt"
mv "$TEL.hidden" "$TEL"

# 6b 追加一行(时间戳用新执行当日,区别于原件的 19:00:00Z 行)
printf '{"seq":99999,"event":"sample","run_id":"%s","utc":"2026-09-10T00:00:00Z"}\n' "$ID" >> "$TEL"
audit > "$HERE/neg_append/audit_stdout.json" 2> "$HERE/neg_append/audit_stderr.log"
NEG_APPEND_RC=$?
echo "$NEG_APPEND_RC" > "$HERE/neg_append/rc.txt"
cp "$W/tel_pristine.bak" "$TEL"

# 6c 同长度篡改(首字节翻转,尺寸不变)
python3 - "$TEL" <<'PYEOF'
import sys
p = sys.argv[1]
b = bytearray(open(p, "rb").read())
b[0] = ord("{") if b[0] != ord("{") else ord("[")
open(p, "wb").write(bytes(b))
print("same-length tamper applied, size preserved:", len(b))
PYEOF
audit > "$HERE/neg_tamper/audit_stdout.json" 2> "$HERE/neg_tamper/audit_stderr.log"
NEG_TAMPER_RC=$?
echo "$NEG_TAMPER_RC" > "$HERE/neg_tamper/rc.txt"
cp "$W/tel_pristine.bak" "$TEL"

# 恢复后健康复核
audit > "$HERE/restored_healthy/audit_stdout.json" 2> "$HERE/restored_healthy/audit_stderr.log"
RESTORED_RC=$?
echo "$RESTORED_RC" > "$HERE/restored_healthy/rc.txt"

echo "NEG_MISSING_RC=$NEG_MISSING_RC(期望非0)"
echo "NEG_APPEND_RC=$NEG_APPEND_RC(期望非0)"
echo "NEG_TAMPER_RC=$NEG_TAMPER_RC(期望非0)"
echo "RESTORED_HEALTHY_RC=$RESTORED_RC(期望0)"
sha256sum "$TEL"

if [ "$NEG_MISSING_RC" -ne 0 ] && [ "$NEG_APPEND_RC" -ne 0 ] && [ "$NEG_TAMPER_RC" -ne 0 ] && [ "$RESTORED_RC" -eq 0 ]; then
  rm -f "$W/tel_pristine.bak"
  echo "NEGATIVES_OUTCOME=ALL_AS_EXPECTED"
  exit 0
else
  echo "NEGATIVES_OUTCOME=UNEXPECTED(保留现场供检查)"
  exit 1
fi
