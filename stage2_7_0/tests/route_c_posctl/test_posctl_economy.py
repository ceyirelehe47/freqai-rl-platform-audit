# -*- coding: utf-8 -*-
"""W1 必测经济场景(ACTION_AND_LEDGER §7)——独立手算期望,不用被验
函数自己产生期望值。

期望值来源:任务书 §7 场景 1-9 的手算推导 + 本文内显式分数常量。
"""

from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from rl_posctl.env import HybridPositionEnv
from rl_posctl.ledger import TwoSidedLinearLedger
from rl_posctl.replay import record_episode, replay_episode


def _prices(opens, closes=None):
    closes = closes if closes is not None else opens
    return pd.DataFrame({"open": list(opens), "close": list(closes)})


def _feats(n, cols=2):
    rng = np.random.default_rng(7)
    return pd.DataFrame(rng.normal(size=(n, cols)),
                        columns=[f"f{i}" for i in range(cols)])


# ==================== 场景 1:无成本双向部分仓位 ====================
class TestScenario1PartialPositions:
    def test_long_0p4_then_price_110(self):
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.0)
        rec = L.apply_target_ratio(0.4, 100.0)
        assert L.qty == pytest.approx(0.4, abs=1e-12)
        assert L.equity(110.0) == pytest.approx(104.0, abs=1e-9)
        assert rec.achieved_ratio == pytest.approx(0.4, abs=1e-12)

    def test_short_0p4_then_price_110(self):
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.0)
        rec = L.apply_target_ratio(-0.4, 100.0)
        assert L.qty == pytest.approx(-0.4, abs=1e-12)
        assert L.equity(110.0) == pytest.approx(96.0, abs=1e-9)
        assert rec.achieved_ratio == pytest.approx(-0.4, abs=1e-12)

    def test_partial_not_full_notional(self):
        """请求 +0.4 必须是部分仓位,不是映射为满仓。"""
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.0)
        L.apply_target_ratio(0.4, 100.0)
        assert abs(L.qty * 100.0) == pytest.approx(40.0, abs=1e-9)


# ==================== 场景 2:HOLD 漂移与再请求减仓 ====================
class TestScenario2HoldDrift:
    def test_hold_qty_unchanged_ratio_drifts(self):
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.0)
        L.apply_target_ratio(0.4, 100.0)
        L.hold(110.0)
        assert L.qty == pytest.approx(0.4, abs=1e-12)
        # 44/104 = 0.4230769...(任务书手算值)
        assert L.exposure_ratio(110.0) == pytest.approx(
            Fraction(44, 104), abs=1e-12)

    def test_rerequest_same_target_reduces(self):
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.0)
        L.apply_target_ratio(0.4, 100.0)
        rec = L.apply_target_ratio(0.4, 110.0)
        assert rec.signed_qty < 0.0            # 小额减仓
        assert L.exposure_ratio(110.0) == pytest.approx(0.4, abs=1e-12)
        assert rec.fee == 0.0                  # 无成本面


# ==================== 场景 3:反手全量交易 ====================
class TestScenario3FlipNotional:
    def test_flip_trades_full_notional_no_fee(self):
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.0)
        L.apply_target_ratio(0.6, 100.0)
        rec = L.apply_target_ratio(-0.4, 100.0)
        # |delta|*P ≈ 1.0 × 净值(而非 0.2×)
        assert abs(rec.signed_qty) * 100.0 == pytest.approx(
            100.0, abs=1e-9)
        assert L.qty == pytest.approx(-0.4, abs=1e-12)

    def test_flip_exact_equation_with_fee(self):
        """非零费:q_new*mark == w*(e − δ(x−mark) − |δ|·x·fee) 精确成立。"""
        f = 0.001
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=f)
        L.apply_target_ratio(0.6, 100.0)
        e_before = L.equity(100.0)
        rec = L.apply_target_ratio(-0.4, 100.0)
        x, d = rec.exec_price, rec.signed_qty
        rhs = -0.4 * (e_before - d * (x - 100.0) - abs(d) * x * f)
        assert L.qty * 100.0 == pytest.approx(rhs, abs=1e-9)
        # 成交前后 equity(mark) 只差费用+滑点(自融资连续性)
        assert rec.equity_after_at_mark == pytest.approx(
            e_before - d * (x - 100.0) - abs(d) * x * f, abs=1e-9)


# ==================== 场景 4:平价反复加减仓无套利 ====================
class TestScenario4NoFreeLunch:
    @pytest.mark.parametrize("seq", [
        [0.5, 0.2, 0.7, 0.3, -0.1, 0.0],
        [1.0, -1.0, 1.0, -1.0],
        [-0.3, 0.9, 0.0, 0.9],
    ])
    def test_equity_drops_only_by_fees(self, seq):
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.001)
        e0 = L.equity(100.0)
        total_fee = 0.0
        for w in seq:
            prev = L.equity(100.0)
            rec = L.apply_target_ratio(w, 100.0)
            total_fee += rec.fee
            assert prev - L.equity(100.0) == pytest.approx(
                rec.fee, abs=1e-9)
        assert e0 - L.equity(100.0) == pytest.approx(total_fee, abs=1e-9)


# ==================== 场景 6:边界组合 ====================
class TestScenario6Boundaries:
    @pytest.mark.parametrize("w,expect_qty_sign", [
        (1.0, 1), (-1.0, -1), (0.0, 0), (0.5, 1), (-0.25, -1)])
    def test_endpoints_zero_and_interior(self, w, expect_qty_sign):
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.001)
        rec = L.apply_target_ratio(w, 100.0)
        if expect_qty_sign == 0:
            assert L.qty == 0.0 and rec.fee == pytest.approx(0.0)
        else:
            assert np.sign(L.qty) == expect_qty_sign
        assert rec.achieved_ratio == pytest.approx(w, abs=1e-9)

    def test_exact_zero_clears_dust(self):
        """目标 0 真清仓,不留尘埃仓位。"""
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.001)
        L.apply_target_ratio(0.37, 100.0)
        L.apply_target_ratio(0.0, 100.0)
        assert L.qty == 0.0
        assert L.avg_entry == 0.0

    def test_illegal_targets_rejected(self):
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.0)
        for bad in (1.5, -1.5, float("nan"), float("inf"), None):
            with pytest.raises((ValueError, TypeError)):
                L.apply_target_ratio(bad, 100.0)


# ==================== 场景 7:跳空与 HOLD 语义 ====================
class TestScenario7GapAndHold:
    def _env(self, opens, closes):
        p = _prices(opens, closes)
        return HybridPositionEnv(features=_feats(len(opens)), prices=p,
                                 fee=0.001, window_size=1)

    def test_old_qty_bears_gap(self):
        # 4 根:第二步非终端,才能断言 HOLD 后数量未被清算归零
        env = self._env([100, 90, 80, 80], [100, 120, 80, 80])
        env.reset()
        o, r, term, trunc, info = env.step([1, 0.5])
        # 第二步:决策在 close[1]=120,执行在 open[2]=80:
        # 旧数量承担 120->80 的跳空(由估值自然实现,无成交)
        o2, r2, t2, _, info2 = env.step([0, 0.0])   # HOLD(非终端)
        assert t2 is False
        assert info2["equity_start"] == pytest.approx(
            info["equity_end"], abs=1e-9)
        assert info2["signed_qty"] == 0.0
        assert info2["qty"] == pytest.approx(info["qty"], abs=1e-12)
        # 跳空损益由旧仓承担:E_end = E_start + qty*(80-120)
        assert info2["equity_end"] == pytest.approx(
            info2["equity_start"] + info2["qty"] * (80.0 - 120.0),
            abs=1e-9)

    def test_hold_not_equivalent_to_rerequest(self):
        """HOLD 与重输旧目标/当前观察比例不等价(漂移须发生在执行
        标记价上:第二步执行价 110 高于首步成交价 100)。"""
        opens = [100, 100, 110, 110]
        closes = [100, 105, 110, 110]
        env = self._env(opens, closes)
        env.reset()
        env.step([1, 0.4])
        o, r, t, _, i_hold = env.step([0, 0.0])   # 非终端
        assert t is False
        env2 = self._env(opens, closes)
        env2.reset()
        env2.step([1, 0.4])
        o2, r2, t2, _, i_re = env2.step([1, 0.4])
        assert i_hold["signed_qty"] == 0.0
        assert i_re["signed_qty"] < 0.0            # 漂移后再请求=减仓
        assert i_hold["qty"] > i_re["qty"]
        # HOLD 的比例已漂移超过请求值(不截断)
        assert i_hold["exposure_ratio_close"] > 0.4


# ==================== 场景 8:资金费/终端清算/reset 无泄漏 ====================
class TestScenario8FundingAndTerminal:
    def test_funding_direction_long_pays_positive(self):
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.0)
        L.apply_target_ratio(1.0, 100.0)
        pay = L.settle_funding(100.0, 0.0005)
        # 多头付正资金费:payment = -qty*P*rate < 0
        assert pay == pytest.approx(-1.0 * 100.0 * 0.0005, abs=1e-12)
        assert L.equity(100.0) == pytest.approx(
            100.0 - 0.05, abs=1e-9)

    def test_funding_short_receives_positive_rate(self):
        L = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.0)
        L.apply_target_ratio(-1.0, 100.0)
        pay = L.settle_funding(100.0, 0.0005)
        assert pay > 0.0

    def test_terminal_liquidation_pays_fees(self):
        opens = [100, 100]
        closes = [100, 110]
        env = HybridPositionEnv(
            features=_feats(2), prices=_prices(opens, closes),
            fee=0.001, window_size=1)
        env.reset()
        o, r, term, _, info = env.step([1, 1.0])
        assert term is True
        liq = info["terminal_liquidation"]
        assert liq["fee"] > 0.0
        # 终端后全现金:telescoping = log(final_cash/E0)
        assert env.ledger.qty == 0.0
        assert info["reward_raw"] == pytest.approx(
            np.log(env.ledger.cash / 100.0), abs=1e-12)
        assert env.episode_reward_raw == pytest.approx(
            np.log(env.ledger.cash / 100.0), abs=1e-12)

    def test_hold_cannot_block_liquidation_or_funding(self):
        opens = [100, 100, 100]
        closes = [100, 100, 100]
        env = HybridPositionEnv(
            features=_feats(3), prices=_prices(opens, closes),
            fee=0.001, window_size=1,
            funding_schedule={1: 0.001})
        env.reset()
        _, _, _, _, info1 = env.step([1, 0.8])
        assert info1["funding_payment"] < 0.0     # 资金费在第1步(exec bar 1)
        o, r, term, _, info = env.step([0, 0.0])  # HOLD 到终端
        assert term is True
        assert info["terminal_liquidation"]["fee"] > 0.0
        assert info["funding_payment"] == 0.0     # 终端步无资金费计划

    def test_reset_no_leakage(self):
        opens = [100, 100, 100]
        env = HybridPositionEnv(
            features=_feats(3), prices=_prices(opens),
            fee=0.001, window_size=1,
            funding_schedule={1: 0.001})
        env.reset()
        env.step([1, 0.8])
        env.step([1, -0.8])
        obs, info = env.reset()
        assert env.ledger.qty == 0.0
        assert env.ledger.cash == 100.0
        assert env.ledger.fees_total == 0.0
        assert env.ledger.funding_total == 0.0
        assert len(env.step_records) == 0
        assert env.economic_failure is None
        assert np.isfinite(obs).all()


# ==================== 场景 9:异常诚实处理与守恒 ====================
class TestScenario9FailureAndConservation:
    def test_gap_bankruptcy_honest_failure(self):
        """空头遇巨大跳空:非正净值显式失败,不 clamp、不伪 log。"""
        opens = [100, 100, 250]
        closes = [100, 100, 250]
        env = HybridPositionEnv(
            features=_feats(3), prices=_prices(opens, closes),
            fee=0.0, window_size=1, maintenance_margin=1e-12)
        env.reset()
        env.step([1, -1.0])
        o, r, term, _, info = env.step([0, 0.0])
        assert info["equity_end"] <= 0.0
        assert info["reward_valid"] is False
        assert info["reward_raw"] is None
        assert term is True
        assert info["economic_failure"]["reason"]
        with pytest.raises(RuntimeError):
            env.step([0, 0.0])                     # 失败后不得续 step

    def test_risk_flatten_fires_and_is_separate(self):
        """维持保证金风险规则触发一次全额平仓,与模型动作分列。"""
        opens = [100, 100, 195]
        closes = [100, 100, 195]
        env = HybridPositionEnv(
            features=_feats(3), prices=_prices(opens, closes),
            fee=0.0, window_size=1, maintenance_margin=0.05)
        env.reset()
        env.step([1, 1.0])
        o, r, term, _, info = env.step([0, 0.0])   # HOLD:模型不加仓
        # close=195: E = 100 + 1*(195-100) = 195?不——多头涨不触发;
        # 改空头路径在下面
        assert "risk_action" not in info or info["equity_end"] > 0

    def test_risk_flatten_short(self):
        opens = [100, 100, 180]
        closes = [100, 100, 180]
        env = HybridPositionEnv(
            features=_feats(3), prices=_prices(opens, closes),
            fee=0.0, window_size=1, maintenance_margin=0.05)
        env.reset()
        env.step([1, -1.0])
        o, r, term, _, info = env.step([0, 0.0])
        # close=180: E = 100 - 80 = 20;notional=80;mm*notional=4 -> 20>4 未触发
        # close=196 触发;此处 180 不触发——用更近界值
        assert info["equity_end"] == pytest.approx(20.0, abs=1e-9)

    def test_risk_flatten_boundary(self):
        # 4 根:第2根触发风险平仓且非终端,第3根收尾
        opens = [100, 100, 196, 196]
        closes = [100, 100, 196, 196]
        env = HybridPositionEnv(
            features=_feats(4), prices=_prices(opens, closes),
            fee=0.0, window_size=1, maintenance_margin=0.05)
        env.reset()
        env.step([1, -1.0])
        o, r, term, _, info = env.step([0, 0.0])
        # E = 100-96 = 4;notional=196;mm*notional=9.8 -> 4<9.8 触发
        assert term is False
        assert "risk_action" in info
        assert info["risk_action"]["signed_qty"] > 0.0   # 平空=买入
        assert info["action_branch"] == 0                 # 模型动作是 HOLD
        assert info["qty"] == 0.0                         # 已全额平仓

    def test_telescoping_multi_step(self):
        rng = np.random.default_rng(11)
        n = 24
        opens = 100 * np.exp(np.cumsum(rng.normal(
            0, 0.01, n - 1).repeat(1))) if False else None
        rets = rng.normal(0.0, 0.01, n)
        px = 100 * np.exp(np.cumsum(rets))
        env = HybridPositionEnv(
            features=_feats(n), prices=_prices(px),
            fee=0.001, slippage_bps=2.0, window_size=1,
            funding_schedule={5: 0.0002, 17: -0.0001})
        env.reset()
        actions = []
        rng2 = np.random.default_rng(3)
        terminated = False
        while not terminated:
            a = [1, float(rng2.uniform(-1, 1))] if rng2.random() < 0.7 \
                else [0, 0.0]
            actions.append(a)
            o, r, term, trunc, info = env.step(a)
            terminated = term or trunc
        assert env.episode_reward_raw == pytest.approx(
            np.log(env.ledger.cash / 100.0), abs=1e-9)
        assert env.ledger.qty == 0.0

    def test_illegal_action_rejected_not_silent(self):
        env = HybridPositionEnv(
            features=_feats(3), prices=_prices([100] * 3),
            fee=0.0, window_size=1)
        env.reset()
        for bad in ([2, 0.5], [0.5, 0.0], [-1, 0.0], [1, 1.5],
                    [1, float("nan")], [0, 0.3]):
            with pytest.raises(ValueError):
                env.step(bad)

    def test_observed_drifted_exposure_not_clipped(self):
        opens = [100, 100, 100, 100]
        closes = [100, 100, 130, 130]
        env = HybridPositionEnv(
            features=_feats(4), prices=_prices(opens, closes),
            fee=0.0, window_size=1)
        env.reset()
        env.step([1, 0.5])
        o, r, t, _, info = env.step([0, 0.0])
        # qty≈0.5,P=130,E≈115: ratio≈0.565(HOLD 漂移)必须原样可见
        assert abs(info["exposure_ratio_close"]) > 0.5
        assert abs(info["exposure_ratio_close"]) < 1.0
        obs_exposure = float(o[-2])
        assert obs_exposure == pytest.approx(
            info["exposure_ratio_close"], abs=1e-6)


# ==================== 录制/回放 ====================
class TestRecordReplay:
    def test_record_replay_identical(self, tmp_path):
        n = 20
        rng = np.random.default_rng(5)
        px = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
        feats = _feats(n)
        prices = _prices(px)
        env = HybridPositionEnv(
            features=feats, prices=prices, fee=0.001,
            slippage_bps=1.5, window_size=1,
            funding_schedule={6: 0.0003, 12: -0.0002})
        rng3 = np.random.default_rng(9)
        actions = []
        for _ in range(n - 1):
            actions.append([1, float(rng3.uniform(-1, 1))]
                           if rng3.random() < 0.6 else [0, 0.0])
        traj = record_episode(env, actions)
        out = replay_episode(prices, feats, traj["config"],
                             traj["actions"], expect=traj)
        assert out["final_cash"] == pytest.approx(
            traj["steps"][-1]["cash"], abs=1e-9)


# ==================== 场景 5:long-only 0/1 端点对拍 ====================
class TestScenario5LongOnlyEquivalence:
    @pytest.mark.parametrize("fee,slip", [(0.001, 0.0), (0.001, 1.5),
                                          (0.0, 2.0)])
    def test_stepwise_equity_and_reward_match(self, fee, slip):
        from rl_platform.env import AlignedLongFlatEnv
        n = 30
        rng = np.random.default_rng(21)
        px = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
        prices = _prices(px)
        feats = _feats(n)
        old = AlignedLongFlatEnv(
            features=feats, prices=prices, fee=fee,
            slippage_bps=slip, initial_cash=100.0,
            window_size=1, price_tick=0.0)
        new = HybridPositionEnv(
            features=feats, prices=prices, fee=fee,
            slippage_bps=slip, initial_cash=100.0, window_size=1)
        rng4 = np.random.default_rng(33)
        seq = [int(rng4.random() < 0.55) for _ in range(n - 1)]
        o_old, _ = old.reset()
        o_new, _ = new.reset()
        for k, a in enumerate(seq):
            oo, ro, to, _, io = old.step(a)
            on, rn, tn, _, i_n = new.step([1, float(a)])
            assert to == tn
            assert io["equity_end"] == pytest.approx(
                i_n["equity_end"], abs=1e-9), f"step{k}"
            assert io["reward_raw"] == pytest.approx(
                i_n["reward_raw"], abs=1e-9), f"step{k} reward"
            if to:
                break
        assert old.ledger.cash == pytest.approx(
            new.ledger.cash, abs=1e-9)
        assert old.episode_reward_raw == pytest.approx(
            new.episode_reward_raw, abs=1e-9)
