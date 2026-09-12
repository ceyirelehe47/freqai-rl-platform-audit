def _claim_fixture(tmp_path, monkeypatch, runtime=None):
    """G03-G04 协议夹具:显式 synthetic authority,权威 plan+receipt
    先持久化,claim 从固定权威路径取得。"""
    repo_root = tmp_path / 'repo'
    claim = repo_root / 'stage2_6_1' / 'artifacts' / 'repair17' \
        / 'development' / 'v2_c13_engineering_claim'
    claim.mkdir(parents=True, exist_ok=True)
    (repo_root / 'stage2_6_1' / 'artifacts').mkdir(parents=True,
                                                   exist_ok=True)
    auth = prof.synthetic_authority(repo_root, claim)
    plan = prof.make_plan(runtime or fixture_runtime())
    persisted = prof.persist_final_plan(plan, authority=auth)
    receipt = {
        'profile': prof.CONTRACT, 'admitted': True,
        'plan_sha256': persisted['plan_sha256'],
        'plan_file_sha256': persisted['file_sha256'],
        'source_closure_sha256': 'ab' * 32,
        'full_regression_evidence': {
            'path': str(prof.authoritative_full_regression_path(auth)),
            'package_sha256': 'aa' * 32, 'entry_rc': 0, 'business_rc': 0},
        'evidence_sha256': 'bb' * 32,
    }
    prof.write_preclaim_receipt(receipt, authority=auth)
    return plan, persisted, receipt, auth


def test_v10_one_shot_claim(tmp_path, monkeypatch):
    plan, persisted, receipt, auth = _claim_fixture(tmp_path, monkeypatch)
    assert prof.claim_state(auth)['consumed'] is False
    consumed = prof.consume_production_claim(authority=auth)
    state = prof.claim_state(auth)
    assert state['consumed'] is True
    assert state['plan_sha256'] == plan['plan_sha256']
    # claim payload 绑定持久化 plan 文件字节(G04/G09 锚)。
    assert consumed['plan_sha256'] == persisted['plan_sha256']
    # 换 out/run_id 不会重新取得:第二次 consume 直接失败。
    with pytest.raises(FileExistsError):
        prof.consume_production_claim(authority=auth)
    # 换 plan(不同 runtime)同样不能重取:claim 文件已排他存在。
    plan2 = prof.make_plan({'kind': 'test_fixture',
                            'generators': copy.deepcopy(GENERATORS),
                            'sources': {}, 'interpreter': 'other'})
    assert plan2['plan_sha256'] != plan['plan_sha256']
    with pytest.raises(FileExistsError):
        prof.consume_production_claim(authority=auth)


def test_v10_corrupted_claim_is_consumed_not_retried(tmp_path,
                                                     monkeypatch):
    plan, persisted, receipt, auth = _claim_fixture(tmp_path, monkeypatch)
    (auth.claim_root / f'{prof.CONTRACT}.json').write_text(
        'not-json{', encoding='utf-8')
    state = prof.claim_state(auth)
    assert state['consumed'] is True and 'error' in state
    # 损坏 claim 不删除重试:consume 仍拒绝(fail closed)。
    with pytest.raises(FileExistsError):
        prof.consume_production_claim(authority=auth)
