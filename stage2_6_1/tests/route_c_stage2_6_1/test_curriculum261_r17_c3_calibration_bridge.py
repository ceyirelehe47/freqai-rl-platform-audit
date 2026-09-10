import copy
import json
from pathlib import Path
import subprocess
import sys
import pytest

HERE=Path(__file__).resolve()
for base in HERE.parents:
    found=False
    for runner in (base/'implementation',base/'runner',base/'stage2_6_1'/'runner',base/'stage2_6_1_runner'):
        if (runner/'r17_c3_calibration_bridge.py').is_file():
            sys.path.insert(0,str(runner))
            support=base/'test_support'
            if (support/'r17_c3_reserve_batch.py').is_file():sys.path.append(str(support))
            found=True;break
    if found:break
else:raise RuntimeError('calibration bridge implementation not found')

import r17_c3_reserve_batch as m
import r17_c3_calibration_bridge as b


"""Explicit synthetic upstream data; no real generation or evaluation."""
import hashlib
import r17_c3_reserve_batch as m
GENERATOR={"family":"c3_cost","version":"cur261-c3-v4","fixture":True}

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

class LadderFixture(Fixture):
    """Deterministic returns only for bridge tests, not a production evaluator."""
    def __init__(self, fail_split=None, **kw):
        super().__init__(**kw);self.fail_split=fail_split
    def evaluate(self,q,p):
        out=ev(q,p)
        v=[.08,.06,.04,.02][m.RUNGS.index(q.rung)] + q.index*.001
        if q.split==self.fail_split and q.rung=='D3': v=-.02
        for row in out['episodes']:
            row['reference']=2*v+.01 if row['side']=='A' else -.01
            row['oracle']=abs(row['reference'])+.1
            row['reference_trades']=3;row['always_long_trades']=1
        out['policy_means']={k:sum(r[k] for r in out['episodes'])/2 for k in m.POLICIES}
        out['difficulty_metric']=out['policy_means']['reference']
        out['reference_beats_required_baselines']=v>0
        out['oracle_positive']=True
        return out


"""NumPy statistical fixtures for adapter tests, not the full repository.

Equations match the inspected R4/R5 contract; the WSL interface check must call
actual repository functions. No test here claims full project execution.
"""
import math
import types
import numpy as np
import r17_c3_calibration_bridge as b
from r17_c3_calibration_authority import RepositoryAuthority


def build_pair_evidence_table(rows,family,corpus):
    by={}
    for r in rows:by.setdefault((r['rung'],r['pair']),{})[r['side']]=r
    table=[]
    for (r,i),x in sorted(by.items()):
        table.append({'family':family,'corpus':corpus,'rung':r,'pair_index':i,
                      'episode_hashes':{s:x[s]['episode_hash'] for s in ('A','B')},
                      'returns':{p:float(np.mean([x['A'][p],x['B'][p]])) for p in b.POLICIES}})
    return {'schema':{'fixture':True},'schema_identity':'fixture','family':family,'corpus':corpus,'rows':table,'n_pairs':len(table)}


def table_series(t,r,p):return np.asarray([x['returns'][p] for x in t['rows'] if x['rung']==r])
def difficulty_series(t,r):return table_series(t,r,'reference')-table_series(t,r,'always_flat')
def margin_series(t,r,p):return table_series(t,r,'reference')-table_series(t,r,p)
def cluster_stats(a):
    return {'n':len(a),'mean':float(np.mean(a)),'sd':float(np.std(a,ddof=1)),
            'se':float(np.std(a,ddof=1)/np.sqrt(len(a)))}
def bootstrap_mean_ci(a):
    rng=np.random.default_rng(b.BOOTSTRAP_SEED)
    v=a[rng.integers(0,len(a),size=(b.BOOTSTRAP_N,len(a)))].mean(axis=1)
    lo,hi=np.quantile(v,[.025,.975])
    return {'n':len(a),'mean':float(a.mean()),'ci_low':float(lo),'ci_high':float(hi),
            'seed':b.BOOTSTRAP_SEED,'resamples':b.BOOTSTRAP_N,'method':'percentile bootstrap;resample pairs(A/B 不拆散)'}

def corpus_conditions_r5(rep,kappa=1.5):
    la=rep['difficulty_ladder'];gaps={}
    for a,c in zip(b.RUNGS,b.RUNGS[1:]):
        key=a+'-'+c;g=rep['adjacent_rung_gaps'][key]
        gaps[key]={**g,'kappa_times_se':kappa*g['se_pair_cluster'],
                   'ok':g['gap']>0 and g['gap']>=kappa*g['se_pair_cluster']}
    margins={}
    for p in b.BASELINES:
        margins[p]={}
        for r in b.RUNGS:
            st=rep['fixed_baseline_margins'][p][r]
            margins[p][r]={'mean':st['mean'],'se':st['se'],'kappa_times_se':kappa*st['se'],
                           'bootstrap_ci':st['bootstrap_ci'],'ok':st['mean']>0 and st['mean']>=kappa*st['se']}
    doc={'rule':'strict per-corpus(R5 唯一口径)','kappa':float(kappa),
         'ordering_ok':all(la[a]['mean']>la[c]['mean'] for a,c in zip(b.RUNGS,b.RUNGS[1:])),
         'gaps_ge_kappa_se':all(x['ok'] for x in gaps.values()),'gaps':gaps,
         'd3_positive':la['D3']['mean']>0,'d3_mean_ge_kappa_se':la['D3']['mean']>=kappa*la['D3']['se'],
         'd3_mean':la['D3']['mean'],'d3_se':la['D3']['se'],'d3_bootstrap_ci':la['D3']['bootstrap_ci'],
         'margins_ok':all(x['ok'] for pr in margins.values() for x in pr.values()),'fixed_baseline_margins':margins,
         'pair_integrity_unity':rep['pair_integrity_pass_rate']==1.,'oracle_positive':rep['oracle_positive_all_rungs']}
    doc['pass']=all(doc[k] for k in ('ordering_ok','gaps_ge_kappa_se','d3_positive','d3_mean_ge_kappa_se','margins_ok','pair_integrity_unity','oracle_positive'))
    return doc


class FixtureAuthority(RepositoryAuthority):
    def __init__(self):
        names=('build_pair_evidence_table','table_series','difficulty_series','margin_series','cluster_stats','bootstrap_mean_ci')
        self.r4=types.SimpleNamespace(**{n:globals()[n] for n in names})
        self.r5=types.SimpleNamespace(corpus_conditions_r5=corpus_conditions_r5)
        self.calls=0
    def describe(self):return {'kind':'test_fixture','sources':{}}
    def analyze(self,rows):
        self.calls+=1
        return super().analyze(rows)


def source(tmp, **kw):
    root=tmp/'source';m.execute(root,LadderFixture(**kw));return root

def bridge(tmp,**kw):
    src=source(tmp,**kw);out=tmp/'output';a=FixtureAuthority()
    result=b.execute(src,out,a,test_mode=True)
    return src,out,result,a

def save(path,obj):path.write_text(m.canonical(obj)+'\n')
def resign(root):
    save(root/'manifest.json',{'contract':b.CONTRACT,'files':{k:v for k,v in m.tree_snapshot(root).items() if k!='manifest.json'}})


def test_happy_real_adapter_method_synthetic_primitives(tmp_path):
    src,out,result,a=bridge(tmp_path)
    assert a.calls==1 and result['engineering_consumer_complete']
    assert result['statistical_diagnostic_pass'] and result['calibration_qualified'] is False
    assert b.verify(out,test_mode=True)['evidence_consistent']
    assert m.tree_snapshot(src)==m.tree_snapshot(out/'input_batch')

@pytest.mark.parametrize('fail_split',['main','validation'])
def test_failed_statistics_are_preserved_not_consumer_error(fail_split,tmp_path):
    src,out,result,a=bridge(tmp_path,fail_split=fail_split)
    assert result['rc']==0 and result['statistical_diagnostic_verdict']=='FAIL'
    assert result['split_pass'][fail_split] is False and result['calibration_qualified'] is False
    assert b.verify(out,test_mode=True)['engineering_consumer_complete']


def test_pair_not_strategy_and_negative_returns_retained(tmp_path):
    _,out,_,_=bridge(tmp_path)
    doc=m.read_json(out/'analysis.json');c=doc['return_counts']
    assert c['n_policy_returns']==160 and len(c['policies'])==5
    assert sum(c['totals'].values())==160 and c['policies']['reference']['negative']==16
    for s in b.SPLITS:
        assert all(set(x['returns'])==set(b.POLICIES) for x in doc['corpora'][s]['report']['pair_table']['rows'])


def test_corpus_se_uses_pair_n_not_episode_n(tmp_path):
    _,out,_,_=bridge(tmp_path)
    st=m.read_json(out/'analysis.json')['corpora']['main']['report']['difficulty_ladder']['D0']
    assert st['n']==2 and st['se']==pytest.approx(.0005)


def test_same_pair_index_across_splits_never_merged(tmp_path):
    _,out,_,_=bridge(tmp_path)
    doc=m.read_json(out/'analysis.json')
    assert all(doc['corpora'][s]['report']['pair_table']['n_pairs']==8 for s in b.SPLITS)
    assert doc['corpora']['main']['report']['corpus']!=doc['corpora']['validation']['report']['corpus']

@pytest.mark.parametrize('mode',['delete','append','same_length'])
def test_input_tamper_before_run_rejected(mode,tmp_path):
    src=source(tmp_path);p=src/'selection.json'
    if mode=='delete':p.unlink()
    elif mode=='append':p.write_bytes(p.read_bytes()+b' ')
    else:p.write_bytes(b'['+p.read_bytes()[1:])
    a=FixtureAuthority()
    with pytest.raises(Exception):b.execute(src,tmp_path/'out',a,test_mode=True)
    assert a.calls==0 and not (tmp_path/'out').exists()

@pytest.mark.parametrize('target',['source','nested','existing','symlink'])
def test_no_input_or_existing_output_overwrite(target,tmp_path):
    src=source(tmp_path);before=m.tree_snapshot(src)
    out=tmp_path/'out'
    if target=='source':out=src
    elif target=='nested':out=src/'new'
    elif target=='existing':out.mkdir();(out/'history').write_text('keep')
    else:out.symlink_to(src,target_is_directory=True)
    with pytest.raises(Exception):b.execute(src,out,FixtureAuthority(),test_mode=True)
    assert before==m.tree_snapshot(src)
    if target=='existing':assert (out/'history').read_text()=='keep'


def test_second_execution_refuses_existing(tmp_path):
    src,out,_,_=bridge(tmp_path);before=m.tree_snapshot(out)
    with pytest.raises(Exception):b.execute(src,out,FixtureAuthority(),test_mode=True)
    assert before==m.tree_snapshot(out)


def test_source_unchanged_full_command(tmp_path):
    src=source(tmp_path);before=m.tree_snapshot(src)
    b.execute(src,tmp_path/'out',FixtureAuthority(),test_mode=True)
    assert before==m.tree_snapshot(src)


def test_production_cli_refuses_fixture(tmp_path):
    _,out,_,_=bridge(tmp_path)
    import os
    env=dict(os.environ);env['PYTHONPATH']=str(Path(b.__file__).parent)+':'+str(Path(m.__file__).parent)
    proc=subprocess.run([sys.executable,str(Path(b.__file__)),'verify','--root',str(out)],capture_output=True,text=True,env=env)
    assert proc.returncode==3 and 'fixture' in proc.stdout


def test_contract_subcommand_loads_no_business(tmp_path):
    script="import sys;import r17_c3_calibration_bridge as b;b.main(['contract']);assert not any(x.startswith('rl_curriculum') for x in sys.modules)"
    import os
    env=dict(os.environ);env['PYTHONPATH']=str(Path(b.__file__).parent)+':'+str(Path(m.__file__).parent)
    p=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,env=env)
    assert p.returncode==0,p.stderr

@pytest.mark.parametrize('where',['analysis','result','episodes','input'])
def test_byte_mutation_after_seal_rejected(where,tmp_path):
    _,out,_,_=bridge(tmp_path)
    p=out/({'input':'input_batch/selection.json'}.get(where,where+'.json'))
    p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(Exception):b.verify(out,test_mode=True)

@pytest.mark.parametrize('case',['promote_qualified','promote_scaled','make_new_requests','force_pass','count_pair_as_return',
                                  'wrong_pair_hash','wrong_pair_mean','wrong_se','wrong_cluster_n','drop_baseline',
                                  'missing_split','pooled_rescue','wrong_gap','flip_margin_leaf','wrong_corpus',
                                  'copy_split','wrong_kappa','bootstrap_seed','metadata_as_return','alter_episodes','extra_file'])
def test_semantic_mutations_still_rejected_after_outer_resign(case,tmp_path):
    _,out,_,_=bridge(tmp_path,fail_split='validation')
    a=m.read_json(out/'analysis.json');r=m.read_json(out/'result.json')
    rep=a['corpora']['main']['report'];cond=a['corpora']['main']['conditions']
    if case=='promote_qualified':r['calibration_qualified']=True
    elif case=='promote_scaled':r['scaled_pipeline_validated']=True
    elif case=='make_new_requests':r['new_pair_requests']=1
    elif case=='force_pass':r['statistical_diagnostic_pass']=True
    elif case=='count_pair_as_return':a['return_counts']['n_policy_returns']=192
    elif case=='wrong_pair_hash':rep['pair_table']['rows'][0]['episode_hashes']['A']='ce-wrong'
    elif case=='wrong_pair_mean':rep['pair_table']['rows'][0]['returns']['reference']=1.
    elif case=='wrong_se':rep['difficulty_ladder']['D0']['se']/=2
    elif case=='wrong_cluster_n':rep['difficulty_ladder']['D0']['n']=4
    elif case=='drop_baseline':del rep['fixed_baseline_margins']['c3_cost_ignorant']
    elif case=='missing_split':del a['corpora']['validation']
    elif case=='pooled_rescue':a['strict_both_pass']=True
    elif case=='wrong_gap':rep['adjacent_rung_gaps']['D0-D1']['gap']=100.
    elif case=='flip_margin_leaf':cond['fixed_baseline_margins']['always_flat']['D0']['ok']=False
    elif case=='wrong_corpus':rep['pair_table']['corpus']='calibration_r17'
    elif case=='copy_split':a['corpora']['validation']=copy.deepcopy(a['corpora']['main'])
    elif case=='wrong_kappa':cond['kappa']=1.
    elif case=='bootstrap_seed':rep['difficulty_ladder']['D0']['bootstrap_ci']['seed']=1
    elif case=='metadata_as_return':rep['pair_table']['rows'][0]['returns']['pair']=0
    elif case=='alter_episodes':
        rows=m.read_json(out/'episodes.json');rows['main'][0]['reference']+=1;save(out/'episodes.json',rows)
    else:(out/'extra').write_text('unexpected')
    save(out/'analysis.json',a);save(out/'result.json',r);resign(out)
    with pytest.raises(Exception):b.verify(out,test_mode=True)

@pytest.mark.parametrize('field',['oracle','reference','pair','episode_hash'])
def test_missing_row_values_rejected(field,tmp_path):
    src=source(tmp_path);rows,_,_=b.load_input(src,test_mode=True);del rows['main'][0][field]
    with pytest.raises(Exception):b.validate_rows(rows)

@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,None])
def test_invalid_returns_rejected(value,tmp_path):
    src=source(tmp_path);rows,_,_=b.load_input(src,test_mode=True);rows['main'][0]['reference']=value
    with pytest.raises(Exception):b.validate_rows(rows)


def test_duplicate_side_rejected(tmp_path):
    src=source(tmp_path);rows,_,_=b.load_input(src,test_mode=True);rows['main'][1]=rows['main'][0].copy()
    with pytest.raises(Exception):b.validate_rows(rows)


def test_authority_failure_preserves_original_and_error(tmp_path):
    src=source(tmp_path);before=m.tree_snapshot(src)
    class Fail(FixtureAuthority):
        def analyze(self,rows):raise RuntimeError('authority failure')
    with pytest.raises(RuntimeError):b.execute(src,tmp_path/'out',Fail(),test_mode=True)
    assert before==m.tree_snapshot(src) and (tmp_path/'out/failure.json').is_file()
    assert not (tmp_path/'out/result.json').exists()


def test_invalid_authority_payload_preserved(tmp_path):
    src=source(tmp_path)
    class Wrong(FixtureAuthority):
        def analyze(self,rows):
            a=super().analyze(rows);a['strict_both_pass']=False;return a
    with pytest.raises(Exception):b.execute(src,tmp_path/'out',Wrong(),test_mode=True)
    assert (tmp_path/'out/analysis.json').is_file() and (tmp_path/'out/failure.json').is_file()
    assert not (tmp_path/'out/manifest.json').exists()


def test_insufficient_cluster_cannot_default_to_zero_se():
    with pytest.raises(Exception):b._stats([.01])


def test_scientific_threshold_uses_exact_greater_equal():
    # No tolerance around verdict: this equality is valid, just-below is not.
    rep={'difficulty_ladder':{r:{'mean':.08-i*.02,'se':0.} for i,r in enumerate(b.RUNGS)},
         'adjacent_rung_gaps':{k:{'gap':.02,'se_pair_cluster':0.} for k in ('D0-D1','D1-D2','D2-D3')},
         'fixed_baseline_margins':{p:{r:{'mean':.02,'se':0.} for r in b.RUNGS} for p in b.BASELINES},
         'pair_integrity_pass_rate':1.,'oracle_positive_all_rungs':True}
    rep['difficulty_ladder']['D3']={'mean':.015,'se':.01}
    assert b._strict_from_report(rep)['d3_mean_ge_kappa_se']
    rep['difficulty_ladder']['D3']['mean']=.015-1e-14
    assert not b._strict_from_report(rep)['d3_mean_ge_kappa_se']
