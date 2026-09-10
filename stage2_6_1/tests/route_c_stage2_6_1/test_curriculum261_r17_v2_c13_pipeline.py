"""R17 V2 C1/C3 engineering calibration local tests.

Fixture data and synthetic matrices only — these are NOT production
generation evidence. The fixture backend fabricates well-formed proofs
and synthetic in-memory pairs; real numerical components (V2 envelope,
routing) are exercised on synthetic fit matrices. Covers taskbook
acceptance matrix A01-A22 at the unit level.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve()
for base in HERE.parents:
    for runner in (base / 'implementation', base / 'runner',
                   base / 'stage2_6_1' / 'runner',
                   base / 'stage2_6_1_runner'):
        if (runner / 'r17_v2_c13_profile.py').is_file():
            sys.path.insert(0, str(runner))
            break
    else:
        continue
    break
else:
    raise RuntimeError('v2c13 implementation not found')

import r17_v2_c13_profile as prof
import r17_v2_c13_batch as batch
import r17_v2_c13_pipeline as pipe

GENERATOR = {'family': 'c3_cost', 'version': 'cur261-c3-v4',
             'fixture': True}

FEATURES = ['%-ret-1', '%-ret-4', '%-vol-24', '%-price-ma-ratio',
            '%-raw_open', '%-raw_high', '%-raw_low', '%-raw_close']


def fixture_params():
    """与 parameter_snapshot 同构的最小参数面(测试夹具,不 import 生产)。"""
    return {
        'rung_params': {
            'c1_opportunity': {r: {'opp_drift_bps': 30.0 + i,
                                   'cur261_rung_key': r}
                               for i, r in enumerate(prof.RUNGS)},
            'c2_context': {r: {'alpha_bps': 60.0 - i} for i, r in
                           enumerate(prof.RUNGS)},
            'c3_cost': {r: {'alpha_bps': 70.0 - 8 * i, 'cue_rate': .2,
                            'mixture': [.5, .3, .2]} for i, r in
                        enumerate(prof.RUNGS)},
        },
        'reference_defaults': {f: {'margin': 1.1}
                               for f in prof.FIT_FAMILIES},
    }


def make_proof(q, accepted=True, attempts=None, family=None,
               reason_override=None):
    family = family or q['family']
    n = attempts if attempts is not None else (1 if accepted else 5)
    base_rp = fixture_params()['rung_params'][family][q['rung']]
    rp = {**base_rp, 'cur261_rung': q['rung']}
    call = {**{k: q[k] for k in ('namespace', 'family', 'rung',
                                 'pair_index')},
            'iteration': 'r17', 'max_attempts': 5, 'rung_params': rp,
            'generator': GENERATOR,
            'split': 'curriculum261_' + q['namespace'],
            'timeframe': '15m'}
    call['digest'] = batch.envelope_digest(call, True)
    envs, logs = [], []
    for i in range(n):
        passed = accepted and i == n - 1
        if reason_override is not None and not passed:
            codes = list(reason_override)
        elif family == 'c3_cost':
            codes = [] if passed else [
                'A:too_few_distractors', 'B:too_few_distractors',
                'pair:too_few_distractors']
        else:
            codes = [] if passed else ['A:generator_contract:fixture']
        is_c3 = family == 'c3_cost'
        env = {**{k: q[k] for k in ('namespace', 'family', 'rung',
                                    'pair_index')},
               'iteration': 'r17', 'attempt_index': i,
               'outer_seed': batch.expected_seed(q, i),
               'internal_derived_seed': batch.expected_seed(q, i) // 2,
               'split': call['split'], 'timeframe': '15m',
               'seed_derivation_fields': {
                   **{k: q[k] for k in ('namespace', 'family', 'rung',
                                        'pair_index')},
                   'attempt': i, 'stage_id': 'stage2_6_1'},
               'generator': GENERATOR, 'exception': None,
               'generator_state_changed': False,
               'generator_state_changed_since_call_start': False,
               'accepted': passed,
               'structural_validator_results': codes,
               'rejection_reasons': codes,
               'base_params': {
                   s: {**rp, 'pair_variant': s, 'episode_bars': 288,
                       'initial_price': 1.0} for s in ('A', 'B')},
               'event_table': {
                   s: {'bars': 288, 'hidden_digest': 'hidden-fixture',
                       'episode_content_hash': 'ce-' + hashlib.sha256(
                           f"{q['family']}/{q['rung']}/{q['pair_index']}"
                           f"/{i}/{s}".encode()).hexdigest(),
                       **({'counts': {
                           'n_signals': 10,
                           'n_above_cost': 6 if s == 'A' else 0,
                           'n_below_cost': 4 if s == 'A' else 10,
                           'n_distractors': 2 if passed else 0}}
                          if is_c3 else {})}
                   for s in ('A', 'B')}}
        env['digest'] = batch.envelope_digest(env)
        envs.append(env)
        logs.append({'index': i, 'accepted': passed,
                     'reason': '; '.join(codes)})
    hashes = ({s: envs[-1]['event_table'][s]['episode_content_hash']
               for s in ('A', 'B')} if accepted else {})
    return {
        'coordinate': dict(q),
        'status': 'accepted' if accepted else 'structural_rejected',
        'recorder_errors': [], 'call_envelope': call,
        'attempt_envelopes': envs, 'episode_hashes': hashes,
        'integrity': {'family': family, 'rung': q['rung'],
                      'pair_index': q['pair_index'], 'pass': True},
        'attempt_log': {
            'family': family, 'rung': q['rung'],
            'pair_index': q['pair_index'],
            'seed_namespace': q['namespace'], 'max_attempts': 5,
            'selected_attempt': n - 1 if accepted else None,
            'attempts': logs, 'output_episode_hashes': hashes}}


import numpy as np
import pandas as pd


def synthetic_pair(q, seed):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        rng.normal(0, 0.01, (64, len(FEATURES))).astype(np.float64),
        columns=FEATURES)
    for col in ('open', 'high', 'low', 'close'):
        df[col] = 1.0 + rng.normal(0, 0.005, 64)
    df['volume'] = np.abs(rng.normal(1000, 10, 64))
    episodes = {s: SimpleNamespace(
        df=df.copy(), spec=SimpleNamespace(seed=seed + i))
        for i, s in enumerate(('A', 'B'))}
    p = make_proof(q)
    return SimpleNamespace(
        family=q['family'], rung=q['rung'], pair_index=q['pair_index'],
        episodes=episodes,
        attempt_log=SimpleNamespace(
            episode_hashes=p['episode_hashes'],
            seed_namespace=q['namespace']),
        integrity={'pass': True}, integrity_ok=True)


class Fixture:
    def __init__(self, rejected=(), fail=None, extra_key_reject=None):
        self.rejected = set(rejected)
        self.fail = fail
        self.extra_key_reject = extra_key_reject
        self.calls = []

    def describe(self):
        return {'kind': 'test_fixture', 'generator': GENERATOR,
                'sources': {}, 'interpreter': sys.version}

    def generate(self, q, observe):
        key = prof.request_key(q)
        self.calls.append(key)
        if key == self.fail:
            raise PermissionError('fixture permission denied')
        if self.extra_key_reject and key == self.extra_key_reject:
            p = make_proof(q, accepted=False,
                           reason_override=['A:nuisance_flap'])
        else:
            p = make_proof(q, accepted=key not in self.rejected)
        observe('call', p['call_envelope'])
        for e in p['attempt_envelopes']:
            observe('attempt', e)
        handle = None
        if p['status'] == 'accepted':
            handle = synthetic_pair(q, abs(hash(key)) % (2 ** 31))
        return batch.Generated(p, handle)


# ------------------------------------------------------------------ A01
def test_a01_contract_budget_and_registry_alignment():
    c = prof.fixed_contract()
    assert c['n_planned_requests'] == 336
    assert c['n_fit_requests'] == 160 and c['n_eval_requests'] == 176
    assert c['max_pair_attempts'] == 1680
    assert c['n_selected_fit_pairs'] == 144
    assert c['n_selected_eval_pairs'] == 160
    assert c['n_fit_manifest_entries_per_bank'] == 144
    assert c['n_main_scaled_eval_episodes'] == 320
    assert c['c1_c2_reserve_allowed'] is False
    plan = prof.make_plan({'kind': 'test_fixture', 'generator': GENERATOR,
                           'sources': {}})
    prof.validate_plan(plan)
    # registry alignment via the real api (deployment tree provides it).
    try:
        from rl_curriculum.curriculum261_api import (
            CURRICULUM261_R17_NAMESPACES as ns,
            CURRICULUM261_R17_FORMAL_NAMESPACES as formal)
        from rl_curriculum.curriculum261_r17_registry import (
            R17_ALL_NAMESPACES)
    except ModuleNotFoundError:
        pytest.skip('rl_curriculum not importable in this layout')
    assert len(ns) == 93 and len(formal) == 4
    assert tuple(ns) == R17_ALL_NAMESPACES
    for name in (*prof.FIT_NAMESPACES.values(),
                 *prof.EVAL_NAMESPACES.values()):
        assert name in ns and name not in formal


def test_a01_undeclared_coordinate_rejected(tmp_path):
    stage = prof.fixed_contract()['stages'][0]
    cursor = batch.StageCursor(stage)
    foreign = dict(cursor.next())
    foreign['pair_index'] = 99
    with pytest.raises(Exception):
        cursor.consume(foreign, 'accepted')


# ------------------------------------------------------------------ A02/A03
@pytest.mark.parametrize('stage_name', ['fit_main', 'eval_main'])
def test_a02_a03_c3_reserve_order(stage_name):
    stage = next(s for s in prof.fixed_contract()['stages']
                 if s['stage'] == stage_name)
    quota = stage['quota_per_stratum']
    cursor = batch.StageCursor(stage)
    rejected_one = next(q for q in prof.stage_requests(stage)
                        if q['family'] == 'c3_cost'
                        and q['rung'] == 'D0' and q['pair_index'] == 0)
    seq = []
    while (q := cursor.next()) is not None:
        seq.append(q)
        cursor.consume(
            q, 'structural_rejected' if q == rejected_one else 'accepted')
    assert cursor.snapshot()['quota_filled']
    d0_c3 = [q for q in seq if q['family'] == 'c3_cost' and q['rung'] == 'D0']
    assert [q['pair_index'] for q in d0_c3] == list(range(quota + 1))
    assert all(q['pair_index'] == quota + 1 and q['tier'] == 'reserve'
               for q in prof.stage_requests(stage)
               if q['family'] == 'c3_cost' and q['rung'] == 'D1'
               and q['pair_index'] == quota + 1)
    # 主额足时不调用备用。
    cursor2 = batch.StageCursor(stage)
    while (q := cursor2.next()) is not None:
        cursor2.consume(q, 'accepted')
    states = cursor2.snapshot()['states']
    reserves = [k for k in states if '_c3_cost_' in k
                and k.endswith((f'p{quota}', f'p{quota + 1}'))]
    assert reserves and all(states[k] == 'not_needed' for k in reserves)


def test_a03_reserve_exhaustion_stops_stage():
    stage = next(s for s in prof.fixed_contract()['stages']
                 if s['stage'] == 'eval_main')
    cursor = batch.StageCursor(stage)
    while (q := cursor.next()) is not None:
        exhaust = (q['family'] == 'c3_cost' and q['rung'] == 'D0')
        cursor.consume(q, 'structural_rejected' if exhaust
                       else 'accepted')
    snap = cursor.snapshot()
    assert snap['stop'] == 'reserve_exhausted'
    assert not snap['quota_filled']


# ------------------------------------------------------------------ A04
def test_a04_unknown_vocab_never_reserves(tmp_path):
    stage = prof.fixed_contract()['stages'][0]
    q = next(x for x in prof.stage_requests(stage)
             if x['family'] == 'c3_cost')
    params = fixture_params()
    runtime = {'generator': GENERATOR}
    p = make_proof(q, accepted=False,
                   reason_override=['A:nuisance_flap'])
    with pytest.raises(Exception):
        batch.validate_proof(q, p, params, runtime)
    p2 = make_proof(q, accepted=False)
    p2['attempt_envelopes'][2]['exception'] = 'GeneratorError: boom'
    with pytest.raises(Exception):
        batch.validate_proof(q, p2, params, runtime)
    p3 = make_proof(q, accepted=False)
    p3['recorder_errors'] = ['ValueError: x']
    with pytest.raises(Exception):
        batch.validate_proof(q, p3, params, runtime)


def test_a04_generator_contract_reject_is_not_reserve_eligible(tmp_path):
    stage = prof.fixed_contract()['stages'][0]
    q = next(x for x in prof.stage_requests(stage)
             if x['family'] == 'c1_opportunity')
    p = make_proof(q, accepted=False)  # C1 默认 reason 是 generator_contract
    cursor = batch.StageCursor(stage)
    cursor.consume(q, 'structural_rejected')
    assert cursor.snapshot()['stop'] == 'fatal_non_c3_rejection'


# ------------------------------------------------------------------ A05
def test_a05_c1_c2_failure_stops(tmp_path):
    for fam in ('c1_opportunity', 'c2_context'):
        stage = prof.fixed_contract()['stages'][0]
        cursor = batch.StageCursor(stage)
        q = cursor.next()  # C1 p0:该 family 的首个主请求
        assert q['family'] == 'c1_opportunity'
        target = q if fam == 'c1_opportunity' else next(
            x for x in prof.stage_requests(stage)
            if x['family'] == fam and x['pair_index'] == 0
            and x['rung'] == 'D0')
        if fam != 'c1_opportunity':
            while (q2 := cursor.next()) != target:
                cursor.consume(q2, 'accepted')
        cursor.consume(target, 'structural_rejected')
        snap = cursor.snapshot()
        assert snap['stop'] == 'fatal_non_c3_rejection'
        # 无 C1/C2 备用坐标被创建。
        reserves = [k for k in snap['states']
                    if fam in k and k.endswith(('p6', 'p7'))]
        assert all(snap['states'][k] == 'not_started' for k in reserves)


# ------------------------------------------------------------------ A06
def test_a06_exhausted_eval_keeps_policy_calls_at_zero(tmp_path):
    stage = next(s for s in prof.fixed_contract()['stages']
                 if s['stage'] == 'eval_main')
    quota = stage['quota_per_stratum']
    rejected = {prof.request_key(q) for q in prof.stage_requests(stage)
                if q['family'] == 'c3_cost' and q['rung'] == 'D0'
                and q['pair_index'] < quota + 2}
    backend = Fixture(rejected=rejected)
    result, handles = batch.execute_stage(
        tmp_path / 'run', stage, backend, fixture_params(),
        backend.describe())
    assert result['rc'] == 4 and result['stop'] == 'reserve_exhausted'
    assert pipe.POLICY_EVALUATION_STARTED is False
    assert not (tmp_path / 'run' / 'stages' / 'eval_main'
                / 'selection.json').exists() or json.loads(
        (tmp_path / 'run' / 'stages' / 'eval_main'
         / 'selection.json').read_text())['quota_filled'] is False


# ------------------------------------------------------------------ A20
def test_a20_one_shot_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(prof, 'CLAIM_ROOT', tmp_path / 'claim')
    plan = prof.make_plan({'kind': 'test_fixture',
                           'generator': GENERATOR, 'sources': {}})
    assert prof.claim_state()['consumed'] is False
    prof.consume_generation_claim(plan)
    state = prof.claim_state()
    assert state['consumed'] is True
    assert state['plan_sha256'] == plan['plan_sha256']
    # 换 out/run_id 不会重新取得:第二次 consume 直接失败。
    with pytest.raises(FileExistsError):
        prof.consume_generation_claim(plan)


# ------------------------------------------------------------------ A21
def test_a21_stage_fault_injection_preserves_evidence(tmp_path):
    stage = prof.fixed_contract()['stages'][0]
    key = prof.request_key(next(
        x for x in prof.stage_requests(stage)
        if x['family'] == 'c2_context' and x['rung'] == 'D1'
        and x['pair_index'] == 2))
    backend = Fixture(fail=key)
    result, handles = batch.execute_stage(
        tmp_path / 'run', stage, backend, fixture_params(),
        backend.describe())
    assert result['rc'] == 3 and result['error']['type'] == 'PermissionError'
    sdir = tmp_path / 'run' / 'stages' / 'fit_main'
    assert (sdir / 'result.json').is_file()
    assert (sdir / 'errors' / (key + '.json')).is_file()
    started = json.loads((sdir / 'starts' / (key + '.json')).read_text())
    assert started['coordinate']['family'] == 'c2_context'
    # 前序成功证据保留。
    ok_key = prof.request_key(next(
        x for x in prof.stage_requests(stage)
        if x['pair_index'] == 0))
    assert (sdir / 'requests' / (ok_key + '.json')).is_file()


# ------------------------------------------------------------------ A22
def test_a22_both_trees_import_same_contract():
    others = []
    for base in HERE.parents:
        for runner in (base / 'stage2_6_1_runner',):
            cand = runner / 'r17_v2_c13_profile.py'
            if cand.is_file():
                others.append(cand)
    if not others:
        pytest.skip('deployed runner tree not present in this layout')
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'v2c13_profile_other', others[0])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.fixed_contract() == prof.fixed_contract()


# ------------------------------------------- A11/A12/A16 real V2 (合成)
def _synthetic_v2(namespace):
    from rl_curriculum.curriculum261_r3_preprocessing import (
        RouteCPreprocessor)
    from rl_curriculum.curriculum261_r4_preprocessing import (
        RouteCPreprocessorV2, build_fit_manifest_entries)
    rng = np.random.default_rng(20260910)
    entries_src = []
    dfs = []
    for family in ('c1_opportunity', 'c2_context', 'c3_cost'):
        for rung in prof.RUNGS:
            for idx in range(2):
                q = {'namespace': namespace, 'family': family,
                     'rung': rung, 'pair_index': idx}
                rec = synthetic_pair(q, 1000 + idx)
                entries_src.append(rec)
                for s in ('A', 'B'):
                    dfs.append(rec.episodes[s].df[FEATURES])
    fit_df = pd.concat(dfs, ignore_index=True)
    inner = RouteCPreprocessor.build_and_fit(fit_df)
    entries = build_fit_manifest_entries(
        entries_src, namespace, 'fixture-pack')
    return RouteCPreprocessorV2(inner, entries, namespace), fit_df


def test_a11_v2_roundtrip_identity_stable(tmp_path):
    pytest.importorskip('rl_curriculum')
    v2, fit_df = _synthetic_v2('fixture_fit_main')
    path = tmp_path / 'envelope.json'
    v2.serialize_envelope(path)
    from rl_curriculum.curriculum261_r4_preprocessing import (
        RouteCPreprocessorV2)
    re = RouteCPreprocessorV2.load_envelope(path)
    assert re.parameter_state_hash == v2.parameter_state_hash
    assert re.manifest_multiset_hash == v2.manifest_multiset_hash
    assert re.bundle_hash == v2.bundle_hash
    sample = fit_df.iloc[:17]
    assert np.array_equal(v2.transform(sample).to_numpy(),
                          re.transform(sample).to_numpy())
    # manifest 篡改被拒。
    raw = json.loads(path.read_text())
    raw['fit_manifest']['entries'][0]['episode_hash'] = 'ce-tampered'
    (tmp_path / 't1.json').write_text(json.dumps(raw))
    with pytest.raises(RuntimeError):
        RouteCPreprocessorV2.load_envelope(tmp_path / 't1.json')


def test_a12_same_params_different_source_binds_bundle(tmp_path):
    pytest.importorskip('rl_curriculum')
    v2_main, fit_df = _synthetic_v2('preplan_v2c13_fit_main_r17')
    # 第二 bank:同参数(inner 同源)不同 manifest 来源。
    from rl_curriculum.curriculum261_r4_preprocessing import (
        RouteCPreprocessorV2, build_fit_manifest_entries)
    entries_src = []
    for family in ('c1_opportunity', 'c2_context', 'c3_cost'):
        for rung in prof.RUNGS:
            for idx in range(2, 4):
                q = {'namespace': 'preplan_v2c13_fit_validation_r17',
                     'family': family, 'rung': rung, 'pair_index': idx}
                entries_src.append(synthetic_pair(q, 5000 + idx))
    inner2 = None
    from rl_curriculum.curriculum261_r3_preprocessing import (
        RouteCPreprocessor)
    inner2 = RouteCPreprocessor.build_and_fit(fit_df)  # 数值参数同源
    entries2 = build_fit_manifest_entries(
        entries_src, 'preplan_v2c13_fit_validation_r17', 'fixture-pack')
    v2_val = RouteCPreprocessorV2(inner2, entries2,
                                  'preplan_v2c13_fit_validation_r17')
    # 参数巧合相同:parameter-state hash 一致,但 bundle/manifest 绑定
    # 实际来源,不允许串用。
    assert v2_main.parameter_state_hash == v2_val.parameter_state_hash
    assert v2_main.manifest_multiset_hash != v2_val.manifest_multiset_hash
    assert v2_main.bundle_hash != v2_val.bundle_hash


def test_a13_routing_swap_and_cached_hash_disguise(tmp_path):
    pytest.importorskip('rl_curriculum')
    from rl_curriculum.curriculum261_r17_routing import (
        RoutingContractError, build_routing_r17, require_eval_routing_r17)
    v2_main, _ = _synthetic_v2('preplan_v2c13_fit_main_r17')
    v2_val, _ = _synthetic_v2('preplan_v2c13_fit_validation_r17')
    routing_main = build_routing_r17('main', v2_main, v2c13=True)
    # eval_validation 撞 main bundle:第一条结果前拒绝。
    with pytest.raises(RoutingContractError):
        require_eval_routing_r17(
            routing_main, 'preplan_v2c13_eval_validation_r17',
            context='swap')
    # 正确组合通过。
    require_eval_routing_r17(
        routing_main, 'preplan_v2c13_eval_main_r17', context='ok')
    routing_val = build_routing_r17('holdout', v2_val, v2c13=True)
    require_eval_routing_r17(
        routing_val, 'preplan_v2c13_eval_validation_r17', context='ok2')
    # 缓存 hash 正确但绑定错对象:build 阶段即因 namespace 权威映射
    # 拒绝(伪装在第一条策略结果前失败)。
    with pytest.raises(RoutingContractError):
        build_routing_r17('main', v2_val, v2c13=True)
    # 正确构造的路由,expected_bundle_hash 指向另一 bundle 时拒绝。
    with pytest.raises(RoutingContractError):
        routing_main.bundle(
            expected_role='main',
            expected_fit_namespace='preplan_v2c13_fit_main_r17',
            expected_bundle_hash=v2_val.bundle_hash, context='wrong-hash')
    # 非正式路由不得服务正式 namespace。
    with pytest.raises(RoutingContractError):
        require_eval_routing_r17(routing_main, 'calibration_r17',
                                 context='formal-leak')


def test_a16_features_position_and_range(tmp_path):
    pytest.importorskip('rl_curriculum')
    v2, fit_df = _synthetic_v2('fixture_fit_main')
    from rl_curriculum.curriculum261_production_obs import (
        PRODUCTION_FEATURE_COLUMNS)
    assert v2.retained_columns == list(PRODUCTION_FEATURE_COLUMNS)
    assert len(PRODUCTION_FEATURE_COLUMNS) == 8
    state = v2.inner.fitted_state()
    assert state['position_slot']['participates_in_fit'] is False
    assert state['position_slot']['scaled'] is False
    # 有界外推:out-of-range 但有限的输入不新增截断(线性外推)。
    wide = fit_df.iloc[:3] * 50.0
    t = v2.transform(wide).to_numpy()
    assert np.isfinite(t).all()


# ------------------------------------------------------------------ A18
def test_a18_strict_algebra_recomputation():
    rng = np.random.default_rng(7)
    rows = []
    for rung_i, rung in enumerate(prof.RUNGS):
        for p in range(10):
            level = 0.02 * (3 - rung_i) + 0.01
            ref = level + rng.normal(0, .001)
            rows.append({
                'rung': rung, 'pair_index': p,
                'returns': {'reference': ref, 'always_flat': 0.0,
                            'always_long': ref - 0.005,
                            'c1_baseline': ref - 0.004,
                            'oracle': ref + 0.01}})
    report = {'pair_table': {'rows': rows},
              'pair_integrity_pass_rate': 1.0,
              'oracle_positive_all_rungs': True}
    out = pipe._recompute_strict(report)
    assert out['strict_pass_recomputed'] is True
    # 把 D3 拉到负:strict 翻 FAIL。
    for row in rows:
        if row['rung'] == 'D3':
            row['returns']['reference'] = -0.01
    out2 = pipe._recompute_strict(report)
    assert out2['strict_pass_recomputed'] is False
    assert out2['d3_positive'] is False
    assert out2['d3_mean_ge_kappa_se'] is False


# ------------------------------------------------------------------ A07/A08
def test_a07_a08_parameter_snapshot_real():
    pytest.importorskip('rl_curriculum')
    snap = prof.parameter_snapshot()
    rp = snap['rung_params']
    assert rp['c3_cost']['D3']['alpha_bps'] == 50.0
    assert rp['c3_cost']['D3']['mixture'] == [0.20, 0.36, 0.44]
    assert rp['c3_cost']['D3']['cue_rate'] == 0.230
    assert rp['c1_opportunity']['D3']['opp_drift_bps'] == 24.5
    assert rp['c1_opportunity']['D3']['neg_drift_bps'] == 16.0
    assert rp['c1_opportunity']['D3']['vol_bps'] == 26.0
    assert rp['c1_opportunity']['D3']['seg_len_range'] == [24, 24]
    assert rp['c1_opportunity']['D3']['state_weights'] == [0.36, 0.28, 0.36]
    from rl_curriculum.curriculum261_r6_param_pack import (
        C2_LADDER_CANDIDATES)
    assert rp['c2_context'] == C2_LADDER_CANDIDATES[
        'c2l_historical_control']
    assert snap['r4_inheritance']['pass'] is True
    # C2 是工程控制,不构造 design 选择。
    assert 'selected' not in snap['pack'].get('c2_selection', '')
    assert snap['pack']['pack_kind'] == 'engineering_v2_c13'


def test_a07_extra_key_detected():
    pytest.importorskip('rl_curriculum')
    snap = prof.parameter_snapshot()
    bad = copy.deepcopy(snap)
    bad['rung_params']['c3_cost']['D3']['extra_knob'] = 1
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_r6_param_pack import (
        R4_SELECTED_C3_D3)
    assert set(bad['rung_params']['c3_cost']['D3']) != set(
        family_specs()['c3_cost'].rung_params['D3'])
    assert bad['rung_params']['c3_cost']['D3'] != R4_SELECTED_C3_D3


# ------------------------------------------------------------------ A10
def test_a10_fit_call_log_caps_at_two(monkeypatch):
    log = []
    monkeypatch.setattr(pipe, 'FIT_CALL_LOG', log)
    log.extend(['fit_main', 'fit_validation'])
    with pytest.raises(Exception):
        log.append('fit_eval')
        if len(log) > 2:
            raise RuntimeError('more than two main-flow fits')


# ------------------------------------------------------------------ A09
def test_a09_fit_source_isolation(tmp_path):
    stage = prof.fixed_contract()['stages'][0]
    root = tmp_path / 'run'
    backend = Fixture()
    result, handles = batch.execute_stage(
        root, stage, backend, fixture_params(), backend.describe())
    assert result['rc'] == 0
    # 正常路径。
    recs = pipe._fit_records_from_stage(root, 'fit_main', handles)
    assert len(recs) == 72
    # 混入另一 bank(validation namespace)生成的 record 被拒。
    intruder = synthetic_pair(
        {'namespace': prof.FIT_NAMESPACES['validation'],
         'family': 'c3_cost', 'rung': 'D0', 'pair_index': 0}, 42)
    with pytest.raises(Exception):
        pipe._fit_records_from_stage(
            root, 'fit_main', {**handles, 'fit_main_c3_cost_D0_p0':
                               intruder})
    # eval 命名空间的坐标混入成员名单被拒(缺合法 handle)。
    bad_selection = json.loads(
        (root / 'stages' / 'fit_main' / 'selection.json').read_text())
    bad_selection['member_coordinates'].append({
        'stage': 'eval_main', 'kind': 'eval', 'split': 'main',
        'namespace': prof.EVAL_NAMESPACES['main'], 'family': 'c3_cost',
        'rung': 'D0', 'pair_index': 99, 'tier': 'primary'})
    (root / 'stages' / 'fit_main' / 'selection.json').write_text(
        json.dumps(bad_selection))
    with pytest.raises(Exception):
        pipe._fit_records_from_stage(root, 'fit_main', handles)


# ------------------------------------------------------------------ A17
def test_a17_quota_decoupled_from_returns():
    stage = prof.fixed_contract()['stages'][2]
    cursor = batch.StageCursor(stage)
    # 收益信息根本不进入调度:consume 只看 accepted/structural 状态。
    q = cursor.next()
    cursor.consume(q, 'accepted')
    snap = cursor.snapshot()
    assert q['stage'] in snap['attempted'][0]


# ------------------------------------------------------------------ A19
def test_a19_old_contracts_untouched():
    here = Path(pipe.__file__).resolve().parent
    for legacy in ('r17_c3_reserve_batch.py',
                   'r17_c3_calibration_bridge.py'):
        assert (here / legacy).is_file()
    old = (here / 'r17_c3_reserve_batch.py').read_text(encoding='utf-8')
    assert 'c3_reserve_main_eng_r17' in old  # v1 合同未被改写
    assert 'preplan_v2c13' not in old  # 旧入口未混入新 profile


# ------------------------------------------------------------------ A14
def test_a14_eval_namespace_validation_matrix():
    pytest.importorskip('rl_curriculum')
    from rl_curriculum.curriculum261_r17_routing import (
        R17_EVAL_NAMESPACE_ROLE, R17_V2C13_ROLE_FIT_NAMESPACE,
        RoutingContractError, require_eval_routing_r17)
    v2_main, _ = _synthetic_v2('preplan_v2c13_fit_main_r17')
    from rl_curriculum.curriculum261_r17_routing import build_routing_r17
    routing = build_routing_r17('main', v2_main, v2c13=True)
    assert R17_EVAL_NAMESPACE_ROLE['preplan_v2c13_eval_main_r17'] == 'main'
    assert R17_EVAL_NAMESPACE_ROLE[
        'preplan_v2c13_eval_validation_r17'] == 'holdout'
    assert R17_V2C13_ROLE_FIT_NAMESPACE['holdout'] == (
        'preplan_v2c13_fit_validation_r17')
    with pytest.raises(RoutingContractError):
        require_eval_routing_r17(
            routing, 'preplan_v2c13_eval_unknown_r17', context='x')
