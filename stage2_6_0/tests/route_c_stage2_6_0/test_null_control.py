"""工作包 H.12:Null Control(无可预测信号 + 有费用)。"""

from __future__ import annotations

import numpy as np

from rl_curriculum.counterfactual import test_null_control
from rl_curriculum.policies import (
    AlwaysFlatPolicy,
    HighTurnoverPolicy,
    NullOvertraderPolicy,
    OracleSegmentedDriftPolicy,
    RuleTrendPolicy,
)

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}
B_PARAMS = {"episode_bars": 96, "sigma_mu_bps": 4.0, "vol_bps": 28.0,
            "theta": 0.015}


def _null_eps(gen_c, seeds=(71, 72, 73, 74, 75, 76)):
    return [gen_c.generate(dict(TRAIN_PARAMS), seed=s, split="null_control")
            for s in seeds]


def test_null_returns_are_permutation_of_source(gen_c, gen_a):
    """Null 收益 = 探针 A 同源轨迹收益的重排(边际分布精确保留)。"""
    ep_null = gen_c.generate(dict(TRAIN_PARAMS), seed=81)
    ep_src = gen_a.generate(dict(TRAIN_PARAMS), seed=81)
    # 完整收益序列(prepend 初始价):np.diff 会丢首元素,而重排改变了
    # 被丢的元素,必须用全序列比较边际分布
    rets_null = np.sort(np.diff(
        np.log(ep_null.df["close"].to_numpy()),
        prepend=float(np.log(ep_null.df["open"].iloc[0]))))
    rets_src = np.sort(np.diff(
        np.log(ep_src.df["close"].to_numpy()),
        prepend=float(np.log(ep_src.df["open"].iloc[0]))))
    assert np.allclose(rets_null, rets_src, atol=1e-9)


def test_rule_no_stable_excess_in_null(gen_c, cfg):
    r = test_null_control(
        RuleTrendPolicy(ma_threshold=0.001), _null_eps(gen_c), cfg)
    assert r.pass_, r.reason
    assert r.extra["excess_positive_ratio"] < 0.75


def test_oracle_loses_advantage_in_null(gen_c, cfg):
    """隐藏标签保留但预测力被切断:Oracle 无稳定优势。"""
    r = test_null_control(
        OracleSegmentedDriftPolicy(), _null_eps(gen_c), cfg)
    assert r.pass_, r.reason


def test_overtrader_fees_loss_high_turnover_in_null(gen_c, cfg):
    r = test_null_control(NullOvertraderPolicy(), _null_eps(gen_c), cfg)
    assert r.pass_
    assert r.extra["high_turnover"] is True
    assert r.extra["excess_median"] < 0


def test_always_flat_strong_baseline_in_null(gen_c, cfg):
    r = test_null_control(AlwaysFlatPolicy(), _null_eps(gen_c), cfg)
    assert r.pass_
    assert abs(r.extra["excess_median"]) < 1e-12


def test_null_hidden_labels_kept_but_independent(gen_c, gen_a):
    """隐藏标签保留;与未来收益的相关性被切断(对照:A 中显著相关)。"""
    ep_null = gen_c.generate(dict(TRAIN_PARAMS), seed=82)
    ep_src = gen_a.generate(dict(TRAIN_PARAMS), seed=82)
    fut_null = np.diff(np.log(ep_null.df["close"].to_numpy()))
    fut_src = np.diff(np.log(ep_src.df["close"].to_numpy()))
    lab_null = ep_null.hidden["regime_direction"].to_numpy()[:-1]
    lab_src = ep_src.hidden["regime_direction"].to_numpy()[:-1]
    assert abs(np.corrcoef(lab_src, fut_src)[0, 1]) > 0.1  # A:标签有预测力
    assert abs(np.corrcoef(lab_null, fut_null)[0, 1]) < 0.35  # Null:切断


def test_null_construction_similarity(gen_c, gen_a):
    """与 A 相似的波动率量级与 Episode 长度(结构尽量一致)。"""
    ep_null = gen_c.generate(dict(TRAIN_PARAMS), seed=83)
    ep_src = gen_a.generate(dict(TRAIN_PARAMS), seed=83)
    v_null = np.std(np.diff(np.log(ep_null.df["close"].to_numpy())))
    v_src = np.std(np.diff(np.log(ep_src.df["close"].to_numpy())))
    assert abs(v_null - v_src) < 0.005
    assert len(ep_null.df) == len(ep_src.df)
    assert list(ep_null.df.columns) == list(ep_src.df.columns)
