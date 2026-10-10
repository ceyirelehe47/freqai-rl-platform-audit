# -*- coding: utf-8 -*-
# R3-fix re-verification probe (A'' = 24ddea34)
import hashlib, json, os, subprocess, sys, time
from pathlib import Path

OUT = Path("/home/cryptorl/tmp_rcw_r3")
OUT.mkdir(parents=True, exist_ok=True)
PY = "/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python"
A = "24ddea34f2a32ae08bf1238e95112391c0d84ab4"
TREE = "9020b844caf3c80fbfbe5a3fd37448c2155a1870"
PLAN = "qbpl-cf43299003ae573108401e10b6f5eefbdf4afb2d59d3dd0bbc542d7c1197059e"
RECORD_SHA = "f19126d157f9318ff1166e93fecaa4c9436e20fe7bc3f5c305bb6ed881bae0e9"
P3 = "/home/cryptorl/projects/crypto_rl_qaf_v3"
D3 = "/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3"
PIN = "/home/cryptorl/release_pin_qaf_v3"
REPO = "/mnt/f/trading/freqai-rl-audit"
EV = REPO + "/stage2_6_1/artifacts/repair17/development/a2_runtime_closure_v1/evidence"
DRAFT = EV + "/../plans/A2_qaf_v3/qprod_formal_level_a_draft_plan.json"
R = {"pass": 0, "fail": 0}

def check(name, ok, detail=""):
    R["pass" if ok else "fail"] += 1
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:400]) if detail else ""))

def info(name, detail):
    print("INFO " + name + " :: " + str(detail)[:500])

def git(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

print("== T1 PIN @A'' ==")
rc, head, _ = git(PIN, "rev-parse", "HEAD")
rc2, branch, _ = git(PIN, "branch", "--show-current")
rc3, dirty, _ = git(PIN, "status", "--porcelain")
check("T1.pin_head_A2", rc == 0 and head == A, head)
check("T1.pin_branch", rc2 == 0 and branch == "route-c-stage2-6-1-repair17", branch)
check("T1.pin_clean", dirty == "", dirty)

print("== T2 P3 deploy sync vs A'' blobs ==")
for rel in ("stage2_6_1/src/rl_curriculum/curriculum261_qprod_formal_levela.py",
            "stage2_6_1/src/rl_curriculum/curriculum261_qprod_formal_budget.py"):
    rc, blob, _ = git(REPO, "show", A + ":" + rel)
    dep = P3 + "/src/rl_curriculum/" + rel.split("/")[-1]
    depb = open(dep, "rb").read()
    eq = depb.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n") == blob.replace("\r\n", "\n").replace("\r", "\n")
    check("T2.sync_" + rel.split("/")[-1][:40], eq, "")

print("== T3 freeze engineering rerun @A'' (own out-dir) ==")
import shutil
eng = OUT / "eng_freeze_a2"; neg = OUT / "eng_freeze_a2_neg"
for d in (eng, neg):
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
code = (
 "import json\n"
 "from pathlib import Path\n"
 "import rl_curriculum.curriculum261_r17_dependencies as dep\n"
 "doc = dep.write_r17_code_freeze(Path(%r), code_freeze_sha=%r)\n"
 "fs = doc['freeze_surface']\n"
 "print('OK', doc['freeze_surface_digest'], fs['missing_required'], fs['repo_head_commit'][:12], fs['n_dev_files'])\n"
) % (str(eng), A)
env = {"PYTHONPATH": P3 + "/src", "PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin", "HOME": "/home/cryptorl"}
p = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=600)
check("T3.freeze_positive", p.returncode == 0 and "r17fs-f835a8a2" in p.stdout, p.stdout.strip()[:150] + p.stderr.strip()[-150:])
code = (
 "from pathlib import Path\n"
 "import rl_curriculum.curriculum261_r17_dependencies as dep\n"
 "try:\n"
 "    dep.write_r17_code_freeze(Path(%r), code_freeze_sha='1'*40)\n"
 "    print('UNEXPECTED_OK')\n"
 "except RuntimeError as e:\n"
 "    print('REFUSED ' + str(e)[:120])\n"
) % (str(neg),)
p = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=600)
check("T3.dummy_refused", "REFUSED" in p.stdout, p.stdout.strip()[:150])

print("== T4 plan rebuild @A'' (identity texts + attempt_identity) ==")
code = (
 "import copy, json\n"
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
 "print('HAS_V1_TOKEN', 'ppo_smoke_qaf_v1' in dump)\n"
 "fam = QAF_ATTEMPTS['qaf_v3']\n"
 "ai = p3['run_scope']['attempt_identity']\n"
 "print('AI', ai['attempt'] == 'qaf_v3', ai['audit_bank'] == fam.audit_bank, ai['preplan_smoke'] == fam.preplan_smoke, ai['ppo_smoke'] == fam.ppo_smoke)\n"
 "print('AI_VALS', ai['audit_bank'], ai['preplan_smoke'], ai['ppo_smoke'])\n"
 "desc = p3['run_scope']['embedded_preflight_smoke']['description']\n"
 "pol = p3['rules']['smoke_policy']\n"
 "print('DESC_OK', fam.ppo_smoke in desc and 'ppo_smoke_qaf_v1' not in desc)\n"
 "print('POLICY_OK', fam.ppo_smoke in pol and 'ppo_smoke_qaf_v1' not in pol)\n"
 "cons = [i['consumer'] for g in p3['run_scope']['budget_items'] for i in (g if isinstance(g, list) else [g])]\n"
 "stale = []\n"
 "for c in cons:\n"
 "    if \"'ppo_smoke_r17'\" in c or '(ppo_smoke_r17)' in c or 'ppo_smoke_r17 ' in c:\n"
 "        stale.append(c[:90])\n"
 "print('STALE_SMOKE_ITEMS', json.dumps(stale, ensure_ascii=False))\n"
 "bank = [c for c in cons if 'generate_fit_bank(' in c]\n"
 "print('BANK_CONS', bank[0][:90] if bank else 'NONE')\n"
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
 "print('V2V3_DIFF', json.dumps(diff))\n"
 "print('QUOTA_EQ', p2['quota'] == p3['quota'], 'STOP_EQ', p2['run_scope']['authorized_stop_after'] == p3['run_scope']['authorized_stop_after'], 'GATESET_EQ', p2['run_scope']['gate_set'] == p3['run_scope']['gate_set'])\n"
) % (A, REPO + "/stage2_6_1/artifacts/repair17/development/a2_runtime_closure_v1/plans/A2_qaf_v3/qprod_formal_level_a_draft_plan.json", "a96bedea24b3a84a19d30f505a121d8c3d68bba3")
p = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=600)
info("T4.stdout", p.stdout.strip() + (" ERR:" + p.stderr.strip()[-250:] if p.returncode else ""))
for ln in p.stdout.splitlines():
    k = ln.split(" ", 1)[0]
    v = ln.split(" ", 1)[1] if " " in ln else ""
    if k == "DIGEST":
        check("T4.plan_digest", v == PLAN, v)
    if k == "DRAFT_EQ":
        check("T4.draft_eq_rebuilt", v == "True", v)
    if k == "HAS_V1_TOKEN":
        check("T4.no_v1_token", v == "False", v)
    if k == "AI":
        check("T4.attempt_identity_matches_family", v.split() == ["True", "True", "True", "True"], v)
    if k == "AI_VALS":
        check("T4.ai_values", v == "preplan_audit_bank_qaf_v3 preplan_smoke_qaf_v3 ppo_smoke_qaf_v3", v)
    if k == "DESC_OK":
        check("T4.desc_follows_family", v == "True", v)
    if k == "POLICY_OK":
        check("T4.policy_follows_family", v == "True", v)
    if k == "STALE_SMOKE_ITEMS":
        res = json.loads(v)
        info("T4.residual_stale_count", len(res))
        print("RESIDUAL " + json.dumps(res, ensure_ascii=False))
    if k == "BANK_CONS":
        check("T4.bank_consumer_v3", "preplan_audit_bank_qaf_v3" in v, v)
    if k == "V2V3_DIFF":
        diff = json.loads(v)
        expect = sorted({"/iteration_id", "/run_scope/budget_items",
                         "/run_scope/embedded_preflight_smoke/description",
                         "/run_scope/attempt_identity/attempt",
                         "/run_scope/attempt_identity/audit_bank",
                         "/run_scope/attempt_identity/preplan_smoke",
                         "/run_scope/attempt_identity/ppo_smoke",
                         "/rules/smoke_policy"})
        check("T4.v2v3_identity_keys_only", diff == expect, diff)
    if k == "QUOTA_EQ":
        vals = v.split()
        check("T4.quota_stop_gateset_eq", vals == ["True", "True", "True"], v)

print("== T5 substance rerun @A'' ==")
prereg = OUT / "prereg_a2.json"
prereg.write_text(json.dumps({
    "admission_id": "rcw-r3-reverify-probe",
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
check("T5.same_root_rc0", p.returncode == 0, (p.stdout + p.stderr)[-200:])
if p.returncode == 0:
    s = json.loads(p.stdout)["substance"]
    check("T5.digest_9020", s["plan_digest_claimed"] == s["plan_digest_recomputed"] == TREE, s["plan_digest_recomputed"][:16])
    check("T5.record_sha_counts", s["regression_evidence"]["sha256"] == RECORD_SHA and s["regression_evidence"]["counts"].get("tests") == 2990, str(s["regression_evidence"]["counts"]))
p = subprocess.run([PY, "-m", "rl_curriculum.curriculum261_r17_admission_substance", "verify",
                    "--repo", PIN, "--commit-a", A, "--preregistration", str(prereg),
                    "--deploy-root", P3], capture_output=True, text=True, env=env, timeout=900)
check("T5.wrong_root_rc2", p.returncode == 2, "rc=" + str(p.returncode) + " " + (p.stdout + p.stderr)[-120:])

print("== T6 three-way rerun (original semantics, own output) ==")
p = subprocess.run([PY, str(OUT / "threeway_rerun.py")], capture_output=True, text=True, env=env, timeout=300)
check("T6.threeway_698_597_660", "698/698 equal" in p.stdout and "597/597 equal" in p.stdout and "660/660 equal" in p.stdout and "mismatches: 0" in p.stdout, p.stdout.strip()[:200])

print("== T7 preflight live @A'' ==")
sys.path.insert(0, P3 + "/src")
try:
    from rl_curriculum.curriculum261_qaf_provenance_guard import runtime_dependency_preflight
    rd = runtime_dependency_preflight(repo=Path(REPO), project_dir=Path(P3), candidate_sha=A)
    check("T7.preflight_ok", rd.get("ok") is True and rd.get("repo_head_commit") == A and rd.get("repo_root") == PIN, json.dumps(rd.get("problems", []))[:150])
except Exception as exc:
    check("T7.preflight_ok", False, repr(exc)[:200])

print("== T8 gate E1-absent still fail-closed ==")
check("T8.config_absent", not os.path.exists(D3 + "/qprod_deploy_config.json"), "")
try:
    from rl_curriculum.curriculum261_qaf_provenance_guard import preissue_gate
    g = preissue_gate(repo=Path(REPO), deploy_root=Path(D3), project_dir=Path(P3),
                      attempt="qaf_v3", candidate_sha=A,
                      report_out=OUT / "gate_refused_a2.json")
    check("T8.gate_refused_zero_writes", g.get("ok") is False and g.get("one_shot_writes") == 0, str(g.get("refusal"))[:150])
except Exception as exc:
    check("T8.gate_refused_zero_writes", False, repr(exc)[:200])

print("== T9 old scenes recheck ==")
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
P2 = "/home/cryptorl/projects/crypto_rl_qaf_v2"
D2 = "/home/cryptorl/projects/crypto_rl_formal_a_qaf_v2"
P1 = "/home/cryptorl/projects/crypto_rl"
check("T9.P1_admission", sha(P1 + "/.r17_formal_admission.json") == "b465e5f17a651d0aee7f9a10fbb406448a37e1eae414c541aef7861db668ab6c", "")
check("T9.P1_issued", sha(P1 + "/r17_admission_issued.jsonl") == "956178b282e42ae73be1cdd3ade0772af53cf7eb2682fe8b9d02a20411fdcb6f", "")
check("T9.P2_env_still_missing", not os.path.exists(P2 + "/environment.yml") and not os.path.exists(P2 + "/requirements-lock.txt"), "")
EXCL = ("__pycache__", ".pytest_cache", ".cache", ".git")
cutoff = time.mktime(time.strptime("2026-10-06 00:00:00", "%Y-%m-%d %H:%M:%S"))
viol = []
for root in (P2, D2):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in EXCL]
        for fn in fns:
            fp = os.path.join(dp, fn)
            try:
                if os.path.getmtime(fp) >= cutoff:
                    viol.append(fp)
            except OSError:
                pass
check("T9.P2_D2_untouched_since_1006", not viol, str(viol[:3]))
for rel in ("stage2_6_1/src/rl_curriculum/curriculum261_r17_admission_substance.py",
            "stage2_6_1/src/rl_curriculum/__init__.py"):
    rc, blob, _ = git(REPO, "show", A + ":" + rel)
    dep = P1 + "/src/rl_curriculum/" + rel.split("/")[-1]
    eq = open(dep, "rb").read() == blob.encode() if rc == 0 else False
    info("T9.sync_" + rel.split("/")[-1], "blob_eq=" + str(eq) + " rc=" + str(rc))

print("== SUMMARY pass=%d fail=%d ==" % (R["pass"], R["fail"]))
