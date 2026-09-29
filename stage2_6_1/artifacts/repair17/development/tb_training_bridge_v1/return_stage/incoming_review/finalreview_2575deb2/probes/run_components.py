#!/usr/bin/env python3
"""Independent, zero-generation/zero-update component review of full C5 modules.
External missing WSL dependencies are recorded-valid capsules, NOT native V2/SB3.
All candidate module files and target decision functions remain unchanged.
Any raw generator or PPO.load is stopped by a sentinel. Synthetic Git repo is local.
"""
from __future__ import annotations
import ast,contextlib,copy,hashlib,importlib.util,io,json,os,shutil,subprocess,sys,types
from pathlib import Path
from datetime import datetime,timezone
B=Path(__file__).resolve().parents[1]
R=B/'received/RouteC_QualifiedInput_TrainingBridge_v1_RETURN'
E=R/'eng_training_bridge_v1'; SRC=R/'return_stage/candidate_source/src/rl_curriculum'
W=B/'probes'/('cases_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'));W.mkdir()
plan0=json.loads((E/'qualified_input_v1_r2_reference/qualification_plan.json').read_text())
pack0=json.loads((E/'qualified_input_v1_r2_reference/parameter_pack.json').read_text())
manifest0=json.loads((E/'eng_ppo_smoke_256.manifest.json').read_text())
def mod(name,**kw):
 m=types.ModuleType(name);m.__dict__.update(kw);sys.modules[name]=m;return m
def load(name):
 s=importlib.util.spec_from_file_location('rl_curriculum.'+name,SRC/(name+'.py'));m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);return m
mod('rl_curriculum',__path__=[str(SRC)],__file__=str(SRC/'__init__.py'))
fams=tuple(pack0['families']);rungs=('D0','D1','D2','D3')
class NeverGenerate(Exception):pass
class DummyGenerator:
 def __init__(self,f):self.family_version=plan0['code_identity']['family_versions'][f]
 def base_params(self,p,s):return {**p,'episode_bars':288,'initial_price':1.,'pair_variant':s}
 def generate(self,*a,**k):raise NeverGenerate('Native generator disabled: no generation performed')
specs={f:types.SimpleNamespace(generator=DummyGenerator(f)) for f in fams}
mod('rl_curriculum.curriculum261_api',CURRICULUM261_FAMILIES=fams,CURRICULUM261_RUNGS=rungs,CURRICULUM261_SEED_NAMESPACES=('qualification_r2',),CURRICULUM261_TIMEFRAME='15m',CURRICULUM261_EPISODE_BARS=288,CURRICULUM261_INITIAL_PRICE=1.,CURRICULUM261_PAIR_VARIANT_KEY='pair_variant',AttemptRecord=object,EpisodeAttemptLog=object,PairGenerationError=RuntimeError,check_attempt_log=lambda *a:None,episode_content_hash=lambda *a:'NOT_USED',qualification_r2_lock_marker=lambda:W/'legacy_R2'/'qualification_plan.json')
mod('rl_curriculum.curriculum261_pairs',family_specs=lambda:specs,FamilySpec=object,compute_pair_integrity=lambda *a:None,pair_structural_contract=lambda *a:())
mod('rl_curriculum.generator_api',GeneratedEpisode=object,GeneratorError=RuntimeError)
mod('rl_curriculum.curriculum261_production_obs',production_observation_identity=lambda:copy.deepcopy(plan0['code_identity']['production_observation_identity']),PRODUCTION_FEATURE_COLUMNS=tuple(plan0['code_identity']['production_observation_identity']['feature_columns']))
vsha=plan0['code_identity']['vendor_sha'];mod('rl_curriculum.ppo262_input_lock',PPO262_EXPECTED_VENDOR_SHA=vsha,vendor_status=lambda:{'sha':vsha,'clean':True})
env0=json.loads((E/'qualified_input_v1_r2_reference/preprocessor_envelope.json').read_text()); envsha=hashlib.sha256((E/'qualified_input_v1_r2_reference/preprocessor_envelope.json').read_bytes()).hexdigest()
class FrozenEnvelopeCapsule:
 @classmethod
 def load_envelope(cls,p):
  if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=envsha:raise RuntimeError('Capsule rejects changed envelope; not a V2 numerical rerun')
  return types.SimpleNamespace(bundle_hash=plan0['preprocessor_bundle_hash'],namespace=env0['namespace'],fit_manifest=copy.deepcopy(env0['fit_manifest']))
mod('rl_curriculum.curriculum261_r4_preprocessing',RouteCPreprocessorV2=FrozenEnvelopeCapsule,preprocessing_v2_contract_digest=lambda:plan0['code_identity']['preprocessing_v2_contract_digest'])
Q=load('ppo262_qualified_input');N=load('ppo262_namespaces');BK=load('ppo262_banks');G=load('ppo262_eng_profile')
cfg={}
for filename in ['ppo262_cli.py','ppo262_entry_specs.py']:
 for node in ast.parse((SRC/filename).read_text()).body:
  if isinstance(node,ast.ImportFrom) and node.module=='rl_curriculum.ppo262_config':
   for n in node.names:cfg[n.name]={}
# Small isolated planning counts; no budget or scientific quantities are inferred.
cfg.update(PPO262_CONFIG_DEV_FAMILIES=fams,PPO262_CONFIG_DEV_RUNG='D1',PPO262_CONFIG_DEV_EPISODES_PER_FAMILY=2,PPO262_CONFIG_DEV_EVAL_PAIRS_PER_FAMILY=1,PPO262_CONFIG_DEV_EVAL_PAIR_BASE=100,PPO262_CONFIG_DEV_TRAIN_PAIR_BASE=200,PPO262_PROBE_BUDGETS={f:{r:2 for r in rungs} for f in fams},PPO262_DEV_EVAL_PAIRS_PER_RUNG=1,PPO262_FINAL_EVAL_PAIRS_PER_RUNG=1)
mod('rl_curriculum.ppo262_config',**cfg)
mod('rl_curriculum.curriculum261_plan',load_locked_plan=lambda _:({'families':copy.deepcopy(pack0['families'])},'R2-recorded-valid-dependency'))
C=load('ppo262_cli');ES=load('ppo262_entry_specs')
results=[]
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def record(name,ok,**kw):results.append({'name':name,'expectation_met':bool(ok),**kw});print(name,'PASS_EXPECTATION' if ok else 'COUNTEREXAMPLE',flush=True)
def case(name,variant='v1_r2_reference'):
 root=W/name;root.mkdir();qd=root/'qualified';shutil.copytree(E/('qualified_input_'+variant),qd);auth=root/'auth.json';shutil.copy2(E/('eng_authorization_'+variant+'.json'),auth);return root,qd,auth
def change(qd,filename,fn):
 p=qd/filename;x=json.loads(p.read_text());fn(x);dump(p,x)
def rebind(qd,auth):
 plan=json.loads((qd/'qualification_plan.json').read_text());pd=Q.qualification_plan_digest(plan);(qd/'qualification_plan_digest.txt').write_text(pd)
 for f in ['qualification_result.json','qualification_exposure.json']:change(qd,f,lambda x:x.update(plan_digest=pd))
 a=json.loads(auth.read_text());a['bindings']['qualification_plan_digest']=pd;a['binding_digest']=Q.authorization_binding_digest({**a['bindings'],'profile':a['profile'],'scope':a['scope']});dump(auth,a)
def inp(name,fn=None,expected=False,scope='engineering'):
 root,qd,auth=case(name)
 if fn:fn(qd,auth)
 rejected=False;why=[]
 try:qi=Q.load_qualified_input(qd,authorization_path=auth,expected_scope=scope)
 except Q.QualifiedInputError as e:rejected=True;why=e.report.get('problems')
 record(name,rejected==expected,rejected=rejected,expected_reject=expected,problems=why)
 return root,qd,auth
inp('input_good')
inp('wrong_plan_digest',lambda d,a:change(d,'qualification_result.json',lambda x:x.update(plan_digest='WRONG')),True)
inp('source_iteration_mismatch',lambda d,a:change(d,'qualification_result.json',lambda x:x.update(source_iteration='OTHER')),True)
inp('exposure_iteration_mismatch',lambda d,a:change(d,'qualification_exposure.json',lambda x:x.update(iteration='OTHER')),True)
def nopro(d,a):change(d,'qualification_plan.json',lambda x:x['code_identity'].pop('producer',None));rebind(d,a)
inp('missing_producer',nopro,True)
def overlap(d,a):change(d,'qualification_plan.json',lambda x:x['preprocessing'].update(fit_namespace='ppo_eng_bank_262e'));rebind(d,a)
inp('fit_training_namespace_overlap',overlap,True)
inp('formal_reject',expected=True,scope='formal')
inp('changed_envelope',lambda d,a:change(d,'preprocessor_envelope.json',lambda x:x['hashes'].update(preprocessor_bundle_hash='WRONG')),True)
def badfit(d,a):change(d,'qualification_plan.json',lambda x:x['preprocessing'].update(fit_namespace='invented_not_the_actual_envelope'));rebind(d,a)
inp('fit_source_namespace_mismatch',badfit,True)
# Same approved envelope, incorrect data-source records in plan, consistent outer hashes.
def badfitrecords(d,a):change(d,'qualification_plan.json',lambda x:x['preprocessing']['fit_fixture_records'][0].update(episode_hash='e262fx-INVENTED'));rebind(d,a)
inp('fit_source_episode_mismatch',badfitrecords,True)
class BoundaryReached(Exception):pass
for name,kind in [('bank_good','none'),('bank_copy_mutation','copy'),('bank_cache_mutation','backing')]:
 root,qd,auth=case(name,'v2_perturbed');qi=Q.load_qualified_input(qd,authorization_path=auth,expected_scope='engineering');val=qi.rung_params()['c1_opportunity']['D1']['opp_drift_bps'];seen={};ledger=G.QuotaLedger(root/'test_ledger.jsonl')
 if kind=='copy':qi.rung_params()['c1_opportunity']['D1']['opp_drift_bps']=999.
 if kind=='backing':qi._pack['families']['c1_opportunity']['rung_params']['D1']['opp_drift_bps']=999.
 def recorder(f,r,s,p):seen['param']=p['opp_drift_bps'];raise BoundaryReached()
 rejected=False
 try:G.generate_eng_bank(qi,ledger,param_recorder=recorder)
 except BoundaryReached:pass
 except Q.QualifiedInputError:rejected=True
 record(name,rejected if kind=='backing' else seen.get('param')==val,rejected=rejected,param_at_boundary=seen.get('param'),ledger_events=len(ledger.records()),native_generated=0)
root,qd,auth=case('routes','v2_perturbed');qi=Q.load_qualified_input(qd,authorization_path=auth,expected_scope='engineering');art=G.route_profile_inputs(qi);dump(root/'route_result.json',art)
record('six_shared_consumer_boundaries',art.get('pass') is True and all(art['routes'][e]['consumer_boundary_hits']['generate262_bank']>0 for e in art['entry_classes']),entry_classes=art['entry_classes'],boundary_hits={e:art['routes'][e]['consumer_boundary_hits'] for e in art['entry_classes']})
# A real, isolated local repository for archive identity helper tests, no user repo mutation.
repo=W/'archive_repo';repo.mkdir();subprocess.run(['git','init','-q',str(repo)],check=True)
rel=repo/'stage2_6_2/src/rl_curriculum/one.py';rel.parent.mkdir(parents=True);rel.write_text('archive identity fixture\n')
subprocess.run(['git','-C',str(repo),'add','.'],check=True);subprocess.run(['git','-C',str(repo),'-c','user.name=Isolated review','-c','user.email=review@invalid','commit','-qm','synthetic local archive'],check=True)
ref=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip();os.environ['PPO262E_REPO_ROOT']=str(repo)
sha=hashlib.sha256(rel.read_bytes()).hexdigest()
record('archive_helper_good',G._verify_identity_at_commit({'one.py':sha},ref) is True)
record('archive_helper_wrong_sha',G._verify_identity_at_commit({'one.py':'f'*64},ref) is False)
record('archive_helper_empty_map_rejected',G._verify_identity_at_commit({},ref) is False,actual=G._verify_identity_at_commit({},ref))
record('archive_helper_empty_and_invalid_commit_rejected',G._verify_identity_at_commit({},'not-a-commit') is False,actual=G._verify_identity_at_commit({},'not-a-commit'))
# Full cold-read; environment Ct isolated to archived-valid identity, actual helper unchanged.
import torch
class NoLoad(Exception):pass
class SentinelPPO:
 @staticmethod
 def load(*a,**k):raise NoLoad('Reached PPO.load; no model was deserialized or run')
mod('stable_baselines3',PPO=SentinelPPO)
G._consumer_code_identity=lambda:copy.deepcopy(manifest0['code_identity_consumer'])
mutants=[('cold_good',None,False),('cold_wrong_pack',lambda m:m['qualified_input'].update(parameter_pack_digest='WRONG'),True),('cold_wrong_source',lambda m:m['qualified_input'].update(qualification_source_iteration='WRONG'),True),('cold_wrong_bank_seed',lambda m:(m['bank'].update(namespace='WRONG',keys=[],n_episodes=0,manifest_sha256='WRONG'),m['training'].update(model_seed=123,total_timesteps=2048)),True),('cold_missing_auth',lambda m:m['qualified_input'].pop('authorization_binding_digest'),True),('cold_empty_code_identity',lambda m:m.update(code_identity_consumer={},candidate_commit=ref),True),('cold_empty_code_identity_invalid_commit',lambda m:m.update(code_identity_consumer={},candidate_commit='not-a-commit'),True)]
for name,fn,expected in mutants:
 root,qd,auth=case(name);mdir=root/'model';mdir.mkdir()
 for f in ['eng_ppo_smoke_256.zip','eng_frozen_probe.json','eng_bank_smoke.json','eng_ppo_smoke.json']:shutil.copy2(E/f,mdir/f)
 mf=copy.deepcopy(manifest0)
 if fn:fn(mf)
 dump(mdir/'eng_ppo_smoke_256.manifest.json',mf);rej=False;hit=False;why=[]
 try:G.cold_read_checkpoint(qd,auth,mdir,root/'out')
 except NoLoad:hit=True
 except Q.QualifiedInputError as e:rej=True;why=e.report.get('problems')
 record(name,rej==expected,rejected=rej,model_load_reached=hit,expected_reject=expected,problems=why)
# Existing quota logic executed with an exception at learn: no real update.
import numpy as np
class DummyEnv:
 def __init__(self,*a,**k):self.observation_space=types.SimpleNamespace(shape=(9,),low=np.array([-np.inf]*8+[0.]),high=np.array([np.inf]*8+[1.]))
 def audit(self):return {'steps_taken':0}
class DummyPPO:
 def __init__(self,e):self.observation_space=e.observation_space
 def learn(self,**k):raise RuntimeError('SYNTHETIC interrupted before any optimization')
mod('rl_curriculum.ppo262_env',CurriculumMultiEpisodeEnv=DummyEnv)
mod('rl_curriculum.ppo262_train',save_model_with_manifest=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Should not save')))
mod('rl_curriculum.ppo262_diag_train',build_diagnosed_ppo=lambda cfg,seed,env:DummyPPO(env))
G._torch_param_digest=lambda _: 'no-model-no-parameters'
root,qd,auth=case('quota_interruption');qi=Q.load_qualified_input(qd,authorization_path=auth,expected_scope='engineering');ledger=G.QuotaLedger(root/'test_ledger.jsonl');states=[]
for i in range(9):
 try:G.engineering_ppo_run(qi,[],ledger,root/str(i))
 except Q.QualifiedInputError:states.append('quota_rejected')
 except RuntimeError:states.append('synthetic_interruption')
record('quota_failures_counted',states==['synthetic_interruption']*8+['quota_rejected'] and ledger.sums()['ppo_smoke_steps']==2048,states=states,sums=ledger.sums(),actual_optimizer_updates=0)
res={'method':'Unchanged C5 modules; external recorded-valid capsules; sentinels before generation/optimizer/PPO.load. Synthetic Git only. NOT live WSL/V2/SB3 rerun.','cases':results,'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in SRC.glob('*.py')},'native_episodes_generated':0,'fit_calls':0,'optimizer_updates':0,'test_work':str(W),'passed_expectations':sum(r['expectation_met'] for r in results),'total':len(results)}
dump(B/'probes/RESULT.json',res);print('TOTAL',res['total'],'MET',res['passed_expectations'])
