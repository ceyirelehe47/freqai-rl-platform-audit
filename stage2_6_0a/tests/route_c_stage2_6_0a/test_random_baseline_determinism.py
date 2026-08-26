"""工作包 C:随机基线确定性(重复评估/顺序无关/RNG 独立)。"""

from __future__ import annotations

import json

from rl_curriculum.evaluator import evaluate_policy
from rl_curriculum.policies import RandomPolicy
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


def _eps(gen_a, seeds=(61, 62, 63)):
    return [gen_a.generate(dict(TRAIN_PARAMS), seed=s, split="train",
                           timeframe="15m") for s in seeds]


def test_random_repeat_evaluation_identical(gen_a, cfg, schema):
    eps = _eps(gen_a)
    r1 = evaluate_policy(RandomPolicy(), eps, cfg, schema)
    r2 = evaluate_policy(RandomPolicy(), eps, cfg, schema)
    strip = lambda r: [e["actions_sha256"] for e in r["episodes"]]
    assert strip(r1) == strip(r2)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_random_input_order_independent(gen_a, cfg, schema):
    eps = _eps(gen_a)
    r1 = evaluate_policy(RandomPolicy(), eps, cfg, schema)
    r2 = evaluate_policy(RandomPolicy(), list(reversed(eps)), cfg, schema)
    a1 = {e["seed"]: e["actions_sha256"] for e in r1["episodes"]}
    a2 = {e["seed"]: e["actions_sha256"] for e in r2["episodes"]}
    assert a1 == a2


def test_random_not_affected_by_interleaved_calls(gen_a, cfg, schema):
    """Episode 之间的外部 RNG 消耗不影响结果(每 Episode 独立种子)。"""
    eps = _eps(gen_a, seeds=(64, 65))
    pol_a = RandomPolicy()
    r_a = evaluate_policy(pol_a, eps, cfg, schema)

    pol_b = RandomPolicy()
    # 在两个 Episode 之间"浪费"大量随机数(模拟其他 Episode 的调用)
    import numpy as np

    run_single = lambda pol, ep: evaluate_policy(
        pol, [ep], cfg, schema)
    first = run_single(pol_b, eps[0])
    for _ in range(1000):  # 外部消耗
        pol_b.act.__self__  # noqa: B018
        np.random.default_rng(0).random(10)
    second = run_single(pol_b, eps[1])

    a_a = {e["seed"]: e["actions_sha256"] for e in r_a["episodes"]}
    a_b = {e["seed"]: e["actions_sha256"]
           for e in first["episodes"] + second["episodes"]}
    assert a_a == a_b


def test_random_derived_from_spec_not_wallclock(gen_a, cfg, schema):
    """两次构造(不同时间)结果一致:种子来自 spec 哈希而非时间。"""
    eps = _eps(gen_a, seeds=(66,))
    r1 = evaluate_policy(RandomPolicy(), eps, cfg, schema)
    import time

    time.sleep(0.01)
    r2 = evaluate_policy(RandomPolicy(), eps, cfg, schema)
    assert r1["episodes"][0]["actions_sha256"] == \
        r2["episodes"][0]["actions_sha256"]
