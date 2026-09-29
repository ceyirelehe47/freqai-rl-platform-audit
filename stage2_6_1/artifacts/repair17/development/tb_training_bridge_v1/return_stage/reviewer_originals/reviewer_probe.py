#!/usr/bin/env python
"""Reviewer independent probe - RouteC TrainingBridge v1 content acceptance.
All writes go to isolated work dir; shared quota ledger untouched here.
Zero native generation, zero optimizer steps in this script.
"""
import hashlib, json, shutil, sys
from pathlib import Path

import numpy as np

ROOT = Path('/mnt/f/trading/tmp_reviewer_tb_v1/work')
if ROOT.exists():
    shutil.rmtree(ROOT)
ROOT.mkdir(parents=True)

RESULTS = []
def check(name, cond, detail=''):
    RESULTS.append((name, bool(cond)))
    print(('PASS' if cond else 'FAIL'), '|', name, ('| ' + str(detail)) if detail else '')

# ---------- independent digest reimplementations (no rl_curriculum import) ----------
def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, default=str)
def sha(t):
    return hashlib.sha256(t.encode('utf-8')).hexdigest()

ART = Path('/mnt/f/trading/freqai-rl-audit/stage2_6_2/artifacts/eng_training_bridge_v1')

# A. committed fixture artifact digest recomputation (byte-level, independent)
plan = json.loads((ART/'qualified_input_v1_r2_reference/qualification_plan.json').read_text(encoding='utf-8'))
locked = (ART/'qualified_input_v1_r2_reference/qualification_plan_digest.txt').read_text().strip()
my_digest = 'qp262e-' + sha(canon(plan))
check('A1 committed plan digest recomputed independently', my_digest == locked, my_digest[:20])

pack = json.loads((ART/'qualified_input_v1_r2_reference/parameter_pack.json').read_text(encoding='utf-8'))
payload = {k: v for k, v in pack.items() if k not in ('digest', 'created_utc')}
my_pack = 'e262pk-' + sha(canon(payload))
check('A2 committed pack digest recomputed independently', my_pack == pack['digest'], my_pack[:20])

auth = json.loads((ART/'eng_authorization_v1_r2_reference.json').read_text(encoding='utf-8'))
b = auth['bindings']
bind_payload = {k: b[k] for k in ('qualification_plan_digest','parameter_pack_digest','preprocessor_bundle_hash')}
bind_payload['profile'] = auth['profile']; bind_payload['scope'] = auth['scope']
my_bind = 'e262az-' + sha(canon(bind_payload))
check('A3 committed authorization binding digest recomputed independently',
      my_bind == auth['binding_digest'], my_bind[:20])
check('A4 authorization file outside qualification dir',
      not Path(auth and ART/'qualified_input_v1_r2_reference' ).resolve() in Path(ART/'eng_authorization_v1_r2_reference.json').resolve().parents,
      'auth is sibling not member')

# committed model zip sha
model_zip = ART/'eng_ppo_smoke_256.zip'
msha = hashlib.sha256(model_zip.read_bytes()).hexdigest()
manifest = json.loads((ART/'eng_ppo_smoke_256.manifest.json').read_text(encoding='utf-8'))
check('A5 committed checkpoint sha256 matches manifest binding',
      msha == manifest['model_sha256'] == '11bc9a9991bc197bd6570607f8efb184436d2e05da4d21a1f0a39a0f382fbe57', msha[:16])
check('A6 manifest engineering_only + binds committed input identities',
      manifest['engineering_only'] is True
      and manifest['qualified_input']['qualification_plan_digest'] == locked
      and manifest['qualified_input']['parameter_pack_digest'] == pack['digest']
      and manifest['qualified_input']['profile'] == 'ppo262_engineering_v1')

probe = json.loads((ART/'eng_frozen_probe.json').read_text(encoding='utf-8'))
obs = probe['observations_float32']
check('A7 committed frozen probe shape/semantics',
      probe['steps'] == 32 and len(obs) == 32 and all(len(o) == 9 for o in obs)
      and all(p[0] + p[1] > 0.99 for p in probe['action_probabilities'])
      and set(probe['deterministic_actions']) <= {0, 1}
      and probe['bundle_hash'] == 'r4pb-26382fb105fcfcf958f333d044cddac97c14cd3c14a7c3c84a83b94cfd726d55')
check('A8 probe collection declared as post-training frozen forward',
      '保存时前向' in probe['collection_semantics'] and probe['reset_seed'] == 262502)

# ---------- now with real modules ----------
from rl_curriculum.ppo262_qualified_input import (
    FORMAL_ADMISSION_REGISTRY, QualifiedInputError, load_qualified_input)
from rl_curriculum.ppo262_eng_fixture import build_eng_fixture

fx1 = build_eng_fixture(ROOT/'fx1', variant='v1_r2_reference', verbose=False)
fx2 = build_eng_fixture(ROOT/'fx2', variant='v2_perturbed', verbose=False)

def load(out, scope='engineering', **kw):
    return load_qualified_input(out['qualification_dir'],
        authorization_path=out['authorization_path'], expected_scope=scope, **kw)
def rej(out, scope='engineering', **kw):
    try:
        load(out, scope, **kw)
        return None
    except QualifiedInputError as e:
        return e.report

# B. positive: my own built fixtures load (not reusing committed bytes)
qi1 = load(fx1); qi2 = load(fx2)
check('B1 own-built v1 fixture loads, digest matches builder output',
      qi1.plan_digest == fx1['qualification_plan_digest'])
check('B2 two legal packs distinct at pack level (K01 contrast base)',
      qi1.pack_digest != qi2.pack_digest
      and qi2.rung_params()['c1_opportunity']['D1']['opp_drift_bps'] == 45.0
      and qi1.rung_params()['c1_opportunity']['D1']['opp_drift_bps'] == 42.0)

# B3: builder output == committed artifact bytes (byte-deterministic rebuild)
same = all((ROOT/'fx1'/'qualified_input_v1_r2_reference'/f).read_bytes()
           == (ART/'qualified_input_v1_r2_reference'/f).read_bytes()
           for f in ('qualification_plan.json','qualification_plan_digest.txt',
                     'qualification_result.json','qualification_exposure.json',
                     'parameter_pack.json','preprocessor_envelope.json'))
check('B3 fixture builder byte-deterministic vs committed artifacts', same)

# C. negative: non-PASS verdict (I02)
mut = ROOT/'mut_nonpass'; shutil.copytree(fx1['qualification_dir'], mut)
r = json.loads((mut/'qualification_result.json').read_text()); r['verdict'] = 'FAIL'
(mut/'qualification_result.json').write_text(json.dumps(r))
rep = rej({'qualification_dir': mut, 'authorization_path': fx1['authorization_path']})
check('C1 non-PASS result rejected', rep is not None and any('verdict' in p for p in rep['problems']))

# C2: plan tampered + digest file recomputed to match (self-consistent forgery)
mut2 = ROOT/'mut_plan'; shutil.copytree(fx1['qualification_dir'], mut2)
p2 = json.loads((mut2/'qualification_plan.json').read_text())
p2['robustness_gate']['pass'] = False  # any content change
(mut2/'qualification_plan.json').write_text(json.dumps(p2, indent=2, ensure_ascii=False, sort_keys=True))
(mut2/'qualification_plan_digest.txt').write_text('qp262e-' + sha(canon(p2)) + '\n')
rep2 = rej({'qualification_dir': mut2, 'authorization_path': fx1['authorization_path']})
check('C2 recomputed-digest self-consistent plan forgery still rejected (result no longer binds plan)',
      rep2 is not None and any('result 未绑定 plan digest' in p for p in rep2['problems']))

# C3: exposure not terminal (I02)
mut3 = ROOT/'mut_expo'; shutil.copytree(fx1['qualification_dir'], mut3)
e3 = json.loads((mut3/'qualification_exposure.json').read_text()); e3['status'] = 'running'
(mut3/'qualification_exposure.json').write_text(json.dumps(e3))
rep3 = rej({'qualification_dir': mut3, 'authorization_path': fx1['authorization_path']})
check('C3 non-completed exposure rejected', rep3 is not None and any('exposure' in p for p in rep3['problems']))

# C4: self-authorization (auth inside qual dir)
inside = Path(fx1['qualification_dir'])/'auth_inside.json'
shutil.copyfile(fx1['authorization_path'], inside)
rep4 = rej(fx1['qualification_dir'] and {'qualification_dir': fx1['qualification_dir'], 'authorization_path': inside})
check('C4 authorization inside qual dir rejected (self-authorization)',
      rep4 is not None and any('自授权' in p for p in rep4['problems']))

# C5: missing authorization file
rep5 = rej({'qualification_dir': fx1['qualification_dir'], 'authorization_path': ROOT/'nope.json'})
check('C5 missing authorization rejected', rep5 is not None and any('授权' in p for p in rep5['problems']))

# C6: forged formal authorization with fully recomputed digests (G01)
from rl_curriculum.ppo262_qualified_input import (
    authorization_binding_digest, parameter_pack_digest)
mut6 = ROOT/'mut_formal'; shutil.copytree(fx1['qualification_dir'], mut6)
p6 = json.loads((mut6/'qualification_plan.json').read_text()); p6['scope'] = 'formal'
(mut6/'qualification_plan.json').write_text(json.dumps(p6, indent=2, ensure_ascii=False, sort_keys=True))
(mut6/'qualification_plan_digest.txt').write_text('qp262e-' + sha(canon(p6)) + '\n')
pk6 = json.loads((mut6/'parameter_pack.json').read_text())
b6 = {'qualification_plan_digest': 'qp262e-' + sha(canon(p6)),
      'parameter_pack_digest': parameter_pack_digest(pk6),
      'preprocessor_bundle_hash': qi1.bundle_hash}
forged = {'format': 'ppo262e-training-authorization-v1', 'profile': 'ppo262_engineering_v1',
          'scope': 'formal', 'bindings': b6,
          'binding_digest': authorization_binding_digest({**b6, 'profile': 'ppo262_engineering_v1', 'scope': 'formal'}),
          'admission_anchor': {'file': 'forged_admission.json', 'sha256': '0'*64}}
(ROOT/'forged_auth.json').write_text(json.dumps(forged))
rep6 = rej({'qualification_dir': mut6, 'authorization_path': ROOT/'forged_auth.json'}, scope='formal')
check('C6 forged formal auth (recomputed digests) rejected via empty registry',
      rep6 is not None and any('admission' in p for p in rep6['problems'])
      and FORMAL_ADMISSION_REGISTRY == {})
check('C7 engineering fixture with scope=formal rejected', rej(fx1, scope='formal') is not None)

# C8: same-byte relocation accepted; replaced pack rejected after validation (I03)
rel = ROOT/'relocated'; shutil.copytree(fx1['qualification_dir'], rel)
rel_auth = ROOT/'rel_auth.json'; shutil.copyfile(fx1['authorization_path'], rel_auth)
qi_rel = load_qualified_input(rel, authorization_path=rel_auth, expected_scope='engineering')
check('C8 same-byte relocation loads (identity by digest not path)',
      qi_rel.plan_digest == fx1['qualification_plan_digest'])
before = qi_rel.rung_params()['c1_opportunity']['D1']['opp_drift_bps']
v2pack = json.loads((Path(fx2['qualification_dir'])/'parameter_pack.json').read_text())
(rel/'parameter_pack.json').write_text(json.dumps(v2pack, indent=2, ensure_ascii=False, sort_keys=True))
rep8 = rej({'qualification_dir': rel, 'authorization_path': rel_auth})
check('C9 pack replaced after validation -> reload rejects, snapshot stable',
      rep8 is not None and any('pack digest' in p for p in rep8['problems'])
      and qi_rel.rung_params()['c1_opportunity']['D1']['opp_drift_bps'] == before)

print('PART1_DONE', sum(1 for _, ok in RESULTS if ok), '/', len(RESULTS))
