"""Engineering Bridge 测试:qualified input 统一锁(I01-I04/V01/G01/N01/M01/M02)。

纪律:
- 本文件测试**零原生生成、零 optimizer 更新**(K01 边界观察用中止型
  recorder,在真实 generator.generate 调用前拦截;env/前向测试只用合成
  episode 与无梯度前向);
- 工程夹具由 ppo262_eng_fixture.build_eng_fixture 构建(合成 fit 来源,
  SYNTHETIC/ENGINEERING_ONLY);
- 旧 R2 默认路径与黄金 digest 保持不变是显式断言(I04)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.ppo262_qualified_input import (
    FORMAL_ADMISSION_REGISTRY,
    QUALIFICATION_PLAN_DIGEST_FILENAME,
    QUALIFICATION_RESULT_FILENAME,
    QualifiedInputError,
    authorization_binding_digest,
    load_qualified_input,
    parameter_pack_digest,
    qualification_plan_digest,
)


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def fixture_root(tmp_path_factory):
    """两个 pack 变体的工程资格夹具(构建一次,模块内共享)。"""
    from rl_curriculum.ppo262_eng_fixture import build_eng_fixture
    root = tmp_path_factory.mktemp("eng_fixture")
    outs = {}
    for variant in ("v1_r2_reference", "v2_perturbed"):
        outs[variant] = build_eng_fixture(root, variant=variant, verbose=False)
    return root, outs


@pytest.fixture(scope="module")
def v1(fixture_root):
    return fixture_root[1]["v1_r2_reference"]


@pytest.fixture(scope="module")
def v2(fixture_root):
    return fixture_root[1]["v2_perturbed"]


def _load(out, scope="engineering", **kw):
    return load_qualified_input(
        out["qualification_dir"], authorization_path=out["authorization_path"],
        expected_scope=scope, **kw)


def _load_reject(out, scope="engineering", **kw):
    with pytest.raises(QualifiedInputError) as ei:
        _load(out, scope=scope, **kw)
    return ei.value.report


# ---------------------------------------------------------------- I01
def test_i01_full_public_positive_path(v1):
    qi = _load(v1)
    assert qi.plan_digest == v1["qualification_plan_digest"]
    assert qi.pack_digest == v1["parameter_pack_digest"]
    assert qi.bundle_hash == v1["preprocessor_bundle_hash"]
    rep = qi.validation_report
    assert not rep["rejected"]
    assert all(rep["checks"].values())
    # 参数与阈值唯一来源 = 快照 pack
    rp = qi.rung_params()
    assert set(rp) == {"c1_opportunity", "c2_context", "c3_cost"}
    assert set(rp["c1_opportunity"]) == {"D0", "D1", "D2", "D3"}
    assert isinstance(qi.reference_thresholds()["c1_opportunity"], dict)


def test_i01_cli_eng_input_lock_positive(v1, tmp_path, capsys):
    from rl_curriculum.ppo262_cli import main
    rc = main(["eng-input-lock",
               "--qual-dir", v1["qualification_dir"],
               "--auth", v1["authorization_path"]])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pass"] is True
    assert out["engineering_only"] is True


# ---------------------------------------------------------------- I02
def test_i02_missing_result_file_rejected(v1):
    qdir = Path(v1["qualification_dir"])
    with pytest.raises(QualifiedInputError):
        with (qdir / QUALIFICATION_RESULT_FILENAME).open() as fh:
            content = fh.read()
        (qdir / QUALIFICATION_RESULT_FILENAME).unlink()
        try:
            _load(v1)
        finally:
            (qdir / QUALIFICATION_RESULT_FILENAME).write_text(
                content, encoding="utf-8")


def _mutate_copy(v1, tmp_path, filename, mutate):
    """复制夹具到 tmp 并按 mutator 改写一个 JSON 文件,返回新路径 dict。"""
    import shutil
    new_root = tmp_path / "mut"
    shutil.copytree(v1["qualification_dir"], new_root)
    p = new_root / filename
    data = json.loads(p.read_text(encoding="utf-8"))
    mutate(data)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False,
                            sort_keys=True), encoding="utf-8")
    out = dict(v1)
    out["qualification_dir"] = str(new_root)
    return out


def test_i02_non_pass_verdict_rejected(v1, tmp_path):
    out = _mutate_copy(v1, tmp_path, QUALIFICATION_RESULT_FILENAME,
                       lambda d: d.update(verdict="FAIL"))
    report = _load_reject(out)
    assert any("verdict" in p for p in report["problems"])


def test_i02_result_binds_wrong_plan_rejected(v1, tmp_path):
    out = _mutate_copy(v1, tmp_path, QUALIFICATION_RESULT_FILENAME,
                       lambda d: d.update(plan_digest="qp262e-forged"))
    report = _load_reject(out)
    assert any("result 未绑定 plan digest" in p for p in report["problems"])


def test_i02_exposure_not_completed_rejected(v1, tmp_path):
    out = _mutate_copy(v1, tmp_path, "qualification_exposure.json",
                       lambda d: d.update(status="running"))
    report = _load_reject(out)
    assert any("exposure" in p for p in report["problems"])


def test_i02_pack_swap_rejected(v2, tmp_path):
    """pack 已通过输入锁字形,但 digest 与 plan 绑定不一致 => 拒。"""
    import shutil
    new_root = tmp_path / "packswap"
    shutil.copytree(v2["qualification_dir"], new_root)
    v1_pack = json.loads((
        Path(v2["qualification_dir"]).parent
        / "qualified_input_v1_r2_reference" / "parameter_pack.json"
    ).read_text(encoding="utf-8"))
    (new_root / "parameter_pack.json").write_text(
        json.dumps(v1_pack, indent=2, sort_keys=True), encoding="utf-8")
    out = dict(v2)
    out["qualification_dir"] = str(new_root)
    report = _load_reject(out)
    assert any("pack digest" in p for p in report["problems"])


def test_i02_envelope_tamper_rejected(v1, tmp_path):
    """scaler 参数数值篡改 => envelope 三层哈希复算失败。"""
    out = _mutate_copy(v1, tmp_path, "preprocessor_envelope.json",
                       lambda d: d["parameter_state"]["scaler"][
                           "data_min_"].__setitem__(0, -123.0))
    report = _load_reject(out)
    assert any("envelope" in p or "bundle" in p
               for p in report["problems"])


def test_i02_r2_dir_cannot_pose_as_qualified_input():
    """旧 R2 工件目录冒充新版资格输入 => format 拒绝。"""
    from rl_curriculum.curriculum261_api import qualification_r2_lock_marker
    with pytest.raises(QualifiedInputError) as ei:
        load_qualified_input(
            qualification_r2_lock_marker().parent,
            authorization_path="/nonexistent.json",
            expected_scope="engineering")
    problems = ei.value.report["problems"]
    assert any("缺件" in p or "授权" in p for p in problems)


# ---------------------------------------------------------------- I03
def test_i03_replaced_pack_rejected_on_reload_snapshot_stable(v1, tmp_path):
    """校验后文件被替换:新装载拒绝;内存快照仍用已验证内容。"""
    import shutil
    new_root = tmp_path / "moved"
    shutil.copytree(v1["qualification_dir"], new_root)
    auth = Path(v1["authorization_path"])
    out = dict(v1)
    out["qualification_dir"] = str(new_root)
    qi = _load(out)  # 同字节移位后合法装载(见下一个测试)
    before = qi.rung_params()["c1_opportunity"]["D1"]["opp_drift_bps"]
    # 替换 pack 字节(v2 的 pack 换入)
    v2_pack = json.loads((
        Path(v1["qualification_dir"]).parent
        / "qualified_input_v2_perturbed" / "parameter_pack.json"
    ).read_text(encoding="utf-8"))
    (new_root / "parameter_pack.json").write_text(
        json.dumps(v2_pack, indent=2, sort_keys=True), encoding="utf-8")
    report = _load_reject(out)
    assert any("pack digest" in p for p in report["problems"])
    # 快照不受磁盘替换影响
    assert qi.rung_params()["c1_opportunity"]["D1"][
        "opp_drift_bps"] == before


def test_i03_same_bytes_relocated_loads(v1, tmp_path):
    """同字节合法移位:身份由 digest 决定,不因路径/文件名误拒。"""
    import shutil
    new_root = tmp_path / "relocated"
    shutil.copytree(v1["qualification_dir"], new_root)
    new_auth = tmp_path / "auth_copy.json"
    shutil.copyfile(v1["authorization_path"], new_auth)
    qi = load_qualified_input(
        new_root, authorization_path=new_auth, expected_scope="engineering")
    assert qi.plan_digest == v1["qualification_plan_digest"]


def test_i03_self_authorization_rejected(v1, tmp_path):
    """授权文件放进资格目录内部 => 自授权拒绝。"""
    import shutil
    new_root = tmp_path / "selfauth"
    shutil.copytree(v1["qualification_dir"], new_root)
    inside = new_root / "eng_authorization_inside.json"
    shutil.copyfile(v1["authorization_path"], inside)
    with pytest.raises(QualifiedInputError) as ei:
        load_qualified_input(new_root, authorization_path=inside,
                             expected_scope="engineering")
    assert any("自授权" in p for p in ei.value.report["problems"])


# ---------------------------------------------------------------- I04
def test_i04_r2_default_unchanged():
    from rl_curriculum.curriculum261_api import qualification_r2_lock_marker
    from rl_curriculum.curriculum261_plan import load_locked_plan
    from rl_curriculum.ppo262_cli import (
        _locked_reference_thresholds, _locked_rung_params,
    )
    from rl_curriculum.ppo262_input_lock import R2_EXPECTED_PLAN_DIGEST
    assert R2_EXPECTED_PLAN_DIGEST == (
        "qp-8f64a1b5619c6eda4cf8639f4e5237e8b9b68a63a15fe67ee2e41c15db"
        "07af99")
    plan, digest = load_locked_plan(qualification_r2_lock_marker().parent)
    assert digest == R2_EXPECTED_PLAN_DIGEST
    assert _locked_rung_params()["c1_opportunity"] == (
        plan["families"]["c1_opportunity"]["rung_params"])
    assert _locked_reference_thresholds()["c3_cost"] == (
        plan["families"]["c3_cost"]["reference_thresholds"])


def test_i04_262_seed_golden_unchanged():
    """旧 namespace 派生黄金值钉死(未因工程 namespace 扩充改变)。"""
    from rl_curriculum.ppo262_namespaces import derive262_seed
    assert derive262_seed(
        "ppo_smoke_262", "c1_opportunity", "D1", 0, 0) == 2721149688598171913


def test_i04_new_profile_reads_new_input_not_r2(v2):
    from rl_curriculum.ppo262_cli import _locked_rung_params
    qi = _load(v2)
    new = qi.rung_params()["c1_opportunity"]["D1"]
    r2 = _locked_rung_params()["c1_opportunity"]["D1"]
    assert new["opp_drift_bps"] == 45.0 and r2["opp_drift_bps"] == 42.0
    assert new != r2  # 新 profile 实际读取新输入,不是 R2


# ---------------------------------------------------------------- V01
def test_v01_bundle_reload_identical_transform(v1):
    from rl_curriculum.curriculum261_r4_preprocessing import (
        RouteCPreprocessorV2,
    )
    from rl_curriculum.ppo262_eng_fixture import (
        synthetic_ohlcv, ENG_FIT_FIXTURE_SPECS,
    )
    from rl_curriculum.curriculum261_production_obs import (
        attach_production_features,
    )
    p1 = RouteCPreprocessorV2.load_envelope(
        Path(v1["qualification_dir"]) / "preprocessor_envelope.json")
    p2 = RouteCPreprocessorV2.load_envelope(
        Path(v1["qualification_dir"]) / "preprocessor_envelope.json")
    assert p1.bundle_hash == p2.bundle_hash == v1["preprocessor_bundle_hash"]
    df = attach_production_features(
        synthetic_ohlcv(ENG_FIT_FIXTURE_SPECS[1]))
    a = p1.transform_episode_df(df)
    b = p2.transform_episode_df(df)
    assert a.equals(b)
    # eval 数据改变不触发 refit,不改变 bundle 身份
    other = attach_production_features(
        synthetic_ohlcv({**ENG_FIT_FIXTURE_SPECS[1], "start": 999.0}))
    p1.transform_episode_df(other)
    assert p1.bundle_hash == v1["preprocessor_bundle_hash"]
    assert p1.parameter_state_hash == p2.parameter_state_hash


def test_v01_same_scaler_params_different_fit_manifest_differs(v1, tmp_path):
    """scaler 数值相同、fit 来源清单不同 => bundle 身份不同。"""
    from rl_curriculum.curriculum261_r4_preprocessing import (
        FitManifestEntry, RouteCPreprocessorV2,
    )
    base = RouteCPreprocessorV2.load_envelope(
        Path(v1["qualification_dir"]) / "preprocessor_envelope.json")
    forged_entries = [
        FitManifestEntry(
            namespace=e.namespace, family=e.family, rung=e.rung,
            pair_index=e.pair_index, side=e.side,
            episode_hash="e262fx-forged" + str(e.pair_index),
            feature_matrix_hash=e.feature_matrix_hash,
            generator_identity=e.generator_identity)
        for e in base.entries]
    forged = RouteCPreprocessorV2(base.inner, forged_entries, base.namespace)
    assert (forged.parameter_state_hash == base.parameter_state_hash)
    assert forged.bundle_hash != base.bundle_hash
    # 消费侧:错绑 bundle 在装载处拒绝(plan 绑定的是原 bundle)
    env_path = tmp_path / "forged_envelope.json"
    forged.serialize_envelope(env_path)
    import shutil
    new_root = tmp_path / "bundleswap"
    shutil.copytree(v1["qualification_dir"], new_root)
    shutil.copyfile(env_path, new_root / "preprocessor_envelope.json")
    out = dict(v1)
    out["qualification_dir"] = str(new_root)
    report = _load_reject(out)
    assert any("bundle" in p for p in report["problems"])


# ---------------------------------------------------------------- G01
def test_g01_engineering_fixture_cannot_unlock_formal(v1):
    report = _load_reject(v1, scope="formal")
    assert any("scope" in p for p in report["problems"])


def test_g01_forged_formal_authorization_rejected(v1, tmp_path):
    """重算摘要并伪造 formal 授权 JSON:admission 注册表防线仍拒绝。"""
    import shutil
    new_root = tmp_path / "formalized"
    shutil.copytree(v1["qualification_dir"], new_root)
    plan = json.loads(
        (new_root / "qualification_plan.json").read_text(encoding="utf-8"))
    plan["scope"] = "formal"
    (new_root / "qualification_plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
    digest = qualification_plan_digest(plan)
    (new_root / QUALIFICATION_PLAN_DIGEST_FILENAME).write_text(
        digest + "\n", encoding="utf-8")
    pack = json.loads(
        (new_root / "parameter_pack.json").read_text(encoding="utf-8"))
    bindings = {
        "qualification_plan_digest": digest,
        "parameter_pack_digest": parameter_pack_digest(pack),
        "preprocessor_bundle_hash": v1["preprocessor_bundle_hash"],
    }
    forged = {
        "format": "ppo262e-training-authorization-v1",
        "profile": "ppo262_engineering_v1",
        "scope": "formal",
        "bindings": bindings,
        "binding_digest": authorization_binding_digest({
            **bindings, "profile": "ppo262_engineering_v1",
            "scope": "formal"}),
        "admission_anchor": {"file": "forged_admission.json",
                             "sha256": "0" * 64},
        "issued_by": "forged",
    }
    auth_path = tmp_path / "forged_auth.json"
    auth_path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(QualifiedInputError) as ei:
        load_qualified_input(new_root, authorization_path=auth_path,
                             expected_scope="formal")
    assert any("admission" in p for p in ei.value.report["problems"])
    assert FORMAL_ADMISSION_REGISTRY == {}


def test_g01_engineering_bytes_cannot_enter_r2_chain(v1, tmp_path):
    """工程 plan 字节换入 R2 锁目录 => load_locked_plan digest 复算抛错。"""
    import shutil
    from rl_curriculum.curriculum261_plan import load_locked_plan
    # 用 R2 真实锁目录的拷贝,避免碰原件
    from rl_curriculum.curriculum261_api import qualification_r2_lock_marker
    copy_root = tmp_path / "r2copy"
    shutil.copytree(qualification_r2_lock_marker().parent, copy_root)
    shutil.copyfile(
        Path(v1["qualification_dir"]) / "qualification_plan.json",
        copy_root / "qualification_plan.json")
    with pytest.raises(Exception):
        load_locked_plan(copy_root)


def test_g01_bank_generation_requires_validated_snapshot(v1, tmp_path):
    """未验证输入在真实生成前拒绝(零 generator 调用)。"""
    from rl_curriculum.ppo262_eng_profile import (
        QuotaLedger, generate_eng_bank,
    )
    ledger = QuotaLedger(tmp_path / "ledger.jsonl")
    with pytest.raises(QualifiedInputError):
        generate_eng_bank(object(), ledger)
    assert ledger.records() == []  # 零事件 = 零生成


# ---------------------------------------------------------------- N01
def test_n01_isolation_covers_engineering_namespace():
    from rl_curriculum.ppo262_namespaces import (
        all_262_namespaces, verify_namespace_isolation,
    )
    art = verify_namespace_isolation(
        pair_range_262=range(0, 60), pair_range_261=range(0, 60))
    assert art["pass"], art["problems"]
    assert "ppo_eng_bank_262e" in art["namespaces_262"]
    assert "ppo_eng_bank_262e" in all_262_namespaces()


def test_n01_fit_label_namespace_disjoint():
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_SEED_NAMESPACES,
    )
    from rl_curriculum.ppo262_eng_fixture import ENG_FIT_NAMESPACE
    from rl_curriculum.ppo262_namespaces import all_262_namespaces
    assert ENG_FIT_NAMESPACE not in all_262_namespaces()
    assert ENG_FIT_NAMESPACE not in CURRICULUM261_SEED_NAMESPACES


def test_n01_planted_same_seed_not_possible():
    """故意植入同 seed 的探测:eng namespace 派生与全部 261/262
    namespace 在枚举范围内无重合(隔离面由实际派生整数保证)。"""
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_SEED_NAMESPACES,
    )
    from rl_curriculum.ppo262_namespaces import _derive262_seed_raw
    eng_seeds = {
        _derive262_seed_raw("ppo_eng_bank_262e", f, r, p, a)
        for f in ("c1_opportunity", "c2_context", "c3_cost")
        for r in ("D0", "D1", "D2", "D3")
        for p in range(50) for a in range(5)}
    old_seeds = set()
    for ns in ("ppo_smoke_262", "ppo_config_dev_262", "ppo_dev_eval_262"):
        old_seeds |= {
            _derive262_seed_raw(ns, f, r, p, a)
            for f in ("c1_opportunity", "c2_context", "c3_cost")
            for r in ("D0", "D1", "D2", "D3")
            for p in range(50) for a in range(5)}
    assert not (eng_seeds & old_seeds)
    assert len(CURRICULUM261_SEED_NAMESPACES) > 0  # 261 枚举面存在

def test_m02_route_profile_inputs(v2, tmp_path):
    """B1 修复后:CLI 驱动真实 prepare 管线 + 消费边界哨兵。"""
    from rl_curriculum.ppo262_cli import main
    rc = main(["eng-route-check",
               "--qual-dir", v2["qualification_dir"],
               "--auth", v2["authorization_path"],
               "--out-dir", str(tmp_path)])
    assert rc == 0
    art = json.loads(
        (tmp_path / "eng_route_check.json").read_text(encoding="utf-8"))
    assert set(art["entry_classes"]) == {
        "smoke", "config_dev", "probe", "core", "dev_eval", "final"}
    qi = _load(v2)
    for cls in art["entry_classes"]:
        route = art["routes"][cls]
        assert route["rung_params_source"].startswith(
            "qualified_input.pack")
        assert route["namespace"] == "ppo_eng_bank_262e"
        assert route["consumer_boundary_hits"]["generate262_bank"] >= 1
    assert art["default_context_official_r2"] is True
    assert art["cached_pack_tamper_rejected"] is True
    assert art["pass"] is True
    assert art["pack_differs_from_r2"] is True


def test_m01_checkpoint_binding_manifest_fields(v1):
    """manifest 绑定字段完整性(真实 checkpoint 的冷读拒另测于 env_bank 文件)。"""
    from rl_curriculum.ppo262_eng_profile import _consumer_code_identity
    ids = _load(v1).identities()
    for key in ("qualification_plan_digest", "parameter_pack_digest",
                "preprocessor_bundle_hash", "profile",
                "qualification_scope", "qualification_source_iteration"):
        assert ids.get(key)
    assert set(_consumer_code_identity()) >= {
        "ppo262_qualified_input.py", "ppo262_env.py", "ppo262_banks.py"}
