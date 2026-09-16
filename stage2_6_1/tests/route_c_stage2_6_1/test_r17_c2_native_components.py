"""Native WSL integration. No monkeypatches, skips or downstream fake components."""
import copy
from pathlib import Path
import sys

import pytest

from rl_curriculum import curriculum261_r17_c2_native as n
from rl_curriculum import curriculum261_r17_c2_native_inputs as i
from rl_curriculum import curriculum261_r17_c2_consumer as consumer
from r17_c2_native_fixtures import make_corpus, spec_for


def _load_rehearsal():
    # The monitored entry normalizes PYTHONPATH to src only; runner modules and
    # their sentinel imports resolve via an explicit runner-dir sys.path insert,
    # per test_curriculum261_r17_v2_c13_synthetic_chain.
    here = Path(__file__).resolve()
    roots = [here.parents[2] / 'stage2_6_1_runner', here.parent.parent / 'runner']
    root = next(p for p in roots if (p / 'r17_c2_native_rehearsal.py').is_file())
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import r17_c2_native_rehearsal
    return r17_c2_native_rehearsal


NativeCallAudit = _load_rehearsal().NativeCallAudit


@pytest.fixture(scope='module')
def samples():
    pack = n.engineering_pack('historical', .95-.02)
    return pack, {role: make_corpus(spec_for('main', role, 'historical', 1 if role=='fit' else 2), pack)
                  for role in ('fit','calibration_matched','calibration_semantic','calibration_independent')}


@pytest.mark.parametrize('mutation', ['drop','duplicate','namespace','index','side','spec_seed','ce_hash','date','hidden','extra_family','retry'])
def test_sample_membership_mutations_fail(samples, mutation):
    _, data = samples
    corpus = copy.deepcopy(data['calibration_independent'])
    p = corpus.items[0]
    if mutation=='drop': corpus.items.pop()
    elif mutation=='duplicate': corpus.items[1]=corpus.items[0]
    elif mutation=='namespace': p.attempt_log.seed_namespace='qualification_r17'
    elif mutation=='index': p.pair_index=900
    elif mutation=='side': p.episodes['B']=p.episodes['A']
    elif mutation=='spec_seed':
        from dataclasses import replace
        ep=p.episodes['A'];ep.spec=replace(ep.spec,seed=ep.spec.seed+1)
    elif mutation=='ce_hash': p.attempt_log.episode_hashes['A']='ce-'+'0'*64
    elif mutation=='date': p.episodes['A'].df.loc[0,'date'] += __import__('pandas').Timedelta('1s')
    elif mutation=='hidden': p.episodes['A'].hidden.iloc[0,0]=999
    elif mutation=='extra_family': p.family='c1_opportunity'
    elif mutation=='retry': p.attempt_log.selected_attempt=1
    with pytest.raises((i.SampleError, RuntimeError)):
        corpus.check()


@pytest.mark.parametrize('field', ['role','split','candidate','count'])
def test_wrong_external_corpus_identity(samples, tmp_path, field):
    from dataclasses import replace
    _, data = samples
    corpus=data['calibration_independent']
    p=tmp_path/'sample.gz';sha=corpus.save(p)
    changes={'role':'design_independent','split':'validation','candidate':'midpoint','count':3}
    with pytest.raises(i.SampleError):
        i.load_corpus(p,sha,replace(corpus.spec,**{field:changes[field]}))


def test_all_sample_types_roundtrip(samples, tmp_path):
    _, data = samples
    for role, corpus in data.items():
        p=tmp_path/(role+'.gz')
        sha=corpus.save(p)
        loaded=i.load_corpus(p,sha,corpus.spec)
        assert loaded.seal==corpus.seal
        assert loaded.document()==corpus.document()


def test_explicit_seeds_require_exact_members_and_fixture_scope(samples):
    _, data=samples
    blocks=data['calibration_semantic'].items
    seeds=data['calibration_semantic'].seeds()
    for invalid in ({}, {**seeds,999:1}, {**seeds,0:True}, {**seeds,0:seeds[0]+1}):
        with pytest.raises(i.SampleError):
            i.explicit_trace_arguments(blocks,invalid)
    bad=copy.deepcopy(blocks)
    bad[0].attempt_log.seed_namespace='cue_semantic_qualification_r17'
    with pytest.raises(i.SampleError):
        i.explicit_trace_arguments(bad,seeds)


def test_raw_reuse_detection_ignores_label_changes(samples):
    _, data=samples
    corpus=data['calibration_independent']
    with pytest.raises(i.SampleError):
        i.disjoint_corpora(corpus,corpus)
    ep=copy.deepcopy(corpus.items[0].episodes['A'])
    original=i.raw_sample_fingerprint(ep)
    ep.df.index=range(1000,1288);ep.hidden.index=range(1000,1288)
    ep.df['date'] += __import__('pandas').Timedelta('1d')
    assert i.raw_sample_fingerprint(ep)==original


def test_real_v2_scaled_canonical_statistics_semantics(samples, tmp_path):
    pack,data=samples
    with NativeCallAudit() as audit:
        session=n.FitSession()
        frozen=session.fit(data['fit'],pack)
        with pytest.raises(i.SampleError): session.fit(data['fit'],pack)
        with pytest.raises(i.SampleError): frozen.fit(data['fit'].records())
        with pytest.raises(i.SampleError): frozen.native.inner.fit(data['fit'].records())
        with pytest.raises(i.SampleError): frozen.native.inner.fit_transform(data['fit'].records())
        checkpoint=frozen.save(tmp_path/'v2.json')
        loaded=n.FrozenV2.load(tmp_path/'v2.json',checkpoint,data['fit'],pack)
        assert n.v2_identity(loaded.native)==n.v2_identity(frozen.native)
        raw,cond=n.matched(data['calibration_matched'],pack,loaded)
        assert raw['n_blocks']==2 and len(raw['episodes'])==16
        assert len(raw['pair_table']['rows'])==8
        canonical=n.canonical_comparison(data['calibration_matched'],pack,loaded)
        assert canonical['pass'] is True
        assert canonical['n_episodes']==16
        indep=n.independent(data['calibration_independent'],pack,loaded)
        assert len(indep['report']['pair_table']['rows'])==8
        assert indep['conditions']['guard']['cue_point_metrics_binding'] is False
        sem=n.semantic(data['calibration_semantic'],pack)
        assert sem['n_blocks']==2 and sem['n_semantic_episodes']==16
        assert sem['shared']['checks']['noise_replay_integrity'] is True
        assert sem['shared']['n_unique_positive_cues']>0
        assert sem['shared']['checks']['n_unique_positive_cues_ge_min'] is False
        wrapped=consumer.wrap_report('semantic','calibration','main','historical',
                        data['calibration_semantic'].spec.namespace,sem)
        with pytest.raises(consumer.InputError):
            consumer.semantic_gate(wrapped,'calibration','main','historical',pack['recall_floor'])
        validation = make_corpus(spec_for('validation','calibration_matched','historical',2),pack)
        with pytest.raises(i.SampleError): loaded.for_eval(validation,pack)
        bad_checkpoint=copy.deepcopy(checkpoint);bad_checkpoint['envelope_sha256']='0'*64
        with pytest.raises(i.SampleError):
            n.FrozenV2.load(tmp_path/'v2.json',bad_checkpoint,data['fit'],pack)
        loaded.native.namespace='fixture_c2_native_validation_fit_v1'
        with pytest.raises(i.SampleError): loaded.check()
    assert all(v==0 for v in audit.result()['blocked'].values())
    assert audit.result()['native_calls']['rl_curriculum.evaluator.run_policy_episode']>0


def test_native_design_receives_explicit_blocks():
    pack=n.engineering_pack('historical',.95-.02)
    data=make_corpus(spec_for('main','design_matched','historical',2),pack)
    with NativeCallAudit() as audit:
        report=n.design_matched(data,pack)
    assert report['n_blocks']==2
    assert set(report['per_formal_block_count'])=={'10','15','20'}
    assert all(v==0 for v in audit.result()['blocked'].values())


def test_parameter_drift_rejected_before_evaluation(samples):
    pack,data=samples
    bad=copy.deepcopy(pack)
    bad['c2_ladder']['D3']['alpha_bps']+=1
    with pytest.raises(i.SampleError):
        n.matched(data['calibration_matched'],bad,None)
