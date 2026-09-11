"""R17 V2 C1/C3 事后治理:producer/consumer 冷读绑定与四态 verdict
测试(E01-E10/S01-S02 的单元与旧归档只读面;任务
R17V2C13PostRunGovernanceAndC2LaunchPrep-v1)。

对现存 v2 归档(已消费 claim 的真实主 run)执行新 verify:
- 数值链完整、stored pair table 四格 strict PASS 保留(S01);
- governance_contract_pass=false(S02):plan legacy 形态、routing
  "(unbound)"、episode 身份层不可完整重建等缺口按事实记录;
- 篡改只读副本后外层重签 manifest 仍被拒(E10)。
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


def _archived_run() -> Path | None:
    """定位现存 v2 主 run:先按测试布局 parents 查找(发布库布局),
    再回退发布库固定挂载路径(部署 tests 布局);都不在则 skip。"""
    candidates = []
    for base in HERE.parents:
        candidates.append(base / 'artifacts' / 'repair17' / 'development'
                          / 'v2_c13_engineering_v2_delivery' / 'main_run'
                          / 'monitored_run' / 'v2_c13_engineering_v2')
    candidates.append(Path(
        '/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17'
        '/development/v2_c13_engineering_v2_delivery/main_run'
        '/monitored_run/v2_c13_engineering_v2'))
    for cand in candidates:
        if (cand / 'result.json').is_file():
            return cand
    return None


# ------------------------------------------------------------- E 系列 单元
def test_e03_multiset_hash_stdlib_matches_production():
    """stdlib multiset 重算与生产 r4 实现逐位一致(差分)。"""
    pytest.importorskip('rl_curriculum')
    from rl_curriculum.curriculum261_r4_preprocessing import (
        FitManifestEntry, fit_manifest_document,
    )

    def entry(i, s):
        return FitManifestEntry(
            namespace='ns-a', family='c1_opportunity', rung='D0',
            pair_index=i, side=s, episode_hash=f'ce-{i:064d}',
            feature_matrix_hash=f'fm-{(i * 7):064d}',
            generator_identity=f'c1_opportunity|v|pack{i % 3}')

    entries = [entry(i, s) for i in range(6) for s in ('A', 'B')]
    doc = fit_manifest_document(copy.deepcopy(entries), namespace='ns-a')
    as_dicts = [e.canonical() for e in entries]
    assert pipe._entry_multiset_hash(as_dicts) == doc['multiset_hash']
    # 换一条 entry(成员换)→ 重算值变化(不是数量级检查)。
    swapped = copy.deepcopy(as_dicts)
    swapped[0]['episode_hash'] = 'ce-tampered'
    assert pipe._entry_multiset_hash(swapped) != doc['multiset_hash']


def test_e08_routing_audit_flags_unbound(monkeypatch, tmp_path):
    """routing 审计:legacy "(unbound)" 行/缺三层身份按缺口计。"""
    from types import SimpleNamespace

    from rl_curriculum.curriculum261_r17_routing import (
        R17BundleRouting,
    )

    v2 = SimpleNamespace(
        namespace='ns', bundle_hash='bh', parameter_state_hash='ph',
        manifest_multiset_hash='mh')
    routing = R17BundleRouting(
        role='main', fit_namespace='ns', bundle_hash='bh',
        parameter_state_hash='ph', manifest_multiset_hash='mh', _v2=v2)
    ledger_rows = []

    class L:
        @staticmethod
        def record(detail, ok):
            row = dict(detail)
            row['pass'] = bool(ok)
            ledger_rows.append(row)

    # 不传 expected_bundle_hash → "(unbound)"(历史行为,可选参数兼容)。
    routing.bundle(context='legacy_call', ledger=L())
    assert ledger_rows[-1]['expected_bundle_hash'] == '(unbound)'
    assert 'actual_parameter_state_hash' in ledger_rows[-1]
    # 传入期望 → 行携带真实期望与三层身份(E08)。
    routing.bundle(context='bound_call', expected_bundle_hash='bh',
                   ledger=L())
    assert ledger_rows[-1]['expected_bundle_hash'] == 'bh'
    assert ledger_rows[-1]['actual_bundle_hash'] == 'bh'
    assert ledger_rows[-1]['actual_parameter_state_hash'] == 'ph'
    assert ledger_rows[-1]['actual_manifest_multiset_hash'] == 'mh'
    # 期望不符 → fail closed。
    with pytest.raises(Exception, match='routing 合同违反'):
        routing.bundle(context='wrong', expected_bundle_hash='other')


def test_e08_require_eval_routing_passes_bundle_hash():
    """require_eval_routing_r17 透传 expected_bundle_hash(不再 unbound)。"""
    pytest.importorskip('rl_curriculum')
    from types import SimpleNamespace

    from rl_curriculum.curriculum261_r17_routing import (
        R17BundleRouting, R17_V2C13_V2_EVAL_NAMESPACES,
        require_eval_routing_r17,
    )

    ns = next(n for n in R17_V2C13_V2_EVAL_NAMESPACES
              if n.endswith('eval_main_r17'))
    v2 = SimpleNamespace(
        namespace='preplan_v2c13_v2_fit_main_r17', bundle_hash='bh',
        parameter_state_hash='ph', manifest_multiset_hash='mh')
    routing = R17BundleRouting(
        role='main', fit_namespace='preplan_v2c13_v2_fit_main_r17',
        v2c13v2=True, bundle_hash='bh', parameter_state_hash='ph',
        manifest_multiset_hash='mh', _v2=v2)
    rows = []

    class L:
        @staticmethod
        def record(detail, ok):
            row = dict(detail)
            row['pass'] = bool(ok)
            rows.append(row)

    require_eval_routing_r17(
        routing, ns, context='calibration_main_c1_opportunity',
        expected_bundle_hash='bh', ledger=L())
    assert rows[-1]['expected_bundle_hash'] == 'bh'
    with pytest.raises(Exception):
        require_eval_routing_r17(
            routing, ns, context='x', expected_bundle_hash='other',
            ledger=L())


# ------------------------------------------------- 旧 v2 归档:四态 verdict
def test_s02_archived_v2_four_state_verdict():
    """S01/S02:现存 v2 主 run 只读冷读 — 数值完成+四格 strict PASS
    保留为诊断;governance 合同 FAIL;formal 未签发;不追认工程 PASS。"""
    pytest.importorskip('rl_curriculum')
    run = _archived_run()
    if run is None:
        pytest.skip('archived v2 main run not present in this layout')
    report = pipe.verify(run)
    assert report['evidence_consistent'] is True
    assert report['numerical_path_complete'] is True
    assert report['stored_table_strict_diagnostic'] == 'PASS'
    assert report['governance_contract_pass'] is False
    assert report['formal_qualification_issued'] is False
    assert report['engineering_complete'] is False
    # 缺口按事实定位(独立审查第 1/4/5/6 项的 reader 侧证据)。
    flags = report['governance_flags']
    assert flags['plan_format_layered'] is False  # runtime 内嵌扫描
    assert flags['routing_matrix_binds_frozen_hash'] is False  # unbound
    assert flags['episode_identity_fully_rebuildable'] is False
    assert report['episode_identity_reload']['partial_legacy'] > 0
    assert report['routing_audit']['unbound'] > 0
    # S01:四格数值保持原样(只读;strict PASS 是 stored-table 诊断)。
    assert all(report['statistical_strict_pass'].get(k) is True for k in (
        'c1_opportunity_main', 'c1_opportunity_validation',
        'c3_cost_main', 'c3_cost_validation'))


# ------------------------------------------------- E10:旧归档只读副本负例
def _remanifest(root: Path) -> None:
    files = batch.tree_snapshot(root)
    files.pop('manifest.json', None)
    (root / 'manifest.json').write_text(
        json.dumps({'contract': prof.CONTRACT, 'files': files},
                   sort_keys=True, indent=2) + '\n', encoding='utf-8')


def test_e10_archived_copy_semantic_negatives(tmp_path):
    """E10:对现存 v2 只读副本的语义负例 — episode 映射/fit 来源/
    routing/canonical/统计摘要错配,重签外层 manifest 仍拒绝。"""
    pytest.importorskip('rl_curriculum')
    run = _archived_run()
    if run is None:
        pytest.skip('archived v2 main run not present in this layout')
    import shutil

    def fresh(name):
        dst = tmp_path / name
        shutil.copytree(run, dst)
        return dst

    # 1) episode 映射错配:selection 成员换人(改 pair_index)。
    t = fresh('ep_map')
    sel = t / 'stages' / 'eval_main' / 'selection.json'
    doc = json.loads(sel.read_text(encoding='utf-8'))
    doc['member_coordinates'][0]['pair_index'] = 99
    sel.write_text(json.dumps(doc), encoding='utf-8')
    _remanifest(t)
    with pytest.raises(Exception):
        pipe.verify(t)

    # 2) fit 来源错配:envelope fit manifest 换成员 hash(重签拒绝)。
    t = fresh('fit_src')
    ep = t / 'bundles' / 'main' / 'envelope.json'
    doc = json.loads(ep.read_text(encoding='utf-8'))
    doc['fit_manifest']['entries'][0]['episode_hash'] = 'ce-swapped'
    doc['hashes']['fit_manifest_multiset_hash'] = 'fm-swapped'
    ep.write_text(json.dumps(doc), encoding='utf-8')
    fz = t / 'bundles' / 'main' / 'frozen_checkpoint.json'
    doc = json.loads(fz.read_text(encoding='utf-8'))
    doc['hashes']['fit_manifest_multiset_hash'] = 'fm-swapped'
    doc['manifest_summary']['multiset_hash'] = 'fm-swapped'
    doc['envelope_file_sha256'] = batch.file_meta(ep)['sha256']
    fz.write_text(json.dumps(doc), encoding='utf-8')
    sm = t / 'bundles' / 'main' / 'fit_manifest.json'
    doc = json.loads(sm.read_text(encoding='utf-8'))
    if doc.get('document', {}).get('entries'):
        doc['document']['entries'][0]['episode_hash'] = 'ce-swapped'
    doc['multiset_hash'] = 'fm-swapped'
    sm.write_text(json.dumps(doc), encoding='utf-8')
    _remanifest(t)
    with pytest.raises(Exception):
        pipe.verify(t)

    # 3) routing 错配:delivery 矩阵行换 bundle hash(外层自洽仍拒)。
    t = fresh('routing')
    dp = t / 'delivery.json'
    doc = json.loads(dp.read_text(encoding='utf-8'))
    doc['routing_matrix'][0]['actual_bundle_hash'] = 'bh-swapped'
    doc['routing_matrix'][0]['expected_bundle_hash'] = 'bh-swapped'
    dp.write_text(json.dumps(doc), encoding='utf-8')
    _remanifest(t)
    with pytest.raises(Exception):
        pipe.verify(t)

    # 4) canonical 成员换人:result 声明的 member_keys 与固定前3不符。
    t = fresh('canonical')
    rp = t / 'result.json'
    doc = json.loads(rp.read_text(encoding='utf-8'))
    doc['reference_equivalence']['main']['member_keys'] = [
        'eval_main_c1_opportunity_D0_p9',
        *doc['reference_equivalence']['main']['member_keys'][1:]]
    rp.write_text(json.dumps(doc), encoding='utf-8')
    _remanifest(t)
    with pytest.raises(Exception):
        pipe.verify(t)

    # 5) 统计摘要翻绿:result strict_pass 与已复核 conditions 不一致。
    t = fresh('stat_flip')
    rp = t / 'result.json'
    doc = json.loads(rp.read_text(encoding='utf-8'))
    doc['statistical']['c1_opportunity_main']['strict_pass'] = \
        not doc['statistical']['c1_opportunity_main']['strict_pass']
    rp.write_text(json.dumps(doc), encoding='utf-8')
    _remanifest(t)
    with pytest.raises(Exception):
        pipe.verify(t)

    # 控制组:未篡改副本冷读通过(字节重签本身不触发拒绝)。
    t = fresh('control')
    _remanifest(t)
    report = pipe.verify(t)
    assert report['evidence_consistent'] is True


# ------------------------------------------------- run() 协议顺序(集成)
_SYNTHETIC_CONTRACT = {
    'engineering_only': True, 'synthetic_profile': True,
    'stages': [{
        'stage': 'fit_main', 'kind': 'fit', 'split': 'main',
        'namespace': 'preplan_v2c13_v2_fit_main_r17',
        'families': ['c1_opportunity'], 'quota_per_stratum': 1,
        'reserve_indices': {},
    }],
}


def _synthetic_authority(tmp_path):
    repo_root = tmp_path / 'repo'
    (repo_root / 'stage2_6_1' / 'artifacts').mkdir(parents=True,
                                                    exist_ok=True)
    claim = (repo_root / 'stage2_6_1' / 'artifacts' / 'repair17'
             / 'development' / 'v2_c13_engineering_claim')
    claim.mkdir(parents=True, exist_ok=True)
    return prof.synthetic_authority(repo_root, claim)


def test_run_requires_authoritative_plan_first(tmp_path, monkeypatch):
    """G03/G12 集成:无权威 plan → run 在消费前拒绝,零生成零 claim。"""
    pytest.importorskip('rl_curriculum')
    auth = _synthetic_authority(tmp_path)
    monkeypatch.setattr(pipe, 'FIT_CALL_LOG', [])
    monkeypatch.setattr(pipe, 'POLICY_EVALUATION_STARTED', False)
    monkeypatch.setattr(pipe, '_EVAL_PHASE_ACTIVE', False)
    (tmp_path / 'run').mkdir()
    out = tmp_path / 'run' / 'chain'

    # 无 plan:run 把真实失败写入 result.json(rc=3),backend 从未被
    # describe(零生成、零 claim)。
    monkeypatch.setattr(pipe, 'source_guard', lambda: {'stub': {
        'path': '/stub', 'sha256': '00' * 32}})
    monkeypatch.setattr(prof, 'parameter_snapshot', lambda: {
        'pack': {'digest': 'x'}, 'rung_params': {}, 'reference_defaults':
            {}, 'r4_parameter_pack_digest': 'y', 'sources': {},
        'r4_inheritance': {'pass': True}})
    monkeypatch.setattr(pipe, 'namespace_unused_evidence',
                        lambda root: {'namespaces_unused': True,
                                      'hits': [], 'n_hits': 0,
                                      'planning_only_hits': [],
                                      'unreadable_evidence': []})
    described = []

    class NoBackend:
        def describe(self):
            described.append(1)
            return {}

    rc = pipe.run(out, backend=NoBackend(), contract=_SYNTHETIC_CONTRACT,
                  authority=auth)
    assert rc == 3
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    assert result['phase'] == 'authoritative_plan_consumption'
    assert 'authoritative final plan missing' in \
        result['error']['message']
    assert described == []  # plan 缺失时连 runtime 对拍都不发生
    assert not out.joinpath('claim.json').exists()


def test_run_rejects_stale_receipt_or_evidence_drift(
        tmp_path, monkeypatch):
    """G09/G11 集成:receipt 过期或 evidence 漂移 → claim 前拒绝。"""
    pytest.importorskip('rl_curriculum')
    auth = _synthetic_authority(tmp_path)
    monkeypatch.setattr(pipe, 'source_guard', lambda: {'stub': {
        'path': '/stub', 'sha256': '00' * 32}})
    from test_curriculum261_r17_v2_c13_pipeline import GENERATORS

    runtime = {'kind': 'test_fixture',
               'generators': copy.deepcopy(GENERATORS),
               'sources': {'stub': {'path': '/stub', 'sha256': '00' * 32}},
               'interpreter': sys.version}
    ev = {'scanned_roots': ['/repo'], 'hits': [], 'n_hits': 0,
          'planning_only_hits': [], 'unreadable_evidence': [],
          'namespaces_unused': True}
    import hashlib

    ev_sha = hashlib.sha256(
        (prof.canonical(ev) + '\n').encode('utf-8')).hexdigest()
    prof.persist_authoritative_evidence(ev, authority=auth)
    plan = prof.make_plan(runtime, contract=_SYNTHETIC_CONTRACT,
                          admission_evidence={
        'kind': 'namespace_unused_v1',
        'path': prof.EVIDENCE_FILENAME, 'sha256': ev_sha})
    prof.validate_plan(plan)
    persisted = prof.persist_final_plan(plan, authority=auth)
    # 过期 closure receipt(回归引用为新形状;closure 故意过期)。
    prof.write_preclaim_receipt({
        'profile': prof.CONTRACT, 'admitted': True,
        'plan_sha256': persisted['plan_sha256'],
        'plan_file_sha256': persisted['file_sha256'],
        'source_closure_sha256': 'ff' * 32,
        'full_regression_evidence': {
            'path': str(prof.authoritative_full_regression_path(auth)),
            'package_sha256': 'aa' * 32, 'entry_rc': 0, 'business_rc': 0},
        'evidence_sha256': 'bb' * 32}, authority=auth)
    monkeypatch.setattr(pipe, 'namespace_unused_evidence',
                        lambda root: ev)
    monkeypatch.setattr(prof, 'parameter_snapshot', lambda: {
        'pack': {'digest': 'x'}, 'rung_params': {}, 'reference_defaults':
            {}, 'r4_parameter_pack_digest': 'y', 'sources': {},
        'r4_inheritance': {'pass': True}})

    class StubBackend:
        def describe(self):
            return copy.deepcopy(runtime)

    (tmp_path / 'run').mkdir()
    out = tmp_path / 'run' / 'chain'
    rc = pipe.run(out, backend=StubBackend(), contract=plan['contract'],
                  authority=auth)
    assert rc == 3
    result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
    assert result['phase'] == 'preclaim_receipt_validation'
    assert 'different source closure' in result['error']['message']
    # 无 claim、无生成产物。
    assert not (auth.claim_root / f'{prof.CONTRACT}.json').exists()
    assert not out.joinpath('claim.json').exists()
    assert not out.joinpath('stages').exists()
