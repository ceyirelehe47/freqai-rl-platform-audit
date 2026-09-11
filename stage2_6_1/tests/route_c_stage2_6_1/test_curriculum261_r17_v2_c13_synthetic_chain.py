"""R17 V2 C1/C3 v2 合成链测试(S2;E01-E05 + 失败演练)。

与生产编排共用核心:通过 pipe.run() 的测试注入入口(backend/contract)
走完整链——计划、claim、四阶段生成、fit/save/reload/freeze、scaled
评估、canonical、R4/R5 统计、delivery/manifest 与 verify 冷读全部是
生产代码路径;仅生成边界替换为合成 Fixture,规模由声明为 synthetic 的
小合同承载(生产 336 合同另在 pipeline 测试精确核验)。

产物全部标记 synthetic;verify 不授予工程完成(不能冒充真实主数据)。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

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

from test_curriculum261_r17_v2_c13_pipeline import (  # noqa: E402
    GENERATORS, make_proof, synthetic_pair)

#: 小合同规模:fit 1/stratum(12 pair/bank),eval 3/stratum(12 pair/
#: family/split;canonical 前3=全部)。满足最小统计样本(每 rung>=2
#: pair 做 ddof=1 cluster 统计:eval 3 pair/rung)。
SMALL_FIT_QUOTA = 1
SMALL_EVAL_QUOTA = 3


def small_contract() -> dict:
    stages = []
    for split in ('main', 'validation'):
        stages.append({
            'stage': f'fit_{split}', 'kind': 'fit', 'split': split,
            'namespace': prof.FIT_NAMESPACES[split],
            'families': list(prof.FIT_FAMILIES),
            'quota_per_stratum': SMALL_FIT_QUOTA,
            'reserve_indices': {'c3_cost': [SMALL_FIT_QUOTA]},
        })
    for split in ('main', 'validation'):
        stages.append({
            'stage': f'eval_{split}', 'kind': 'eval', 'split': split,
            'namespace': prof.EVAL_NAMESPACES[split],
            'families': list(prof.EVAL_FAMILIES),
            'quota_per_stratum': SMALL_EVAL_QUOTA,
            'reserve_indices': {'c3_cost': [SMALL_EVAL_QUOTA]},
        })
    fit_req = sum(len(s['families']) * len(prof.RUNGS) * (
        s['quota_per_stratum'] + len(s['reserve_indices'].get(
            'c3_cost', []))) for s in stages if s['kind'] == 'fit')
    eval_req = sum(len(s['families']) * len(prof.RUNGS) * (
        s['quota_per_stratum'] + len(s['reserve_indices'].get(
            'c3_cost', []))) for s in stages if s['kind'] == 'eval')
    n_fit_pairs = SMALL_FIT_QUOTA * len(prof.FIT_FAMILIES) * len(
        prof.RUNGS)
    return {
        'version': prof.CONTRACT, 'engineering_only': True,
        'synthetic_profile': True,
        'purpose': 'synthetic-chain rehearsal profile; NOT the '
                   'authorized 336 engineering plan',
        'baseline': prof.BASELINE, 'parent': prof.PARENT,
        'rungs': list(prof.RUNGS), 'stages': stages,
        'namespaces': {'fit': dict(prof.FIT_NAMESPACES),
                       'eval': dict(prof.EVAL_NAMESPACES)},
        'formal_namespaces_touched': [],
        'max_pair_requests': fit_req + eval_req,
        'max_attempts_per_pair': 5,
        'max_pair_attempts': 5 * (fit_req + eval_req),
        'n_planned_requests': fit_req + eval_req,
        'n_fit_requests': fit_req, 'n_eval_requests': eval_req,
        'n_selected_pairs_total': 2 * n_fit_pairs + 2 * (
            SMALL_EVAL_QUOTA * len(prof.EVAL_FAMILIES) * len(
                prof.RUNGS)),
        'n_selected_fit_pairs': 2 * n_fit_pairs,
        'n_selected_eval_pairs': 2 * (
            SMALL_EVAL_QUOTA * len(prof.EVAL_FAMILIES) * len(
                prof.RUNGS)),
        'n_fit_manifest_entries_per_bank': 2 * n_fit_pairs,
        'n_main_scaled_eval_episodes': 2 * SMALL_EVAL_QUOTA * len(
            prof.EVAL_FAMILIES) * len(prof.RUNGS),
        'n_fit_pairs_per_bank': n_fit_pairs,
        'n_eval_pairs_per_family_per_split': SMALL_EVAL_QUOTA * len(
            prof.RUNGS),
        'canonical_pairs_per_split': min(3, SMALL_EVAL_QUOTA) * len(
            prof.EVAL_FAMILIES) * len(prof.RUNGS),
        'c3_reserve_allowed_rejections': sorted(prof.C3_ALLOWED_REJECTIONS),
        'c1_c2_reserve_allowed': False,
        'generation_before_evaluation': True,
        'abort_on_exhaustion': True,
        'eval_requires_both_bundles_frozen': True,
    }


class ChainFixture:
    """生成边界替身:用生产 params_snapshot 构造合法 proof + 合成 pair。"""

    def __init__(self, fail_at=None, reject=(), reason_override=None,
                 swap_generator_family=None):
        self.fail_at = fail_at
        self.reject = set(reject)
        self.reason_override = reason_override
        self.swap_generator_family = swap_generator_family
        self.calls = []
        self.params = None  # run() 首次 describe 前注入生产 snapshot

    def describe(self):
        return {'kind': 'test_fixture',
                'generators': copy.deepcopy(GENERATORS),
                'sources': {}, 'interpreter': sys.version}

    def generate(self, q, observe):
        key = prof.request_key(q)
        self.calls.append(key)
        if key == self.fail_at:
            raise PermissionError('synthetic chain fault injection')
        generator_override = None
        if self.swap_generator_family and q['family'] == \
                self.swap_generator_family[0]:
            generator_override = GENERATORS[
                self.swap_generator_family[1]]
        p = make_proof(
            q, accepted=key not in self.reject,
            reason_override=self.reason_override,
            generator_override=generator_override,
            params=self.params['rung_params'] if self.params else None)
        handle = None
        if p['status'] == 'accepted':
            handle = synthetic_pair(q, abs(hash(key)) % (2 ** 31))
            # 治理修复(E04):proof 与 fit manifest 的 episode hash 必须
            # 同源。把合成 event_table 的占位 hash 换成 handle 的真实
            # episode_content_hash(envelope digest 重算),否则生产
            # reader 的逐成员绑定如实拒绝。
            real = dict(handle.attempt_log.episode_hashes)
            for env in p['attempt_envelopes']:
                for side in ('A', 'B'):
                    env['event_table'][side][
                        'episode_content_hash'] = real[side]
                env['digest'] = batch.envelope_digest(env)
            p['episode_hashes'] = dict(real)
            p['attempt_log']['output_episode_hashes'] = dict(real)
        observe('call', p['call_envelope'])
        for e in p['attempt_envelopes']:
            observe('attempt', e)
        return batch.Generated(p, handle)


def _chain_authority(tmp_path):
    """合成链 authority(路径确定性推导;与 fixture 建立的目录一致)。"""
    repo_root = tmp_path / 'repo'
    claim = repo_root / 'stage2_6_1' / 'artifacts' / 'repair17' \
        / 'development' / 'v2_c13_engineering_claim'
    return prof.synthetic_authority(repo_root, claim)


@pytest.fixture
def chain_env(tmp_path, monkeypatch):
    """隔离环境:tmp repo root(空 artifacts)/tmp claim/重置模块全局。

    治理 v2 后合成链走完整新协议:显式 synthetic authority + 固定路径
    合成健康回归证据包(机器验证过、候选闭包对拍),fixture 经生产
    prepare_authoritative_plan()(真实 source/params/扫描 + 权威
    plan/evidence/receipt create-only 持久化),run() 再复验回归包并
    从同一权威计划取得 claim —— 与生产唯一差异仍是生成边界替身与
    小合同。
    """
    repo_root = tmp_path / 'repo'
    (repo_root / 'stage2_6_1' / 'artifacts').mkdir(parents=True)
    # claim 根必须在 repo 根内(生产相对结构;G07 守卫拒绝域外 claim 根)。
    claim = repo_root / 'stage2_6_1' / 'artifacts' / 'repair17' \
        / 'development' / 'v2_c13_engineering_claim'
    claim.mkdir(parents=True, exist_ok=True)
    auth = _chain_authority(tmp_path)
    from r17_v2_c13_regression_evidence import build_synthetic_package

    build_synthetic_package(
        prof.authoritative_full_regression_path(auth),
        current_sources=pipe.source_guard())
    monkeypatch.setattr(pipe, 'FIT_CALL_LOG', [])
    monkeypatch.setattr(pipe, 'POLICY_EVALUATION_STARTED', False)
    monkeypatch.setattr(pipe, '_EVAL_PHASE_ACTIVE', False)
    (tmp_path / 'run').mkdir()
    return tmp_path


def _preclaim_authoritative(tmp_path, backend, contract):
    """合成链的 preclaim gate:真实流程持久化权威 plan/evidence/receipt
    (回归证据包由 chain_env 预先建立在固定权威路径)。"""
    backend.params = prof.parameter_snapshot()
    return pipe.prepare_authoritative_plan(
        backend=backend, contract=contract,
        authority=_chain_authority(tmp_path))


def _run_chain(tmp_path, backend, contract=None):
    contract = contract if contract is not None else small_contract()
    _preclaim_authoritative(tmp_path, backend, contract)
    out = tmp_path / 'run' / 'chain'
    rc = pipe.run(out, backend=backend, contract=contract,
                  authority=_chain_authority(tmp_path))
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    return rc, out, result


# ------------------------------------------------------------------ E01
def test_e01_healthy_synthetic_chain_full_path(chain_env):
    """健康链:生产编排核心 + 仅生成边界替身,全链 complete + 冷读。"""
    pytest.importorskip('rl_curriculum')
    backend = ChainFixture()
    rc, out, result = _run_chain(chain_env, backend)
    assert rc == 0, result.get('error')
    assert result['status'] == 'complete'
    assert result['synthetic'] is True
    assert result['engineering_path_complete'] is True
    assert result['fit_calls'] == ['fit_main', 'fit_validation']
    assert result['policy_evaluation_started'] is True
    assert result['phase'] == 'delivered'
    # 产物结构:plan/claim/params/stages/bundles/episodes/evaluations/
    # result/delivery/manifest 全部存在。
    for rel in ('plan.json', 'claim.json', 'params_snapshot.json',
                'result.json', 'delivery.json', 'manifest.json',
                'eval_selection.json'):
        assert (out / rel).is_file(), rel
    for split in ('main', 'validation'):
        assert (out / 'bundles' / split / 'envelope.json').is_file()
        assert (out / 'bundles' / split / 'frozen_checkpoint.json'
                ).is_file()
        assert (out / 'bundles' / split / 'fit_manifest.json').is_file()
        for family in ('c1_opportunity', 'c3_cost'):
            assert (out / 'evaluations' / split
                    / f'{family}_report.json').is_file()
        assert (out / 'evaluations' / split
                / 'reference_equivalence.json').is_file()
    # delivery:synthetic 标记 + 工程完成不授予。
    delivery = json.loads((out / 'delivery.json').read_text(
        encoding='utf-8'))
    assert delivery['synthetic'] is True
    assert delivery['engineering_consumer_complete'] is False
    assert delivery['calibration_qualified'] is False
    # verify 冷读(生产 reader,stdlib only):一致但 synthetic 不授予。
    report = pipe.verify(out)
    assert report['evidence_consistent'] is True
    assert report['synthetic'] is True
    assert report['engineering_complete'] is False
    assert report['status'] == 'complete'
    # 统计四格存在(合成数据,任何 strict 结果都保留)。
    stat = result['statistical']
    for key in ('c1_opportunity_main', 'c1_opportunity_validation',
                'c3_cost_main', 'c3_cost_validation'):
        assert key in stat
    # claim 已消费(一次性)。
    assert prof.claim_state()['consumed'] is True


# ------------------------------------------------------------------ E02
def test_e02_selected_episode_inputs_reload_and_hash(chain_env):
    """数值输入持久化:CSV 重载后按原 episode content hash 验证。

    治理修复后持久化为 v2 完整格式(df+hidden+完整 spec),生产 reader
    ``_reload_episode_identity`` 对每个选定 A/B 重算权威
    episode_content_hash 并与生成时值逐位对拍(不是复制旧 hash 字段)。
    """
    pytest.importorskip('rl_curriculum')
    backend = ChainFixture()
    rc, out, result = _run_chain(chain_env, backend)
    assert rc == 0
    checked = 0
    for stage in ('fit_main', 'fit_validation', 'eval_main',
                  'eval_validation'):
        sdir = out / 'stages' / stage
        stage_result = json.loads((sdir / 'result.json').read_text(
            encoding='utf-8'))
        for key, meta in stage_result.get('episode_artifacts',
                                          {}).items():
            for side in ('A', 'B'):
                csv = out / 'episodes' / stage / meta[side]['csv']
                assert batch.file_meta(csv)['sha256'] == \
                    meta[side]['csv_sha256']
                recomputed = pipe._reload_episode_identity(
                    out, stage, key, side, meta[side])
                assert recomputed is not None, \
                    'v2 persist format must be fully rebuildable'
                assert recomputed == \
                    meta[side]['episode_content_hash'], \
                    f'identity hash mismatch: {stage}/{key}/{side}'
                checked += 1
    assert checked >= 48  # (fit 12 + eval 12) × 2 split × 2 side


# ------------------------------------------------------------------ E03
def test_e03_phase_accurate_on_generation_failure(chain_env):
    """fit 阶段生成失败:准确 phase,统计 NOT_RUN,前序原件保留。"""
    pytest.importorskip('rl_curriculum')
    contract = small_contract()
    backend = ChainFixture(fail_at='fit_validation_c2_context_D1_p0')
    backend.params = prof.parameter_snapshot()
    _preclaim_authoritative(chain_env, backend, contract)
    out = chain_env / 'run' / 'chain'
    rc = pipe.run(out, backend=backend, contract=contract,
                  authority=_chain_authority(chain_env))
    assert rc == 3
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    assert result['status'] == 'generation_failed'
    assert result['phase'] == 'fit_validation_generation'
    assert result['statistical'] is None  # NOT_RUN
    assert result['engineering_path_complete'] is False
    # execute_stage 记录原始注入错误并停止;run 层包成链失败。
    assert result['error']['type'] == 'PermissionError'
    # 前序 fit_main 完整保留;eval 阶段未开始。
    assert (out / 'bundles' / 'main' / 'envelope.json').is_file()
    assert not (out / 'stages' / 'eval_main').exists()
    assert result['policy_evaluation_started'] is False
    assert (out / 'stages' / 'fit_validation' / 'errors'
            / 'fit_validation_c2_context_D1_p0.json').is_file()
    # verify 对失败 run 的冷读:阶段真实停止被读出。
    report = pipe.verify(out)
    assert report['status'] == 'generation_failed'
    assert report['engineering_complete'] is False


def test_e03_reserve_exhaustion_phase_and_eval_not_started(chain_env):
    """C3 eval 备援耗尽:rc=4,评估未启动,policy 调用数为零事实。"""
    pytest.importorskip('rl_curriculum')
    contract = small_contract()
    quota = SMALL_EVAL_QUOTA
    reject = {f'eval_main_c3_cost_D0_p{i}' for i in range(quota + 1)}
    backend = ChainFixture(reject=reject,
                           reason_override=['A:too_few_distractors',
                                            'B:too_few_distractors',
                                            'pair:too_few_distractors'])
    backend.params = prof.parameter_snapshot()
    _preclaim_authoritative(chain_env, backend, contract)
    out = chain_env / 'run' / 'chain'
    rc = pipe.run(out, backend=backend, contract=contract,
                  authority=_chain_authority(chain_env))
    assert rc == 4
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    assert result['phase'] == 'eval_main_generation'
    assert result['stop'] == 'reserve_exhausted'
    assert result['policy_evaluation_started'] is False
    # fit 已完成的事实照实保留。
    assert result['fit_calls'] == ['fit_main', 'fit_validation']
    assert (out / 'bundles' / 'main' / 'envelope.json').is_file()
    assert not (out / 'evaluations').exists()


# ------------------------------------------------------------------ E04
def test_e04_semantic_tampering_rejected_by_cold_reader(chain_env):
    """成功 fixture 的语义负例:外层自洽的翻绿副本被 verify 拒绝。"""
    pytest.importorskip('rl_curriculum')
    backend = ChainFixture()
    rc, out, result = _run_chain(chain_env, backend)
    assert rc == 0

    def remanifest(root: Path) -> None:
        """重算 manifest.json(模拟外层字节摘要自洽的篡改;收集时
        排除 manifest.json 自身,与生产 tree_snapshot 写入时序一致)。"""
        from r17_v2_c13_batch import tree_snapshot

        files = tree_snapshot(root)
        files.pop('manifest.json', None)
        manifest = {'contract': prof.CONTRACT, 'files': files}
        (root / 'manifest.json').write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + '\n',
            encoding='utf-8')

    # 负例 1:统计 FAIL 被改成 PASS(conditions.pass 翻绿)。
    import shutil

    t1 = out.parent / 'tamper_pass_flip'
    shutil.copytree(out, t1)
    rep_path = t1 / 'evaluations' / 'main' / 'c1_opportunity_report.json'
    doc = json.loads(rep_path.read_text(encoding='utf-8'))
    doc['conditions']['pass'] = not doc['conditions']['pass']
    rep_path.write_text(json.dumps(doc), encoding='utf-8')
    remanifest(t1)
    with pytest.raises(Exception, match='strict algebra mismatch'):
        pipe.verify(t1)

    # 负例 2:delivery 工程完成翻绿(synthetic→real 伪装)。
    t2 = out.parent / 'tamper_delivery_flip'
    shutil.copytree(out, t2)
    dpath = t2 / 'delivery.json'
    doc = json.loads(dpath.read_text(encoding='utf-8'))
    doc['engineering_consumer_complete'] = True
    doc['synthetic'] = False
    dpath.write_text(json.dumps(doc), encoding='utf-8')
    remanifest(t2)
    with pytest.raises(Exception):
        pipe.verify(t2)

    # 负例 3:envelope 文件等长篡改(锚点 hash 检出)。
    t3 = out.parent / 'tamper_envelope'
    shutil.copytree(out, t3)
    epath = t3 / 'bundles' / 'main' / 'envelope.json'
    doc = json.loads(epath.read_text(encoding='utf-8'))
    doc['parameter_state']['scaler']['data_min_'][0] += 0.25
    epath.write_text(json.dumps(doc), encoding='utf-8')
    remanifest(t3)
    with pytest.raises(Exception,
                       match='envelope file bytes drift'):
        pipe.verify(t3)

    # 负例 4:fit manifest 成员被换(多重集身份变化)。
    t4 = out.parent / 'tamper_manifest_member'
    shutil.copytree(out, t4)
    mpath = t4 / 'bundles' / 'main' / 'fit_manifest.json'
    doc = json.loads(mpath.read_text(encoding='utf-8'))
    if doc.get('document', {}).get('entries'):
        doc['document']['entries'][0]['episode_hash'] = 'ce-tampered'
    mpath.write_text(json.dumps(doc), encoding='utf-8')
    remanifest(t4)
    with pytest.raises(Exception):
        pipe.verify(t4)

    # 正例回控:原件 verify 仍然通过(篡改不损原件)。
    report = pipe.verify(out)
    assert report['evidence_consistent'] is True


# ------------------------------------------------------------------ 失败演练
def test_fault_cross_family_identity_stops_first_request(chain_env):
    """三族身份错配:C2 请求带 C3 身份 → 首请求处 fatal 停止。"""
    pytest.importorskip('rl_curriculum')
    backend = ChainFixture(swap_generator_family=('c2_context', 'c3_cost'))
    rc, out, result = _run_chain(chain_env, backend)
    assert rc == 3
    assert result['status'] == 'generation_failed'
    assert result['phase'] == 'fit_main_generation'
    assert 'generator identity mismatch' in \
        result['error']['message']


def test_fault_write_failure_preserves_state(chain_env, monkeypatch):
    """artifact 写入失败:阶段准确停止,不补造成功数据。"""
    pytest.importorskip('rl_curriculum')
    contract = small_contract()
    backend = ChainFixture()
    backend.params = prof.parameter_snapshot()
    _preclaim_authoritative(chain_env, backend, contract)
    out = chain_env / 'run' / 'chain'
    real_new_json = batch.new_json
    calls = {'n': 0}

    def flaky_new_json(path, value):
        calls['n'] += 1
        # 在首个 eval_main 请求 start 处模拟磁盘写失败。
        if 'stages/eval_main/starts' in str(path):
            raise OSError('simulated disk full')
        return real_new_json(path, value)

    monkeypatch.setattr(pipe, 'new_json', flaky_new_json)
    monkeypatch.setattr(batch, 'new_json', flaky_new_json)
    rc = pipe.run(out, backend=backend, contract=contract,
                  authority=_chain_authority(chain_env))
    assert rc == 3
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    assert result['status'] == 'generation_failed'
    assert result['statistical'] is None
    # fit 两 bank 已完成的事实保留。
    assert (out / 'bundles' / 'main' / 'envelope.json').is_file()
    assert result['fit_calls'] == ['fit_main', 'fit_validation']


def test_fault_refit_during_eval_blocked(chain_env, monkeypatch):
    """eval 中 refit:实际调用入口被拒(评估阶段激活守卫)。"""
    pytest.importorskip('rl_curriculum')
    backend = ChainFixture()
    backend.params = prof.parameter_snapshot()
    contract = small_contract()
    _preclaim_authoritative(chain_env, backend, contract)
    out = chain_env / 'run' / 'chain'
    real_eval = pipe.evaluate_split
    invoked = {'n': 0}

    def eval_with_refit_attempt(root, split, handles, params, plan,
                                ledger, **kw):
        # 先走真实评估(激活 eval 阶段),随后尝试再 fit:必须被拒。
        out = real_eval(root, split, handles, params, plan, ledger, **kw)
        with pytest.raises(Exception, match='refit blocked'):
            pipe.fit_and_freeze(
                root, split, [], params, plan, None,
                expected_fit_pairs=contract['n_fit_pairs_per_bank'])
        invoked['n'] += 1
        return out

    monkeypatch.setattr(pipe, 'evaluate_split', eval_with_refit_attempt)
    rc = pipe.run(out, backend=backend, contract=contract,
                  authority=_chain_authority(chain_env))
    assert rc == 0
    assert invoked['n'] == 2  # 两分区的评估都尝试过 refit 且被拒
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    assert result['fit_calls'] == ['fit_main', 'fit_validation']


# ------------------------------------------------------------------ E05 入口
def test_e05_production_profile_precise_vs_small(chain_env):
    """生产 336 合同精确核验(非运行):与小合同明确区分。"""
    c = prof.fixed_contract()
    assert c['n_planned_requests'] == 336
    assert c['n_fit_pairs_per_bank'] == 72
    assert c['n_eval_pairs_per_family_per_split'] == 40
    assert c['canonical_pairs_per_split'] == 24
    assert 'synthetic_profile' not in c or \
        c.get('synthetic_profile') is not True
    small = small_contract()
    assert small['n_planned_requests'] < 336
    assert small['synthetic_profile'] is True
    # 小合同 plan 自洽 + synthetic 声明通过 validate_plan。
    runtime = {'kind': 'test_fixture',
               'generators': copy.deepcopy(GENERATORS),
               'sources': {}, 'interpreter': sys.version}
    plan = prof.make_plan(runtime, small)
    prof.validate_plan(plan)
    # 未声明 synthetic 的注入合同被拒。
    bad = copy.deepcopy(small)
    bad.pop('synthetic_profile')
    with pytest.raises(Exception,
                       match='declared synthetic'):
        prof.validate_plan(prof.make_plan(runtime, bad))
    # 生产 runtime 单身份(v1 形态)计划被拒。
    with pytest.raises(Exception, match='three-family generator map'):
        prof.validate_plan(prof.make_plan(
            {'kind': 'real', 'generator': GENERATORS['c3_cost']},
            small))


# ------------------------------------------------------------- E11 回归证据
def test_e11_regression_tamper_rejected_before_claim(chain_env):
    """F09/F10/F11:preclaim 后篡改权威回归包(含重签外层 manifest)
    → run 在 claim 前拒绝;未篡改控制组照常完成全链。"""
    pytest.importorskip('rl_curriculum')
    auth = _chain_authority(chain_env)
    backend = ChainFixture()
    contract = small_contract()
    _preclaim_authoritative(chain_env, backend, contract)
    pkg = prof.authoritative_full_regression_path(auth)
    # 彻底攻击者:篡改 junit + 重签 manifest + 同步 required 条目;
    # supervisor run_record 的角色 sha 与 receipt 锚定的包 digest 仍
    # 拒绝(双层内锚 + 内容寻址 digest)。
    import hashlib

    junit = (pkg / 'junit.xml').read_text(encoding='utf-8')
    (pkg / 'junit.xml').write_text(
        junit.replace('test_synth_0', 'test_syNth_0'), encoding='utf-8')
    from r17_v2_c13_regression_evidence import package_content_index

    required = json.loads((pkg / 'required_files.json').read_text())
    data = (pkg / 'junit.xml').read_bytes()
    for e in required['entries']:
        if e['path'] == 'junit.xml':
            e['sha256'] = hashlib.sha256(data).hexdigest()
            e['size'] = len(data)
    (pkg / 'required_files.json').write_text(
        json.dumps(required, indent=2), encoding='utf-8')
    index = {rel: meta for rel, meta in package_content_index(pkg).items()
             if rel != 'manifest.json'}
    (pkg / 'manifest.json').write_text(
        json.dumps({'format': 'R17V2C13FullRegressionEvidence-v1',
                    'files': index}, indent=2, sort_keys=True),
        encoding='utf-8')

    out = chain_env / 'run' / 'chain_tamper'
    rc = pipe.run(out, backend=backend, contract=contract, authority=auth)
    assert rc == 3
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    assert result['phase'] == 'full_regression_evidence_revalidation'
    assert 'full regression evidence rejected before claim' in \
        result['error']['message']
    # claim 未消费、无任何生成产物。
    assert prof.claim_state(auth)['consumed'] is False
    assert not out.joinpath('claim.json').exists()
    assert not out.joinpath('stages').exists()


def test_e11_regression_digest_anchor_rejects_resign_only(chain_env):
    """F10:仅重签外层 manifest(不改语义文件)→ 包 digest 漂移,run
    在 receipt 包 digest 锚处拒绝。"""
    pytest.importorskip('rl_curriculum')
    auth = _chain_authority(chain_env)
    backend = ChainFixture()
    contract = small_contract()
    _preclaim_authoritative(chain_env, backend, contract)
    pkg = prof.authoritative_full_regression_path(auth)
    from r17_v2_c13_regression_evidence import package_content_index

    index = {rel: meta for rel, meta in package_content_index(pkg).items()
             if rel != 'manifest.json'}
    (pkg / 'manifest.json').write_text(
        json.dumps({'format': 'R17V2C13FullRegressionEvidence-v1',
                    'files': index, 'resigned': True}, indent=2,
                   sort_keys=True), encoding='utf-8')
    out = chain_env / 'run' / 'chain_resign'
    rc = pipe.run(out, backend=backend, contract=contract, authority=auth)
    assert rc == 3
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    assert result['phase'] == 'full_regression_evidence_revalidation'
    assert prof.claim_state(auth)['consumed'] is False
