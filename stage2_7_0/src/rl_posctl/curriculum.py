# -*- coding: utf-8 -*-
"""C1–C4 双向课程:合成生成器、可观察参考与失败对照
(RouteC_PositionControl W3,PosctlC4Curriculum-v2 / C123Adapter-v2,
R1 修复四档无差异与参考数学边界)。

全部为独立新工程域(PosctlEngBanks-v2 语料),不改旧 rl_curriculum
family/version 语义;v1(无界正态噪声 + 名义四档)结果只读归档。

R1 修复(P1):
- 噪声律:v1 把无界正态接到 log(1+w·r) 并以有限 Gauss-Hermite 节点
  声称非正净值概率为 0——数学上不成立。v2 改为**方差匹配有界均匀**:
  r = μ_eff + a·U, U~Unif(−1,1), a=√3·σ(与 v1 同 σ²)。支撑有限
  ⇒ E[log(1+w·r)] 有闭式精确解(gbar),|w|·(|μ|+a)<1 时有限,
  支撑内可破产时如实 −inf(经济失败定义明确,不靠积分节点回避)。
- C4 四档:v1 的 c4d0/d1/d2/d3 只差课程名,同 seed 逐位一致。v2
  每档 = 事前固定的不同参数集(信号/上下文/质量/regime 的保持率、
  σ 是否随 g 切换、μ_eff 结构),同 seed 下四档价格/特征/隐藏链
  全部不同(见 TIER_OVERRIDES;由测试固定)。
- 参考:v1 的一步 myopic 比较在训练面费用/边际比下退化为全清仓。
  v2 参考 = 可观察状态 MDP 的**精确动态规划**(后向归纳):状态
  (s,c,q,g) 马尔可夫链转移已知、每 bar 期望对数增长 gbar 闭式、
  动作 = HOLD 或 REBALANCE(w∈41 点网格)、费用 fee·|Δw|(滑点/
  tick=0 时与真实账本精确一致;非零时为披露近似,由 replay 对拍
  量化误差)。E[log Π(1+w_k r_k)] = Σ E[log(1+w_k r_k)] 逐步可加
  ⇒ DP 对"期望对数增长"准则精确(不虚称路径级最优)。

信号模型(因果,参数已知 → 参考可离线精确计算):
- 可观察特征:s∈{−1,0,+1} 方向 / c∈{0,1} 上下文门 / q∈5 级机会
  质量 / g∈{0,1} 波动 regime;
- 组件独立马尔可夫:s 以 s_switch_p 重抽;c/g 以各自保持率重抽;
  q 以 q_hold_p 保持,否则按 (1/8,1/4,1/4,1/4,1/8) 重抽(5 级
  离散,可观察 = 真实,无隐藏质量);
- 下一根收益由决策 bar 的可观察状态决定;r[0]=0(种子 bar)。

课程有效性验收(在看任何学习结果之前,由测试固定):
- 四档同 seed 逐位不同;每档参考能力点非空(D0 方向+幅度/D1 风险
  敏感/D2 动态加减仓退出反手/D3 成本敏感 HOLD);
- 同一训练规格下参考输出非平凡:内部仓位(双侧)、HOLD、调整、
  反手都有出现且不劣于 flat/恒半仓等基线(检查函数供测试/runner);
- C1 空头边真实(镜像配对);C2 同信号跨上下文最优动作不同;
  C3 参考跳过低于费用的边际。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from rl_posctl.versions import (
    POSCTL_C123_ADAPTER_VERSION, POSCTL_C4_CURRICULUM_VERSION)

# 5 级机会质量与重抽分布(级距 0.25;q~U[0,1] 落桶概率)
Q_LEVELS = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
Q_FRESH_P = np.array([0.125, 0.25, 0.25, 0.25, 0.125])

_S_VALUES = np.array([-1, 0, 1], dtype=np.int64)


# ============================== 期望对数增长(闭式,有界均匀) ==============================
def gbar(w, mu: float, sigma: float):
    """E[log(1 + w·r)], r = mu + a·U, U~Unif(−1,1), a=√3·σ。

    闭式(数值稳定形,消 z+−z− 相消):令 x = wa/b,
    E = ln b + G(x)/(2x) − 1,G(x) = (1+x)ln(1+x) − (1−x)ln(1−x),
    由 log1p 计算(相对朴素 F(z±)/(2c) 形把绝对误差从 ~1e-13
    降到机器精度;与幂级数展开双精度一致,见测试)。
    z₋ = b(1−x) ≤ 0(支撑内可破产)→ −inf(如实,不靠积分节点粉饰)。
    标量与数组 w 均可。
    """
    a = math.sqrt(3.0) * float(sigma)
    w = np.asarray(w, dtype=np.float64)
    b = 1.0 + w * float(mu)
    c = w * a
    out = np.full(w.shape, -np.inf)
    flat = np.abs(c) < 1e-300
    with np.errstate(divide="ignore", invalid="ignore"):
        x = np.where(b != 0.0, c / np.where(b != 0.0, b, 1.0), 0.0)
        ok = (~flat) & (b > 0.0) & (x > -1.0) & (x < 1.0) & (
            (1.0 - x) > 0.0)
        xs = np.where(ok, x, 0.0)
        g = ((1.0 + xs) * np.log1p(xs)
             - (1.0 - xs) * np.log1p(-xs))
        val = np.log(np.where(b > 0.0, b, 1.0)) + g / (
            2.0 * xs) - 1.0
        out = np.where(ok, val, out)
    out = np.where(flat & (b > 0.0),
                   np.log(np.where(b > 0, b, 1.0)), out)
    return out if out.ndim else float(out)


def kelly_w(mu: float, sigma: float, *, n_grid: int = 401) -> float:
    """argmax_{w∈[−1,1]} gbar(w; mu, sigma)(细网格;闭式目标)。"""
    grid = np.linspace(-1.0, 1.0, n_grid)
    vals = gbar(grid, mu, sigma)
    return float(grid[int(np.argmax(vals))])


# ============================== 课程规格 ==============================
@dataclass(frozen=True)
class CourseSpec:
    course: str                     # "c1"|"c2"|"c3"|"c4d0".."c4d3"
    horizon: int = 64
    mu_max: float = 1.2e-3          # 单根最大条件漂移(事前固定)
    sigma_lo: float = 0.03          # 低波动 σ(工程合成参数)
    sigma_hi: float = 0.06          # 高波动 σ(D1/D2 风险 regime)
    fee: float = 1e-3
    slippage_bps: float = 0.0
    initial_cash: float = 100.0
    # 组件马尔可夫参数(逐档覆盖;v1 的 hold_p/signal_switch_p/
    # noise_signal_p 三参数模型废弃)
    s_switch_p: float = 0.10        # 方向信号重抽概率
    c_hold_p: float = 0.85          # 上下文门保持概率
    g_hold_p: float = 0.85          # 波动 regime 保持概率
    q_hold_p: float = 0.80          # 质量级保持概率(否则重抽)
    sigma_regime: bool = False      # True: σ=g 切换;False: 恒 σ_lo
    seed: int = 0


# C4 四档 + C1–C3 的事前固定覆盖(参数在看任何学习结果前确定;
# 唯一调整途径 = 课程有效性检查未通过时的实现层修正,须记录)
TIER_OVERRIDES: dict[str, dict] = {
    # D0 方向与幅度基本选择:质量持久(少闪变)、σ 恒定、门 c 不入 μ
    "c4d0": dict(s_switch_p=0.08, c_hold_p=0.85, g_hold_p=0.85,
                 q_hold_p=0.90, sigma_regime=False),
    # D1 风险敏感配置:σ 随 g 切换,参考在 hi-σ 下收缩敞口
    "c4d1": dict(s_switch_p=0.10, c_hold_p=0.85, g_hold_p=0.80,
                 q_hold_p=0.90, sigma_regime=True),
    # D2 动态加减仓/退出/反手:信号/门切换更快,机会增强/衰减/失效
    "c4d2": dict(s_switch_p=0.22, c_hold_p=0.75, g_hold_p=0.80,
                 q_hold_p=0.80, sigma_regime=True),
    # D3 成本敏感再平衡/HOLD:质量高频闪变(短暂噪声),方向持久
    "c4d3": dict(s_switch_p=0.06, c_hold_p=0.92, g_hold_p=0.85,
                 q_hold_p=0.45, sigma_regime=False),
    # C1:无门控(μ 不含 c/q);C2:门控;C3:弱边际(μ 含 0.5 因子)
    "c1": dict(sigma_regime=False),
    "c2": dict(sigma_regime=False),
    "c3": dict(sigma_regime=False),
}

VALID_COURSES = ("c1", "c2", "c3",
                 "c4d0", "c4d1", "c4d2", "c4d3")


def spec_for(course: str, seed: int = 0, **overrides) -> CourseSpec:
    """按课程名构造事前固定规格(显式 overrides 可覆盖;审计可复算)。"""
    if course not in VALID_COURSES:
        raise ValueError(f"未知课程 {course!r}")
    kw = dict(TIER_OVERRIDES[course])
    kw["course"] = course
    kw["seed"] = int(seed)
    kw.update(overrides)
    return CourseSpec(**kw)


def mu_eff_of(spec: CourseSpec, s, c, q):
    """μ_eff(可观察状态函数;C1 无门控,C3 弱边际,D0 无门,其余全量)。"""
    s = np.asarray(s, dtype=np.float64)
    c = np.asarray(c, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    if spec.course == "c1":
        return s * spec.mu_max
    if spec.course == "c2":
        return s * c * spec.mu_max
    if spec.course == "c3":
        return s * c * q * spec.mu_max * 0.5
    if spec.course == "c4d0":
        return s * q * spec.mu_max
    return s * c * q * spec.mu_max    # c4d1/d2/d3


def sigma_of(spec: CourseSpec, g):
    g = np.asarray(g, dtype=np.int64)
    if spec.sigma_regime:
        return np.where(g == 1, spec.sigma_hi, spec.sigma_lo)
    return np.full(g.shape, spec.sigma_lo, dtype=np.float64)


# 全进程生成调用计数(R1 计量披露口径:bank 生成走 QuotaLedger,
# 普通单测夹具生成按来源单列,不混入 bank 额度)
GEN_CALL_COUNT = 0


# ============================== 生成器 ==============================
def generate_episode(spec: CourseSpec, seed: int):
    """一个训练 episode:返回 (prices, features, hidden)。

    prices/features 因果对齐(bar k 收益由决策 bar k−1 可观察状态
    决定);hidden 仅用于生成诊断与课程有效性检查(= 可观察链,
    v2 无隐藏质量)。r 为**算术**收益(与线性合约经济/参考数学一致)。
    """
    global GEN_CALL_COUNT
    GEN_CALL_COUNT += 1
    rng = np.random.default_rng((spec.seed, int(seed)))
    n = spec.horizon + 1
    s = np.zeros(n, dtype=np.int64)
    c = np.zeros(n, dtype=np.int64)
    qi = np.zeros(n, dtype=np.int64)
    g = np.zeros(n, dtype=np.int64)
    s[0] = rng.choice(_S_VALUES)
    c[0] = rng.integers(0, 2)
    qi[0] = rng.choice(len(Q_LEVELS), p=Q_FRESH_P)
    g[0] = rng.integers(0, 2)
    r = np.zeros(n)
    # 逐 bar 交错抽样(状态→噪声):截断 horizon 的前缀与全长
    # 生成逐位一致(无未来泄漏的可验证性质);r[t] 由 t−1 状态驱动
    sqrt3 = math.sqrt(3.0)
    mu_eff = np.zeros(n)
    sigma = np.zeros(n)
    for t in range(1, n):
        if rng.random() < spec.s_switch_p:
            s[t] = rng.choice(_S_VALUES)
        else:
            s[t] = s[t - 1]
        c[t] = c[t - 1] if rng.random() < spec.c_hold_p else int(
            rng.integers(0, 2))
        g[t] = g[t - 1] if rng.random() < spec.g_hold_p else int(
            rng.integers(0, 2))
        if rng.random() < spec.q_hold_p:
            qi[t] = qi[t - 1]
        else:
            qi[t] = rng.choice(len(Q_LEVELS), p=Q_FRESH_P)
        u = rng.uniform(-1.0, 1.0)
        q_arr = Q_LEVELS[qi[t - 1]]
        mu_eff[t] = float(mu_eff_of(
            spec, np.array([s[t - 1]]), np.array([c[t - 1]]),
            np.array([q_arr]))[0])
        sig_t = float(spec.sigma_hi if (
            spec.sigma_regime and g[t - 1] == 1) else spec.sigma_lo)
        sigma[t] = sig_t
        r[t] = mu_eff[t] + (sqrt3 * sig_t) * u
    q = Q_LEVELS[qi]
    if np.any(1.0 + r <= 0.0):
        raise RuntimeError("合成算术收益越界(价格非正;结构非法,"
                           "按结构重试另取 seed,不按 PnL 拒收)")
    close = 100.0 * np.cumprod(1.0 + r)
    open_ = np.empty_like(close)
    open_[0] = 100.0
    open_[1:] = close[:-1]
    prices = pd.DataFrame({"open": open_, "close": close})
    feats = pd.DataFrame({
        "s": s.astype(float),
        "c": c.astype(float),
        "q": q,
        "g": g.astype(float),
    })
    # hidden 语义:mu_eff[t]/sigma[t] = 驱动 bar t 收益的状态参数
    # (= 决策 bar t−1 的可观察状态;r[0]=0 种子 bar)
    hidden = {"mu_eff": mu_eff, "sigma": sigma, "s": s, "c": c,
              "q": q, "g": g, "qi": qi}
    return prices, feats, hidden


# ============================== DP 参考(精确后向归纳) ==============================
W_GRID = np.linspace(-1.0, 1.0, 41)
_DP_CACHE: dict[tuple, dict] = {}


def _state_chain(spec: CourseSpec):
    """可观察状态空间与转移矩阵(组件独立 → Kronecker)。

    与生成器逐分量同语义(独立复核口径,勿复用本函数):
    - s:以 p 重抽均匀(3 态)⇒ P=(1−p)I+p·U₃;
    - c/g:以 1−p_hold 重抽均匀(2 态,重抽可回到同值)
      ⇒ P=p_hold·I+(1−p_hold)·U₂;
    - q:以 pq 保持,否则按 Q_FRESH_P 重抽(重抽可回到同级)
      ⇒ P=pq·I+(1−pq)·Q_FRESH_P(按行广播)。
    全部行随机(行和=1);先前版本 q 用 (1−pq)Q 偏对角+pq 对角
    (行和<1,每步漏掉 (1−pq)·Q[i] 的"重抽回原级"质量,c4d3 漏
    至 13.75%)、c/g 用硬翻转(P(same)=p_hold)——与生成器不符,
    已由独立 reviewer 反例证实并修正。
    """
    states, next_mats = [], []
    # s: 3 态
    p_switch = spec.s_switch_p
    states.append(_S_VALUES.astype(float))
    next_mats.append((1.0 - p_switch) * np.eye(3)
                     + p_switch / 3.0)
    # c: 2 态
    pc = spec.c_hold_p
    states.append(np.array([0.0, 1.0]))
    next_mats.append(pc * np.eye(2) + (1.0 - pc) / 2.0)
    # q: 5 级
    pq = spec.q_hold_p
    states.append(Q_LEVELS.copy())
    next_mats.append(pq * np.eye(5)
                     + (1.0 - pq) * Q_FRESH_P[None, :])
    # g: 2 态
    pg = spec.g_hold_p
    states.append(np.array([0.0, 1.0]))
    next_mats.append(pg * np.eye(2) + (1.0 - pg) / 2.0)
    # Kronecker 组合
    levels = np.meshgrid(*states, indexing="ij")
    table = np.stack([lv.reshape(-1) for lv in levels], axis=1)
    trans = next_mats[0]
    for m in next_mats[1:]:
        trans = np.kron(trans, m)
    return table, trans      # (K,4), (K,K)


def _dp_key(spec: CourseSpec, steps: int) -> tuple:
    return (spec.course, spec.mu_max, spec.sigma_lo, spec.sigma_hi,
            spec.fee, spec.s_switch_p, spec.c_hold_p, spec.g_hold_p,
            spec.q_hold_p, spec.sigma_regime, spec.horizon, steps,
            len(W_GRID))


def reference_policy(spec: CourseSpec) -> dict:
    """后向归纳求精确参考:返回 policy[steps_left][state_idx,w_idx]。

    动作:REBALANCE(w_a) 对全部网格点 a(费用 fee·|w_a−w_k|)或
    HOLD(保持当前 w,无费);一步价值 = Σ_j P[i,j]·(gbar(w;j)+V[j])。
    终值:平仓费 fee·|w|(终端清算线性费用模型,slippage/tick=0 下
    与真实账本一致)。
    """
    key = _dp_key(spec, spec.horizon)
    if key in _DP_CACHE:
        return _DP_CACHE[key]
    table, trans = _state_chain(spec)          # (K,4), (K,K)
    K = table.shape[0]
    W = W_GRID.shape[0]
    mu = mu_eff_of(spec, table[:, 0], table[:, 1], table[:, 2])
    sig = sigma_of(spec, table[:, 3])
    # G[j, a] = gbar(w_a; state j)
    G = np.empty((K, W))
    for j in range(K):
        G[j] = gbar(W_GRID, mu[j], sig[j])
    fee = spec.fee
    fee_mat = fee * np.abs(W_GRID[None, :] - W_GRID[:, None])  # (k,a)
    V = -fee * np.abs(W_GRID)[None, :].repeat(K, axis=0)       # 终值
    policies = {}
    values = {}
    H = spec.horizon
    for steps_left in range(1, H + 1):
        # 本 bar 收益由**决策时状态 i** 的 (μ_i,σ_i) 驱动
        # (r[t+1]=μ_eff(state[t])+σ(state[t])·U,生成器因果对齐);
        # 随后按 P 转移到 j,进入 V[j,·]。
        EV = trans @ V                                   # (i, a)
        Q_rebal = G[:, None, :] - fee_mat + EV[:, None, :]  # (i,k,a)
        q_hold = G + EV                                  # (i, k) HOLD 保持
        best_rebal = Q_rebal.max(axis=2)
        act_rebal = Q_rebal.argmax(axis=2)
        pick_hold = q_hold >= best_rebal
        V = np.where(pick_hold, q_hold, best_rebal)
        policies[steps_left] = np.where(
            pick_hold, -1, act_rebal)              # -1 = HOLD
        values[steps_left] = V.copy()
    out = {"table": table, "mu": mu, "sigma": sig, "G": G,
           "policies": policies, "values": values, "W": W_GRID,
           "final_V": V, "spec": spec}
    _DP_CACHE[key] = out
    return out


def initial_value(spec: CourseSpec) -> float:
    """DP 参考的期望对数增长(精确,无抽样噪声)。

    对生成器初始分布(s 均匀/c 均匀/q~Q_FRESH_P/g 均匀)取
    values[horizon][i, w=0] 的期望;>0 ⇔ 参考策略期望优于
    恒空仓(flat ≡ 0)。课程有效性检查用它,避免少样本实现的
    抽样波动误判。
    """
    pol = reference_policy(spec)
    V = pol["values"][spec.horizon]
    idx0 = int(np.argmin(np.abs(W_GRID)))
    total = 0.0
    for s_idx in range(3):
        for c_idx in range(2):
            for q_idx in range(5):
                for g_idx in range(2):
                    i = ((s_idx * 2 + c_idx) * 5 + q_idx) * 2 + g_idx
                    p = (1 / 3) * (1 / 2) * Q_FRESH_P[q_idx] * (1 / 2)
                    total += p * V[i, idx0]
    return float(total)

def _state_index(spec: CourseSpec, s: float, c: float, q: float,
                 g: float) -> int:
    s_idx = int(np.argmin(np.abs(_S_VALUES - s)))
    c_idx = 0 if c < 0.5 else 1
    q_idx = int(np.argmin(np.abs(Q_LEVELS - q)))
    g_idx = 0 if g < 0.5 else 1
    # 状态表按 meshgrid(s,c,q,g) 行优先展开
    return ((s_idx * 2 + c_idx) * 5 + q_idx) * 2 + g_idx


def reference_action(spec: CourseSpec, feat_row, current_w: float,
                     *, steps_left: int | None = None):
    """可观察 DP 参考:(branch, w)。需要剩余步数(有限视野精确解)。

    steps_left=None 时用满视野策略(近似上界;正式调用应传
    n_rows−1−decision_tick)。
    """
    pol = reference_policy(spec)
    s = float(feat_row["s"])
    c = float(feat_row["c"])
    q = float(feat_row["q"])
    g = float(feat_row["g"])
    i = _state_index(spec, s, c, q, g)
    sl = spec.horizon if steps_left is None else max(
        1, min(int(steps_left), spec.horizon))
    w_idx = int(np.argmin(np.abs(W_GRID - float(current_w))))
    act = pol["policies"][sl][i, w_idx]
    if act < 0:
        return (0, 0.0)
    return (1, float(W_GRID[int(act)]))



# ============================== 课程有效性检查 ==============================
def tier_validity(spec: CourseSpec, n_episodes: int = 32,
                  seed0: int = 0, quota=None) -> dict:
    """参考轨迹统计(题目有效性检查;测试与 runner 共用)。

    断言素材:非零敞口步占比、内部仓位(0<|w|<1)步、HOLD 步、
  调仓步、反手步、双侧方向出现、相对 flat 的净对数优势。
    """
    from rl_posctl.env import HybridPositionEnv
    from rl_posctl.evalreport import run_policy, summarize

    def ref(row, w, sl):
        return reference_action(spec, row, w, steps_left=sl)

    stats = dict(nonzero=0, interior=0, hold=0, rebal=0, flips=0,
                 pos=0, neg=0, net_log=0.0, flat_net_log=0.0,
                 steps=0, n_failures=0)
    for i in range(n_episodes):
        if quota is not None:
            quota.record(gen_calls=1, episodes=1,
                         bank=f"posctl_{spec.course}_validity",
                         domain="eval")
        prices, feats, _ = generate_episode(spec, seed0 + i)
        env = HybridPositionEnv(
            features=feats, prices=prices, fee=spec.fee, window_size=1)
        infos = run_policy(env, ref)
        summ = summarize(infos)
        stats["n_failures"] += summ["n_reward_invalid_steps"]
        stats["net_log"] += (summ["net_log_return"] or 0.0)
        env2 = HybridPositionEnv(
            features=feats, prices=prices, fee=spec.fee, window_size=1)
        infos2 = run_policy(env2, lambda row, w, sl: (1, 0.0))
        stats["flat_net_log"] += (summarize(infos2)["net_log_return"]
                                  or 0.0)
        prev_w = 0.0
        for info in infos:
            if info["reward_valid"]:
                stats["steps"] += 1
                w_now = (info["exposure_ratio_close"] or 0.0)
                if info["action_branch"] == 0:
                    stats["hold"] += 1
                else:
                    stats["rebal"] += 1
                    if abs(info["action_w"]) > 0:
                        stats["nonzero"] += 1
                    if 0 < abs(info["action_w"]) < 1:
                        stats["interior"] += 1
                    if (prev_w > 1e-9 and info["action_w"] < -1e-9) or (
                            prev_w < -1e-9 and info["action_w"] > 1e-9):
                        stats["flips"] += 1
                if info["exposure_ratio_close"] is not None:
                    if w_now > 1e-9:
                        stats["pos"] += 1
                    elif w_now < -1e-9:
                        stats["neg"] += 1
                prev_w = info["action_w"] if info[
                    "action_branch"] == 1 else prev_w
    return stats


# ============================== 基线/失败对照 ==============================
def baseline_policies():
    """最少对照族(返回 name -> fn(feat_row, current_w)->(branch,w))。"""
    def flat(row, w, *unused):
        return (1, 0.0)

    def long_half(row, w, *unused):
        return (1, 0.5)

    def short_half(row, w, *unused):
        return (1, -0.5)

    def long_full(row, w, *unused):
        return (1, 1.0)

    def short_full(row, w, *unused):
        return (1, -1.0)

    def binary_sign(row, w, *unused):
        s = int(round(float(row["s"])))
        return (1, float(np.clip(s, -1.0, 1.0)))

    def first_then_hold(row, w, *unused):
        if abs(w) < 1e-9 and int(round(float(row["s"]))) != 0:
            return (1, float(np.clip(
                int(round(float(row["s"]))), -1.0, 1.0)))
        return (0, 0.0)

    def always_retarget(row, w, *unused):
        s = int(round(float(row["s"])))
        return (1, 0.5 * float(np.clip(s, -1.0, 1.0)))

    def local_only(row, w, *unused):
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
