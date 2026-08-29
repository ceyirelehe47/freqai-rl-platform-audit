"""工作包 B:reset 无任何 Episode 身份 token(接口/worker 协议/行为)。"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from rl_curriculum.evaluator import (
    derive_episode_seed,
    run_observation_episode,
)
from rl_curriculum.generator_api import EpisodeSpec
from rl_curriculum.generators import ProbeSegmentedDriftGenerator
from rl_curriculum.policy_api import (
    CandidatePolicy,
    ObservableBaselinePolicy,
    ObservationOnlyPolicy,
)
from rl_curriculum.policies import RandomPolicy, RuleTrendPolicy


def test_candidate_reset_signature_has_no_parameters():
    sig = inspect.signature(ObservationOnlyPolicy.reset_episode)
    assert list(sig.parameters) == ["self"], (
        "reset_episode 必须无参数:任何 seed/hash/id 都会向候选泄漏"
        "稳定 Episode 身份 token")
    for cls in (CandidatePolicy, ObservableBaselinePolicy):
        assert list(inspect.signature(
            cls.reset_episode).parameters) == ["self"]


def test_worker_reset_message_is_byte_exact():
    """worker 协议 reset 消息逐字节 {"op": "reset"};携带任何身份字段
    (derived_seed/episode_id/seed/spec_hash)都被视为协议违规。"""
    from rl_candidate_runtime.worker import main as worker_main

    src = inspect.getsource(worker_main)
    assert "set(req.keys()) != {\"op\"}" in src
    assert "reset-identity-token" in src
    from rl_curriculum.candidate_worker import WORKER_PROTOCOL

    assert WORKER_PROTOCOL == "candidate-worker-v2"


def test_reset_message_wire_format_exact():
    from rl_curriculum.sandbox import SandboxedCandidate

    src = inspect.getsource(SandboxedCandidate.reset_episode)
    assert '{"op": "reset"}' in src or "{'op': 'reset'}" in src
    # SubprocessCandidate(旧实现)已删除,reset 消息不再有 derived_seed
    from rl_curriculum import candidate_worker

    assert not hasattr(candidate_worker, "SubprocessCandidate")


class _StatefulSpy(CandidatePolicy):
    name = "stateful_spy"
    seen_resets = 0
    received_args: list = []

    def reset_episode(self) -> None:
        type(self).seen_resets += 1
        type(self).received_args.append(None)
        self.state = 0

    def __init__(self):
        self.state = 0

    def act(self, observation: np.ndarray) -> int:
        self.state += 1
        return int(self.state % 2)


@pytest.fixture
def episodes():
    gen = ProbeSegmentedDriftGenerator()
    params = {"episode_bars": 96, "regimes": [[1, 20.0, 48], [0, 0.0, 48]]}
    specs = [EpisodeSpec("probe_segmented_drift", dict(params), s,
                         "train", "15m") for s in (11, 12)]
    return [gen.generate(dict(params), s, timeframe="15m")
            for s in (11, 12)]


def test_stateful_candidate_state_cleared_each_episode(
        episodes, schema, cfg):
    policy = _StatefulSpy()
    for ep in episodes:
        r = run_observation_episode(policy, ep, cfg, schema)
        assert r is not None
    assert _StatefulSpy.seen_resets == 2


def test_candidate_cannot_distinguish_identical_prefix_episodes(
        episodes, schema, cfg):
    """两个 observation 前缀完全相同但 EpisodeSpec 不同的题目,候选的
    前缀决策必须一致(候选无任何身份 token 可用于区分)。"""
    import pandas as pd

    e1, e2 = episodes
    # 构造 e2':与 e1 的 df/hidden 完全一致,但 spec(seed)不同
    spec2 = EpisodeSpec("probe_segmented_drift",
                        dict(e2.spec.params), seed=e2.spec.seed + 999,
                        split=e2.spec.split, timeframe=e2.spec.timeframe)
    from rl_curriculum.generator_api import GeneratedEpisode

    e2b = GeneratedEpisode(
        spec=spec2, df=e1.df.copy(), hidden=e1.hidden.copy(),
        family_version=e1.family_version, timeframe=e1.timeframe,
        is_null=e1.is_null, generator_fingerprint=e1.generator_fingerprint,
        meta=dict(e1.meta), declared_feature_columns=e1.declared_feature_columns)
    # 派生 seed 不同(身份 token 假设存在时会不同)
    assert derive_episode_seed(e1.spec) != derive_episode_seed(e2b.spec)
    spy = _StatefulSpy()
    r1 = run_observation_episode(spy, e1, cfg, schema,
                                 return_actions=True)[1]
    spy2 = _StatefulSpy()
    r2 = run_observation_episode(spy2, e2b, cfg, schema,
                                 return_actions=True)[1]
    assert r1 == r2, "相同 observation 前缀下候选行为不一致(存在身份通道)"


def test_random_baseline_determinism_via_episode_instance(episodes, schema,
                                                           cfg):
    """随机基线确定性由 episode_instance 工厂承载,不经过候选接口。"""
    template = RandomPolicy(seed=0)
    results = [
        run_observation_episode(template, ep, cfg, schema)
        for ep in episodes
    ]
    results_again = [
        run_observation_episode(template, ep, cfg, schema)
        for ep in reversed(episodes)
    ]
    by_seed = {(r.spec.seed, r.actions_sha256) for r in results}
    assert len(by_seed) == len(episodes)
    again = {(r.spec.seed, r.actions_sha256) for r in results_again}
    assert by_seed == again


def test_feedforward_and_rnn_style_reset_use_no_args():
    class RNNStyle(CandidatePolicy):
        name = "rnn_style"
        state: list = []

        def reset_episode(self) -> None:
            self.state = []

        def act(self, observation) -> int:
            self.state.append(float(observation[0]))
            return int(len(self.state) % 2)

    rnn = RNNStyle()
    rnn.act(np.zeros(9, dtype=np.float32))
    rnn.reset_episode()  # 无参数即可清零 RNN 状态
    assert rnn.state == []
