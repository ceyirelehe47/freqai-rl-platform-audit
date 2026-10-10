# -*- coding: utf-8 -*-
# Final re-verification probe (A3 = 0f494d27)
import hashlib, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

OUT = Path("/home/cryptorl/tmp_rcw_r3")
OUT.mkdir(parents=True, exist_ok=True)
PY = "/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python"
A = "0f494d27bad2ed0de6876ff32f4cb7d656a19c98"
TREE = "7a2fecbbea921181562720b07e5b87ca6c4e5f7a"
PLAN = "qbpl-c2dd9bb802ca890cc6aa2ef2b9ae4ffbb8f5f1788ee7e87dd7854816aabe8a36"
RECORD_SHA = "2e9fccfb14ab9c67992a1031302b690d2af28c6c56f8c0d05d412fb2ce4d5548"
P3 = "/home/cryptorl/projects/crypto_rl_qaf_v3"
D3 = "/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3"
PIN = "/home/cryptorl/release_pin_qaf_v3"
REPO = "/mnt/f/trading/freqai-rl-audit"
EV = REPO + "/stage2_6_1/artifacts/repair17/development/a2_runtime_closure_v1/evidence"
R = {"pass": 0, "fail": 0}

def check(name, ok, detail=""):
    R["pass" if ok else "fail"] += 1
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail else ""))

def git(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True)
    return p.returncode, p.stdout, p.stderr

print("== U1 PIN @A3 ==")
rc, head, _ = git(PIN, "rev-parse", "HEAD")
rc2, branch, _ = git(PIN, "branch", "--show-current")
rc3, dirty, _ = git(PIN, "status", "--porcelain")
check("U1.pin_head_A3", rc == 0 and head.decode().strip() == A, head)
check("U1.pin_branch", branch.decode().strip() == "route-c-stage2-6-1-repair17", branch)
check("U1.pin_clean", dirty == b"", dirty)

print("== U2 P3 sync (byte) ==")
rc, blob, _ = git(REPO, "show", A + ":stage2_6_1/src/rl_curriculum/curriculum261_qprod_formal_budget.py")
dep = Path(P3 + "/src/rl_curriculum/curriculum261_qprod_formal_budget.py").read_bytes()
check("U2.sync_budget", blob == dep, "")

print("== U3 freeze rerun @A3 (own out-dir) ==")
eng = OUT / "eng_freeze_a3"; neg = OUT / "eng_freeze_a3_neg"
for d in (eng, neg):
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
env = {"PYTHONPATH": P3 + "/src", "PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin", "HOME": "/home/cryptorl"}
code = (
 "from pathlib import Path\n"
 "import rl_curriculum.curriculum261_r17_dependencies as dep\n"
 "doc = dep.write_r17_code_freeze(Path(%r), code_freeze_sha=%r)\n"
 "fs = doc['freeze_surface']\n"
 "print('OK', doc['freeze_surface_digest'], fs['missing_required'], fs['repo_head_commit'][:12])\n"
) % (str(eng), A)
p = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=600)
check("U3.freeze_positive", "r17fs-5f36c3ca" in p.stdout and "[]" in p.stdout, p.stdout.strip()[:120])
code = (
 "from pathlib import Path\n"
 "import rl_curriculum.curriculum261_r17_dependencies as dep\n"
 "try:\n"
 "    dep.write_r17_code_freeze(Path(%r), code_freeze_sha='1'*40)\n"
 "    print('UNEXPECTED_OK')\n"
 "except RuntimeError:\n"
 "    print('REFUSED')\n"
) % (str(neg),)
p = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=600)
check("U3.dummy_refused", "REFUSED" in p.stdout, "")

print("== U4 plan rebuild @A3 + payload-wide namespace sweep ==")
code = (
 "import json, re\n"
 "from rl_curriculum.curriculum261_qaf_attempt import QAF_ATTEMPTS\n"
 "from rl_curriculum.curriculum261_qprod_formal_levela import build_formal_level_a_plan\n"
 "from rl_curriculum.curriculum261_qprod_plan import research_plan_digest\n"
 "from rl_curriculum.curriculum261_qprod_coordinate import qprod_coordinate_code_identity\n"
 "ci = qprod_coordinate_code_identity()\n"
 "p3 = build_formal_level_a_plan(code_freeze_sha=%r, code_identity=ci, authorized_stop_after='verify-formal-logs', model_update_authorized=True, formal_attempt='qaf_v3')\n"
 "print('DIGEST', research_plan_digest(p3))\n"
 "draft = json.load(open(%r))\n"
 "print('DRAFT_EQ', draft == p3)\n"
 "dump = json.dumps(p3, ensure_ascii=False)\n"
 "hits = re.findall(r'[a-zA-Z0-9_]*_r17\\\\b|qaf_v[0-9]\\\\b', dump)\n"
 "nonfn = sorted(set(h for h in hits if not h.startswith('run_') and h not in ('r17',)))\n"
 "print('NS_SWEEP', json.dumps(nonfn))\n"
 "fam = QAF_ATTEMPTS['qaf_v3']\n"
 "ai = p3['run_scope']['attempt_identity']\n"
 "print('AI', ai['attempt'] == 'qaf_v3', ai['audit_bank'] == fam.audit_bank, ai['preplan_smoke'] == fam.preplan_smoke, ai['ppo_smoke'] == fam.ppo_smoke)\n"
 "cons = [i['consumer'] for g in p3['run_scope']['budget_items'] for i in (g if isinstance(g, list) else [g])]\n"
 "mets = [i.get('metering', '') for g in p3['run_scope']['budget_items'] for i in (g if isinstance(g, list) else [g])]\n"
 "smoke = [c for c in cons if 'fit_preprocessor_v2_from_bank_r17' in c and 'smoke' in c.lower() or 'ppo_smoke' in c]\n"
 "print('SMOKE_CONS', json.dumps([c[:80] for c in cons if 'ppo_smoke' in c or 'generate_pair' in c], ensure_ascii=False))\n"
 "print('METER_SMOKE', json.dumps([m[:60] for m in mets if 'smoke' in m], ensure_ascii=False))\n"
 "p2 = build_formal_level_a_plan(code_freeze_sha=%r, code_identity=ci, authorized_stop_after='verify-formal-logs', model_update_authorized=True, formal_attempt='qaf_v2')\n"
 "def flat(d, path=''):\n"
 "    out = {}\n"
 "    if isinstance(d, dict):\n"
 "        for k in d:\n"
 "            out.update(flat(d[k], path + '/' + k))\n"
 "    else:\n"
 "        out[path] = d\n"
 "    return out\n"
 "f1, f2 = flat(p2), flat(p3)\n"
 "diff = sorted(k for k in f1 if f1[k] != f2.get(k))\n"
 "ident = {k for k in diff if k in ('/code_freeze_sha', '/iteration_id', '/rules/smoke_policy', '/run_scope/budget_items') or k.startswith('/run_scope/attempt_identity/') or k == '/run_scope/embedded_preflight_smoke/description'}\n"
 "print('V2V3_ALL_IDENTITY', set(diff) == ident and len(diff) == len(ident), len(diff))\n"
 "print('QUOTA_EQ', p2['quota'] == p3['quota'], p2['run_scope']['authorized_stop_after'] == p3['run_scope']['authorized_stop_after'], p2['run_scope']['gate_set'] == p3['run_scope']['gate_set'])\n"
) % (A, REPO + "/stage2_6_1/artifacts/repair17/development/a2_runtime_closure_v1/plans/A2_qaf_v3/qprod_formal_level_a_draft_plan.json", "a96bedea24b3a84a19d30f505a121d8c3d68bba3")
p = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=600)
print(p.stdout.strip())
if p.returncode:
    print("ERR", p.stderr[-300:])
for ln in p.stdout.splitlines():
    k, _, v = ln.partition(" ")
    if k == "DIGEST":
        check("U4.plan_digest", v == PLAN, v)
    if k == "DRAFT_EQ":
        check("U4.draft_eq", v == "True", v)
    if k == "NS_SWEEP":
        res = json.loads(v)
        check("U4.no_stale_ns_tokens", res == [], res)
    if k == "AI":
        check("U4.attempt_identity", v.split() == ["True"] * 4, v)
    if k == "V2V3_ALL_IDENTITY":
        ok, n = v.split()
        check("U4.v2v3_identity_only", ok == "True", "ndiff=" + n)
    if k == "QUOTA_EQ":
        check("U4.quota_stop_gateset", v.split() == ["True", "True", "True"], v)

print("== U5 substance rerun @A3 ==")
prereg = OUT / "prereg_a3.json"
prereg.write_text(json.dumps({
    "admission_id": "rcw-r3-final-probe",
    "iteration": "qprod_a_formal_v3",
    "plan_digest": TREE,
    "plan_digest_method": "git_tree_digest",
    "regression_evidence": EV + "/regress261_d3/regression_evidence_v3_record.json",
    "authorization": "reviewer read-only probe",
    "formal_attempt": "qaf_v3",
}, indent=1), encoding="utf-8")
p = subprocess.run([PY, "-m", "rl_curriculum.curriculum261_r17_admission_substance", "verify",
                    "--repo", PIN, "--commit-a", A, "--preregistration", str(prereg),
                    "--deploy-root", D3], capture_output=True, text=True, env=env, timeout=900)
ok5 = p.returncode == 0
d5 = ""
if ok5:
    s = json.loads(p.stdout)["substance"]
    d5 = s["plan_digest_recomputed"][:12] + " " + s["regression_evidence"]["sha256"][:12]
check("U5.same_root_rc0", ok5 and TREE.startswith(d5.split()[0]) and RECORD_SHA.startswith(d5.split()[1]), d5)
p = subprocess.run([PY, "-m", "rl_curriculum.curriculum261_r17_admission_substance", "verify",
                    "--repo", PIN, "--commit-a", A, "--preregistration", str(prereg),
                    "--deploy-root", P3], capture_output=True, text=True, env=env, timeout=900)
check("U5.wrong_root_rc2", p.returncode == 2, "rc=" + str(p.returncode))

print("== U6 three-way rerun ==")
p = subprocess.run([PY, str(OUT / "threeway_rerun.py")], capture_output=True, text=True, env=env, timeout=300)
check("U6.threeway", "698/698 equal" in p.stdout and "597/597 equal" in p.stdout and "660/660 equal" in p.stdout and "mismatches: 0" in p.stdout, p.stdout.strip()[:150])

print("== U7 preflight + gate @A3 ==")
sys.path.insert(0, P3 + "/src")
from rl_curriculum.curriculum261_qaf_provenance_guard import runtime_dependency_preflight, preissue_gate
rd = runtime_dependency_preflight(repo=Path(REPO), project_dir=Path(P3), candidate_sha=A)
check("U7.preflight_ok", rd.get("ok") is True and rd.get("repo_head_commit") == A, str(rd.get("problems"))[:120])
check("U7.config_absent", not os.path.exists(D3 + "/qprod_deploy_config.json"), "")
g = preissue_gate(repo=Path(REPO), deploy_root=Path(D3), project_dir=Path(P3),
                  attempt="qaf_v3", candidate_sha=A, report_out=OUT / "gate_refused_a3.json")
check("U7.gate_fail_closed", g.get("ok") is False and g.get("one_shot_writes") == 0, str(g.get("refusal"))[:120])

print("== U8 old scenes quick ==")
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
P1 = "/home/cryptorl/projects/crypto_rl"
check("U8.P1_admission", sha(P1 + "/.r17_formal_admission.json") == "b465e5f17a651d0aee7f9a10fbb406448a37e1eae414c541aef7861db668ab6c", "")
check("U8.P2_env_missing", not os.path.exists("/home/cryptorl/projects/crypto_rl_qaf_v2/environment.yml"), "")

print("== SUMMARY pass=%d fail=%d ==" % (R["pass"], R["fail"]))
