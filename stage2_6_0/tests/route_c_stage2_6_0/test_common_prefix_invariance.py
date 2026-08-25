"""工作包 H.1:共同前缀 / 不同未来后缀(因果性硬测试)。"""

from __future__ import annotations

import pandas as pd

from rl_curriculum.counterfactual import (
    splice_prefix_suffix,
    test_common_prefix_future_suffix,
)
from rl_curriculum.policies import (
    FutureLeakProbePolicy,
    OracleSegmentedDriftPolicy,
    RuleTrendPolicy,
    StepCounterCheaterPolicy,
)

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}


def test_splice_prefix_bitwise_identical(gen_a):
    ep = gen_a.generate(TRAIN_PARAMS, seed=31)
    other = gen_a.generate(TRAIN_PARAMS, seed=31 + 10_000)
    cut = 48
    df_c = splice_prefix_suffix(ep.df, other.df, cut)
    cols = [c for c in df_c.columns if c != "date"]
    assert df_c[cols].iloc[:cut].equals(ep.df[cols].iloc[:cut])
    # 后缀相对收益与 other 一致(几何缩放)
    import numpy as np

    k = ep.df["close"].iloc[cut - 1] / other.df["close"].iloc[cut - 1]
    assert np.allclose(
        df_c["close"].to_numpy()[cut:], other.df["close"].to_numpy()[cut:] * k
    )
    # 价格连续:open[cut] == close[cut-1]
    assert df_c["open"].iloc[cut] == df_c["close"].iloc[cut - 1]


def test_oracle_passes_common_prefix(gen_a, cfg):
    ep = gen_a.generate(TRAIN_PARAMS, seed=32)
    r = test_common_prefix_future_suffix(
        gen_a, OracleSegmentedDriftPolicy(), ep, cfg)
    assert r.pass_, r.reason
    assert r.action_match_rate == 1.0
    assert r.first_divergence_step is None


def test_rule_policy_passes_common_prefix(gen_a, cfg):
    ep = gen_a.generate(TRAIN_PARAMS, seed=33)
    r = test_common_prefix_future_suffix(
        gen_a, RuleTrendPolicy(ma_threshold=0.001), ep, cfg)
    assert r.pass_, r.reason


def test_future_leak_probe_detected(gen_a, cfg):
    """修改未来后缀改变共同前缀动作 -> 判定未来泄漏(多切割点)。"""
    pol = FutureLeakProbePolicy(fee_threshold=cfg.fee)
    detected = False
    for seed in (41, 42):
        ep = gen_a.generate(TRAIN_PARAMS, seed=seed)
        for cut_ratio in (0.3, 0.5, 0.7):
            r = test_common_prefix_future_suffix(
                gen_a, pol, ep, cfg, cut_ratio=cut_ratio)
            if not r.pass_:
                detected = True
                assert r.first_divergence_step is not None
    assert detected, "FutureLeakProbe 必须在某个切割点暴露"


def test_step_counter_passes_common_prefix_but_fails_length(gen_a, cfg):
    """StepCounter 不读未来 -> 共同前缀通过(由长度测试负责抓)。"""
    ep = gen_a.generate(TRAIN_PARAMS, seed=34)
    r = test_common_prefix_future_suffix(
        gen_a, StepCounterCheaterPolicy(), ep, cfg)
    assert r.pass_
