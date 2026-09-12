"""R17 V2 C1/C3 治理 v2:不可变 authority、固定 claim API 与
plan → preclaim receipt → 排他 claim 协议测试(G03-G12 + A02-A10;
任务 R17V2C13GovernanceAuthorityEvidenceAndC2PrepClosure-v2)。

覆盖:
- production authority 不可被 env/cwd/out/run id/第二 checkout/模块
  属性改写;无 set_test_authority 注入面(A02/A03);
- RealBackend/生产合同 与合成 authority 组合在写入前拒绝(A04);
- CLI 无 root override;相对路径/../symlink parent/域外根拒绝(A05);
- 权威 plan/receipt/evidence/regression 路径只由 authority 推导,
  claim API 不接收 caller path/receipt dict(A06/A07);
- claim 绑定 plan digest、plan 文件字节、source closure、回归证据包
  digest(A08);
- 并发竞态恰好一个成功;崩溃与损坏 claim fail closed(A09/A10)。
"""
from __future__ import annotations

import copy
import inspect
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

from test_curriculum261_r17_v2_c13_pipeline import (  # noqa: E402
    GENERATORS, fixture_runtime)


def _runtime(tag: str = 'proto') -> dict:
    return {'kind': 'test_fixture',
            'generators': copy.deepcopy(GENERATORS),
            'sources': {'mod': {'path': f'/deployed/{tag}.py',
                                'sha256': tag * 32}},
            'interpreter': sys.version}


def _healthy_regression_ref(auth) -> dict:
    return {'path': str(prof.authoritative_full_regression_path(auth)),
            'package_sha256': 'aa' * 32, 'entry_rc': 0, 'business_rc': 0}


@pytest.fixture
def authority(tmp_path):
    """显式合成 authority(独立临时根;pytest tmp_path 在系统临时目录)。"""
    root = tmp_path / 'repo'
    claim = root / 'stage2_6_1' / 'artifacts' / 'repair17' / 'development' \
        / 'v2_c13_engineering_claim'
    claim.mkdir(parents=True)
    return prof.synthetic_authority(root, claim)


def _persist_plan_and_receipt(auth, closure='ab' * 32, runtime=None):
    plan = prof.make_plan(runtime or _runtime())
    persisted = prof.persist_final_plan(plan, authority=auth)
    receipt = {
        'profile': prof.CONTRACT, 'admitted': True,
        'plan_sha256': persisted['plan_sha256'],
        'plan_file_sha256': persisted['file_sha256'],
        'source_closure_sha256': closure,
        'full_regression_evidence': _healthy_regression_ref(auth),
        'evidence_sha256': 'bb' * 32,
    }
    prof.write_preclaim_receipt(receipt, authority=auth)
    return plan, persisted, receipt


# ------------------------------------------------- A02/A03 authority 不可变
def test_a02_production_authority_immutable(monkeypatch, tmp_path):
    """env/cwd/out/run id/模块属性改写全部不影响生产 authority 推导。"""
    prod = prof.production_authority()
    assert str(prod.repo_root) == '/mnt/f/trading/freqai-rl-audit'
    assert 'v2_c13_engineering_claim' in str(prod.claim_root)
    # 环境变量注入无效。
    monkeypatch.setenv('R17_V2C13_REPO_ROOT', str(tmp_path))
    monkeypatch.setenv('R17_V2C13_CLAIM_ROOT', str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert prof.production_authority() == prod
    # 旧注入面(monkeypatch 模块属性)不再被生产入口读取:即使强行
    # 设置同名属性,权威路径推导仍指向生产根。
    monkeypatch.setattr(prof, 'RELEASE_REPO_ROOT', tmp_path, raising=False)
    monkeypatch.setattr(prof, 'CLAIM_ROOT', tmp_path, raising=False)
    assert str(prof.claim_state()['path']).startswith(
        '/mnt/f/trading/freqai-rl-audit')
    assert str(prof.authoritative_plan_path()).startswith(
        '/mnt/f/trading/freqai-rl-audit')
    assert prof.production_authority() == prod
    # 每次调用重建等值实例(frozen;内容相等)。
    assert prof.resolve_authority(None) == prod


def test_a03_no_authority_injection_surface():
    """可变全局与 set_test_authority 注入面已废除(A03)。"""
    assert not hasattr(prof, 'set_test_authority')
    assert not hasattr(prof, 'RELEASE_REPO_ROOT')
    assert not hasattr(prof, 'CLAIM_ROOT')
    src = Path(prof.__file__).read_text(encoding='utf-8')
    assert 'global RELEASE_REPO_ROOT' not in src
    assert 'def set_test_authority' not in src
    # 模块内不得有任何环境读取调用。
    import re

    assert re.search(r'environ|getenv', src) is None


def test_a04_combination_rejected_before_writes(tmp_path, authority):
    """先调用合成 fixture,再走 RealBackend/生产合同组合:在任何写入
    之前拒绝(B2/A04);生产 authority 同样拒绝 fixture backend/注入
    合同。"""
    from r17_v2_c13_batch import RealBackend

    real_like = object.__new__(RealBackend)  # 不触发 __init__
    # 合成 authority + 默认 RealBackend(None)→ 拒绝。
    with pytest.raises(prof.ProfileError, match='RealBackend'):
        prof.enforce_authority_combination(
            authority, backend=None, contract=None)
    # 合成 authority + RealBackend 实例 → 拒绝。
    with pytest.raises(prof.ProfileError, match='RealBackend'):
        prof.enforce_authority_combination(
            authority, backend=real_like, contract=None)
    # 合成 authority + 未声明 synthetic 的合同 → 拒绝。
    with pytest.raises(prof.ProfileError, match='synthetic contract'):
        prof.enforce_authority_combination(
            authority, backend=object(),
            contract={'engineering_only': True})
    # 生产 authority + fixture backend → 拒绝。
    with pytest.raises(prof.ProfileError, match='fixture backend'):
        prof.enforce_authority_combination(
            prof.production_authority(), backend=object(), contract=None)
    # 生产 authority + 注入合同 → 拒绝。
    with pytest.raises(prof.ProfileError, match='injected contract'):
        prof.enforce_authority_combination(
            prof.production_authority(), backend=None,
            contract={'engineering_only': True})
    # 合成 + fixture backend + 声明 synthetic 合同 → 通过。
    prof.enforce_authority_combination(
        authority, backend=object(),
        contract={'engineering_only': True, 'synthetic_profile': True})
    # 拒绝必须发生在任何写入之前:合成根内无任何生产文件。
    assert not (authority.claim_root / prof.PLAN_FILENAME).exists()


def test_a05_cli_and_paths_have_no_root_override(authority, capsys):
    """production CLI 不暴露 root 参数;未知 root 选项拒绝(A05)。"""
    import r17_v2_c13_pipeline as pipe

    for argv in (['run', '--out', '/tmp/x', '--repo-root', '/tmp'],
                 ['run', '--out', '/tmp/x', '--claim-root', '/tmp'],
                 ['verify', '--root', '/tmp', '--release-repo', '/tmp']):
        with pytest.raises(SystemExit):
            pipe.main(argv)
    with pytest.raises(SystemExit):
        prof.main(['namespaces', '--repo-root', '/tmp'])
    # 相对路径/../symlink parent/域外根:claim 根守卫拒绝(claim_state
    # fail closed 而非旁路)。
    outside_claim = authority.repo_root.parent / 'other' / 'claim'
    outside_claim.mkdir(parents=True)
    bad = prof.Authority(repo_root=authority.repo_root,
                         claim_root=outside_claim,
                         synthetic=True)
    state = prof.claim_state(bad)
    assert state['consumed'] is True and 'error' in state


def test_a06_a07_fixed_paths_and_claim_api(authority):
    """权威路径只由 authority 推导;claim API 无 caller path/receipt。"""
    sig = inspect.signature(prof.consume_production_claim)
    assert set(sig.parameters) == {'authority'}, sig.parameters
    assert 'plan_path' not in sig.parameters
    assert 'receipt' not in sig.parameters
    assert set(inspect.signature(
        prof.persist_final_plan).parameters) == {'plan', 'authority'}
    assert set(inspect.signature(
        prof.write_preclaim_receipt).parameters) == {'receipt', 'authority'}
    assert set(inspect.signature(
        prof.persist_authoritative_evidence).parameters) == {
        'evidence', 'authority'}
    # 路径推导只依赖 authority(同 authority 等值实例给同一路径)。
    same = prof.synthetic_authority(authority.repo_root, authority.claim_root)
    assert (prof.authoritative_plan_path(authority)
            == prof.authoritative_plan_path(same)
            == authority.claim_root / prof.PLAN_FILENAME)
    assert (prof.authoritative_full_regression_path(authority)
            == authority.claim_root / prof.FULL_REGRESSION_DIRNAME)


# -------------------------------------------------------------------- G03
def test_g03_plan_persist_create_only_fsync_readback(authority):
    """最终 plan:create-only + 重读 digest 对拍;二次写拒绝。"""
    plan, persisted, _ = _persist_plan_and_receipt(authority)
    body = prof.authoritative_plan_path(authority).read_bytes()
    assert 'plan_sha256' in body.decode('utf-8')
    import hashlib

    assert persisted['file_sha256'] == hashlib.sha256(body).hexdigest()
    assert persisted['plan_sha256'] == plan['plan_sha256']
    # 已存在 → 拒绝(不覆盖)。
    with pytest.raises(Exception, match='already persisted'):
        prof.persist_final_plan(plan, authority=authority)


def test_g03_plan_digest_self_consistent(authority):
    """plan_sha256 等于除自身外全字段 canonical digest(篡改即拒绝)。"""
    plan, _, _ = _persist_plan_and_receipt(authority)
    doc = json.loads(prof.authoritative_plan_path(authority).read_text())
    assert doc['plan_sha256'] == plan['plan_sha256']
    doc['requests'][0]['tier'] = 'reserve'
    prof.authoritative_plan_path(authority).write_text(
        json.dumps(doc), encoding='utf-8')
    with pytest.raises(Exception, match='digest does not match'):
        prof.validate_plan(json.loads(
            prof.authoritative_plan_path(authority).read_text()))


# -------------------------------------------------------------------- G04
def test_g04_claim_requires_persisted_plan_file(authority):
    """claim 只能从固定权威路径取得;内存 dict/caller path 不是入口。"""
    with pytest.raises(Exception, match='authoritative plan file missing'):
        prof.consume_production_claim(authority=authority)
    plan, persisted, receipt = _persist_plan_and_receipt(authority)
    consumed = prof.consume_production_claim(authority=authority)
    assert consumed['plan_sha256'] == persisted['plan_sha256']
    claim = json.loads(
        (authority.claim_root / f'{prof.CONTRACT}.json').read_text())
    assert claim['plan_file_sha256'] == persisted['file_sha256']


def test_g04_claim_rejects_in_memory_plan_drift(authority):
    """receipt 绑定的 plan digest 与持久化文件不符 → claim 拒绝。"""
    plan, persisted, receipt = _persist_plan_and_receipt(authority)
    stale = dict(receipt, plan_sha256='ef' * 32)
    prof.receipt_path(authority).unlink()
    prof.write_preclaim_receipt(stale, authority=authority)
    with pytest.raises(Exception, match='different plan digest'):
        prof.consume_production_claim(authority=authority)


# -------------------------------------------------------------------- G05/G11
def test_g11_receipt_shape_and_stale_closure_rejected(authority):
    """receipt 形状校验;source closure 漂移(过期候选)拒绝;伪回归
    引用(unspecified/自报 rc)拒绝(F01)。"""
    plan, persisted, receipt = _persist_plan_and_receipt(authority)
    healthy_ref = receipt['full_regression_evidence']
    # 缺 admitted / 回归 rc 非零 / 缺包 digest → 形状拒绝。
    for bad in (
        dict(receipt, admitted=False),
        dict(receipt, full_regression_evidence=dict(
            healthy_ref, entry_rc=1)),
        dict(receipt, full_regression_evidence=dict(
            healthy_ref, business_rc=3)),
        dict(receipt, full_regression_evidence={
            'path': 'unspecified', 'package_sha256': 'aa' * 32,
            'entry_rc': 0, 'business_rc': 0}),
        dict(receipt, full_regression_evidence={
            'path': 'test://full-green', 'entry_rc': 0}),
        dict(receipt, full_regression_evidence={
            'path': healthy_ref['path'],
            'package_sha256': 'not-a-digest', 'entry_rc': 0,
            'business_rc': 0}),
        {k: v for k, v in receipt.items() if k != 'plan_sha256'},
        {k: v for k, v in receipt.items() if k != 'plan_file_sha256'},
    ):
        with pytest.raises(prof.ProfileError):
            prof.validate_preclaim_receipt(bad, plan_sha256='x' * 64,
                                           source_closure_sha256='y' * 64)
    # 过期候选:closure 不匹配。
    with pytest.raises(Exception, match='different source closure'):
        prof.validate_preclaim_receipt(
            receipt, plan_sha256=persisted['plan_sha256'],
            source_closure_sha256='cd' * 32)
    # 同 plan 同 closure → 通过。
    prof.validate_preclaim_receipt(
        receipt, plan_sha256=persisted['plan_sha256'],
        source_closure_sha256=receipt['source_closure_sha256'])
    # 回归证据包 digest 不匹配 → 拒绝(F10/F11 的 receipt 锚)。
    with pytest.raises(Exception, match='full-regression'):
        prof.validate_preclaim_receipt(
            receipt, plan_sha256=persisted['plan_sha256'],
            source_closure_sha256=receipt['source_closure_sha256'],
            full_regression_evidence_sha256='ee' * 32)


def test_g11_missing_receipt_fails_closed(authority):
    """权威 receipt 缺失/损坏:load fail closed,不静默跳过。"""
    with pytest.raises(Exception, match='receipt missing'):
        prof.load_preclaim_receipt(authority)
    prof.receipt_path(authority).write_text('broken{', encoding='utf-8')
    with pytest.raises(Exception, match='unreadable'):
        prof.load_preclaim_receipt(authority)


# -------------------------------------------------------------------- G06/G07
def test_g07_claim_root_escape_rejected(authority):
    """symlink/.. 相对路径/域外 claim 根:权威守卫拒绝(G07)。"""
    plan, persisted, receipt = _persist_plan_and_receipt(authority)
    state = prof.claim_state(authority)
    assert state['consumed'] is False
    # symlink 逃逸:claim 根内放符号链接指向域外文件(读取时拒绝)。
    outside = authority.repo_root.parent / 'outside.json'
    outside.write_text('{}', encoding='utf-8')
    link = authority.claim_root / 'escape'
    link.symlink_to(outside)
    resolved = link.resolve()
    assert not resolved.is_relative_to(authority.claim_root.resolve())
    # 域外 claim 根(repo 根之外)→ guard 拒绝且 fail closed。
    bad = prof.Authority(repo_root=authority.repo_root,
                         claim_root=authority.repo_root.parent / 'other'
                         / 'claim',
                         synthetic=True)
    (authority.repo_root.parent / 'other' / 'claim').mkdir(parents=True)
    state = prof.claim_state(bad)
    assert state['consumed'] is True and 'error' in state


def test_g07_second_checkout_cannot_reacquire(authority):
    """claim 已消费后,换 repo 根副本不能重取(排他文件在权威根)。"""
    plan, persisted, receipt = _persist_plan_and_receipt(authority)
    prof.consume_production_claim(authority=authority)
    assert prof.claim_state(authority)['consumed'] is True


# -------------------------------------------------------------------- G08
def test_g08_concurrent_claim_exactly_one_wins(authority):
    """两进程并发 O_EXCL:恰好一个成功;失败方不删不重试(A09)。"""
    import multiprocessing as mp

    plan, persisted, receipt = _persist_plan_and_receipt(authority)
    claim_path = authority.claim_root / f'{prof.CONTRACT}.json'

    def contender(result_q, delay, auth):
        import time

        time.sleep(delay)
        try:
            prof.consume_production_claim(authority=auth)
            result_q.put('won')
        except FileExistsError:
            result_q.put('exists')
        except Exception as exc:  # noqa: BLE001
            result_q.put(f'err:{type(exc).__name__}')

    q = mp.Queue()
    procs = [mp.Process(target=contender, args=(q, i * 0.02, authority))
             for i in range(2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
    results = [q.get(timeout=5) for _ in procs]
    assert sorted(results) == ['exists', 'won'], results
    assert claim_path.is_file()  # 失败方未删除


# -------------------------------------------------------------------- G09
def test_g09_plan_tamper_before_claim_rejected(authority):
    """claim 前 plan 文件被替换/等长篡改:receipt 文件锚拒绝。"""
    plan, persisted, receipt = _persist_plan_and_receipt(authority)
    body = prof.authoritative_plan_path(authority).read_text(encoding='utf-8')
    i = body.index('"baseline"')
    tampered = body[:i] + '"basel1ne"' + body[i + len('"baseline"'):]
    assert len(tampered) == len(body)
    prof.authoritative_plan_path(authority).write_text(tampered,
                                                       encoding='utf-8')
    with pytest.raises(Exception):
        prof.consume_production_claim(authority=authority)


# -------------------------------------------------------------------- G10
def test_g10_claim_survives_crash_no_recovery(authority):
    """claim 成功后即使进程'崩溃'(无生成):claim 永久消费(A09/A10);
    损坏 claim 同样按 consumed fail closed,无恢复/删除接口。"""
    plan, persisted, receipt = _persist_plan_and_receipt(authority)
    prof.consume_production_claim(authority=authority)
    assert prof.claim_state(authority)['consumed'] is True
    with pytest.raises(FileExistsError):
        prof.consume_production_claim(authority=authority)
    # 截断/损坏 claim → consumed fail closed。
    claim_path = authority.claim_root / f'{prof.CONTRACT}.json'
    claim_path.write_bytes(b'{truncated')
    state = prof.claim_state(authority)
    assert state['consumed'] is True and 'error' in state
    # 没有任何"删除/恢复 claim"接口。
    for forbidden in ('delete_claim', 'reset_claim', 'recover_claim',
                      'remove_claim'):
        assert not hasattr(prof, forbidden)


# -------------------------------------------------------------------- A08
def test_a08_claim_binds_closure_and_regression_digest(authority):
    """claim payload 绑定合同/plan digest/plan 文件字节/source
    closure/回归证据包 digest/消费时间(§4.3)。"""
    closure = 'ab' * 32
    pkg_sha = 'aa' * 32
    plan, persisted, receipt = _persist_plan_and_receipt(authority,
                                                         closure=closure)
    receipt['full_regression_evidence']['package_sha256'] = pkg_sha
    prof.receipt_path(authority).unlink()
    prof.write_preclaim_receipt(receipt, authority=authority)
    prof.consume_production_claim(authority=authority)
    claim = json.loads(
        (authority.claim_root / f'{prof.CONTRACT}.json').read_text())
    assert claim['profile'] == prof.CONTRACT
    assert claim['contract_sha256'] == prof.digest(plan['contract'])
    assert claim['plan_sha256'] == persisted['plan_sha256']
    assert claim['plan_file_sha256'] == persisted['file_sha256']
    assert claim['source_closure_sha256'] == closure
    assert claim['full_regression_evidence_sha256'] == pkg_sha
    assert claim['consumed_utc']


# -------------------------------------------------------------------- G12
def test_g12_plan_identity_stable_across_planning_only_hits():
    """planning-only 自引用不改变 plan 身份;namespace 扫描内容不内嵌。"""
    ev_sha = 'aa' * 32
    p1 = prof.make_plan(_runtime(), admission_evidence={
        'kind': 'namespace_unused_v1',
        'path': prof.EVIDENCE_FILENAME, 'sha256': ev_sha})
    p2 = prof.make_plan(_runtime(), admission_evidence={
        'kind': 'namespace_unused_v1',
        'path': prof.EVIDENCE_FILENAME, 'sha256': ev_sha})
    assert p1['plan_sha256'] == p2['plan_sha256']
    assert 'namespace_unused' not in p1['runtime']
    assert p1['admission_evidence']['sha256'] == ev_sha
    legacy = {'contract': p1['contract'],
              'contract_sha256': p1['contract_sha256'],
              'baseline': p1['baseline'], 'runtime': dict(
                  _runtime(), namespace_unused={'scanned': ['x']}),
              'requests': p1['requests']}
    legacy['plan_sha256'] = prof.digest(legacy)
    prof.validate_plan(legacy)


def test_g12_admission_evidence_reference_validated():
    """evidence 引用必须是 {path, sha256} 摘要,不接受内嵌观察。"""
    with pytest.raises(Exception, match='content reference'):
        prof.make_plan(_runtime(), admission_evidence={
            'kind': 'namespace_unused_v1',
            'path': prof.EVIDENCE_FILENAME,
            'sha256': 'not-a-hash'})
    with pytest.raises(Exception, match='content reference'):
        prof.make_plan(_runtime(), admission_evidence={
            'kind': 'namespace_unused_v1',
            'sha256': 'ab' * 32,
            'scanned_roots': ['/x'], 'hits': []})


# ------------------------------------------------------- preclaim 三元组
def test_preclaim_triple_create_only_and_evidence_anchor(authority):
    """prepare 三元组:evidence/plan/receipt 全 create-only;evidence
    摘要进入 plan;重复执行拒绝(不允许覆盖重试)。"""
    ev = {'scanned_roots': ['/repo/stage2_6_1/artifacts'],
          'hits': [], 'n_hits': 0, 'planning_only_hits': [],
          'unreadable_evidence': [], 'namespaces_unused': True}
    import hashlib

    out = prof.persist_authoritative_evidence(ev, authority=authority)
    body = prof.authoritative_evidence_path(authority).read_bytes()
    assert out['sha256'] == hashlib.sha256(body).hexdigest()
    assert json.loads(body) == ev
    with pytest.raises(Exception, match='already persisted'):
        prof.persist_authoritative_evidence(ev, authority=authority)
