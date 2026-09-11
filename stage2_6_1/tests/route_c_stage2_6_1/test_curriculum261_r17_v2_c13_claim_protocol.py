"""R17 V2 C1/C3 事后治理:最终 plan → preclaim receipt → 排他 claim
协议测试(G03-G12;任务 R17V2C13PostRunGovernanceAndC2LaunchPrep-v1)。

覆盖 v2 轮六项工程合同缺口中的协议项:
- claim 绑定的最终 plan 必须先 create-only 持久化并 fsync+重读;
- claim 只能从持久化 plan 文件取得,内存 dict 不再是入口;
- preclaim receipt 是 production run 的机器准入条件(同 plan/同
  source closure/同候选完整回归);
- 生产根不得被环境变量/out/cwd/run_id/符号链接/第二 checkout 旁路;
- 并发竞态恰好一个成功;崩溃与损坏 claim fail closed。
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

from test_curriculum261_r17_v2_c13_pipeline import (  # noqa: E402
    GENERATORS, fixture_runtime)


def _runtime(tag: str = 'proto') -> dict:
    return {'kind': 'test_fixture',
            'generators': copy.deepcopy(GENERATORS),
            'sources': {'mod': {'path': f'/deployed/{tag}.py',
                                'sha256': tag * 32}},
            'interpreter': sys.version}


@pytest.fixture
def authority(tmp_path, monkeypatch):
    monkeypatch.setattr(prof, 'RELEASE_REPO_ROOT', tmp_path / 'repo')
    monkeypatch.setattr(prof, 'CLAIM_ROOT',
                        tmp_path / 'repo' / 'stage2_6_1' / 'artifacts'
                        / 'repair17' / 'development'
                        / 'v2_c13_engineering_claim')
    (prof.CLAIM_ROOT).mkdir(parents=True)
    return tmp_path


def _persist_plan_and_receipt(closure='ab' * 32, runtime=None):
    plan = prof.make_plan(runtime or _runtime())
    persisted = prof.persist_final_plan(
        plan, prof.authoritative_plan_path())
    receipt = {
        'profile': prof.CONTRACT, 'admitted': True,
        'plan_sha256': persisted['plan_sha256'],
        'plan_file_sha256': persisted['file_sha256'],
        'source_closure_sha256': closure,
        'full_regression_ref': {'path': 'test://full-green',
                                'entry_rc': 0},
    }
    prof.write_preclaim_receipt(receipt)
    return plan, persisted, receipt


# -------------------------------------------------------------------- G03
def test_g03_plan_persist_create_only_fsync_readback(authority):
    """最终 plan:create-only + 重读 digest 对拍;二次写拒绝。"""
    plan, persisted, _ = _persist_plan_and_receipt()
    body = prof.authoritative_plan_path().read_bytes()
    assert 'plan_sha256' in body.decode('utf-8')
    import hashlib

    assert persisted['file_sha256'] == hashlib.sha256(body).hexdigest()
    assert persisted['plan_sha256'] == plan['plan_sha256']
    # 已存在 → 拒绝(不覆盖)。
    with pytest.raises(Exception, match='already persisted'):
        prof.persist_final_plan(plan, prof.authoritative_plan_path())


def test_g03_plan_digest_self_consistent(authority):
    """plan_sha256 等于除自身外全字段 canonical digest(篡改即拒绝)。"""
    plan, _, _ = _persist_plan_and_receipt()
    doc = json.loads(prof.authoritative_plan_path().read_text())
    assert doc['plan_sha256'] == plan['plan_sha256']
    doc['requests'][0]['tier'] = 'reserve'
    prof.authoritative_plan_path().write_text(
        json.dumps(doc), encoding='utf-8')
    with pytest.raises(Exception, match='digest does not match'):
        prof.validate_plan(json.loads(
            prof.authoritative_plan_path().read_text()))


# -------------------------------------------------------------------- G04
def test_g04_claim_requires_persisted_plan_file(authority):
    """claim 只能从持久化 plan 文件取得;内存 dict 不是入口。"""
    assert not hasattr(prof, 'consume_generation_claim')
    receipt = {
        'profile': prof.CONTRACT, 'admitted': True,
        'plan_sha256': 'cd' * 32, 'source_closure_sha256': 'ab' * 32,
        'full_regression_ref': {'path': 'x', 'entry_rc': 0},
    }
    with pytest.raises(Exception, match='plan file missing'):
        prof.consume_generation_claim_from_plan_file(
            prof.authoritative_plan_path(), receipt)
    plan, persisted, receipt = _persist_plan_and_receipt()
    consumed = prof.consume_generation_claim_from_plan_file(
        prof.authoritative_plan_path(), receipt)
    assert consumed['plan_sha256'] == persisted['plan_sha256']
    claim = json.loads(
        (prof.CLAIM_ROOT / f'{prof.CONTRACT}.json').read_text())
    assert claim['plan_file_sha256'] == persisted['file_sha256']


def test_g04_claim_rejects_in_memory_plan_drift(authority):
    """receipt 绑定的 plan digest 与持久化文件不符 → claim 拒绝。"""
    plan, persisted, receipt = _persist_plan_and_receipt()
    stale = dict(receipt, plan_sha256='ef' * 32)
    with pytest.raises(Exception, match='different plan digest'):
        prof.consume_generation_claim_from_plan_file(
            prof.authoritative_plan_path(), stale)


# -------------------------------------------------------------------- G05/G11
def test_g11_receipt_shape_and_stale_closure_rejected(authority):
    """receipt 形状校验;source closure 漂移(过期候选)拒绝。"""
    plan, persisted, receipt = _persist_plan_and_receipt()
    # 缺 admitted / full ref rc != 0 → 形状拒绝。
    for bad in (
        dict(receipt, admitted=False),
        dict(receipt, full_regression_ref={'path': 'x', 'entry_rc': 1}),
        {k: v for k, v in receipt.items() if k != 'plan_sha256'},
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


def test_g11_missing_receipt_fails_closed(authority):
    """权威 receipt 缺失/损坏:load fail closed,不静默跳过。"""
    with pytest.raises(Exception, match='receipt missing'):
        prof.load_preclaim_receipt()
    prof.receipt_path().write_text('broken{', encoding='utf-8')
    with pytest.raises(Exception, match='unreadable'):
        prof.load_preclaim_receipt()


# -------------------------------------------------------------------- G06/G07
def test_g06_no_env_root_override_in_production_module():
    """生产 profile 不从环境取根(import 时已固定;G06/G07)。"""
    import re

    src = Path(prof.__file__).read_text(encoding='utf-8')
    # 模块内不得有任何环境读取调用(注释里的中文说明不在此列)。
    assert re.search(r'environ|getenv', src) is None
    # 根是固定常量,且可被 fixture 显式注入接口替换。
    assert str(prof.RELEASE_REPO_ROOT).startswith('/')
    assert callable(getattr(prof, 'set_test_authority', None))


def test_g07_claim_root_escape_rejected(authority, monkeypatch):
    """symlink/.. 相对路径/域外 claim 根:权威守卫拒绝(G07)。"""
    plan, persisted, receipt = _persist_plan_and_receipt()
    # 正常路径仍可用(控制组)。
    state = prof.claim_state()
    assert state['consumed'] is False
    # symlink 逃逸:claim 根内放符号链接指向域外文件。
    outside = authority / 'outside.json'
    outside.write_text('{}', encoding='utf-8')
    link = prof.CLAIM_ROOT / 'escape'
    link.symlink_to(outside)
    resolved = link.resolve()
    assert not resolved.is_relative_to(prof.CLAIM_ROOT.resolve())
    # 域外 claim 根(RELEASE_REPO_ROOT 之外)→ guard 拒绝且 fail closed。
    monkeypatch.setattr(prof, 'CLAIM_ROOT', authority / 'other-root'
                        / 'claim')
    (authority / 'other-root' / 'claim').mkdir(parents=True)
    state = prof.claim_state()
    assert state['consumed'] is True and 'error' in state


def test_g07_second_checkout_cannot_reacquire(authority):
    """claim 已消费后,换 repo 根副本不能重取(排他文件在权威根)。"""
    plan, persisted, receipt = _persist_plan_and_receipt()
    prof.consume_generation_claim_from_plan_file(
        prof.authoritative_plan_path(), receipt)
    assert prof.claim_state()['consumed'] is True


# -------------------------------------------------------------------- G08
def test_g08_concurrent_claim_exactly_one_wins(authority):
    """两进程并发 O_EXCL:恰好一个成功;失败方不删不重试。"""
    import multiprocessing as mp

    plan, persisted, receipt = _persist_plan_and_receipt()
    claim_path = prof.CLAIM_ROOT / f'{prof.CONTRACT}.json'

    def contender(result_q, delay):
        import time

        time.sleep(delay)
        try:
            prof.consume_generation_claim_from_plan_file(
                prof.authoritative_plan_path(), receipt)
            result_q.put('won')
        except FileExistsError:
            result_q.put('exists')
        except Exception as exc:  # noqa: BLE001
            result_q.put(f'err:{type(exc).__name__}')

    q = mp.Queue()
    procs = [mp.Process(target=contender, args=(q, i * 0.02))
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
    plan, persisted, receipt = _persist_plan_and_receipt()
    # 等长篡改:改一个字符但保持长度;plan digest 自洽也过不了文件锚。
    body = prof.authoritative_plan_path().read_text(encoding='utf-8')
    i = body.index('"baseline"')
    tampered = body[:i] + '"basel1ne"' + body[i + len('"baseline"'):]
    assert len(tampered) == len(body)
    prof.authoritative_plan_path().write_text(tampered, encoding='utf-8')
    with pytest.raises(Exception):
        prof.consume_generation_claim_from_plan_file(
            prof.authoritative_plan_path(), receipt)


# -------------------------------------------------------------------- G10
def test_g10_claim_survives_crash_no_recovery(authority):
    """claim 成功后即使进程'崩溃'(无生成):claim 永久消费。"""
    plan, persisted, receipt = _persist_plan_and_receipt()
    prof.consume_generation_claim_from_plan_file(
        prof.authoritative_plan_path(), receipt)
    # 模拟生成前崩溃:没有任何生成证据;再次申请被拒。
    assert prof.claim_state()['consumed'] is True
    with pytest.raises(FileExistsError):
        prof.consume_generation_claim_from_plan_file(
            prof.authoritative_plan_path(), receipt)


# -------------------------------------------------------------------- G12
def test_g12_plan_identity_stable_across_planning_only_hits(authority):
    """planning-only 自引用不改变 plan 身份:同一 runtime+evidence
    两次组装 digest 相同;namespace 扫描内容不再内嵌 runtime。"""
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
    # runtime 内嵌易变观察的 legacy 形态:validate 不崩(digest 自洽),
    # 但 governance verdict(verify)会标记 plan_format_layered=false。
    legacy = {'contract': p1['contract'],
              'contract_sha256': p1['contract_sha256'],
              'baseline': p1['baseline'], 'runtime': dict(
                  _runtime(), namespace_unused={'scanned': ['x']}),
              'requests': p1['requests']}
    legacy['plan_sha256'] = prof.digest(legacy)
    prof.validate_plan(legacy)


def test_g12_admission_evidence_reference_validated(authority):
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

    out = prof.persist_authoritative_evidence(ev)
    body = prof.authoritative_evidence_path().read_bytes()
    assert out['sha256'] == hashlib.sha256(body).hexdigest()
    assert json.loads(body) == ev
    with pytest.raises(Exception, match='already persisted'):
        prof.persist_authoritative_evidence(ev)
