# -*- coding: utf-8 -*-
"""QProd 导出适配器 + 消费合同测试(X01/X02/X03/X04 + v2 来源表示)。

零原生生成/零 fit/零 optimizer:producer 原件由 Level A 工程排练
(标注夹具输入)真实产生;导出器验证原件;消费走当前
load_qualified_input/EntrySpec 共享准备/冻结 V2 wrapper(bank=标注
夹具替身)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_qprod_context import (
    QProdContextError, QProdRunSession, build_engineering_context,
)
from rl_curriculum.curriculum261_qprod_levela import (
    build_engineering_cue_report_fixture,
    build_engineering_topology_fixture, run_level_a_rehearsal,
)
from rl_curriculum.ppo262_qualified_input import (
    QualifiedInputError, authorization_binding_digest,
    load_qualified_input, qualification_plan_digest,
)
import rl_curriculum.ppo262_qprod_export as export_mod
from rl_curriculum.ppo262_qprod_export import (
    QProdExportError, build_engineering_authorization,
    export_qualification_delivery,
)

PROFILE = "ppo262_qprod_engineering_v1"


def _producer(tmp_path: Path, *, variant="v1_r2_reference",
              robustness_pass=True):
    from rl_curriculum.ppo262_eng_fixture import (
        _engineering_pack, build_frozen_v2_preprocessor,
    )
    adir = tmp_path / "authority"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "authority_identity.json").write_text(json.dumps(
        {"authority_id": "t"}), encoding="utf-8")
    ctx = build_engineering_context(
        level="level_a", iteration_id="e2e",
        base_dir=tmp_path / "base", code_freeze_sha="sha",
        authority_dir=adir)
    session = QProdRunSession(ctx.state_root, level="level_a",
                              iteration_id=ctx.iteration_id)
    session.acquire({"entry": "export-test"})
    pack = _engineering_pack(variant)
    preproc, _records = build_frozen_v2_preprocessor()
    envelope_path = tmp_path / "env.json"
    preproc.serialize_envelope(envelope_path)
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    out = run_level_a_rehearsal(ctx, session, {
        "gate_topology": build_engineering_topology_fixture(),
        "cue_audit_report": build_engineering_cue_report_fixture(),
        "preplan_smoke": {"pass": True},
        "design_plan": {"grid": "f"},
        "parameter_pack": pack,
        "calibration_artifacts": {
            "preprocessor_bundle_calibration.json": {
                "preprocessor_bundle_hash":
                    envelope["hashes"]["preprocessor_bundle_hash"]},
            "preprocessor_bundle_holdout.json": {
                "preprocessor_bundle_hash":
                    envelope["hashes"]["preprocessor_bundle_hash"]}},
        "robustness_gate": {"pass": robustness_pass},
        "c2_marginal": {"metrics": {
            "non_cue_false_positive_max": 0.001}},
        "c2_marginal_thresholds": {
            "non_cue_false_positive_max": 0.01},
        "v2_envelope_path": envelope_path,
    })
    return ctx, out


def _exported(tmp_path: Path, **kw):
    ctx, out = _producer(tmp_path, **kw)
    delivery = tmp_path / "delivery"
    receipt = export_qualification_delivery(
        ctx.artifact_root, ctx.state_root, delivery,
        expected_scope="engineering")
    auth = build_engineering_authorization(
        receipt, profile=PROFILE,
        authority_note="isolated engineering test authority(test)")
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps(auth, indent=2, sort_keys=True),
                         encoding="utf-8")
    return ctx, out, delivery, receipt, auth_path


# ---------------------------------------------------------------- X01
def test_x01_producer_to_qualified_input_real_path(tmp_path):
    ctx, out, delivery, receipt, auth_path = _exported(tmp_path)
    assert out["verdict"] == "PASS"
    # 六件套齐备且逐件可校验
    for name in ("qualification_plan.json",
                 "qualification_plan_digest.txt",
                 "qualification_result.json",
                 "qualification_exposure.json", "parameter_pack.json",
                 "preprocessor_envelope.json"):
        assert (delivery / name).is_file(), name
    qi = load_qualified_input(
        delivery, authorization_path=auth_path,
        expected_scope="engineering", expected_profile=PROFILE)
    assert qi.scope == "engineering"
    plan = json.loads(
        (delivery / "qualification_plan.json").read_text(
            encoding="utf-8"))
    # v2 来源表示:真实资格来源不改称手工夹具
    assert plan["preprocessing"]["version"] == 2
    assert plan["preprocessing"]["source_kind"] == "qualification_chain"
    assert "fit_fixture_records" not in plan["preprocessing"]
    # 无手工补 JSON:digests 全部重算一致
    assert qualification_plan_digest(plan) == (
        delivery / "qualification_plan_digest.txt").read_text().strip()


# ---------------------------------------------------------------- X02
def _mutate_and_reexport(tmp_path, mutator):
    ctx, out = _producer(tmp_path)
    delivery = tmp_path / "delivery"
    mutator(ctx)
    with pytest.raises(QProdExportError):
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, delivery,
            expected_scope="engineering")
    assert not (delivery / "qualification_result.json").is_file(), (
        "拒绝时不得产可用成功包")


def test_x02_pass_string_only_result_rejected(tmp_path):
    """只写 PASS 字符串(判定核心复算不符)拒绝。"""

    def mutator(ctx):
        # result 仍写 PASS,但 gate 表与 raw 证据矛盾(判定核心复算
        # 出 exposure gate = True;伪造为 False ⇒ gates 不一致拒绝)
        p = ctx.artifact_root / "qprod_qualification_result.json"
        r = json.loads(p.read_text(encoding="utf-8"))
        r["gates"]["exposure_one_shot_completed"] = False
        p.write_text(json.dumps(r), encoding="utf-8")

    _mutate_and_reexport(tmp_path, mutator)


def test_x02_failed_qualification_not_exported(tmp_path):
    with pytest.raises(QProdExportError):
        ctx, out = _producer(tmp_path, robustness_pass=False)
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, tmp_path / "d",
            expected_scope="engineering")
    assert out["verdict"] == "FAIL"


def test_x02_missing_originals_rejected(tmp_path):
    def mutator(ctx):
        (ctx.artifact_root / "qprod_qualification_raw.json").unlink()

    _mutate_and_reexport(tmp_path, mutator)


def test_x02_exposure_not_completed_rejected(tmp_path):
    def mutator(ctx):
        p = ctx.artifact_root / "qprod_qualification_exposure.json"
        e = json.loads(p.read_text(encoding="utf-8"))
        e["status"] = "running"
        p.write_text(json.dumps(e), encoding="utf-8")

    _mutate_and_reexport(tmp_path, mutator)


def test_x02_old_r2_format_rejected(tmp_path):
    """旧 R2 输入冒充 QProd producer 原件拒绝。"""

    def mutator(ctx):
        p = ctx.artifact_root / "qprod_qualification_result.json"
        r = json.loads(p.read_text(encoding="utf-8"))
        r["format"] = "ppo262e-qualification-result-v1"
        p.write_text(json.dumps(r), encoding="utf-8")

    _mutate_and_reexport(tmp_path, mutator)


def test_x02_formal_scope_export_refused(tmp_path):
    ctx, out = _producer(tmp_path)
    with pytest.raises(QProdExportError, match="无真实正式资格链"):
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, tmp_path / "d",
            expected_scope="formal")


# ---------------------------------------------------------------- X03
def test_x03_pack_source_swap_rejected(tmp_path):
    """换 pack(摘要自洽重绑)仍拒:判定核心/计划绑定与原件矛盾。"""

    def mutator(ctx):
        from rl_curriculum.ppo262_eng_fixture import _engineering_pack

        p = ctx.artifact_root / "parameter_pack.json"
        p.write_text(json.dumps(
            _engineering_pack("v2_perturbed")), encoding="utf-8")

    _mutate_and_reexport(tmp_path, mutator)


def test_x03_fit_source_swap_rejected(tmp_path):
    """V2 entries 换来源(与计划声明不逐项对应)拒。"""

    def mutator(ctx):
        p = Path(ctx.state_root) / "qprod_qualification_plan.json"
        qp = json.loads(p.read_text(encoding="utf-8"))
        qp["preprocessing"]["fit_records"][0]["episode_hash"] = (
            "e262fx-INVENTED")
        from rl_curriculum.curriculum261_qprod_plan import (
            qualification_plan_digest,
        )
        qp["qualification_plan_digest"] = qualification_plan_digest(qp)
        p.write_text(json.dumps(qp), encoding="utf-8")
        (Path(ctx.state_root) /
         "qprod_qualification_plan_digest.txt").write_text(
            qp["qualification_plan_digest"], encoding="utf-8")

    _mutate_and_reexport(tmp_path, mutator)


# ---------------------------------------------------------------- X04
def test_x04_two_preset_inputs_shared_prep_boundary(tmp_path):
    """两套预定参数/来源正例进入共享消费准备;变更在真实参数边界可见。

    bank=标注夹具替身(零生成);reset/step 真实;工程件改 formal
    仍零更新拒绝。
    """
    import numpy as np

    from rl_curriculum.curriculum261_production_obs import (
        attach_production_features,
    )
    from rl_curriculum.generator_api import (
        EpisodeSpec, GeneratedEpisode,
    )
    from rl_curriculum.ppo262_banks import EpisodeKey, LoadedEpisode
    from rl_curriculum.ppo262_eng_fixture import synthetic_ohlcv
    from rl_curriculum.ppo262_entry_specs import (
        PROFILE_BANK_NAMESPACE, prepare_smoke_inputs,
    )
    from rl_curriculum.curriculum261_api import episode_content_hash

    probe = {}
    for variant in ("v1_r2_reference", "v2_perturbed"):
        ctx, out, delivery, receipt, auth = _exported(
            tmp_path / variant, variant=variant)
        with pytest.raises(QualifiedInputError):
            load_qualified_input(
                delivery, authorization_path=auth,
                expected_scope="formal")  # 工程授权不解锁正式入口
        from rl_curriculum.ppo262_qualified_input import (
            activated_profile_input,
        )

        qi = load_qualified_input(
            delivery, authorization_path=auth,
            expected_scope="engineering", expected_profile=PROFILE)
        with activated_profile_input(qi):
            spec = prepare_smoke_inputs()
            spec.assert_from_profile(qi)
            probe[variant] = {
                "pack_digest": qi.pack_digest,
                "bundle_hash": qi.bundle_hash,
                "namespace": spec.namespace,
                "d1_c1": spec.rung_params["c1_opportunity"]["D1"],
            }

            def _fixture_episode(k):
                df = attach_production_features(synthetic_ohlcv({
                    "start": 100.0 * (1 + 0.2 * k),
                    "drift": 0.0002 * (k + 1), "amp": 0.003,
                    "period": 24.0, "phase": 0.7, "wick": 0.0015,
                    "bars": 288}))
                return GeneratedEpisode(
                    spec=EpisodeSpec(
                        family="eng_synthetic",
                        params={"fixture_k": k, "bank_double": True},
                        seed=9000 + k, split="train", timeframe="15m"),
                    df=df, hidden=df.iloc[:0].copy(),
                    family_version="qprod-bank-fixture-v1",
                    timeframe="15m", is_null=False,
                    generator_fingerprint="qprod-bank-double-v1")

            bank = [
                LoadedEpisode(
                    key=EpisodeKey(
                        PROFILE_BANK_NAMESPACE, "c1_opportunity", "D0",
                        k, "A"),
                    episode=_fixture_episode(k),
                    content_hash=episode_content_hash(
                        _fixture_episode(k)))
                for k in range(2)]
            from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv

            env = CurriculumMultiEpisodeEnv(
                bank, preprocessor=qi.preprocessor)
            obs, _ = env.reset(seed=20260930)
            for _ in range(2):
                obs, *_ = env.step(1)
            assert obs is not None
    # 两套预定输入在真实参数/身份边界可区分
    assert (probe["v1_r2_reference"]["pack_digest"]
            != probe["v2_perturbed"]["pack_digest"])
    assert (probe["v1_r2_reference"]["d1_c1"]
            != probe["v2_perturbed"]["d1_c1"])
    # V2 envelope fit 样例来源一致(同一冻结 producer fit 样例)
    assert (probe["v1_r2_reference"]["bundle_hash"]
            == probe["v2_perturbed"]["bundle_hash"])


# ---------------------------------------------------- v1/v2 兼容
def test_v1_preprocessing_inputs_unchanged(tmp_path):
    """旧工程输入(v1 fit_fixture_records)装载行为不变。"""
    from rl_curriculum.ppo262_eng_fixture import build_eng_fixture

    out = build_eng_fixture(str(tmp_path), variant="v1_r2_reference",
                            verbose=False)
    qi = load_qualified_input(
        out["qualification_dir"],
        authorization_path=out["authorization_path"],
        expected_scope="engineering")
    plan = json.loads((Path(out["qualification_dir"]) /
                       "qualification_plan.json").read_text(
        encoding="utf-8"))
    assert "fit_fixture_records" in plan["preprocessing"]
    assert plan["preprocessing"].get("version", 1) == 1


def test_unknown_preprocessing_version_rejected(tmp_path):
    ctx, out, delivery, receipt, auth_path = _exported(tmp_path)
    plan_path = delivery / "qualification_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["preprocessing"]["version"] = 3
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True),
                         encoding="utf-8")
    d = qualification_plan_digest(plan)
    (delivery / "qualification_plan_digest.txt").write_text(
        d + "\n", encoding="utf-8")
    for f in ("qualification_result.json",
              "qualification_exposure.json"):
        x = json.loads((delivery / f).read_text(encoding="utf-8"))
        x["plan_digest"] = d
        (delivery / f).write_text(json.dumps(x), encoding="utf-8")
    a = json.loads(auth_path.read_text(encoding="utf-8"))
    a["bindings"]["qualification_plan_digest"] = d
    a["binding_digest"] = authorization_binding_digest({
        **a["bindings"], "profile": a["profile"], "scope": a["scope"]})
    auth_path.write_text(json.dumps(a), encoding="utf-8")
    with pytest.raises(QualifiedInputError, match="不识别"):
        load_qualified_input(
            delivery, authorization_path=auth_path,
            expected_scope="engineering", expected_profile=PROFILE)
