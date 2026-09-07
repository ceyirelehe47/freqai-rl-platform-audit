#!/usr/bin/env bash
# 全量 run 关键数据核对(junit/summary/run_record)。
set -uo pipefail
RD=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/unified_shutdown_cold_read/runs/final_20260907T163430
python3 - "$RD" <<'PYEOF'
import json, sys, xml.etree.ElementTree as ET
rd = __import__("pathlib").Path(sys.argv[1])
j = ET.parse(rd / "junit.xml").getroot()
s = json.loads((rd / "summary.json").read_text(encoding="utf-8"))
r = json.loads((rd / "run_record.json").read_text(encoding="utf-8"))
suites = j.findall("testsuite") or [j]
 tot = fail = err = skip = 0
 for ts in suites:
    tot += int(ts.get("tests", 0)); fail += int(ts.get("failures", 0))
    err += int(ts.get("errors", 0)); skip += int(ts.get("skipped", 0))
print("junit:", {"tests": tot, "failures": fail, "errors": err,
                 "skipped": skip, "passed": tot - fail - err - skip})
print("summary.business.rc:", s["business"]["rc"])
print("summary.io:", {k: s["io"][k] for k in
      ("submitted", "accepted", "ok", "failed", "queued",
       "in_flight", "dropped_critical", "io_stuck")})
cov = s["coverage"]
print("coverage.win_read_failures:", cov.get("win_read_failures"),
      "last_op:", cov.get("win_read_failure_last_op"))
print("coverage.telemetry_capped:", cov.get("telemetry_capped"),
      "coverage_gaps is None:", cov.get("coverage_gaps") is None)
print("coverage.win_last_mono/guest_last_mono:",
      cov.get("win_last_mono"), cov.get("guest_last_mono"))
print("external_stop_sig:", s.get("external_stop_sig"),
      "sig_count:", s.get("external_stop_sig_count"))
print("residual_unconfirmed:", s.get("residual_unconfirmed"))
print("stop_requested_reasons:", s.get("stop_requested_reasons"))
print("run_record.evidence_complete:", r["evidence_complete"],
      "missing_roles:", r["missing_roles"], "finalized:", r["finalized"])
print("run_record.required roles:",
      [e["role"] for e in r["required"]])
PYEOF
grep -o "MONITORED_RC=[0-9]*" /tmp/r17u_full_out.txt 2>/dev/null | head -1
tail -c 400 "$RD/business/stdout.log" 2>/dev/null | tr -d '\0'
