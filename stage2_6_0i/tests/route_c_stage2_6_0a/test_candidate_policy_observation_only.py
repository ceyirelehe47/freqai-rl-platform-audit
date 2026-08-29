"""工作包 A1:正式候选策略只收 observation(接口与运行时双验证)。
阶段 2.6.0b 更新:reset_episode() 无参数——候选不再接收任何 Episode
身份 token(derived_seed),改为断言 reset 恰好被调用且无参。"""

from __future__ import annotations

import inspect

import numpy as np

from rl_curriculum.evaluator import run_observation_episode
from rl_curriculum.policy_api import (
    CandidatePolicy,
    FormalPolicyRejected,
    ObservableBaselinePolicy,
    assert_formal_candidate,
)
from rl_curriculum.probes import StepCounterCheaterProbe
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


class _SpyCandidate(CandidatePolicy):
    """记录每次 act 实际收到的参数(证明只有 observation)。"""

    name = "spy_candidate"

    def __init__(self):
        self.calls: list[tuple] = []
        self.reset_calls: list[tuple] = []  # 每次 reset 收到的实参名

    def reset_episode(self) -> None:
        frame = inspect.currentframe()
        args = frame.f_back.f_locals if frame and frame.f_back else {}
        self.reset_calls.append(tuple(args.keys()))

    def act(self, observation: np.ndarray) -> int:
        frame = inspect.currentframe()
        args = frame.f_back.f_locals if frame and frame.f_back else {}
        self.calls.append((type(observation).__name__, tuple(args.keys())))
        return 0


def test_candidate_act_signature_is_observation_only():
    """接口签名:act(self, observation),无 ctx/df/hidden 参数。"""
    sig = inspect.signature(CandidatePolicy.act)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    assert [p.name for p in params] == ["observation"], sig


def test_formal_path_passes_only_observation(gen_a, cfg, schema):
    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=1, split="train",
                        timeframe="15m")
    spy = _SpyCandidate()
    run_observation_episode(spy, ep, cfg, schema)
    assert spy.calls, "候选未被调用"
    for type_name, caller_locals in spy.calls:
        assert type_name == "ndarray"
        # 调用点局部无 df/hidden/future_returns/tick/n_rows
        for forbidden in ("df", "hidden", "future_returns", "ctx",
                          "n_rows", "split", "family"):
            assert forbidden not in caller_locals, (
                f"评估循环向候选暴露了 {forbidden}")
    # 每 Episode 恰好一次 reset(2.6.0b:无参数——候选不接收任何
    # Episode 身份 token/seed,派生种子只存在于基线通道)
    assert len(spy.reset_calls) == 1
    assert "derived_seed" not in spy.reset_calls[0]


def test_formal_guard_rejects_probes_and_foreign_objects():
    assert_formal_candidate(_SpyCandidate())  # 正式候选通过
    try:
        assert_formal_candidate(StepCounterCheaterProbe())
        raise AssertionError("探针必须被拒绝")
    except FormalPolicyRejected:
        pass
    for bad in (object(), lambda obs: 0, "not-a-policy"):
        try:
            assert_formal_candidate(bad)
            raise AssertionError("非策略对象必须被拒绝")
        except FormalPolicyRejected:
            pass


def test_baseline_reads_slots_not_df(gen_a, cfg, schema):
    """可观察基线从 observation 槽位读特征;未绑定 schema 即报错。"""
    from rl_curriculum.policies import RuleTrendPolicy

    rule = RuleTrendPolicy()
    try:
        rule.read(np.zeros(schema.observation_dim, dtype=np.float32),
                  "ma_ratio")
        raise AssertionError("未绑定 schema 时必须报错(无 df 后门)")
    except RuntimeError:
        pass
    rule.bind_observation_schema(schema)
    assert rule.slot("ma_ratio") == 4  # whitelist 序:ret_1/ret_4/ret_12/vol_24/ma_ratio
    assert rule.slot("ret_4") == 1
    assert rule.position_slot() == schema.observation_dim - 1
    assert issubclass(RuleTrendPolicy, ObservableBaselinePolicy)
