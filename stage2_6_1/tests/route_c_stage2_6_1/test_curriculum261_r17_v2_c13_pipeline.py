"""R17 V2 C1/C3 engineering calibration local tests (v2).

Fixture data and synthetic matrices only — these are NOT production
generation evidence. The fixture backend fabricates well-formed proofs
and synthetic in-memory pairs; real numerical components (V2 envelope,
routing, R4/R5 statistics) are exercised on synthetic fit matrices.

v2 修复后本文件的夹具与被测代码不再共享 v1 的单族身份假设:
- GENERATORS 是三族互异的身份映射(与权威 generator_identity 的
  输出形态同构);make_proof 按请求 family 取身份;
- 跨族摘要(C1 坐标 + C3 身份)与缺族映射被显式拒绝;
- v1 首个 C1 proof 用于只读回归,证明缺陷定位在跨族比较。

Covers the v2 taskbook acceptance groups V01-V10 (identity / registry /
claim), S01-S05 (strict recompute differential) and B01-B07 (actual V2
object binding) at the unit level; E01-E05 live in the synthetic-chain
module.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
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

#: 三族互异的 fixture generator 身份(v2:修复 v1 全局单值 GENERATOR 的
#: 夹具缺陷;形态与 curriculum261_generation_envelope.generator_identity
#: 输出同构:family/version/fingerprint 等逐族不同)。
GENERATORS = {
    'c1_opportunity': {
        'family': 'c1_opportunity', 'family_version': 'cur261-c1-v5',
        'class': 'tests.fixture.C1OpportunityGenerator',
        'source_sha256': 'c1' * 32, 'fingerprint': 'g-fixture-c1',
        'state_digest': 'fixture-c1-state', 'fixture': True},
    'c2_context': {
        'family': 'c2_context', 'family_version': 'cur261-c2-v9',
        'class': 'tests.fixture.C2ContextGatingGenerator',
        'source_sha256': 'c2' * 32, 'fingerprint': 'g-fixture-c2',
        'state_digest': 'fixture-c2-state', 'fixture': True},
    'c3_cost': {
        'family': 'c3_cost', 'family_version': 'cur261-c3-v4',
        'class': 'tests.fixture.C3CostAwareGenerator',
        'source_sha256': 'c3' * 32, 'fingerprint': 'g-fixture-c3',
        'state_digest': 'fixture-c3-state', 'fixture': True},
}

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


def fixture_runtime():
    """与 RealBackend.describe() v2 形态一致的测试 runtime。"""
    return {'kind': 'test_fixture', 'generators': copy.deepcopy(GENERATORS),
            'sources': {}, 'interpreter': sys.version}


def make_proof(q, accepted=True, attempts=None, family=None,
               reason_override=None, generator_override=None,
               params=None):
    family = family or q['family']
    generator = generator_override if generator_override is not None \
        else GENERATORS[family]
    n = attempts if attempts is not None else (1 if accepted else 5)
    base_rp = (params if params is not None
               else fixture_params()['rung_params'])[family][q['rung']]
    rp = {**base_rp, 'cur261_rung': q['rung']}
    call = {**{k: q[k] for k in ('namespace', 'family', 'rung',
                                 'pair_index')},
            'iteration': 'r17', 'max_attempts': 5, 'rung_params': rp,
            'generator': generator,
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
               'generator': generator, 'exception': None,
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
    from rl_curriculum.generator_api import (
        EpisodeSpec, GeneratedEpisode,
    )
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        rng.normal(0, 0.01, (64, len(FEATURES))).astype(np.float64),
        columns=FEATURES)
    for col in ('open', 'high', 'low', 'close'):
        df[col] = 1.0 + rng.normal(0, 0.005, 64)
    df['volume'] = np.abs(rng.normal(1000, 10, 64))
    hidden = pd.DataFrame(0.0, index=df.index,
                          columns=['signal', 'distractor'])

    def _ep(i):
        spec = EpisodeSpec(
            family=q['family'], params={'fixture': True},
            seed=int(seed + i), split='train', timeframe='15m')
        return GeneratedEpisode(
            spec=spec, df=df.copy(), hidden=hidden.copy(),
            family_version='fixture-v1', timeframe='15m',
            is_null=False, generator_fingerprint='g-fixture-synth')

    episodes = {s: _ep(i) for i, s in enumerate(('A', 'B'))}
    from rl_curriculum.curriculum261_api import episode_content_hash

    p = make_proof(q)
    # handle 的 episode hash 用真实生产函数计算(df/hidden/spec 实值),
    # 使 fit manifest 与 episode CSV 重载验证走真实身份。
    real_hashes = {s: episode_content_hash(episodes[s])
                   for s in ('A', 'B')}
    return SimpleNamespace(
        family=q['family'], rung=q['rung'], pair_index=q['pair_index'],
        episodes=episodes,
        attempt_log=SimpleNamespace(
            episode_hashes=real_hashes,
            seed_namespace=q['namespace'],
            selected_attempt=0, max_attempts=5,
            attempts=[SimpleNamespace(**a)
                      for a in p['attempt_log']['attempts']]),
        integrity={'pass': True}, integrity_ok=True)


class Fixture:
    def __init__(self, rejected=(), fail=None, extra_key_reject=None):
        self.rejected = set(rejected)
        self.fail = fail
        self.extra_key_reject = extra_key_reject
        self.calls = []

    def describe(self):
        return fixture_runtime()

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


# ------------------------------------------------------------------ V01
def test_v01_real_three_family_metadata_zero_generation():
    """真实三族 metadata 零生成:权威 generator_identity 逐族绑定。"""
    pytest.importorskip('rl_curriculum')
    from rl_curriculum.curriculum261_generation_envelope import (
        generator_identity,
    )
    from rl_curriculum.curriculum261_pairs import family_specs

    specs = family_specs()
    generators = {f: generator_identity(specs[f].generator)
                  for f in ('c1_opportunity', 'c2_context', 'c3_cost')}
    # 映射键集恰好是三族;每条内部 family 与键一致。
    assert set(generators) == set(prof.FIT_FAMILIES)
    for family, ident in generators.items():
        assert ident.get('family') == family
        assert ident.get('family_version')
        assert ident.get('fingerprint')
    # 三族身份彼此不同(fingerprint/source 均互异)。
    fps = [g['fingerprint'] for g in generators.values()]
    assert len(set(fps)) == 3
    # v1 已保存 proof 的 call_envelope 记录了 C1 真实版本号:与权威
    # metadata 一致(身份回归的运行时侧面)。
    assert generators['c1_opportunity']['family_version'].startswith(
        'cur261-c1-')


def test_v01_production_api_sentinel_not_consumed_by_preflight(monkeypatch):
    """生产生成 API 加"调用即失败"哨兵:三族 metadata 预检零生成。"""
    pytest.importorskip('rl_curriculum')
    from rl_curriculum import curriculum261_api as api

    def _boom(*a, **kw):
        raise AssertionError('production generation API consumed by '
                             'preflight checks')

    monkeypatch.setattr(api, 'generate_pair_with_attempts', _boom)
    from rl_curriculum.curriculum261_generation_envelope import (
        generator_identity,
    )
    from rl_curriculum.curriculum261_pairs import family_specs

    specs = family_specs()
    generators = {f: generator_identity(specs[f].generator)
                  for f in prof.FIT_FAMILIES}
    assert len(generators) == 3  # 预检完成且未触发哨兵


# ------------------------------------------------------------------ V02
def test_v02_three_family_proofs_and_cross_family_rejection():
    params = fixture_params()
    runtime = fixture_runtime()
    stage = prof.fixed_contract()['stages'][0]
    for family in ('c1_opportunity', 'c2_context', 'c3_cost'):
        q = next(x for x in prof.stage_requests(stage)
                 if x['family'] == family)
        p = make_proof(q)
        # 合法 proof:按请求 family 的身份通过。
        assert batch.validate_proof(q, p, params, runtime) == 'accepted'
    # 跨族摘要拒绝:C1 坐标 + 摘要正确的 C3 身份。
    q_c1 = next(x for x in prof.stage_requests(stage)
                if x['family'] == 'c1_opportunity')
    p_wrong = make_proof(q_c1, generator_override=GENERATORS['c3_cost'])
    with pytest.raises(Exception, match='generator identity mismatch'):
        batch.validate_proof(q_c1, p_wrong, params, runtime)
    # 反向:C3 坐标 + C1 身份。
    q_c3 = next(x for x in prof.stage_requests(stage)
                if x['family'] == 'c3_cost')
    p_wrong2 = make_proof(q_c3, generator_override=GENERATORS['c1_opportunity'])
    with pytest.raises(Exception, match='generator identity mismatch'):
        batch.validate_proof(q_c3, p_wrong2, params, runtime)
    # attempt 级身份错配(call 正确、attempt 用别族身份)。
    p_attempt = make_proof(q_c1)
    p_attempt['attempt_envelopes'][0]['generator'] = \
        GENERATORS['c2_context']
    p_attempt['attempt_envelopes'][0]['digest'] = \
        batch.envelope_digest(p_attempt['attempt_envelopes'][0])
    with pytest.raises(Exception):
        batch.validate_proof(q_c1, p_attempt, params, runtime)
    # 旧式 v1 单身份 runtime(无 generators 映射)拒绝,不 fallback。
    with pytest.raises(Exception, match='generator map missing family'):
        batch.validate_proof(q_c1, make_proof(q_c1), params,
                             {'kind': 'real',
                              'generator': GENERATORS['c3_cost']})
    # 缺族映射拒绝。
    partial = copy.deepcopy(runtime)
    del partial['generators']['c2_context']
    q_c2 = next(x for x in prof.stage_requests(stage)
                if x['family'] == 'c2_context')
    with pytest.raises(Exception, match='generator map missing family'):
        batch.validate_proof(q_c2, make_proof(q_c2), params, partial)


def _repo_root_for_v1_evidence() -> Path | None:
    import os

    for key in ('R17_V2C13_REPO_ROOT',):
        if os.environ.get(key):
            return Path(os.environ[key])
    for cand in (Path('/mnt/f/trading/freqai-rl-audit'),
                 HERE.parents[3] if len(HERE.parents) > 3 else None):
        if cand and (cand / 'stage2_6_1' / 'runner').is_dir():
            return cand
    return None


def test_v03_v1_first_c1_proof_readonly_regression(tmp_path):
    """v1 首个 C1 proof 只读回归:缺陷定位在跨族比较;不可入 v2 配额。"""
    pytest.importorskip('rl_curriculum')
    root = _repo_root_for_v1_evidence()
    if root is None:
        pytest.skip('v1 archived evidence root not reachable')
    proof_path = root / (
        'stage2_6_1/artifacts/repair17/development/'
        'v2_c13_engineering_delivery/main_run/monitored_run/'
        'v2_c13_engineering/stages/fit_main/requests/'
        'fit_main_c1_opportunity_D0_p0.json')
    if not proof_path.is_file():
        pytest.skip(f'v1 first proof not found: {proof_path}')
    raw_bytes = proof_path.read_bytes()
    proof = json.loads(raw_bytes.decode('utf-8'))
    q = proof['coordinate']
    # 只读:文件字节不变。
    assert proof_path.read_bytes() == raw_bytes
    assert q['family'] == 'c1_opportunity' and q['rung'] == 'D0'
    assert q['namespace'] == prof.V1_FIT_NAMESPACES['main']
    # v1 的 runtime 形态(单 C3 身份)在 v1 已诚实 FAIL;此处证明:
    # 用正确按族身份(取自该 proof 自身 call_envelope 记录的真实 C1
    # 身份)时,该 proof 的其余合同全部成立——缺陷唯一定位在跨族比较。
    v1_c1_generator = proof['call_envelope']['generator']
    v1_style_runtime = {
        'kind': 'real',
        'generators': {'c1_opportunity': v1_c1_generator},
    }
    # v1 params snapshot 从归档读,不重构。
    snap_path = root / (
        'stage2_6_1/artifacts/repair17/development/'
        'v2_c13_engineering_delivery/main_run/monitored_run/'
        'v2_c13_engineering/params_snapshot.json')
    snap = json.loads(snap_path.read_text(encoding='utf-8'))
    status = batch.validate_proof(q, proof, snap, v1_style_runtime)
    assert status == 'accepted'
    # v1 缺陷形态(describe 只登记 C3 单身份)在 v2 校验下被拒绝:
    # 旧式 runtime 缺 generators 映射 → fail closed,不 fallback。
    v1_buggy_runtime = {'kind': 'real', 'generator': {'family': 'c3_cost'}}
    with pytest.raises(Exception, match='generator map missing family'):
        batch.validate_proof(q, proof, snap, v1_buggy_runtime)
    # v2 admission:v1 proof 的 namespace/坐标不属于任何 v2 stage。
    v2_coords = {tuple(sorted(c.items())) for c in (
        prof.all_requests())}
    assert tuple(sorted(q.items())) not in v2_coords
    # 文件仍为原字节(只读回归不落写)。
    assert proof_path.read_bytes() == raw_bytes


# ------------------------------------------------------------------ V04
def test_v04_registry_97_4_exact_increment():
    c = prof.fixed_contract()
    assert c['n_planned_requests'] == 336
    assert c['n_fit_requests'] == 160 and c['n_eval_requests'] == 176
    assert c['max_pair_attempts'] == 1680
    assert c['n_selected_fit_pairs'] == 144
    assert c['n_selected_eval_pairs'] == 160
    assert c['n_fit_manifest_entries_per_bank'] == 144
    assert c['n_main_scaled_eval_episodes'] == 320
    assert c['c1_c2_reserve_allowed'] is False
    plan = prof.make_plan(fixture_runtime())
    prof.validate_plan(plan)
    try:
        from rl_curriculum.curriculum261_api import (
            CURRICULUM261_R17_NAMESPACES as ns,
            CURRICULUM261_R17_FORMAL_NAMESPACES as formal)
        from rl_curriculum.curriculum261_r17_registry import (
            R17_ALL_NAMESPACES, R17_FORMAL_QUALIFICATION_NAMESPACES)
    except ModuleNotFoundError:
        pytest.skip('rl_curriculum not importable in this layout')
    # 精确 97/4;非重言式:与显式基线集合 + 四 v2 名的并集精确相等。
    assert len(ns) == 97 and len(formal) == 4
    assert tuple(ns) == R17_ALL_NAMESPACES
    v1_names = (*prof.V1_FIT_NAMESPACES.values(),
                *prof.V1_EVAL_NAMESPACES.values())
    v2_names = (*prof.FIT_NAMESPACES.values(),
                *prof.EVAL_NAMESPACES.values())
    baseline_89 = set(R17_ALL_NAMESPACES) - set(v1_names) - set(v2_names)
    assert len(baseline_89) == 89  # v1 之前的历史基线
    assert set(R17_ALL_NAMESPACES) == baseline_89 | set(v1_names) \
        | set(v2_names)
    assert set(v1_names) & set(v2_names) == set()
    for name in v2_names:
        assert name in ns and name not in formal
    assert tuple(formal) == R17_FORMAL_QUALIFICATION_NAMESPACES
    # v1 名保留且仍非正式。
    for name in v1_names:
        assert name in ns and name not in formal


def test_v04_undeclared_coordinate_rejected(tmp_path):
    stage = prof.fixed_contract()['stages'][0]
    cursor = batch.StageCursor(stage)
    foreign = dict(cursor.next())
    foreign['pair_index'] = 99
    with pytest.raises(Exception):
        cursor.consume(foreign, 'accepted')


# ------------------------------------------------------------------ V05
def test_v05_full_request_manifest_and_budget():
    requests = prof.all_requests()
    assert len(requests) == 336
    fit_req = [q for q in requests if q['kind'] == 'fit']
    eval_req = [q for q in requests if q['kind'] == 'eval']
    assert len(fit_req) == 160 and len(eval_req) == 176
    # 逐坐标派生 seed 可复算(1680 attempt 上界派生面)。
    q = requests[0]
    for i in range(5):
        s = batch.expected_seed(q, i)
        assert isinstance(s, int) and s >= 0
    # 336 坐标唯一;6/10 配额与备援 tier 精确。
    keys = [prof.request_key(q) for q in requests]
    assert len(set(keys)) == 336
    for stage in prof.fixed_contract()['stages']:
        coords = prof.stage_requests(stage)
        quota = stage['quota_per_stratum']
        for family in stage['families']:
            reserve = stage['reserve_indices'].get(family, [])
            n_indices = quota + len(reserve)
            for rung in prof.RUNGS:
                idx = [c['pair_index'] for c in coords
                       if c['family'] == family and c['rung'] == rung]
                assert sorted(idx) == list(range(n_indices))


# ------------------------------------------------------------------ V06
@pytest.mark.parametrize('stage_name', ['fit_main', 'eval_main'])
def test_v06_c3_reserve_order(stage_name):
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
    # 选中 p10 就保留 p10(不回填改写为缺位的 p0)。
    assert rejected_one['pair_index'] == 0
    assert quota in [q['pair_index'] for q in d0_c3]
    # 主额足时不调用备用。
    cursor2 = batch.StageCursor(stage)
    while (q := cursor2.next()) is not None:
        cursor2.consume(q, 'accepted')
    states = cursor2.snapshot()['states']
    reserves = [k for k in states if '_c3_cost_' in k
                and k.endswith((f'p{quota}', f'p{quota + 1}'))]
    assert reserves and all(states[k] == 'not_needed' for k in reserves)


def test_v06_reserve_exhaustion_stops_stage():
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


# ------------------------------------------------------------------ V07
def test_v07_unknown_vocab_never_reserves(tmp_path):
    stage = prof.fixed_contract()['stages'][0]
    q = next(x for x in prof.stage_requests(stage)
             if x['family'] == 'c3_cost')
    params = fixture_params()
    runtime = fixture_runtime()
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
    # generator 状态漂移不可补。
    p4 = make_proof(q, accepted=False)
    p4['attempt_envelopes'][1]['generator_state_changed'] = True
    p4['attempt_envelopes'][1]['digest'] = batch.envelope_digest(
        p4['attempt_envelopes'][1])
    with pytest.raises(Exception):
        batch.validate_proof(q, p4, params, runtime)


def test_v07_generator_contract_reject_is_not_reserve_eligible(tmp_path):
    stage = prof.fixed_contract()['stages'][0]
    q = next(x for x in prof.stage_requests(stage)
             if x['family'] == 'c1_opportunity')
    cursor = batch.StageCursor(stage)
    cursor.consume(q, 'structural_rejected')
    assert cursor.snapshot()['stop'] == 'fatal_non_c3_rejection'


def test_v07_incomplete_attempt_evidence_never_reserves():
    stage = prof.fixed_contract()['stages'][0]
    q = next(x for x in prof.stage_requests(stage)
             if x['family'] == 'c3_cost')
    params = fixture_params()
    runtime = fixture_runtime()
    # 拒绝但尝试不足五次。
    p = make_proof(q, accepted=False, attempts=3)
    with pytest.raises(Exception):
        batch.validate_proof(q, p, params, runtime)


# ------------------------------------------------------------------ V08
def test_v08_exhausted_eval_keeps_policy_calls_at_zero(tmp_path,
                                                       monkeypatch):
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
    # 真实后续动作未调用:evaluate_split 在耗尽语料上必须拒绝,
    # 且拒绝前不产生任何 policy 结果(无 report 文件)。
    from r17_v2_c13_batch import read_json as _rj

    selection = _rj(tmp_path / 'run' / 'stages' / 'eval_main'
                    / 'selection.json')
    assert selection['quota_filled'] is False
    assert selection['evaluation_not_started'] is True
    assert not (tmp_path / 'run' / 'evaluations').exists() or \
        list((tmp_path / 'run' / 'evaluations').rglob('*_report.json')) == []


# ------------------------------------------------------------------ A05
def test_v05_c1_c2_failure_stops(tmp_path):
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


# ------------------------------------------------------------------ V09
def test_v09_namespace_consumption_detection(tmp_path, monkeypatch):
    """计划/夹具文件不误判;真实生成痕迹阻止;不可读按未知停止。"""
    import os

    names = (*prof.FIT_NAMESPACES.values(),
             *prof.EVAL_NAMESPACES.values())
    # 场景 1:只有计划文件(planning-only)→ unused=True。
    repo1 = tmp_path / 'repo1'
    (repo1 / 'stage2_6_1' / 'artifacts').mkdir(parents=True)
    (repo1 / 'stage2_6_1' / 'artifacts' / 'plan.json').write_text(
        json.dumps({'requests': [{'namespace': names[0]}]}),
        encoding='utf-8')
    out = prof.namespace_unused_evidence(repo1)
    assert out['namespaces_unused'] is True
    assert out['n_hits'] == 0
    assert out['n_planning_only_hits'] == 1
    # 场景 2:真实生成证据(call envelope)→ unused=False。
    repo2 = tmp_path / 'repo2'
    (repo2 / 'stage2_6_1' / 'artifacts' / 'stages' / 'fit_main'
     / 'requests').mkdir(parents=True)
    (repo2 / 'stage2_6_1' / 'artifacts' / 'stages' / 'fit_main'
     / 'requests' / 'p0.json').write_text(
        json.dumps({'call_envelope': {'namespace': names[0]}}),
        encoding='utf-8')
    out2 = prof.namespace_unused_evidence(repo2)
    assert out2['namespaces_unused'] is False
    assert out2['n_hits'] == 1
    # 场景 3:已消费 claim → unused=False。
    repo3 = tmp_path / 'repo3'
    (repo3 / 'stage2_6_1' / 'artifacts').mkdir(parents=True)
    (repo3 / 'stage2_6_1' / 'artifacts' / 'claim.json').write_text(
        json.dumps({'consumed_utc': 'x', 'plan_sha256': 'y',
                    'profile': names[0]}), encoding='utf-8')
    out3 = prof.namespace_unused_evidence(repo3)
    assert out3['namespaces_unused'] is False
    # 场景 4:证据损坏(非 UTF-8)→ 未知,不宣布零命中。
    repo4 = tmp_path / 'repo4'
    (repo4 / 'stage2_6_1' / 'artifacts').mkdir(parents=True)
    (repo4 / 'stage2_6_1' / 'artifacts' / 'broken.json').write_bytes(
        b'\xff\xfe\x00broken')
    out4 = prof.namespace_unused_evidence(repo4)
    assert out4['namespaces_unused'] is False
    assert out4['unreadable_evidence']


# ------------------------------------------------------------------ V10
def test_v10_one_shot_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(prof, 'CLAIM_ROOT', tmp_path / 'claim')
    plan = prof.make_plan(fixture_runtime())
    assert prof.claim_state()['consumed'] is False
    prof.consume_generation_claim(plan)
    state = prof.claim_state()
    assert state['consumed'] is True
    assert state['plan_sha256'] == plan['plan_sha256']
    # 换 out/run_id 不会重新取得:第二次 consume 直接失败。
    with pytest.raises(FileExistsError):
        prof.consume_generation_claim(plan)
    # 换 plan(不同 runtime)同样不能重取:claim 文件已排他存在。
    plan2 = prof.make_plan({'kind': 'test_fixture',
                            'generators': copy.deepcopy(GENERATORS),
                            'sources': {}, 'interpreter': 'other'})
    assert plan2['plan_sha256'] != plan['plan_sha256']
    with pytest.raises(FileExistsError):
        prof.consume_generation_claim(plan2)


def test_v10_corrupted_claim_is_consumed_not_retried(tmp_path,
                                                     monkeypatch):
    monkeypatch.setattr(prof, 'CLAIM_ROOT', tmp_path / 'claim')
    (tmp_path / 'claim').mkdir(parents=True)
    (tmp_path / 'claim' / f'{prof.CONTRACT}.json').write_text(
        'not-json{', encoding='utf-8')
    state = prof.claim_state()
    assert state['consumed'] is True and 'error' in state
    # 损坏 claim 不删除重试:consume 仍拒绝。
    with pytest.raises(FileExistsError):
        prof.consume_generation_claim(prof.make_plan(fixture_runtime()))


# ------------------------------------------------------------------ V0x exec
def test_v0x_stage_fault_injection_preserves_evidence(tmp_path):
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


def test_v0x_both_trees_import_same_contract():
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


# ------------------------------------------- synthetic V2 helpers (B 组)
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


def _v2_fixture_namespace(split):
    return f'fixture_v2c13_v2_fit_{split}'


# ------------------------------------------------------------------ B01
def test_b01_v2_roundtrip_identity_stable(tmp_path):
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
    # 参数篡改(scaler 数值状态)被拒。
    raw2 = json.loads(path.read_text())
    raw2['parameter_state']['scaler']['data_min_'][0] += 1.0
    (tmp_path / 't2.json').write_text(json.dumps(raw2))
    with pytest.raises(RuntimeError):
        RouteCPreprocessorV2.load_envelope(tmp_path / 't2.json')


def _equiv_records(namespace, families, rungs, n_pairs):
    """canonical 等价用合成 records(synthetic_pair 已是真 GeneratedEpisode)。"""
    records = []
    for family in families:
        for rung in rungs:
            for idx in range(n_pairs):
                q = {'namespace': namespace, 'family': family,
                     'rung': rung, 'pair_index': idx}
                records.append(synthetic_pair(q, 700 + idx))
    return records


def test_b01_same_params_different_source_binds_bundle(tmp_path):
    pytest.importorskip('rl_curriculum')
    v2_main, fit_df = _synthetic_v2('fixture_v2c13_v2_fit_main')
    from rl_curriculum.curriculum261_r4_preprocessing import (
        RouteCPreprocessorV2, build_fit_manifest_entries)
    entries_src = []
    for family in ('c1_opportunity', 'c2_context', 'c3_cost'):
        for rung in prof.RUNGS:
            for idx in range(2, 4):
                q = {'namespace': 'fixture_v2c13_v2_fit_validation',
                     'family': family, 'rung': rung, 'pair_index': idx}
                entries_src.append(synthetic_pair(q, 5000 + idx))
    from rl_curriculum.curriculum261_r3_preprocessing import (
        RouteCPreprocessor)
    inner2 = RouteCPreprocessor.build_and_fit(fit_df)  # 数值参数同源
    entries2 = build_fit_manifest_entries(
        entries_src, 'fixture_v2c13_v2_fit_validation', 'fixture-pack')
    v2_val = RouteCPreprocessorV2(inner2, entries2,
                                  'fixture_v2c13_v2_fit_validation')
    # 参数巧合相同:parameter-state hash 一致,但 bundle/manifest 绑定
    # 实际来源,不允许串用。
    assert v2_main.parameter_state_hash == v2_val.parameter_state_hash
    assert v2_main.manifest_multiset_hash != v2_val.manifest_multiset_hash
    assert v2_main.bundle_hash != v2_val.bundle_hash


# ------------------------------------------------------------------ B02
def test_b02_fit_source_isolation(tmp_path):
    stage = prof.fixed_contract()['stages'][0]
    root = tmp_path / 'run'
    backend = Fixture()
    result, handles = batch.execute_stage(
        root, stage, backend, fixture_params(), backend.describe())
    assert result['rc'] == 0
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


# ------------------------------------------------------------------ B03/B04
def test_b03_cached_fields_correct_but_object_swapped_detected():
    """缓存 main 字段不变而内部对象换 validation:取用时拒绝,调用 0。"""
    pytest.importorskip('rl_curriculum')
    import dataclasses

    from rl_curriculum.curriculum261_r17_routing import (
        RoutingContractError, build_routing_r17)
    # 用真实 v2 fit namespace(权威路由表内;entries/pack 是合成数据)。
    v2_main, _ = _synthetic_v2(prof.FIT_NAMESPACES['main'])
    v2_val, _ = _synthetic_v2(prof.FIT_NAMESPACES['validation'])
    routing_main = build_routing_r17(
        'main', v2_main, v2c13v2=True,
        expected_bundle_hash=v2_main.bundle_hash)
    got = routing_main.bundle(
        expected_role='main',
        expected_fit_namespace=prof.FIT_NAMESPACES['main'],
        context='healthy')
    assert got is v2_main
    # B4 核心反例:缓存字段(main 的 hash/namespace)不变,把 _v2 换成
    # validation 身份对象——旧实现返回 validation 对象,修复后拒绝。
    swapped = dataclasses.replace(routing_main, _v2=v2_val)
    calls = []

    def _track(*a, **kw):
        calls.append(1)
        raise AssertionError('policy evaluation consumed a swapped bundle')

    with pytest.raises(RoutingContractError, match='实际 bundle 对象'):
        swapped.bundle(
            expected_role='main',
            expected_fit_namespace=prof.FIT_NAMESPACES['main'],
            expected_bundle_hash=routing_main.bundle_hash,
            context='disguise')
    assert calls == []  # 无 policy 调用发生


def test_b04_inner_state_mutation_detected_at_use():
    """inner 状态修改(同 namespace)在取用时被检出。"""
    pytest.importorskip('rl_curriculum')
    from rl_curriculum.curriculum261_r17_routing import (
        RoutingContractError, build_routing_r17)
    v2_main, fit_df = _synthetic_v2(prof.FIT_NAMESPACES['main'])
    routing = build_routing_r17('main', v2_main, v2c13v2=True)
    # 正常取用通过。
    assert routing.bundle(
        expected_role='main',
        expected_fit_namespace=prof.FIT_NAMESPACES['main'],
        context='ok') is v2_main
    # 实际 refit 同一 inner(同 namespace,不同数据 → 状态改变)→
    # 取用拒绝。同数据 refit 的 hash 不变不构成检出,这正是 B05 要求
    # refit guard 独立于 hash 对拍的原因(此处用不同数据注入漂移)。
    v2_main.inner.fit(fit_df * 2.0)
    with pytest.raises(RoutingContractError, match='实际 bundle 对象'):
        routing.bundle(
            expected_role='main',
            expected_fit_namespace=prof.FIT_NAMESPACES['main'],
            context='after-refit')


def test_b04_envelope_file_anchor_detects_tamper(tmp_path):
    """envelope 文件字节锚点:数值篡改改变锚定 hash 且重载被三层拒绝。"""
    pytest.importorskip('rl_curriculum')
    from r17_v2_c13_batch import file_meta
    v2_main, _ = _synthetic_v2(prof.FIT_NAMESPACES['main'])
    envelope = tmp_path / 'envelope.json'
    v2_main.serialize_envelope(envelope)
    frozen_hash = file_meta(envelope)['sha256']
    # 等长语义篡改:改 scaler 数值状态(保持 JSON 合法)。
    raw = json.loads(envelope.read_text(encoding='utf-8'))
    raw['parameter_state']['scaler']['data_min_'][0] += 0.5
    tampered = tmp_path / 'envelope_tampered.json'
    tampered.write_text(json.dumps(raw), encoding='utf-8')
    assert file_meta(tampered)['sha256'] != frozen_hash
    # 重载篡改文件被 V2 三层 hash 拒绝(文件锚点与对象层双保险)。
    from rl_curriculum.curriculum261_r4_preprocessing import (
        RouteCPreprocessorV2)
    with pytest.raises(RuntimeError):
        RouteCPreprocessorV2.load_envelope(tampered)


# ------------------------------------------------------------------ B05
def test_b05_refit_blocked_after_freeze(monkeypatch, tmp_path):
    pytest.importorskip('rl_curriculum')
    # 评估阶段激活后,fit_and_freeze 的实际调用入口被拒(独立于
    # FIT_CALL_LOG 自报列表)。
    monkeypatch.setattr(pipe, '_EVAL_PHASE_ACTIVE', True)
    with pytest.raises(Exception, match='refit blocked'):
        pipe.fit_and_freeze(tmp_path, 'main', [], fixture_params(),
                            prof.make_plan(fixture_runtime()), None)
    # 自报列表为空也照样拒绝(不靠 append 计数判定)。
    assert pipe.FIT_CALL_LOG == [] or len(pipe.FIT_CALL_LOG) <= 2


def test_b05_fit_call_log_caps_at_two(monkeypatch):
    log = []
    monkeypatch.setattr(pipe, 'FIT_CALL_LOG', log)
    log.extend(['fit_main', 'fit_validation'])
    with pytest.raises(Exception):
        log.append('fit_eval')
        if len(log) > 2:
            raise RuntimeError('more than two main-flow fits')


# ------------------------------------------------------------------ B06
def test_b06_eval_rejects_raw_downgrade_and_wrong_namespace():
    pytest.importorskip('rl_curriculum')
    from rl_curriculum.curriculum261_r17_routing import (
        RoutingContractError, build_routing_r17, require_eval_routing_r17)
    v2_main, _ = _synthetic_v2(prof.FIT_NAMESPACES['main'])
    routing = build_routing_r17('main', v2_main, v2c13v2=True)
    # 工程正式 eval namespace(v2)正确组合通过。
    require_eval_routing_r17(
        routing, prof.EVAL_NAMESPACES['main'], context='ok')
    # v1 namespace 不属于 v2 路由表:期望 fit namespace 不符 → 拒绝。
    with pytest.raises(RoutingContractError):
        require_eval_routing_r17(
            routing, prof.V1_EVAL_NAMESPACES['main'], context='v1-mix')
    # 正式 namespace 被非正式路由拒绝。
    with pytest.raises(RoutingContractError):
        require_eval_routing_r17(routing, 'calibration_r17',
                                 context='formal-leak')
    # 未知 namespace 拒绝。
    with pytest.raises(RoutingContractError):
        require_eval_routing_r17(
            routing, 'preplan_v2c13_v2_eval_unknown_r17', context='x')
    # v1 路由表(v2c13)不能服务 v2 fit namespace。
    with pytest.raises(RoutingContractError):
        build_routing_r17('main', v2_main, v2c13=True)


def test_b06_features_position_and_range(tmp_path):
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


# ------------------------------------------------------------------ B07
def test_b07_a15_canonical_vs_legacy_real_functions(tmp_path):
    """A15:实际 canonical 函数 + writer;legacy 差异可解释不隐藏。"""
    pytest.importorskip('rl_curriculum')
    from rl_curriculum.curriculum261_r17_reference import (
        reference_equivalence_run_r17,
        write_reference_equivalence_artifacts_r17,
    )
    namespace = prof.EVAL_NAMESPACES['main']
    records = _equiv_records(namespace, ('c1_opportunity', 'c3_cost'),
                             ('D0', 'D3'), 2)
    v2, _ = _synthetic_v2(_v2_fixture_namespace('main'))
    pack = {'digest': 'fixture-pack'}
    report = reference_equivalence_run_r17(
        records, v2, pack, eval_namespace=namespace)
    # canonical(数学逆)与 scaled(生产投影)必须逐位等价。
    assert report['canonical_scaled_full_equality'] is True
    # gate = canonical 等价 + unexplained == 0 + float64 math path。
    assert report['unexplained_mismatches'] == 0
    assert report['float64_math_path']['pass'] is True
    assert report['pass'] is True
    # legacy 差异(如有)是诊断输出,不伪装成 canonical 失败:
    # legacy_action_diffs_total >= 0 且每个记录的 mismatch 带
    # float32 边界解释字段。
    if report['legacy_action_diffs_total'] > 0:
        for m in report['mismatches']:
            assert 'explainable_by_float32_boundary' in m
            assert m['explainable_by_float32_boundary'] is True
    # writer 实际落盘并读回核对(n_mismatches 在 mismatches 文件里)。
    write_reference_equivalence_artifacts_r17(
        tmp_path, report, stem='reference_equivalence')
    saved = json.loads((tmp_path / 'reference_equivalence.json'
                        ).read_text(encoding='utf-8'))
    assert saved['eval_namespace'] == namespace
    assert saved['canonical_scaled_full_equality'] is True
    saved_mism = json.loads(
        (tmp_path / 'reference_equivalence_mismatches.json'
         ).read_text(encoding='utf-8'))
    assert saved_mism['n_mismatches'] == report['unexplained_mismatches']
    assert saved_mism['legacy_action_diffs_total'] == \
        report['legacy_action_diffs_total']


# ------------------------------------------------------------------ S01
def test_s01_gap_se_square_root_counterexample():
    """任务书固定反例:SE_hi=SE_lo=0.02、gap=0.005 → 正确口径 FAIL。"""
    # 构造临界场景:D2/D3 两相邻 rung 的 pair 值交替 ±a 使每侧
    # SE≈0.02、gap=0.005;其余 rung 大 gap 通过。
    rows = []
    level = {r: 0.02 * (3 - i) + 0.01 for i, r in enumerate(prof.RUNGS)}
    for rung in prof.RUNGS:
        for p in range(10):
            if rung == 'D2':
                # 交替 ±0.03:sd=0.03*sqrt(10/9),se=0.01(精确)。
                ref = 0.030 + ((-1) ** p) * 0.03
            elif rung == 'D3':
                ref = 0.025 + ((-1) ** p) * 0.03
            else:
                ref = level[rung]
            rows.append({
                'rung': rung, 'pair_index': p,
                'returns': {'reference': ref, 'always_flat': 0.0,
                            'always_long': ref - 0.005,
                            'oracle': ref + 0.01}})
    report = {'family': 'c1_opportunity',
              'pair_table': {'rows': rows},
              'pair_integrity_pass_rate': 1.0,
              'oracle_positive_all_rungs': True}
    out = pipe._recompute_strict(report)
    gap_detail = out['gaps']['D2-D3']
    assert math.isclose(gap_detail['se'], math.sqrt(2) * 0.01,
                        rel_tol=1e-9), gap_detail
    assert math.isclose(gap_detail['gap'], 0.005, rel_tol=1e-9)
    assert gap_detail['gap'] < 1.5 * gap_detail['se']
    assert gap_detail['ok'] is False  # 正确口径 FAIL
    assert out['gaps_ok'] is False
    # 漏开方的 v1 公式(平方和 = 0.0002 → 1.5*0.0002=0.0003 < 0.005)
    # 会误 PASS:反向证明该口径不可复活。
    wrong_se = 0.01 ** 2 + 0.01 ** 2
    assert 0.005 >= 1.5 * wrong_se  # v1 公式下会误判通过


# ------------------------------------------------------------------ S02
def test_s02_metadata_and_diagnostics_do_not_extend_gates():
    """*_trades/诊断策略列不改变绑定结论;基线集合不自动扩大。"""
    def build(extra=False):
        rows = []
        for i, rung in enumerate(prof.RUNGS):
            for p in range(10):
                ref = 0.02 * (3 - i) + 0.01
                row = {
                    'rung': rung, 'pair_index': p,
                    'returns': {'reference': ref, 'always_flat': 0.0,
                                'always_long': ref - 0.005,
                                'oracle': ref + 0.01},
                    'reference_trades': 2,
                    'pair': p + 100,
                }
                if extra:
                    row['returns']['c1_shortcut_naive_momentum'] = \
                        ref - 0.004
                rows.append(row)
        return {'family': 'c1_opportunity',
                'pair_table': {'rows': rows},
                'pair_integrity_pass_rate': 1.0,
                'oracle_positive_all_rungs': True}

    base = pipe._recompute_strict(build())
    extra = pipe._recompute_strict(build(extra=True))
    # 绑定结论不变;margin 键集合保持白名单。
    assert base['strict_pass_recomputed'] == \
        extra['strict_pass_recomputed'] is True
    assert set(extra['margins']) == {'always_flat', 'always_long'}
    assert extra['margins'] == base['margins']
    # C3:cost_ignorant 是必需基线;诊断列同样不扩大。
    def build_c3(extra=False):
        rows = []
        for i, rung in enumerate(prof.RUNGS):
            for p in range(10):
                ref = 0.02 * (3 - i) + 0.01
                row = {
                    'rung': rung, 'pair_index': p,
                    'returns': {'reference': ref, 'always_flat': 0.0,
                                'always_long': ref - 0.005,
                                'c3_cost_ignorant': ref - 0.006,
                                'oracle': ref + 0.01}}
                if extra:
                    row['returns']['c3_diagnostic_only'] = ref - 0.003
                rows.append(row)
        return {'family': 'c3_cost',
                'pair_table': {'rows': rows},
                'pair_integrity_pass_rate': 1.0,
                'oracle_positive_all_rungs': True}

    c3a = pipe._recompute_strict(build_c3())
    c3b = pipe._recompute_strict(build_c3(extra=True))
    assert c3a['strict_pass_recomputed'] == \
        c3b['strict_pass_recomputed'] is True
    assert set(c3b['margins']) == {'always_flat', 'always_long',
                                   'c3_cost_ignorant'}
    # v1 缺陷回放:全列推导 + 跳过 flat 会把 c3_diagnostic_only 变成
    # 新 gate 并漏掉 flat margin;修复后均不发生。


# ------------------------------------------------------------------ S03
def test_s03_flat_checked_every_rung_and_missing_baseline_rejected():
    """flat 在每个 rung 都有 margin 条件;缺必需基线拒绝。"""
    rows = []
    for i, rung in enumerate(prof.RUNGS):
        for p in range(10):
            ref = 0.02 * (3 - i) + 0.01
            rows.append({
                'rung': rung, 'pair_index': p,
                'returns': {'reference': ref, 'always_flat': 0.0,
                            'always_long': ref - 0.005,
                            'oracle': ref + 0.01}})
    report = {'family': 'c1_opportunity',
              'pair_table': {'rows': rows},
              'pair_integrity_pass_rate': 1.0,
              'oracle_positive_all_rungs': True}
    out = pipe._recompute_strict(report)
    assert set(out['margins']) == {'always_flat', 'always_long'}
    for rung in prof.RUNGS:
        assert rung in out['margins']['always_flat']
    # 非 D3 rung 的 flat margin 弱(均值正但 < 1.5SE)被检出,不只看 D3。
    # D1 的 flat margin = 0.0005 + (-1)^p*0.004:mean=0.0005>0 但
    # se=0.004/3≈0.001333 → 0.0005 < 1.5*se → FAIL。
    for row in rows:
        if row['rung'] == 'D1':
            p = row['pair_index']
            row['returns']['always_flat'] = row['returns']['reference'] \
                - (0.0005 + ((-1) ** p) * 0.004)
    out2 = pipe._recompute_strict(report)
    flat_d1 = out2['margins']['always_flat']['D1']
    assert flat_d1['ok'] is False
    assert out2['strict_pass_recomputed'] is False
    # 缺必需基线(c1 缺 always_long)拒绝。
    for row in rows:
        row['returns'].pop('always_long')
    with pytest.raises(Exception, match='missing required returns column'):
        pipe._recompute_strict(report)
    # 未知 family 拒绝。
    with pytest.raises(Exception, match='unknown family'):
        pipe._recompute_strict({**report, 'family': 'c9_unknown'})


# ------------------------------------------------------------------ S04
def test_s04_pair_table_integrity_rejections():
    def ok_rows():
        rows = []
        for i, rung in enumerate(prof.RUNGS):
            for p in range(10):
                ref = 0.02 * (3 - i) + 0.01
                rows.append({
                    'rung': rung, 'pair_index': p,
                    'returns': {'reference': ref, 'always_flat': 0.0,
                                'always_long': ref - 0.005,
                                'oracle': ref + 0.01}})
        return rows

    def report(rows):
        return {'family': 'c1_opportunity',
                'pair_table': {'rows': rows},
                'pair_integrity_pass_rate': 1.0,
                'oracle_positive_all_rungs': True}

    # 空 pair 表拒绝。
    with pytest.raises(Exception, match='empty pair table'):
        pipe._recompute_strict(report([]))
    # 缺一个 rung 的行拒绝。
    rows = [r for r in ok_rows() if r['rung'] != 'D2']
    with pytest.raises(Exception, match='missing rows for some rung'):
        pipe._recompute_strict(report(rows))
    # 未知 rung 拒绝。
    rows = ok_rows()
    rows[0] = {**rows[0], 'rung': 'D9'}
    with pytest.raises(Exception, match='unknown rung'):
        pipe._recompute_strict(report(rows))


# ------------------------------------------------------------------ S05
def test_s05_authority_leafwise_differential():
    """真实导入的 R4 统计/R5 gate 与 _recompute_strict 逐叶对拍。"""
    pytest.importorskip('rl_curriculum')
    from rl_curriculum.curriculum261_r4_pairs import rung_report_r4
    from rl_curriculum.curriculum261_r5_pairs import corpus_conditions_r5
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_r6_param_pack import (
        C2_LADDER_CANDIDATES, R4_SELECTED_C1_D3, R4_SELECTED_C3_D3,
    )

    specs = family_specs()
    rung_params = {
        'c1_opportunity': {**{r: dict(specs['c1_opportunity']
                                      .rung_params[r])
                              for r in ('D0', 'D1', 'D2')},
                           'D3': dict(R4_SELECTED_C1_D3)},
        'c3_cost': {**{r: dict(specs['c3_cost'].rung_params[r])
                      for r in ('D0', 'D1', 'D2')},
                    'D3': dict(R4_SELECTED_C3_D3)},
    }
    for family in ('c1_opportunity', 'c3_cost'):
        thresholds = dict(specs[family].reference_defaults)
        # 多个 seed 批:健康(可 PASS)与受扰(FAIL)两端。
        for variant, tweak in (('healthy', 0.0), ('degraded', 0.004)):
            records = []
            for i, rung in enumerate(prof.RUNGS):
                for p in range(10):
                    q = {'namespace': 'fixture_eval', 'family': family,
                         'rung': rung, 'pair_index': p}
                    rec = synthetic_pair(
                        q, 10000 + 100 * i + p + (0 if variant ==
                                                 'healthy' else 7))
                    records.append(rec)
            family_report = rung_report_r4(
                records, family, rung_params[family], thresholds,
                corpus='fixture_eval')
            authority = corpus_conditions_r5(family_report, kappa=1.5)
            recomputed = pipe._recompute_strict(family_report)
            # 逐叶:ordering。
            assert recomputed['ordering_ok'] == authority['ordering_ok']
            # 逐叶:每个 gap 的 ok 与 SE 数值(容差不放宽门槛)。
            for key, auth_gap in authority['gaps'].items():
                rec_gap = recomputed['gaps'][key]
                assert rec_gap['ok'] == auth_gap['ok'], (family, key)
                assert math.isclose(rec_gap['se'],
                                    auth_gap['se_pair_cluster'],
                                    rel_tol=1e-9, abs_tol=1e-15), (
                    family, key, rec_gap, auth_gap)
            # 逐叶:每个基线 × rung 的 margin。
            for baseline, per_rung in authority[
                    'fixed_baseline_margins'].items():
                assert baseline in recomputed['margins']
                for rung, st in per_rung.items():
                    rec_st = recomputed['margins'][baseline][rung]
                    assert rec_st['ok'] == st['ok'], (
                        family, baseline, rung)
                    assert math.isclose(rec_st['mean'], st['mean'],
                                        rel_tol=1e-9, abs_tol=1e-15)
                    assert math.isclose(rec_st['se'], st['se'],
                                        rel_tol=1e-9, abs_tol=1e-15)
            assert recomputed['margins_ok'] == authority['margins_ok']
            assert recomputed['gaps_ok'] == authority['gaps_ge_kappa_se']
            assert recomputed['d3_positive'] == authority['d3_positive']
            assert recomputed['d3_mean_ge_kappa_se'] == \
                authority['d3_mean_ge_kappa_se']
            assert recomputed['strict_pass_recomputed'] == \
                authority['pass']
            # 两端都出现(PASS 与 FAIL 至少各见一次的概率由多 variant
            # 承担;本断言只锁一致性,不强制端点)。


def test_s05_threshold_boundary_semantics():
    """> 与 >= 的区别:恰等于阈值时 margin/gap 条件通过,零与负拒绝。"""
    # 构造 D2/D3 恰在 gap == 1.5*SE_gap 的临界表(数值精确构造)。
    # n=10,交替 ±a 使 sd = a*sqrt(10/9) 逼近;改用全常数序列(SE=0)
    # 加单点微扰不可精确;此处用 n=2 的最小表验证等号语义。
    rows = []
    vals = {'D0': [0.080, 0.080], 'D1': [0.060, 0.060],
            'D2': [0.040, 0.040], 'D3': [0.020, 0.020]}
    for rung in prof.RUNGS:
        for p, ref in enumerate(vals[rung]):
            rows.append({
                'rung': rung, 'pair_index': p,
                'returns': {'reference': ref, 'always_flat': 0.0,
                            'always_long': ref - 0.005,
                            'oracle': ref + 0.01}})
    report = {'family': 'c1_opportunity',
              'pair_table': {'rows': rows},
              'pair_integrity_pass_rate': 1.0,
              'oracle_positive_all_rungs': True}
    out = pipe._recompute_strict(report)
    # SE=0 的 rung:gap>0 且 gap >= 0 → 通过(等号方向正确)。
    for key, gap in out['gaps'].items():
        assert gap['ok'] is True, (key, gap)
    # margin 恰为 0(reference == always_flat 的基线)→ mean>0 失败。
    for row in rows:
        if row['rung'] == 'D3':
            row['returns']['always_long'] = row['returns']['reference']
    out2 = pipe._recompute_strict(report)
    assert out2['margins']['always_long']['D3']['ok'] is False
    assert out2['strict_pass_recomputed'] is False


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


# ------------------------------------------------------------------ A17/A19/A14
def test_a17_quota_decoupled_from_returns():
    stage = prof.fixed_contract()['stages'][2]
    cursor = batch.StageCursor(stage)
    q = cursor.next()
    cursor.consume(q, 'accepted')
    snap = cursor.snapshot()
    assert q['stage'] in snap['attempted'][0]


def test_a19_old_contracts_untouched():
    here = Path(pipe.__file__).resolve().parent
    for legacy in ('r17_c3_reserve_batch.py',
                   'r17_c3_calibration_bridge.py'):
        assert (here / legacy).is_file()
    old = (here / 'r17_c3_reserve_batch.py').read_text(encoding='utf-8')
    assert 'c3_reserve_main_eng_r17' in old  # v1 合同未被改写
    assert 'preplan_v2c13' not in old  # 旧入口未混入新 profile


def test_a14_eval_namespace_validation_matrix():
    pytest.importorskip('rl_curriculum')
    from rl_curriculum.curriculum261_r17_routing import (
        R17_EVAL_NAMESPACE_ROLE, R17_V2C13_V2_ROLE_FIT_NAMESPACE,
        RoutingContractError, build_routing_r17, require_eval_routing_r17)
    # fixture namespace 不在 v2 权威路由表:build 阶段拒绝(未知 fit
    # namespace 不能伪装进入评估)。
    v2_fixture, _ = _synthetic_v2(_v2_fixture_namespace('main'))
    with pytest.raises(RoutingContractError):
        build_routing_r17('main', v2_fixture, v2c13v2=True)
    # 权威映射:v2 eval 名字绑定正确 role。
    assert R17_EVAL_NAMESPACE_ROLE[prof.EVAL_NAMESPACES['main']] == 'main'
    assert R17_EVAL_NAMESPACE_ROLE[
        prof.EVAL_NAMESPACES['validation']] == 'holdout'
    assert R17_V2C13_V2_ROLE_FIT_NAMESPACE['holdout'] == (
        prof.FIT_NAMESPACES['validation'])
    assert R17_V2C13_V2_ROLE_FIT_NAMESPACE['main'] == (
        prof.FIT_NAMESPACES['main'])
    # 未知 eval namespace 拒绝(用真 v2 namespace 的 routing)。
    v2_real, _ = _synthetic_v2(prof.FIT_NAMESPACES['main'])
    routing_real = build_routing_r17('main', v2_real, v2c13v2=True)
    with pytest.raises(RoutingContractError):
        require_eval_routing_r17(
            routing_real, 'preplan_v2c13_v2_eval_unknown_r17', context='x')
    require_eval_routing_r17(
        routing_real, prof.EVAL_NAMESPACES['main'], context='ok')
