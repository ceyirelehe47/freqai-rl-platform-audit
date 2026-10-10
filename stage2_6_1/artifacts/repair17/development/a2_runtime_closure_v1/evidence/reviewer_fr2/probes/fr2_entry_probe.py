# -*- coding: utf-8 -*-
"""FR2-02 entry-level probe: inject historical mutation into the REAL
direct qprod_formal_authority issue-permit path (isolated domain)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path("/home/cryptorl/tmp_fr2_review/fr2_dom")
OUT = Path("/mnt/f/trading/local/fr2_review/fr2_entry_probe_results.json")
CHILD = "/mnt/f/trading/local/fr2_review/fr2_entry_child.py"
R13 = "stage2_6_1/artifacts/repair13"

pin = BASE / "release_pin"
project = BASE / "project"
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(pin),
                      capture_output=True, text=True).stdout.strip()
tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=str(pin),
                      capture_output=True, text=True).stdout.strip()

edep = BASE / "entry_deploy"
if edep.exists():
    shutil.rmtree(edep)
deploy = edep / "deploy"
art = deploy / "artifacts" / "formal_a_qaf_v3"
art.mkdir(parents=True)
adir = edep / "authority"

sys.path.insert(0, str(project / "src"))
sys.path.insert(0, str(project / "tests" / "route_c_stage2_6_1"))
from rl_curriculum.curriculum261_qaf_provenance_guard import (  # noqa
    install_to_target, read_pinned_source)
from test_curriculum261_qaf_v2_preissue_guard import _guard_repo  # noqa
src = read_pinned_source(_guard_repo())
install_to_target(art, src)
(deploy / "qprod_deploy_config.json").write_text(json.dumps({
    "format": "cur261-qprod-deploy-config-v1",
    "mode": "formal_ready",
    "formal_roots": {"qprod_a_formal_v3": {
        "artifact_root": str(art),
        "state_root": str(deploy / "state"),
        "authority_dir": str(adir)}}}, ensure_ascii=False, indent=1),
    encoding="utf-8")

ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
       "HOME": "/home/cryptorl",
       "PYTHONDONTWRITEBYTECODE": "1",
       "PYTHONPATH": str(project / "src")}


def child():
    p = subprocess.run(
        [sys.executable, CHILD, str(pin), str(project), str(deploy),
         str(adir), head, tree],
        capture_output=True, text=True, env=ENV,
        cwd=str(project), timeout=600)
    rc = None
    for line in p.stdout.splitlines():
        if line.startswith("CHILD_RC="):
            rc = line.split("=", 1)[1]
    return rc, p.stdout, p.stderr


def init_authority():
    p = subprocess.run(
        [sys.executable, str(project / "stage2_6_1_runner"
         / "qprod_formal_authority.py"), "init", "--dir", str(adir)],
        capture_output=True, text=True, env=ENV, cwd=str(project),
        timeout=300)
    assert p.returncode == 0, p.stderr[-400:]


def no_permits():
    return list(adir.rglob("permit_*")) == []


results = {"cases": []}

init_authority()
rc, out, err = child()
c1 = {"name": "legal_passes_gate_to_approval_boundary",
      "rc": rc,
      "approval_boundary": ("用户批准原件缺失" in out
                            or "approval" in out.lower()),
      "no_guard_markers": not any(m in out for m in (
          "historical_bindings", "vendor_static", "branch_lineage",
          "historical_digests")),
      "no_permits": no_permits()}
c1["pass"] = (c1["approval_boundary"] and c1["no_guard_markers"]
              and c1["no_permits"] and rc == "96")
results["cases"].append(c1)

marker_path = pin / R13 / "r13_iteration_aborted.json"
saved = marker_path.read_bytes()
marker_path.unlink()
try:
    rc, out, err = child()
    c2 = {"name": "r13_abort_missing_direct_entry_refusal",
          "rc": rc,
          "historical_bindings": "historical_bindings" in out,
          "guard_refusal": "签发前守卫拒绝" in out,
          "zero_writes": '"one_shot_writes": 0' in out,
          "no_permits": no_permits(),
          "stderr_tail": err[-200:]}
    c2["pass"] = (c2["historical_bindings"] and c2["guard_refusal"]
                  and c2["zero_writes"] and c2["no_permits"]
                  and rc == "96")
    results["cases"].append(c2)
finally:
    marker_path.write_bytes(saved)

vend = project / "vendor" / "freqtrade"
vsaved = BASE / "vendor_saved_entry"
vend.rename(vsaved)
try:
    rc, out, err = child()
    c3 = {"name": "vendor_missing_same_gate_refusal",
          "rc": rc,
          "vendor_static": "vendor_static" in out,
          "zero_writes": '"one_shot_writes": 0' in out,
          "no_permits": no_permits()}
    c3["pass"] = (c3["vendor_static"] and c3["zero_writes"]
                  and c3["no_permits"] and rc == "96")
    results["cases"].append(c3)
finally:
    vsaved.rename(vend)

ok = all(c["pass"] for c in results["cases"])
results["verdict"] = "ALL_PASS" if ok else "HAS_FAILURE"
OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1),
               encoding="utf-8")
for c in results["cases"]:
    print(("PASS " if c["pass"] else "FAIL ") + c["name"] + " rc=" + str(c["rc"]))
    if not c["pass"]:
        print(json.dumps(c, ensure_ascii=False)[:1000])
print("VERDICT " + results["verdict"])
