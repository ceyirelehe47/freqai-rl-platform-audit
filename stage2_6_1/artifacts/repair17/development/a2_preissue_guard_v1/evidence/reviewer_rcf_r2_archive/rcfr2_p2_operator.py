# -*- coding: utf-8 -*-
"""RCF R2 independent probe: RCF-02 pre-permit full same-root verify
(operator level) + RCF-03 continuous leaf boundary (real chain).

Independent scenarios (not a rerun of the author's tests):
  S1  wrong cwd written into the REAL record fields (runs[0].cwd) -> pre-permit refuse
  S1b author-style mutation (block-level keys + record moved) -> reason check
  S2  junit missing -> refuse;  S3 junit tampered -> refuse
  S4  deploy src drift -> refuse
  S5  normal path: real operator execute -> permit/admission -> launch ->
      chain to determinism leaf sentinel (marker v2 + gate consumed + no science)
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
TREE = Path("/home/cryptorl/projects/crypto_rl_qaf_v2")
TESTS = TREE / "tests" / "route_c_stage2_6_1"
sys.path.insert(0, str(TREE / "src"))
sys.path.insert(0, str(TESTS))
PY = sys.executable
WORK = Path("/mnt/f/trading/local/rcf_r2_review/p2_work")
RESULTS = []

def rec(name, ok, detail=""):
    RESULTS.append({"scenario": name, "ok": bool(ok), "detail": str(detail)[:900]})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {str(detail)[:700]}")

import test_curriculum261_qaf_v2_reviewclosure as rct  # noqa: E402

def rm(p):
    if p.exists():
        shutil.rmtree(p)

rm(WORK)
WORK.mkdir(parents=True)

print("== building sandbox domain (real executor run) ==")
d = rct._make_rc_domain(WORK / "dom", "p2")
d["tree"] = subprocess.run(
    ["git", "-C", str(d["repo"]), "rev-parse", d["commit_a"] + "^{tree}"],
    capture_output=True, text=True, check=True).stdout.strip()
print("domain:", json.dumps({k: str(v) for k, v in d.items()}, indent=1)[:1200])
RECORD = Path(d["record"])

def snapshot(d):
    au = d["authority"]
    return {
        "authority_files": sorted(str(p.relative_to(au)) for p in au.rglob("*") if p.is_file()),
        "admission": (d["deploy"] / ".r17_formal_admission.json").exists(),
        "issuance_log": (d["deploy"] / "r17_admission_issued.jsonl").exists(),
        "permits": sorted(p.name for p in au.glob("qprod_permit_*")),
        "preregs": sorted(p.name for p in au.glob("preregistration_*")),
        "state_exists": Path(d["state"]).exists(),
    }

def run_execute(d, evidence, extra=(), env_extra=None):
    argv = [PY, str(rct._runner_dir() / "qaf_v2_operator_entry.py"), "execute",
            "--repo", str(d["repo"]),
            "--guard-repo", str(rct._guard_repo()),
            "--deploy-root", str(d["deploy"]),
            "--project-dir", str(rct._project_tree_root()),
            "--approval-json", str(rct._approval_path(d)),
            "--regression-evidence", str(evidence),
            "--admission-id", "rcfr2-probe",
            "--authorization", "probe:RCFR2 independent",
            "--plan-digest", d["tree"],
            "--plan-digest-method", "git_tree_digest",
            "--code-freeze-sha", d["commit_a"],
            "--stop-after", "verify-formal-logs", "--model-update",
            "--attempt", "qaf_v2", *extra]
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=1200, cwd=str(TREE), env=env)

def verify_reason(d, evidence_path):
    """direct deep-verify call, same argv shape as the operator's new block"""
    pre = d["base"] / "prereg_ro.json"
    pre.write_text(json.dumps({
        "admission_id": "PRE-PERMIT-READONLY-VERIFY",
        "iteration": "qprod_a_formal_v2",
        "plan_digest": d["tree"],
        "plan_digest_method": "git_tree_digest",
        "authorization": "NOT_AN_AUTHORIZATION: probe",
        "regression_evidence": str(evidence_path),
        "deploy_state_root": str(d["state"]),
        "formal_attempt": "qaf_v2",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(d["deploy"] / "src")
    p = subprocess.run(
        [PY, "-m", "rl_curriculum.curriculum261_r17_admission_substance",
         "verify", "--repo", str(d["repo"]),
         "--commit-a", d["commit_a"], "--deploy-root", str(d["deploy"]),
         "--preregistration", str(pre)],
        cwd=str(d["deploy"]), capture_output=True, text=True, env=env)
    return p.returncode, (p.stdout or p.stderr).strip()

# ---------------- S1: correct-field wrong cwd (in place) ------------------
original = RECORD.read_bytes()
rec_doc = json.loads(original)
rec_doc["collection_run"]["runs"][0]["cwd"] = "/nonexistent/other/root"
rec_doc["execution"]["runs"][0]["cwd"] = "/nonexistent/other/root"
RECORD.write_text(json.dumps(rec_doc, ensure_ascii=False), encoding="utf-8")
rc_v, reason = verify_reason(d, RECORD)
rec("s1a_verify_correct_field_cwd", rc_v == 2 and "cwd" in reason,
    f"rc={rc_v} reason={reason[:120]}")
before = snapshot(d)
proc = run_execute(d, RECORD, extra=("--test-domain",))
after = snapshot(d)
RECORD.write_bytes(original)
rec("s1b_operator_refuses_pre_permit_correct_cwd",
    proc.returncode == 96 and "同根核验失败" in proc.stdout
    and "cwd" in proc.stdout and after == before,
    f"rc={proc.returncode} stdout_tail={proc.stdout[-260:]!r} zero_writes={after == before}")

# ---------------- S1b: author-style mutation control ----------------------
bad = d["base"] / "wrong_cwd_record_authorstyle.json"
rec2 = json.loads(original)
rec2.setdefault("collection_run", {})["cwd"] = "/nonexistent/other/root"
rec2.setdefault("execution", {})["cwd"] = "/nonexistent/other/root"
bad.write_text(json.dumps(rec2, ensure_ascii=False), encoding="utf-8")
rc_a, reason_a = verify_reason(d, bad)
rec("s1c_author_style_reason_is_relocation_not_cwd",
    rc_a == 2 and "cwd" not in reason_a,
    f"rc={rc_a} reason={reason_a[:140]} (record relocated -> artifact refs break)")

# ---------------- S1d: fixed-test shape (real runs[*].cwd, sibling) --------
bad2 = RECORD.parent / "wrong_cwd_record_probe.json"
rec3 = json.loads(original)
rec3["collection_run"]["runs"][0]["cwd"] = "/nonexistent/other/root"
for _run in rec3["execution"].get("runs", []):
    _run["cwd"] = "/nonexistent/other/root"
bad2.write_text(json.dumps(rec3, ensure_ascii=False), encoding="utf-8")
rc_d, reason_d = verify_reason(d, bad2)
before = snapshot(d)
proc = run_execute(d, bad2, extra=("--test-domain",))
after = snapshot(d)
bad2.unlink(missing_ok=True)
rec("s1d_fixed_test_shape_binds_cwd_reason",
    rc_d == 2 and "cwd" in reason_d and "junit_missing" not in reason_d
    and proc.returncode == 96 and "cwd" in proc.stdout and after == before,
    "verify_rc=%s reason=%s operator_rc=%s zero_writes=%s" % (
        rc_d, reason_d[:120], proc.returncode, after == before))

# ---------------- S2: junit missing ---------------------------------------
jref = rec_doc["junit"][0]["path"] if isinstance(rec_doc.get("junit"), list) else None
jp = RECORD.parent / jref
jbytes = jp.read_bytes()
jp.unlink()
rc_v, reason = verify_reason(d, RECORD)
rec("s2a_verify_junit_missing", rc_v == 2 and "junit_missing" in reason,
    f"rc={rc_v} reason={reason[:120]}")
before = snapshot(d)
proc = run_execute(d, RECORD, extra=("--test-domain",))
after = snapshot(d)
jp.write_bytes(jbytes)
rec("s2b_operator_refuses_pre_permit_junit_missing",
    proc.returncode == 96 and after == before and "one_shot_writes\": 0" in proc.stdout,
    f"rc={proc.returncode} zero_writes={after == before}")

# ---------------- S3: junit tampered --------------------------------------
jp.write_bytes(jbytes + b"\n<!--tamper-->\n")
rc_v, reason = verify_reason(d, RECORD)
before = snapshot(d)
proc = run_execute(d, RECORD, extra=("--test-domain",))
after = snapshot(d)
jp.write_bytes(jbytes)
rec("s3_junit_tampered_refused_pre_permit",
    rc_v == 2 and "sha_mismatch" in reason and proc.returncode == 96 and after == before,
    f"verify_rc={rc_v} reason={reason[:100]} operator_rc={proc.returncode} zero_writes={after == before}")

# ---------------- S4: deploy src byte drift -------------------------------
drift = sorted((d["deploy"] / "src" / "rl_curriculum").glob("*.py"))[0]
db = drift.read_bytes()
drift.write_bytes(db + b"\n# drift\n")
rc_v, reason = verify_reason(d, RECORD)
before = snapshot(d)
proc = run_execute(d, RECORD, extra=("--test-domain",))
after = snapshot(d)
drift.write_bytes(db)
rec("s4_deploy_drift_refused_pre_permit",
    rc_v == 2 and ("deploy_mismatch" in reason or "surface" in reason)
    and proc.returncode == 96 and after == before,
    f"verify_rc={rc_v} reason={reason[:120]} operator_rc={proc.returncode} zero_writes={after == before}")

# ---------------- S5: normal path -> chain -> leaf sentinel ---------------
before = snapshot(d)
res = run_execute(d, RECORD, extra=("--test-domain", "--leaf-sentinel",
                                    "determinism-matrix"),
                  env_extra={"R17_RELEASE_REPO": str(d["repo"])})
out = res.stdout
au = d["authority"]
permits = list(au.glob("qprod_permit_*"))
admission = d["deploy"] / ".r17_formal_admission.json"
log = d["deploy"] / "r17_admission_issued.jsonl"
marker = d["art"] / "leaf_sentinel_marker.json"
gate = d["art"] / "chain_budget_gate.json"
verify = d["art"] / "gate_topology_provenance_verify.json"
m = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
g = json.loads(gate.read_text(encoding="utf-8")) if gate.is_file() else {}
det_dir = d["art"] / "determinism"
det_files = sorted(p.name for p in det_dir.iterdir()) if det_dir.is_dir() else None
chain_result = d["art"] / "r17_chain_result.json"
cdoc = json.loads(chain_result.read_text(encoding="utf-8")) if chain_result.is_file() else {}
print("S5 rc:", res.returncode)
print("S5 permits:", [p.name for p in permits])
print("S5 marker:", json.dumps(m, ensure_ascii=False))
print("S5 gate consumed:", g.get("consumed"))
print("S5 determinism dir:", det_files)
print("S5 chain result ok/failed_step:", cdoc.get("ok"), cdoc.get("failed_step"))
print("S5 stdout tail:", out[-1200:])
ok5 = (
    len(permits) == 1 and admission.is_file() and log.is_file()
    and m.get("format") == "cur261-qaf-test-leaf-sentinel-v2"
    and m.get("science_executed") is False
    and m.get("prerequisites_executed") == {"stage_budget_gate": True,
                                            "attempt_identity_resolved": True}
    and m.get("stress_namespace") == "stress_qaf_v2"
    and (g.get("consumed") or {}).get("determinism-matrix")
    and det_files == []
    and verify.is_file() and json.loads(verify.read_text())["pass"] is True
    and cdoc.get("ok") is False and cdoc.get("failed_step") in ("audit", "determinism-matrix")
    and res.returncode != 0
)
rec("s5_operator_chain_to_leaf_sentinel", ok5,
    f"rc={res.returncode} permit={len(permits)} admission={admission.is_file()} "
    f"marker_v2={m.get('format')} stress_ns={m.get('stress_namespace')} "
    f"gate_consumed={sorted((g.get('consumed') or {}).keys())} det_files={det_files} "
    f"chain={cdoc.get('ok')}/{cdoc.get('failed_step')}")

print("\n==== SUMMARY ====")
badl = [r for r in RESULTS if not r["ok"]]
print(f"{len(RESULTS) - len(badl)}/{len(RESULTS)} scenario assertions passed")
for r in badl:
    print("FAILED:", json.dumps(r, ensure_ascii=False))
(WORK.parent / "p2_results.json").write_text(
    json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
sys.exit(1 if badl else 0)
