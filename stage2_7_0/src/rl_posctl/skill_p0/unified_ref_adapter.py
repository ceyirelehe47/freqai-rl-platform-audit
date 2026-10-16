# -*- coding: utf-8 -*-
"""统一世界 flat 校准:纯参考适配器(UNIFIED_FLAT_CALIBRATION_V1 准备段)。

**本段只实现适配与配置,不执行三次预算内的 H32 后向归纳。**
纯数学:仅 numpy(leggauss 求积);禁止 import p0eval(torch/env 顶层)
与任何模型/bank/confirm 依赖。经济机制=已验收 A11 候选 digest 绑定;
旧 C1/奖励/生产信任表零改动;技能门保持 not_specified;任何缺失/不稳
定结论=not_established(不改题降门)。
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np

from rl_posctl.skill_p0.unified_course import (
    OBS_COLUMNS, SPEC_VERSIONS, UNIFIED_TASK)

ADAPTER_SCHEMA = "UNIFIED_FLAT_REF_ADAPTER_V1"
STATUS = "prepared_not_run"      # 三次预算计算未启动

# ---- 计算前配置(审查方钉值;候选未校准,门 not_specified) --------
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
    "noise": "sqrt(3)*sigma*U, U~Unif(-1,1)",
    "kernel_ref": hashlib.sha256(json.dumps(
        UNIFIED_TASK["transition_kernel"], sort_keys=True,
        default=str).encode()).hexdigest(),
    "economy_ref": hashlib.sha256(json.dumps(
        UNIFIED_TASK["economy"], sort_keys=True,
        default=str).encode()).hexdigest(),
    "task_ref": UNIFIED_TASK["task_id"],
    "spec_versions": dict(SPEC_VERSIONS)}

CONFIG_DIGEST = hashlib.sha256(json.dumps(
    CALIB_CONFIG, sort_keys=True).encode()).hexdigest()

# 三档预算(最多共 3 次 H32 后向归纳;禁止第四档/参数扫描)
TIERS = {
    "L0": {"n_dense": 81, "n_ext_per_side": 16,
           "gauss_legendre": 12, "n_actions": 41},
    "L1": {"n_dense": 161, "n_ext_per_side": 32,
           "gauss_legendre": 24, "n_actions": 81},
    "L2": {"n_dense": 321, "n_ext_per_side": 64,
           "gauss_legendre": 48, "n_actions": 161}}
BUDGET = {"max_runs": 3, "wall_clock_s": 900,
          "cpu_s": 600, "rss_gib": 1.0}
ACCOUNT_DENSE_DOMAIN = 1.25        # ±
ACCOUNT_EXT_DOMAIN = 20.0          # ± 延伸
FORBIDDEN_SWEEP = ("mu", "sigma", "fee", "seed")


def dependency_available() -> bool:
    """纯 numpy 求积;scipy 不必需。若连 leggauss 都缺→
    dependency_unavailable(不安装、不静默换 200001 点)。"""
    try:
        from numpy.polynomial.legendre import leggauss
        leggauss(2)
        return True
    except Exception:
        return False


# ---- 64 题固定集(完整保留;不得按结果删题) ----------------------
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
                        "account": {"exposure": 0.0,
                                    "solvency_raw":
                                        math.inf}})
    for s in (-1, 1):                      # 4 题末段
        for g in (0, 1):
            qs.append({
                "id": "T%03d" % (len(qs) + 1),
                "s": s, "c": 1, "q": 1.0, "g": g,
                "remaining": 1, "total": 32,
                "account": {"exposure": 0.0,
                            "solvency_raw": math.inf}})
    assert len(qs) == 64
    return qs


QUESTIONS = build_questions()


# ---- 动作/账户网格 ---------------------------------------------
def action_grid(tier: str) -> np.ndarray:
    """[-1,1] 等距含 0 与 ±1;数量=档内 n_actions。"""
    if tier not in TIERS:
        raise ValueError("unknown tier %r" % tier)
    n = TIERS[tier]["n_actions"]
    if n % 2 == 0:
        raise ValueError("n_actions must be odd (grid "
                         "must contain 0)")
    w = np.linspace(-1.0, 1.0, n)
    if w[n // 2] != 0.0 or abs(w[0] + 1) > 1e-15 \
            or abs(w[-1] - 1) > 1e-15:
        raise ValueError("action grid malformed")
    return w


def account_grid(tier: str) -> np.ndarray:
    """账户敞口:密集域 ±1.25(n_dense 均匀)+两侧几何延伸
    至 ±20(每侧 n_ext_per_side 点,几何比例)。"""
    t = TIERS[tier]
    dense = np.linspace(-ACCOUNT_DENSE_DOMAIN,
                        ACCOUNT_DENSE_DOMAIN, t["n_dense"])
    ratio = (ACCOUNT_EXT_DOMAIN /
             ACCOUNT_DENSE_DOMAIN) ** (
        1.0 / t["n_ext_per_side"])
    ext_pos = ACCOUNT_DENSE_DOMAIN * ratio ** np.arange(
        1, t["n_ext_per_side"] + 1)
    grid = np.concatenate([
        -ext_pos[::-1], dense, ext_pos])
    return np.sort(np.unique(np.round(grid, 12)))


# ---- 纯数学一步经济(与 A11 经济声明一致) -----------------------
def mu_eff(s: int, c: int, q: float) -> float:
    return s * c * q * CALIB_CONFIG["mu"]


def noise_nodes(g: int, n_gl: int):
    """U∈[−1,1] 的 GL 节点/权重 → 收益 x=μ_eff+√3σu。"""
    from numpy.polynomial.legendre import leggauss
    u, wu = leggauss(n_gl)
    sigma = CALIB_CONFIG["sigma_by_g"][str(g)]
    return u, wu, sigma


def step_growth(exposure: float, target_w: float,
                x: float) -> tuple:
    """决策 close[t](调仓到目标 w,扣费)→ 持有过 bar 收益 x。
    返回 (log_growth, next_exposure)。REBAL 与 HOLD 同一公式
    (HOLD=target_w 保持当前数量:目标=漂移后当前比例,见
    hold_target();固定数量语义由此保证)。终端另有真实清算腿
    (terminal_liquidation_log)。"""
    fee = CALIB_CONFIG["fee"]
    turn = abs(target_w - exposure)
    nav_mult = (1.0 - fee * turn) * (1.0 + target_w * x)
    if nav_mult <= 0:
        return -math.inf, target_w
    lg = math.log(nav_mult)
    if target_w == 0.0:
        return lg, 0.0
    nxt = target_w * (1.0 + x) / (1.0 + target_w * x)
    return lg, nxt


def hold_target(exposure: float, x_prev: float) -> float:
    """HOLD=保持数量:上一结算后比例即本步目标(无交易费)。"""
    if exposure == 0.0:
        return 0.0
    return exposure * (1.0 + x_prev) / (
        1.0 + exposure * x_prev)


def terminal_liquidation_log(exposure: float,
                             x: float) -> float:
    """终端真实清算腿:末 bar 结算后清到 flat,清算交易量
    |最终敞口| 计费一次(不与学生主动退出混同)。"""
    fee = CALIB_CONFIG["fee"]
    nav = 1.0 + exposure * x
    if nav <= 0:
        return -math.inf
    final_w = exposure * (1.0 + x) / nav
    return math.log(nav * (1.0 - fee * abs(final_w)))


# ---- 必须行动判定(仅 Q_REBAL−Q_HOLD 与数值稳定性) -------------
def must_act_from_q(q_hold: float, q_rebals: dict,
                    stability_tol: float = 1e-9) -> object:
    """当前判据=Q_REBAL−Q_HOLD(禁止用正总价值替代)。
    返回 {'status': 'act'|'no_act'|'unstable'|'not_established',
          'best_w':..., 'margin':..., 'stability_gap':...}。
    相邻精度差仅经验诊断,不作严格误差上界;离散近优点集与连续
    容差带分开输出(不取凸包)。"""
    if not q_rebals:
        return {"status": "not_established"}
    diffs = {w: q - q_hold for w, q in q_rebals.items()}
    best_w = max(diffs, key=diffs.get)
    margin = diffs[best_w]
    vals = sorted(diffs.values())
    gap = (vals[-1] - vals[-2]) if len(vals) > 1 else \
        float("nan")
    unstable = any(
        not math.isfinite(v) for v in vals)
    if unstable:
        return {"status": "unstable",
                "stability_gap": gap}
    status = "act" if margin > stability_tol \
        else "no_act"
    return {"status": status, "best_w": best_w,
            "margin": margin,
            "diff_max_min": vals[-1] - vals[0],
            "stability_gap": gap,
            "near_opt_points": sorted(
                w for w, d in diffs.items()
                if d >= margin - 1e-12)}


# ---- 查询契约:仅当前可见状态/合法账户/原始 remaining-total ----
def make_query(question: dict) -> dict:
    """构造参考查询(禁未来/bank/模型/confirm;输入白名单)。"""
    allowed = {"s", "c", "q", "g", "remaining", "total",
               "account"}
    extra = set(question) - allowed - {"id"}
    if extra:
        raise ValueError(
            "query carries non-visible fields %r"
            % sorted(extra))
    if question["remaining"] > question["total"]:
        raise ValueError("remaining > total")
    return {k: question[k] for k in
            ("s", "c", "q", "g", "remaining", "total",
             "account")}


def cache_key(question_id: str, exposure: float,
              action_w: float, tier: str) -> str:
    """缓存键含实际动作坐标+全部数值配置 digest+档参数。"""
    payload = {
        "q": question_id, "e": float(exposure),
        "w": float(action_w), "tier": TIERS[tier],
        "config": CONFIG_DIGEST,
        "adapter": ADAPTER_SCHEMA}
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True).encode()).hexdigest()
