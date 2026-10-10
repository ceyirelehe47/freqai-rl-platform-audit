import json, subprocess, sys, tempfile
from pathlib import Path
BASE = Path("/home/cryptorl/tmp_fr1_review")
DOM = BASE / "dom"; PIN = DOM / "release_pin"; PROJ = DOM / "project"
A = "0735f2559aa80889bfed16c88d20e5c72c280a75"
PY = "/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python"
OUT = []
sys.path.insert(0, "/home/cryptorl/projects/crypto_rl_qaf_v3/src")
import rl_curriculum.curriculum261_qaf_provenance_guard as guard
import rl_curriculum.curriculum261_r17_dependencies as dep
import rl_curriculum.curriculum261_r17_cli as cli
guard.R17_PIN_EXPECTED_ROOT = str(PIN)
dep.R17_RELEASE_PIN_ROOT = PIN  # redirect consumer-side readers to isolated pin

def preflight():
    return guard.runtime_dependency_preflight(repo=PIN, project_dir=PROJ,
                                              candidate_sha=A, python=PY)
def rec(name, cond, detail):
    OUT.append({"scenario": name, "passed": bool(cond), "detail": detail})
    print(("PASS " if cond else "FAIL ") + name, str(detail)[:220])

# A) deletion of a digests_match-covered digest file -> refuse
f = PIN / "stage2_6_1/artifacts/repair2/qualification_plan_digest.txt"
d = f.read_bytes(); f.unlink()
rd = preflight()
hit = [p for p in rd.get("problems", []) if "historical_digests" in p]
rec("A_r2_digest_deleted_refused", (not rd["ok"]) and hit, hit)
f.write_bytes(d)
rd = preflight(); rec("A_restore_ok", rd["ok"], rd.get("problems"))

# B) r13 abort marker (r13_binding worktree file, NOT in digests_match)
g = PIN / "stage2_6_1/artifacts/repair13/r13_iteration_aborted.json"
dg = g.read_bytes(); g.unlink()
rd = preflight()
hit = [p for p in rd.get("problems", []) if "historical_digests" in p or "branch_lineage" in p]
rec("B_r13_abort_marker_deleted_preflight_still_ok", rd["ok"] and not hit,
    {"ok": rd["ok"], "problems": rd.get("problems", [])[:3]})
try:
    tmp = Path(tempfile.mkdtemp(prefix="r13b_", dir=str(BASE)))
    b = cli._r13_failure_binding(tmp)
    audit_side = "pass=" + str(b.get("pass"))
except Exception as e:
    audit_side = "RAISED: " + str(e)[:120]
rec("B_audit_side_r13_binding_fails_same_condition",
    audit_side.startswith("RAISED"), audit_side)
g.write_bytes(dg)
rd = preflight(); rec("B_restore_ok", rd["ok"], rd.get("problems"))

# C) r11 cue_event_trace.jsonl (r11_binding file, NOT in digests_match r11 set)
h = PIN / "stage2_6_1/artifacts/repair11/cue_event_trace.jsonl"
dh = h.read_bytes(); h.unlink()
rd = preflight()
rec("C_r11_cue_event_trace_deleted_preflight_still_ok", rd["ok"],
    {"ok": rd["ok"], "problems": rd.get("problems", [])[:3]})
try:
    tmp2 = Path(tempfile.mkdtemp(prefix="r11b_", dir=str(BASE)))
    b2 = cli._r11_abort_binding(tmp2)
    audit_side2 = "pass=" + str(b2.get("pass"))
except Exception as e:
    audit_side2 = "RAISED: " + str(e)[:120]
rec("C_audit_side_r11_binding_fails_same_condition",
    audit_side2.startswith("RAISED"), audit_side2)
h.write_bytes(dh)
rd = preflight(); rec("C_restore_ok", rd["ok"], rd.get("problems"))

(BASE / "results" / "residual_probe.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1))
n_fail = sum(1 for r in OUT if not r["passed"])
print("TOTAL %d, %d failed" % (len(OUT), n_fail))
sys.exit(1 if n_fail else 0)
