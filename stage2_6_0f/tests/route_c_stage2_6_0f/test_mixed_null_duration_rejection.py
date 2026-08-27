"""工作包 C5:mixed-duration 攻击矩阵(12 场景)。

所有拒绝均为 EXAM_INVALID(考试材料无效),不是候选 FAIL 或疑似
作弊;全部拒绝发生在候选 checkpoint 加载之前。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tests.route_c_stage2_6_0f.conftest import FAMILIES


def _derive(pack):
    from rl_curriculum.null_duration_contract import (
        NullDurationContractError,
        derive_global_null_duration_contract,
    )

    return derive_global_null_duration_contract(
        pack, required_families=list(FAMILIES))


def _pack_with_bars(bars_by_family=None, bars_by_seed=None):
    """构造自定义 null pack(episode_bars 按族/按 seed 覆写)。"""
    from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
    from rl_curriculum.mock_sealed_exam import assemble_mock_hidden_pack

    base = assemble_mock_hidden_pack()
    eps = []
    for e in base.episodes:
        if e.split != "null_control":
            eps.append(e)
            continue
        params = dict(e.params)
        if bars_by_family and e.family in bars_by_family:
            params["episode_bars"] = bars_by_family[e.family]
        if bars_by_seed and int(e.seed) in bars_by_seed:
            params["episode_bars"] = bars_by_seed[int(e.seed)]
        eps.append(EpisodeSpec(
            e.family, params, e.seed, e.split, timeframe=e.timeframe))
    return ExamPack(
        name=base.name, version=base.version, visibility=base.visibility,
        charter_hash=base.charter_hash, spec_versions=base.spec_versions,
        episodes=eps, timeframe=base.timeframe)


def test_s1_all_families_96_passes(mock_pack):
    """场景 1:三族全部 96 bars -> 唯一合同 PASS。"""
    c = _derive(mock_pack)
    assert c["resolved_bars"] == 96


def test_s2_cross_family_mixed_rejected():
    """场景 2:sign 96 / volstate 192 / stochvol 48 -> EXAM_INVALID。"""
    from rl_curriculum.null_duration_contract import (
        NullDurationContractError,
    )

    pack = _pack_with_bars(bars_by_family={
        "probe_null_volstate": 192, "probe_null_stochvol": 48})
    with pytest.raises(NullDurationContractError,
                       match="不唯一|resolved duration"):
        _derive(pack)


def test_s3_partial_pairs_in_family_rejected():
    """场景 3:同一 family 中部分 pair 96、部分 192 -> EXAM_INVALID。"""
    from rl_curriculum.null_duration_contract import (
        NullDurationContractError,
    )

    base = _pack_with_bars()
    seeds_192 = sorted({
        int(e.seed) for e in base.episodes
        if e.split == "null_control" and e.family == "probe_null_sign"
    })[:16]  # 一半 cluster 改 192
    pack = _pack_with_bars(bars_by_seed={s: 192 for s in seeds_192})
    with pytest.raises(NullDurationContractError, match="不唯一"):
        _derive(pack)


def test_s4_pairs_consistent_but_across_pairs_differ_rejected():
    """场景 4:每个 pair 内部一致,但不同 pair 不一致 -> EXAM_INVALID。"""
    from rl_curriculum.null_duration_contract import (
        NullDurationContractError,
    )

    # 同一 seed 的 orig+flip 都改 192(pair 内一致),另一 seed 保持 96
    base = _pack_with_bars()
    sign_seeds = sorted({
        int(e.seed) for e in base.episodes
        if e.split == "null_control" and e.family == "probe_null_sign"})
    pack = _pack_with_bars(bars_by_seed={
        sign_seeds[0]: 192, sign_seeds[1]: 192})  # 完整 pair(cluster)
    with pytest.raises(NullDurationContractError, match="不唯一"):
        _derive(pack)


def test_s5_equivalent_raw_declarations_allowed():
    """场景 5:raw 参数不同但 resolved duration 完全相同 -> 允许。"""
    from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
    from rl_curriculum.mock_sealed_exam import assemble_mock_hidden_pack

    base = assemble_mock_hidden_pack()
    eps = []
    half = False
    for e in base.episodes:
        if e.split != "null_control":
            eps.append(e)
            continue
        params = dict(e.params)
        # 前一半族用 episode_bars,后一半族用 duration_hours(15m 下
        # 24h == 96 bars,resolved 相同)
        if e.family in ("probe_null_volstate", "probe_null_stochvol"):
            params.pop("episode_bars", None)
            params["duration_hours"] = 24.0
        eps.append(EpisodeSpec(
            e.family, params, e.seed, e.split, timeframe=e.timeframe))
    pack = ExamPack(
        name=base.name, version=base.version, visibility=base.visibility,
        charter_hash=base.charter_hash, spec_versions=base.spec_versions,
        episodes=eps, timeframe=base.timeframe)
    c = _derive(pack)
    assert c["resolved_bars"] == 96  # duration_hours=24 -> ceil(24*4)=96


def test_s6_pack_vs_family_report_duration_mismatch_rejected(
        sealed_exam_env, mock_identity):
    """场景 6:pack 合同与 family report 时长不同 -> 拒绝(spec hash
    对账失败;96 材料 + 192 pack)。"""
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
        verify_sealed_commitment,
    )

    env = sealed_exam_env
    # pack 全族改为 192 -> 合同 192;但承诺 nqs/family 报告来自 96 材料
    pack192 = _pack_with_bars(bars_by_family={
        "probe_null_sign": 192, "probe_null_volstate": 192,
        "probe_null_stochvol": 192})
    contract192 = _derive(pack192)
    with pytest.raises(SealedExamError, match="spec|规范|duration"):
        verify_sealed_commitment(
            env["commitment"], pack=pack192, charter=env["charter"],
            schema=env["schema"], registry=env["registry"],
            eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
            sandbox_profile=env["profile"], builder_identity=mock_identity,
            duration_contract=contract192)


def test_s7_pack_vs_power_spec_duration_mismatch_rejected(
        sealed_exam_env, mock_identity, duration_contract):
    """场景 7:pack 合同与 power spec 不同 -> 拒绝(power 重跑用合同
    bars 重建 spec,hash 与承诺不一致)。"""
    from rl_curriculum.sealed_exam import (
        SealedExamError,
        verify_sealed_commitment,
    )

    env = sealed_exam_env
    # 执行器侧喂入与 pack(96)不一致的 192 合同 -> spec/power 对账失败
    contract192 = dict(duration_contract)
    contract192["resolved_bars"] = 192
    contract192["resolved_duration_seconds"] = 192 * 900
    contract192["resolved_duration_hours"] = 192 * 900 / 3600.0
    from rl_curriculum.null_duration_contract import (
        null_duration_contract_hash,
    )

    with pytest.raises(SealedExamError):
        verify_sealed_commitment(
            env["commitment"], pack=env["pack"], charter=env["charter"],
            schema=env["schema"], registry=env["registry"],
            eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
            sandbox_profile=env["profile"], builder_identity=mock_identity,
            duration_contract=contract192)


def test_s8_pack_vs_pack_validity_report_duration_mismatch_rejected(
        sealed_exam_env, mock_identity, duration_contract, cfg, schema,
        mock_pack_materialized):
    """场景 8:pack 合同与 pack validity report 不同 -> 拒绝(npv-
    hash 对账:报告用 192 合同生成,承诺绑定 96 报告)。"""
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        pack_validity_report_hash,
        validate_null_pack,
    )
    from rl_curriculum.sealed_exam import SealedExamError

    env = sealed_exam_env
    contract192 = dict(duration_contract)
    contract192["resolved_bars"] = 192
    contract192["resolved_duration_seconds"] = 192 * 900
    contract192["resolved_duration_hours"] = 192 * 900 / 3600.0
    spec192 = build_spec_for_pack(
        cfg, timeframe="15m", episode_bars=192)
    pv192 = validate_null_pack(
        mock_pack_materialized, cfg=cfg, schema=schema, spec=spec192,
        pack_hash=env["pack"].pack_hash(),
        builder_identity=mock_identity, duration_contract=contract192)
    assert pack_validity_report_hash(pv192) != (
        env["commitment"].pack_validity["report_hash"])
    # run 层:4b 步现算 npv- 与承诺对账失败 -> EXAM_INVALID(在
    # run_sealed_exam 中由 npv hash 比对拒绝;此处直接断言哈希不等)


def test_s9_missing_duration_rejected():
    """场景 9:缺 duration 字段且无法解析 -> 拒绝。"""
    from rl_curriculum.null_duration_contract import (
        NullDurationContractError,
    )

    pack = _pack_with_bars()
    for e in pack.episodes:
        if e.split == "null_control":
            e.params.pop("episode_bars", None)
    with pytest.raises(NullDurationContractError, match="无法解析"):
        _derive(pack)


def test_s10_episode_order_irrelevant(mock_pack, duration_contract):
    """场景 10:修改 Episode 顺序不能改变推导结果。"""
    import random

    shuffled = copy.deepcopy(mock_pack)
    random.Random(20260827).shuffle(shuffled.episodes)
    assert _derive(shuffled) == duration_contract


def test_s11_first96_last96_middle192_bypass_fails():
    """场景 11:'首个为 96、最后为 96、中间为 192'的绕过必须失败
    (旧 first/last 语义会漏过;全局收集捕获)。"""
    from rl_curriculum.null_duration_contract import (
        NullDurationContractError,
    )

    pack = _pack_with_bars()
    null_eps = [e for e in pack.episodes if e.split == "null_control"]
    # 首条与末条保持 96,中间全部改 192
    middle = null_eps[1:-1]
    for e in middle:
        e.params["episode_bars"] = 192
    with pytest.raises(NullDurationContractError, match="不唯一"):
        _derive(pack)
    # 反向:首末 192,中间 96 同样失败
    pack2 = _pack_with_bars()
    null2 = [e for e in pack2.episodes if e.split == "null_control"]
    for e in null2[1:-1]:
        e.params["episode_bars"] = 192
    null2[0].params["episode_bars"] = 96
    null2[-1].params["episode_bars"] = 96
    with pytest.raises(NullDurationContractError, match="不唯一"):
        _derive(pack2)


def test_s12_rejection_before_checkpoint_load(sealed_exam_env,
                                              monkeypatch, tmp_path):
    """场景 12:所有 duration 拒绝发生在候选 checkpoint 加载前
    (沙箱启动器从未被调用)。"""
    import rl_curriculum.formal_exam as fe

    env = sealed_exam_env
    # 构造混合 pack:写盘后直接 run(mixed -> 步骤 3 合同派生失败)
    pack = _pack_with_bars(bars_by_family={"probe_null_volstate": 192})
    d = tmp_path / "s12"
    d.mkdir()
    pack.save(d / "pack.json")
    env["commitment"].save(d / "commitment.json")
    called = {"sandbox": False}
    orig = fe._load_sandboxed_candidate

    def spy(*a, **kw):
        called["sandbox"] = True
        return orig(*a, **kw)

    monkeypatch.setattr(fe, "_load_sandboxed_candidate", spy)
    out, rc = fe.run_sealed_exam(
        sealed_manifest_path=str(d / "commitment.json"),
        pack_path=str(d / "pack.json"),
        checkpoint_path=str(d / "whatever.zip"),
        out_path=str(d / "out.json"),
        retire_registry_path=str(d / "ret.json"),
        attempt_registry_path=str(d / "att.json"),
        charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"],
        builder_provider=__import__(
            "rl_curriculum.builder_identity", fromlist=[
                "MockBuilderIdentityProvider"]
        ).MockBuilderIdentityProvider())
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
    assert called["sandbox"] is False, (
        "混合时长拒绝必须发生在候选沙箱启动/checkpoint 加载之前")
