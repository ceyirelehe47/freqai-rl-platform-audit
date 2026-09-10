#!/usr/bin/env bash
# R17 验证E-3:full2 交付副本包 + 隔离冷读 + 三类篡改负例
set -uo pipefail
source ~/projects/crypto_rl/activate-freqtrade.sh >/dev/null 2>&1

RUN=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision/runs/r17ns_full2_20260909T174348
C3=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_entry_temp_ownership_closure
RUNNER=/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner
PKG=/mnt/f/trading/r17_native_smoke_logs/full2_pkg
ID=r17ns_full2_20260909T174348

rm -rf "$PKG"
mkdir -p "$PKG/runs" "$PKG/c3_evidence" "$PKG/code"

# 1) 全部必要原始文件 + native 三证明(整 run 目录副本)
cp -r "$RUN" "$PKG/runs/$ID"

# 2) 既有正确 C3 证据(不改旧包,复制入包)
cp "$C3/verification_v6/receipts_v6/semantic_health.json" "$PKG/c3_evidence/"
cp "$C3/verification_v6/cold_read_report_v6.json" "$PKG/c3_evidence/"
cp "$C3/counterexamples/old_reader_counterexamples_v6.json" "$PKG/c3_evidence/"
cp "$C3/counterexamples/fixed_reader_flip_v6.json" "$PKG/c3_evidence/"
cp "$RUNNER/r17_c3_engineering_slice.py" "$PKG/c3_evidence/candidate_reader.py"

# 3) 实际用到的新验证代码(Python/PS1/C#)+legacy 汇总
cp "$RUNNER/r17_required_bytes.py" "$RUNNER/r17_verified_aggregate.py" \
   "$RUNNER/r17_native_sampler.py" "$RUNNER/r17_win_sampler_control.ps1" \
   "$RUNNER/r17_win_sampler_lifecycle.ps1" "$RUNNER/r17_win_process.cs" \
   "$RUNNER/r17_win_sampler.ps1" "$RUNNER/r17_supervision.py" \
   "$C3/tools/aggregate_v6.py" "$PKG/code/"

# 4) 冷读 config:全部路径指向包内
python3 - "$PKG" "$ID" <<'PYEOF'
import json, sys
pkg, rid = sys.argv[1], sys.argv[2]
cfg = {
 "full_run_record": f"{pkg}/runs/{rid}/run_record.json",
 "full_stdout": f"{pkg}/runs/{rid}/business/stdout.log",
 "full_junit": f"{pkg}/runs/{rid}/junit.xml",
 "c3_semantic_receipt": f"{pkg}/c3_evidence/semantic_health.json",
 "c3_cold_read_report": f"{pkg}/c3_evidence/cold_read_report_v6.json",
 "old_counterexamples": f"{pkg}/c3_evidence/old_reader_counterexamples_v6.json",
 "fixed_flip": f"{pkg}/c3_evidence/fixed_reader_flip_v6.json",
 "candidate_reader": f"{pkg}/c3_evidence/candidate_reader.py"}
json.dump(cfg, open(f"{pkg}/cold_config.json", "w"), indent=1)
# 隔离断言:config 所有路径都在包内
assert all(v.startswith(pkg + "/") for v in cfg.values()), "config 路径逃逸包外"
print("cold_config ok, all paths inside package")
PYEOF

# 5) 隔离冷读(健康副本必须过)
python3 "$PKG/code/r17_verified_aggregate.py" \
  --root "$PKG" --record "$PKG/runs/$ID/run_record.json" \
  --legacy-script "$PKG/code/aggregate_v6.py" \
  --config "$PKG/cold_config.json" \
  --out "$PKG/verified_aggregate_cold.json"
COLD_RC=$?
echo "COLD_READ_RC=$COLD_RC"

# 6) 三类篡改负例(只作用于包内可写副本;每例后恢复)
TEL="$PKG/runs/$ID/telemetry/win_samples.jsonl"
cp "$TEL" "$PKG/runs/$ID/telemetry/win_samples.jsonl.bak"

run_audit() {
  python3 "$PKG/code/r17_required_bytes.py" --root "$PKG" \
    --record "$PKG/runs/$ID/run_record.json" > /tmp/neg_audit.json 2>&1
  echo $?
}

# 6a 缺件
mv "$TEL" "$TEL.hidden"
NEG_MISSING_RC=$(run_audit)
mv "$TEL.hidden" "$TEL"

# 6b 追加一行
printf '{"seq":99999,"event":"sample","run_id":"%s","utc":"2026-09-09T19:00:00Z"}\n' "$ID" >> "$TEL"
NEG_APPEND_RC=$(run_audit)
cp "$PKG/runs/$ID/telemetry/win_samples.jsonl.bak" "$TEL"

# 6c 同长度篡改(首字节翻转)
python3 - "$TEL" <<'PYEOF'
import sys
p = sys.argv[1]
b = bytearray(open(p, "rb").read())
b[0] = ord("{") if b[0] != ord("{") else ord("[")
open(p, "wb").write(bytes(b))
print("same-length tamper applied, size preserved:", len(b))
PYEOF
NEG_TAMPER_RC=$(run_audit)
cp "$PKG/runs/$ID/telemetry/win_samples.jsonl.bak" "$TEL"

echo "NEG_MISSING_RC=$NEG_MISSING_RC(期望非0)"
echo "NEG_APPEND_RC=$NEG_APPEND_RC(期望非0)"
echo "NEG_TAMPER_RC=$NEG_TAMPER_RC(期望非0)"

# 7) 恢复后健康副本复核仍过
FINAL_CHECK_RC=$(run_audit)
echo "RESTORED_HEALTHY_RC=$FINAL_CHECK_RC(期望0)"
rm "$PKG/runs/$ID/telemetry/win_samples.jsonl.bak"
sha256sum "$TEL"
