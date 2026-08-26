"""工作包 A3:Oracle 使用独立接口与独立上下文(无未来/无完整 df)。"""

from __future__ import annotations

import inspect

import numpy as np

from rl_curriculum.evaluator import run_oracle_episode
from rl_curriculum.policy_api import OracleActContext, OraclePolicy
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


class _SpyOracle(OraclePolicy):
    name = "spy_oracle"

    def __init__(self):
        self.contexts: list[OracleActContext] = []

    def reset_episode(self, derived_seed: int) -> None:
        return None

    def act(self, ctx: OracleActContext) -> int:
        self.contexts.append(ctx)
        return 0


def test_oracle_context_slots_exclude_future():
    """OracleActContext 槽位只有 tick/position/隐藏行;无 df/未来。"""
    ctx = OracleActContext(tick=5, position=1,
                           hidden_row={"regime_direction": 1.0})
    assert set(getattr(ctx, "__slots__", ("tick", "position"))) <= {
        "tick", "position", "_hidden_row"}
    row = ctx.hidden_row
    assert row == {"regime_direction": 1.0}
    row["tamper"] = 1  # 返回副本:篡改不影响内部状态
    assert "tamper" not in ctx.hidden_row


def test_oracle_act_signature_uses_oracle_context():
    sig = inspect.signature(OraclePolicy.act)
    params = [p.name for p in sig.parameters.values() if p.name != "self"]
    assert params == ["ctx"]


def test_oracle_path_provides_current_row_only(gen_a, cfg, schema):
    """每步只收到当前行隐藏状态(标量 dict),不是完整 hidden DataFrame。"""
    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=2, split="train",
                        timeframe="15m")
    spy = _SpyOracle()
    run_oracle_episode(spy, ep, cfg, schema)
    assert spy.contexts
    for ctx in spy.contexts:
        assert isinstance(ctx.hidden_row, dict)
        assert all(isinstance(v, float) for v in ctx.hidden_row.values())
        # 只有探针 A 的隐藏列(当前行),无 bars_to_regime_end 之外的帧
        assert set(ctx.hidden_row) == set(ep.hidden.columns)
        # 无 DataFrame/ndarray 形式的未来数据
        assert not any(
            isinstance(v, (np.ndarray,)) for v in ctx.hidden_row.values())


def test_oracle_is_not_a_candidate_interface():
    """Oracle 不是 ObservationOnlyPolicy:能力层互不继承;
    正式候选入口(assert_formal_candidate)对 Oracle 拒绝。"""
    from rl_curriculum.policy_api import (
        ObservationOnlyPolicy,
        FormalPolicyRejected,
        assert_formal_candidate,
    )

    assert not issubclass(OraclePolicy, ObservationOnlyPolicy)
    try:
        assert_formal_candidate(_SpyOracle())
        raise AssertionError("Oracle 不得进入正式候选接口")
    except FormalPolicyRejected:
        pass
