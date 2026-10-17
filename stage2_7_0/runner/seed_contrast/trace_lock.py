# -*- coding: utf-8 -*-
"""trace_lock — 事前锁定的共同自然市场流(纯核数学,零策略输入)。

episode trace=(r 序列 + s/c/q/g 演化序列),由
random.Random(trace_base+episode_index) 确定生成;与任何策略
动作无关(A/B/基线见同一市场)。准备期零生成(仅规格);执行时
按本模块一次性生成 128 episode 并 SHA 锁定。
"""
import random

H = 32
MU = 0.0012
SIGMA = {0: 0.03, 1: 0.06}

KERNEL = {
    "s": ([-1, 0, 1], 0.78, 0.22, None),
    "c": ([0, 1], 0.75, 0.25, None),
    "q": ([0.0, 0.25, 0.5, 0.75, 1.0], 0.80, None,
          [0.125, 0.25, 0.25, 0.25, 0.125]),
    "g": ([0, 1], 0.80, 0.20, None)}


def episode_list():
    """64 H32(s±各32)+64 tail(s±各32)=128,次序固定。"""
    eps = []
    for rem in (32, 1):
        for s in (1, -1):
            for _ in range(32):
                eps.append({"remaining": rem, "s": s})
    return eps


def _draw_r(rng, s, c, q, g):
    mu_eff = s * c * q * MU
    u = rng.random() * 2.0 - 1.0
    return mu_eff + (3.0 ** 0.5) * SIGMA[g] * u


def _evolve(rng, comp, v):
    vals, hold, _res, fresh = KERNEL[comp]
    if fresh is not None:
        if rng.random() < hold:
            return v
        x = rng.random()
        acc = 0.0
        for fv, fp in zip(vals, fresh):
            acc += fp
            if x < acc:
                return fv
        return vals[-1]
    if rng.random() < hold:
        return v
    return vals[rng.randrange(len(vals))]


def make_trace(spec_ep, seed):
    """单 episode trace:决策点状态序列+结算 r 序列(均 t 前缀)。

    返回 {"remaining","s0","steps":[{"s","c","q","g","r"}...]}
    (r 为该决策步 close 结算收益;无策略输入)。
    """
    rng = random.Random(seed)
    s, c, q, g = spec_ep["s"], 1, 1.0, 0
    n = spec_ep["remaining"]
    steps = []
    for _ in range(n):
        r = _draw_r(rng, s, c, q, g)
        steps.append({"s": s, "c": c, "q": q, "g": g,
                      "r": r})
        s = _evolve(rng, "s", s)
        c = _evolve(rng, "c", c)
        q = _evolve(rng, "q", q)
        g = _evolve(rng, "g", g)
    return {"remaining": spec_ep["remaining"],
            "s0": spec_ep["s"], "steps": steps}


def build_all(trace_base):
    """执行期一次生成全部 128 trace(锁定文件内容)。"""
    return [make_trace(e, trace_base + i)
            for i, e in enumerate(episode_list())]
