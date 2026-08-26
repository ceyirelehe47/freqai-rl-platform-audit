"""工作包 A:候选无法读取 hidden(接口层不存在该路径)。"""

from __future__ import annotations

import numpy as np

from rl_curriculum.evaluator import (
    EvaluationError,
    run_observation_episode,
    run_policy_episode,
)
from rl_curriculum.policy_api import CandidatePolicy
from rl_curriculum.probes import OracleLikeHiddenReaderProbe
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


class _HiddenHuntingCandidate(CandidatePolicy):
    """恶意候选:尝试从各种渠道获取 hidden(必须全部失败)。"""

    name = "hidden_hunter"

    def __init__(self):
        self.found: list[str] = []

    def reset_episode(self, derived_seed: int) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        import sys

        frame = sys._getframe().f_back  # 评估循环栈帧
        if frame is not None:
            for key in frame.f_locals:
                # hidden/future_returns 对象绝不允许出现在正式评估
                # 循环的任何栈帧(评估器自身持有 episode 引用属正常,
                # 该通道由子进程候选隔离覆盖,见 subprocess 测试)
                if key in ("hidden", "future_returns"):
                    self.found.append(key)
        # 尝试全局注册表
        for m in ("rl_curriculum.evaluator",):
            mod = sys.modules.get(m)
            if mod is not None and hasattr(mod, "CURRENT_HIDDEN"):
                self.found.append("module-global")
        return 0


def test_candidate_cannot_reach_hidden(gen_a, cfg, schema):
    """正式路径运行后,恶意候选未能捕获任何 episode/hidden 引用。"""
    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=3, split="train",
                        timeframe="15m")
    hunter = _HiddenHuntingCandidate()
    run_observation_episode(hunter, ep, cfg, schema)
    assert hunter.found == [], f"候选捕获了隐藏数据通道: {hunter.found}"


def test_hidden_only_exists_in_oracle_and_probe_paths(gen_a, cfg, schema):
    """hidden 只进入 Oracle 上下文与测试探针 harness,两者均非候选接口。"""
    from rl_curriculum.policy_api import FormalPolicyRejected, assert_formal_candidate
    from rl_curriculum.policies import OracleSegmentedDriftPolicy

    oracle = OracleSegmentedDriftPolicy()
    assert oracle.reads_hidden is True
    try:
        assert_formal_candidate(oracle)
        raise AssertionError("reads_hidden 的 Oracle 不得进入候选接口")
    except FormalPolicyRejected:
        pass
    probe = OracleLikeHiddenReaderProbe()
    try:
        assert_formal_candidate(probe)
        raise AssertionError("读 hidden 的探针不得进入候选接口")
    except FormalPolicyRejected:
        pass


def test_probe_can_read_hidden_only_in_test_harness(gen_a, cfg, schema):
    """读隐藏的探针在测试 harness 中正常运行(证明审计能力保留),
    但该 harness 与正式评估路径物理分离。"""
    from rl_curriculum.evaluator import run_test_probe_episode

    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=4, split="train",
                        timeframe="15m")
    probe = OracleLikeHiddenReaderProbe()
    result = run_test_probe_episode(probe, ep, cfg, schema)
    assert probe.reads == "hidden-ok"  # 确实读到了(仅测试路径)
    assert np.isfinite(result.net_return)


def test_candidate_dispatch_rejects_harness_objects(gen_a, cfg, schema):
    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=5, split="train",
                        timeframe="15m")
    try:
        run_policy_episode("bogus", ep, cfg, schema)
        raise AssertionError("未知类型必须被调度器拒绝")
    except EvaluationError:
        pass
