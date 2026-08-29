"""工作包 H.12 + 阶段 2.6.0a 工作包 L:多族 Null Control。

阶段 2.6.0a 更新:test_null_control 接收按族分组的 Episode 字典;
正式结论要求跨多个结构不同的 Null 家族一致;全排列(probe_null_control)
保留为探针。
"""

from __future__ import annotations

import numpy as np

from rl_curriculum.counterfactual import test_null_control
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
from rl_curriculum.policies import (
    AlwaysFlatPolicy,
    HighTurnoverPolicy,
    OracleSegmentedDriftPolicy,
    RuleTrendPolicy,
)
from rl_curriculum.probes import NullOvertraderProbe

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}
FORMAL_NULLS = ("probe_null_sign", "probe_null_block", "probe_null_volstate")


def _null_by_family(families, params=None, seeds=(71, 72, 73, 74)):
    return {
        fam: [DEFAULT_GENERATOR_REGISTRY[fam].generate(
            dict(params or TRAIN_PARAMS), seed=s, split="null_control",
            timeframe="15m") for s in seeds]
        for fam in families
    }


def test_null_returns_are_permutation_of_source(gen_c, gen_a):
    """全排列 Null 收益 = 探针 A 同源轨迹收益的重排(边际分布精确保留)。"""
    ep_null = gen_c.generate(dict(TRAIN_PARAMS), seed=81, timeframe="15m")
    ep_src = gen_a.generate(dict(TRAIN_PARAMS), seed=81, timeframe="15m")
    rets_null = np.sort(np.diff(
        np.log(ep_null.df["close"].to_numpy()),
        prepend=float(np.log(ep_null.df["open"].iloc[0]))))
    rets_src = np.sort(np.diff(
        np.log(ep_src.df["close"].to_numpy()),
        prepend=float(np.log(ep_src.df["open"].iloc[0]))))
    assert np.allclose(rets_null, rets_src, atol=1e-9)


def test_sign_null_preserves_absolute_returns(gen_a):
    """符号 Null:|收益| 逐位保留(波动聚集幅度结构保留),方向被随机化。"""
    gen_sign = DEFAULT_GENERATOR_REGISTRY["probe_null_sign"]
    ep_null = gen_sign.generate(dict(TRAIN_PARAMS), seed=81, timeframe="15m")
    ep_src = gen_a.generate(dict(TRAIN_PARAMS), seed=81, timeframe="15m")
    r_null = np.diff(np.log(ep_null.df["close"].to_numpy()),
                     prepend=float(np.log(ep_null.df["open"].iloc[0])))
    r_src = np.diff(np.log(ep_src.df["close"].to_numpy()),
                    prepend=float(np.log(ep_src.df["open"].iloc[0])))
    assert np.allclose(np.sort(np.abs(r_null)), np.sort(np.abs(r_src)),
                       atol=1e-12)
    assert not np.allclose(np.sort(r_null), np.sort(r_src), atol=1e-9)


def test_block_null_preserves_within_block_structure():
    gen_block = DEFAULT_GENERATOR_REGISTRY["probe_null_block"]
    ep = gen_block.generate({**TRAIN_PARAMS, "null_block_size": 8},
                            seed=82, timeframe="15m")
    assert ep.meta["null_doc"]["preserves"].startswith("块内")


def test_volstate_null_preserves_marginal():
    """波动状态 Null:|收益| 多重集合保留,符号被随机化(方向 1)。"""
    from rl_curriculum.generators import ProbeNullVolStateShuffleGenerator

    gen = ProbeNullVolStateShuffleGenerator()
    ep = gen.generate(dict(TRAIN_PARAMS), seed=83, timeframe="15m")
    src = _source_returns(TRAIN_PARAMS, 83)
    r = np.diff(np.log(ep.df["close"].to_numpy()),
                prepend=float(np.log(ep.df["open"].iloc[0])))
    assert np.allclose(np.sort(np.abs(r)), np.sort(np.abs(src)), atol=1e-12)
    # 符号随机化:带符号多重集合与源不同
    assert not np.allclose(np.sort(r), np.sort(src), atol=1e-9)


def _source_returns(params, seed):
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator

    gen = ProbeSegmentedDriftGenerator()
    ep = gen.generate(dict(params), seed=seed, timeframe="15m")
    return np.diff(np.log(ep.df["close"].to_numpy()),
                   prepend=float(np.log(ep.df["open"].iloc[0])))


def test_rule_no_stable_excess_across_null_families(cfg, schema):
    r = test_null_control(
        RuleTrendPolicy(ma_threshold=0.001),
        _null_by_family(FORMAL_NULLS), cfg, schema)
    assert r.pass_, r.reason
    # 分块 Null 的档内残存结构可使个别 seed 超额为正(已声明的局限),
    # 但任何一族都不得达到"稳定正超额"(中位>0 且 比例>=0.75 且 CI>0)
    for fam, per in r.extra["per_family"].items():
        assert not per["stable_positive_excess"], fam


def test_oracle_loses_advantage_in_all_null_families(cfg, schema):
    """隐藏标签保留但预测力被切断:Oracle 无稳定优势(跨族一致)。"""
    r = test_null_control(
        OracleSegmentedDriftPolicy(), _null_by_family(FORMAL_NULLS),
        cfg, schema)
    assert r.pass_, r.reason


def test_overtrader_fees_loss_high_turnover_in_null(cfg, schema):
    r = test_null_control(NullOvertraderProbe(),
                          _null_by_family(("probe_null_control",)), cfg, schema)
    assert r.pass_
    assert r.extra["high_turnover"] is True
    assert r.extra["per_family"]["probe_null_control"]["excess_median"] < 0


def test_always_flat_strong_baseline_in_null(cfg, schema):
    r = test_null_control(AlwaysFlatPolicy(),
                          _null_by_family(FORMAL_NULLS), cfg, schema)
    assert r.pass_
    for per in r.extra["per_family"].values():
        assert abs(per["excess_median"]) < 1e-12


def test_high_turnover_baseline_loses_in_null(cfg, schema):
    r = test_null_control(HighTurnoverPolicy(),
                          _null_by_family(FORMAL_NULLS), cfg, schema)
    assert r.pass_
    assert r.extra["high_turnover"] is True


def test_null_hidden_labels_kept_but_independent(gen_c, gen_a):
    """隐藏标签保留;与未来收益的相关性被切断(对照:A 中显著相关)。"""
    ep_null = gen_c.generate(dict(TRAIN_PARAMS), seed=82, timeframe="15m")
    ep_src = gen_a.generate(dict(TRAIN_PARAMS), seed=82, timeframe="15m")
    fut_null = np.diff(np.log(ep_null.df["close"].to_numpy()))
    fut_src = np.diff(np.log(ep_src.df["close"].to_numpy()))
    lab_null = ep_null.hidden["regime_direction"].to_numpy()[:-1]
    lab_src = ep_src.hidden["regime_direction"].to_numpy()[:-1]
    assert abs(np.corrcoef(lab_src, fut_src)[0, 1]) > 0.1  # A:标签有预测力
    assert abs(np.corrcoef(lab_null, fut_null)[0, 1]) < 0.35  # Null:切断


def test_null_construction_similarity(gen_c, gen_a):
    """与 A 相似的波动率量级与 Episode 长度(结构尽量一致)。"""
    ep_null = gen_c.generate(dict(TRAIN_PARAMS), seed=83, timeframe="15m")
    ep_src = gen_a.generate(dict(TRAIN_PARAMS), seed=83, timeframe="15m")
    v_null = np.std(np.diff(np.log(ep_null.df["close"].to_numpy())))
    v_src = np.std(np.diff(np.log(ep_src.df["close"].to_numpy())))
    assert abs(v_null - v_src) < 0.005
    assert len(ep_null.df) == len(ep_src.df)
    assert list(ep_null.df.columns) == list(ep_src.df.columns)
