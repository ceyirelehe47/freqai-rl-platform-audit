"""工作包 D:终端清算费用与模型换手/强制清算的指标分离。
阶段 2.6.0b 更新:reset_episode() 无参数(候选不接收 Episode 身份 token)。"""

from __future__ import annotations

import numpy as np

from rl_curriculum.evaluator import run_observation_episode
from rl_curriculum.policy_api import CandidatePolicy
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


class _BuyAndHoldCandidate(CandidatePolicy):
    """第 3 步起持续做多直到终端(由强制清算平仓)。"""

    name = "buy_and_hold"

    def reset_episode(self) -> None:
        self.step = 0

    def act(self, observation: np.ndarray) -> int:
        self.step += 1
        return int(self.step >= 3)


class _TradeTwiceCandidate(CandidatePolicy):
    """买->卖->买:2 次模型往返 + 终端强制平仓闭合第 3 次往返。"""

    name = "trade_twice"

    def reset_episode(self) -> None:
        self.step = 0

    def act(self, observation: np.ndarray) -> int:
        self.step += 1
        if self.step < 10:
            return 1
        if self.step < 20:
            return 0
        return 1


def _ep(gen_a, seed=71):
    return gen_a.generate(dict(TRAIN_PARAMS), seed=seed, timeframe="15m")


def test_terminal_fee_included_in_total_fees(gen_a, cfg, schema):
    """终端清算手续费进入 total_fees(阶段 2.6.0 漏记)。"""
    r = run_observation_episode(_BuyAndHoldCandidate(), _ep(gen_a), cfg,
                                schema)
    assert r.terminal_liquidation_fee > 0
    assert r.total_fees == r.total_execution_fees + r.terminal_liquidation_fee
    assert abs(r.total_fees - (
        r.total_execution_fees + r.terminal_liquidation_fee)) < 1e-15
    # reward telescoping 覆含全部费用(含清算)
    assert r.reward_consistency_ok


def test_flat_has_no_fees_and_no_liquidation(gen_a, cfg, schema):
    from rl_curriculum.policies import AlwaysFlatPolicy

    r = run_observation_episode(AlwaysFlatPolicy(), _ep(gen_a, 72), cfg,
                                schema)
    assert r.total_fees == 0.0
    assert r.terminal_liquidation_fee == 0.0
    assert r.policy_order_executions == 0
    assert r.forced_terminal_executions == 0
    assert r.round_trip_count == 0
    assert r.net_return == 0.0


def test_policy_vs_forced_executions_separated(gen_a, cfg, schema):
    r = run_observation_episode(_BuyAndHoldCandidate(), _ep(gen_a, 73), cfg,
                                schema)
    # 一次模型买入 + 一次终端强制卖出
    assert r.policy_order_executions == 1
    assert r.forced_terminal_executions == 1
    assert r.round_trip_count == 1
    assert r.policy_action_switches == 1  # 0->1 一次目标切换
    assert r.n_trades == 1  # n_trades 只计模型成交


def test_round_trips_counted_per_cycle(gen_a, cfg, schema):
    r = run_observation_episode(_TradeTwiceCandidate(), _ep(gen_a, 74), cfg,
                                schema)
    # buy->sell 完整往返 1 次;buy->终端强制平仓闭合第 2 次
    assert r.policy_order_executions == 3  # buy, sell, buy
    assert r.round_trip_count == 2
    assert r.forced_terminal_executions == 1


def test_fee_ledger_reconciliation(gen_a, cfg, schema):
    """费用指标与账本逐项对上:final_cash 与净值/费用一致。"""
    r = run_observation_episode(_TradeTwiceCandidate(), _ep(gen_a, 75), cfg,
                                schema)
    assert np.isclose(
        r.final_cash, cfg.initial_cash * (1.0 + r.net_return), rtol=1e-12)
    # 高换手策略的手续费显著非零且计入了净值
    assert r.total_fees > 0
    assert r.reward_abs_error < 1e-9


def test_turnover_reflects_model_switches_not_forced_close(gen_a, cfg,
                                                            schema):
    """换手率只统计模型目标切换,强制终端卖出不算模型换手。"""
    r = run_observation_episode(_BuyAndHoldCandidate(), _ep(gen_a, 76), cfg,
                                schema)
    n = r.n_decisions
    assert r.turnover_rate == r.policy_action_switches / n
    assert r.policy_action_switches == 1
