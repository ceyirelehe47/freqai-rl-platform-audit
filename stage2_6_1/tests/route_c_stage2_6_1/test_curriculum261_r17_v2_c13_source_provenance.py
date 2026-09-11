"""R17 V2 C1/C3 治理 v2:历史 lock 恢复、治理 lock 角色与来源分层
provenance 测试(P01-P06;任务 R17V2C13GovernanceAuthorityEvidenceAndC2PrepClosure-v2)。

- P01:历史 r17_v2_c13_source_lock.py 恢复 d3cdf3d1 精确字节;
- P02:治理 lock 独立存在、角色准确、无自指/时间戳/artifact 混入;
- P03:source guard 使用治理 lock,不重签历史 lock;
- P04:旧执行闭包 591b1f35... 保持 bytes unavailable,不伪造;
- P05:五闭包角色分层正确;
- P06:受保护旧 artifact 字节快照不变(运行前后由归档层差分承载,
  这里覆盖 lock/claim 只读事实)。
"""
from __future__ import annotations

import hashlib
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

import r17_v2_c13_batch as batch
import r17_v2_c13_pipeline as pipe
import r17_v2_c13_profile as prof
import r17_v2_c13_regression_evidence as rev

#: 历史锁定文件的目标字节(任务书 §6.1)。
HISTORICAL_LOCK_SHA256 = (
    'c9152b62192a93571c16ba62e0ef2e70522f108726f3eb83fd25d48007a77c55')
HISTORICAL_LOCK_BASELINE = '769b6d282b6e870491e31e92f96828543d23ab24'
#: v2 主 run 执行闭包内的三个 runner 成员历史 sha(取自历史 lock)。
HISTORICAL_V2_RUNNER_SHAS = {
    'r17_v2_c13_batch': '6b4547f8c1b4e37949e2335575e5a5c33ca816d6bd062b'
                        '371246ed3b2da7a2db',
    'r17_v2_c13_pipeline': '93f2d59af8b1279f9bd5f7faf0102ca2f75a8a570a6aa8'
                           '5fe4d4339d213985d7',
    'r17_v2_c13_profile': 'ff192c3a4819a557c0b5a989162e64712e173eeac124be2'
                          '45dc1e22591cb8019',
}


def _lock_path(name: str) -> Path:
    return Path(pipe.__file__).resolve().parent / name


def test_p01_historical_lock_restored_bytes():
    """P01:历史 lock 文件字节 = d3cdf3d1 精确内容(只读承载)。"""
    data = _lock_path('r17_v2_c13_source_lock.py').read_bytes()
    assert hashlib.sha256(data).hexdigest() == HISTORICAL_LOCK_SHA256
    text = data.decode('utf-8')
    assert f"BASELINE = '{HISTORICAL_LOCK_BASELINE}'" in text
    assert 'locks the real execution source closure' in text
    # 历史注释未被修改。
    assert 'The historical reserve/bridge locks remain untouched.' in text
    # 历史 v2 执行闭包成员仍在(未被重签成本轮字节)。
    import ast

    tree = ast.parse(text)
    ns: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[
                0].id == 'SOURCE_SHA256':
            ns = ast.literal_eval(node.value)
    assert ns.get('r17_v2_c13_batch') == HISTORICAL_V2_RUNNER_SHAS[
        'r17_v2_c13_batch']
    assert ns.get('r17_v2_c13_pipeline') == HISTORICAL_V2_RUNNER_SHAS[
        'r17_v2_c13_pipeline']
    assert ns.get('r17_v2_c13_profile') == HISTORICAL_V2_RUNNER_SHAS[
        'r17_v2_c13_profile']


def test_p02_governance_lock_role_and_member_set():
    """P02:治理 lock 独立存在、角色声明准确、无自指/时间戳混入。"""
    import r17_v2_c13_governance_source_lock as gov

    gov.validate_member_set()
    assert set(gov.SOURCE_SHA256) == set(gov.MEMBER_MODULES)
    assert gov.MEMBER_MODULES and len(set(gov.MEMBER_MODULES)) == len(
        gov.MEMBER_MODULES)
    text = _lock_path('r17_v2_c13_governance_source_lock.py').read_text(
        encoding='utf-8')
    # 角色声明:不是 v2 主 run 执行闭包(常量 + 文档双承载)。
    assert 'NOT the v2 main-run execution closure' in gov.GOVERNANCE_ROLE
    assert '不是' in text and '591b1f35' in text
    # 不锁定自身、不混入 artifact/日志/时间戳。
    assert 'r17_v2_c13_governance_source_lock' not in gov.SOURCE_SHA256
    for forbidden in ('artifacts/', '.jsonl', '.log', 'utc', 'timestamp'):
        assert forbidden not in json.dumps(gov.SOURCE_SHA256), forbidden
    # 成员可在发布库与部署树分别复算(路径映射函数存在且双树覆盖)。
    rel_map = rev._recompute_members(Path('/nonexistent'), Path('/nonexistent'),
                                     dict(gov.SOURCE_SHA256))
    for module, entry in rel_map.items():
        assert 'release' in entry and 'deploy' in entry, module


def test_p03_source_guard_uses_governance_lock(monkeypatch):
    """P03:source_guard/RealBackend 用治理 lock;历史 lock 不被重签。"""
    src = Path(pipe.__file__).read_text(encoding='utf-8')
    assert 'r17_v2_c13_governance_source_lock' in src
    guard = pipe.source_guard()
    import r17_v2_c13_governance_source_lock as gov

    assert set(guard) == set(gov.SOURCE_SHA256)
    # 行为证明:篡改任一部署成员字节 → guard 拒绝;恢复后通过。
    victim = Path(batch.__file__).resolve()
    original = victim.read_bytes()
    try:
        victim.write_bytes(original + b'\n# tamper-probe\n')
        with pytest.raises(Exception, match='source drift'):
            pipe.source_guard()
    finally:
        victim.write_bytes(original)
    assert pipe.source_guard()  # 恢复后仍绿
    # 历史 lock 字节未因 guard 运行而改变。
    assert hashlib.sha256(
        _lock_path('r17_v2_c13_source_lock.py').read_bytes()
    ).hexdigest() == HISTORICAL_LOCK_SHA256


def test_p04_p05_provenance_layering():
    """P04/P05:旧执行闭包保持不可用;五闭包角色分层正确。"""
    release_repo = prof.production_authority().repo_root
    if not (release_repo / 'stage2_6_1' / 'runner' / (
            'r17_v2_c13_governance_source_lock.py')).is_file():
        pytest.fail(f'release repo not reachable at {release_repo}')
    prov = rev.build_source_provenance(
        release_repo, candidate_commit='ab' * 20)
    closures = prov['closures']
    assert set(closures) == {
        'v2_main_run_execution', 'previous_post_run_reader',
        'previous_governance_candidate_rejected',
        'current_candidate_governance', 'evidence_only_commit'}
    # P04:执行闭包不可用,不伪造;归档 plan 见证 digest 存在。
    execution = closures['v2_main_run_execution']
    assert execution['sha256'] == rev.V2_MAIN_RUN_EXECUTION_CLOSURE
    assert execution['bytes_available'] is False
    assert execution['usable_for_future_preclaim'] is False
    assert execution['archived_plan_witness'] is True
    # P05:只有本轮治理候选可用于未来 preclaim。
    for key in ('previous_post_run_reader',
                'previous_governance_candidate_rejected',
                'evidence_only_commit'):
        assert closures[key]['usable_for_future_preclaim'] is False, key
    current = closures['current_candidate_governance']
    assert current['usable_for_future_preclaim'] is True
    assert current['members_digest'] == hashlib.sha256(json.dumps(
        current['members'], sort_keys=True, separators=(',', ':'),
        ensure_ascii=False).encode('utf-8')).hexdigest()
    assert current['role'].startswith('post-run governance')


def test_p06_protected_lock_and_claim_facts_readonly():
    """P06:生产 claim 状态只读快照事实(v1/v2 claim 已消费;历史 lock
    不变)。"""
    state = prof.claim_state()
    assert state['consumed'] is True
    assert state['path'].startswith('/mnt/f/trading/freqai-rl-audit')
    assert hashlib.sha256(
        _lock_path('r17_v2_c13_source_lock.py').read_bytes()
    ).hexdigest() == HISTORICAL_LOCK_SHA256
    # 治理 lock 与历史 lock 是两个独立文件。
    assert (_lock_path('r17_v2_c13_source_lock.py').resolve()
            != _lock_path('r17_v2_c13_governance_source_lock.py').resolve())
