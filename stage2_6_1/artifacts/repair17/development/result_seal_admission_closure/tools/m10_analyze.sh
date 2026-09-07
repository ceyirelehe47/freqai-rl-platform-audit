#!/usr/bin/env bash
# 分析 m10 失败现场
set -u
D="${1:-/tmp/pytest-of-cryptorl/pytest-0/test_m10_critical_stops_busine0}"
python3 - "$D" << 'PYEOF'
import json, sys, os
d = sys.argv[1]
sp = os.path.join(d, "run", "summary.json")
if not os.path.isfile(sp):
    print("summary 不存在:", sp)
    print("目录内容:", os.listdir(d) if os.path.isdir(d) else "无")
    sys.exit(0)
s = json.load(open(sp))
b = s["business"]
print("rc:", b["rc"], "signal:", b["signal"])
print("protector:", json.dumps(b.get("protector"))[:420])
print("stop_reasons:", s.get("stop_requested_reasons"))
print("residual_unconfirmed:", s.get("residual_unconfirmed"))
print("io:", json.dumps(s.get("io"))[:260])
print("stage_marks:", json.dumps(s.get("stage_marks"))[:260])
ap = os.path.join(d, "run", "alerts", "alerts.jsonl")
print("--- alerts 关键事件 ---")
for l in open(ap).read().splitlines():
    o = json.loads(l)
    ev = o.get("event")
    if ev in ("stop_requested", "sigterm_sent", "business_started",
              "business_exited", "supervisor_end", "escalate",
              "kill_sent", "run_timeout", "business_spawn_failed"):
        print(ev, "|", str(o)[:180])
PYEOF
