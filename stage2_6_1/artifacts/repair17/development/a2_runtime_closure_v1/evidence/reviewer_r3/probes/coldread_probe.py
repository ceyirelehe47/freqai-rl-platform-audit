# -*- coding: utf-8 -*-
# Final cold-read of the RETURN package (read-only; output to reviewer dirs)
import hashlib, json, re, subprocess, sys, zipfile
from pathlib import Path

ZIPP = "/mnt/f/trading/trading/outgoing/RouteC_A2_RuntimeClosure_NewAttempt_v1_RETURN_TO_CHATGPT.zip"
REPO = "/mnt/f/trading/freqai-rl-audit"
HEAD = "383debf27895af414ea50d2c571659b82e063714"
LOCAL = Path("/mnt/f/trading/local/rcw_r3_review")
OUT = Path("/home/cryptorl/tmp_rcw_r3")
OUT.mkdir(parents=True, exist_ok=True)
R = {"pass": 0, "fail": 0}

def check(name, ok, detail=""):
    R["pass" if ok else "fail"] += 1
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail else ""))

def info(name, detail):
    print("INFO " + name + " :: " + str(detail)[:400])

def gitblob(path):
    p = subprocess.run(["git", "-C", REPO, "show", HEAD + ":" + path], capture_output=True)
    return p.stdout

h = hashlib.sha256(Path(ZIPP).read_bytes()).hexdigest()
check("C1.zip_sha256", h == "d2dc59f358d9d60793b5404b820806cb89205139a1beb310f13bec8cf19c45e6", h)
side = Path(ZIPP + ".sha256.txt").read_text().strip()
check("C1.sidecar_matches", h in side, side[:120])

z = zipfile.ZipFile(ZIPP)
names = z.namelist()
check("C2.testzip_crc", z.testzip() is None, "all CRC ok")
dups = [n for n in set(names) if names.count(n) > 1]
check("C2.no_dup_names", not dups, dups)
bad = [n for n in names if n.startswith("/") or ".." in n.split("/") or ":" in n.split("/")[0] and len(n.split("/")[0]) <= 3]
check("C2.no_traversal", not bad, bad)
syms = [i.filename for i in z.infolist() if (i.external_attr >> 16) & 0o170000 == 0o120000]
check("C2.no_symlinks", not syms, syms)
toplevel = sorted(set(n.split("/")[0] for n in names))
check("C2.top_level", toplevel == ["RouteC_A2_RuntimeClosure_NewAttempt_v1_RETURN", "SHA256SUMS.txt"], toplevel)
files = [i for i in z.infolist() if not i.is_dir()]
info("C2.counts", "entries=%d files=%d dirs=%d" % (len(names), len(files), len(names) - len(files)))

sums = {}
for ln in z.read("SHA256SUMS.txt").decode("utf-8", errors="replace").splitlines():
    ln = ln.strip()
    if not ln or ln.startswith("#"):
        continue
    a, _, b = ln.partition("  ")
    key = b.strip().lstrip("*")
    sums[key[2:] if key.startswith("./") else key] = a.strip()
zfiles = {i.filename for i in files} - {"SHA256SUMS.txt"}
check("C3.sums_coverage_exact", set(sums) == zfiles and len(sums) == 94, "manifest=%d zipfiles=%d missing=%s extra=%s" % (len(sums), len(zfiles), sorted(zfiles - set(sums))[:4], sorted(set(sums) - zfiles)[:4]))
badh = []
for name, want in sorted(sums.items()):
    got = hashlib.sha256(z.read(name)).hexdigest()
    if got != want:
        badh.append(name)
check("C3.sums_all_recomputed", not badh, badh[:5])

TOP = "RouteC_A2_RuntimeClosure_NewAttempt_v1_RETURN/"
BASE = "stage2_6_1/artifacts/repair17/development/a2_runtime_closure_v1/"
KEY = [
    ("CLOSURE_REPORT_RC.md", BASE + "CLOSURE_REPORT_RC.md"),
    ("PENDING_APPROVAL_SUMMARY.md", BASE + "PENDING_APPROVAL_SUMMARY.md"),
    ("COMMANDS_APPENDIX.md", BASE + "COMMANDS_APPENDIX.md"),
    ("DECISION_SUMMARY.md", BASE + "DECISION_SUMMARY.md"),
    ("evidence/regress261_d3/regression_evidence_v3_record.json", BASE + "evidence/regress261_d3/regression_evidence_v3_record.json"),
    ("evidence/regress261_d3/summary.json", BASE + "evidence/regress261_d3/summary.json"),
    ("plans/A2_qaf_v3/qprod_formal_level_a_draft_plan.json", BASE + "plans/A2_qaf_v3/qprod_formal_level_a_draft_plan.json"),
    ("evidence/runtime_verify/substance_verify_D3.json", BASE + "evidence/runtime_verify/substance_verify_D3.json"),
    ("evidence/runtime_verify/freeze_engineering_P3.json", BASE + "evidence/runtime_verify/freeze_engineering_P3.json"),
    ("evidence/runtime_verify/prefix_probe_0f494d27/step1_provenance.log", BASE + "evidence/runtime_verify/prefix_probe_0f494d27/step1_provenance.log"),
    ("evidence/runtime_verify/prefix_probe_0f494d27/step2_determinism.log", BASE + "evidence/runtime_verify/prefix_probe_0f494d27/step2_determinism.log"),
    ("evidence/runtime_verify/prefix_probe_0f494d27/step3_audit.log", BASE + "evidence/runtime_verify/prefix_probe_0f494d27/step3_audit.log"),
    ("evidence/three_way_compare.json", BASE + "evidence/three_way_compare.json"),
    ("evidence/reviewer_r3/REVIEW_REPORT_v1.md", BASE + "evidence/reviewer_r3/REVIEW_REPORT_v1.md"),
    ("evidence/reviewer_r3/REVIEW_REPORT_v2_r3fix.md", BASE + "evidence/reviewer_r3/REVIEW_REPORT_v2_r3fix.md"),
    ("evidence/reviewer_r3/REVIEW_REPORT_v3_final.md", BASE + "evidence/reviewer_r3/REVIEW_REPORT_v3_final.md"),
]
mismatch = []
for zrel, rpath in KEY:
    zb = z.read(TOP + zrel)
    gb = gitblob(rpath)
    eq = zb == gb
    creq = zb.replace(b"\r", b"") == gb.replace(b"\r", b"")
    if not eq:
        mismatch.append((zrel, "bytes_differ", "cr_eq=%s" % creq))
check("C4.key_members_match_repo(16)", not mismatch, mismatch[:4])
loc = []
for zrel, local in (("evidence/reviewer_r3/REVIEW_REPORT_v1.md", "REVIEW_REPORT_v1.md"),
                    ("evidence/reviewer_r3/REVIEW_REPORT_v2_r3fix.md", "REVIEW_REPORT_v2_r3fix.md"),
                    ("evidence/reviewer_r3/REVIEW_REPORT_v3_final.md", "REVIEW_REPORT_v3_final.md")):
    lb = (LOCAL / local).read_bytes()
    if z.read(TOP + zrel) != lb:
        loc.append((zrel, "differ_raw", z.read(TOP + zrel).replace(b"\r", b"") == lb.replace(b"\r", b"")))
check("C4.reports_match_local_originals", not loc, loc)

docs = {d: z.read(TOP + d).decode("utf-8", errors="replace") for d in
        ("CLOSURE_REPORT_RC.md", "PENDING_APPROVAL_SUMMARY.md", "COMMANDS_APPENDIX.md", "DECISION_SUMMARY.md")}
A3 = "0f494d27bad2ed0de6876ff32f4cb7d656a19c98"
TREE = "7a2fecbbea921181562720b07e5b87ca6c4e5f7a"
PLAN = "qbpl-c2dd9bb802ca890cc6aa2ef2b9ae4ffbb8f5f1788ee7e87dd7854816aabe8a36"
REC = "2e9fccfb14ab9c67992a1031302b690d2af28c6c56f8c0d05d412fb2ce4d5548"
for d, txt in docs.items():
    ok = A3 in txt and (TREE in txt or d == "DECISION_SUMMARY.md" and "7a2fecbb" in txt) and "qbpl-c2dd9bb8" in txt and ("2e9fccfb" in txt or d == "COMMANDS_APPENDIX.md") and "qaf-v3-0f494d27-a2" in txt
    check("C5.bindings_" + d[:20], ok, "")
stale_hits = []
for d, txt in docs.items():
    for m in re.finditer(r"85a879a4|ae50a20c|24ddea34", txt):
        s = max(0, m.start() - 50)
        stale_hits.append((d, txt[s:m.end() + 40].replace("\n", " ")))
info("C5.stale_candidate_mentions", "%d (expect evolution/history only)" % len(stale_hits))
for d, ctx in stale_hits[:14]:
    print("  CTX %s :: ...%s..." % (d, ctx))
ph = []
for n in [i.filename for i in files if i.filename.endswith((".md", ".json", ".txt"))]:
    t = z.read(n).decode("utf-8", errors="replace")
    for pat in ("稍后补", "TBD", "待补", "FIXME", "XXX_placeholder"):
        if pat in t:
            ph.append((n, pat))
check("C5.no_placeholders", not ph, ph[:5])

ds = docs["DECISION_SUMMARY.md"]
check("C6.decision_summary_le2p", len(ds) < 7400 and ds.count("\n") < 120, "chars=%d lines=%d" % (len(ds), ds.count("\n")))
check("C6.decision_has_template_and_steps", "批准:以 Commit A" in ds and "E1" in ds and "E4" in ds and "COMMANDS_APPENDIX" in ds, "")
idx = z.read(TOP + "evidence/regression_attempts_index.md").decode("utf-8", errors="replace")
check("C6.attempts_index_sha_refs", all(x in idx for x in ("85a879a4", "24ddea34", "0f494d27", "f19126d1", "2e9fccfb")) and "commit" in idx.lower(), idx[:150])
sd = [n for n in names if n.startswith(TOP + "source_diff/")]
check("C6.source_diff_present", len(sd) >= 1, sd)
plogs = [n for n in names if "prefix_probe_0f494d27" in n]
check("C6.prefix_logs_in_pkg", any("step1_provenance.log" in n for n in plogs) and any("step3_audit.log" in n for n in plogs), str(len(plogs)))

print("== SUMMARY pass=%d fail=%d ==" % (R["pass"], R["fail"]))
