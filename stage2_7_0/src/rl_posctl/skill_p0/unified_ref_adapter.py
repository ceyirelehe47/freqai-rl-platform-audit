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
_RUNS = {"used": 0, "open": None}
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
    acct = question["account"]
    if not isinstance(acct, dict) or acct != {
            "cash": 100.0, "exposure": 0.0,
            "solvency_raw": math.inf}:
        raise ValueError(
            "account must be exactly flat cash100/"
            "exposure0/solvency+inf: %r" % (acct,))
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


def _backward_induction(profile: dict) -> dict:
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
    from numpy.polynomial.legendre import leggauss
    u, wu = leggauss(gl)
    x_all = (mu[:, None] + (np.sqrt(3) * sig)[:, None]
             * u[None, :])          # (S, gl)
    w_nodes = 0.5 * wu              # U∈[-1,1] 密度 1/2
    V = np.empty((bars + 1, S, K))
    # 终端:清算腿只收当前 post_w(=e)
    V[0] = np.log(np.maximum(
        1.0 - fee * np.abs(acc[None, :]), 1e-300))
    V[0][np.where(
        1.0 - fee * np.abs(acc[None, :]) <= 0)[1]] = -np.inf
    E_arr = np.empty((S, K))
    for t in range(1, bars + 1):
        Vprev = V[t - 1]
        Vavg = P @ Vprev            # 期望在插值前(线性可交换)
        best = np.full((S, K), -np.inf)
        for w in np.concatenate([acts, [None]]):
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
                    Vi = (Vavg[np.arange(S), i2]
                          * (1.0 - f2)
                          + Vavg[np.arange(S), np.minimum(
                              i2 + 1, K - 1)] * f2)[:, None]
                step = lg + Vi
                step = np.where(
                    np.isfinite(step), step, -np.inf)
                Q += w_nodes[j] * step
            best = np.maximum(best, Q)
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
    _RUNS["used"] += 1
    _RUNS["open"] = {
        "tier": tier, "seq": _RUNS["used"],
        "wall0": time.perf_counter(),
        "cpu0": time.process_time(),
        "rss0_gib": (resource.getrusage(
            resource.RUSAGE_SELF).ru_maxrss
            / (1024 * 1024))}
    return dict(_RUNS["open"])


def _run_checkpoint(handle: dict) -> tuple:
    wall = time.perf_counter() - handle["wall0"]
    cpu = time.process_time() - handle["cpu0"]
    rss = resource.getrusage(
        resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    why = None
    if wall > BUDGET["wall_clock_s"]:
        why = "wall_clock"
    elif cpu > BUDGET["cpu_s"]:
        why = "cpu"
    elif rss > BUDGET["rss_gib"]:
        why = "rss"
    return why, {"wall_s": wall, "cpu_s": cpu,
                 "rss_gib": rss}


def _finish_run() -> dict:
    if _RUNS["open"] is None:
        raise RuntimeError("no open run")
    h = _RUNS["open"]
    why, meters = _run_checkpoint(h)
    _RUNS["open"] = None
    return {"tier": h["tier"], "seq": h["seq"],
            "stop_reason": why or "completed",
            **meters}


def budget_allows(wall_elapsed: float,
                  cpu_elapsed: float) -> tuple:
    """参数式检查保留(供外部预算预判);真消费走 begin/finish。"""
    if _RUNS["used"] >= BUDGET["max_runs"]:
        return False, "runs_exhausted(%d)" % _RUNS["used"]
    if wall_elapsed > BUDGET["wall_clock_s"]:
        return False, "wall_clock"
    if cpu_elapsed > BUDGET["cpu_s"]:
        return False, "cpu"
    rss = resource.getrusage(
        resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    if rss > BUDGET["rss_gib"]:
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
    """一次档内 H32 后向归纳:预约消费、逐 bar checkpoint、
    超限即停(部分结果+stop_reason)。**验收前不得调用**。"""
    _verify_binding()
    if tier not in TIERS:
        raise ValueError("unknown tier %r" % tier)
    h = _begin_run(tier)
    prof = _tier_profile(tier)
    try:
        res = _backward_induction(prof)
    finally:
        fin = _finish_run()
    res["budget"] = fin
    res["dp_key"] = dp_cache_key(tier)
    res["tier"] = tier
    if fin["stop_reason"] != "completed":
        res["partial"] = True
    return res


def query_Q(query: dict, tier: str,
            dp_tables: dict) -> dict:
    """逐题输出 Q_HOLD+每个 REBAL Q(需已解 dp_tables)。"""
    _verify_binding()
    if dp_tables.get("solver") != SOLVER_VERSION:
        raise ValueError("dp_tables solver mismatch")
    if dp_tables.get("tier") != tier:
        raise ValueError("dp_tables tier mismatch")
    acc = dp_tables["accounts"]
    V = dp_tables["V"]
    states = state_space()
    try:
        si = states.index((
            query["s"], query["c"],
            float(query["q"]), query["g"]))
    except ValueError:
        raise ValueError("query state not in space")
    t = query["remaining"]
    e0 = float(query["account"]["exposure"])
    mu = (query["s"] * query["c"] * query["q"]
          * CALIB_CONFIG["mu"])
    sig = CALIB_CONFIG["sigma_by_g"][str(query["g"])]
    fee = CALIB_CONFIG["fee"]
    from numpy.polynomial.legendre import leggauss
    u, wu = leggauss(dp_tables["gl"])
    Vavg_row = None
    P = full_state_transition()
    Vprev = V[t - 1] if t >= 1 else V[0]
    Vavg = P @ Vprev
    row = Vavg[si]
    idx0, frac0 = _interp_weights(
        np.array([e0]), acc)

    def val_at(e):
        i, fr = _interp_weights(np.array([e]), acc)
        return float(row[i[0]] * (1 - fr[0])
                     + row[min(i[0] + 1, len(acc) - 1)]
                     * fr[0])

    q_out = {}
    for w in dp_tables["actions"]:
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
    return {"qid_state": si, "remaining": t,
            "q_hold": q_hold, "q_rebals": q_out,
            "dp_key": dp_tables.get("dp_key")}


# ---- 完整性强制(64×3) ------------------------------------------
def validate_tier_outputs(per_tier: dict) -> None:
    """缺题/重复/错身份输出→拒。"""
    _verify_binding()
    if set(per_tier) != set(TIERS):
        raise ValueError(
            "need exactly tiers L0/L1/L2, got %r"
            % sorted(per_tier))
    for tier, tables in per_tier.items():
        if tables.get("tier") != tier:
            raise ValueError(
                "tier identity mismatch at %r" % tier)
        if tables.get("dp_key") != dp_cache_key(tier):
            raise ValueError(
                "dp_key mismatch at %r" % tier)
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


# ---- 跨档分析(动作集合漂移感知) --------------------------------
def analyze_tiers(per_tier: dict) -> dict:
    _verify_binding()
    tiers = sorted(per_tier)
    if len(tiers) < 2:
        return {"status": "not_established",
                "reason": "need >=2 tiers"}
    out = {}
    qids = set.intersection(
        *(set(per_tier[t]) for t in tiers))
    fine = tiers[-1]
    for qid in sorted(qids):
        rows = {t: per_tier[t][qid] for t in tiers}
        bests, margins, act_class = {}, {}, {}
        for t, row in rows.items():
            diffs = {w: q - row["q_hold"]
                     for w, q in row["q_rebals"].items()}
            vals = sorted(diffs.values())
            if (not vals) or not all(
                    math.isfinite(v) for v in vals):
                act_class[t] = "unstable"
                continue
            bw = max(diffs, key=diffs.get)
            bests[t] = bw
            margins[t] = diffs[bw]
            act_class[t] = ("act" if diffs[bw] > 0
                            else "no_act")
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
        # 动作集合漂移:best_w 跨档位移超过最粗档动作间距之半
        acts0 = sorted(rows[tiers[0]]["q_rebals"])
        if len(acts0) >= 2:
            spacing0 = min(
                b - a for a, b in zip(acts0, acts0[1:]))
        else:
            spacing0 = float("inf")   # 单动作无间距概念
        if spacing0 != float("inf") and \
                drift > spacing0 / 2.0:
            out[qid] = {
                "status": "not_established",
                "reason": ("best_w drifted across tiers "
                           "(%.3f > spacing/2 %.4f) — "
                           "action set not stable"
                           % (drift, spacing0 / 2)),
                "best_w": bests}
            continue
        # 公共坐标(L0 ⊂ L1 ⊂ L2)Q 值一致性
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
        status = ("act" if m_final > uncertainty
                  else "no_act")
        out[qid] = {
            "status": status,
            "best_w": bests,
            "margin_final": m_final,
            "cross_tier_margin_diff": cross,
            "common_coord_value_dev": val_dev,
            "uncertainty_q_units": uncertainty,
            "near_opt_points_final": near,
            "value_uncertainty_band_q_units": [
                m_final - uncertainty,
                m_final + uncertainty]}
    return out


# ---- 解析边界(尾题负控) ----------------------------------------
def last_bar_fee_boundary() -> dict:
    _verify_binding()
    mu_max = CALIB_CONFIG["mu"]
    fee = CALIB_CONFIG["fee"]
    lhs = mu_max * (1.0 + fee)
    rhs = 2.0 * fee
    return {"lhs": lhs, "rhs": rhs,
            "no_act_proved": lhs < rhs}
