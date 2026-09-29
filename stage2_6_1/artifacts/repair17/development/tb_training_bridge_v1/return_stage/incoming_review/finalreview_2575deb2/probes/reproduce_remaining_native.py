#!/usr/bin/env python3
"""Reproduce the remaining input/legacy-migration issues using real WSL dependencies.
Only edits new isolated copies. Never fit, generate episodes, deserialize models, or learn.
Requires the already installed project and immutable Git candidate objects. Does NOT install.
"""
from __future__ import annotations
import argparse,hashlib,importlib,json,os,shutil,sys
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--project',type=Path,required=True,help='Existing WSL deployed project root')
p.add_argument('--repo',type=Path,required=True,help='Existing repo containing candidate objects (read-only)')
p.add_argument('--return-root',type=Path,required=True,help='Extracted RouteC_QualifiedInput_TrainingBridge_v1_RETURN directory')
p.add_argument('--out',type=Path,required=True,help='New persistent directory, must not exist')
a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
os.environ['PPO262E_REPO_ROOT']=str(a.repo);sys.path.insert(0,str(a.project/'src'))
Q=importlib.import_module('rl_curriculum.ppo262_qualified_input');G=importlib.import_module('rl_curriculum.ppo262_eng_profile')
from stable_baselines3 import PPO
src_hashes={m.__name__:hashlib.sha256(Path(m.__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for m in (Q,G)}
E=a.return_root/'eng_training_bridge_v1'
def write(p,obj):p.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')
def copycase(name):
 root=a.out/name;root.mkdir();qd=root/'qualified';shutil.copytree(E/'qualified_input_v1_r2_reference',qd);auth=root/'auth.json';shutil.copy2(E/'eng_authorization_v1_r2_reference.json',auth);return root,qd,auth
def rebind(qd,auth,mut):
 plan=json.loads((qd/'qualification_plan.json').read_text());mut(plan);write(qd/'qualification_plan.json',plan);pd=Q.qualification_plan_digest(plan);(qd/'qualification_plan_digest.txt').write_text(pd,encoding='utf-8')
 for f in ['qualification_result.json','qualification_exposure.json']:
  x=json.loads((qd/f).read_text());x['plan_digest']=pd;write(qd/f,x)
 x=json.loads(auth.read_text());x['bindings']['qualification_plan_digest']=pd;x['binding_digest']=Q.authorization_binding_digest({**x['bindings'],'profile':x['profile'],'scope':x['scope']});write(auth,x)
results=[]
for name,fn,expected in [('fit_positive',None,False),('fit_namespace_mismatch',lambda p:p['preprocessing'].update(fit_namespace='invented_not_actual_fit'),True),('fit_episode_mismatch',lambda p:p['preprocessing']['fit_fixture_records'][0].update(episode_hash='e262fx-INVENTED'),True)]:
 root,qd,auth=copycase(name)
 if fn:rebind(qd,auth,fn)
 rejected=False;err=''
 try:Q.load_qualified_input(qd,authorization_path=auth,expected_scope='engineering')
 except Q.QualifiedInputError as e:rejected=True;err=str(e)
 results.append({'name':name,'expected_reject':expected,'rejected':rejected,'expectation_met':rejected==expected,'error':err})
class StopBeforeLoad(Exception):pass
original_load=PPO.load
# Sentinel at the ONLY model deserialization call. All preceding native validation remains real.
def sentinel(*args,**kw):raise StopBeforeLoad('PPO.load boundary reached, no deserialization')
PPO.load=staticmethod(sentinel)
try:
 for name,empty,invalid in [('cold_positive',False,False),('cold_empty_identity',True,False),('cold_empty_identity_invalid_commit',True,True)]:
  root,qd,auth=copycase(name);modeldir=root/'model';modeldir.mkdir()
  for f in ['eng_ppo_smoke_256.zip','eng_ppo_smoke_256.manifest.json','eng_ppo_smoke_256.manifest.v2.json','eng_frozen_probe.json','eng_bank_smoke.json','eng_ppo_smoke.json']:
   if (E/f).is_file():shutil.copy2(E/f,modeldir/f)
  mp=modeldir/'eng_ppo_smoke_256.manifest.v2.json'
  if not mp.exists():mp=modeldir/'eng_ppo_smoke_256.manifest.json'
  if empty:
   m=json.loads(mp.read_text());m['code_identity_consumer']={}
   if invalid:m['candidate_commit']='not-a-commit'
   else:m['candidate_commit']=m.get('candidate_commit') or 'e565298dad8063df70775dfdd47e3bf682f29926'
   write(mp,m)
  hit=False;rejected=False;err=''
  try:G.cold_read_checkpoint(qd,auth,modeldir,root/'out',expected_profile='ppo262_engineering_v1')
  except StopBeforeLoad:hit=True
  except Q.QualifiedInputError as e:rejected=True;err=str(e)
  results.append({'name':name,'expected_reject':empty,'rejected':rejected,'model_load_reached':hit,'expectation_met':rejected if empty else hit,'error':err})
finally:PPO.load=original_load
report={'source_sha256':src_hashes,'cases':results,'native_generation':0,'fit':0,'optimizer_updates':0,'models_deserialized':0,'pass':all(r['expectation_met'] for r in results)}
write(a.out/'RESULT.json',report);print(json.dumps(report,indent=2,ensure_ascii=False));sys.exit(0 if report['pass'] else 1)
