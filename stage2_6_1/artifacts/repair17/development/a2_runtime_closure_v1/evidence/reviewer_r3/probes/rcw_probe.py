# -*- coding: utf-8 -*-
# Independent reviewer probe for RouteC_A2_RuntimeClosure_NewAttempt_v1
# Read-only against audited objects; writes only under /home/cryptorl/tmp_rcw_r3
import hashlib, json, os, subprocess, sys, time
from pathlib import Path

OUT = Path("/home/cryptorl/tmp_rcw_r3")
OUT.mkdir(parents=True, exist_ok=True)
PY = "/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python"
A = "85a879a46d0a20831644eb9aae52e0537436713f"
TREE = "06827b7d1534e136fd2b65347ec0f7ce392c0c3e"
PLAN = "qbpl-2c65de6fe59a03b817ee3653d744a8c05ccdaf35dac6bba02cf66a20179330e4"
RECORD_SHA = "de43964e7ebe476f5ce2e3a88800d157278aa8a99d092a0bb496445a7784e994"
P3 = "/home/cryptorl/projects/crypto_rl_qaf_v3"
D3 = "/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3"
PIN = "/home/cryptorl/release_pin_qaf_v3"
REPO = "/mnt/f/trading/freqai-rl-audit"
EV = REPO + "/stage2_6_1/artifacts/repair17/development/a2_runtime_closure_v1/evidence"
R = {"pass": 0, "fail": 0, "info": 0}

def check(name, ok, detail=""):
    R["pass" if ok else "fail"] += 1
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:400]) if detail else ""))

def info(name, detail):
    R["info"] += 1
    print("INFO " + name + " :: " + str(detail)[:400])

def git(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

print("== S1 PIN state ==")
rc, head, _ = git(PIN, "rev-parse", "HEAD")
rc2, branch, _ = git(PIN, "branch", "--show-current")
rc3, pordirty, _ = git(PIN, "status", "--porcelain")
rc4, pintree, _ = git(PIN, "rev-parse", "HEAD^{tree}")
check("S1.pin_head==A", rc == 0 and head == A, head)
check("S1.pin_branch", rc2 == 0 and branch == "route-c-stage2-6-1-repair17", branch)
check("S1.pin_clean", rc3 == 0 and pordirty == "", pordirty)
check("S1.pin_is_independent_clone", (Path(PIN) / ".git").is_dir(), "dotgit_dir=" + str((Path(PIN)/".git").is_dir()))
info("S1.pin_tree", pintree)

print("== S2 release_repo_candidates pin priority (live import from P3) ==")
code = (
 "import rl_curriculum.curriculum261_r17_dependencies as d\n"
 "print('CANDS', [str(c) for c in d.release_repo_candidates()])\n"
 "print('RESOLVED', d._freeze_release_repo())\n")
p = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                   env={"PYTHONPATH": P3 + "/src", "PYTHONDONTWRITEBYTECODE": "1",
                        "PATH": "/usr/bin:/bin", "HOME": "/home/cryptorl"})
info("S2.stdout", p.stdout.strip() + p.stderr.strip()[-200:])
check("S2.pin_first", "release_pin_qaf_v3" in p.stdout.split("CANDS")[1].splitlines()[0] if "CANDS" in p.stdout else False, "")
check("S2.resolved_pin", "RESOLVED " + PIN in p.stdout, "")

print("== S3 freeze engineering rerun (own out-dir) ==")
eng = OUT / "eng_freeze_rcw"
neg = OUT / "eng_freeze_neg"
import shutil
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
 "print('FREEZE_OK', json.dumps({'digest': doc['freeze_surface_digest'], 'missing': fs['missing_required'], 'root': str(fs['repo_root']), 'head': fs['repo_head_commit'], 'dev': fs['n_dev_files'], 'tracked': fs['n_repo_tracked']}))\n"
) % (str(eng), A)
p = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                   env={"PYTHONPATH": P3 + "/src", "PYTHONDONTWRITEBYTECODE": "1",
                        "PATH": "/usr/bin:/bin", "HOME": "/home/cryptorl"}, timeout=600)
line = [l for l in p.stdout.splitlines() if l.startswith("FREEZE_OK")]
check("S3.freeze_positive_rc0", p.returncode == 0 and line, (p.stdout + p.stderr)[-300:])
if line:
    fj = json.loads(line[0][len("FREEZE_OK "):])
    check("S3.freeze_digest", fj["digest"] == "r17fs-c4b5818c0aec55fedde63fba523366a6d20b7bbe874e8732ffff9913935070af", fj["digest"])
    check("S3.freeze_missing_empty", fj["missing"] == [], fj["missing"])
    check("S3.freeze_root_pin_head_A", fj["root"] == PIN and fj["head"] == A, str(fj["root"]) + " " + fj["head"][:12])
    check("S3.freeze_artifact_written", (eng / "r17_code_freeze.json").is_file(), "")
code = (
 "from pathlib import Path\n"
 "import rl_curriculum.curriculum261_r17_dependencies as dep\n"
 "try:\n"
 "    dep.write_r17_code_freeze(Path(%r), code_freeze_sha='1'*40)\n"
 "    print('UNEXPECTED_OK')\n"
 "except RuntimeError as e:\n"
 "    print('REFUSED ' + str(e)[:200])\n"
) % (str(neg),)
p = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                   env={"PYTHONPATH": P3 + "/src", "PYTHONDONTWRITEBYTECODE": "1",
                        "PATH": "/usr/bin:/bin", "HOME": "/home/cryptorl"}, timeout=600)
check("S3.dummy_sha_refused", "REFUSED" in p.stdout and "repo HEAD" in p.stdout, p.stdout.strip()[:220])

print("== S4 plan digest rebuild (real builder) + v2/v3 identity diff ==")
code = (
 "import copy, json\n"
 "from rl_curriculum.curriculum261_qprod_formal_levela import build_formal_level_a_plan\n"
 "from rl_curriculum.curriculum261_qprod_plan import research_plan_digest\n"
 "from rl_curriculum.curriculum261_qprod_coordinate import qprod_coordinate_code_identity\n"
 "ci = qprod_coordinate_code_identity()\n"
 "p3 = build_formal_level_a_plan(code_freeze_sha=%r, code_identity=ci, authorized_stop_after='verify-formal-logs', model_update_authorized=True, formal_attempt='qaf_v3')\n"
 "d = research_plan_digest(p3)\n"
 "print('PLAN_DIGEST', d)\n"
 "draft = json.load(open(%r))\n"
 "print('DRAFT_EQ_REBUILT', draft == p3)\n"
 "p2 = build_formal_level_a_plan(code_freeze_sha='a96bedea24b3a84a19d30f505a121d8c3d68bba3', code_identity=ci, authorized_stop_after='verify-formal-logs', model_update_authorized=True, formal_attempt='qaf_v2')\n"
 "def diffkeys(a, b, path=''):\n"
 "    out = []\n"
 "    if isinstance(a, dict) and isinstance(b, dict):\n"
 "        for k in sorted(set(a) | set(b)):\n"
 "            out += diffkeys(a.get(k), b.get(k), path + '/' + k)\n"
 "    elif isinstance(a, list) and isinstance(b, list):\n"
 "        if a != b:\n"
 "            out.append(path)\n"
 "    elif a != b:\n"
 "        out.append(path)\n"
 "    return out\n"
 "print('V2_V3_DIFF', json.dumps(sorted(diffkeys(p2, p3))))\n"
 "print('SMOKE_DESC', p3['run_scope']['embedded_preflight_smoke']['description'][:180])\n"
 "print('QUOTA_EQ', p2['quota'] == p3['quota'])\n"
 "print('RULES_EQ_EXC_MODELUPD', {k: v for k, v in p2['rules'].items() if k != 'model_update_authorized' and k != 'post_qualification_smoke_authorized'} == {k: v for k, v in p3['rules'].items() if k != 'model_update_authorized' and k != 'post_qualification_smoke_authorized'})\n"
 "print('STOP_EQ', p2['run_scope']['authorized_stop_after'] == p3['run_scope']['authorized_stop_after'])\n"
 "print('GATESET_EQ', p2['run_scope']['gate_set'] == p3['run_scope']['gate_set'])\n"
 "print('BUDGET_FACE_EQ', p2['run_scope']['budget'] == p3['run_scope']['budget'])\n"
 "print('BUDGET_ITEMS_EQ', p2['run_scope']['budget_items'] == p3['run_scope']['budget_items'])\n"
) % (A, REPO + "/stage2_6_1/artifacts/repair17/development/a2_runtime_closure_v1/plans/A2_qaf_v3/qprod_formal_level_a_draft_plan.json")
p = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                   env={"PYTHONPATH": P3 + "/src", "PYTHONDONTWRITEBYTECODE": "1",
                        "PATH": "/usr/bin:/bin", "HOME": "/home/cryptorl"}, timeout=600)
info("S4.stdout", p.stdout.strip() + (" ERR:" + p.stderr.strip()[-200:] if p.returncode else ""))
for ln in p.stdout.splitlines():
    if ln.startswith("PLAN_DIGEST"):
        check("S4.plan_digest", ln.split()[1] == PLAN, ln.split()[1])
    if ln.startswith("DRAFT_EQ_REBUILT"):
        check("S4.draft_eq_rebuilt", ln.split()[1] == "True", ln)
    if ln.startswith("V2_V3_DIFF"):
        diff = json.loads(ln.split(" ", 1)[1])
        check("S4.v2v3_only_identity", diff == ["/code_freeze_sha", "/iteration_id"], diff)
    if ln.startswith("QUOTA_EQ"):
        check("S4.quota_eq", ln.split()[1] == "True", ln)
    if ln.startswith("RULES_EQ_EXC_MODELUPD"):
        check("S4.rules_eq", ln.split()[1] == "True", ln)
    if ln.startswith("GATESET_EQ") or ln.startswith("BUDGET_FACE_EQ") or ln.startswith("BUDGET_ITEMS_EQ") or ln.startswith("STOP_EQ"):
        check("S4." + ln.split()[0].lower(), ln.split()[1] == "True", ln)
    if ln.startswith("SMOKE_DESC"):
        check("S4.smoke_desc_names_v1_not_v3", "ppo_smoke_qaf_v1" in ln, ln[:200])

print("== S5 qaf_v3 identity wiring ==")
code = (
 "from rl_curriculum.curriculum261_qaf_attempt import QAF3_ALL_NEW, QAF_ATTEMPTS, qaf_input_scope_for_attempt, qaf_iteration_id_for_attempt\n"
 "import rl_curriculum.curriculum261_api as api\n"
 "import rl_curriculum.curriculum261_r17_registry as reg\n"
 "import rl_curriculum.curriculum261_r17_generation_evidence as ge\n"
 "print('N26', len(QAF3_ALL_NEW), len(set(QAF3_ALL_NEW)))\n"
 "print('V1V2_DISJOINT', not (set(QAF3_ALL_NEW) & set(QAF_ATTEMPTS['qaf_v1'].input_scope)), not (set(QAF3_ALL_NEW) & set(QAF_ATTEMPTS['qaf_v2'].input_scope)))\n"
 "print('ITER', qaf_iteration_id_for_attempt('qaf_v3'))\n"
 "print('SCOPE_OK', qaf_input_scope_for_attempt('qaf_v3') == QAF3_ALL_NEW)\n"
 "print('SEED_MISSING', [n for n in QAF3_ALL_NEW if n not in api.CURRICULUM261_SEED_NAMESPACES][:3])\n"
 "print('API_ALL_OK', all(n in api.CURRICULUM261_R17_NAMESPACES for n in QAF3_ALL_NEW))\n"
 "print('API_FORMAL4_OK', all(n in api.CURRICULUM261_R17_FORMAL_NAMESPACES for n in QAF_ATTEMPTS['qaf_v3'].formal_four))\n"
 "print('REG_ALL_OK', all(n in reg.R17_ALL_NAMESPACES for n in QAF3_ALL_NEW))\n"
 "print('FW_ITERS', ge.R17_FRAMEWORK_ITERATIONS)\n"
 "print('S1', api.derive261_seed(QAF3_ALL_NEW[0], 'cue', 'r1', 0, 1) != api.derive261_seed(QAF3_ALL_NEW[0], 'cue', 'r1', 0, 2))\n"
)
p = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                   env={"PYTHONPATH": P3 + "/src", "PYTHONDONTWRITEBYTECODE": "1",
                        "PATH": "/usr/bin:/bin", "HOME": "/home/cryptorl"}, timeout=300)
info("S5.stdout", p.stdout.strip() + (" ERR:" + p.stderr.strip()[-200:] if p.returncode else ""))
for ln in p.stdout.splitlines():
    k = ln.split(" ", 1)[0]
    v = ln.split(" ", 1)[1] if " " in ln else ""
    if k == "N26":
        check("S5.26_unique", v.split() == ["26", "26"], v)
    if k == "V1V2_DISJOINT":
        check("S5.disjoint", v.split() == ["True", "True"], v)
    if k == "ITER":
        check("S5.iter_v3", v == "qprod_a_formal_v3", v)
    if k == "SCOPE_OK":
        check("S5.scope", v == "True", v)
    if k == "SEED_MISSING":
        check("S5.seed_registered", v in ("[]", ""), v)
    if k == "API_ALL_OK":
        check("S5.api_all", v == "True", v)
    if k == "API_FORMAL4_OK":
        check("S5.api_formal4", v == "True", v)
    if k == "REG_ALL_OK":
        check("S5.reg_all", v == "True", v)
    if k == "FW_ITERS":
        check("S5.fw_iter_has_v3", "qaf_v3" in v, v)

print("== S6 substance verify same-root rc0 / wrong-root rc2 ==")
prereg = OUT / "prereg_rcw.json"
prereg.write_text(json.dumps({
    "admission_id": "rcw-r3-review-probe",
    "iteration": "qprod_a_formal_v3",
    "plan_digest": TREE,
    "plan_digest_method": "git_tree_digest",
    "regression_evidence": EV + "/regress261_d3/regression_evidence_v3_record.json",
    "authorization": "reviewer read-only probe",
    "formal_attempt": "qaf_v3",
}, indent=1), encoding="utf-8")
base_env = {"PYTHONPATH": P3 + "/src", "PYTHONDONTWRITEBYTECODE": "1",
            "PATH": "/usr/bin:/bin", "HOME": "/home/cryptorl"}
p = subprocess.run([PY, "-m", "rl_curriculum.curriculum261_r17_admission_substance", "verify",
                    "--repo", PIN, "--commit-a", A, "--preregistration", str(prereg),
                    "--deploy-root", D3], capture_output=True, text=True, env=base_env, timeout=900)
check("S6.same_root_rc0", p.returncode == 0, (p.stdout + p.stderr)[-250:])
if p.returncode == 0:
    s = json.loads(p.stdout)["substance"]
    check("S6.claimed_eq_recomputed", s["plan_digest_claimed"] == s["plan_digest_recomputed"] == TREE, s["plan_digest_recomputed"])
    check("S6.counts_2989", s["regression_evidence"]["counts"].get("tests") == 2989 and s["regression_evidence"]["counts"].get("failures") == 0, s["regression_evidence"]["counts"])
    check("S6.record_sha", s["regression_evidence"]["sha256"] == RECORD_SHA, s["regression_evidence"]["sha256"])
p = subprocess.run([PY, "-m", "rl_curriculum.curriculum261_r17_admission_substance", "verify",
                    "--repo", PIN, "--commit-a", A, "--preregistration", str(prereg),
                    "--deploy-root", P3], capture_output=True, text=True, env=base_env, timeout=900)
check("S6.wrong_root_rc2", p.returncode == 2, "rc=" + str(p.returncode) + " out=" + (p.stdout + p.stderr)[-200:])

print("== S7 three-way compare (own CR-normalized script) ==")
EXCL = ("__pycache__", ".pytest_cache", ".cache", ".git")
def scan(root):
    root = Path(root)
    m = {}
    for f in root.rglob("*"):
        try:
            if not f.is_file() or f.is_symlink():
                continue
            rel = f.relative_to(root).as_posix()
            b = f.read_bytes()
        except OSError:
            continue
        if any(part in EXCL for part in rel.split("/")):
            continue
        m[rel] = hashlib.sha256(b.replace(b"\r", b"")).hexdigest()
    return m
P3m = scan(P3)
D3m = scan(D3)
PINm = scan(PIN)
tw = {}
for name, (x, y) in {"P3D3": (P3m, D3m), "P3PIN": (P3m, PINm), "D3PIN": (D3m, PINm)}.items():
    shared = set(x) & set(y)
    diff = sorted(k for k in shared if x[k] != y[k])
    tw[name] = {"shared": len(shared), "equal": len(shared) - len(diff),
                "only_left": len(set(x) - set(y)), "only_right": len(set(y) - set(x)),
                "diff_samples": diff[:10]}
(OUT / "three_way_rcw.json").write_text(json.dumps(tw, indent=1), encoding="utf-8")
check("S7.P3D3_698_equal", tw["P3D3"]["shared"] == 698 and tw["P3D3"]["equal"] == 698, tw["P3D3"])
check("S7.P3PIN_597_equal", tw["P3PIN"]["shared"] == 597 and tw["P3PIN"]["equal"] == 597, tw["P3PIN"])
check("S7.D3PIN_660_equal", tw["D3PIN"]["shared"] == 660 and tw["D3PIN"]["equal"] == 660, tw["D3PIN"])

print("== S8 old scenes read-only ==")
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
P2 = "/home/cryptorl/projects/crypto_rl_qaf_v2"
D2 = "/home/cryptorl/projects/crypto_rl_formal_a_qaf_v2"
P1 = "/home/cryptorl/projects/crypto_rl"
check("S8.P2_env_still_missing", not os.path.exists(P2 + "/environment.yml") and not os.path.exists(P2 + "/requirements-lock.txt"), "")
check("S8.P2_strategy", sha(P2 + "/user_data/strategies/RouteCStrategy.py") == "dc5deab41647d2bd5ce022ca8be08f3c229335162c81549eb07b3b1ca94c1fac", "")
check("S8.P2_activate", sha(P2 + "/activate-freqtrade.sh") == "6c43ec584dfa36722b69f4c6a96310fe427263cf06cf1d0a6f5eec2f431fa92e", "")
check("S8.D2_env", sha(D2 + "/environment.yml") == "e7a0850eb6c965a6f4dc6389802a0b388f2424eec6b80d7e62077197549f8899", "")
check("S8.D2_reqs", sha(D2 + "/requirements-lock.txt") == "4e727d3daed162cec3a47ee8d6d8602e44bf8f19a5d99032d51cfe3957c4d99b", "")
check("S8.P1_admission", sha(P1 + "/.r17_formal_admission.json") == "b465e5f17a651d0aee7f9a10fbb406448a37e1eae414c541aef7861db668ab6c", "")
check("S8.P1_issued", sha(P1 + "/r17_admission_issued.jsonl") == "956178b282e42ae73be1cdd3ade0772af53cf7eb2682fe8b9d02a20411fdcb6f", "")
check("S8.P1_singles", sha(P1 + "/environment.yml") == "e7a0850eb6c965a6f4dc6389802a0b388f2424eec6b80d7e62077197549f8899" and sha(P1 + "/requirements-lock.txt") == "4e727d3daed162cec3a47ee8d6d8602e44bf8f19a5d99032d51cfe3957c4d99b", "")
# rehearsal inventory sampling: verify sampled dirs are dummy-sha refusal negatives
inv = []
invp = Path(EV) / "w1_audit/rehearsal_inventory_20261010.txt"
for ln in invp.read_text(encoding="utf-8", errors="replace").splitlines():
    ln = ln.strip()
    if "::" in ln and ln[:4] == "2026":
        inv.append(ln.split("::")[0].strip())
info("S8.inventory_dirs", len(inv))
sample = inv[:2] + inv[len(inv)//2:len(inv)//2+1] + inv[-2:]
bad = []
for d in sample:
    full = Path(P1) / "r17_rt_runs" / d
    if not full.is_dir():
        bad.append(d + ":missing")
        continue
    errs = list(full.rglob("*.err")) + list(full.rglob("audit.err"))
    txt = ""
    for e in errs:
        try:
            txt += e.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    if "code_freeze_sha" not in txt and "repo HEAD" not in txt:
        bad.append(d + ":no_refusal_text")
check("S8.rehearsal_negatives", not bad and len(sample) == 5, bad)
runs = sorted((Path(P1) / "r17_rt_runs").glob("2026100[56]*")) if (Path(P1) / "r17_rt_runs").exists() else []
info("S8.rt_runs_count", len(runs))
# new files in old P2/D2 after 2026-10-05 12:00Z (should be none)
def newer_than(root, ts):
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in EXCL]
        for fn in fns:
            fp = os.path.join(dp, fn)
            try:
                if os.path.getmtime(fp) > ts:
                    out.append(fp)
            except OSError:
                pass
    return out
cutoff = time.mktime(time.strptime("2026-10-05 12:00:00", "%Y-%m-%d %H:%M:%S"))
n2 = newer_than(P2, cutoff)
n2d = newer_than(D2, cutoff)
check("S8.P2_D2_no_new_files", not n2 and not n2d, str(n2[:3]) + str(n2d[:3]))

print("== S9 D3 config absent / authority+state fresh / E1 boundary ==")
check("S9.D3_config_absent", not os.path.exists(D3 + "/qprod_deploy_config.json"), "")
for rel in ("authority", "artifacts/route_c_stage2_6_1_repair17/state", "artifacts/formal_a_qaf_v3/.r17_formal_provenance.json"):
    info("S9.D3_" + rel.replace("/", "_"), os.path.exists(D3 + "/" + rel))
check("S9.roots_distinct", len({P3, D3, PIN, P2, D2, P1}) == 6, "")

print("== S10 evidence log uniqueness (logs_20261010) ==")
logdir = Path(EV) / "runtime_verify/logs_20261010"
logs = sorted(logdir.glob("*.log")) if logdir.is_dir() else []
sizes = {l.name: l.stat().st_size for l in logs}
info("S10.logs", json.dumps(sizes))
check("S10.four_distinct_logs", len(logs) == 4 and len(set(sizes.values())) == 4, str(len(logs)))

print("== S11 live runtime_dependency_preflight (positive) ==")
sys.path.insert(0, P3 + "/src")
try:
    from rl_curriculum.curriculum261_qaf_provenance_guard import runtime_dependency_preflight
    rd = runtime_dependency_preflight(repo=Path(REPO), project_dir=Path(P3), candidate_sha=A)
    check("S11.preflight_ok", rd.get("ok") is True, json.dumps(rd.get("problems", rd))[:300])
    check("S11.preflight_pin_head", rd.get("repo_root") == PIN and rd.get("repo_head_commit") == A, str(rd.get("repo_root")) + " " + str(rd.get("repo_head_commit"))[:12])
except Exception as exc:
    check("S11.preflight_ok", False, repr(exc)[:300])

print("== S12 live preissue_gate E1-absent fail-closed ==")
try:
    from rl_curriculum.curriculum261_qaf_provenance_guard import preissue_gate
    g = preissue_gate(repo=Path(REPO), deploy_root=Path(D3), project_dir=Path(P3),
                      attempt="qaf_v3", candidate_sha=A,
                      report_out=OUT / "gate_refused_rcw.json")
    check("S12.gate_refused", g.get("ok") is False, str(g.get("refusal"))[:200])
    check("S12.zero_writes", g.get("one_shot_writes") == 0 and g.get("business_leaf_calls") == 0, "")
    check("S12.deploy_roots_fail", g.get("checks", {}).get("deploy_roots", {}).get("ok") is False, "")
except Exception as exc:
    check("S12.gate_refused", False, repr(exc)[:300])

print("== SUMMARY pass=%d fail=%d info=%d ==" % (R["pass"], R["fail"], R["info"]))
