# -*- coding: utf-8 -*-
"""C1–C4 双向课程:合成生成器、可观察参考与失败对照
(RouteC_PositionControl W3,PosctlC4Curriculum-v1 / C123Adapter-v1)。

全部为独立新工程域(PosctlEngBanks-v1 语料),不改旧 rl_curriculum
family/version 语义;双向(可做空)语义登记为新版本。

信号模型(因果,参数已知 -> 参考可离线精确计算):
- bar t 的可观察特征:s[t]∈{−1,0,+1}(方向信号)/c[t]∈{0,1}
  (上下文门)/q[t]∈[0,1](机会质量)/g[t]∈{0,1}(波动 regime);
- 下一根收益 r[t+1] = μ_eff(s,c,q) + σ(g)·ε,ε~N(0,1) iid;
  μ_eff = s·c·μ_max·q(C2 门控:C1 取 c≡1;C3 用小 μ 对比费用;
  C4 用连续 q 与双 regime);
- 特征不包含任何未来收益/真实标签/episode id/seed;账户状态由
  环境观察通道(exposure/solvency)提供。

参考策略(全部只依赖当时可观察状态;对已知参数做数值积分,
不抽样未来):
- kelly_w(mu, sigma):maximize E[log(1+w·r)](Gauss-Hermite 数值
  积分,w∈[−1,1] 网格 + 黄金分割细化)——期望对数增长最优的
  myopic 敞口;
- C1/C2 参考:REBALANCE(clip(kelly_w(μ_eff,σ),−1,1));μ_eff=0
  时 REBALANCE(0)(清仓),非 HOLD(无仓位漂移歧义);
- C3 参考:若 round-trip 期望费用拖累 ≥ 期望优势(解析比较
  2·fee·|w*| 与 μ_eff·w* 的期望增长增量),则 REBALANCE(0) 或
  HOLD(见 kelly_with_cost);
- C4 D0–D3 参考:对已知 (q,g) 状态网格 + 费用的一步价值函数
  V(w|r) 的动态解(小网格 value iteration;D3 的 HOLD=保持当前 w
  作为动作参与 argmax,使其与再平衡直接比较)。

课程有效性验收(在看任何学习结果之前,由测试固定):
- 存在状态使内部仓位期望增长严格优于 0 与 ±1(C4 核心);
- 存在状态使 HOLD 优于小幅再平衡(费用主导);
- 存在状态使调整优于 HOLD(机会变化主导);
- C1 空头边真实(镜像质量配对);C2 同信号跨上下文最优动作
  不同;C3 参考跳过低于费用的边际。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# Gauss-Hermite 节点(probabilists' He_n,64 阶):
# E[f(ε)] = Σ wᵢ·f(xᵢ)/√(2π),ε~N(0,1)
_GH_X, _GH_W = np.polynomial.hermite_e.hermegauss(64)
_GH_EPS = _GH_X
_GH_WT = _GH_W / math.sqrt(2.0 * math.pi)


def expected_log_growth(w: float, mu: float, sigma: float) -> float:
    """E[log(1 + w·r)],r=mu+sigma·ε,64 阶 Gauss-Hermite 数值积分。

    1+w·r <= 0 的质量为 0(本工程参数域内 |w·r| << 1);若出现
    非正参数样本,如实返回 −inf(不 clamp)。
    """
    r = mu + sigma * _GH_EPS
    body = 1.0 + w * r
    if np.any(body <= 0.0):
        return -math.inf
    return float(np.dot(_GH_WT, np.log(body)))


def kelly_w(mu: float, sigma: float, *, n_grid: int = 81,
            refine: int = 3) -> float:
    """argmax_{w∈[−1,1]} E[log(1+w·r)](网格+逐层黄金分割细化)。"""
    lo, hi = -1.0, 1.0
    best_w, best_v = 0.0, expected_log_growth(0.0, mu, sigma)
    grid = np.linspace(lo, hi, n_grid)
    for w in grid:
        v = expected_log_growth(float(w), mu, sigma)
        if v > best_v:
            best_v, best_w = v, float(w)
    span = 2.0 / (n_grid - 1)
    for _ in range(refine):
        cands = np.linspace(max(lo, best_w - span), min(
            hi, best_w + span), 21)
        for w in cands:
            v = expected_log_growth(float(w), mu, sigma)
            if v > best_v:
                best_v, best_w = v, float(w)
        span *= 0.1
    return best_w


# ============================== 课程规格 ==============================
@dataclass(frozen=True)
class CourseSpec:
    course: str                     # "c1" | "c2" | "c3" | "c4d0..d3"
    horizon: int = 64
    mu_max: float = 0.003           # 单根最大条件漂移
    sigma_lo: float = 0.10          # 低波动 regime σ(工程合成参数)
    sigma_hi: float = 0.20          # 高波动 regime σ(C4 D1 风险敏感)
    fee: float = 0.001
    slippage_bps: float = 0.0
    initial_cash: float = 100.0
    hold_p: float = 0.5             # 信号保持概率(状态马尔可夫)
    signal_switch_p: float = 0.25   # 信号切换概率
    noise_signal_p: float = 0.20    # 质量噪声扰动概率(D3 短暂噪声)
    seed: int = 0


# ============================== 生成器 ==============================
def generate_episode(spec: CourseSpec, seed: int):
    """一个训练 episode:返回 (prices, features, hidden)。

    prices/features 因果对齐;hidden 仅用于生成诊断与课程有效性
   检查(不进入特征)。
    """
    rng = np.random.default_rng((spec.seed, seed))
    n = spec.horizon + 1           # 决策 bar 0..n-2,执行至 n-1
    # 信号/上下文/质量/regime 马尔可夫链
    s = np.zeros(n, dtype=np.int64)
    c = np.zeros(n, dtype=np.int64)
    q = np.zeros(n)
    g = np.zeros(n, dtype=np.int64)
    s[0] = rng.choice([-1, 0, 1])
    c[0] = rng.integers(0, 2)
    g[0] = rng.integers(0, 2)
    q[0] = rng.random()
    for t in range(1, n):
        if rng.random() < spec.signal_switch_p:
            s[t] = rng.choice([-1, 0, 1])
        else:
            s[t] = s[t - 1]
        if rng.random() < spec.hold_p:
            c[t] = c[t - 1]
        else:
            c[t] = rng.integers(0, 2)
        if rng.random() < spec.hold_p:
            g[t] = g[t - 1]
        else:
            g[t] = rng.integers(0, 2)
        if rng.random() < spec.noise_signal_p:
            q[t] = rng.random()      # 短暂噪声(D3)
        else:
            q[t] = q[t - 1]
    mu_eff = _mu_eff_of(spec, s, c, q)
    sigma = np.where(g == 1, spec.sigma_hi, spec.sigma_lo)
    # 因果对齐:bar k 的收益由决策 bar k−1 的可观察状态决定
    # (features[k−1] -> r[k]);bar 0 收益恒 0(种子 bar)。
    # r 为**算术**收益(与线性合约经济/参考 Kelly 数学一致:
    # equity 增长 = 1 + w·r;不混用对数收益引入 σ²/2 伪漂移)。
    r = np.zeros(n)
    r[1:] = mu_eff[:-1] + sigma[:-1] * rng.standard_normal(n - 1)
    if np.any(1.0 + r <= 0.0):
        raise RuntimeError("合成算术收益越界(价格非正;结构非法,"
                           "按结构重试另取 seed,不按 PnL 拒收)")
    close = 100.0 * np.cumprod(1.0 + r)
    open_ = np.empty_like(close)
    open_[0] = 100.0
    open_[1:] = close[:-1]          # open[t] = close[t-1](无隔夜跳空
                                    # 源;跳空由执行时序语义覆盖)
    import pandas as pd
    prices = pd.DataFrame({"open": open_, "close": close})
    feats = pd.DataFrame({
        "s": s.astype(float),
        "c": c.astype(float),
        "q": q,
        "g": g.astype(float),
        "q_step": np.round(q * 4) / 4.0,   # 粗粒化可观察质量
    })
    hidden = {"mu_eff": mu_eff, "sigma": sigma, "s": s, "c": c,
              "q": q, "g": g}
    return prices, feats, hidden


def _mu_eff_of(spec: CourseSpec, s, c, q) -> np.ndarray:
    if spec.course.startswith("c1"):
        return s * spec.mu_max            # c≡1 语义:C1 无门控
    if spec.course.startswith("c2"):
        return s * c * spec.mu_max
    if spec.course.startswith("c3"):
        return s * c * spec.mu_max * q * 0.5   # 弱边际 vs 费用
    return s * c * spec.mu_max * q        # C4 全量


# ============================== 参考策略 ==============================
def reference_action(spec: CourseSpec, feat_row, current_w: float):
    """可观察参考:(branch, w)。只读 feat_row(s/c/q_step/g)。"""
    s = int(round(float(feat_row["s"])))
    c = int(round(float(feat_row["c"])))
    q = float(feat_row["q_step"])
    g = int(round(float(feat_row["g"])))
    sigma = spec.sigma_hi if g == 1 else spec.sigma_lo
    if spec.course.startswith("c3"):
        return _c3_action(spec, s, c, q, sigma, current_w)
    if spec.course.startswith("c4"):
        return _c4_action(spec, s, c, q, sigma, current_w)
    mu = _mu_eff_of(spec, np.array([s]), np.array([c]),
                    np.array([q]))[0]
    if abs(mu) < 1e-12:
        return (1, 0.0)
    return (1, float(np.clip(kelly_w(mu, sigma), -1.0, 1.0)))


def _c3_action(spec, s, c, q, sigma, current_w):
    """成本敏感:弱边际不足以覆盖往返费用时清仓/保持,否则 Kelly。"""
    mu = s * c * spec.mu_max * q * 0.5
    if abs(mu) < 1e-12:
        return (1, 0.0)
    w_star = float(np.clip(kelly_w(mu, sigma), -1.0, 1.0))
    # 期望增长增量(相对不持仓)是否超过一次往返费用拖累
    gain = expected_log_growth(w_star, mu, sigma) - 0.0
    cost_drag = 2.0 * spec.fee * abs(w_star)
    if gain <= cost_drag:
        return (0, 0.0) if abs(current_w) < 1e-9 else (1, 0.0)
    return (1, w_star)


def _c4_action(spec, s, c, q, sigma, current_w):
    """C4 参考:D0–D3 共用一步价值比较(HOLD 是动作候选)。

    动作候选:REBALANCE(w*)/REBALANCE(0)/REBALANCE(±1)/
    HOLD(保持 current_w);对已知 (mu,sigma,fee) 用 Gauss-Hermite
    一步期望比较,费用只对实际发生的 |Δw| 征收。
    """
    mu = s * c * spec.mu_max * q
    cands = [(1, 0.0), (1, 1.0), (1, -1.0), (0, 0.0)]
    w_star = 0.0
    if abs(mu) > 1e-12:
        w_star = float(np.clip(kelly_w(mu, sigma), -1.0, 1.0))
        cands.append((1, w_star))
    best, best_v = cands[0], -math.inf
    for act in cands:
        w_after = current_w if act[0] == 0 else act[1]
        delta = abs(w_after - current_w)
        v = expected_log_growth(w_after, mu, sigma) - spec.fee * delta
        if v > best_v:
            best_v, best = v, act
    return best


# ============================== 基线/失败对照 ==============================
def baseline_policies():
    """最少对照族(返回 name -> fn(feat_row, current_w)->(branch,w))。"""
    def flat(row, w):
        return (1, 0.0)

    def long_half(row, w):
        return (1, 0.5)

    def short_half(row, w):
        return (1, -0.5)

    def long_full(row, w):
        return (1, 1.0)

    def short_full(row, w):
        return (1, -1.0)

    def binary_sign(row, w):
        s = int(round(float(row["s"])))
        return (1, float(np.clip(s, -1.0, 1.0)))

    def first_then_hold(row, w):
        if abs(w) < 1e-9 and int(round(float(row["s"]))) != 0:
            return (1, float(np.clip(
                int(round(float(row["s"]))), -1.0, 1.0)))
        return (0, 0.0)

    def always_retarget(row, w):
        s = int(round(float(row["s"])))
        return (1, 0.5 * float(np.clip(s, -1.0, 1.0)))

    def local_only(row, w):
        """只读局部信号,忽略上下文/质量/成本(C2/C3 失败对照)。"""
        s = int(round(float(row["s"])))
        return (1, float(np.clip(s, -1.0, 1.0)))

    return {
        "flat": flat, "long_half": long_half,
        "short_half": short_half, "long_full": long_full,
        "short_full": short_full, "binary_sign": binary_sign,
        "first_then_hold": first_then_hold,
        "always_retarget_half": always_retarget,
        "local_only": local_only,
    }
