"""工作包 D3:故意读取 nuisance 的策略必须 FAIL(依赖 = 行为不稳定)。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.counterfactual import (
    NuisanceEquivalenceSpec,
    test_nuisance_slot_injection,
)
from rl_curriculum.policy_api import ObservableBaselinePolicy


class NuisanceReaderPolicy(ObservableBaselinePolicy):
    """故意依赖 nuisance_0 槽位做决策(病态依赖)。"""

    name = "nuisance_reader"

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        idx = self.slot("nuisance_0")
        return int(float(observation[idx]) > 0.25)


@pytest.fixture(scope="module")
def ext_episodes():
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator

    gen = ProbeSegmentedDriftGenerator()
    params = {"episode_bars": 96, "drift_bps_range": [30.0, 45.0],
              "vol_bps_range": [32.0, 50.0]}
    return [gen.generate(dict(params), s, split="param_extrapolation",
                         timeframe="15m") for s in (301, 302)]


def test_nuisance_dependency_fails(ext_episodes, schema, cfg):
    spec = NuisanceEquivalenceSpec(n_transform_seeds=3, bootstrap_iters=400)
    r = test_nuisance_slot_injection(
        NuisanceReaderPolicy(), ext_episodes, cfg, schema, spec=spec)
    assert not r.pass_
    assert "dependency" in r.extra["failure_modes"]
    assert r.action_match_rate < spec.action_match_min
    # 行为指纹证据:动作一致率逐变换记录
    assert len(r.extra["action_match_rates"]) == len(ext_episodes) * 3


def test_dependency_evidence_includes_divergence_positions(
        ext_episodes, schema, cfg):
    spec = NuisanceEquivalenceSpec(n_transform_seeds=2, bootstrap_iters=300)
    r = test_nuisance_slot_injection(
        NuisanceReaderPolicy(), ext_episodes, cfg, schema, spec=spec)
    assert r.first_divergence_step is not None
    assert r.reason.startswith("行为不稳定")
