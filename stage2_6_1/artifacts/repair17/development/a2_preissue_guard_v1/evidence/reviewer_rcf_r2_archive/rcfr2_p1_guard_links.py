# -*- coding: utf-8 -*-
"""RCF R2 independent probe: RCF-01 final-file link boundary + report writes.

Runs candidate guard (work tree) and parent guard (extracted 97f81a6d) side by
side. All work in /mnt/f/trading/local/rcf_r2_review/p1_* isolated dirs.
"""
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

TREE = Path("/home/cryptorl/projects/crypto_rl_qaf_v2")
sys.path.insert(0, str(TREE / "src"))
REPO = Path("/mnt/f/trading/freqai-rl-audit")
BASE = Path("/mnt/f/trading/local/rcf_r2_review")
P1 = BASE / "p1_work"
RESULTS = []

def rec(name, ok, detail):
    RESULTS.append({"scenario": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

# candidate guard
import rl_curriculum.curriculum261_qaf_provenance_guard as cand
# parent guard (different module name)
spec = importlib.util.spec_from_file_location(
    "parent_guard", str(BASE / "parent_guard_97f81a6d.py"))
par = importlib.util.module_from_spec(spec)
sys.modules["parent_guard"] = par
spec.loader.exec_module(par)

def fresh(tag):
    d = P1 / tag
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d

def listing(root):
    return sorted(p.name for p in root.iterdir()) if root.exists() else None

src = cand.read_pinned_source(REPO)
JSON_NAME = cand.PROVENANCE_JSON_TARGET_NAME
DIG_NAME = cand.PROVENANCE_DIGEST_TARGET_NAME
json_bytes = src["json_bytes"]
digest_bytes = src["digest_bytes"]

# ---------------- A1: dangling file symlinks -> protected domain ----------
d = fresh("a1")
prot = d / "prot"; prot.mkdir()
art = d / "art"; art.mkdir()
(art / JSON_NAME).symlink_to(prot / "never_json.json")
(art / DIG_NAME).symlink_to(prot / "never_digest.txt")
prot_before = listing(prot)
try:
    cand.install_to_target(art, src)
    rec("a1_dangling_links_refused", False, "install returned; expected refusal")
except cand.ProvenanceGuardError as exc:
    ok = (listing(prot) == prot_before
          and not (prot / "never_json.json").exists()
          and not (prot / "never_digest.txt").exists()
          and listing(art) == sorted([JSON_NAME, DIG_NAME]))
    rec("a1_dangling_links_refused", ok,
        f"refused({exc}); prot={listing(prot)} art={listing(art)}")

# ---------------- A2: jp -> existing wrong-bytes file ----------------------
d = fresh("a2")
prot = d / "prot"; prot.mkdir()
wrong = prot / "wrong.json"; wrong.write_bytes(b"WRONG-CONTENT-ORIGINAL")
art = d / "art"; art.mkdir()
(art / JSON_NAME).symlink_to(wrong)
before = wrong.read_bytes()
try:
    cand.install_to_target(art, src)
    rec("a2_link_to_wrong_bytes_refused", False, "returned; expected refusal")
except cand.ProvenanceGuardError as exc:
    ok = wrong.read_bytes() == before and listing(art) == sorted([JSON_NAME])
    rec("a2_link_to_wrong_bytes_refused", ok,
        f"refused({exc}); wrong-file-intact={wrong.read_bytes()==before}")

# ---------------- A3: jp -> existing CORRECT file, dp missing --------------
d = fresh("a3")
prot = d / "prot"; prot.mkdir()
goodjson = prot / "orig.json"; goodjson.write_bytes(json_bytes)
art = d / "art"; art.mkdir()
(art / JSON_NAME).symlink_to(goodjson)
try:
    out = cand.install_to_target(art, src)
    rec("a3_link_correct_halfpair", False, f"returned {out}; expected refusal")
except cand.ProvenanceGuardError as exc:
    ok = goodjson.read_bytes() == json_bytes and listing(art) == sorted([JSON_NAME])
    rec("a3_link_correct_halfpair", ok, f"refused({exc})")

# ---------------- A3b: both links -> existing CORRECT files ----------------
d = fresh("a3b")
prot = d / "prot"; prot.mkdir()
goodjson = prot / "orig.json"; goodjson.write_bytes(json_bytes)
gooddig = prot / "orig.digest"; gooddig.write_bytes(digest_bytes)
art = d / "art"; art.mkdir()
(art / JSON_NAME).symlink_to(goodjson)
(art / DIG_NAME).symlink_to(gooddig)
try:
    out = cand.install_to_target(art, src)
    ok = (goodjson.read_bytes() == json_bytes
          and gooddig.read_bytes() == digest_bytes
          and listing(art) == sorted([JSON_NAME, DIG_NAME]))
    rec("a3b_both_links_correct_bytes", ok,
        f"behavior={out.get('installed')}/{out.get('idempotent_ok')} "
        f"prot-untouched={ok} (observation: accepted idempotent, "
        f"zero writes through links)")
except cand.ProvenanceGuardError as exc:
    rec("a3b_both_links_correct_bytes", True,
        f"refused({exc}); zero writes through links")

# ---------------- A4: legit dir install + idempotent -----------------------
d = fresh("a4")
art = d / "fresh_art"
out1 = cand.install_to_target(art, src)
f1 = (art / JSON_NAME).read_bytes(); d1 = (art / DIG_NAME).read_bytes()
mt1 = (art / JSON_NAME).stat().st_mtime_ns
out2 = cand.install_to_target(art, src)
mt2 = (art / JSON_NAME).stat().st_mtime_ns
rec("a4_legit_install_idempotent",
    out1["installed"] and out1["actions"] == ["wrote:json", "wrote:digest"]
    and out2["installed"] is False and out2["idempotent_ok"] is True
    and f1 == json_bytes and d1 == digest_bytes and mt1 == mt2,
    f"first={out1['actions']} second=idempotent mt-equal={mt1==mt2}")

# ---------------- helpers: deploy config + preissue -----------------------
def write_cfg(deploy):
    deploy.mkdir(parents=True, exist_ok=True)
    state = deploy / "artifacts/route_c_stage2_6_1_repair17/state"
    cfg = {"format": "cur261-qprod-deploy-config-v1", "mode": "formal_ready",
           "formal_roots": {"qprod_a_formal_v2": {
               "artifact_root": str(deploy / "artifacts/formal_a_qaf_v2"),
               "state_root": str(state),
               "authority_dir": str(deploy / "authority")}}}
    (deploy / "qprod_deploy_config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return cfg

def preissue(mod, report_out=None, deploy=None, rogue_env=None):
    if rogue_env:
        os.environ["CURRICULUM261_R17_STATE_ROOT"] = str(rogue_env)
    try:
        return mod.preissue_gate(repo=REPO, deploy_root=deploy,
                                 project_dir=Path("/tmp"), attempt="qaf_v2",
                                 report_out=report_out)
    finally:
        os.environ.pop("CURRICULUM261_R17_STATE_ROOT", None)

# ---------------- A5: report path = symlink -> historical original --------
d = fresh("a5")
hist = d / "historical_original.json"
hist.write_text('{"irreplaceable": true}', encoding="utf-8")
rpt = d / "diag_report.json"
rpt.symlink_to(hist)
try:
    preissue(cand, report_out=rpt, deploy=d / "nodeploy")
    rec("a5_report_link_candidate_refused", False, "returned; expected raise")
except cand.ProvenanceGuardError as exc:
    ok = (hist.read_text(encoding="utf-8") == '{"irreplaceable": true}'
          and rpt.is_symlink())
    rec("a5_report_link_candidate_refused", ok,
        f"refused({str(exc)[:60]}...); hist-intact={ok}")

# parent control: same shape, separate files
hist2 = d / "historical_original_parent.json"
hist2.write_text('{"irreplaceable": true}', encoding="utf-8")
rpt2 = d / "diag_report_parent.json"
rpt2.symlink_to(hist2)
try:
    rep_par = preissue(par, report_out=rpt2, deploy=d / "nodeploy")
    clobbered = hist2.read_text(encoding="utf-8") != '{"irreplaceable": true}'
    rec("a5_report_link_parent_clobbers", clobbered,
        f"parent returned report (ok={rep_par.get('ok')}); "
        f"historical original overwritten via link={clobbered}")
except Exception as exc:
    rec("a5_report_link_parent_clobbers", False, f"parent raised {exc}")

# ---------------- A5b: report path = dangling symlink ---------------------
d = fresh("a5b")
never = d / "never_report.json"
rpt = d / "diag_report.json"
rpt.symlink_to(never)
try:
    preissue(cand, report_out=rpt, deploy=d / "nodeploy")
    rec("a5b_dangling_report_link_candidate", False, "returned; expected raise")
except cand.ProvenanceGuardError as exc:
    ok = (not never.exists()) and rpt.is_symlink()
    rec("a5b_dangling_report_link_candidate", ok,
        f"refused({str(exc)[:50]}...); target-not-created={not never.exists()}")

# parent control for dangling link
never2 = d / "never_report_parent.json"
rpt2 = d / "diag_report_parent.json"
rpt2.symlink_to(never2)
try:
    preissue(par, report_out=rpt2, deploy=d / "nodeploy")
    created = never2.exists()
    rec("a5b_dangling_report_link_parent_writes_through", created,
        f"parent wrote through dangling link; target created={created}")
except Exception as exc:
    rec("a5b_dangling_report_link_parent_writes_through", False, f"parent raised {exc}")

# ---------------- A5c: normal regular report file (positive) --------------
d = fresh("a5c")
dep = d / "deploy"; write_cfg(dep)
rpt = d / "diag.json"; rpt.write_text("{}", encoding="utf-8")
rep = preissue(cand, report_out=rpt, deploy=dep)
doc = json.loads(rpt.read_text(encoding="utf-8"))
rec("a5c_normal_report_positive", doc.get("refusal") == rep.get("refusal"),
    f"refusal={doc.get('refusal')}")

# ---------------- A6: report overwrite long -> short same path ------------
# F1 fix (d705c494) expectation: exact truncating overwrite (parent parity)
d = fresh("a6")
depc = d / "deploy"; write_cfg(depc)
rpt = d / "diag.json"
rep_long = preissue(cand, report_out=rpt, deploy=depc)          # target fail
rep_short = preissue(cand, report_out=rpt, deploy=depc,
                     rogue_env=d / "rogue")                     # env fail
wl = json.dumps(rep_long, ensure_ascii=False, indent=1).encode()
ws = json.dumps(rep_short, ensure_ascii=False, indent=1).encode()
raw = rpt.read_bytes()
try:
    parsed = json.loads(raw.decode("utf-8"))
    parse_ok = True
except ValueError:
    parsed = None
    parse_ok = False
fixed = (len(ws) < len(wl)
         and raw == ws
         and parse_ok
         and parsed == rep_short)
rec("a6_overwrite_short_report_exact_truncated", fixed,
    f"long={len(wl)}B short={len(ws)}B file={len(raw)}B exact={raw == ws} "
    f"parses={parse_ok}")

# parent control: long then short (write_text truncates)
d = fresh("a6p")
depp = d / "deploy"; write_cfg(depp)
rpt = d / "diag_parent.json"
rp_long = preissue(par, report_out=rpt, deploy=depp)
rp_short = preissue(par, report_out=rpt, deploy=depp, rogue_env=d / "rogue")
wp = json.dumps(rp_short, ensure_ascii=False, indent=1).encode()
rawp = rpt.read_bytes()
parent_clean = rawp == wp
try:
    json.loads(rawp.decode("utf-8")); pp = True
except ValueError:
    pp = False
rec("a6_parent_overwrite_clean_control", parent_clean and pp,
    f"parent file={len(rawp)}B exact-short={parent_clean} parses={pp}")

# ---------------- A7: allow_replace_broken mixed dir + link target --------
d = fresh("a7")
art = d / "mixed"
cand.install_to_target(art, src)
(art / "historical_evidence.json").write_text('{"keep": true}', encoding="utf-8")
(art / JSON_NAME).write_text("{}")
try:
    cand.install_to_target(art, src, allow_replace_broken=True)
    rec("a7_mixed_dir_refused", False, "returned; expected refusal")
except cand.ProvenanceGuardError as exc:
    ok = (json.loads((art / "historical_evidence.json").read_text())
          == {"keep": True})
    rec("a7_mixed_dir_refused", ok and "两件之外" in str(exc), f"refused({exc})")

d = fresh("a7b")
prot = d / "prot"; prot.mkdir()
wrong = prot / "wrong_target.json"; wrong.write_bytes(b"WRONG-PROTECTED")
art = d / "art"; art.mkdir()
(art / JSON_NAME).symlink_to(wrong)
out = cand.install_to_target(art, src, allow_replace_broken=True)
ok = (wrong.read_bytes() == b"WRONG-PROTECTED"
      and not (art / JSON_NAME).is_symlink()
      and (art / JSON_NAME).read_bytes() == json_bytes
      and (art / DIG_NAME).read_bytes() == digest_bytes)
rec("a7b_allow_replace_link_target_untouched", ok,
    f"actions={out['actions']} prot-intact={wrong.read_bytes() == b'WRONG-PROTECTED'} "
    f"art-files-fresh={not (art / JSON_NAME).is_symlink()}")

print("\n==== SUMMARY ====")
bad = [r for r in RESULTS if not r["ok"]]
print(f"{len(RESULTS) - len(bad)}/{len(RESULTS)} scenario assertions passed")
for r in bad:
    print("FAILED:", json.dumps(r, ensure_ascii=False))
(BASE / "p1_results.json").write_text(
    json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
sys.exit(1 if bad else 0)
