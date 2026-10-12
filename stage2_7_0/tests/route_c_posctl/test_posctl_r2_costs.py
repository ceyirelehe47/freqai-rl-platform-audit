# -*- coding: utf-8 -*-
"""R2-03 资金费现金流/净成本符号正反例(独立审查 F3)。

原反例:平价多头 0.5、单边费 .001、资金费率 .001:
fees=.099950025,资金费现金流 −.049975012(支出),净值损失
.149925037;旧 total_cost_all_in=fees+现金流=.049975012(把支出当
收入抵扣)。v2 修正:net_cost = 全部费用 − 资金费现金流;
多空 × 正负费率 × 空仓 × 全部成交腿对账;平价无滑点净值损失由
净成本独立复算;滑点口径显式(不与净值重复计)。
"""

import math

import numpy as np
import pandas as pd
import pytest

from rl_posctl.env import HybridPositionEnv
from rl_posctl.evalreport import summarize


def _feats(n):
    rng = np.random.default_rng(31)
    return pd.DataFrame(rng.normal(size=(n, 2)),
                        columns=["f0", "f1"])


def _run(w0, rate, fee=0.001, slippage_bps=0.0, extra_action=None):
    prices = pd.DataFrame({"open": [100.0, 100.0, 100.0],
                           "close": [100.0, 100.0, 100.0]})
    env = HybridPositionEnv(
        features=_feats(3), prices=prices, fee=fee,
        slippage_bps=slippage_bps, window_size=1,
        funding_schedule=({1: rate} if rate is not None else None))
    env.reset()
    acts = [([1.0, w0], ([0.0, 0.0] if extra_action is None
                         else extra_action))]
    out = []
    for a in acts:
        _o, _r, _t, _tr, info = env.step(a[0])
        _o, _r, _t, _tr, info2 = env.step(a[1])
        out.append((info, info2))
    return env, out


class TestFundingSignMatrix:
    @pytest.mark.parametrize("w0,rate,exp_fees,exp_cf,exp_net", [
        # reviewer 探针原值:多头付费(现金流<0 增成本)
        (0.5, 0.001, 0.099950025, -0.049975012, 0.149925037),
        # 空头收资金费(现金流>0 抵扣)
        (-0.5, 0.001, 0.099950025, 0.049975012, 0.049975012),
        # 负费率镜像:多头收/空头付
        (0.5, -0.001, 0.099950025, 0.049975012, 0.049975012),
        (-0.5, -0.001, 0.099950025, -0.049975012, 0.149925037),
    ])
    def test_parity_net_cost_recomputes_equity_loss(
            self, w0, rate, exp_fees, exp_cf, exp_net):
        """平价无滑点:净成本 = 费用 − 现金流,且**独立复算**净值
        损失(eq0 − final)逐位一致(旧口径把符号接反)。"""
        env, ((i1, i2),) = _run(w0, rate)
        s = summarize(env.step_records)
        assert s["total_fees"] == pytest.approx(exp_fees, rel=1e-6)
        assert s["funding_cashflow_total"] == pytest.approx(
            exp_cf, rel=1e-6)
        assert s["net_cost"] == pytest.approx(exp_net, rel=1e-6)
        eq_loss = s["initial_equity"] - s["final_equity"]
        assert eq_loss == pytest.approx(exp_net, abs=1e-9)
        assert s["reconciliation"]["fees_match"] is True
        assert s["reconciliation"]["funding_match"] is True

    def test_empty_position_no_funding_no_cost(self):
        env, ((i1, i2),) = _run(0.0, 0.001)
        s = summarize(env.step_records)
        assert s["funding_cashflow_total"] == 0.0
        assert s["net_cost"] == pytest.approx(0.0, abs=1e-12)

    def test_all_legs_counted_no_double_count(self):
        """模型腿 + 风险腿 + 终端腿 + 资金费全部计入并与账本累计
        对账;同量不重复计(净成本 = 分项和 − 现金流机械恒等)。"""
        # 空头 0.9,mm=0.9:bar2 开盘风险平仓腿 → 模型重开多 0.5
        # → 资金费(bar2 close)→ bar3 HOLD → 终端清算腿
        prices = pd.DataFrame({"open": [100.0, 100.0, 130.0, 130.0],
                               "close": [100.0, 100.0, 130.0, 130.0]})
        env = HybridPositionEnv(
            features=_feats(4), prices=prices, fee=0.001,
            window_size=1, maintenance_margin=0.9,
            funding_schedule={2: 0.001})
        env.reset()
        env.step([1.0, -0.9])         # 模型建仓腿(空)
        _o, _r, _t, _tr, info2 = env.step(
            [1.0, 0.5])   # 开盘风险平仓腿 + 模型重开腿
        env.step([0.0, 0.0])          # 终端清算腿
        s = summarize(env.step_records)
        assert info2["open_risk_triggered"] is True
        assert s["model_action_fees"] > 0.0
        assert s["risk_action_fees"] > 0.0
        assert s["terminal_liquidation_fees"] > 0.0
        assert s["funding_cashflow_total"] < 0.0       # 多头支付
        assert s["reconciliation"]["fees_match"] is True
        assert s["reconciliation"]["funding_match"] is True
        parts = (s["model_action_fees"] + s["risk_action_fees"]
                 + s["terminal_liquidation_fees"]
                 + s["extra_risk_fees"])
        assert parts == pytest.approx(s["total_fees"], rel=1e-12)
        assert s["net_cost"] == pytest.approx(
            parts - s["funding_cashflow_total"], rel=1e-12)

    def test_slippage_in_exec_price_not_double_counted(self):
        """滑点:费用按实际成交价(含不利滑点)计;净值损失 =
        净成本 + 滑点拖累(方向不利差价),口径分开不重复。"""
        env0, ((a1, a2),) = _run(0.5, 0.001, slippage_bps=0.0)
        s0 = summarize(env0.step_records)
        env1, ((b1, b2),) = _run(0.5, 0.001, slippage_bps=50.0)
        s1 = summarize(env1.step_records)
        eq_loss0 = s0["initial_equity"] - s0["final_equity"]
        eq_loss1 = s1["initial_equity"] - s1["final_equity"]
        # 净成本仍只含费用−现金流;滑点拖累(方向不利差价)体现在
        # 净值损失与净成本之差,且随滑点增大(不藏进费用也不重复计)
        assert eq_loss1 > s1["net_cost"]
        drag0 = eq_loss0 - s0["net_cost"]
        drag1 = eq_loss1 - s1["net_cost"]
        assert drag1 > drag0 > -1e-12
        assert s1["net_cost_definition"].startswith(
            "model_action_fees+risk_action_fees")

    def test_short_receiving_funding_can_have_negative_net_cost(self):
        """不伪造"成本必须非负":空头持续收资金费 > 费用时净成本
        为负(净收益),如实呈现。"""
        env, ((i1, i2),) = _run(-0.2, 0.05, fee=0.0)
        s = summarize(env.step_records)
        assert s["funding_cashflow_total"] > 0.0
        assert s["net_cost"] < 0.0
        eq_gain = s["final_equity"] - s["initial_equity"]
        assert eq_gain == pytest.approx(-s["net_cost"], abs=1e-9)
