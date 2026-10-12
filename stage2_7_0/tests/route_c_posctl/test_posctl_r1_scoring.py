# -*- coding: utf-8 -*-
"""R1-C 评分与成本对账正反例(独立审查 §5 原反例+分类总账)。

原反例(上轮缺陷):100 资金/单边 fee=0.001/最后一步开 +1 并终端
清仓——账本手续费 0.1998、报告只计 0.0999;总成交 199.8 报告只
99.9;初始至终态回撤 0.002 报告为 0。v2 summarize:全腿分类、初始
净值前置、总账对账、失败段 invalid 不冒充。
"""

import math

import numpy as np
import pandas as pd
import pytest

from rl_posctl.env import HybridPositionEnv
from rl_posctl.evalreport import run_policy, summarize


def _feats(n):
    rng = np.random.default_rng(13)
    return pd.DataFrame(rng.normal(size=(n, 2)),
                        columns=["f0", "f1"])


def _flat_run(opens, closes, fee=0.001, mm=0.05, funding=None):
    env = HybridPositionEnv(
        features=_feats(len(opens)),
        prices=pd.DataFrame({"open": list(opens),
                             "close": list(closes)}),
        fee=fee, window_size=1, maintenance_margin=mm,
        funding_schedule=funding)
    infos = run_policy(env, lambda row, w, sl: (1, 0.0))
    return env, infos


class TestReviewCounterexampleCosts:
    def test_open_long_terminal_close_full_accounting(self):
        """审查原例:100 资金,fee=0.001,第一步开 +1(open=100),
        最后一步终端清算(close=100)。"""
        opens = [100.0, 100.0, 100.0]
        closes = [100.0, 100.0, 100.0]
        env = HybridPositionEnv(
            features=_feats(3),
            prices=pd.DataFrame({"open": opens, "close": closes}),
            fee=0.001, window_size=1)
        env.reset()
        env.step([1.0, 1.0])          # 开 +1(bar1 执行)
        obs, r, term, trunc, info = env.step([0.0, 0.0])  # bar2 终端清算
        assert term is True
        infos = env.step_records
        s = summarize(infos)
        # 账本真实:开仓腿 fee=0.0999001 + 清算腿 fee=0.0999001
        assert s["model_action_fees"] == pytest.approx(
            0.0999000999, rel=1e-6)
        assert s["terminal_liquidation_fees"] == pytest.approx(
            0.0999000999, rel=1e-6)
        assert s["total_fees"] == pytest.approx(0.1998001998,
                                                rel=1e-6)
        # 全腿换手:开 100 + 清 99.9 = 199.8
        assert s["turnover_notional"] == pytest.approx(
            199.8001998001, rel=1e-6)
        # 回撤从初始净值起算:首步末 equity=99.9 → dd≈0.001/100
        assert s["max_drawdown"] == pytest.approx(
            0.001998001998, rel=1e-6)
        assert s["max_drawdown_includes_initial"] is True
        # 总账对账:分类和 == 账本累计
        assert s["reconciliation"]["fees_match"] is True

    def test_risk_flatten_fees_classified(self):
        """风险平仓费单独分类且计入总账(不漏计)。"""
        env = HybridPositionEnv(
            features=_feats(4),
            prices=pd.DataFrame({"open": [100, 100, 112.0, 100.0],
                                 "close": [100, 100, 112.0, 100.0]}),
            fee=0.001, window_size=1, maintenance_margin=0.9)
        env.reset()
        env.step([1.0, -1.0])
        env.step([0.0, 0.0])          # 开盘风险平仓
        env.step([1.0, 0.0])
        s = summarize(env.step_records)
        assert s["risk_action_fees"] > 0.0
        assert s["n_risk_actions"] == 1
        assert s["n_open_risk_actions"] == 1
        assert s["reconciliation"]["fees_match"] is True

    def test_funding_classified_and_reconciled(self):
        env, infos = _flat_run(
            [100, 100, 100.0, 100.0], [100, 100, 100.0, 100.0],
            fee=0.0, funding={2: 0.5})
        s = summarize(infos)
        assert s["funding_total"] == 0.0    # 空仓无资金费
        env2 = HybridPositionEnv(
            features=_feats(4),
            prices=pd.DataFrame({"open": [100, 100, 100.0, 100.0],
                                 "close": [100, 100, 100.0, 100.0]}),
            fee=0.0, window_size=1, funding_schedule={2: 0.5})
        env2.reset()
        env2.step([1.0, 0.5])
        env2.step([0.0, 0.0])
        env2.step([0.0, 0.0])
        s2 = summarize(env2.step_records)
        assert s2["funding_total"] == pytest.approx(-25.0)
        assert s2["reconciliation"]["funding_match"] is True
        assert s2["total_cost_all_in"] == pytest.approx(-25.0)


class TestFailureScoring:
    def test_failure_marks_invalid_and_keeps_partial_sum(self):
        """经济失败:net_log_return=None/valid=False;部分和与失败
        原因保留;不用截断段冒充整段收益。"""
        env = HybridPositionEnv(
            features=_feats(4),
            prices=pd.DataFrame({"open": [100, 100, 250.0, 250.0],
                                 "close": [100, 100, 250.0, 250.0]}),
            fee=0.0, window_size=1)
        env.reset()
        env.step([1.0, -1.0])         # 开空
        env.step([0.0, 0.0])          # 开盘失败(open=250 → −50)
        s = summarize(env.step_records)
        assert s["economic_failure"] is True
        assert s["net_log_return"] is None
        assert s["net_log_return_valid"] is False
        assert s["net_return"] is None
        assert s["net_return_valid"] is False
        # 首步(有效)部分和保留,失败原因完整记录
        assert s["net_log_return_partial_sum"] == pytest.approx(0.0)
        assert any("开盘净值非正" in x
                   for x in s["economic_failure_reasons"])
        assert s["n_reward_invalid_steps"] == 1

    def test_normal_run_valid(self):
        env, infos = _flat_run([100, 100, 105.0, 105.0],
                               [100, 100, 105.0, 105.0], fee=0.0)
        s = summarize(infos)
        assert s["economic_failure"] is False
        assert s["net_log_return_valid"] is True
        assert s["net_log_return"] == pytest.approx(0.0)


class TestDrawdownInitialSegment:
    def test_dd_covers_initial_to_first_step(self):
        """首步即亏损:回撤必须包含 初始→首步末 段(上轮漏记)。"""
        env = HybridPositionEnv(
            features=_feats(3),
            prices=pd.DataFrame({"open": [100.0, 100.0, 99.0],
                                 "close": [100.0, 99.0, 99.0]}),
            fee=0.001, window_size=1)
        env.reset()
        env.step([1.0, 1.0])          # open@100 →close 99:亏 1+费
        env.step([0.0, 0.0])
        s = summarize(env.step_records)
        eq1 = 100.0 - 1.0 - 0.1       # 首步末净值(近似)
        assert s["initial_equity"] == pytest.approx(100.0)
        assert s["max_drawdown"] > (1.0 - 0.99)   # 至少首步损失
