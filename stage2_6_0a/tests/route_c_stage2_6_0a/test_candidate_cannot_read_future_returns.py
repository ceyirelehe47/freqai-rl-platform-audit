"""工作包 A:候选无法读取 future_returns(正式路径不构造该数组)。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.evaluator import run_observation_episode
from rl_curriculum.policy_api import CandidatePolicy
from rl_curriculum.probes import FutureLeakProbe
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


class _FutureHuntingCandidate(CandidatePolicy):
    """恶意候选:扫描评估循环栈帧寻找 future_returns(必须失败)。"""

    name = "future_hunter"

    def __init__(self):
        self.found: list[str] = []

    def reset_episode(self, derived_seed: int) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        import sys

        frame = sys._getframe().f_back
        while frame is not None:
            for key in frame.f_locals:
                if key == "future_returns":
                    self.found.append(key)
            frame = frame.f_back
        return 0


def test_formal_path_never_constructs_future_returns(gen_a, cfg, schema):
    """正式评估路径的完整调用栈中不存在 future_returns 局部名。"""
    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=6, split="train",
                        timeframe="15m")
    hunter = _FutureHuntingCandidate()
    run_observation_episode(hunter, ep, cfg, schema)
    assert hunter.found == [], (
        f"正式候选路径出现了 future_returns: {hunter.found}")


def test_future_returns_only_in_test_harness(gen_a, cfg, schema):
    """future_returns 只在 run_test_probe_episode 内构造(供泄漏探针);
    FutureLeakProbe 在正式路径下无法获得它。"""
    from rl_curriculum.evaluator import run_test_probe_episode
    from rl_curriculum.policy_api import FormalPolicyRejected, assert_formal_candidate

    probe = FutureLeakProbe()
    try:
        assert_formal_candidate(probe)
        raise AssertionError("FutureLeakProbe 必须被正式入口拒绝")
    except FormalPolicyRejected:
        pass
    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=7, split="train",
                        timeframe="15m")
    result = run_test_probe_episode(probe, ep, cfg, schema)
    assert np.isfinite(result.net_return)  # harness 中可运行


def test_candidate_env_observation_has_no_future_window():
    """冻结环境的观察只含历史窗口 + 仓位(env 合同)。"""
    import pandas as pd

    from rl_platform.env import AlignedLongFlatEnv

    rng = np.random.default_rng(9)
    n = 32
    close = 100.0 * np.cumprod(1 + rng.normal(0, 0.003, n))
    open_ = np.concatenate([[100.0], close[:-1]])
    env = AlignedLongFlatEnv(
        features=pd.DataFrame({"f0": rng.normal(0, 1, n)}),
        prices=pd.DataFrame({"open": open_, "close": close}), window_size=1)
    obs, _ = env.reset(seed=0)
    assert obs.shape == (2,)
    obs2, _, _, _, _ = env.step(1)
    assert obs2.shape == (2,)
    with pytest.raises(ValueError):
        env.step(2)  # 非法动作 fail closed
