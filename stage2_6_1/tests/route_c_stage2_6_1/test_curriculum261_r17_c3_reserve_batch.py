"""Finite reserve policy tests: fixture data, NOT production generation evidence."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve()
for base in HERE.parents:
    for runner in (base/'implementation', base/'runner', base/'stage2_6_1'/'runner',
                   base/'stage2_6_1_runner'):
        if (runner/'r17_c3_reserve_batch.py').is_file():
            sys.path.insert(0, str(runner)); break
    else:
        continue
    break
else:
    raise RuntimeError('reserve implementation not found')
import r17_c3_reserve_batch as m

GENERATOR = {'family': 'c3_cost', 'version': 'cur261-c3-v4', 'fixture': True}


def proof(q, accepted=True, attempts=None):
    n = attempts if attempts is not None else (1 if accepted else 5)
    rp = {**m.PARAMS[q.rung], 'cur261_rung': q.rung}
    call = {**q.coordinate, 'iteration': 'r17', 'max_attempts': 5, 'rung_params': rp,
            'generator': GENERATOR, 'split': 'curriculum261_'+q.coordinate['namespace'], 'timeframe': '15m'}
    call['digest'] = m.envelope_digest(call, True)
    envs, logs = [], []
    for i in range(n):
        passed = accepted and i == n-1
        codes = [] if passed else ['A:too_few_distractors','B:too_few_distractors','pair:too_few_distractors']
        env = {**q.coordinate, 'iteration':'r17', 'attempt_index':i, 'outer_seed':m.expected_seed(q,i),
               'internal_derived_seed':m.expected_seed(q,i)//2, 'split':call['split'], 'timeframe':'15m',
               'seed_derivation_fields':{**q.coordinate,'attempt':i,'stage_id':'stage2_6_1'},
               'generator':GENERATOR, 'exception':None, 'generator_state_changed':False,
               'generator_state_changed_since_call_start':False, 'accepted':passed,
               'structural_validator_results':codes, 'rejection_reasons':codes,
               'base_params':{s:{**rp,'pair_variant':s,'episode_bars':288,'initial_price':1.0} for s in ('A','B')},
               'event_table':{s:{'bars':288,'hidden_digest':'hidden-fixture',
                                'episode_content_hash':'ce-'+hashlib.sha256(f'{q.key}/{i}/{s}'.encode()).hexdigest(),
                                'counts':{'n_signals':10,'n_above_cost':6 if s=='A' else 0,
                                          'n_below_cost':4 if s=='A' else 10,'n_distractors':2 if passed else 0}}
                              for s in ('A','B')}}
        env['digest'] = m.envelope_digest(env)
        envs.append(env)
        logs.append({'index':i,'accepted':passed,'reason':'; '.join(codes)})
    hashes = {s:envs[-1]['event_table'][s]['episode_content_hash'] for s in ('A','B')} if accepted else {}
    return {'coordinate':q.coordinate,'status':'accepted' if accepted else 'structural_rejected',
            'recorder_errors':[], 'call_envelope':call,'attempt_envelopes':envs,
            'episode_hashes':hashes,'integrity':{'family':m.FAMILY,'rung':q.rung,'pair_index':q.index,'pass':True},
            'attempt_log':{'family':m.FAMILY,'rung':q.rung,'pair_index':q.index,
                           'seed_namespace':q.coordinate['namespace'],'max_attempts':5,
                           'selected_attempt':n-1 if accepted else None,
                           'attempts':logs,'output_episode_hashes':hashes}}


def ev(q,p,negative=False):
    rows=[]
    for side in ('A','B'):
        row={'rung':q.rung,'pair':q.index,'side':side,'episode_hash':p['episode_hashes'][side]}
        row.update({'always_flat':0.,'always_long':-.002,'c3_cost_ignorant':-.05,
                    'reference':-.12 if negative else .10,'oracle':-.1 if negative else .20})
        rows.append(row)
    means={n:sum(r[n] for r in rows)/2 for n in m.POLICIES}
    return {'family':m.FAMILY,'episodes':rows,'policy_means':means,
            'difficulty_metric':means['reference']-max(0.,means['always_long']),
            'reference_beats_required_baselines':means['reference']>max(means[n] for n in m.POLICIES[:3]),
            'oracle_positive':means['oracle']>0}


class Fixture:
    def __init__(self,rejected=(),fail=None,negative=False,evaluation_fail=None):
        self.rejected=set(rejected); self.fail=fail; self.negative=negative
        self.evaluation_fail=evaluation_fail; self.calls=[]; self.evaluated=[]; self.root=None
    def describe(self):
        return {'kind':'test_fixture','generator':GENERATOR}
    def generate(self,q,observe):
        self.calls.append(q.key)
        if q.key==self.fail:
            raise PermissionError('fixture permission denied; not structural')
        p=proof(q,q.key not in self.rejected)
        observe('call',p['call_envelope'])
        for e in p['attempt_envelopes']: observe('attempt',e)
        return m.Generated(p,p if p['status']=='accepted' else None)
    def evaluate(self,q,handle):
        assert self.root is None or (self.root/'selection.json').is_file()
        self.evaluated.append(q.key)
        if q.key==self.evaluation_fail:
            raise OSError('evaluation failed')
        return ev(q,handle,self.negative)


def execute(tmp_path,backend=None):
    backend=backend or Fixture()
    backend.root=tmp_path/'batch'
    out=m.execute(backend.root,backend)
    return out,backend


def resign(root):
    path=root/'manifest.json'
    path.write_text(m.canonical({'contract':m.CONTRACT,'files':{
        k:v for k,v in m.tree_snapshot(root).items() if k!='manifest.json'}})+'\n')


def save(path,doc):
    path.write_text(m.canonical(doc)+'\n')


def test_happy_all_primaries_and_no_reserves(tmp_path):
    out,b=execute(tmp_path)
    assert out['rc']==0 and len(b.calls)==16 and len(b.evaluated)==16
    assert all(k.endswith(('p0','p1')) for k in b.calls)
    r=m.verify(b.root,allow_test_fixture=True)
    assert r['engineering_batch_complete'] and r['n_requests']==16
    assert all(v=='not_needed' for k,v in out['schedule']['states'].items() if k.endswith(('p2','p3')))


@pytest.mark.parametrize('split',tuple(m.NAMESPACES))
@pytest.mark.parametrize('rung',m.RUNGS)
def test_same_stratum_reserve_only(split,rung,tmp_path):
    failed=f'{split}_{rung}_p0'
    out,b=execute(tmp_path,Fixture([failed]))
    assert out['rc']==0 and len(b.calls)==17
    assert f'{split}_{rung}_p2' in b.calls and f'{split}_{rung}_p3' not in b.calls
    assert failed not in b.evaluated
    m.verify(b.root,allow_test_fixture=True)


def test_reject_one_reserve_then_next(tmp_path):
    out,b=execute(tmp_path,Fixture(['main_D0_p0','main_D0_p2']))
    assert b.calls[:4]==['main_D0_p0','main_D0_p1','main_D0_p2','main_D0_p3']
    assert out['rc']==0 and len(b.evaluated)==16


def test_both_primaries_rejected_uses_two_reserves(tmp_path):
    out,b=execute(tmp_path,Fixture(['main_D0_p0','main_D0_p1']))
    assert out['schedule']['selected'][:2]==['main_D0_p2','main_D0_p3']
    assert out['rc']==0


def test_finite_exhaustion_stops_entire_batch_before_eval(tmp_path):
    out,b=execute(tmp_path,Fixture([f'main_D0_p{i}' for i in range(4)]))
    assert out['rc']==4 and len(b.calls)==4 and not b.evaluated
    r=m.verify(b.root,allow_test_fixture=True)
    assert r['evidence_consistent'] and not r['engineering_batch_complete']
    assert out['schedule']['states']['validation_D0_p0']=='not_started'


def test_maximum_32_requests_160_attempt_bound(tmp_path):
    class Slow(Fixture):
        def generate(self,q,observe):
            self.calls.append(q.key)
            p=proof(q,q.index>=2,attempts=5)
            observe('call',p['call_envelope'])
            for e in p['attempt_envelopes']: observe('attempt',e)
            return m.Generated(p,p if q.index>=2 else None)
    out,b=execute(tmp_path,Slow())
    assert out['rc']==0 and len(b.calls)==32
    assert len(list((b.root/'attempts').glob('*/attempt_*.json')))==160


def test_negative_performance_not_a_membership_gate(tmp_path):
    out,b=execute(tmp_path,Fixture(negative=True))
    assert out['rc']==0 and len(b.calls)==16
    assert m.verify(b.root,allow_test_fixture=True)['engineering_batch_complete']


def test_evaluator_error_does_not_generate_replacement(tmp_path):
    out,b=execute(tmp_path,Fixture(evaluation_fail='main_D0_p1'))
    assert out['rc']==3 and len(b.calls)==16 and len(b.evaluated)==2
    assert out['evaluated']==['main_D0_p0']
    assert not any(k.endswith('p2') for k in b.calls)
    m.verify(b.root,allow_test_fixture=True)


def test_nonstructural_error_stops_immediately(tmp_path):
    out,b=execute(tmp_path,Fixture(fail='main_D0_p0'))
    assert out['rc']==3 and b.calls==['main_D0_p0'] and b.evaluated==[]
    m.verify(b.root,allow_test_fixture=True)


def test_new_output_no_overwrite(tmp_path):
    out,b=execute(tmp_path)
    before=m.tree_snapshot(b.root)
    with pytest.raises(FileExistsError): m.execute(b.root,Fixture())
    assert before==m.tree_snapshot(b.root)


def test_source_guard_prevents_generation(tmp_path):
    b=Fixture()
    def fail(): raise m.EvidenceError('source drift')
    result=m.execute(tmp_path/'batch',b,source_guard=fail)
    assert result['rc']==3 and b.calls==[]


def test_source_guard_before_evaluation(tmp_path):
    b=Fixture(); calls=[]
    def guard():
        calls.append(1)
        if len(calls)==2: raise m.EvidenceError('changed source')
    result=m.execute(tmp_path/'batch',b,source_guard=guard)
    assert result['rc']==3 and len(b.calls)==16 and not b.evaluated


@pytest.mark.parametrize('mutation',[
    'missing_envelope','bad_digest','wrong_namespace','wrong_seed','null_internal_seed',
    'missing_side','generator_error','nuisance_failure','unknown_rejection','missing_param',
    'wrong_param','recorder_failure','selected_hashes','wrong_generator','state_drift',
    'accepted_with_reasons','rejection_short','accepted_integrity_false','wrong_log_namespace'])
def test_proof_faults_fail_closed(mutation):
    q=m.Request('main','D0',0); p=proof(q)
    if mutation=='rejection_short': p=proof(q,False,4)
    e=p['attempt_envelopes'][0]
    if mutation=='missing_envelope': p['attempt_envelopes']=[]
    elif mutation=='bad_digest': e['digest']='bad'
    elif mutation=='wrong_namespace': e['namespace']='qualification_r17'
    elif mutation=='wrong_seed': e['outer_seed']+=1
    elif mutation=='null_internal_seed': e['internal_derived_seed']=None
    elif mutation=='missing_side': del e['event_table']['B']
    elif mutation=='generator_error': e['exception']='arbitrary generator failure'
    elif mutation in ('nuisance_failure','unknown_rejection'):
        p=proof(q,False); e=p['attempt_envelopes'][0]
        e['rejection_reasons']=e['structural_validator_results']=[
            'pair:nuisance_volume_identical' if mutation=='nuisance_failure' else 'PnL_too_low']
        p['attempt_log']['attempts'][0]['reason']='; '.join(e['rejection_reasons'])
    elif mutation=='missing_param': del e['base_params']['A']['alpha_bps']
    elif mutation=='wrong_param': e['base_params']['B']['distractor_rate']=.9
    elif mutation=='recorder_failure': p['recorder_errors']=['disk failure']
    elif mutation=='selected_hashes':
        p['episode_hashes']={s:'ce-'+'0'*64 for s in ('A','B')}
        p['attempt_log']['output_episode_hashes']=p['episode_hashes']
    elif mutation=='wrong_generator': e['generator']={'changed':True}
    elif mutation=='state_drift': e['generator_state_changed']=True
    elif mutation=='accepted_with_reasons': e['rejection_reasons']=['A:too_few_signals']
    elif mutation=='accepted_integrity_false': p['integrity']['pass']=False
    elif mutation=='wrong_log_namespace': p['attempt_log']['seed_namespace']='elsewhere'
    if mutation!='bad_digest': e['digest']=m.envelope_digest(e)
    with pytest.raises((m.EvidenceError,KeyError)):
        m.validate_proof(q,p,m.make_plan(Fixture().describe()))


@pytest.mark.parametrize('field',['alpha_bps','payoff_bars','vol_bps','cue_rate','mixture','distractor_rate'])
def test_deleted_param_even_with_valid_digest(field):
    q=m.Request('main','D2',1); p=proof(q)
    e=p['attempt_envelopes'][0]; del e['base_params']['B'][field]
    e['digest']=m.envelope_digest(e)
    with pytest.raises(m.EvidenceError): m.validate_proof(q,p,m.make_plan(Fixture().describe()))


@pytest.mark.parametrize('side',['A','B'])
def test_three_downstream_hashes_cannot_override_selected(side):
    q=m.Request('main','D0',0); p=proof(q)
    p['episode_hashes'][side]='ce-'+'a'*64
    p['attempt_log']['output_episode_hashes']=p['episode_hashes']
    with pytest.raises(m.EvidenceError): m.validate_proof(q,p,m.make_plan(Fixture().describe()))


@pytest.mark.parametrize('mutation',['reorder','selection','extra_request','extra_eval','modified_plan','hide_rejection'])
def test_cold_semantic_tamper_even_when_manifest_resigned(tmp_path,mutation):
    out,b=execute(tmp_path,Fixture(['main_D0_p0']))
    rp=b.root/'result.json'; r=m.read_json(rp)
    if mutation=='reorder': r['results'][0],r['results'][1]=r['results'][1],r['results'][0]; save(rp,r)
    elif mutation=='selection':
        sp=b.root/'selection.json'; s=m.read_json(sp); s['selected'][0]='validation_D0_p0'; save(sp,s)
    elif mutation=='extra_request': save(b.root/'requests'/'main_D0_p9.json',{})
    elif mutation=='extra_eval': save(b.root/'evaluations'/'main_D0_p9.json',{})
    elif mutation=='modified_plan':
        pp=b.root/'plan.json'; p=m.read_json(pp); p['contract']['reserve_indices'].append(4); save(pp,p)
    elif mutation=='hide_rejection': r['results'].pop(0); save(rp,r)
    resign(b.root)
    with pytest.raises(m.EvidenceError): m.verify(b.root,allow_test_fixture=True)


@pytest.mark.parametrize('mutation',['delete','append','same_length'])
def test_bytes_tamper(tmp_path,mutation):
    out,b=execute(tmp_path)
    path=b.root/'selection.json'; data=path.read_bytes()
    if mutation=='delete': path.unlink()
    elif mutation=='append': path.write_bytes(data+b' ')
    else: path.write_bytes(b'['+data[1:])
    with pytest.raises(m.EvidenceError): m.verify(b.root,allow_test_fixture=True)


def test_verify_does_not_write(tmp_path):
    out,b=execute(tmp_path); before=m.tree_snapshot(b.root)
    m.verify(b.root,allow_test_fixture=True)
    assert before==m.tree_snapshot(b.root)


def test_cli_refuses_fixture_as_real_evidence(tmp_path):
    out,b=execute(tmp_path)
    p=subprocess.run([sys.executable,m.__file__,'verify','--root',str(b.root)],capture_output=True,text=True)
    assert p.returncode!=0 and 'fixture is not real' in p.stderr


def test_plan_cli_zero_business_import(tmp_path):
    p=subprocess.run([sys.executable,m.__file__,'plan'],capture_output=True,text=True)
    assert p.returncode==0
    c=json.loads(p.stdout); assert c['max_pair_requests']==32 and c['max_attempt_envelopes']==160


def test_read_duplicate_keys_and_nan(tmp_path):
    path=tmp_path/'bad.json'
    for text in ['{"x":1,"x":2}','{"x":NaN}']:
        path.write_text(text)
        with pytest.raises(m.EvidenceError): m.read_json(path)


def test_existing_temp_not_deleted(tmp_path,monkeypatch):
    monkeypatch.setattr(m.secrets,'token_hex',lambda n:'fixed')
    conflict=tmp_path/'.x.json.fixed.tmp'; conflict.write_text('NOT OWNED')
    with pytest.raises(FileExistsError): m.new_json(tmp_path/'x.json',{'x':1})
    assert conflict.read_text()=='NOT OWNED'


def test_existing_target_preserved(tmp_path):
    target=tmp_path/'out.json'; target.write_text('OLD')
    with pytest.raises(FileExistsError): m.new_json(target,{})
    assert target.read_text()=='OLD'
    assert len(list(tmp_path.iterdir()))==1


def test_hidden_parameter_override_rejected():
    q=m.Request('main','D0',0);p=proof(q);e=p['attempt_envelopes'][0]
    e['base_params']['A']['noise_mutate_from']=10;e['digest']=m.envelope_digest(e)
    with pytest.raises(m.EvidenceError):m.validate_proof(q,p,m.make_plan(Fixture().describe()))


def test_unused_reserve_cannot_have_hidden_attempt_file(tmp_path):
    out,b=execute(tmp_path)
    p=b.root/'attempts'/'main_D0_p2'/'attempt_0.json';p.parent.mkdir();save(p,{})
    resign(b.root)
    with pytest.raises(m.EvidenceError):m.verify(b.root,allow_test_fixture=True)


def test_evaluation_values_do_not_change_selection(tmp_path):
    a=tmp_path/'positive';a.mkdir();b=tmp_path/'negative';b.mkdir()
    r1,f1=execute(a,Fixture(['main_D0_p0'],negative=False))
    r2,f2=execute(b,Fixture(['main_D0_p0'],negative=True))
    assert r1['schedule']==r2['schedule']
    assert (f1.root/'selection.json').read_bytes()==(f2.root/'selection.json').read_bytes()


def test_six_attempts_not_allowed():
    q=m.Request('main','D0',0);p=proof(q,False,6)
    with pytest.raises(m.EvidenceError):m.validate_proof(q,p,m.make_plan(Fixture().describe()))


def test_reordered_selected_envelope_fails():
    q=m.Request('validation','D3',0);p=proof(q,True,2)
    p['attempt_envelopes'].reverse()
    with pytest.raises(m.EvidenceError):m.validate_proof(q,p,m.make_plan(Fixture().describe()))


@pytest.mark.parametrize('stage',['request','evaluation'])
def test_written_invalid_evidence_is_preserved_and_not_substituted(tmp_path,stage):
    class Broken(Fixture):
        def generate(self,q,observe):
            g=super().generate(q,observe)
            if stage=='request':g.proof['integrity']['pass']=False
            return g
        def evaluate(self,q,h):
            v=super().evaluate(q,h)
            if stage=='evaluation':v['episodes'][0]['episode_hash']='ce-'+'f'*64
            return v
    r,b=execute(tmp_path,Broken())
    assert r['rc']==3
    if stage=='request':
        assert len(b.calls)==1 and len(b.evaluated)==0
        assert (b.root/'requests'/'main_D0_p0.json').is_file()
    else:
        assert len(b.calls)==16 and len(b.evaluated)==1
        assert (b.root/'evaluations'/'main_D0_p0.json').is_file()


def test_self_consistent_digest_does_not_hide_wrong_rejection_count():
    q=m.Request('main','D0',0);p=proof(q,False)
    e=p['attempt_envelopes'][0];e['event_table']['A']['counts']['n_distractors']=2
    e['digest']=m.envelope_digest(e)
    with pytest.raises(m.EvidenceError,match='count/rejection-reason'):m.validate_proof(q,p,m.make_plan(Fixture().describe()))
