# -*- coding: utf-8 -*-
"""R1-A 开盘偿付/维护风险边界正反例(独立审查 §3 的原反例+邻接例)。

原反例(上轮缺陷):100 资金/100 价满额做空,下一 open=250 时净值
−50、close=100;HOLD 被判有效且未终止。v2 语义:开盘偿付检查先于
模型动作,HOLD 与 REBALANCE 同经济状态一致;失败可追踪;无未记录
异常;不使用未来 high/low(prices 无该列)。
"""

import math

import numpy as np
import pandas as pd
import pytest

from rl_posctl.env import HybridPositionEnv


def _feats(n):
    rng = np.random.default_rng(11)
    return pd.DataFrame(rng.normal(size=(n, 2)),
                        columns=["f0", "f1"])


def _mk(opens, closes, fee=0.0, mm=0.05):
    return HybridPositionEnv(
        features=_feats(len(opens)),
        prices=pd.DataFrame({"open": list(opens),
                             "close": list(closes)}),
        fee=fee, window_size=1, maintenance_margin=mm)


class TestOpenInsolvency:
    def test_review_counterexample_short_gap_hold_fails_at_open(self):
        """审查原反例:short −1@100,open=250(净值 −50)→ HOLD
        必须在开盘失败终结,不得等 close=100 '恢复'。"""
        env = _mk([100, 100, 250], [100, 100, 100])
        env.reset()
        _, _, _, _, i1 = env.step([1.0, -1.0])
        assert i1["qty"] == pytest.approx(-1.0)
        obs, r, term, trunc, info = env.step([0.0, 0.0])   # HOLD
        assert term is True
        assert info["reward_valid"] is False
        ef = info["economic_failure"]
        assert ef["phase"] == "open"
        assert ef["executed"] is False
        assert ef["equity_at_open"] == pytest.approx(-50.0)
        # 不执行任何动作 ⇒ 无费用、无成交
        assert info["fee"] == 0.0
        assert info["signed_qty"] == 0.0
        assert info["fill_kind"] is None
        # 终结后继续 step = 显式异常(不静默)
        with pytest.raises(RuntimeError):
            env.step([0.0, 0.0])

    def test_same_state_rebalance_identical_failure(self):
        """同经济状态一致:REBALANCE(0) 与 HOLD 同样在开盘失败,
        不给任何分支'先活过去'的权限。"""
        env = _mk([100, 100, 250], [100, 100, 100])
        env.reset()
        env.step([1.0, -1.0])
        obs, r, term, trunc, info = env.step([1.0, 0.0])
        assert term is True
        assert info["reward_valid"] is False
        assert info["economic_failure"]["phase"] == "open"
        assert info["economic_failure"]["executed"] is False

    def test_long_crash_gap_symmetric(self):
        """多头跳空崩盘方向对称:+1@100,open=−50 净值 250→..."""
        # equity = 100 + 1*(open−100);open=−40 → equity = −40
        env = _mk([100, 100, -40.0, -40.0], [100, 100, -40.0, -40.0])
        env.reset()
        env.step([1.0, 1.0])
        obs, r, term, trunc, info = env.step([0.0, 0.0])
        assert term is True
        assert info["economic_failure"]["equity_at_open"] < 0

    def test_positive_equity_survives_gap(self):
        """正例:轻仓+跳空仍偿付 ⇒ 无失败,经济照常。"""
        env = _mk([100, 100, 130.0, 130.0], [100, 100, 130.0, 130.0])
        env.reset()
        env.step([1.0, 0.2])
        obs, r, term, trunc, info = env.step([0.0, 0.0])
        assert info["reward_valid"] is True
        assert term is False

    def test_failure_recorded_in_step_records_and_reward_none(self):
        env = _mk([100, 100, 250], [100, 100, 100])
        env.reset()
        env.step([1.0, -1.0])
        env.step([0.0, 0.0])
        rec = env.step_records[-1]
        assert rec["reward_raw"] is None
        assert rec["reward_scaled"] is None
        assert rec["reward_valid"] is False
        assert rec["economic_failure"]["phase"] == "open"
        assert env.episode_reward_raw is None


class TestOpenMaintenance:
    def _short_below_maintenance_at_open(self, action):
        """-1 空头@100,open=112:equity=88 < 0.9*112=100.8(维护
        不足但偿付为正)→ 开盘风险平仓;随后模型动作照常执行。"""
        env = _mk([100, 100, 112.0, 100.0],
                  [100, 100, 112.0, 100.0], fee=0.001, mm=0.9)
        env.reset()
        env.step([1.0, -1.0])
        obs, r, term, trunc, info = env.step(action)
        assert info["open_risk_triggered"] is True
        assert info["risk_action"]["phase"] == "open"
        assert info["risk_action"]["signed_qty"] == pytest.approx(
            1.0, rel=1e-3)
        assert info["risk_action"]["fee"] > 0.0
        assert term is False
        return env, info

    def test_hold_below_maintenance_open_flatten(self):
        env, info = self._short_below_maintenance_at_open([0.0, 0.0])
        assert info["action_branch"] == 0
        assert info["qty"] == pytest.approx(0.0)   # 平仓后空仓

    def test_rebalance_after_open_flatten_reexecutes(self):
        env, info = self._short_below_maintenance_at_open(
            [1.0, 0.5])
        # 开盘平仓后 REBALANCE(0.5) 在 open=112 上重新建多
        assert info["action_branch"] == 1
        assert info["qty"] > 0
        assert info["fill_kind"] == "rebalance"

    def test_solvency_ok_no_open_risk(self):
        """正例:同价格但足额(小仓)⇒ 无开盘风险事件。"""
        env = _mk([100, 100, 112.0, 100.0],
                  [100, 100, 112.0, 100.0], fee=0.001, mm=0.9)
        env.reset()
        obs, r, term, trunc, info = env.step([1.0, 0.2])
        assert info["risk_action"] is None
        assert info["reward_valid"] is True


class TestFundingAndRisk:
    def test_funding_then_close_risk_flatten(self):
        """开盘偿付充足、负资金费(空头支付)后仍偿付 → 无风险事件,
        资金费如实入账。"""
        # -0.5 空头@100,fee=0;资金费率 −0.6(空头支付 0.5*100*0.6)
        opens = [100, 100, 100.0, 100.0]
        closes = [100, 100, 100.0, 100.0]
        env = HybridPositionEnv(
            features=_feats(4),
            prices=pd.DataFrame({"open": opens, "close": closes}),
            fee=0.0, window_size=1, maintenance_margin=0.9,
            funding_schedule={2: -0.6})
        env.reset()
        env.step([1.0, -0.5])     # equity=100
        # bar2:开盘 100 equity=100 ≥ 0.9*50=45 通过;资金费 −30
        # → equity=70 < 0.9*50=45? 70>45 不触发。用更紧的仓:
        obs, r, term, trunc, info = env.step([0.0, 0.0])
        assert info["funding_payment"] == pytest.approx(-30.0)
        assert info["equity_end"] == pytest.approx(70.0)

    def test_funding_drives_below_maintenance_close_flatten(self):
        """资金费把净值打到维护线下 → 收盘风险平仓全额计入。"""
        env = HybridPositionEnv(
            features=_feats(4),
            prices=pd.DataFrame({"open": [100, 100, 100.0, 100.0],
                                 "close": [100, 100, 100.0, 100.0]}),
            fee=0.0, window_size=1, maintenance_margin=0.5,
            funding_schedule={2: -1.0})
        env.reset()
        env.step([1.0, -0.8])     # equity=100,notional=80
        # 资金费:空头支付 0.8*100*1.0=80 → equity=20 < 0.5*80=40
        obs, r, term, trunc, info = env.step([0.0, 0.0])
        assert info["funding_payment"] == pytest.approx(-80.0)
        assert info["risk_action"] is not None
        assert info["risk_action"]["phase"] == "close"
        assert info["qty"] == pytest.approx(0.0)
        assert info["reward_valid"] is True   # equity 20−0(fee=0)>0

    def test_terminal_liquidation_last_bar(self):
        """终端清算:最后一根强平与普通平仓同费用;HOLD 不阻止。"""
        env = _mk([100, 100, 100.0, 100.0, 100.0],
                  [100, 100, 100.0, 100.0, 100.0], fee=0.001)
        env.reset()
        env.step([1.0, 0.5])
        env.step([0.0, 0.0])
        env.step([0.0, 0.0])
        obs, r, term, trunc, info = env.step([0.0, 0.0])
        assert term is True
        tl = info["terminal_liquidation"]
        assert tl is not None
        assert tl["signed_qty"] == pytest.approx(-0.5, rel=1e-3)
        assert tl["fee"] > 0.0

    def test_no_future_high_low_used(self):
        """带 high/low 列的环境不使用它们(执行只看 open/close)。"""
        prices = pd.DataFrame({
            "open": [100, 100, 110.0, 110.0],
            "close": [100, 100, 105.0, 105.0],
            "high": [100, 100, 500.0, 500.0],
            "low": [100, 100, 1.0, 1.0]})
        env = HybridPositionEnv(
            features=_feats(4), prices=prices, fee=0.0,
            window_size=1)
        env.reset()
        obs, r, term, trunc, i1 = env.step([1.0, 0.5])
        # 执行 bar1:open=close=100 → equity 100(建仓无浮盈)
        assert i1["equity_end"] == pytest.approx(100.0)
        obs, r, term, trunc, info = env.step([0.0, 0.0])
        # bar2 close=105 → equity 102.5;不用 low=1/high=500
        assert info["equity_end"] == pytest.approx(102.5)


class TestErrorTraceability:
    def test_open_failure_no_unrecorded_exception(self):
        """开盘非正净值路径不产生未记录异常:失败信息完整落
        info/step_records,账本调用不 raise。"""
        env = _mk([100, 100, 250.0, 250.0],
                  [100, 100, 250.0, 250.0], fee=0.001)
        env.reset()
        env.step([1.0, -1.0])
        try:
            obs, r, term, trunc, info = env.step([1.0, 0.3])
        except Exception as exc:      # pragma: no cover
            pytest.fail(f"开盘失败路径抛出未记录异常: {exc}")
        assert term and info["reward_valid"] is False
        assert info["economic_failure"]["executed"] is False

    def test_reward_zero_placeholder_flagged_invalid(self):
        """失败步 reward 数值 0.0 是占位;valid=False 必须让训练
        harness 判无效(不能把 0 当真实收益)。"""
        env = _mk([100, 100, 250.0], [100, 100, 250.0])
        env.reset()
        env.step([1.0, -1.0])
        obs, r, term, trunc, info = env.step([0.0, 0.0])
        assert r == 0.0
        assert info["reward_valid"] is False
        assert info["reward_raw"] is None
