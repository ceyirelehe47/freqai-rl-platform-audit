#!/usr/bin/env bash
# [新执行 2026-09-10] 第2项补件:fg 与 setsid 两短 run 的封口后观测。
# 双点间隔 11s(> 采样器默认 IntervalSeconds=5 的两个周期),核验:
# 终态登记 terminal.json 的 bytes/sha256 与当前遥测一致,且两点之间无增长。
# 对 run 目录只读;输出只写本目录。
set -uo pipefail
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development
NEW=$BASE/native_sampler_validation_delivery/new_executions_20260910

python3 - "$NEW/06_post_seal_observation/observation.json" <<'PYEOF'
import json, hashlib, os, time, datetime, sys

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def snap(p):
    return {"bytes": os.path.getsize(p),
            "sha256": sha(p),
            "mtime_utc": datetime.datetime.fromtimestamp(os.path.getmtime(p), datetime.timezone.utc).isoformat()}

out = {"scope": "post-seal observation (NEW execution 2026-09-10): two-point stability of sealed win telemetry vs terminal.json",
       "two_point_interval_s": 11,
       "sampler_default_interval_s": 5,
       "runs": []}
allok = True
for rid in ["r17ns_fg_20260909T165222", "r17ns_setsid_20260909T165735"]:
    rd = "/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision/runs/" + rid
    tel = rd + "/telemetry/win_samples.jsonl"
    term = json.load(open(rd + "/native_sampler/terminal.json", encoding="utf-8"))
    t1 = snap(tel)
    time.sleep(11)
    t2 = snap(tel)
    lines = open(tel, "rb").read().splitlines()
    last = json.loads(lines[-1]) if lines else {}
    ok = (t1 == t2 and t1["bytes"] == term.get("bytes") and t1["sha256"] == term.get("sha256"))
    allok = allok and ok
    out["runs"].append({
        "run_id": rid,
        "terminal_declared": {"bytes": term.get("bytes"), "sha256": term.get("sha256"),
                               "reason": term.get("reason"), "clean": term.get("clean")},
        "t1": t1, "t2": t2,
        "last_sample": {"utc": last.get("utc"), "event": last.get("event")},
        "stable_and_matches_terminal": ok})
out["all_ok"] = allok
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), indent=1)
print("OBSERVATION_OK" if allok else "OBSERVATION_MISMATCH")
sys.exit(0 if allok else 1)
PYEOF
RC=$?
echo "OBSERVATION_RC=$RC"
exit "$RC"
