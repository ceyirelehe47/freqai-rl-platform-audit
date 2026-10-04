# RCF-02 independent state-matrix probe (own construction)
import hashlib, json, os, shutil, subprocess, sys
from pathlib import Path

TREE = Path('/home/cryptorl/rcf_review/tree')
PROBE = Path('/home/cryptorl/rcf_review/probe/B')
REPO = Path('/mnt/f/trading/freqai-rl-audit')
RUNNER = TREE / 'stage2_6_1_runner'
PY = sys.executable
sys.path.insert(0, str(TREE / 'src'))
sys.path.insert(0, str(TREE / 'tests' / 'route_c_stage2_6_1'))
ITER = 'qprod_a_formal_v2'
out = {}

def sha(p):
    p = Path(p)
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else None

def snapfiles(root):
    root = Path(root); s = {}
    if not root.exists(): return s
    for p in sorted(root.rglob('*')):
        if p.is_file() and not p.is_symlink():
            s[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return s

def make_domain(base):
    from r17_admission_substance_test_support import (
        git_repo_with_candidate, sync_deploy_surface, run_executor, record_path)
    from rl_curriculum.curriculum261_qaf_provenance_guard import (
        install_to_target, read_pinned_source)
    base.mkdir(parents=True, exist_ok=True)
    repo, commit_a, parent = git_repo_with_candidate(base)
    deploy = base / 'deploy'
    sync_deploy_surface(repo, commit_a, deploy)
    run_dir, summary, rc = run_executor(base / 'run', repo, commit_a, deploy,
                                        expect_rc=(0,))
    assert rc == 0 and summary.get('ok'), (rc, summary)
    state = deploy / 'artifacts/route_c_stage2_6_1_repair17/state'
    art = deploy / 'artifacts/formal_a_qaf_v2'
    auth = deploy / 'authority'
    (deploy / 'qprod_deploy_config.json').write_text(json.dumps({
        "format": "cur261-qprod-deploy-config-v1", "mode": "formal_ready",
        "formal_roots": {ITER: {"artifact_root": str(art),
                                "state_root": str(state),
                                "authority_dir": str(auth)}}},
        ensure_ascii=False, indent=1), encoding='utf-8')
    res = install_to_target(art, read_pinned_source(REPO))
    assert res['post']['ready'], res
    tree = subprocess.run(['git', '-C', str(repo), 'rev-parse',
                           commit_a + '^{tree}'], capture_output=True,
                          text=True, check=True).stdout.strip()
    return dict(base=base, repo=repo, commit_a=commit_a, deploy=deploy,
                state=state, art=art, authority=auth,
                record=record_path(run_dir), tree=tree)

def make_approval(d, path):
    from rl_curriculum.curriculum261_qprod_formal import formal_approval_digest
    from rl_curriculum.curriculum261_qprod_coordinate import (
        qprod_coordinate_code_identity)
    from rl_curriculum.curriculum261_qprod_formal_levela import (
        build_formal_level_a_plan)
    from rl_curriculum.curriculum261_qprod_plan import research_plan_digest
    from rl_curriculum.curriculum261_qaf_attempt import QAF_V2_FAMILY
    payload = build_formal_level_a_plan(
        code_freeze_sha=d['commit_a'],
        code_identity=qprod_coordinate_code_identity(),
        authorized_stop_after="verify-formal-logs",
        model_update_authorized=True, formal_attempt="qaf_v2")
    digest = research_plan_digest(payload)
    approval = {
        "format": "cur261-qprod-formal-approval-v1",
        "approval_id": "probe-approval",
        "task_level": "level_a",
        "iteration_id": ITER,
        "approved": {
            "research_plan_digest": digest,
            "code_freeze_sha": d['commit_a'],
            "artifact_root": str(d['art']),
            "state_root": str(d['state']),
            "authority_dir": str(d['authority']),
            "namespaces": list(QAF_V2_FAMILY.input_scope),
            "coordinate_ids": [],
            "quota": dict(payload["quota"]),
            "authorized_stop_after": "verify-formal-logs",
            "model_update_authorized": True,
        },
        "approval_source": {
            "kind": "user_direct_approval",
            "statement_digest": "probe-review-only-not-a-real-approval",
            "note": "PROBE ONLY (isolated dir; not a production input)",
        },
    }
    approval["approval_digest"] = formal_approval_digest(approval)
    path.write_text(json.dumps(approval, ensure_ascii=False, indent=1),
                    encoding='utf-8')
    return path

def execute(d, approval, evidence, *, admission_id='probe-adm',
            leaf_sentinel=None, test_domain=True, timeout=900, child_timeout=None):
    argv = [PY, str(RUNNER / 'qaf_v2_operator_entry.py'), 'execute',
            '--repo', str(d['repo']), '--guard-repo', str(REPO),
            '--deploy-root', str(d['deploy']), '--project-dir', str(TREE),
            '--approval-json', str(approval),
            '--regression-evidence', str(evidence),
            '--admission-id', admission_id,
            '--authorization', 'probe:RCF02-state-matrix',
            '--plan-digest', d['tree'],
            '--plan-digest-method', 'git_tree_digest',
            '--code-freeze-sha', d['commit_a'],
            '--stop-after', 'verify-formal-logs', '--model-update',
            '--attempt', 'qaf_v2']
    if test_domain: argv.append('--test-domain')
    if leaf_sentinel: argv += ['--leaf-sentinel', leaf_sentinel]
    if child_timeout: argv += ['--child-timeout', str(child_timeout)]
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env['R17_RELEASE_REPO'] = str(d['repo'])
    return subprocess.run(argv, capture_output=True, text=True, env=env,
                          timeout=timeout)

def lastjson(text):
    for chunk in reversed([c for c in text.split('\n\n') if c.strip()]):
        try: return json.loads(chunk)
        except Exception: continue
    return {}

PERMIT = f"qprod_permit_level_a_{ITER}.json"
APPROVAL = f"qprod_formal_approval_level_a_{ITER}.json"

shutil.rmtree(PROBE, ignore_errors=True)

# ---------------- B1: stored approval mismatch, zero write ----------------
d1 = make_domain(PROBE / 'b1')
ap1 = make_approval(d1, d1['base'] / 'approval.json')
old = json.loads(ap1.read_text(encoding='utf-8'))
old['approved']['code_freeze_sha'] = '0' * 40
from rl_curriculum.curriculum261_qprod_formal import formal_approval_digest
old.pop('approval_digest'); old['approval_digest'] = formal_approval_digest(old)
d1['authority'].mkdir(parents=True, exist_ok=True)
(d1['authority'] / APPROVAL).write_text(json.dumps(old, ensure_ascii=False),
                                        encoding='utf-8')
before = snapfiles(d1['authority'])
r = execute(d1, ap1, d1['record'])
out['B1'] = {'rc': r.returncode,
             'digest_refusal': ('不一致' in r.stdout),
             'authority_unchanged': snapfiles(d1['authority']) == before,
             'no_permit': not (d1['authority'] / PERMIT).exists(),
             'no_admission': not (d1['deploy'] / '.r17_formal_admission.json').exists(),
             'stdout_last': lastjson(r.stdout).get('refused', r.stdout[-200:])}

# ---------------- B2: evidence preflight variants (no write) ----------------
d2 = make_domain(PROBE / 'b2')
ap2 = make_approval(d2, d2['base'] / 'approval.json')
rec = json.loads(Path(d2['record']).read_text(encoding='utf-8'))
variants = {}
variants['missing'] = d2['base'] / 'nope.json'
w = dict(rec); w['commit_a_sha'] = '1' * 40
p = d2['base'] / 'wrong_commit.json'; p.write_text(json.dumps(w), encoding='utf-8')
variants['wrong_commit'] = p
c = json.loads(json.dumps(rec)); c['counts'] = dict(c['counts']); c['counts']['failures'] = 1
p = d2['base'] / 'counts_fail.json'; p.write_text(json.dumps(c), encoding='utf-8')
variants['counts_fail'] = p
f = json.loads(json.dumps(rec)); f['format'] = 'cur261-r17-candidate-regression-evidence-v5'
p = d2['base'] / 'fmt_v5.json'; p.write_text(json.dumps(f), encoding='utf-8')
variants['format_v5'] = p
before2 = snapfiles(d2['authority'])
res = {}
for k, v in variants.items():
    rr = execute(d2, ap2, v)
    lj = lastjson(rr.stdout)
    res[k] = {'rc': rr.returncode, 'refused': str(lj.get('refused'))[:110],
              'one_shot_writes': lj.get('one_shot_writes')}
res['authority_unchanged'] = snapfiles(d2['authority']) == before2
res['no_permit'] = not (d2['authority'] / PERMIT).exists()
out['B2'] = res

# ---------------- B3: existing (real) permit -> rc4, zero new write ----------------
d3 = make_domain(PROBE / 'b3')
ap3 = make_approval(d3, d3['base'] / 'approval.json')
steps = [['init', '--dir', str(d3['authority'])],
         ['record-approval', '--dir', str(d3['authority']),
          '--approval-json', str(ap3)],
         ['issue-permit', '--dir', str(d3['authority']),
          '--deploy-root', str(d3['deploy']), '--task-level', 'level_a',
          '--attempt', 'qaf_v2', '--repo', str(REPO),
          '--project-dir', str(TREE)]]
for s in steps:
    rr = subprocess.run([PY, str(RUNNER / 'qprod_formal_authority.py')] + s,
                        capture_output=True, text=True)
    assert rr.returncode == 0, (s, rr.stdout, rr.stderr)
before3 = snapfiles(d3['authority'])
r3 = execute(d3, ap3, d3['record'])
out['B3'] = {'rc': r3.returncode,
             'refused': str(lastjson(r3.stdout).get('refused'))[:110],
             'authority_unchanged': snapfiles(d3['authority']) == before3,
             'permit_sha': sha(d3['authority'] / PERMIT),
             'json_writes': lastjson(r3.stdout).get('one_shot_writes')}

# ---------------- B4: admission present only -> rc4, no permit ----------------
d4 = make_domain(PROBE / 'b4')
ap4 = make_approval(d4, d4['base'] / 'approval.json')
(d4['deploy'] / '.r17_formal_admission.json').write_text(json.dumps(
    {"format": "cur261-r17-formal-admission-v2", "commit_a_sha": d4['commit_a'],
     "admission_id": "probe-prior", "deployed_state_root": str(d4['state'])}),
    encoding='utf-8')
before4 = snapfiles(d4['authority'])
r4 = execute(d4, ap4, d4['record'])
out['B4'] = {'rc': r4.returncode,
             'refused': str(lastjson(r4.stdout).get('refused'))[:110],
             'authority_unchanged': snapfiles(d4['authority']) == before4,
             'no_permit': not (d4['authority'] / PERMIT).exists(),
             'json_writes': lastjson(r4.stdout).get('one_shot_writes')}

# ---------------- B5: REAL issuance log at deploy root, no admission file ----------------
d5 = make_domain(PROBE / 'b5')
ap5 = make_approval(d5, d5['base'] / 'approval.json')
log = d5['deploy'] / 'r17_admission_issued.jsonl'
log.write_text(json.dumps({"admission_id": "prior-issued-id",
                           "commit_a_sha": d5['commit_a'],
                           "issued_utc": "2026-01-01T00:00:00Z",
                           "substance_digest": "r17sub-probe",
                           "preregistration_sha256": "0" * 64}) + '\n',
               encoding='utf-8')
r5 = execute(d5, ap5, d5['record'], admission_id='probe-adm-second',
             leaf_sentinel='determinism-matrix')
lines = [x for x in log.read_text(encoding='utf-8').splitlines() if x.strip()]
ids = [json.loads(x)['admission_id'] for x in lines]
out['B5'] = {'rc': r5.returncode,
             'refused': str(lastjson(r5.stdout).get('refused'))[:110],
             'new_permit_written': (d5['authority'] / PERMIT).is_file(),
             'admission_file_written': (d5['deploy'] / '.r17_formal_admission.json').is_file(),
             'issuance_log_ids_after': ids,
             'leaf_marker': (d5['art'] / 'leaf_sentinel_marker.json').is_file(),
             'chain_result': (json.loads((d5['art'] / 'r17_chain_result.json').read_text(encoding='utf-8'))
                              if (d5['art'] / 'r17_chain_result.json').is_file() else None)}

# ---------------- B6: operator's (non-produced) state-root log path -> rc4 ----------------
d6 = make_domain(PROBE / 'b6')
ap6 = make_approval(d6, d6['base'] / 'approval.json')
d6['state'].mkdir(parents=True, exist_ok=True)
(d6['state'] / 'r17_admission_issuance.log.jsonl').write_text('{"admission_id": "phantom"}\n',
                                                              encoding='utf-8')
before6 = snapfiles(d6['authority'])
r6 = execute(d6, ap6, d6['record'], admission_id='probe-adm-six',
             leaf_sentinel='determinism-matrix')
out['B6'] = {'rc': r6.returncode,
             'refused': str(lastjson(r6.stdout).get('refused'))[:110],
             'no_permit': not (d6['authority'] / PERMIT).exists(),
             'authority_unchanged': snapfiles(d6['authority']) == before6,
             'state_flags': lastjson(r6.stdout).get('state')}

# ---------------- B7: post-permit refusal honesty (one_shot_writes=1) ----------------
d7 = make_domain(PROBE / 'b7')
ap7 = make_approval(d7, d7['base'] / 'approval.json')
cand = sorted((d7['deploy'] / 'src' / 'rl_curriculum').glob('*.py'))
probe_file = cand[0]
orig = probe_file.read_bytes()
try:
    probe_file.write_bytes(orig + b'\n# drift probe\n')
    r7 = execute(d7, ap7, d7['record'], admission_id='probe-adm-seven')
finally:
    probe_file.write_bytes(orig)
lj7 = lastjson(r7.stdout)
out['B7'] = {'rc': r7.returncode, 'refused': str(lj7.get('refused'))[:110],
             'one_shot_writes': lj7.get('one_shot_writes'),
             'permit_written': (d7['authority'] / PERMIT).is_file(),
             'prereg_written': any(d7['authority'].glob('preregistration_*')),
             'no_admission': not (d7['deploy'] / '.r17_formal_admission.json').exists(),
             'deploy_restored': probe_file.read_bytes() == orig}

# ---------------- B8: leaf-sentinel without --test-domain (validation timing) ----------------
d8 = make_domain(PROBE / 'b8')
ap8 = make_approval(d8, d8['base'] / 'approval.json')
before8 = snapfiles(d8['authority'])
r8 = execute(d8, ap8, d8['record'], admission_id='probe-adm-eight',
             leaf_sentinel='determinism-matrix', test_domain=False)
lj8 = lastjson(r8.stdout)
out['B8'] = {'rc': r8.returncode, 'refused': str(lj8.get('refused'))[:130],
             'one_shot_writes': lj8.get('one_shot_writes'),
             'permit_written': (d8['authority'] / PERMIT).is_file(),
             'prereg_written': any(d8['authority'].glob('preregistration_*')),
             'admission_file_written': (d8['deploy'] / '.r17_formal_admission.json').is_file(),
             'authority_before_count': len(before8),
             'authority_after_count': len(snapfiles(d8['authority'])),
             'authority_delta': sorted(set(snapfiles(d8['authority'])) - set(before8))}

print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
