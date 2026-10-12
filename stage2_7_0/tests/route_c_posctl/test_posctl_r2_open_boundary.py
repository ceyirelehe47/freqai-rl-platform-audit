# -*- coding: utf-8 -*-
"""R2-02 开盘风险平仓扣费后不可偿付:统一经济失败终态正反例。

原反例(独立审查 F2/probe post_risk_fee):100 资金/fee=.001/100 价
开空 −1;次 open=199.8999 使开盘净值 0.1,风险平仓费 ≈0.1997002,
扣费后净值 −0.0997001998:
- HOLD 落 reward_invalid 终态(旧);
- 目标 0/+0.5 在 apply_target_ratio 抛 ValueError,step_records
  增量 0、economic_failure=None(信息丢失)——R2 修复对象。
v3:强制风险成交后偿付复查先于任意模型动作;HOLD/清仓/正负目标
一致终结;已发生成交/费用保全;修复后 step 拒绝;正净值路径不回归。
"""

import math

import numpy as np
import pandas as pd
import pytest

from rl_posctl.env import HybridPositionEnv

AFTER_FEE = -0.0997001998002105      # reviewer 探针原值
RISK_FEE = 0.1997001998001998
OPEN_FEE = 0.0999000999000999        # 开空 −1 的建仓费(同账本)


def _feats(n):
    rng = np.random.default_rng(21)
    return pd.DataFrame(rng.normal(size=(n, 2)),
                        columns=["f0", "f1"])


def _mk(opens, closes, fee=0.001, mm=0.05, funding=None):
    return HybridPositionEnv(
        features=_feats(len(opens)),
        prices=pd.DataFrame({"open": opens, "close": closes}),
        fee=fee, window_size=1, maintenance_margin=mm,
        funding_schedule=funding)


def _probe_env():
    """100→100→199.8999:-1 空头,bar2 开盘触发风险平仓且扣费后
    不可偿付(reviewer 固定路径)。"""
    return _mk([100.0, 100.0, 199.8999],
               [100.0, 100.0, 199.8999])


def _open_short(env):
    env.reset()
    obs, r, term, trunc, info = env.step([1.0, -1.0])
    assert not term
    return info


class TestPostRiskFeeInsolvency:
    @pytest.mark.parametrize("action", [
        [0.0, 0.0], [1.0, 0.0], [1.0, 0.5], [1.0, -0.5]])
    def test_all_branches_unified_terminal(self, action):
        """HOLD/清仓/正负目标:同一经济状态 ⇒ 同一失败终态,
        无未记录异常,不执行模型动作,成交/费用保全。"""
        env = _probe_env()
        _open_short(env)
        n0 = len(env.step_records)
        obs, r, term, trunc, info = env.step(action)
        assert term is True and trunc is False
        assert info["reward_valid"] is False
        assert info["reward_raw"] is None
        assert r == 0.0                    # 占位,valid=False
        ef = info["economic_failure"]
        assert ef["phase"] == "open_risk_flatten"
        assert ef["cause"] == "risk_flatten_fee_insolvency"
        assert ef["executed"] is False     # 模型动作未执行
        assert ef["action"] == action
        assert info["equity_end"] == pytest.approx(
            AFTER_FEE, rel=1e-9)
        # 风险腿保全:费用/成交价/数量 + 账本累计
        ra = info["risk_action"]
        assert ra is not None and ra["phase"] == "open"
        assert ra["fee"] == pytest.approx(RISK_FEE, rel=1e-9)
        # 账本累计保全建仓费+风险费(已发生费用不丢失)
        assert info["fees_cum"] == pytest.approx(
            OPEN_FEE + RISK_FEE, rel=1e-9)
        assert info["qty"] == pytest.approx(0.0)   # 已全额平仓
        # 记录完整落账(旧 REBALANCE 分支 record 增量 0)
        assert len(env.step_records) - n0 == 1
        rec = env.step_records[-1]
        assert rec["economic_failure"]["cause"] == (
            "risk_flatten_fee_insolvency")

    def test_step_after_terminal_refused(self):
        env = _probe_env()
        _open_short(env)
        env.step([1.0, 0.0])
        with pytest.raises(RuntimeError, match="终结"):
            env.step([0.0, 0.0])

    def test_no_recovery_window(self):
        """扣费后不可偿付 ⇒ 当根终结,不允许"等收盘恢复":
        即使 close 回到 100(对空头有利)也必须失败终结。"""
        env = _mk([100.0, 100.0, 199.8999],
                  [100.0, 100.0, 100.0])
        _open_short(env)
        obs, r, term, trunc, info = env.step([0.0, 0.0])
        assert term is True
        assert info["reward_valid"] is False
        assert info["economic_failure"][
            "cause"] == "risk_flatten_fee_insolvency"

    def test_positive_after_risk_fee_model_action_still_runs(self):
        """正例(不回归):风险平仓扣费后仍偿付 ⇒ 模型动作照常
        执行(含 REBALANCE 重新建仓与 HOLD 空仓)。"""
        env = _mk([100.0, 100.0, 112.0, 100.0],
                  [100.0, 100.0, 112.0, 100.0], fee=0.001, mm=0.9)
        env.reset()
        env.step([1.0, -1.0])
        obs, r, term, trunc, info = env.step([1.0, 0.5])
        assert info["open_risk_triggered"] is True
        assert info["equity_end"] > 0.0
        assert info["fill_kind"] == "rebalance"
        assert info["qty"] > 0.0
        assert info["reward_valid"] is True


class TestAdjacentInsolvencyAttribution:
    def test_funding_insolvency_phase(self):
        """资金费结算后(收盘风险/终端前)净值 ≤0 ⇒ phase=funding,
        已发生资金费现金流保全。"""
        env = _mk([100.0, 100.0, 100.0, 100.0],
                  [100.0, 100.0, 100.0, 100.0], fee=0.0, mm=0.05,
                  funding={2: -1.3})
        env.reset()
        env.step([1.0, -0.8])
        obs, r, term, trunc, info = env.step([0.0, 0.0])
        assert info["funding_payment"] == pytest.approx(-104.0)
        ef = info["economic_failure"]
        assert ef["phase"] == "funding"
        assert ef["cause"] == "funding_insolvency"
        assert info["reward_valid"] is False

    def test_close_risk_fee_insolvency_phase(self):
        """开盘足额、收盘风险平仓费耗尽 ⇒ phase=close_risk_flatten
        (开盘偿付检查不误伤;归因首个不可偿付事件)。"""
        env = _mk([100.0, 100.0, 100.0, 100.0],
                  [100.0, 100.0, 130.0, 130.0], fee=0.8, mm=0.9)
        env.reset()
        env.step([1.0, -0.9])
        obs, r, term, trunc, info = env.step([0.0, 0.0])   # bar2 非末根
        ef = info["economic_failure"]
        assert ef["phase"] == "close_risk_flatten"
        assert info["risk_action"]["phase"] == "close"
        assert info["reward_valid"] is False

    def test_terminal_liquidation_fee_insolvency_phase(self):
        """终端清算费使净值 ≤0 ⇒ phase=terminal_liquidation,
        清算腿保全(HOLD 不能阻止清算/费用)。"""
        env = _mk([100.0, 100.0, 100.0, 100.0],
                  [100.0, 100.0, 100.0, 100.0], fee=3.0)
        env.reset()
        env.step([1.0, 0.5])          # fee=3:建仓费 60 ⇒ equity 40
        env.step([0.0, 0.0])
        obs, r, term, trunc, info = env.step(
            [0.0, 0.0])               # 终端清算费 60 ⇒ equity −20
        assert term is True
        ef = info["economic_failure"]
        assert ef["phase"] == "terminal_liquidation"
        assert info["terminal_liquidation"] is not None
        assert info["terminal_liquidation"]["fee"] > 0.0
        assert info["reward_valid"] is False

    def test_open_equity_positive_survives(self):
        """正例:无任何风险事件时既有语义不变(维护足额)。"""
        env = _mk([100.0, 100.0, 101.0],
                  [100.0, 100.0, 101.0], fee=0.001)
        env.reset()
        env.step([1.0, 0.3])
        obs, r, term, trunc, info = env.step([0.0, 0.0])
        assert info["risk_action"] is None
        assert info["reward_valid"] is True
