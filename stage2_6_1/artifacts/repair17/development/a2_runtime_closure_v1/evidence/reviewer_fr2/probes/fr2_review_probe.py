# -*- coding: utf-8 -*-
"""FR2 independent acceptance probes (own isolated domain)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

REAL_PIN = Path("/home/cryptorl/release_pin_qaf_v3")
REAL_P3 = Path("/home/cryptorl/projects/crypto_rl_qaf_v3")
OLD_P = Path("/home/cryptorl/projects/crypto_rl")
CAND = "c0fb685823eb4733bda9f5920601311228d55fde"
BRANCH = "route-c-stage2-6-1-repair17"
BASE = Path("/home/cryptorl/tmp_fr2_review/fr2_dom")
OUT = Path("/mnt/f/trading/local/fr2_review/fr2_probe_results.json")

R11 = "stage2_6_1/artifacts/repair11"
R12 = "stage2_6_1/artifacts/repair12"
R13 = "stage2_6_1/artifacts/repair13"

results = {"real_roots": None, "domain": None, "scenarios": [],
           "verdict": None}


def run(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError("rc=%s\n%s\n%s" % (p.returncode, p.stdout,
                                              p.stderr))
    return p


sys.path.insert(0, str(REAL_P3 / "src"))
sys.path.insert(0, str(REAL_P3 / "tests" / "route_c_stage2_6_1"))
import rl_curriculum.curriculum261_qaf_provenance_guard as guard  # noqa
import test_curriculum261_qaf_v3_finite_repair_r1 as R1  # noqa

results["real_roots"] = guard.runtime_dependency_preflight(
    repo=REAL_PIN, project_dir=REAL_P3, candidate_sha=CAND)

if BASE.exists():
    shutil.rmtree(BASE)
BASE.mkdir(parents=True)
pin = BASE / "release_pin"
run(["git", "clone", "-q", "--shared", "--no-checkout",
     str(REAL_PIN), str(pin)])
head = run(["git", "rev-parse", "HEAD"], cwd=REAL_PIN).stdout.strip()
run(["git", "sparse-checkout", "init", "--no-cone"], cwd=pin)
run(["git", "sparse-checkout", "set", *R1._sparse_patterns()], cwd=pin)
run(["git", "checkout", "-qB", BRANCH, head], cwd=pin)

project = BASE / "project"
project.mkdir()


def proj_copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes().replace(b"\r", b""))


def copy_tree(sd, dd):
    for f in sd.rglob("*"):
        if not f.is_file() or f.is_symlink():
            continue
        if any(p in ("__pycache__", ".pytest_cache")
               for p in f.relative_to(sd).parts):
            continue
        proj_copy(f, dd / f.relative_to(sd))


copy_tree(pin / "stage2_6_1" / "src", project / "src")
copy_tree(pin / "stage2_6_1" / "runner", project / "stage2_6_1_runner")
copy_tree(pin / "stage2_6_1" / "tests" / "route_c_stage2_6_1",
          project / "tests" / "route_c_stage2_6_1")
proj_copy(pin / "stage2_6_1" / "report" / "r20_design_calc_v4.py",
          project / "report" / "r20_design_calc_v4.py")
proj_copy(pin / "stage2_6_1" / "report" / "r20_design_calc_v4.json",
          project / "report" / "r20_design_calc_v4.json")
proj_copy(pin / "stage2_6_1" / "artifacts" / "repair10"
          / "r10_design_plan.json",
          project / "artifacts" / "route_c_stage2_6_1_repair10"
          / "r10_design_plan.json")
for rel in R1._ORIGINALS:
    dst = project / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(OLD_P / rel, dst)
from rl_curriculum.curriculum261_qaf_provenance_guard import (  # noqa
    RUNTIME_TREE_ALLOWED_EXTRAS)
for rel in RUNTIME_TREE_ALLOWED_EXTRAS:
    origin = REAL_P3 / rel
    if origin.is_file():
        dst = project / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(origin, dst)
for top in REAL_P3.joinpath("src").iterdir():
    if top.name == "rl_curriculum" or top.name.startswith("."):
        continue
    if top.is_dir():
        copy_tree(top, project / "src" / top.name)
    elif top.is_file():
        proj_copy(top, project / "src" / top.name)

from rl_curriculum.curriculum261_r17_cli import VENDOR_PIN  # noqa
vend = project / "vendor" / "freqtrade"
run(["git", "clone", "-q", "--shared", "--no-checkout",
     str(REAL_P3 / "vendor" / "freqtrade"), str(vend)])
run(["git", "checkout", "-q", VENDOR_PIN], cwd=vend)
results["domain"] = {"base": str(BASE), "pin": str(pin),
                     "project": str(project), "head": head,
                     "vendor_pin": VENDOR_PIN}


def preflight():
    saved = guard.R17_PIN_EXPECTED_ROOT
    guard.R17_PIN_EXPECTED_ROOT = str(pin)
    try:
        return guard.runtime_dependency_preflight(
            repo=pin, project_dir=project, candidate_sha=head)
    finally:
        guard.R17_PIN_EXPECTED_ROOT = saved


MARKERS = ("vendor_static", "historical_digests", "branch_lineage")


def record(name, rd, expect=None, allow_branch_lineage=False):
    entry = {"name": name, "ok": rd.get("ok"),
             "bind_states": rd.get("bind_states"),
             "head": rd.get("repo_head_commit"),
             "problems": rd.get("problems") or rd.get("reason")}
    checks = {}
    if expect is None:
        checks["ok_true"] = bool(rd.get("ok"))
        bs = rd.get("bind_states") or {}
        checks["bind_all_true"] = bool(bs) and all(
            v is True for v in bs.values())
    else:
        probs = " | ".join(str(x) for x in (rd.get("problems") or []))
        bs = rd.get("bind_states") or {}
        checks["ok_false"] = rd.get("ok") is False
        checks["target_bind_false"] = bs.get(expect) is False
        checks["others_bind_true"] = all(
            v is True for k, v in bs.items() if k != expect)
        checks["historical_bindings_marker"] = \
            "historical_bindings" in probs
        for m in MARKERS:
            hit = m in probs
            if m == "branch_lineage" and allow_branch_lineage:
                checks["only_" + m] = hit
            else:
                checks["no_" + m] = not hit
        checks["head_is_A"] = rd.get("repo_head_commit") == head
    entry["checks"] = checks
    entry["all_pass"] = all(checks.values())
    results["scenarios"].append(entry)
    print(("PASS " if entry["all_pass"] else "FAIL ") + name)
    if not entry["all_pass"]:
        print(json.dumps(entry, ensure_ascii=False,
                         default=str)[:1200])


def mutate(rel, delete=False, append=None, write=None):
    f = pin / rel
    data = f.read_bytes()
    if delete:
        f.unlink()
    elif append is not None:
        f.write_bytes(data + append)
    elif write is not None:
        f.write_bytes(write)
    return data, f


def restore(f, data):
    f.write_bytes(data)


record("baseline_positive", preflight(), expect=None)

data, f = mutate(R11 + "/cue_event_trace.jsonl", delete=True)
try:
    record("r11_trace_missing", preflight(), expect="r11")
finally:
    restore(f, data)

data, f = mutate(R11 + "/r11_iteration_aborted.json", append=b"\n")
try:
    record("r11_marker_bytes", preflight(), expect="r11")
finally:
    restore(f, data)

finalf = pin / R11 / "qualification_result.json"
finalf.write_text('{"verdict": "PASS"}\n', encoding="utf-8")
try:
    record("r11_final_appears", preflight(), expect="r11")
finally:
    finalf.unlink()

data, f = mutate(R11 + "/cue_contract_audit.json", append=b" ")
try:
    record("r11_audit_changed", preflight(), expect="r11")
finally:
    restore(f, data)

data, f = mutate(R13 + "/r13_iteration_aborted.json", delete=True)
try:
    record("r13_abort_missing", preflight(), expect="r13")
finally:
    restore(f, data)

p13 = pin / R13 / "qualification_result.json"
data = p13.read_bytes()
obj = json.loads(p13.read_text(encoding="utf-8"))
obj["fr2_independent_tamper"] = True
p13.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n",
               encoding="utf-8")
try:
    record("r13_result_blob_changed", preflight(), expect="r13")
finally:
    p13.write_bytes(data)

data, f = mutate(R13 + "/qualification_exposure_r13.json", delete=True)
try:
    record("r13_exposure_missing", preflight(), expect="r13")
finally:
    restore(f, data)

data, f = mutate(R13 + "/qualification_plan_digest_r13.txt",
                 write=b"fr2probe-tampered\n")
try:
    record("r13_plan_digest_changed", preflight(), expect="r13")
finally:
    restore(f, data)

data, f = mutate(R12 + "/r12_iteration_aborted.json", append=b"\n")
try:
    record("r12_marker_bytes", preflight(), expect="r12",
           allow_branch_lineage=True)
finally:
    restore(f, data)

expf = pin / R12 / "qualification_exposure_r12.json"
expf.write_text('{"status": "exposed"}\n', encoding="utf-8")
try:
    record("r12_exposure_appears", preflight(), expect="r12")
finally:
    expf.unlink()

data, f = mutate(R13 + "/r13_iteration_aborted.json", delete=True)
preflight()
restore(f, data)
record("restore_positive", preflight(), expect=None)

ok = all(s["all_pass"] for s in results["scenarios"])
rr = results["real_roots"] or {}
ok = ok and bool(rr.get("ok")) and (rr.get("bind_states")
                                    or {}).get("r13") is True
results["verdict"] = "ALL_PASS" if ok else "HAS_FAILURE"
OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1,
                          default=str), encoding="utf-8")
print("VERDICT " + results["verdict"])
