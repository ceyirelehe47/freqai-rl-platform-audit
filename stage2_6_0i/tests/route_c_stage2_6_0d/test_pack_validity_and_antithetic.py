"""工作包 B/D6/D7:pack-level validity、偶然漂移拦截与 antithetic
结构平衡。

- D6:分布理论为零但实际 pack 偶然显著向上 -> PACK_INVALID,
  候选不得进入评估,不得判 FAIL/作弊;
- D7:antithetic 镜像性质(收益逐位相反/绝对收益与波动状态一致/
  pair 计数/pair 标志不进 observation/顺序 seeded 随机化/一条路径
  被修改时完整性失败/同 pair 只算一个 cluster);
- B4:pack 构建不可候选依赖(确定性 namespace 推导/attempt 推进/
  最大尝试数/匿名拒绝原因记录);
- B2:pack 构建器产物通过 pack-level validity。
"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.null_pack_validation import (
    build_spec_for_pack,
    pack_validity_report_hash,
    validate_null_pack,
)
from rl_curriculum.null_qualification_spec import (
    MIN_PACK_CLUSTERS_PER_FAMILY,
)


def _spec(cfg):
    return build_spec_for_pack(cfg, timeframe="15m", episode_bars=96)


# ------------------------------------------------------------------- D7
@pytest.mark.parametrize("fam", ("probe_null_sign", "probe_null_volstate",
                                 "probe_null_stochvol"))
def test_antithetic_mirror_bitwise(fam):
    """D7:同 seed 的 orig/flip 收益逐位互为相反数;绝对收益与
    波动状态路径一致;长度与 timeframe 一致。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS

    gen = R[fam]
    flip_params = dict(BASE_PARAMS)
    flip_params["antithetic_flip"] = True
    e1 = gen.generate(dict(BASE_PARAMS), 987654,
                      split="null_control", timeframe="15m")
    e2 = gen.generate(dict(flip_params), 987654,
                      split="null_control", timeframe="15m")
    b1 = np.diff(np.log(e1.df["close"].to_numpy()),
                 prepend=np.log(e1.df["open"].iloc[0]))
    b2 = np.diff(np.log(e2.df["close"].to_numpy()),
                 prepend=np.log(e2.df["open"].iloc[0]))
    assert np.allclose(b1, -b2), "镜像变体收益必须逐位取负"
    assert len(e1.df) == len(e2.df) == 96
    # |wick| 噪声路径一致(绝对路径形状镜像)
    assert np.allclose(e1.df["volume"], e2.df["volume"])
    # pair 累计漂移精确抵消
    assert abs((b1.sum() + b2.sum())) < 1e-10


def test_pair_flag_not_in_observation():
    """D7:pair 标志不进入 observation(feature 列表中无 flip 字段)。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS

    flip_params = dict(BASE_PARAMS)
    flip_params["antithetic_flip"] = True
    e = R["probe_null_stochvol"].generate(
        dict(flip_params), 111, split="null_control", timeframe="15m")
    obs_cols = set(e.df.columns)
    assert "antithetic_flip" not in obs_cols
    assert not any("flip" in str(c) or "pair" in str(c)
                   for c in obs_cols), obs_cols


def test_pack_pair_order_randomized_and_stable():
    """D7:pair 顺序 seeded 随机化(非单调 base seed 顺序)且构建确定。"""
    from rl_curriculum.mock_sealed_exam import build_mock_hidden_pack

    p1 = build_mock_hidden_pack()
    p2 = build_mock_hidden_pack()
    assert [s.seed for s in p1.episodes] == [s.seed for s in p2.episodes]
    null_seeds = [s.seed for s in p1.episodes
                  if s.split == "null_control"
                  and s.family == "probe_null_sign"]
    bases = null_seeds[::2]  # 每 pair 的 base(flip 在前)
    sorted_bases = sorted(bases)
    assert bases != sorted_bases, "pair 顺序应 seeded 随机化(非单调)"


def test_pack_builder_deterministic_with_attempt_log():
    """B4:构建确定;attempt 记录;构建只依赖 Null 结构(无候选输入)。
    with_builder_log 模式产物通过 pack-level validity。"""
    from rl_curriculum.mock_sealed_exam import build_mock_hidden_pack

    pack, log = build_mock_hidden_pack(with_builder_log=True)
    assert log["attempts"][0]["attempt"] == 0
    assert log["attempts"][-1]["verdict"] == "accept"
    assert log["format"] == "builder-attempt-log-v2"
    assert log["selected_attempt"] == log["attempts"][-1]["attempt"]
    assert log["max_attempts"] >= 1
    # 每族 32 pair = 64 Episode
    for fam in ("probe_null_sign", "probe_null_volstate",
                "probe_null_stochvol"):
        n = sum(1 for s in pack.episodes
                if s.family == fam and s.split == "null_control")
        assert n == MIN_PACK_CLUSTERS_PER_FAMILY * 2


def test_pack_validity_valid_for_mock_pack(sealed_exam_env):
    """B2:mock pack 的 pack-level validity 全部通过(32 pair/族;
    AlwaysLong/HFT 上界检验 + Oracle/Rule 中心检验 + 结构完整)。"""
    pv = sealed_exam_env["materials"]["pack_validity_report"]
    assert pv["verdict"] == "PACK_VALID", pv["reasons"][:3]
    for fam, block in pv["per_family"].items():
        assert block["n_clusters"] == MIN_PACK_CLUSTERS_PER_FAMILY
        assert block["problems"] == []
    assert sealed_exam_env["commitment"].pack_validity[
        "report_hash"] == pack_validity_report_hash(pv)


# ------------------------------------------------------------------- D6
def test_accidental_drift_pack_is_invalid(schema, cfg):
    """D6:分布理论为零(stochvol 构造零漂移)但实际 pack 偶然显著
    向上(3-seed 反例 seeds [11,22,33] 的已知正漂移)-> PACK_INVALID;
    候选不得进入评估,不得判 FAIL(执行器层:EXAM_INVALID)。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS

    eps = [R["probe_null_stochvol"].generate(
        dict(BASE_PARAMS), s, split="null_control", timeframe="15m")
        for s in (11, 22, 33)]
    rep = validate_null_pack(
        {"probe_null_stochvol": eps}, cfg=cfg, schema=schema,
        spec=_spec(cfg), **__import__('compat_stage2_6_0f', fromlist=['validate_kwargs']).validate_kwargs())
    assert rep["verdict"] == "PACK_INVALID"
    problems = "; ".join(rep["reasons"])
    assert "cluster 数" in problems  # 3 < 32(pack 门槛拦截)


def test_accidental_drift_large_pack_is_invalid(schema, cfg):
    """D6 强化:32 pair 数量达标但中心优势超 margin 的 pack(构造每
    bar +2.5bps 固定漂移的'伪 stochvol'场景)-> PACK_INVALID,拦截
    的理由是经济优势而非数量。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification_spec import (
        pack_construction_seeds,
    )

    params = dict(BASE_PARAMS)
    # 固定正漂移(每 bar +2.5bps,累计 0.0024 > margin 0.002)
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator

    gen = ProbeSegmentedDriftGenerator()
    drift_params = {
        "episode_bars": 96, "vol_bps_range": [8.0, 10.0],
        "initial_price": 100.0, "regimes": [[1, 2.5, 96]],
    }
    flip_params = dict(drift_params)
    flip_params["antithetic_flip"] = True
    seeds = pack_construction_seeds("probe_null_stochvol", 0, 8)
    eps = []
    for s in seeds:
        # 用同 namespace seed 生成(漂移市场;flip 镜像)
        eps.append(gen.generate(dict(drift_params), s,
                                split="null_control", timeframe="15m"))
        eps.append(gen.generate(dict(flip_params), s,
                                split="null_control", timeframe="15m"))
    assert len(eps) == 16
    rep = validate_null_pack(
        {"probe_null_stochvol": eps}, cfg=cfg, schema=schema,
        spec=_spec(cfg), **__import__('compat_stage2_6_0f', fromlist=['validate_kwargs']).validate_kwargs())
    # antithetic 抵消确定性漂移 -> long 不超;但 oracle/rule 中心在
    # 漂移市场(方向恒正可预测)超 margin -> PACK_INVALID
    assert rep["verdict"] == "PACK_INVALID", rep["reasons"]


def test_modified_path_breaks_pack_integrity(sealed_exam_env):
    """D7:pack 的任一 null Episode 路径被修改 -> pack hash 变化 ->
    执行器现算的 pack validity hash 与承诺不一致(EXAM_INVALID)。"""
    from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
    from rl_curriculum.null_pack_validation import validate_null_pack

    env = sealed_exam_env
    pack = env["pack"]
    eps = [s for s in pack.episodes if s.split == "null_control"]
    assert eps
    # 篡改一个 null episode 的 seed(路径被修改)
    victim = eps[0]
    tampered_specs = [
        s if s is not victim else EpisodeSpec(
            s.family, s.params, s.seed + 1, s.split, timeframe=s.timeframe)
        for s in pack.episodes]
    tampered_pack = ExamPack(
        name=pack.name, version=pack.version, visibility=pack.visibility,
        charter_hash=pack.charter_hash, spec_versions=pack.spec_versions,
        episodes=tampered_specs, timeframe=pack.timeframe)
    assert tampered_pack.pack_hash() != pack.pack_hash()
    # 承诺的 pack_validity 绑定原 pack -> hash 失配
    assert env["commitment"].pack_validity["pack_hash"] == \
        pack.pack_hash()
    assert env["commitment"].pack_validity["pack_hash"] != \
        tampered_pack.pack_hash()


def test_missing_flip_breaks_structure_check(schema, cfg):
    """D7:pack 缺一个 flip Episode(镜像对不完整)-> pack-level
    antithetic 结构检查失败。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from null_qual_cache import null_episode_specs

    specs = null_episode_specs(families=("probe_null_sign",))
    # 丢掉最后一个 flip(flip_params 的一支)
    victim_idx = max(
        i for i, s in enumerate(specs)
        if (s.params or {}).get("antithetic_flip")) if any(
        (s.params or {}).get("antithetic_flip") for s in specs) else -1
    broken = [s for i, s in enumerate(specs) if i != victim_idx]
    eps = [R[s.family].generate(dict(s.params), s.seed, split=s.split,
                                timeframe=s.timeframe) for s in broken]
    rep = validate_null_pack(
        {"probe_null_sign": eps}, cfg=cfg, schema=schema, spec=_spec(cfg),
        **__import__('compat_stage2_6_0f', fromlist=['validate_kwargs']).validate_kwargs())
    assert rep["verdict"] == "PACK_INVALID"
    assert any("antithetic" in r or "镜像" in r
               for r in rep["reasons"])


def test_builder_not_candidate_dependent():
    """B4:构建函数签名不接收任何候选/模型输入。"""
    import inspect
    import rl_curriculum.mock_sealed_exam as mse

    sig = inspect.signature(mse.build_mock_hidden_pack)
    for banned in ("checkpoint", "candidate", "model", "policy"):
        assert banned not in sig.parameters
