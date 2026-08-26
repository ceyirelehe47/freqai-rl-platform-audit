"""工作包 C:策略 Episode 生命周期(跨 Episode 状态清零)。"""

from __future__ import annotations

import numpy as np

from rl_curriculum.evaluator import derive_episode_seed, run_observation_episode
from rl_curriculum.policies import PeriodicTogglePolicy
from rl_curriculum.policy_api import CandidatePolicy
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


class _StatefulCandidate(CandidatePolicy):
    """带内部计数器的候选:reset 必须清零,否则跨 Episode 泄漏。"""

    name = "stateful"

    def __init__(self):
        self.counter = 0
        self.resets = 0

    def reset_episode(self, derived_seed: int) -> None:
        self.counter = 0
        self.resets += 1

    def act(self, observation: np.ndarray) -> int:
        self.counter += 1
        return int(self.counter <= 5)  # 每 Episode 前 5 步做多


def test_reset_called_per_episode(gen_a, cfg, schema):
    eps = [gen_a.generate(dict(TRAIN_PARAMS), seed=s, timeframe="15m")
           for s in (41, 42, 43)]
    cand = _StatefulCandidate()
    for ep in eps:
        run_observation_episode(cand, ep, cfg, schema)
    assert cand.resets == 3
    assert cand.counter == len(eps[0].df) - 1  # 只累计最后一个 Episode


def test_stateful_actions_independent_of_previous_episodes(gen_a, cfg, schema):
    """同一 Episode 的动作不因"之前跑过别的 Episode"而变化。"""
    ep_target = gen_a.generate(dict(TRAIN_PARAMS), seed=45, timeframe="15m")
    ep_other = gen_a.generate(dict(TRAIN_PARAMS), seed=46, timeframe="15m")
    fresh = _StatefulCandidate()
    r_fresh, a_fresh, _ = run_observation_episode(
        fresh, ep_target, cfg, schema, return_actions=True)
    reused = _StatefulCandidate()
    run_observation_episode(reused, ep_other, cfg, schema)
    r_reuse, a_reuse, _ = run_observation_episode(
        reused, ep_target, cfg, schema, return_actions=True)
    assert a_fresh == a_reuse
    assert r_fresh.actions_sha256 == r_reuse.actions_sha256


def test_periodic_toggle_reset_between_episodes(gen_a, cfg, schema):
    """周期基线的计数器在 Episode 间清零(动作序列可重复)。"""
    eps = [gen_a.generate(dict(TRAIN_PARAMS), seed=s, timeframe="15m")
           for s in (47, 48)]
    pol = PeriodicTogglePolicy(8)
    r0, a0, _ = run_observation_episode(pol, eps[0], cfg, schema,
                                        return_actions=True)
    r1, a1, _ = run_observation_episode(pol, eps[1], cfg, schema,
                                        return_actions=True)
    again = PeriodicTogglePolicy(8)
    r1b, a1b, _ = run_observation_episode(again, eps[1], cfg, schema,
                                          return_actions=True)
    assert a1 == a1b  # 相同 spec + 新实例 = 同动作
    assert pol._step == len(eps[1].df) - 1  # 计数器只反映当前 Episode


def test_derived_seed_order_independent(gen_a):
    """derived_seed 由 spec 规范化哈希派生,与 Episode 输入顺序无关。"""
    eps = [gen_a.generate(dict(TRAIN_PARAMS), seed=s, timeframe="15m")
           for s in (49, 50, 51)]
    seeds = [derive_episode_seed(e.spec) for e in eps]
    seeds_rev = [derive_episode_seed(e.spec) for e in reversed(eps)]
    assert list(reversed(seeds)) == seeds_rev
    assert len(set(seeds)) == 3  # 不同 spec 派生不同种子
