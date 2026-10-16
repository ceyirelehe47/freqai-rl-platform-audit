# -*- coding: utf-8 -*-
"""统一世界 flat 校准:纯参考适配器 v2(UNIFIED_FLAT_CALIBRATION_V1 准备段二轮)。

**三次预算 H32 后向归纳仍未启动(STATUS=prepared_not_run)。**
纯数学:仅 numpy;零 torch/env/p0eval/model/bank/confirm import。
经济=精确双边费(非线性,见 rebal_step);HOLD=固定数量无费;终端独立
清算腿只收 post_w。身份/配置 digest 在每个消费入口重算校验(防导入后
篡改)。预算 guard 预登记 3 次,先到先停,拒第 4 次。门 not_specified。
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

ADAPTER_SCHEMA = "UNIFIED_FLAT_REF_ADAPTER_V2"
SOLVER_VERSION = "dp-h32-v1"
STATUS = "prepared_not_run"

# ---- 钉值配置(可变 dict,但每个入口 _verify_binding 重算 digest) --
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


CONFIG_DIGEST = _sha(CALIB_CONFIG)

# ---- 完整 A11 身份绑定(task/obs/action/execution/reward) --------
IDENTITY = {
    "task_digest": _sha(UNIFIED_TASK),
    "obs": list(OBS_COLUMNS),
    "action": _sha(ACTION_FAMILIES),
    "execution": UNIFIED_TASK["economy"]["execution"],
    "reward": SPEC_VERSIONS["reward"],
    "kernel_digest": _sha(
        UNIFIED_TASK["transition_kernel"]),
    "economy_digest": _sha(UNIFIED_TASK["economy"]),
    "task_id": UNIFIED_TASK["task_id"]}
IDENTITY_DIGEST = _sha(IDENTITY)


def _verify_binding() -> None:
    """消费入口统一校验:实际配置/身份 digest 必须与冻结值一致
    (导入后改 CALIB_CONFIG 任何数值→立即拒绝,缓存键不会失配)。"""
    if _sha(CALIB_CONFIG) != CONFIG_DIGEST:
        raise RuntimeError(
            "CALIB_CONFIG mutated after freeze: digest "
            "mismatch — refused")
    if _sha(IDENTITY) != IDENTITY_DIGEST:
        raise RuntimeError("identity binding broken")


# ---- 三档预算(预登记;先到先停;拒第 4 次) ------------------------
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
_RUNS_USED = {"count": 0}
ACCOUNT_DENSE_DOMAIN = 1.25
ACCOUNT_EXT_DOMAIN = 20.0


def dependency_available() -> bool:
    try:
        from numpy.polynomial.legendre import leggauss
        leggauss(2)
        return True
    except Exception:
        return False


# ---- 64 题固定集(完整保留;不按结果删题) -------------------------
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


# ---- 严格查询契约(只认 64 题/flat 账户域;递归拒额外字段) --------
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
    """仅当前可见状态/合法账户/原始 remaining-total;ID 不是信息。"""
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
                "%s must be int in %r (bool/float/str "
                "rejected): %r" % (name, dom, v))
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
    if n % 2 == 0:
        raise ValueError("n_actions must be odd")
    w = np.linspace(-1.0, 1.0, n)
    if w[n // 2] != 0.0:
        raise ValueError("grid must contain 0")
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


# ---- 精确经济原语(非线性双边费) --------------------------------
def hold_step(e: float, r: float) -> tuple:
    """HOLD=固定数量:log(1+e·r);e'=e(1+r)/(1+e·r);零费零再漂移。"""
    _verify_binding()
    nav = 1.0 + e * r
    if nav <= 0:
        return -math.inf, e
    if e == 0.0:
        return math.log(nav), 0.0
    return math.log(nav), e * (1.0 + r) / nav


def rebal_step(e: float, w: float, r: float) -> tuple:
    """REBAL 到扣费后目标 w(双边费,非线性):
    w>e: fee·|(w−e)/(1+w·fee)|;w<e: fee·|(w−e)/(1−w·fee)|。"""
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


def liq_value(e: float, r: float) -> float:
    """终端独立清算腿:只收 post_w 的费,不加 bar 收益。"""
    _verify_binding()
    fee = CALIB_CONFIG["fee"]
    if e == 0.0:
        return 0.0        # post_w=0,无费
    post = e * (1.0 + r) / (1.0 + e * r)
    v = math.log(1.0 - fee * abs(post))
    return v if (1.0 - fee * abs(post)) > 0 else -math.inf


# ---- 转移矩阵(现核,行随机) ------------------------------------
def build_transition_matrices() -> dict:
    _verify_binding()
    k = UNIFIED_TASK["transition_kernel"]
    out = {}
    for comp in ("s", "c", "g"):
        vals = k[comp]["values"]
        n = len(vals)
        hold = float(k[comp]["hold_p"])
        res = float(k[comp]["resample_p"])
        # 重抽=在全值域均匀(可含原值):P(j|i)=res/n;
        # P(i|i)+=hold → 行和=hold+res=1
        m = np.full((n, n), res / n)
        idx = np.arange(n)
        m[idx, idx] += hold
        out[comp] = {"values": list(vals), "matrix": m}
    qv = k["q"]["values"]
    nq = len(qv)
    hold = float(k["q"]["hold_p"])
    fresh = np.array(k["q"]["fresh_p"], dtype=float)
    mq = np.tile(fresh / fresh.sum(), (nq, 1))
    np.fill_diagonal(mq, hold)
    # 行随机化:off-diagonal 按比例缩放至 1-hold
    off = mq.copy()
    np.fill_diagonal(off, 0.0)
    rowsum = off.sum(axis=1, keepdims=True)
    target = 1.0 - hold
    off = off * (target / rowsum)
    np.fill_diagonal(off, hold)
    out["q"] = {"values": list(qv), "matrix": off}
    for comp in ("s", "c", "g", "q"):
        assert np.allclose(
            out[comp]["matrix"].sum(axis=1), 1.0)
    return out


# ---- 键(全坐标+完整 digest) ------------------------------------
def dp_cache_key(tier: str) -> str:
    """DP 键=task/config 双 digest+全部动作与账户坐标+档+solver。"""
    _verify_binding()
    payload = {
        "identity": IDENTITY_DIGEST,
        "config": CONFIG_DIGEST,
        "tier": TIERS[tier],
        "actions": [float(x) for x in action_grid(tier)],
        "accounts": [float(x) for x in
                     account_grid(tier)],
        "solver": SOLVER_VERSION}
    return _sha(payload)


def query_cache_key(query: dict, tier: str) -> str:
    """query 键=DP 键+规范状态/账户/remaining/total。"""
    base = dp_cache_key(tier)
    payload = {
        "base": base,
        "state": [query["s"], query["c"],
                  float(query["q"]), query["g"]],
        "account": {"cash": query["account"]["cash"],
                    "exposure": query["account"][
                        "exposure"],
                    "solvency_raw": "inf"},
        "remaining": query["remaining"],
        "total": query["total"]}
    return _sha(payload)


# ---- 预算 guard + 后向归纳接口(实现就绪,未运行) -----------------
def _budget_state() -> dict:
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return {"runs": _RUNS_USED["count"],
            "rss_gib": ru.ru_maxrss / (1024 * 1024)}


def budget_allows(wall_elapsed: float,
                  cpu_elapsed: float) -> tuple:
    st = _budget_state()
    if st["runs"] >= BUDGET["max_runs"]:
        return False, "runs_exhausted(%d)" % st["runs"]
    if wall_elapsed > BUDGET["wall_clock_s"]:
        return False, "wall_clock"
    if cpu_elapsed > BUDGET["cpu_s"]:
        return False, "cpu"
    if st["rss_gib"] > BUDGET["rss_gib"]:
        return False, "rss"
    return True, "ok"


def solve_reference(tier: str) -> dict:
    """一次档内 H32 后向归纳(60 状态×账户网格×动作×GL×32 bar)。
    预算 guard 先到先停;**本准备段不调用**——仅接口就绪。"""
    raise NotImplementedError(
        "budgeted solve not started in prep segment "
        "(STATUS=%s); awaiting reviewer approval" % STATUS)


def solve_plan(tier: str) -> dict:
    """plan-only 计数(不执行 DP):形状/内存/注册次数。"""
    _verify_binding()
    t = TIERS[tier]
    acts = action_grid(tier)
    accs = account_grid(tier)
    n_states = 3 * 2 * 5 * 2
    per_cell = len(acts) * t["gauss_legendre"]
    cells = n_states * len(accs) * CALIB_CONFIG["H"]
    return {"tier": tier, "states": n_states,
            "bars": CALIB_CONFIG["H"],
            "actions": len(acts),
            "account_points": len(accs),
            "gl": t["gauss_legendre"],
            "total_action_evals": int(
                cells * per_cell),
            "est_value_arrays_gib": round(
                n_states * len(accs) * 8 / 2**30, 6),
            "runs_registered": _RUNS_USED["count"],
            "runs_max": BUDGET["max_runs"]}


def query_Q(query: dict, tier: str,
            dp_tables) -> dict:
    """逐题输出:Q_HOLD+每个 REBAL Q(从已解 dp_tables 读)。"""
    _verify_binding()
    raise NotImplementedError(
        "query_Q requires a completed solve (not started "
        "in prep segment)")


# ---- 跨档分析与判定 --------------------------------------------
def analyze_tiers(per_tier: dict) -> dict:
    """per_tier: {tier: {qid: {'q_hold':f,'q_rebals':{w:f}}}}。
    区分 action_gap(档内第一第二差)与 L0/L1/L2 逐题经验精度差;
    best_w 反号或 act 类别跨档变化→unstable/not_established;
    must-act 仅当 Q_REBAL−Q_HOLD 超过不确定尺度;离散接受点集与
    连续工程带分开输出,不取凸包。"""
    _verify_binding()
    tiers = sorted(per_tier)
    if len(tiers) < 2:
        return {"status": "not_established",
                "reason": "need >=2 tiers"}
    out = {}
    qids = set.intersection(
        *(set(per_tier[t]) for t in tiers))
    for qid in sorted(qids):
        rows = {t: per_tier[t][qid] for t in tiers}
        bests, margins, act_class = {}, {}, {}
        for t, row in rows.items():
            diffs = {w: q - row["q_hold"]
                     for w, q in row["q_rebals"].items()}
            vals = sorted(diffs.values())
            finite = all(math.isfinite(v)
                         for v in vals)
            if not finite or not vals:
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
        sign_set = {math.copysign(1.0, b)
                    for b in bests.values() if b != 0}
        if len(classes) > 1 or len(sign_set) > 1:
            out[qid] = {
                "status": "not_established",
                "reason": ("best-action sign/class "
                           "changed across tiers"),
                "best_w": bests,
                "act_class": act_class}
            continue
        ms = [margins[t] for t in tiers]
        cross = max(ms) - min(ms)
        uncertainty = max(cross, 1e-12)
        m_final = margins[tiers[-1]]
        out[qid] = {
            "status": ("act"
                       if m_final > uncertainty
                       else "no_act"),
            "best_w": bests,
            "margin_final": m_final,
            "cross_tier_diff": cross,
            "uncertainty": uncertainty,
            "near_opt_points_final": sorted(
                w for w, d in
                per_tier[tiers[-1]][qid][
                    "q_rebals"].items()
                if d - per_tier[tiers[-1]][qid][
                    "q_hold"] >= m_final - 1e-12),
            "continuous_band": [
                m_final - uncertainty,
                m_final + uncertainty]}
    return out


# ---- 解析边界(尾题负控;非求解) --------------------------------
def last_bar_fee_boundary() -> dict:
    """强状态末 bar 解析边界:act 需要漂移跨过双边费往返。
    边界条件 mu_max*(1+fee) < 2*fee → 单 bar 内任何 REBAL 都无法
    覆盖进出场双边费 → no_act(解析,不算 DP)。"""
    _verify_binding()
    mu_max = CALIB_CONFIG["mu"]
    fee = CALIB_CONFIG["fee"]
    lhs = mu_max * (1.0 + fee)
    rhs = 2.0 * fee
    return {"lhs": lhs, "rhs": rhs,
            "no_act_proved": lhs < rhs}
