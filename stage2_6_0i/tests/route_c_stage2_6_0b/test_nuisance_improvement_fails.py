"""工作包 D:nuisance 变化后系统性改善 -> FAIL(单边漏洞已修复)。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.counterfactual import (
    NuisanceEquivalenceSpec,
    test_nuisance_slot_injection,
)
from rl_curriculum.policy_api import ObservableBaselinePolicy


class TailExploitPolicy(ObservableBaselinePolicy):
    """病态策略:只在 nuisance_0 进入原始分布不可能出现的尾部时做多。

    原始 nuisance 为 counter-hash 均匀噪声 ∈ (-1, 1);注入变体为标准
    正态。策略以 nuisance_0 > 1.5 为入场条件:原始分布下永不触发
    (永远空仓,收益恒 0),注入后 ~6.7% 的 bar 做多——在上行外推
    市场中获得系统性正收益 => 等价检验必须以 improvement FAIL。
    """

    name = "tail_exploit"

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return int(float(observation[self.slot("nuisance_0")]) > 1.5)


@pytest.fixture(scope="module")
def upward_episodes():
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator

    gen = ProbeSegmentedDriftGenerator()
    params = {"episode_bars": 96,
              "regimes": [[1, 40.0, 48], [1, 30.0, 48]],
              "drift_bps_range": [30.0, 45.0]}
    return [gen.generate(dict(params), s, split="param_extrapolation",
                         timeframe="15m") for s in (301, 302, 303)]


def test_systematic_improvement_fails(upward_episodes, schema, cfg):
    spec = NuisanceEquivalenceSpec(delta_return=0.0005, n_transform_seeds=3,
                                   bootstrap_iters=400)
    r = test_nuisance_slot_injection(
        TailExploitPolicy(), upward_episodes, cfg, schema, spec=spec)
    assert not r.pass_, f"单边漏洞:显著改善仍通过: {r.reason}"
    assert "improvement" in r.extra["failure_modes"]
    boot = r.extra["paired_bootstrap"]
    assert boot["ci_high"] > spec.delta_return
    assert "系统性改善" in r.reason


class OrderSensitiveNuisancePolicy(ObservableBaselinePolicy):
    """依赖 nuisance 时序顺序的状态策略:置乱(保持边际)即崩溃。"""

    name = "order_sensitive_nuisance"

    def __init__(self):
        super().__init__()
        self._prev = None

    def reset_episode(self) -> None:
        self._prev = None

    def act(self, observation: np.ndarray) -> int:
        v = float(observation[self.slot("nuisance_0")])
        if self._prev is None:
            self._prev = v
            return 0
        rising = v > self._prev
        self._prev = v
        return int(rising)


def test_improvement_detected_in_shuffle_mode_too(upward_episodes, schema,
                                                  cfg):
    """置乱模式保持边际但破坏顺序:顺序敏感策略必须 FAIL。"""
    from rl_curriculum.counterfactual import test_nuisance_slot_shuffle

    spec = NuisanceEquivalenceSpec(n_transform_seeds=2, bootstrap_iters=300)
    r = test_nuisance_slot_shuffle(
        OrderSensitiveNuisancePolicy(), upward_episodes, cfg, schema,
        spec=spec)
    assert not r.pass_
    assert "dependency" in r.extra["failure_modes"]
