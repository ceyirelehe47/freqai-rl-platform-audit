# -*- coding: utf-8 -*-
"""统一世界 flat 校准:纯参考适配器 v3(UNIFIED_FLAT_CALIBRATION_V1 三轮)。

**三次预算 H32 三档求解仍未运行**(验收只做 plan-only 与纯单元
测试)。真实 DP 内核已实现(_backward_induction 行随机核+线性插值+
GL 求积);runner 预约/消费/计时/RSS guard 为实际实现。
身份校验对**活消费对象**(UNIFIED_TASK/ACTION_FAMILIES/OBS_COLUMNS/
SPEC_VERSIONS/CALIB_CONFIG)每入口重算 digest。纯 numpy;零 torch/env/
p0eval/bank/confirm。门 not_specified。
"""
from __future__ import annotations

import hashlib
import json
import math
import resource
import time

import numpy as np

from rl_posctl.skill_p0.unified_course import (
    ACTION_FAMILIES, OBS_COLUMNS, SPEC_VERSIONS, UNIFIED_TASK)

ADAPTER_SCHEMA = "UNIFIED_FLAT_REF_ADAPTER_V3"
SOLVER_VERSION = "dp-h32-v3"
STATUS = "prepared_not_run"   # 三档预算求解未启动

CALIB_CONFIG = {
    "mu": 0.0012,
    "sigma_by_g": {"0": 0.03, "1": 0.06},
    "fee": 0.001,
    "H": 32,
    "initial_cash": 100.0,
    "slippage_bps": 0.0,
    "price_tick": 0.0,
    "gap": 0.0,
    "funding": "none",
    "maintenance_margin": 0.05,
    "reward_scale": 1.0,
    "noise": "sqrt(3)*sigma*U, U~Unif(-1,1)"}


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, default=str).encode()).hexdigest()


# 冻结基准(导入时取自活对象;每入口对活对象重算比对)
_FROZEN = {
    "config": _sha(CALIB_CONFIG),
    "task": _sha(UNIFIED_TASK),
    "action": _sha(ACTION_FAMILIES),
    "obs": _sha(list(OBS_COLUMNS)),
    "reward": _sha(SPEC_VERSIONS["reward"]),
    "identity": None}
IDENTITY = {
    "task_digest": _FROZEN["task"],
    "obs": list(OBS_COLUMNS),
    "action": _FROZEN["action"],
    "execution": UNIFIED_TASK["economy"]["execution"],
    "reward": SPEC_VERSIONS["reward"],
    "kernel_digest": _sha(
        UNIFIED_TASK["transition_kernel"]),
    "economy_digest": _sha(UNIFIED_TASK["economy"]),
    "task_id": UNIFIED_TASK["task_id"]}
IDENTITY_DIGEST = _sha(IDENTITY)
_FROZEN["identity"] = IDENTITY_DIGEST
CONFIG_DIGEST = _FROZEN["config"]


def _verify_binding() -> None:
    """对**活消费对象**重算 digest 并与冻结值比对——改 UNIFIED_
    TASK/CALIB_CONFIG 等任何被消费对象立即拒(非仅验标签副本)。"""
    checks = (
        (_sha(CALIB_CONFIG), _FROZEN["config"],
         "CALIB_CONFIG"),
        (_sha(UNIFIED_TASK), _FROZEN["task"],
         "UNIFIED_TASK"),
        (_sha(ACTION_FAMILIES), _FROZEN["action"],
         "ACTION_FAMILIES"),
        (_sha(list(OBS_COLUMNS)), _FROZEN["obs"],
         "OBS_COLUMNS"),
        (_sha(SPEC_VERSIONS["reward"]),
         _FROZEN["reward"], "SPEC_VERSIONS.reward"),
        (_sha(IDENTITY), _FROZEN["identity"],
         "IDENTITY"))
    for live, frozen, name in checks:
        if live != frozen:
            raise RuntimeError(
                "%s mutated after freeze (live digest "
                "mismatch): refused" % name)


TIERS = {
    "L0": {"n_dense": 81, "n_ext_per_side": 16,
           "gauss_legendre": 12, "n_actions": 41},
    "L1": {"n_dense": 161, "n_ext_per_side": 32,
           "gauss_legendre": 24, "n_actions": 81},
    "L2": {"n_dense": 321, "n_ext_per_side": 64,
           "gauss_legendre": 48, "n_actions": 161}}
BUDGET = {"max_runs": 3, "wall_clock_s": 900.0,
          "cpu_s": 600.0, "rss_gib": 1.0}
FORBIDDEN_SWEEP = ("mu", "sigma", "fee", "seed")
ACCOUNT_DENSE_DOMAIN = 1.25
ACCOUNT_EXT_DOMAIN = 20.0


def dependency_available() -> bool:
    try:
        from numpy.polynomial.legendre import leggauss
        leggauss(2)
        return True
    except Exception:
        return False


# ---- 64 题固定集 -----------------------------------------------
def build_questions() -> list:
    qs = []
    for s in (-1, 0, 1):
        for c in (0, 1):
            for q in (0.0, 0.25, 0.5, 0.75, 1.0):
                for g in (0, 1):
                    qs.append({
                        "id": "G%03d" % (len(qs) + 1),
                        "s": s, "c": c, "q": q, "g": g,
                        "remaining": 32, "total": 32,
                        "account": {"cash": 100.0,
                                    "exposure": 0.0,
                                    "solvency_raw":
                                        math.inf}})
    for s in (-1, 1):
        for g in (0, 1):
            qs.append({
                "id": "T%03d" % (len(qs) + 1),
                "s": s, "c": 1, "q": 1.0, "g": g,
                "remaining": 1, "total": 32,
                "account": {"cash": 100.0,
                            "exposure": 0.0,
                            "solvency_raw": math.inf}})
    assert len(qs) == 64
    return qs


QUESTIONS = build_questions()
_Q_LEVELS = (0.0, 0.25, 0.5, 0.75, 1.0)
_QIDS = [q["id"] for q in QUESTIONS]


# ---- 严格查询 --------------------------------------------------
def _reject_extra(node, allowed, path) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k not in allowed:
                raise ValueError(
                    "non-visible/extra field %r at %r"
                    % (k, path))
            _reject_extra(
                v, allowed.get(k, {}) if isinstance(
                    allowed.get(k), dict) else (),
                path + [k])


def make_query(question: dict) -> dict:
    _verify_binding()
    top_allowed = {"s", "c", "q", "g", "remaining",
                   "total", "account", "id"}
    if set(question) - top_allowed:
        raise ValueError(
            "query carries non-visible fields %r"
            % sorted(set(question) - top_allowed))
    s, c, q, g = (question["s"], question["c"],
                  question["q"], question["g"])
    for name, v, dom in (("s", s, (-1, 0, 1)),
                         ("c", c, (0, 1)),
                         ("g", g, (0, 1))):
        if isinstance(v, bool) or not isinstance(
                v, int) or v not in dom:
            raise ValueError(
                "%s must be int in %r: %r"
                % (name, dom, v))
    if (isinstance(q, bool) or not isinstance(
            q, (int, float))
            or float(q) not in _Q_LEVELS):
        raise ValueError(
            "q must be one of the five levels: %r" % (q,))
    for f in ("remaining", "total"):
        v = question[f]
        if (isinstance(v, bool) or not isinstance(v, int)
                or v < 1):
            raise ValueError(
                "%s must be positive int: %r" % (f, v))
    if question["remaining"] > question["total"]:
        raise ValueError("remaining > total")
    if question["total"] != CALIB_CONFIG["H"]:
        raise ValueError(
            "this calibration package fixes total=%d; "
            "got %r" % (CALIB_CONFIG["H"],
                        question["total"]))
    acct = question["account"]
    _flat_ok = (
        isinstance(acct, dict)
        and set(acct) == {"cash", "exposure",
                          "solvency_raw"}
        and isinstance(acct.get("cash"),
                       (int, float))
        and not isinstance(acct.get("cash"), bool)
        and float(acct["cash"]) == 100.0
        and isinstance(acct.get("exposure"),
                       (int, float))
        and not isinstance(acct.get("exposure"),
                           bool)
        and float(acct["exposure"]) == 0.0
        and isinstance(
            acct.get("solvency_raw"), float)
        and not isinstance(
            acct.get("solvency_raw"), bool)
        and math.isinf(acct["solvency_raw"])
        and acct["solvency_raw"] > 0)
    if not _flat_ok:
        raise ValueError(
            "account must be exactly flat cash100/"
            "exposure0(non-bool)/solvency+inf: %r"
            % (acct,))
    _reject_extra(question, {
        "s": (), "c": (), "q": (), "g": (),
        "remaining": (), "total": (), "id": (),
        "account": {"cash": (), "exposure": (),
                    "solvency_raw": ()}}, [])
    return {"s": s, "c": c, "q": q, "g": g,
            "remaining": question["remaining"],
            "total": question["total"],
            "account": acct}


# ---- 网格 ------------------------------------------------------
def action_grid(tier: str) -> np.ndarray:
    if tier not in TIERS:
        raise ValueError("unknown tier %r" % tier)
    n = TIERS[tier]["n_actions"]
    w = np.linspace(-1.0, 1.0, n)
    return w


def account_grid(tier: str) -> np.ndarray:
    if tier not in TIERS:
        raise ValueError("unknown tier %r" % tier)
    t = TIERS[tier]
    dense = np.linspace(-ACCOUNT_DENSE_DOMAIN,
                        ACCOUNT_DENSE_DOMAIN, t["n_dense"])
    ratio = (ACCOUNT_EXT_DOMAIN /
             ACCOUNT_DENSE_DOMAIN) ** (
        1.0 / t["n_ext_per_side"])
    ext = ACCOUNT_DENSE_DOMAIN * ratio ** np.arange(
        1, t["n_ext_per_side"] + 1)
    return np.sort(np.unique(np.round(np.concatenate(
        [-ext[::-1], dense, ext]), 12)))


# ---- 精确经济原语 ----------------------------------------------
def hold_step(e: float, r: float) -> tuple:
    _verify_binding()
    nav = 1.0 + e * r
    if nav <= 0:
        return -math.inf, e
    if e == 0.0:
        return math.log(nav), 0.0
    return math.log(nav), e * (1.0 + r) / nav


def rebal_step(e: float, w: float, r: float) -> tuple:
    _verify_binding()
    fee = CALIB_CONFIG["fee"]
    d = w - e
    denom = (1.0 + w * fee) if w > e else (1.0 - w * fee)
    fee_frac = fee * abs(d / denom)
    growth = 1.0 + w * r
    nav = (1.0 - fee_frac) * growth
    if nav <= 0:
        return -math.inf, w
    if w == 0.0:
        return math.log(nav), 0.0
    return math.log(nav), w * (1.0 + r) / growth


def liq_value(post_w: float) -> float:
    """终端清算腿:**只收 post_w**(末 bar 结算后的最终比例),
    不再漂移、不加收益;先合法/正净值判断再 log。"""
    _verify_binding()
    if (isinstance(post_w, bool)
            or not isinstance(post_w, (int, float))
            or not math.isfinite(float(post_w))):
        raise ValueError(
            "post_w must be finite number: %r" % (post_w,))
    post_w = float(post_w)
    if post_w == 0.0:
        return 0.0
    fee = CALIB_CONFIG["fee"]
    val = 1.0 - fee * abs(post_w)   # 先判合法
    if val <= 0.0:
        return -math.inf
    return math.log(val)


# ---- 转移矩阵(A11 核逐项:重抽可回当前值) ---------------------
def build_transition_matrices() -> dict:
    _verify_binding()
    k = UNIFIED_TASK["transition_kernel"]
    out = {}
    for comp in ("s", "c", "g"):
        vals = k[comp]["values"]
        n = len(vals)
        hold = float(k[comp]["hold_p"])
        res = float(k[comp]["resample_p"])
        m = np.full((n, n), res / n)   # 重抽均匀含原值
        idx = np.arange(n)
        m[idx, idx] += hold            # P(i|i)=res/n+hold
        out[comp] = {"values": list(vals), "matrix": m}
    qv = k["q"]["values"]
    hold = float(k["q"]["hold_p"])
    fresh = np.array(k["q"]["fresh_p"], dtype=float)
    fresh = fresh / fresh.sum()
    mq = 0.2 * np.tile(fresh, (len(qv), 1))
    idx = np.arange(len(qv))
    mq[idx, idx] += hold    # P=.8I+.2*fresh(q0 对角=.825)
    out["q"] = {"values": list(qv), "matrix": mq}
    for comp in ("s", "c", "g", "q"):
        assert np.allclose(
            out[comp]["matrix"].sum(axis=1), 1.0), comp
    return out


# ---- 状态空间 --------------------------------------------------
_S_VALUES = (-1, 0, 1)
_C_VALUES = (0, 1)
_Q_VALUES = (0.0, 0.25, 0.5, 0.75, 1.0)
_G_VALUES = (0, 1)


def state_space() -> list:
    return [(s, c, q, g) for s in _S_VALUES
            for c in _C_VALUES for q in _Q_VALUES
            for g in _G_VALUES]


def full_state_transition() -> np.ndarray:
    """60×60 联合转移=分量乘积(A11:逐 bar 分量独立)。"""
    tm = build_transition_matrices()
    P = np.ones((60, 60))
    si = {v: i for i, v in enumerate(
        tm["s"]["values"])}
    ci = {v: i for i, v in enumerate(
        tm["c"]["values"])}
    qi = {v: i for i, v in enumerate(
        tm["q"]["values"])}
    gi = {v: i for i, v in enumerate(
        tm["g"]["values"])}
    states = state_space()
    for a, (s0, c0, q0, g0) in enumerate(states):
        for b, (s1, c1, q1, g1) in enumerate(states):
            P[a, b] = (
                tm["s"]["matrix"][si[s0], si[s1]]
                * tm["c"]["matrix"][ci[c0], ci[c1]]
                * tm["q"]["matrix"][qi[q0], qi[q1]]
                * tm["g"]["matrix"][gi[g0], gi[g1]])
    assert np.allclose(P.sum(axis=1), 1.0)
    return P


# ---- 键 --------------------------------------------------------
def dp_cache_key(tier: str) -> str:
    _verify_binding()
    return _sha({
        "identity": IDENTITY_DIGEST,
        "config": CONFIG_DIGEST,
        "tier": TIERS[tier],
        "actions": [float(x) for x in action_grid(tier)],
        "accounts": [float(x) for x in
                     account_grid(tier)],
        "solver": SOLVER_VERSION})


def query_cache_key(query: dict, tier: str) -> str:
    return _sha({
        "base": dp_cache_key(tier),
        "state": [query["s"], query["c"],
                  float(query["q"]), query["g"]],
        "account": {"cash": query["account"]["cash"],
                    "exposure": query["account"][
                        "exposure"]},
        "remaining": query["remaining"],
        "total": query["total"]})


# ---- 真实 DP 内核 ----------------------------------------------
def _interp_weights(points: np.ndarray,
                    grid: np.ndarray):
    """线性插值索引/权重(外推取边界值)。"""
    n = len(grid)
    idx = np.searchsorted(grid, points, side="right") - 1
    idx = np.clip(idx, 0, n - 2)
    frac = (points - grid[idx]) / (
        grid[idx + 1] - grid[idx])
    frac = np.clip(frac, 0.0, 1.0)
    return idx, frac


def forced_liquidation_value(e: float,
                             r: float) -> float:
    """风险越界(|e'|>延伸域)时的强制清算值(原参考语义):
    在触发时点收费清仓回 flat——log(growth)+log(1-fee·|post|),
    之后续值在 flat 上。仅当净值 growth<=0 或清算后权益
    1-fee·|post|<=0 才 -inf。e=20,r=-.04: growth=.2,post=96,
    因子 .904 → 有限;post=1901 → 因子 -0.901 → -inf。"""
    _verify_binding()
    lg, post = hold_step(e, r)
    if not math.isfinite(lg):
        return -math.inf
    fee = CALIB_CONFIG["fee"]
    factor = 1.0 - fee * abs(post)
    if factor <= 0.0:
        return -math.inf
    return lg + math.log(factor)


def forced_invalid(post_e, growth) -> bool:
    """真无效判定:净值非正或清算后权益非正(仅此才 -inf)。"""
    _verify_binding()
    if (isinstance(post_e, bool)
            or not isinstance(post_e, (int, float))
            or not math.isfinite(float(post_e))):
        return True
    if not isinstance(growth, (int, float)) \
            or not math.isfinite(float(growth)):
        return True
    if float(growth) <= 0.0:
        return True
    return (1.0 - CALIB_CONFIG["fee"]
            * abs(float(post_e))) <= 0.0


def _hold_support_mask(acc, mu_vec, sig_vec,
                       fee):
    """HOLD 支撑检查(纯代数,不跑积分):
    L(r)=1+e*r-fee*|e|*(1+r) 关于 r 仿射 → 支撑端点
    r_lo=mu-√3σ, r_hi=mu+√3σ。任一端点 L<0 → 正测度失败
    (HOLD 臂 -inf);恰 =0 记边界(不当正概率破产)。"""
    r_lo = mu_vec - math.sqrt(3) * sig_vec
    r_hi = mu_vec + math.sqrt(3) * sig_vec
    a = acc[None, :]
    Llo = (1.0 + a * r_lo[:, None]
           - fee * np.abs(a) * (1.0 + r_lo)[:, None])
    Lhi = (1.0 + a * r_hi[:, None]
           - fee * np.abs(a) * (1.0 + r_hi)[:, None])
    fails = (Llo < 0) | (Lhi < 0)
    edge = (Llo == 0) | (Lhi == 0)
    return fails, edge


def _risk_select_hold(Vi, e_next, growth, Vavg,
                      fee, ext, flat_i):
    """HOLD 风险选择:Vi(含正常插值续值)在越界格替换为
    **仅清算费+下一 flat 续值**(当期增长只由外层 lg 计一次);
    真无效(净值/清算后权益≤0)→-inf。全部 (S,K)。"""
    risk = np.abs(e_next) > ext
    dead = (growth <= 0) | (
        1.0 - fee * np.abs(e_next) <= 0)
    fee_log = np.log(np.maximum(
        1.0 - fee * np.abs(e_next), 1e-300))
    forced = (fee_log
              + Vavg[:, flat_i:flat_i + 1])
    Vi = np.where(risk & ~dead, forced, Vi)
    Vi[dead] = -np.inf
    return Vi


def _risk_select_rebal(Vi1d, e_row, growth,
                       Vavg, fee, ext, flat_i):
    """REBAL 风险选择(一维):e_row/growth 均为 (S,);
    正常插值续值 Vi1d (S,);越界→清算费+Vavg[:,flat_i] (S,);
    真无效→-inf;返回 (S,1)(唯一一次升维)。"""
    risk = (np.abs(e_row) > ext)
    dead = (growth <= 0) | (
        1.0 - fee * np.abs(e_row) <= 0)
    fee_log = np.log(np.maximum(
        1.0 - fee * np.abs(e_row), 1e-300))
    flat_cont = Vavg[np.arange(Vavg.shape[0]),
                     flat_i]
    sel = np.where(risk & ~dead,
                   fee_log + flat_cont, Vi1d)
    sel[dead] = -np.inf
    return sel[:, None]


def _backward_induction(profile: dict,
                        checkpoint=None) -> dict:
    """真实后向归纳(纯函数,无预算副作用)。
    profile: {actions, accounts, gl, bars, states, P,
    mu_vec, sigma_vec, fee}。V[t] 对每状态×账户。"""
    acts = profile["actions"]
    acc = profile["accounts"]
    gl = profile["gl"]
    bars = int(profile["bars"])
    P = profile["P"]                # (S,S)
    mu = profile["mu_vec"]          # (S,)
    sig = profile["sigma_vec"]      # (S,)
    fee = profile["fee"]
    S, K = len(mu), len(acc)
    ext = ACCOUNT_EXT_DOMAIN
    from numpy.polynomial.legendre import leggauss
    u, wu = leggauss(gl)

    def _ck(bar, phase):
        if checkpoint is None:
            return None
        return checkpoint(bar, phase)

    x_all = (mu[:, None] + (np.sqrt(3) * sig)[:, None]
             * u[None, :])          # (S, gl)
    w_nodes = 0.5 * wu              # U∈[-1,1] 密度 1/2
    pre = _ck(-1, "alloc_V")
    if pre:
        return {"partial": True, "stop_reason": pre,
                "bars_done": -1, "V": None,
                "solver": SOLVER_VERSION}
    V = np.empty((bars + 1, S, K))
    # 终端:清算腿只收当前 post_w(=e)
    V[0] = np.log(np.maximum(
        1.0 - fee * np.abs(acc[None, :]), 1e-300))
    V[0][np.where(
        1.0 - fee * np.abs(acc[None, :]) <= 0)[1]] = -np.inf
    flat_i = K // 2
    sup_fail, sup_edge = _hold_support_mask(
        acc, mu, sig, fee)
    for t in range(1, bars + 1):
        why = _ck(t, "bar_begin")
        if why:
            return {"partial": True,
                    "stop_reason": why,
                    "bars_done": t - 1, "V": V[:t],
                    "accounts": acc,
                    "actions": np.asarray(acts),
                    "gl": gl, "bars": bars,
                    "solver": SOLVER_VERSION}
        Vprev = V[t - 1]
        Vavg = P @ Vprev            # 期望在插值前(线性可交换)
        best = np.full((S, K), -np.inf)
        first_why = None
        for w in np.concatenate([acts, [None]]):
            why_w = _ck(t, "action_loop")
            if why_w is not None and \
                    first_why is None:
                first_why = why_w
            if first_why is not None:
                break
            # None=HOLD(目标=当前 e,零费)
            Q = np.zeros((S, K))
            for j in range(gl):
                x = x_all[:, j]              # (S,)
                if w is None:
                    # HOLD:数量固定;e 随 x 漂移(逐账户不同)
                    growth = (1.0
                              + acc[None, :] * x[:, None])
                    lg = np.log(np.maximum(growth, 1e-300))
                    lg[growth <= 0] = -np.inf
                    e_next = (acc[None, :]
                              * (1.0 + x[:, None])
                              / np.maximum(growth, 1e-300))
                    dead = growth <= 0
                    e_next = np.where(dead, acc[None, :],
                                      e_next)
                    idx, frac = _interp_weights(
                        e_next.ravel(), acc)
                    idx = idx.reshape(S, K)
                    frac = frac.reshape(S, K)
                    rows = np.arange(S)[:, None]
                    Vi = (Vavg[rows, idx] * (1.0 - frac)
                          + Vavg[rows, np.minimum(
                              idx + 1, K - 1)] * frac)
                    risk_h = np.abs(e_next) > ext
                    dead_h = (growth <= 0) | (
                        1.0 - fee * np.abs(e_next)
                        <= 0)
                    flat_i = K // 2   # 账户网格含 0(奇数 dense)
                    forced_h = (
                        np.log(np.maximum(
                            growth, 1e-300))
                        + np.log(np.maximum(
                            1.0 - fee * np.abs(
                                e_next), 1e-300))
                        + Vavg[:, flat_i:flat_i + 1])
                    Vi = np.where(
                        risk_h & ~dead_h,
                        forced_h, Vi)
                    Vi[dead_h] = -np.inf
                else:
                    # REBAL:目标 w 固定;费随起始敞口
                    d = w - acc[None, :]
                    denom = np.where(
                        d > 0, 1.0 + w * fee,
                        1.0 - w * fee)
                    fee_frac = fee * np.abs(d / denom)
                    growth = 1.0 + w * x        # (S,)
                    nav = ((1.0 - fee_frac)
                           * growth[:, None])   # (S,K)
                    lg = np.log(np.maximum(nav, 1e-300))
                    lg[nav <= 0] = -np.inf
                    e_row = np.where(
                        w == 0.0, 0.0,
                        w * (1.0 + x) / np.maximum(
                            growth, 1e-300))    # (S,)
                    i2, f2 = _interp_weights(e_row, acc)
                    Vi1d = (Vavg[np.arange(S), i2]
                            * (1.0 - f2)
                            + Vavg[np.arange(S), np.minimum(
                                i2 + 1, K - 1)] * f2)
                    Vi = _risk_select_rebal(
                        Vi1d, e_row, growth, Vavg,
                        fee, ext, flat_i)
                step = lg + Vi
                step = np.where(
                    np.isfinite(step), step, -np.inf)
                Q += w_nodes[j] * step
            best = np.maximum(best, Q)
        if first_why is not None:
            return {"partial": True,
                    "stop_reason": first_why,
                    "bars_done": t - 1, "V": V[:t],
                    "accounts": acc,
                    "actions": np.asarray(acts),
                    "gl": gl, "bars": bars,
                    "solver": SOLVER_VERSION}
        V[t] = best
    return {"V": V, "accounts": acc,
            "actions": np.asarray(acts),
            "gl": gl, "bars": bars,
            "solver": SOLVER_VERSION}


def _tier_profile(tier: str) -> dict:
    _verify_binding()
    states = state_space()
    mu = np.array([s * c * q * CALIB_CONFIG["mu"]
                   for s, c, q, g in states])
    sig = np.array([
        CALIB_CONFIG["sigma_by_g"][str(g)]
        for s, c, q, g in states])
    return {"actions": action_grid(tier),
            "accounts": account_grid(tier),
            "gl": TIERS[tier]["gauss_legendre"],
            "bars": CALIB_CONFIG["H"],
            "states": states,
            "P": full_state_transition(),
            "mu_vec": mu, "sigma_vec": sig,
            "fee": CALIB_CONFIG["fee"]}


# ---- 预算 guard(实际预约/消费/计时/RSS) -----------------------
_RUNS = {"used": 0, "open": None,
         "tiers_used": []}
_JOB = None        # 单一活时钟:首包创建,横跨三档/query/analysis
_now_wall = time.perf_counter
_now_cpu = time.process_time


def _job() -> dict:
    """首包只建一次;之后所有检查读真实 elapsed。"""
    global _JOB
    if _JOB is None:
        _JOB = {"wall0": _now_wall(),
                "cpu0": _now_cpu()}
    return _JOB


def _job_elapsed() -> tuple:
    j = _job()
    return (_now_wall() - j["wall0"],
            _now_cpu() - j["cpu0"])


def _now_rss_gib() -> float:
    return (resource.getrusage(
        resource.RUSAGE_SELF).ru_maxrss
        / (1024 * 1024))


def _begin_run(tier: str) -> dict:
    if _RUNS["open"] is not None:
        raise RuntimeError(
            "a run is already open (%s)"
            % _RUNS["open"]["tier"])
    if _RUNS["used"] >= BUDGET["max_runs"]:
        raise RuntimeError(
            "budget exhausted: %d/%d runs used — "
            "4th run refused"
            % (_RUNS["used"], BUDGET["max_runs"]))
    if tier in _RUNS["tiers_used"]:
        raise RuntimeError(
            "tier %r already consumed a run — repeat "
            "refused" % tier)
    wall, cpu = _job_elapsed()
    if (wall > BUDGET["wall_clock_s"]
            or cpu > BUDGET["cpu_s"]):
        raise RuntimeError(
            "job budget already exceeded "
            "(wall=%.1fs cpu=%.1fs) — new run "
            "refused" % (wall, cpu))
    if _now_rss_gib() > BUDGET["rss_gib"]:
        raise RuntimeError(
            "rss budget already exceeded — new run "
            "refused")
    _RUNS["used"] += 1
    _RUNS["tiers_used"].append(tier)
    _RUNS["open"] = {
        "tier": tier, "seq": _RUNS["used"],
        "wall0": _now_wall(), "cpu0": _now_cpu()}
    return dict(_RUNS["open"])


def _run_checkpoint(handle: dict) -> tuple:
    """读 job 真实 elapsed(不叠加旧 total、不按段重置)。"""
    wall, cpu = _job_elapsed()
    rss = _now_rss_gib()
    why = None
    if wall > BUDGET["wall_clock_s"]:
        why = "wall_clock"
    elif cpu > BUDGET["cpu_s"]:
        why = "cpu"
    elif rss > BUDGET["rss_gib"]:
        why = "rss"
    return why, {"cum_wall_s": wall, "cum_cpu_s": cpu,
                 "rss_gib": rss}


def _finish_run(stop_reason: str = None) -> dict:
    if _RUNS["open"] is None:
        raise RuntimeError("no open run")
    h = _RUNS["open"]
    why, meters = _run_checkpoint(h)
    _RUNS["open"] = None
    return {"tier": h["tier"], "seq": h["seq"],
            "stop_reason": why or (stop_reason
                                   or "completed"),
            **meters}


def budget_allows(wall_elapsed: float,
                  cpu_elapsed: float) -> tuple:
    """外部预算预判:候选增量叠加 job 真实 elapsed。"""
    if _RUNS["used"] >= BUDGET["max_runs"]:
        return False, "runs_exhausted(%d)" % _RUNS["used"]
    wall, cpu = _job_elapsed()
    if wall + wall_elapsed > BUDGET["wall_clock_s"]:
        return False, "wall_clock"
    if cpu + cpu_elapsed > BUDGET["cpu_s"]:
        return False, "cpu"
    if _now_rss_gib() > BUDGET["rss_gib"]:
        return False, "rss"
    return True, "ok"


def solve_plan(tier: str) -> dict:
    _verify_binding()
    t = TIERS[tier]
    acc = account_grid(tier)
    n_states = 60
    per_cell = (t["n_actions"] + 1) * t["gauss_legendre"]
    cells = n_states * len(acc) * CALIB_CONFIG["H"]
    return {"tier": tier, "states": n_states,
            "bars": CALIB_CONFIG["H"],
            "actions": t["n_actions"] + 1,   # +HOLD
            "account_points": len(acc),
            "gl": t["gauss_legendre"],
            "total_step_evals": int(
                cells * per_cell),
            "est_value_arrays_gib": round(
                (CALIB_CONFIG["H"] + 1) * n_states
                * len(acc) * 8 / 2**30, 6),
            "runs_used": _RUNS["used"],
            "runs_max": BUDGET["max_runs"]}


def solve_reference(tier: str) -> dict:
    """一次档内 H32 后向归纳:名额即时消费(失败也计)、逐
    bar/大分配 checkpoint(三档累计墙/CPU+RSS)、越限停止保留
    部分状态且不可 completed;同档重复与第 4 次拒。验收前禁调。"""
    _verify_binding()
    if tier not in TIERS:
        raise ValueError("unknown tier %r" % tier)
    h = _begin_run(tier)

    def _ck(bar, phase):
        why, _m = _run_checkpoint(h)
        return why

    try:
        prof = _tier_profile(tier)
        res = _backward_induction(prof, checkpoint=_ck)
        stopped = bool(res.get("partial"))
        fin = _finish_run(
            res.get("stop_reason") if stopped
            else None)
    except Exception:
        try:
            _finish_run("exception")
        except RuntimeError:
            pass          # 已被 finally 关闭
        raise
    res["budget"] = fin
    res["dp_key"] = dp_cache_key(tier)
    res["tier"] = tier
    res["completed"] = (fin["stop_reason"]
                        == "completed")
    if res["completed"] and res.get("V") \
            is not None and not np.isfinite(
                np.asarray(res["V"])).all():
        res["completed"] = False
        res["partial"] = True
        res["stop_reason"] = "value_domain"
    if not res["completed"]:
        res["partial"] = True
        res.setdefault("stop_reason",
                       fin["stop_reason"])
    return res


def _budget_gate() -> None:
    """query/analysis/表验真共用同一 job 活时钟预算门
    (真实 elapsed,横跨三档与全部下游消费)。"""
    wall, cpu = _job_elapsed()
    if wall > BUDGET["wall_clock_s"]:
        raise RuntimeError(
            "job budget exceeded (wall) — downstream "
            "consumption refused")
    if cpu > BUDGET["cpu_s"]:
        raise RuntimeError(
            "job budget exceeded (cpu) — downstream "
            "consumption refused")
    if _now_rss_gib() > BUDGET["rss_gib"]:
        raise RuntimeError(
            "job budget exceeded (rss) — downstream "
            "consumption refused")


def validate_dp_tables(tier: str,
                       tables: dict) -> None:
    """DP 表验真(真接线):tier/solver/dp_key/真实动作与账户
    坐标/GL/形状((H+1,60,len(acc)))/完成标志全绑定。"""
    _verify_binding()
    if tier not in TIERS:
        raise ValueError("unknown tier %r" % tier)
    if tables.get("solver") != SOLVER_VERSION:
        raise ValueError("solver mismatch")
    if tables.get("tier") != tier:
        raise ValueError("tier identity mismatch")
    if tables.get("dp_key") != dp_cache_key(tier):
        raise ValueError("dp_key mismatch")
    if not tables.get("completed"):
        raise ValueError(
            "tables not completed (stop=%r)"
            % tables.get("stop_reason"))
    if tables.get("partial"):
        raise ValueError("partial tables rejected")
    if tables.get("bars") != CALIB_CONFIG["H"]:
        raise ValueError(
            "bars must equal H=%d; got %r"
            % (CALIB_CONFIG["H"],
               tables.get("bars")))
    # 完成状态必须一致:completed 与任何中断/异常原因矛盾即拒
    for path, reason in (
            ("stop_reason", tables.get("stop_reason")),
            ("budget.stop_reason",
             (tables.get("budget") or {}).get(
                 "stop_reason"))):
        if reason not in (None, "completed"):
            raise ValueError(
                "inconsistent completion: %s=%r "
                "while completed=True" % (path,
                                          reason))
    if not np.array_equal(
            np.asarray(tables["actions"]),
            action_grid(tier)):
        raise ValueError("action coordinates mismatch")
    acc_t = account_grid(tier)
    if not np.array_equal(
            np.asarray(tables["accounts"]), acc_t):
        raise ValueError("account coordinates mismatch")
    if tables.get("gl") != TIERS[tier][
            "gauss_legendre"]:
        raise ValueError("gl mismatch")
    V = np.asarray(tables["V"])
    want = (CALIB_CONFIG["H"] + 1, 60, len(acc_t))
    if V.shape != want:
        raise ValueError(
            "V shape %r != %r" % (V.shape, want))
    # 固定域不变量:任意网格 |e|≤20 可 REBAL0(费≤.02)后永
    # flat → max-value 必有限;内部高杠杆 HOLD 臂可 -inf 但
    # 不应逃出 max。任何非有限 V(含 -inf)都 invalid。
    if not np.isfinite(V).all():
        n_bad = int((~np.isfinite(V)).sum())
        raise ValueError(
            "V contains %d non-finite entries "
            "(fixed-domain max must be finite)"
            % n_bad)


def query_Q(query: dict, tier: str,
            dp_tables: dict) -> dict:
    """逐题输出(需已验真 dp_tables;查询内容重验规范):
    Q_HOLD+全部动作 Q、状态/期限、grid/task 键。"""
    _verify_binding()
    _budget_gate()
    validate_dp_tables(tier, dp_tables)
    q = make_query(query)
    acc = dp_tables["accounts"]
    V = dp_tables["V"]
    states = state_space()
    try:
        si = states.index((
            q["s"], q["c"], float(q["q"]), q["g"]))
    except ValueError:
        raise ValueError("query state not in space")
    t = q["remaining"]
    if not 1 <= t <= CALIB_CONFIG["H"]:
        raise ValueError("remaining outside 1..H")
    e0 = float(q["account"]["exposure"])
    mu = (q["s"] * q["c"] * q["q"]
          * CALIB_CONFIG["mu"])
    sig = CALIB_CONFIG["sigma_by_g"][str(q["g"])]
    from numpy.polynomial.legendre import leggauss
    u, wu = leggauss(dp_tables["gl"])
    P = full_state_transition()
    Vprev = V[t - 1] if t >= 1 else V[0]
    Vavg = P @ Vprev
    row = Vavg[si]

    def val_at(e):
        i, fr = _interp_weights(np.array([e]), acc)
        return float(row[i[0]] * (1 - fr[0])
                     + row[min(i[0] + 1,
                               len(acc) - 1)] * fr[0])

    q_out = {}
    for w in dp_tables["actions"]:
        _budget_gate()            # 每动作检查
        tot = 0.0
        for ui, wi in zip(u, wu):
            x = mu + math.sqrt(3) * sig * ui
            lg, e2 = rebal_step(e0, float(w), x)
            if not math.isfinite(lg):
                tot += 0.5 * wi * -math.inf
                continue
            tot += 0.5 * wi * (lg + val_at(e2))
        q_out[float(w)] = tot
    q_hold = 0.0
    for ui, wi in zip(u, wu):
        x = mu + math.sqrt(3) * sig * ui
        lg, e2 = hold_step(e0, x)
        if not math.isfinite(lg):
            q_hold += 0.5 * wi * -math.inf
            continue
        q_hold += 0.5 * wi * (lg + val_at(e2))
    _budget_gate()                # 返回前检查
    return {"qid_state": si,
            "state": [q["s"], q["c"], float(q["q"]),
                      q["g"]],
            "remaining": t, "total": q["total"],
            "q_hold": q_hold, "q_rebals": q_out,
            "dp_key": dp_tables.get("dp_key"),
            "grid": {"n_actions":
                     len(dp_tables["actions"]),
                     "gl": dp_tables["gl"]}}


# ---- 完整性强制(64×3) ------------------------------------------
def validate_tier_outputs(per_tier: dict) -> None:
    """64×3 内容级强制:身份/坐标/形状经 validate_dp_tables;
    每条输出须携带与规范题一致的 (s,c,q,g,remaining,total) 与
    全动作 Q 集——只有 ID 的伪元数据/改内容保 ID/缺 Q 全拒。"""
    _verify_binding()
    if set(per_tier) != set(TIERS):
        raise ValueError(
            "need exactly tiers L0/L1/L2, got %r"
            % sorted(per_tier))
    canon = {q["id"]: q for q in QUESTIONS}
    for tier, tables in per_tier.items():
        validate_dp_tables(tier, tables)
        qs = tables.get("questions", [])
        ids = [q.get("id") for q in qs]
        if ids != _QIDS:
            missing = [i for i in _QIDS
                       if i not in ids]
            dup = len(ids) - len(set(ids))
            raise ValueError(
                "tier %r questions invalid: "
                "missing=%r duplicates=%d"
                % (tier, missing[:4], dup))
        acts = set(float(x) for x in
                   action_grid(tier))
        for entry in qs:
            c = canon[entry["id"]]
            for f in ("s", "c", "q", "g",
                      "remaining", "total"):
                if entry.get(f) != c[f]:
                    raise ValueError(
                        "tier %r qid %s field %s "
                        "content mismatch (forged "
                        "metadata rejected)"
                        % (tier, entry["id"], f))
            qr = entry.get("q_rebals")
            if (not isinstance(qr, dict)
                    or set(map(float, qr)) != acts):
                raise ValueError(
                    "tier %r qid %s q_rebals must "
                    "cover the full action set"
                    % (tier, entry["id"]))

            def _ok_q(x):
                return (isinstance(x, float)
                        and (math.isfinite(x)
                             or x == -math.inf))

            if not _ok_q(entry.get("q_hold")) or \
                    not all(_ok_q(v)
                            for v in qr.values()):
                raise ValueError(
                    "tier %r qid %s Q values "
                    "invalid (NaN/+inf/str/bool "
                    "rejected; only finite or "
                    "exact -inf allowed)"
                    % (tier, entry["id"]))


# ---- 跨档分析(动作集合漂移感知) --------------------------------
def analyze_tiers(per_tier_full: dict) -> dict:
    """唯一正式分析入口:per_tier_full={tier: tables(含
    questions 全 64 条)}——先 validate_tier_outputs(缺/重复/
    错身份/旧 qid→Q 格式均拒),再逐题三档分析。
    判定:act 仅当 margin>不确定尺度;best diff≤0→no_act;
    0<margin≤不确定尺度→not_established(无法判定,与无行动
    分开);换类/反号/漂移→not_established;NaN→unstable。"""
    _verify_binding()
    _budget_gate()
    validate_tier_outputs(per_tier_full)
    per_tier = {
        t: {e["id"]: {"q_hold": e["q_hold"],
                      "q_rebals": e["q_rebals"]}
            for e in tables["questions"]}
        for t, tables in per_tier_full.items()}
    tiers = sorted(per_tier)
    if len(tiers) < 2:
        return {"status": "not_established",
                "reason": "need >=2 tiers"}
    out = {}
    qids = set.intersection(
        *(set(per_tier[t]) for t in tiers))
    fine = tiers[-1]
    for qid in sorted(qids):
        _budget_gate()            # 每题检查
        rows = {t: per_tier[t][qid] for t in tiers}
        bests, margins, act_class = {}, {}, {}
        for t, row in rows.items():
            if (not _q_ok(row["q_hold"]) or
                    row["q_hold"] == -math.inf or
                    any(q == -math.inf
                        for q in
                        row["q_rebals"].values())):
                # 64 flat 根上意外 -inf:不可判定,不产
                # act/no_act(也避免 -inf−(−inf)=NaN 被
                # max 隐藏)
                out[qid] = {
                    "status": "not_established",
                    "reason": ("non-finite Q at flat "
                               "root (unexpected "
                               "-inf)")}
                rows[t] = None
                break
            diffs = {w: q - row["q_hold"]
                     for w, q in
                     row["q_rebals"].items()}
            vals = sorted(diffs.values())
            if (not vals) or any(
                    not _q_ok(v) for v in vals):
                act_class[t] = "unstable"
                continue
            bw = max(diffs, key=diffs.get)
            bests[t] = bw
            margins[t] = diffs[bw]
            act_class[t] = ("act" if diffs[bw] > 0
                            else "no_act")
        if any(rows.get(t) is None
               for t in tiers):
            continue        # 已判 not_established
        if any(v == "unstable"
               for v in act_class.values()):
            out[qid] = {"status": "unstable"}
            continue
        classes = set(act_class.values())
        bws = [bests[t] for t in tiers]
        drift = max(bws) - min(bws)
        sign_set = {math.copysign(1.0, b)
                    for b in bws if b != 0}
        if len(classes) > 1 or len(sign_set) > 1:
            out[qid] = {
                "status": "not_established",
                "reason": "best-action class/sign changed",
                "best_w": bests,
                "act_class": act_class}
            continue
        acts0 = sorted(rows[tiers[0]]["q_rebals"])
        if len(acts0) >= 2:
            spacing0 = min(
                b - a for a, b in
                zip(acts0, acts0[1:]))
        else:
            spacing0 = float("inf")
        if spacing0 != float("inf") and \
                drift > spacing0 / 2.0:
            out[qid] = {
                "status": "not_established",
                "reason": ("best_w drifted across "
                           "tiers (%.3f > spacing/2 "
                           "%.4f)" % (drift,
                                      spacing0 / 2)),
                "best_w": bests}
            continue
        common = set(rows[tiers[0]]["q_rebals"])
        for t in tiers[1:]:
            common &= set(rows[t]["q_rebals"])
        ref = rows[fine]
        val_dev = 0.0
        for t in tiers[:-1]:
            for w in common:
                val_dev = max(
                    val_dev,
                    abs(rows[t]["q_rebals"][w]
                        - ref["q_rebals"][w]))
        ms = [margins[t] for t in tiers]
        cross = max(ms) - min(ms)
        uncertainty = max(cross, val_dev, 1e-12)
        m_final = margins[fine]
        near = sorted(
            w for w, d in ref["q_rebals"].items()
            if d - ref["q_hold"] >= m_final - 1e-12)
        if m_final <= 0.0:
            status = "no_act"       # 无行动(可判)
        elif m_final > uncertainty:
            status = "act"
        else:
            status = "not_established"   # 无法判定
        out[qid] = {
            "status": status,
            "best_w": bests,
            "margin_final": m_final,
            "cross_tier_margin_diff": cross,
            "common_coord_value_dev": val_dev,
            "uncertainty_q_units": uncertainty,
            "near_opt_points_final": near,
            "near_opt_note": (
                "numerical max-tie set only "
                "(1e-12 equality); NOT an error-"
                "aware near-optimal set and NOT a "
                "continuous band"),
            "value_uncertainty_band_q_units": [
                m_final - uncertainty,
                m_final + uncertainty]}
    _budget_gate()                # 返回前检查
    return out


def _q_ok(v) -> bool:
    return (isinstance(v, float)
            and (math.isfinite(v)
                 or v == -math.inf))


# ---- 解析边界(尾题负控) ----------------------------------------
def last_bar_fee_boundary() -> dict:
    _verify_binding()
    mu_max = CALIB_CONFIG["mu"]
    fee = CALIB_CONFIG["fee"]
    lhs = mu_max * (1.0 + fee)
    rhs = 2.0 * fee
    return {"lhs": lhs, "rhs": rhs,
            "no_act_proved": lhs < rhs}
