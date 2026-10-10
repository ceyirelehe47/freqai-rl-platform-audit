# -*- coding: utf-8 -*-
"""FR1 independent reviewer probe (own domain, own scenarios)."""
import json, os, shutil, subprocess, sys
from pathlib import Path

BASE = Path("/home/cryptorl/tmp_fr1_review")
DOM = BASE / "dom"
PIN = DOM / "release_pin"
PROJ = DOM / "project"
VEND = PROJ / "vendor" / "freqtrade"
A = "0735f2559aa80889bfed16c88d20e5c72c280a75"
PY = "/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python"
BR = "route-c-stage2-6-1-repair17"

sys.path.insert(0, "/home/cryptorl/projects/crypto_rl_qaf_v3/src")
import rl_curriculum.curriculum261_qaf_provenance_guard as guard
guard.R17_PIN_EXPECTED_ROOT = str(PIN)  # isolated-domain redirect (probe only)

RESULTS = []
def record(scenario, rd, expect_ok, marker=None):
    markers = ("vendor_static", "historical_digests", "branch_lineage")
    hit = [m for m in markers if any(m in p for p in rd.get("problems", []))]
    ok_flag = bool(rd.get("ok"))
    passed = (ok_flag == expect_ok) and (marker is None or hit == [marker])
    RESULTS.append({"scenario": scenario, "passed": passed, "ok": ok_flag,
                    "markers_hit": hit, "problems": rd.get("problems", [])[:4],
                    "vendor_ok": rd.get("vendor_ok"),
                    "hist_digests_match": rd.get("hist_digests_match"),
                    "heb_ok": rd.get("heb_ok"),
                    "heb_branch": rd.get("heb_branch")})
    print(("PASS " if passed else "FAIL ") + scenario,
          "ok=" + str(ok_flag), "markers=" + str(hit))

def preflight():
    return guard.runtime_dependency_preflight(
        repo=PIN, project_dir=PROJ, candidate_sha=A, python=PY)

def git(*a):
    return subprocess.run(["git", "-C", str(PIN), *a], capture_output=True, text=True)

def vgit(*a):
    return subprocess.run(["git", "-C", str(VEND), *a], capture_output=True, text=True)

# 0 baseline
record("00_baseline_legal", preflight(), True, None)

# FR01 vendor matrix
saved = DOM / "vendor_saved"
VEND.rename(saved)
record("01_vendor_missing", preflight(), False, "vendor_static")
saved.rename(VEND)
record("02_vendor_restored", preflight(), True, None)

rm = VEND / "README.md"
data = rm.read_bytes()
rm.write_bytes(data + b"\n# fr1-probe dirty\n")
record("03_vendor_dirty_correct_head", preflight(), False, "vendor_static")
rm.write_bytes(data)
record("04_vendor_restored2", preflight(), True, None)

(VEND / ".fr1_probe").write_text("x")
vgit("add", "-A")
vgit("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fr1 wrong head")
record("05_vendor_wrong_head_clean", preflight(), False, "vendor_static")
vgit("checkout", "-q", "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
record("06_vendor_restored3", preflight(), True, None)

# FR02 historical originals
h13 = PIN / "stage2_6_1/artifacts/repair13/r13_design_plan_digest.txt"
d13 = h13.read_bytes(); h13.unlink()
record("07_hist_digest_deleted", preflight(), False, "historical_digests")
h13.write_bytes(d13)
record("08_hist_restored", preflight(), True, None)

h5 = PIN / "stage2_6_1/artifacts/repair5/r5_design_plan_digest.txt"
d5 = h5.read_bytes(); h5.write_bytes(b"tampered-fr1-probe\n")
record("09_hist_digest_bytes_changed", preflight(), False, "historical_digests")
h5.write_bytes(d5)

h11 = PIN / "stage2_6_1/artifacts/repair11/r11_code_freeze.json"
d11 = h11.read_bytes(); h11.write_bytes(b'{"tampered":"fr1-probe"}\n')
record("10_hist_r11_blob_changed_head_unchanged", preflight(), False, "historical_digests")
h11.write_bytes(d11)
record("11_hist_all_restored", preflight(), True, None)

# FR03 branch/lineage
git("checkout", "-q", "--detach", A)
record("12_detached_same_commit", preflight(), False, "branch_lineage")
git("checkout", "-qB", BR, A)
record("13_branch_restored", preflight(), True, None)

git("checkout", "-qB", "route-c-stage2-6-1-repair18", A)
record("14_wrong_branch_name", preflight(), False, "branch_lineage")
git("checkout", "-qB", BR, A)
record("15_branch_restored2", preflight(), True, None)

# existing refusal not regressed: env file missing
envf = PROJ / "environment.yml"
edata = envf.read_bytes(); envf.unlink()
rd = preflight()
markers = [m for m in ("vendor_static","historical_digests","branch_lineage")
           if any(m in p for p in rd.get("problems", []))]
passed = (not rd.get("ok")) and markers == [] and any(
    ("environment.yml" in p) or ("缺失" in p) for p in rd.get("problems", []))
RESULTS.append({"scenario": "16_env_missing_existing_refusal", "passed": passed,
                "ok": bool(rd.get("ok")), "markers_hit": markers,
                "problems": rd.get("problems", [])[:4]})
print(("PASS " if passed else "FAIL ") + "16_env_missing_existing_refusal", rd.get("problems", [])[:3])
envf.write_bytes(edata)
record("17_final_baseline_green", preflight(), True, None)

# ---- entry subprocess scenarios ----
from rl_curriculum.curriculum261_qaf_provenance_guard import (
    install_to_target, read_pinned_source)
deploy = DOM / "deploy"
art = deploy / "artifacts" / "formal_a_qaf_v3"
art.mkdir(parents=True)
src = read_pinned_source(PIN)
install_to_target(art, src)
(deploy / "qprod_deploy_config.json").write_text(json.dumps({
    "format": "cur261-qprod-deploy-config-v1",
    "mode": "formal_ready",
    "formal_roots": {"qprod_a_formal_v3": {
        "artifact_root": str(art),
        "state_root": str(deploy / "state"),
        "authority_dir": str(deploy / "authority")}}}),
    encoding="utf-8")
tree = subprocess.run(["git", "-C", str(PIN), "rev-parse", A + "^{tree}"],
                      capture_output=True, text=True).stdout.strip()
approval = DOM / "approval.json"
approval.write_text("{}", encoding="utf-8")
entry = PROJ / "stage2_6_1_runner" / "qaf_v2_operator_entry.py"
env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
       "HOME": "/home/cryptorl", "PYTHONDONTWRITEBYTECODE": "1",
       "PYTHONPATH": str(PROJ / "src")}

def run_operator():
    return subprocess.run(
        [PY, str(entry), "execute", "--repo", str(PIN),
         "--deploy-root", str(deploy), "--project-dir", str(PROJ),
         "--approval-json", str(approval),
         "--regression-evidence", "unused",
         "--admission-id", "qaf-v3-fr1-review-probe",
         "--authorization", "test",
         "--plan-digest", tree, "--code-freeze-sha", A,
         "--attempt", "qaf_v3", "--model-update"],
        capture_output=True, text=True, env=env, cwd=str(PROJ), timeout=600)

saved2 = DOM / "vendor_saved_e1"
VEND.rename(saved2)
proc = run_operator()
saved2.rename(VEND)
p = proc
ok96 = (p.returncode == 96 and "vendor_static" in p.stdout
        and '"one_shot_writes": 0' in p.stdout
        and not (deploy / "authority").exists())
RESULTS.append({"scenario": "18_operator_entry_vendor_refusal", "passed": ok96,
                "rc": p.returncode, "markers_in_stdout": "vendor_static" in p.stdout,
                "one_shot_writes_zero": '"one_shot_writes": 0' in p.stdout,
                "authority_absent": not (deploy / "authority").exists()})
print(("PASS " if ok96 else "FAIL ") + "18_operator_entry_vendor_refusal rc=%d" % p.returncode)

# admission issue entry
prereg = DOM / "prereg.json"
prereg.write_text(json.dumps({
    "iteration": "qprod_a_formal_v3", "formal_attempt": "qaf_v3",
    "plan_digest": tree, "plan_digest_method": "git_tree_digest",
    "regression_evidence": "unused-fr1-review",
    "admission_id": "qaf-v3-fr1-review-probe",
    "authorization": "test"}), encoding="utf-8")
aentry = PROJ / "stage2_6_1_runner" / "r17_admission_issue.py"
saved3 = DOM / "vendor_saved_e2"
VEND.rename(saved3)
pa = subprocess.run(
    [PY, str(aentry), "--repo", str(PIN), "--deploy-root", str(deploy),
     "--state-root", str(deploy / "artifacts" / "route_c_stage2_6_1_repair17" / "state"),
     "--commit-a", A, "--preregistration", str(prereg),
     "--project-dir", str(PROJ)],
    capture_output=True, text=True, env=env, cwd=str(PROJ), timeout=600)
saved3.rename(VEND)
oka = (pa.returncode == 96 and "vendor_static" in pa.stdout
       and '"one_shot_writes": 0' in pa.stdout
       and not (deploy / "authority").exists())
RESULTS.append({"scenario": "19_admission_entry_vendor_refusal", "passed": oka,
                "rc": pa.returncode, "markers_in_stdout": "vendor_static" in pa.stdout,
                "one_shot_writes_zero": '"one_shot_writes": 0' in pa.stdout,
                "authority_absent": not (deploy / "authority").exists()})
print(("PASS " if oka else "FAIL ") + "19_admission_entry_vendor_refusal rc=%d" % pa.returncode)

# full-legal operator: gate passes -> refusal at post-gate approval boundary
pf = run_operator()
okp = (pf.returncode != 0
       and "vendor_static" not in pf.stdout
       and "historical_digests" not in pf.stdout
       and "branch_lineage" not in pf.stdout
       and "one_shot_writes" in pf.stdout
       and not (deploy / "authority").exists())
RESULTS.append({"scenario": "20_operator_full_legal_gate_pass_to_next_boundary",
                "passed": okp, "rc": pf.returncode,
                "stdout_tail": pf.stdout[-300:]})
print(("PASS " if okp else "FAIL ") + "20_operator_full_legal rc=%d" % pf.returncode)

n_fail = sum(1 for r in RESULTS if not r.get("passed"))
print("TOTAL %d scenarios, %d failed" % (len(RESULTS), n_fail))
(BASE / "results" / "fr1_probe_results.json").write_text(
    json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
sys.exit(1 if n_fail else 0)
