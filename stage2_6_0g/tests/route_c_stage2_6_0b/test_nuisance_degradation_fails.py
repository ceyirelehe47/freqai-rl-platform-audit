"""工作包 D:nuisance 变化后系统性恶化 -> FAIL(2.6.0a 只查改善的漏洞)。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.counterfactual import (
    NuisanceEquivalenceSpec,
    test_nuisance_slot_injection,
)
from rl_curriculum.policy_api import ObservableBaselinePolicy


class CollapseOnTailPolicy(ObservableBaselinePolicy):
    """病态策略:nuisance_0 处于原始分布的常见区间时正常跟随趋势,
    进入变体分布的常见区间(|z|>0.8,原始均匀分布下只占 10%)时
    反向做空(Long/Flat 合同下 = 满仓逆势)。

    下行市场中:原始(少触发)基本跟随规则收益;注入变体后大量
    触发逆势持仓 => 系统性恶化。
    """

    name = "collapse_on_tail"

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        n0 = float(observation[self.slot("nuisance_0")])
        if abs(n0) > 0.8:
            return 1 - int(self.read(observation, "ret_4") > 0)  # 逆势
        return int(self.read(observation, "ret_4") > 0)  # 正常跟随


@pytest.fixture(scope="module")
def downward_episodes():
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator

    gen = ProbeSegmentedDriftGenerator()
    params = {"episode_bars": 96,
              "regimes": [[-1, 40.0, 48], [-1, 30.0, 48]],
              "drift_bps_range": [30.0, 45.0]}
    return [gen.generate(dict(params), s, split="param_extrapolation",
                         timeframe="15m") for s in (301, 302, 303)]


def test_systematic_degradation_fails(downward_episodes, schema, cfg):
    spec = NuisanceEquivalenceSpec(delta_return=0.0005, n_transform_seeds=3,
                                   bootstrap_iters=400)
    r = test_nuisance_slot_injection(
        CollapseOnTailPolicy(), downward_episodes, cfg, schema, spec=spec)
    assert not r.pass_, f"恶化漏洞:nuisance 崩溃仍通过: {r.reason}"
    boot = r.extra["paired_bootstrap"]
    # 收益差系统性为负(CI low < -δ)或行为崩溃,二者必居其一
    assert (boot["ci_low"] < -spec.delta_return
            or r.action_match_rate < spec.action_match_min)
    assert ("degradation" in r.extra["failure_modes"]
            or "dependency" in r.extra["failure_modes"])


def test_degradation_and_dependency_both_recorded(downward_episodes, schema,
                                                  cfg):
    spec = NuisanceEquivalenceSpec(n_transform_seeds=2, bootstrap_iters=300)
    r = test_nuisance_slot_injection(
        CollapseOnTailPolicy(), downward_episodes, cfg, schema, spec=spec)
    assert not r.pass_
    assert r.extra["median_turnover_diff"] is not None
    assert r.extra["n_pairs"] == len(downward_episodes) * 2
