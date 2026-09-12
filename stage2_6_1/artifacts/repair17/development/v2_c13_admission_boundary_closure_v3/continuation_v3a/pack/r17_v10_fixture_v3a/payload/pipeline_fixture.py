def _claim_fixture(tmp_path, monkeypatch, runtime=None):
    """V10:复用已适配 v3 的健康协议夹具,不复制旧假回执。

    延迟导入避免两个测试模块在收集时循环初始化。默认 runtime、
    synthetic 合同、真实临时回归包和各层摘要都由同一构造函数产生;
    此处只负责隔离 authority,不替换/绕过任何生产校验函数。
    """
    from test_curriculum261_r17_v2_c13_claim_protocol import (
        _persist_plan_and_receipt,
    )

    repo_root = tmp_path / 'repo'
    claim = repo_root / 'stage2_6_1' / 'artifacts' / 'repair17' \
        / 'development' / 'v2_c13_engineering_claim'
    claim.mkdir(parents=True, exist_ok=True)
    auth = prof.synthetic_authority(repo_root, claim)
    # 未传 runtime 时使用协议夹具的非空 synthetic source identity,
    # 而不是 fixture_runtime() 的空 sources。传入的 runtime 由调用方
    # 明确负责;不替 caller 补造 source identity。
    plan, persisted, receipt = _persist_plan_and_receipt(
        auth, runtime=copy.deepcopy(runtime) if runtime is not None else None)
    return plan, persisted, receipt, auth


def test_v10_fixture_is_evidence_backed_and_not_production(tmp_path, monkeypatch):
    """健康 fixture 必须有实包,可只读准入检查,不能授予生产资格。"""
    import r17_v2_c13_regression_evidence as rev
    from r17_v2_c13_admission_guard import tree_index

    plan, persisted, receipt, auth = _claim_fixture(tmp_path, monkeypatch)
    package = prof.authoritative_full_regression_path(auth)
    assert auth.synthetic is True
    assert plan['runtime']['kind'] == 'test_fixture'
    assert plan['contract'].get('synthetic_profile') is True
    assert plan['runtime']['sources']
    assert package.is_dir()
    assert receipt['full_regression_evidence']['path'] == str(package)
    assert receipt['full_regression_evidence']['package_sha256'] == rev.package_digest(package)
    assert receipt['source_closure_sha256'] == prof.digest(plan['runtime']['sources'])
    assert persisted['file_sha256'] == hashlib.sha256(
        prof.authoritative_plan_path(auth).read_bytes()).hexdigest()
    before = tree_index(auth.repo_root)
    verdict = rev.verify_package(
        package, authority=auth, current_sources=plan['runtime']['sources'],
        checks='structural')
    assert verdict['ok'], verdict['errors']
    assert verdict['admission_eligible'] is False
    admitted = prof.validate_claim_admission(auth)
    assert admitted['plan']['plan_sha256'] == plan['plan_sha256']
    assert admitted['full_regression_evidence_sha256'] == verdict['package_sha256']
    assert tree_index(auth.repo_root) == before
    assert prof.claim_state(auth)['consumed'] is False
    assert not (auth.claim_root / f'{prof.CONTRACT}.json').exists()


@pytest.mark.parametrize('mutation,error', [
    ('production_contract', 'production/synthetic contract and authority disagree'),
    ('missing_regression', 'full regression evidence rejected at claim'),
    ('fake_regression_digest', 'different full-regression evidence package'),
    ('missing_admission', 'authoritative admission evidence missing'),
])
def test_v10_unhealthy_fixture_is_still_rejected(tmp_path, monkeypatch, mutation, error):
    """修复的是成功夹具;旧不健康形态仍须在写 claim 前被拒绝。"""
    import shutil
    from r17_v2_c13_admission_guard import tree_index

    plan, persisted, receipt, auth = _claim_fixture(tmp_path, monkeypatch)
    if mutation == 'production_contract':
        # 在临时副本中重算外层摘要,确保命中合同/authority层,不是摘要层。
        plan['contract'] = prof.fixed_contract()
        plan['contract_sha256'] = prof.digest(plan['contract'])
        plan['plan_sha256'] = prof.digest({
            k: v for k, v in plan.items() if k != 'plan_sha256'})
        body = (prof.canonical(plan) + '\n').encode('utf-8')
        prof.authoritative_plan_path(auth).write_bytes(body)
        receipt['plan_sha256'] = plan['plan_sha256']
        receipt['plan_file_sha256'] = hashlib.sha256(body).hexdigest()
    elif mutation == 'missing_regression':
        shutil.rmtree(prof.authoritative_full_regression_path(auth))
    elif mutation == 'fake_regression_digest':
        assert receipt['full_regression_evidence']['package_sha256'] != 'aa' * 32
        receipt['full_regression_evidence']['package_sha256'] = 'aa' * 32
    elif mutation == 'missing_admission':
        prof.authoritative_evidence_path(auth).unlink()
    else:
        raise AssertionError(f'unknown fixture mutation: {mutation}')
    # 只修改 pytest 临时夹具,不触碰任何生产/历史文件。
    prof.receipt_path(auth).write_text(
        prof.canonical(receipt) + '\n', encoding='utf-8')
    before = tree_index(auth.repo_root)
    with pytest.raises(prof.ProfileError, match=error):
        prof.consume_production_claim(authority=auth)
    assert not (auth.claim_root / f'{prof.CONTRACT}.json').exists()
    assert prof.claim_state(auth)['consumed'] is False
    assert tree_index(auth.repo_root) == before
