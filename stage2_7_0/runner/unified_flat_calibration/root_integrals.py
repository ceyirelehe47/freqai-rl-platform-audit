# -*- coding: utf-8 -*-
"""root_integrals v3 — 极小纯函数(PLAN_ONLY;无真实 V/Q、
无 solver/query/leggauss;测试含手写数值面板,非"零积分")。

v3(审查方 3699):
- 小 w 分支 lg/post 均**级数稳定**(避免闭式端点相消);
- post 级数截断界含几何因子 1/(1−ρ),ρ=|w|·x_max;
- seg_integral_bounded 返回 (值, **仅 post 级数截断上界**);
  该界**不含 lg 级数余项与浮点舍入**,不是总积分误差证书;
- 适用域声明:级数分支 |w·x|<1e-8(带显式界);闭式分支
  面向固定 L2 动作网格(|w|≥0.0125)量级,**不宣称任意小 w
  可靠**(小 w 走级数分支,界随值给出)。
STATUS=PLAN_ONLY。
"""
import math

STATUS = "PLAN_ONLY"
FEE_DEFAULT = 0.001
SERIES_EPS = 1e-8
MIN_GRID_ABS_W = 0.0125   # 固定 L2 网格最小 |w|(参考)


def exposure_after(w, x):
    if w == 0.0:
        return 0.0
    return w * (1.0 + x) / (1.0 + w * x)


def flat_fee_frac(w, fee=FEE_DEFAULT):
    d = abs(w)
    denom = (1.0 + w * fee) if w > 0 else (1.0 - w * fee)
    return fee * (d / denom)


def flat_root_lg(w, x, fee=FEE_DEFAULT):
    nav = (1.0 - flat_fee_frac(w, fee)) * (1.0 + w * x)
    if nav <= 0.0:
        return -math.inf
    return (math.log(1.0 - flat_fee_frac(w, fee))
            + math.log1p(w * x))


def solve_x_at_exposure(w, E):
    if w == 0.0:
        raise ValueError("w=0: e2 恒 0,无切点")
    if w * E - w == 0.0:
        raise ValueError("degenerate: E=1")
    return (w - E) / (w * E - w)


def _lg_int(f, w, x_lo, x_hi):
    """∫[log f + log1p(wx)]dx → (值, lg 级数余项上界
    (闭式分支=0 标记,实际浮点舍入不在任何界内)。"""
    d1 = x_hi - x_lo
    const = d1 * math.log(f) if f != 1.0 else 0.0
    if w == 0.0:
        return const, 0.0
    xm = max(abs(x_lo), abs(x_hi))
    rho = abs(w) * xm
    if rho < SERIES_EPS:
        d2 = x_hi ** 2 - x_lo ** 2
        d3 = x_hi ** 3 - x_lo ** 3
        d4 = x_hi ** 4 - x_lo ** 4
        t1 = w * d2 / 2
        t2 = -w * w * d3 / 6
        t3 = w ** 3 * d4 / 12
        rem = (abs(w) ** 4 * xm ** 4 * d1 / 4
               / (1.0 - rho))
        return const + t1 + t2 + t3, rem
    # 闭式(相消风险区已由级数分支避开)
    def prim(x):
        return x * math.log1p(w * x) - x \
            + math.log1p(w * x) / w
    # 注:log f 项并入 const;prim 只含 log1p 部分
    return const + (prim(x_hi) - prim(x_lo)), 0.0


def _post_int(w, x_lo, x_hi):
    """∫ w(1+x)/(1+wx) dx → (值, **仅 post 级数截断上界**)。
    小 |w·x|<SERIES_EPS:三项级数+几何因子尾界
    ≤ w⁴·xm³·(d1+d2/2)/(1−ρ);否则精确原函数
    x − (1−w)/w·log1p(wx)(log1p 稳定,界=0 标记)。"""
    if w == 0.0:
        return 0.0, 0.0
    xm = max(abs(x_lo), abs(x_hi))
    rho = abs(w) * xm
    if rho < SERIES_EPS:
        d1 = x_hi - x_lo
        d2 = x_hi ** 2 - x_lo ** 2
        d3 = x_hi ** 3 - x_lo ** 3
        d4 = x_hi ** 4 - x_lo ** 4
        t1 = w * (d1 + d2 / 2)
        t2 = -w * w * (d2 / 2 + d3 / 3)
        t3 = w ** 3 * (d3 / 3 + d4 / 4)
        rem = (abs(w) ** 4 * xm ** 3
               * (d1 + abs(d2) / 2)
               / (1.0 - rho))
        return t1 + t2 + t3, rem

    def prim(x):
        return x - (1.0 - w) / w * math.log1p(w * x)
    return prim(x_hi) - prim(x_lo), 0.0


def seg_integral_bounded(a, b, w, u_lo, u_hi,
                         fee=FEE_DEFAULT,
                         mu=0.0, sig=None,
                         k=None, x_lo=None,
                         x_hi=None):
    """段积分(均匀 u 期望)+**仅 post 级数截断上界**。
    返回 (E_u 值, post_series_bound);bound 不含 lg 级数
    余项与浮点舍入——**不是总积分误差证书**。"""
    if k is None:
        k = math.sqrt(3) * (sig
                            if sig is not None
                            else 1.0)
    if k <= 0:
        raise ValueError("k must be >0")
    if x_lo is None:
        x_lo = mu + k * u_lo
    if x_hi is None:
        x_hi = mu + k * u_hi
    if x_hi <= x_lo:
        raise ValueError("empty segment")
    f = 1.0 - flat_fee_frac(w, fee)
    lg_val, _lg_rem = _lg_int(f, w, x_lo, x_hi)
    post, rem = _post_int(w, x_lo, x_hi)
    val = (0.5 / k) * (
        lg_val + a * (x_hi - x_lo) + b * post)
    return val, (0.5 / k) * abs(b) * rem


def seg_integral(a, b, w, u_lo, u_hi,
                 fee=FEE_DEFAULT, mu=0.0,
                 sig=None, k=None,
                 x_lo=None, x_hi=None):
    """同 seg_integral_bounded 但只返值(便于求和);
    需要界时用 bounded 版。"""
    v, _ = seg_integral_bounded(
        a, b, w, u_lo, u_hi, fee, mu, sig,
        k, x_lo, x_hi)
    return v
