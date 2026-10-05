# -*- coding: utf-8 -*-
"""RCF R2 independent probe: RCF-03 sentinel placement + gate wiring.

Direct CLI runs of r17_cli determinism-matrix in isolated tmp dirs:
  g1 no gate, no deployed env, sentinel -> rc0 + marker v2 (engineering path unchanged)
  g2 root gate (in plan), sentinel -> rc0 + gate consumed + marker v2 + stress ns
  g3 subdir gate layout -> fallback hit + consumed
  g4 gate without determinism-matrix in plan -> rc2, no marker
  g5 no gate + deployed env -> rc2 fail closed, no marker
  g6 gate pre-consumed -> rc2, no marker
  g7 invalid --formal-namespace-attempt -> rc2, no marker
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
TREE = Path("/home/cryptorl/projects/crypto_rl_qaf_v2")
sys.path.insert(0, str(TREE / "src"))
PY = sys.executable
WORK = Path("/mnt/f/trading/local/rcf_r2_review/p4_work")
RESULTS = []

def rec(name, ok, detail=""):
    RESULTS.append({"scenario": name, "ok": bool(ok), "detail": str(detail)[:700]})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {str(detail)[:600]}")

from rl_curriculum.curriculum261_qprod_formal_budget import (
    write_chain_budget_gate)

STEPS = ["provenance-verify", "determinism-matrix", "audit",
         "verify-formal-logs"]

def fresh(tag):
    d = WORK / tag
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d

def run(d, *, attempt=None, env_extra=None, timeout=120):
    argv = [PY, "-m", "rl_curriculum.curriculum261_r17_cli",
            "determinism-matrix", "--out-dir", str(d)]
    if attempt is not None:
        argv += ["--formal-namespace-attempt", attempt]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(TREE / "src")
    env["CURRICULUM261_QAF_TEST_LEAF_SENTINEL"] = "determinism-matrix"
    env.update(env_extra or {})
    return subprocess.run(argv, cwd=str(TREE), env=env, capture_output=True,
                          text=True, timeout=timeout)

def read_json(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

if WORK.exists():
    shutil.rmtree(WORK)
WORK.mkdir(parents=True)

# g1: engineering path, no gate, no deployed env
d = fresh("g1")
p = run(d, attempt="qaf_v2")
m = read_json(d / "leaf_sentinel_marker.json")
det = d / "determinism"
det_files = sorted(q.name for q in det.iterdir()) if det.is_dir() else None
rec("g1_no_gate_engineering_unchanged",
    p.returncode == 0 and m is not None
    and m.get("format") == "cur261-qaf-test-leaf-sentinel-v2"
    and m.get("stress_namespace") == "stress_qaf_v2"
    and not (d / "chain_budget_gate.json").exists()
    and det_files == [],
    f"rc={p.returncode} marker_ns={m and m.get('stress_namespace')} det={det_files}")

# g2: root gate in plan -> hit + consumed
d = fresh("g2")
write_chain_budget_gate(d, steps_in_plan=STEPS, stop_after="verify-formal-logs")
p = run(d, attempt="qaf_v2")
g = read_json(d / "chain_budget_gate.json")
m = read_json(d / "leaf_sentinel_marker.json")
det = d / "determinism"
det_files = sorted(q.name for q in det.iterdir()) if det.is_dir() else None
rec("g2_root_gate_hit_and_consumed",
    p.returncode == 0
    and (g.get("consumed") or {}).get("determinism-matrix")
    and m is not None and m.get("prerequisites_executed") == {
        "stage_budget_gate": True, "attempt_identity_resolved": True}
    and det_files == [],
    f"rc={p.returncode} consumed={sorted((g.get('consumed') or {}).keys())}")

# g3: subdir gate layout -> fallback hit
d = fresh("g3")
sub = d / "determinism"
sub.mkdir(parents=True)
write_chain_budget_gate(sub, steps_in_plan=STEPS, stop_after="verify-formal-logs")
p = run(d, attempt="qaf_v2")
g = read_json(sub / "chain_budget_gate.json")
m = read_json(d / "leaf_sentinel_marker.json")
rec("g3_subdir_gate_fallback_hit",
    p.returncode == 0 and (g.get("consumed") or {}).get("determinism-matrix")
    and m is not None,
    f"rc={p.returncode} consumed={sorted((g.get('consumed') or {}).keys())}")

# g4: gate without determinism-matrix -> refuse, no marker
d = fresh("g4")
write_chain_budget_gate(d, steps_in_plan=["provenance-verify", "audit",
                                          "verify-formal-logs"],
                        stop_after="verify-formal-logs")
p = run(d, attempt="qaf_v2")
g = read_json(d / "chain_budget_gate.json")
rec("g4_gate_step_not_in_plan_refused",
    p.returncode == 2 and not (d / "leaf_sentinel_marker.json").exists()
    and not (g.get("consumed") or {}),
    f"rc={p.returncode} stdout={p.stdout.strip()[:140]}")

# g5: no gate + deployed env -> fail closed, no marker
d = fresh("g5")
state = d / "state"; state.mkdir()
p = run(d, attempt="qaf_v2",
        env_extra={"CURRICULUM261_R17_DEPLOYED_STATE_ROOT": str(state)})
rec("g5_missing_gate_formal_context_fail_closed",
    p.returncode == 2 and not (d / "leaf_sentinel_marker.json").exists()
    and "预算门缺失" in p.stdout,
    f"rc={p.returncode} stdout={p.stdout.strip()[:160]}")

# g6: pre-consumed gate -> refuse, no marker
d = fresh("g6")
write_chain_budget_gate(d, steps_in_plan=STEPS, stop_after="verify-formal-logs")
gp = d / "chain_budget_gate.json"
doc = read_json(gp)
doc["consumed"]["determinism-matrix"] = "prior-run"
gp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
p = run(d, attempt="qaf_v2")
rec("g6_preconsumed_refused_no_marker",
    p.returncode == 2 and not (d / "leaf_sentinel_marker.json").exists()
    and "已消费" in p.stdout,
    f"rc={p.returncode} stdout={p.stdout.strip()[:160]}")

# g7: invalid attempt -> argparse reject before anything
d = fresh("g7")
p = run(d, attempt="bogus")
rec("g7_invalid_attempt_rejected",
    p.returncode == 2 and not (d / "leaf_sentinel_marker.json").exists()
    and not (d / "chain_budget_gate.json").exists(),
    f"rc={p.returncode} stderr={p.stderr.strip()[:120]}")

print("\n==== SUMMARY ====")
bad = [r for r in RESULTS if not r["ok"]]
print(f"{len(RESULTS) - len(bad)}/{len(RESULTS)} scenario assertions passed")
for r in bad:
    print("FAILED:", json.dumps(r, ensure_ascii=False))
(WORK.parent / "p4_results.json").write_text(
    json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
sys.exit(1 if bad else 0)
