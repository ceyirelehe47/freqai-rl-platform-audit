"""工作包 C1-C4:全局 strict Null duration contract。

- 从全部 required strict Null family 的 null_control Episode 派生唯一
  规范化合同(timeframe/bar seconds/resolved bars/resolved duration);
- resolved 值比较(非原始参数文本):episode_bars=96 与
  duration_hours=24@15m 解析为同一合同,允许;
- 不存在取第一个/最后一个 Episode 或 96 默认回退;
- commitment v6 绑定 ndc-(payload + hash);qualification spec /
  family reports / power / pack validity 全链路对账。
"""

from __future__ import annotations

import copy
import json

import pytest

from tests.route_c_stage2_6_0f.conftest import FAMILIES


def _derive(pack):
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    return derive_global_null_duration_contract(
        pack, required_families=list(FAMILIES))


def test_unique_resolved_contract_from_all_episodes(mock_pack,
                                                    duration_contract):
    """唯一合同:覆盖全部 192 条 null Episode(3 族 x 64)。"""
    c = duration_contract
    assert c["format"] == "null-duration-contract-v1"
    assert c["timeframe"] == "15m"
    assert c["bar_duration_seconds"] == 900
    assert c["resolved_bars"] == 96
    assert c["resolved_duration_seconds"] == 96 * 900
    assert c["resolved_duration_hours"] == pytest.approx(24.0)
    assert c["n_null_episodes"] == 192
    assert c["episodes_per_family"] == {
        "probe_null_sign": 64, "probe_null_volstate": 64,
        "probe_null_stochvol": 64}
    assert c["resolution_rules_version"].startswith("rps-")


def test_episode_order_does_not_change_derivation(mock_pack,
                                                  duration_contract):
    """C5-10:修改 Episode 顺序 -> 推导结果不变。"""
    shuffled = copy.deepcopy(mock_pack)
    shuffled.episodes = list(reversed(shuffled.episodes))
    assert _derive(shuffled) == duration_contract


def test_equivalent_raw_declarations_same_contract():
    """C5-5:episode_bars=96 与 duration_hours=24 在 15m 下解析为完全
    相同的合同(比较 resolved 值)。"""
    from rl_curriculum.exam_pack import ExamPack
    from rl_curriculum.generator_api import EpisodeSpec
    from rl_curriculum.mock_sealed_exam import assemble_mock_hidden_pack

    base = assemble_mock_hidden_pack()
    eps_bars = [
        EpisodeSpec(e.family, {"episode_bars": 96,
                               **{k: v for k, v in e.params.items()
                                  if k not in ("episode_bars",
                                               "antithetic_flip")}},
                    e.seed, e.split, timeframe=e.timeframe)
        if e.split == "null_control" else e
        for e in base.episodes]
    eps_hours = [
        EpisodeSpec(e.family, {"duration_hours": 24.0,
                               **{k: v for k, v in e.params.items()
                                  if k not in ("episode_bars",
                                               "antithetic_flip")}},
                    e.seed, e.split, timeframe=e.timeframe)
        if e.split == "null_control" else e
        for e in base.episodes]
    pack_bars = ExamPack(
        name=base.name, version=base.version, visibility=base.visibility,
        charter_hash=base.charter_hash, spec_versions=base.spec_versions,
        episodes=eps_bars, timeframe=base.timeframe)
    pack_hours = ExamPack(
        name=base.name, version=base.version, visibility=base.visibility,
        charter_hash=base.charter_hash, spec_versions=base.spec_versions,
        episodes=eps_hours, timeframe=base.timeframe)
    c_bars = _derive(pack_bars)
    c_hours = _derive(pack_hours)
    # resolved 合同完全相同(原始声明通道不同被允许)
    keys = ("timeframe", "bar_duration_seconds", "resolved_bars",
            "resolved_duration_seconds", "resolved_duration_hours")
    for k in keys:
        assert c_bars[k] == c_hours[k]


def test_contradictory_raw_declarations_fail_closed():
    """原始 duration 与 bars 自相矛盾 -> 参数解析器 fail closed。"""
    from rl_curriculum.param_resolution import (
        ParamResolutionError,
        resolve_duration,
    )

    with pytest.raises(ParamResolutionError, match="不一致"):
        resolve_duration(
            {"episode_bars": 48, "duration_hours": 24.0}, "15m")


def test_missing_duration_fields_rejected(mock_pack):
    """C5-9:Null Episode 缺 episode_bars 且缺 duration_hours -> 合同
    派生失败(不得使用默认值)。"""
    from rl_curriculum.null_duration_contract import (
        NullDurationContractError,
    )

    stripped = copy.deepcopy(mock_pack)
    for ep in stripped.episodes:
        if ep.split == "null_control":
            ep.params.pop("episode_bars", None)
            ep.params.pop("duration_hours", None)
    with pytest.raises(NullDurationContractError,
                       match="无法解析|duration"):
        _derive(stripped)


def test_no_first_or_last_episode_semantics_remains():
    """正式路径源码不再存在 first/last Episode 推导与 96 回退。"""
    import inspect

    import rl_curriculum.formal_exam as fe
    import rl_curriculum.mock_sealed_exam as mse
    import rl_curriculum.sealed_exam as se

    for mod in (fe, mse, se):
        src = inspect.getsource(mod)
        assert '.get("episode_bars", 96)' not in src, mod.__name__
        assert ".get('episode_bars', 96)" not in src, mod.__name__
    # verify/spec 构建一律来自 duration_contract["resolved_bars"]
    vsrc = inspect.getsource(se)
    assert 'duration_contract["resolved_bars"]' in vsrc
    assert 'duration_contract["timeframe"]' in vsrc


def test_commitment_binds_contract_payload_and_hash(sealed_exam_env,
                                                    duration_contract):
    """C4:承诺绑定合同 payload(ndc- hash + 公开 duration/timeframe)。"""
    from rl_curriculum.null_duration_contract import (
        null_duration_contract_hash,
    )

    env = sealed_exam_env
    assert env["commitment"].null_duration_contract == duration_contract
    assert env["commitment"].null_duration_contract_hash == (
        null_duration_contract_hash(duration_contract))
    assert env["commitment"].null_duration_contract_hash.startswith("ndc-")


def test_spec_family_power_pack_cross_binding(sealed_exam_env, cfg,
                                              duration_contract,
                                              pack_validity_report):
    """全链路对账:qualification spec / family reports / power /
    pack validity 与同一 duration 合同一致(C2)。"""
    from rl_curriculum.null_duration_contract import (
        null_duration_contract_hash,
    )
    from rl_curriculum.null_qualification_spec import (
        build_spec_payload,
        null_qualification_spec_hash,
    )

    env = sealed_exam_env
    # 1) spec 用合同 bars 构建 -> 与承诺 nqs 一致
    spec = build_spec_payload(
        cfg, timeframe=duration_contract["timeframe"],
        episode_bars=int(duration_contract["resolved_bars"]))
    assert null_qualification_spec_hash(spec) == (
        env["commitment"].null_qualification_spec_hash)
    # spec 的时长字段与合同一致
    assert spec["timeframe"] == duration_contract["timeframe"]
    assert spec["episode_duration_hours"] == pytest.approx(
        duration_contract["resolved_duration_hours"])
    # 2) family reports 的时长与合同一致(逐族)
    for fam, rep in env["null_qual_reports"].items():
        assert rep["timeframe"] == duration_contract["timeframe"]
        assert rep["episode_duration_hours"] == pytest.approx(
            duration_contract["resolved_duration_hours"])
    # 3) pack validity 报告绑定同一合同 hash
    assert pack_validity_report["duration_contract_hash"] == (
        null_duration_contract_hash(duration_contract))
    assert pack_validity_report["duration_contract"] == duration_contract


def test_verify_cross_binding(sealed_exam_env, mock_identity,
                              duration_contract):
    """verify 路径:合同对账通过;篡改承诺合同 -> 拒绝。"""
    from rl_curriculum.sealed_exam import (
        SealedExamError,
        verify_sealed_commitment,
    )

    env = sealed_exam_env
    report = verify_sealed_commitment(
        env["commitment"], pack=env["pack"], charter=env["charter"],
        schema=env["schema"], registry=env["registry"],
        eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
        sandbox_profile=env["profile"], builder_identity=mock_identity,
        duration_contract=duration_contract)
    assert report["checks"]["null_duration_contract_hash"] is True

    # 篡改:承诺的 ndc- 与 pack 实际合同不一致
    bad = copy.deepcopy(json.loads(env["commitment"].to_json()))
    bad["null_duration_contract"]["resolved_bars"] = 48
    from rl_curriculum.null_duration_contract import (
        null_duration_contract_hash as _ndc_hash2,
    )
    from rl_curriculum.sealed_exam import SealedExamCommitment

    # payload 被改 -> from_json 哈希自洽校验拒绝(或 verify 对账拒绝)
    with pytest.raises(Exception,
                       match="哈希不一致|duration contract"):
        c = SealedExamCommitment.from_json(json.dumps(bad))
        verify_sealed_commitment(
            c, pack=env["pack"], charter=env["charter"],
            schema=env["schema"], registry=env["registry"],
            eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
            sandbox_profile=env["profile"], builder_identity=mock_identity,
            duration_contract=duration_contract)
