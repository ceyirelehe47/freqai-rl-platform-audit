# -*- coding: utf-8 -*-
"""RCF R2 probe: RCF-01 at the real CLI surfaces (operator prepare /
guard preissue) with file-link states."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TREE = Path("/home/cryptorl/projects/crypto_rl_qaf_v2")
sys.path.insert(0, str(TREE / "src"))
PY = sys.executable
REPO = Path("/mnt/f/trading/freqai-rl-audit")
BASE = Path("/mnt/f/trading/local/rcf_r2_review/p1_work")
RESULTS = []

def rec(name, ok, detail=""):
    RESULTS.append({"scenario": name, "ok": bool(ok), "detail": str(detail)[:600]})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {str(detail)[:500]}")

def fresh(tag):
    d = BASE / tag
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d

def write_cfg(deploy, art):
    deploy.mkdir(parents=True, exist_ok=True)
    state = deploy / "artifacts/route_c_stage2_6_1_repair17/state"
    cfg = {"format": "cur261-qprod-deploy-config-v1", "mode": "formal_ready",
           "formal_roots": {"qprod_a_formal_v2": {
               "artifact_root": str(art),
               "state_root": str(state),
               "authority_dir": str(deploy / "authority")}}}
    (deploy / "qprod_deploy_config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return cfg

RUNNER = TREE / "stage2_6_1_runner" / "qaf_v2_operator_entry.py"
GUARD = "rl_curriculum.curriculum261_qaf_provenance_guard"
env = dict(os.environ, PYTHONPATH=str(TREE / "src"))

# c1: prepare CLI on dir with two dangling file links -> refuse, no domain write
d = fresh("c1")
prot = d / "prot"; prot.mkdir()
art = d / "art"; art.mkdir()  # will be recreated as link dir? no: art dir with links
(art / "gate_topology_reconciliation.json").symlink_to(prot / "never.json")
(art / "gate_topology_provenance.digest").symlink_to(prot / "never.txt")
dep = d / "deploy"; write_cfg(dep, art)
p = subprocess.run([PY, str(RUNNER), "prepare", "--repo", str(REPO),
                    "--deploy-root", str(dep),
                    "--project-dir", str(TREE), "--attempt", "qaf_v2"],
                   capture_output=True, text=True, cwd=str(TREE), env=env)
ok = (p.returncode != 0 and "符号链接" in (p.stdout + p.stderr)
      and not (prot / "never.json").exists() and not (prot / "never.txt").exists())
rec("c1_prepare_cli_dangling_links", ok,
    f"rc={p.returncode} out={(p.stdout + p.stderr)[:200]!r}")

# c2: prepare CLI legit new dir -> rc0 + files installed
d = fresh("c2")
art = d / "fresh_art"
dep = d / "deploy"; write_cfg(dep, art)
p = subprocess.run([PY, str(RUNNER), "prepare", "--repo", str(REPO),
                    "--deploy-root", str(dep),
                    "--project-dir", str(TREE), "--attempt", "qaf_v2"],
                   capture_output=True, text=True, cwd=str(TREE), env=env)
ok = (p.returncode == 0
      and (art / "gate_topology_reconciliation.json").is_file()
      and not (art / "gate_topology_reconciliation.json").is_symlink())
rec("c2_prepare_cli_positive", ok, f"rc={p.returncode} tail={p.stdout[-160:]!r}")

# c3: preissue CLI --report-out symlink -> rc3, historical original intact
d = fresh("c3")
hist = d / "hist.json"; hist.write_text('{"keep":true}', encoding="utf-8")
rpt = d / "report.json"; rpt.symlink_to(hist)
dep = d / "deploy"; write_cfg(dep, d / "art")
p = subprocess.run([PY, "-m", GUARD, "preissue", "--repo", str(REPO),
                    "--deploy-root", str(dep), "--project-dir", str(TREE),
                    "--attempt", "qaf_v2", "--report-out", str(rpt)],
                   capture_output=True, text=True, cwd=str(TREE), env=env)
hist_text = hist.read_text(encoding="utf-8")
ok = (p.returncode == 3 and hist_text == '{"keep":true}'
      and rpt.is_symlink())
rec("c3_preissue_cli_report_link_refused", ok,
    "rc=%s out=%r hist-intact=%s" % (p.returncode,
                                     p.stdout.strip()[:200],
                                     hist_text == '{"keep":true}'))

print("\n==== SUMMARY ====")
bad = [r for r in RESULTS if not r["ok"]]
print(f"{len(RESULTS) - len(bad)}/{len(RESULTS)} scenario assertions passed")
(WORK := BASE.parent) and (BASE.parent / "p1b_results.json").write_text(
    json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
sys.exit(1 if bad else 0)
