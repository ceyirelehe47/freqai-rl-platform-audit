# -*- coding: utf-8 -*-
"""C1–C4 双向课程:合成生成器、可观察参考与失败对照
(RouteC_PositionControl W3,PosctlC4Curriculum-v3 / C123Adapter-v2,
R2 修正参考的账户状态转移)。

全部为独立新工程域(PosctlEngBanks-v3 语料),不改旧 rl_curriculum
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
- 参考(v3,R2-04 修正):R1-v2 的"精确动态规划"**措辞撤销**——
  其递推把 HOLD 当作保持 w 列不变,与真实环境 HOLD(保持数量,
  w_next = w(1+r)/(1+w·r))不一致(reviewer 固定路径反例:
  100→110→99、初始 50% 多头:真实固定数量净值 99.5 vs 恒比例
  99.75)。v3 参考 = **真实账户状态转移**的数值后向归纳(转移
  算子与账本逐位一致,单测对拍;w 非均匀网格插值 + GL 求积;
  41 点动作网格 = 模型动作集限制,不称连续最优上界),误差由
  网格/求积细化收敛差声明(error_report),用于优势主张时
  误差必须小于声称的优势。

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

# R3-01 执行中硬限(suite/运行器在消费前设置;None=不限):
# 越限的第 N+1 次生成调用在**任何采样之前**拒绝,不是事后结算发现。
GEN_CALL_LIMIT = None


# ============================== 生成器 ==============================
def generate_episode(spec: CourseSpec, seed: int):
    """一个训练 episode:返回 (prices, features, hidden)。

    prices/features 因果对齐(bar k 收益由决策 bar k−1 可观察状态
    决定);hidden 仅用于生成诊断与课程有效性检查(= 可观察链,
    v2 无隐藏质量)。r 为**算术**收益(与线性合约经济/参考数学一致)。
    """
    global GEN_CALL_COUNT
    if GEN_CALL_LIMIT is not None and (
            GEN_CALL_COUNT + 1 > GEN_CALL_LIMIT):
        from rl_posctl.budget import BudgetExceeded
        raise BudgetExceeded(
            "generate_episode 执行中硬限拒绝:已调用 "
            f"{GEN_CALL_COUNT}+1 > 授权 {GEN_CALL_LIMIT};本次生成"
            "不执行(fail closed,不是事后结算发现)")
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


# ============================== DP 参考(真实账户状态转移;PosctlC4Curriculum-v3) ==============================
# R2-04(FiniteRepair R2):旧 v2 递推把 HOLD 当作"保持敞口比例 w 列
# 不变"——与真实环境 HOLD(保持**数量**,比例随收益漂移
# w_next = w(1+r)/(1+w·r))不一致;费用线性近似 fee·|Δw| 也与账本
# 扣费后口径求解不同。v3 参考:
#   - 状态 = 可观察链 (s,c,q,g) + **真实账户敞口比 w**(连续);
#   - 转移 = 与账本/env 逐位一致的解析算子(hold_step/rebal_step/
#     终端清算,见下;单测与 TwoSidedLinearLedger 对拍);
#   - 动作 = HOLD 或 REBALANCE(41 点动作网格 = 模型动作集限制,
#     **不称连续最优上界**);
#   - 数值方法 = w 非均匀网格(内部密集、外部几何延伸到维持保证金
#     强制平仓边界 1/mm)上线性插值 + r 积分 Gauss-Legendre 求积;
#     41 点动作网格上的价值是网格内最优(非连续最优);
#   - 误差声明 = 网格/求积细化的收敛差(见 error_report/收敛单测),
#     用于有效性主张的误差必须小于所声称的优势。
W_GRID = np.linspace(-1.0, 1.0, 41)
_DP_CACHE: dict[tuple, dict] = {}

# 账户网格默认分辨率(n_dense 奇数 ⇒ 0.0 为精确格点)
REF_N_DENSE = 321
REF_N_EXT = 64
REF_M_QUAD = 40
W_DENSE = 1.25       # 内部密集域(覆盖 HOLD 单 bar 最大漂移 ~2.35? 不,
                     # 单bar可达2.35;密集域取±1.25 覆盖常见决策区,
                     # 其余由几何延伸段覆盖到强制平仓边界)


def account_grid(n_dense: int = REF_N_DENSE,
                 n_ext: int = REF_N_EXT,
                 w_ext: float = 20.0) -> np.ndarray:
    """账户敞口比数值网格:内部均匀 + 外部几何延伸到 ±w_ext。

    w_ext = 1/maintenance_margin(env 默认 mm=0.05 ⇒ 20):|w|>w_ext
    的状态在下一开盘被强制风险平仓(回 0 并付 fee·|w|),为精确
    延伸语义(见 _forced_flat_ext),不是截断。
    """
    if n_dense % 2 == 0:
        n_dense += 1        # 保证 0.0 精确格点
    inner = np.linspace(-W_DENSE, W_DENSE, n_dense)
    frac = np.geomspace(W_DENSE, float(w_ext), int(n_ext) + 1)[1:]
    return np.concatenate([-frac[::-1], inner, frac])


def liq_value(w, fee: float):
    """终端清算的 log 增长 = log(1 - fee·|w|)(fee·|w|≥1 ⇒ -inf)。"""
    w = np.asarray(w, dtype=np.float64)
    f = fee * np.abs(w)
    out = np.where(f < 1.0, np.log1p(-f), -np.inf)
    return out if out.ndim else float(out)


def hold_step(w: float, r: float):
    """HOLD 一步(固定数量):返回 (log 增长, 后继敞口比)。

    与账本一致:数量不变 ⇒ E_next = E·(1+w·r),
    w_next = w(1+r)/(1+w·r)。1+w·r ≤ 0 ⇒ 经济失败(-inf)。
    """
    g = 1.0 + w * r
    if g <= 0.0:
        return -math.inf, math.inf * (1 if w >= 0 else -1)
    return math.log(g), w * (1.0 + r) / g


def rebal_fee_fraction(w: float, w_t: float, fee: float) -> float:
    """扣费后口径目标调仓的费用比例 f = fee·|δ|/e(与账本
    _solve_q_new 同解:δ=(w_t−w)/(1±w_t·fee),e=1,open=1)。"""
    if w_t > w:
        delta = (w_t - w) / (1.0 + w_t * fee)
    elif w_t < w:
        delta = (w_t - w) / (1.0 - w_t * fee)
    else:
        return 0.0
    return fee * abs(delta)


def rebal_step(w: float, w_t: float, r: float, fee: float):
    """REBALANCE(w_t) 一步:返回 (log 增长, 后继敞口比)。

    调仓在 open 成交(扣费后口径精确解),本 bar 收益作用于新仓位:
    log 增长 = log(1−f) + log(1+w_t·r);后继比例按固定数量漂移。
    """
    f = rebal_fee_fraction(w, w_t, fee)
    lg, wn = hold_step(w_t, r)
    if f >= 1.0:
        return -math.inf, math.inf
    if lg == -math.inf:
        return -math.inf, wn
    return math.log1p(-f) + lg, wn


def _forced_flat_ext(w, fee: float, value_from_zero):
    """|w|>强制平仓边界的精确延伸:下一开盘强制平仓(付 fee·|w|,
    回 0)后再行动 ⇒ V(w) = log(1−fee·|w|) + V(0)。"""
    w = np.asarray(w, dtype=np.float64)
    base = np.where(fee * np.abs(w) < 1.0,
                    np.log1p(-fee * np.abs(w)), -np.inf)
    return base + value_from_zero


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
    已由独立 reviewer 反例证实并修正(R1)。
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


def _dp_key(spec: CourseSpec, steps: int, n_dense: int,
            n_ext: int, m_quad: int, mm: float,
            w_ext: float) -> tuple:
    # R3-03(F3-a):缓存键必须绑定**全部**影响语义/适用性的参数——
    # 旧键漏 slippage_bps,零滑点解出的对象可被 10bps 规格命中。
    return (spec.course, spec.mu_max, spec.sigma_lo, spec.sigma_hi,
            spec.fee, spec.slippage_bps, spec.s_switch_p,
            spec.c_hold_p, spec.g_hold_p,
            spec.q_hold_p, spec.sigma_regime, spec.horizon, steps,
            len(W_GRID), n_dense, n_ext, m_quad, mm, w_ext)


def reference_policy(spec: CourseSpec, *,
                     n_dense: int = REF_N_DENSE,
                     n_ext: int = REF_N_EXT,
                     m_quad: int = REF_M_QUAD,
                     maintenance_margin: float = 0.05,
                     w_ext: float | None = None) -> dict:
    """真实账户动力学参考(后向归纳;数值近似,误差声明见下)。

    返回 dict:table/mu/sigma/trans(可观察链)、G(K,A) 各状态动作
    的本 bar 期望对数增长(gbar 闭式)、grid(nW) 账户网格、
    policies[sl](K,nW;-1=HOLD,否则 W_GRID 动作索引)、
    values[sl](K,nW)、hold_values[sl](K,nW HOLD 臂值,供独立对照)、
    cont_rebal[sl](K,A 调仓臂续值)、zero_idx、x/wq(GL 节点)、
    solver_meta(网格/求积/误差声明)。w_ext 覆盖强制平仓边界
    (默认 1/maintenance_margin;测试可延伸以验证边界外语义)。

    声明:本参考是"41 点动作网格 + 账户网格线性插值 + GL 求积"下的
    数值最优,**不是**连续动作最优,也不虚称精确;用于优势主张时
    必须配合 error_report 的收敛差(误差 < 优势)。

    R3-03(F3-a):**假设检查先于缓存**——适用性(滑点=0)不满足时,
    无论冷缓存还是暖缓存一律拒绝;缓存命中不得绕过假设校验,也不
    能把不同滑点规格映射到同一缓存对象(键同时绑定 slippage_bps)。
    """
    w_ext_v = float(w_ext) if w_ext is not None else (
        1.0 / float(maintenance_margin))
    if spec.slippage_bps != 0.0:
        raise ValueError(
            "参考求解器假设 slippage_bps=0(课程规格如此);非零滑点"
            " 的近似与误差声明未建立,拒绝虚算(该检查先于缓存查询,"
            "暖缓存同输入同拒绝)")
    key = _dp_key(spec, spec.horizon, n_dense, n_ext, m_quad,
                  maintenance_margin, w_ext_v)
    if key in _DP_CACHE:
        return _DP_CACHE[key]
    table, trans = _state_chain(spec)          # (K,4), (K,K)
    K = table.shape[0]
    A = W_GRID.shape[0]
    mu = mu_eff_of(spec, table[:, 0], table[:, 1], table[:, 2])
    sig = sigma_of(spec, table[:, 3])
    G = np.empty((K, A))
    for j in range(K):
        G[j] = gbar(W_GRID, mu[j], sig[j])
    grid = account_grid(n_dense, n_ext, w_ext=w_ext_v)
    nW = grid.shape[0]
    zero_idx = int(np.argmin(np.abs(grid)))
    fee = spec.fee
    w_bound = 1.0 / maintenance_margin
    # 调仓费矩阵(账户网格 × 动作网格)
    fmat = np.empty((nW, A))
    for k in range(nW):
        for a in range(A):
            fmat[k, a] = rebal_fee_fraction(
                grid[k], W_GRID[a], fee)
    log_fee = np.where(fmat < 1.0, np.log1p(-fmat), -np.inf)
    # GL 节点/权重(E over U~Unif(-1,1))
    x, wq = np.polynomial.legendre.leggauss(int(m_quad))
    wq = wq / 2.0
    a_amp = math.sqrt(3.0) * sig                # (K,) r = mu + a·x
    # 终值:清算 only
    V = np.tile(liq_value(grid, fee), (K, 1))   # (K, nW)
    policies: dict[int, np.ndarray] = {}
    values: dict[int, np.ndarray] = {}
    hold_values: dict[int, np.ndarray] = {}
    cont_rebal: dict[int, np.ndarray] = {}
    H = spec.horizon

    def _cont_of(ev_row: np.ndarray, w_pts: np.ndarray):
        """EV 行在 w_pts 的续值(内部插值;|w|>边界精确延伸)。"""
        inside = np.abs(w_pts) <= w_bound
        out = np.empty_like(w_pts)
        out[inside] = np.interp(
            w_pts[inside], grid, ev_row)
        if (~inside).any():
            out[~inside] = _forced_flat_ext(
                w_pts[~inside], fee, float(ev_row[zero_idx]))
        return out

    for steps_left in range(1, H + 1):
        EV = trans @ V                           # (K, nW)
        # HOLD 臂:gbar(grid;μ_i,σ_i) + E_r[EV_i(w_next)]
        hv = np.empty((K, nW))
        for i in range(K):
            r_nodes = mu[i] + a_amp[i] * x
            gb = gbar(grid, mu[i], sig[i])
            finite = np.isfinite(gb)
            cont = np.zeros(nW)
            for m in range(len(x)):
                r = float(r_nodes[m])
                g = 1.0 + grid * r
                safe = np.where(g > 0.0, g, 1.0)
                wn = np.where(
                    g > 0.0, grid * (1.0 + r) / safe, 0.0)
                cont += wq[m] * _cont_of(EV[i], wn)
            hv[i] = np.where(finite, gb + cont, -np.inf)
        # 调仓臂(动作 a):log(1−f) + gbar(w_a) + E_r[EV_i(w_next(w_a))]
        cont_a = np.empty((K, A))
        for i in range(K):
            r_nodes = mu[i] + a_amp[i] * x
            acc = np.zeros(A)
            for m in range(len(x)):
                r = float(r_nodes[m])
                g = 1.0 + W_GRID * r
                wn = W_GRID * (1.0 + r) / g
                acc += wq[m] * _cont_of(EV[i], wn)
            cont_a[i] = acc
        Q = log_fee[None, :, :] + G[:, None, :] \
            + cont_a[:, None, :]                 # (K, nW, A)
        best = Q.max(axis=2)
        act = Q.argmax(axis=2)
        pick_hold = hv >= best
        V = np.where(pick_hold, hv, best)
        pol = np.where(pick_hold, -1, act)
        # |w|>强制平仓边界:开盘强制平仓(付 fee·|w|,回 0)后行动
        over = np.abs(grid) > w_bound
        if over.any():
            V[:, over] = (_forced_flat_ext(
                grid[over], fee, 0.0)[None, :]
                + V[:, zero_idx:zero_idx + 1])
            pol[:, over] = pol[:, zero_idx:zero_idx + 1]
            hv[:, over] = V[:, over]
        policies[steps_left] = pol
        values[steps_left] = V.copy()
        hold_values[steps_left] = hv
        cont_rebal[steps_left] = cont_a
    out = {"table": table, "mu": mu, "sigma": sig, "G": G,
           "trans": trans, "grid": grid, "zero_idx": zero_idx,
           "W": W_GRID, "policies": policies, "values": values,
           "hold_values": hold_values, "cont_rebal": cont_rebal,
           "final_V": V, "spec": spec, "x": x, "wq": wq,
           "solver_meta": {
               "n_dense": int(n_dense), "n_ext": int(n_ext),
               "m_quad": int(m_quad),
               "w_dense": W_DENSE, "w_ext": float(w_ext_v),
               "maintenance_margin": float(maintenance_margin),
               "action_grid_size": int(A),
               "account_grid_size": int(nW),
               "method": ("account-exact transitions + linear "
                          "interp on non-uniform w grid + "
                          "Gauss-Legendre r quadrature; grid-"
                          "restricted optimum, NOT continuous "
                          "optimal upper bound")}}
    _DP_CACHE[key] = out
    return out


def initial_value(spec: CourseSpec, *, n_dense: int = REF_N_DENSE,
                  n_ext: int = REF_N_EXT,
                  m_quad: int = REF_M_QUAD) -> float:
    """参考的期望对数增长(数值;对生成器初始分布取 values[horizon]
    [i, w=0] 的期望;>0 ⇔ 参考策略期望优于恒空仓 flat≡0)。

    R2 声明:这是账户网格/求积下的数值近似;有效性主张必须配合
    error_report(spec) 的收敛差(误差 < 声称优势)。
    """
    pol = reference_policy(spec, n_dense=n_dense, n_ext=n_ext,
                           m_quad=m_quad)
    V = pol["values"][spec.horizon]
    zi = pol["zero_idx"]
    total = 0.0
    for s_idx in range(3):
        for c_idx in range(2):
            for q_idx in range(5):
                for g_idx in range(2):
                    i = ((s_idx * 2 + c_idx) * 5 + q_idx) * 2 + g_idx
                    p = (1 / 3) * (1 / 2) * Q_FRESH_P[q_idx] * (1 / 2)
                    total += p * float(V[i, zi])
    return float(total)


def validate_refinements(refinements) -> list:
    """细化规格校验(R3-03/F3-b;eval 运行器预约前用同一校验)。

    拒绝:空/单级(无比较即无收敛证据)、重复级别(相邻差恒 0,
    冒充零误差)、倒退/非严格细化、非正整数/bool/NaN/inf、
    非法元组形状。空/单级/重复/倒退组合不得产出 err_bound——
    "没有做新比较"不等于"误差为零"。
    """
    try:
        levels = list(refinements)
    except TypeError:
        raise ValueError(
            f"refinements 必须可迭代(得到 {type(refinements)!r})")
    if len(levels) < 2:
        raise ValueError(
            f"refinements 至少两级(得到 {len(levels)} 级):单级/空"
            "无收敛比较,err_bound 无从谈起(不得当零误差)")
    norm = []
    for i, lv in enumerate(levels):
        if isinstance(lv, (str, bytes)) or not hasattr(
                lv, "__iter__"):
            raise ValueError(
                f"refinements[{i}] 非法级别 {lv!r}:需"
                "(n_dense, n_ext, m_quad) 三元组")
        t = tuple(lv)
        if len(t) != 3:
            raise ValueError(
                f"refinements[{i}]={lv!r}:长度 {len(t)}≠3"
                "(n_dense, n_ext, m_quad)")
        for x in t:
            if isinstance(x, bool) or not isinstance(x, (int, float)):
                raise ValueError(
                    f"refinements[{i}]={lv!r}:分量 {x!r} 非数值")
            xf = float(x)
            if (not math.isfinite(xf) or xf != int(xf)
                    or int(xf) <= 0):
                raise ValueError(
                    f"refinements[{i}]={lv!r}:分量 {x!r} 非正整数"
                    "(NaN/inf/非整数/bool/≤0 拒绝)")
        norm.append((int(t[0]), int(t[1]), int(t[2])))
    for i in range(len(norm) - 1):
        a, b = norm[i], norm[i + 1]
        if b == a:
            raise ValueError(
                f"refinements 级别重复:{a}(相邻差恒 0 冒充零误差,"
                "不是证明精确)")
        if any(b[k] < a[k] for k in range(3)):
            raise ValueError(
                f"refinements 非细化(倒退):{a} -> {b}"
                "(每分量须不减且至少一分量严格增)")
        if not any(b[k] > a[k] for k in range(3)):
            raise ValueError(
                f"refinements 级别未细化:{a} -> {b}"
                "(须至少一个分量严格增,否则无新比较)")
    return norm


def error_report(spec: CourseSpec,
                 refinements=((161, 32, 20), (321, 64, 40),
                              (481, 96, 80))) -> dict:
    """网格/求积细化收敛差(误差声明;用于优势主张的门槛)。

    R3-03(F3-b):细化输入先过 validate_refinements——空/单级/重复/
    倒退/非法数值组合**拒绝**,不再产出退化 err_bound=0;各级值须
    有限(−inf/NaN 无收敛意义)。err_bound 是**经验相邻级差**,
    不是已证明的误差上界——输出 err_bound_kind 如实分型;基于它
    的 qualified 只是有条件的数值开发判断,不是一般误差保证。
    """
    levels = validate_refinements(refinements)
    vals = []
    for nd, ne, mq in levels:
        v = initial_value(spec, n_dense=nd, n_ext=ne, m_quad=mq)
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(
                f"细化级别 {(nd, ne, mq)} 初值非有限({v!r}):"
                "无收敛意义的值不得充当误差证据")
        vals.append(float(v))
    diffs = [abs(vals[i + 1] - vals[i])
             for i in range(len(vals) - 1)]
    return {"values": vals,
            "refinements": [list(r) for r in levels],
            "adjacent_diffs": diffs,
            "err_bound": (max(diffs) if diffs else 0.0),
            "err_bound_kind": "empirical_adjacent_diff",
            "spec_key": spec_fingerprint(spec),
            "judged_grid": [REF_N_DENSE, REF_N_EXT, REF_M_QUAD],
            "err_bound_note": (
                "经验收敛差(相邻细化级最大差),不是已证明的误差"
                "上界;qualified 判断仅为本固定规格下的有条件数值"
                "开发判断")}


def spec_fingerprint(spec: CourseSpec) -> tuple:
    """课程规格语义指纹(全部影响参考值/适用性的字段;R4-B)。"""
    return (spec.course, spec.horizon, spec.seed, spec.mu_max,
            spec.sigma_lo, spec.sigma_hi, spec.fee,
            spec.slippage_bps, spec.s_switch_p, spec.c_hold_p,
            spec.g_hold_p, spec.q_hold_p, spec.sigma_regime,
            spec.initial_cash)


def _verify_error_report(spec: CourseSpec, report: dict,
                         judged_value: float) -> dict:
    """复算绑定 error_report 证据(R4-B/C1;tier_validity 消费用)。

    核验:结构完整、细化链合法(validate_refinements)、各级值
    有限、err_bound == 重算 max|相邻差|、spec_key == 当前规格
    指纹、最细级 == 当前判定值所用默认求解网格(REF_*)。
    通过 → verified + err_bound + 证据摘要;不通过 → 未验证
    原因(调用方输出 NOT_ESTABLISHED)。手改 err_bound/错规格
    报告/最细级与判定网格不一致均不通过。
    """
    try:
        vals = report["values"]
        refs = report["refinements"]
        diffs = report["adjacent_diffs"]
        eb = report["err_bound"]
        skey = report["spec_key"]
        judged = report["judged_grid"]
    except (KeyError, TypeError):
        return {"verified": False,
                "reason": "报告结构不完整(缺 values/refinements/"
                          "adjacent_diffs/err_bound/spec_key/"
                          "judged_grid;疑似非 error_report 输出)"}
    try:
        levels = validate_refinements(refs)
    except ValueError as exc:
        return {"verified": False,
                "reason": f"细化链非法:{exc}"}
    if (not isinstance(vals, list) or len(vals) != len(levels)
            or not isinstance(diffs, list)
            or len(diffs) != len(levels) - 1):
        return {"verified": False,
                "reason": "值/差数组长度与细化级不匹配"}
    for v in vals:
        if not isinstance(v, (int, float)) or isinstance(v, bool) \
                or not math.isfinite(float(v)):
            return {"verified": False,
                    "reason": f"细化值非有限({v!r})"}
    recompute = [abs(float(vals[i + 1]) - float(vals[i]))
                 for i in range(len(vals) - 1)]
    if any(abs(a - b) > 1e-15 * max(1.0, abs(b))
           for a, b in zip(recompute, diffs)):
        return {"verified": False,
                "reason": "adjacent_diffs 与值序列复算不符(疑似"
                          "手改)"}
    if (not isinstance(eb, (int, float)) or isinstance(eb, bool)
            or not math.isfinite(float(eb))
            or abs(float(eb) - max(recompute))
            > 1e-15 * max(1.0, abs(max(recompute)))):
        return {"verified": False,
                "reason": f"err_bound 与 max|相邻差| 复算不符"
                          f"({eb!r} vs {max(recompute)!r};疑似手改)"}
    if tuple(skey) != spec_fingerprint(spec):
        return {"verified": False,
                "reason": "spec_key 与当前课程规格不一致(错规格"
                          "证据不得给本规格结论)"}
    try:
        judged_list = [int(x) for x in judged]
    except (TypeError, ValueError):
        return {"verified": False,
                "reason": f"judged_grid 类型非法({judged!r});"
                          "结构残缺按未验证处理"}
    if judged_list != [REF_N_DENSE, REF_N_EXT, REF_M_QUAD]:
        return {"verified": False,
                "reason": "judged_grid 与判定值所用默认求解网格"
                  f"不一致({judged_list} vs "
                  f"{[REF_N_DENSE, REF_N_EXT, REF_M_QUAD]});误差"
                  "基准与被判定值不同"}
    finest = levels[-1]
    if list(finest) != [REF_N_DENSE, REF_N_EXT, REF_M_QUAD]:
        return {"verified": False,
                "reason": f"最细级 {finest} != 判定网格 "
                  f"{[REF_N_DENSE, REF_N_EXT, REF_M_QUAD]};误差"
                  "声明未覆盖被判定值的求解设置"}
    jv = float(judged_value)
    if not math.isclose(float(vals[-1]), jv,
                        rel_tol=1e-12, abs_tol=0.0):
        return {"verified": False,
                "reason": (f"最细级值 {vals[-1]!r} != 被判定参考值"
                           f" {jv!r}(自洽伪造值链不通过;合法报告"
                           "最细级在判定网格上必与参考值一致)")}

    return {"verified": True,
            "err_bound": float(eb),
            "evidence": {
                "refinements": [list(r) for r in levels],
                "n_levels": len(levels),
                "adjacent_diffs": recompute,
                "spec_key": list(skey),
                "judged_grid": [int(x) for x in judged],
                "verified_by": "tier_validity._verify_error_report"}}

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
    """可观察参考动作:(branch, w)。需要剩余步数(有限视野解)。

    在**实际**敞口比 current_w(连续,不吸附格点)上评估:
    HOLD 臂 = gbar(w) + E_r[V_{h−1}(j, w_next(w,r))];
    调仓臂 = log(1−f(w,w_a)) + gbar(w_a) + cont_a(j, w_a)。
    |w|>强制平仓边界时按"先强制平仓回 0 再行动"评估。
    steps_left=None 用满视野(近似;正式调用应传真实剩余步数)。
    """
    pol = reference_policy(spec)
    s = float(feat_row["s"])
    c = float(feat_row["c"])
    q = float(feat_row["q"])
    g = float(feat_row["g"])
    i = _state_index(spec, s, c, q, g)
    sl = spec.horizon if steps_left is None else max(
        1, min(int(steps_left), spec.horizon))
    w = float(current_w)
    fee = spec.fee
    w_bound = 1.0 / float(
        pol["solver_meta"]["maintenance_margin"])
    if abs(w) > w_bound:
        # 下一开盘强制平仓(费用由强制平仓腿承担)后从 0 行动:
        # 直接在 w=0 上评估(与真实 env 时序一致)
        w = 0.0
    grid = pol["grid"]
    if sl - 1 >= 1:
        EV = pol["trans"] @ pol["values"][sl - 1]   # (K, nW)
        ev_row = EV[i]
    else:
        # 末 bar:后继价值 = 终端清算(状态无关)
        ev_row = liq_value(grid, fee)

    x, wq = pol["x"], pol["wq"]
    mu_i, sig_i = float(pol["mu"][i]), float(pol["sigma"][i])
    zi = pol["zero_idx"]
    r_nodes = mu_i + math.sqrt(3.0) * sig_i * x

    def cont_at(w_pts):
        w_pts = np.asarray(w_pts, dtype=np.float64)
        inside = np.abs(w_pts) <= w_bound
        out = np.empty_like(w_pts)
        out[inside] = np.interp(w_pts[inside], grid, ev_row)
        if (~inside).any():
            out[~inside] = _forced_flat_ext(
                w_pts[~inside], fee, float(ev_row[zi]))
        return out

    # HOLD 臂(在真实 w 上;支撑含破产 ⇒ −inf,正确 discouraged)
    g_hold = 1.0 + w * r_nodes
    if np.any(g_hold <= 0.0):
        q_hold = -math.inf
    else:
        wn = w * (1.0 + r_nodes) / g_hold
        q_hold = float(gbar(np.array(w), mu_i, sig_i)) + float(
            np.dot(wq, cont_at(wn)))
    # 调仓臂(41 动作;费用按真实 w 精确解;w_a∈[−1,1] 节点安全)
    best_val, best_a = q_hold, -1
    for a in range(W_GRID.shape[0]):
        wa = float(W_GRID[a])
        f = rebal_fee_fraction(w, wa, fee)
        if f >= 1.0:
            continue
        g_a = 1.0 + wa * r_nodes
        if np.any(g_a <= 0.0):
            continue
        wn_a = wa * (1.0 + r_nodes) / g_a
        val = (math.log1p(-f) + float(pol["G"][i, a])
               + float(np.dot(wq, cont_at(wn_a))))
        if val > best_val:
            best_val, best_a = val, a
    if best_a < 0:
        return (0, 0.0)
    return (1, float(W_GRID[int(best_a)]))



# ============================== 课程有效性检查 ==============================
def tier_validity(spec: CourseSpec, n_episodes: int = 32,
                  seed0: int = 0, quota=None,
                  err_bound: float | None = None) -> dict:
    """参考轨迹统计(题目有效性检查;测试与 runner 共用)。

    断言素材:非零敞口步占比、内部仓位(0<|w|<1)步、HOLD 步、
  调仓步、反手步、双侧方向出现、相对 flat 的净对数优势。

  R2-04:dp_initial_value 为**数值参考值**;err_bound 传入时输出
  qualified = (value − err_bound > 0)——误差 ≥ 优势 ⇒ 未证明,
  下游不得把该课程视为 qualified(如实 NOT_ESTABLISHED);
  err_bound 来源 = error_report(spec) 收敛差,不得手设宽容差。
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
            # 计数生成两步结算(调用必计;成功才结 episode)——
            # 鸭子类型调用 quota 方法,避免 curriculum↔banks 循环导入
            quota.record(gen_calls=1,
                         bank=f"posctl_{spec.course}_validity",
                         domain="eval")
            prices, feats, _ = generate_episode(spec, seed0 + i)
            quota.record_episode(
                bank=f"posctl_{spec.course}_validity", domain="eval")
        else:
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
    stats["dp_initial_value"] = initial_value(spec)
    stats["dp_solver_meta"] = dict(
        reference_policy(spec)["solver_meta"])
    if err_bound is not None:
        # R4-B(C1):有效性结论必须绑定**可复算证据**,裸标量只能作
        # 诊断——不再把手填 0/False 贴上 empirical_adjacent_diff 并
        # 给 qualified=true。三类输入:
        # - bool/非有限/负数:结构性非法,拒绝(资源工作前);
        # - 裸数值(含 0):diagnostic_only,qualified=False,
        #   NOT_ESTABLISHED(没有细化链/规格绑定,不足以给结论);
        # - error_report 输出(dict):复算绑定——细化链合法、
        #   err_bound == 重算 max|相邻差|、spec 指纹一致、最细级
        #   == 当前判定值所用默认求解网格;任一不满足即
        #   NOT_ESTABLISHED(不误拒合法报告,也不给手改值放行)。
        if isinstance(err_bound, bool):
            raise ValueError(
                f"err_bound 非法({err_bound!r}):布尔不是误差证据")
        if isinstance(err_bound, dict):
            verdict = _verify_error_report(
                spec, err_bound,
                judged_value=float(stats["dp_initial_value"]))
            if verdict.get("verified"):
                eb = float(verdict["err_bound"])
                stats["dp_err_bound"] = eb
                stats["err_bound_kind"] = "empirical_adjacent_diff"
                stats["err_evidence"] = verdict["evidence"]
                stats["qualified"] = bool(
                    stats["dp_initial_value"] - eb > 0.0)
                stats["qualification_note"] = (
                    "value−err>0 才 qualified;误差=绑定复算的"
                    "error_report 经验相邻差(非已证明误差上界);"
                    "本判断为固定规格下的有条件数值开发判断,"
                    "不足即 NOT_ESTABLISHED,不构成一般误差保证")
            else:
                stats["err_bound_kind"] = "unverified_report"
                stats["qualified"] = False
                stats["qualification_note"] = (
                    "证据未通过绑定复算(" + verdict["reason"]
                    + ");NOT_ESTABLISHED,不作有效性结论")
        else:
            eb = float(err_bound)
            if not math.isfinite(eb) or eb < 0.0:
                raise ValueError(
                    f"err_bound 非法({err_bound!r}):非有限/负值"
                    "不是误差证据(拒绝)")
            stats["dp_err_bound_diagnostic_only"] = eb
            stats["err_bound_kind"] = "diagnostic_only"
            stats["qualified"] = False
            stats["qualification_note"] = (
                "裸标量 err_bound 仅作诊断:无细化链/规格/求解"
                "设置绑定,不足以支撑有效性结论(NOT_ESTABLISHED);"
                "合格判定请传入 error_report(spec) 的完整报告")
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
