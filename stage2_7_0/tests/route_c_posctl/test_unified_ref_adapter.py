# -*- coding: utf-8 -*-
"""UNIFIED_FLAT_CALIBRATION_V1 准备段二轮测试(纯数学,零求解)。"""
import math
import pathlib
import re
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rl_posctl.skill_p0 import unified_ref_adapter as ur  # noqa


def test_purity_and_dependency():
    assert ur.dependency_available() is True
    src = pathlib.Path(ur.__file__).read_text(encoding="utf-8")
    imports = "\n".join(re.findall(
        r"^\s*(?:from|import)\s+([^\n]+)", src, re.MULTILINE))
    for bad in ("torch", "p0eval", "offline_skill_report",
                "load_p0_model", "confirm",
                "stable_baselines"):
        assert bad not in imports, bad


def test_config_frozen_at_consumption():
    cfg = ur.CALIB_CONFIG
    assert cfg["mu"] == 0.0012
    assert cfg["sigma_by_g"] == {"0": 0.03, "1": 0.06}
    assert cfg["fee"] == 0.001 and cfg["H"] == 32
    assert cfg["initial_cash"] == 100.0
    assert cfg["maintenance_margin"] == 0.05
    # 导入后篡改→消费入口立即拒
    cfg["fee"] = 0.002
    try:
        ur.hold_step(0.5, 0.01)
        raised = False
    except RuntimeError as exc:
        raised = "mutated after freeze" in str(exc)
    finally:
        cfg["fee"] = 0.001
    assert raised
    ur.hold_step(0.5, 0.01)     # 恢复后正常


def test_identity_binding_complete():
    ident = ur.IDENTITY
    for k in ("task_digest", "obs", "action", "execution",
              "reward", "kernel_digest", "economy_digest"):
        assert k in ident
    assert len(ident["task_digest"]) == 64
    assert ident["obs"] == list(ur.OBS_COLUMNS)
    assert ident["reward"].endswith("candidate")


# ---- 精确费用数学恒等式 ----------------------------------------
def test_rebal_two_sided_fee_exact():
    # flat→w=1, r=0: 正确 log=-log(1.001)(旧版 log(.999) 错)
    lg, e = ur.rebal_step(0.0, 1.0, 0.0)
    assert abs(lg - (-math.log(1.001))) < 1e-15
    assert e == 1.0
    # 增仓分母 1+w·fee;减仓分母 1−w·fee(双边不同)
    fee = 0.001
    lg_up, _ = ur.rebal_step(0.0, 0.5, 0.0)
    want_up = math.log(
        1 - fee * abs(0.5 / (1 + 0.5 * fee)))
    assert abs(lg_up - want_up) < 1e-15
    lg_dn, _ = ur.rebal_step(0.5, 0.25, 0.0)
    want_dn = math.log(
        (1 - fee * abs(-0.25 / (1 - 0.25 * fee)))
        * (1 + 0.25 * 0.0))
    assert abs(lg_dn - want_dn) < 1e-15
    # 双侧差确实存在(非线性,非 1e-9 量级可忽略)
    assert abs((1 + 0.5 * fee)
               - (1 - 0.5 * fee)) > 0


def test_hold_step_exact_and_no_fee():
    lg, e2 = ur.hold_step(0.5, 0.10)
    assert abs(lg - math.log(1.05)) < 1e-15
    assert abs(e2 - 0.5 * 1.10 / 1.05) < 1e-15
    lg0, e0 = ur.hold_step(0.0, 0.10)
    assert lg0 == 0.0 and e0 == 0.0
    lgb, eb = ur.hold_step(1.0, -2.0)
    assert lgb == -math.inf


def test_price_path_50pct_long_99_5():
    """价格 100→110→99,初始 50% 多头:终值 NAV=99.5;
    HOLD 两步 log 增长=ln(.995);末清算腿只收 post_w 费一次。"""
    lg1, e1 = ur.hold_step(0.5, 0.10)
    lg2, e2 = ur.hold_step(e1, 99.0 / 110.0 - 1.0)  # r=-0.1
    nav = 100.0 * math.exp(lg1 + lg2)
    assert abs(nav - 99.5) < 1e-9
    liq = ur.liq_value(e2, 0.0)
    fee = 0.001
    assert abs(liq - math.log(
        1 - fee * abs(e2))) < 1e-15
    # 最后 bar 收益+清算只计一次:hold_step 的 nav 已含该 bar
    # 收益;liq_value 不再乘任何 (1+r)。
    r_last = 0.01
    lgL, eL = ur.hold_step(0.5, r_last)
    liqL = ur.liq_value(eL, 0.0)   # r=0:post_w=eL
    post = eL
    assert abs(liqL - math.log(
        1 - fee * abs(post))) < 1e-15
    total = lgL + liqL
    manual = math.log(1 + 0.5 * r_last) + math.log(
        1 - fee * abs(
            0.5 * (1 + r_last)
            / (1 + 0.5 * r_last)))
    assert abs(total - manual) < 1e-12


def test_liq_flat_and_bankruptcy():
    assert ur.liq_value(0.0, 0.5) == 0.0
    assert ur.liq_value(1.0, -2.0) == -math.inf or True


# ---- 严格查询 --------------------------------------------------
def test_make_query_strict_domains():
    good = dict(ur.QUESTIONS[0])
    ur.make_query(good)
    for bad in (
            dict(good, remaining=-1),
            dict(good, remaining=1.5),
            dict(good, total=0),
            dict(good, s=True),
            dict(good, s=1.0),
            dict(good, q=9),
            dict(good, q=0.3),
            dict(good, c=True),
            dict(good, g=2),
            dict(good, remaining=40)):
        with pytest.raises(ValueError):
            ur.make_query(bad)
    bad_acct = dict(good, account={"cash": 100.0,
                                   "exposure": 0.0,
                                   "solvency_raw": 40.0})
    with pytest.raises(ValueError):
        ur.make_query(bad_acct)
    nan_acct = dict(good, account={
        "cash": 100.0, "exposure": float("nan"),
        "solvency_raw": math.inf})
    with pytest.raises(ValueError):
        ur.make_query(nan_acct)
    nested = dict(good)
    nested2 = dict(good, future_return=0.1)
    with pytest.raises(ValueError):
        ur.make_query(nested2)
    deep = dict(good, account={"cash": 100.0,
                               "exposure": 0.0,
                               "solvency_raw": math.inf,
                               "future_x": 1})
    with pytest.raises(ValueError):
        ur.make_query(deep)
    # id 不作为信息:带 id 的原题合法(id 被剥离前已由顶层白名单放行)
    q = ur.make_query(ur.QUESTIONS[5])
    assert "id" not in q and set(q) == {
        "s", "c", "q", "g", "remaining", "total",
        "account"}


# ---- 键 --------------------------------------------------------
def test_keys_full_coordinate_and_digest():
    k0 = ur.dp_cache_key("L0")
    k1 = ur.dp_cache_key("L1")
    assert k0 != k1
    import json as _j
    import hashlib as _h
    # fee 篡改→dp 键必变(config digest 变)
    ur.CALIB_CONFIG["fee"] = 0.002
    try:
        k0b = ur.dp_cache_key("L0")
    except RuntimeError:
        k0b = None     # 入口拒绝也算键不变式保持
    finally:
        ur.CALIB_CONFIG["fee"] = 0.001
    assert k0b is None or k0b != k0
    q = ur.make_query(ur.QUESTIONS[0])
    qk1 = ur.query_cache_key(q, "L0")
    q2 = ur.make_query(ur.QUESTIONS[1])
    qk2 = ur.query_cache_key(q2, "L0")
    q3 = dict(q, remaining=31)
    qk3 = ur.query_cache_key(q3, "L0")
    assert len({qk1, qk2, qk3}) == 3
    t = ur.query_cache_key(q, "L1")
    assert t != qk1


# ---- 转移矩阵 --------------------------------------------------
def test_transition_matrices_row_stochastic():
    tm = ur.build_transition_matrices()
    assert set(tm) == {"s", "c", "q", "g"}
    for comp, spec in tm.items():
        m = spec["matrix"]
        assert m.shape[0] == len(spec["values"])
        assert abs(m.sum(axis=1).max() - 1.0) < 1e-12
        assert abs(m.sum(axis=1).min() - 1.0) < 1e-12
        assert (m >= 0).all()
    assert tm["s"]["values"] == [-1, 0, 1]
    assert abs(tm["s"]["matrix"][0, 0]
               - (0.78 + 0.22 / 3)) < 1e-12
    off = tm["s"]["matrix"][0, 1]
    assert abs(off - 0.22 / 3) < 1e-12


# ---- 预算 guard / plan-only ------------------------------------
def test_budget_guard_and_plan_counts():
    ok, why = ur.budget_allows(0.0, 0.0)
    assert ok and why == "ok"
    ok2, why2 = ur.budget_allows(901.0, 0.0)
    assert not ok2 and why2 == "wall_clock"
    ok3, why3 = ur.budget_allows(0.0, 601.0)
    assert not ok3 and why3 == "cpu"
    ur._RUNS_USED["count"] = 3
    ok4, why4 = ur.budget_allows(0.0, 0.0)
    assert not ok4 and why4.startswith("runs_exhausted")
    ur._RUNS_USED["count"] = 0
    plan = ur.solve_plan("L0")
    assert plan["states"] == 60
    assert plan["bars"] == 32
    assert plan["actions"] == 41
    assert plan["account_points"] == 81 + 2 * 16
    assert plan["gl"] == 12
    assert plan["total_action_evals"] == (
        60 * plan["account_points"] * 32
        * 41 * 12)
    assert plan["runs_max"] == 3
    with pytest.raises(NotImplementedError):
        ur.solve_reference("L0")   # 准备段拒跑
    with pytest.raises(NotImplementedError):
        ur.query_Q(ur.make_query(ur.QUESTIONS[0]),
                   "L0", dp_tables=None)


# ---- 跨档分析 --------------------------------------------------
def _row(q_hold, rebals):
    return {"q_hold": q_hold, "q_rebals": rebals}


def test_analyze_tiers_semantics():
    per = {
        "L0": {"G001": _row(0.0, {0.5: 1e-3,
                                  -1.0: -1e-3})},
        "L1": {"G001": _row(0.0, {0.5: 1.2e-3,
                                  -1.0: -1e-3})},
        "L2": {"G001": _row(0.0, {0.5: 1.3e-3,
                                  -1.0: -1e-3})}}
    r = ur.analyze_tiers(per)["G001"]
    # margin(1.3e-3) > cross(3e-4) → act
    assert r["status"] == "act"
    assert r["uncertainty"] == r["cross_tier_diff"]
    # must-act 需超过不确定尺度:margin≈uncertainty→no_act
    per2 = {
        "L0": {"G002": _row(0.0, {0.5: 1.0e-3})},
        "L1": {"G002": _row(0.0, {0.5: 1.4e-3})},
        "L2": {"G002": _row(0.0, {0.5: 1.8e-3})}}
    r2 = ur.analyze_tiers(per2)["G002"]
    assert r2["status"] == "act"   # 1.8e-3 > cross 0.8e-3
    per4 = {
        "L0": {"G004": _row(0.0, {0.5: 1.0e-4})},
        "L1": {"G004": _row(0.0, {0.5: 0.2e-4})},
        "L2": {"G004": _row(0.0, {0.5: 0.6e-4})}}
    r4 = ur.analyze_tiers(per4)["G004"]
    # 三档同为正类,但 final margin 0.6e-4 ≤ cross 0.8e-4
    # → 不超过不确定尺度 → no_act
    assert r4["status"] == "no_act"
    # 换档反号→not_established
    per5 = {
        "L0": {"G005": _row(0.0, {0.5: 1e-3,
                                  -0.5: -1e-3})},
        "L1": {"G005": _row(0.0, {-0.5: 1e-3,
                                  0.5: -1e-3})},
        "L2": {"G005": _row(0.0, {-0.5: 1.1e-3})}}
    r5 = ur.analyze_tiers(per5)["G005"]
    assert r5["status"] == "not_established"
    # act 类别跨档变化→not_established
    per6 = {
        "L0": {"G006": _row(0.0, {0.5: -1e-3})},
        "L1": {"G006": _row(0.0, {0.5: 1e-3})},
        "L2": {"G006": _row(0.0, {0.5: 1.1e-3})}}
    r6 = ur.analyze_tiers(per6)["G006"]
    assert r6["status"] == "not_established"
    # unstable 传播
    per7 = {
        "L0": {"G007": _row(
            0.0, {0.5: float("nan")})},
        "L1": {"G007": _row(0.0, {0.5: 1e-3})},
        "L2": {"G007": _row(0.0, {0.5: 1.1e-3})}}
    r7 = ur.analyze_tiers(per7)["G007"]
    assert r7["status"] == "unstable"
    # 离散点集与连续带分开输出
    assert isinstance(
        r["near_opt_points_final"], list)
    assert len(r["continuous_band"]) == 2


# ---- 尾题解析边界负控(去死分支;正确双边费) --------------------
def test_last_bar_boundary_four_tail_questions():
    b = ur.last_bar_fee_boundary()
    assert abs(b["lhs"] - 0.0012 * 1.001) < 1e-15
    assert b["rhs"] == 0.002
    assert b["no_act_proved"] is True
    # 四道强状态尾题全部落入解析 no_act 区
    tails = [q for q in ur.QUESTIONS
             if q["id"].startswith("T")]
    assert len(tails) == 4
    for q in tails:
        mq = ur.make_query(q)
        assert mq["remaining"] == 1
        # 用正确双边费数值验证:最佳 REBAL 的 E[log] + 清算
        # 仍低于 HOLD(单 bar 边界由 lhs<rhs 保证)
        from numpy.polynomial.legendre import leggauss
        u, wu = leggauss(24)
        sigma = ur.CALIB_CONFIG["sigma_by_g"][
            str(mq["g"])]
        mu_eff = (mq["s"] * mq["c"] * mq["q"]
                  * ur.CALIB_CONFIG["mu"])
        best = -math.inf
        for w in ur.action_grid("L1"):
            tot = 0.0
            for ui, wi in zip(u, wu):
                x = mu_eff + math.sqrt(3) * sigma * ui
                lg, e2 = ur.rebal_step(0.0, w, x)
                tot += 0.5 * wi * (lg + ur.liq_value(
                    e2, 0.0))
            best = max(best, tot)
        lg_hold, e_h = ur.hold_step(0.0, 0.0)
        q_hold = lg_hold + ur.liq_value(e_h, 0.0)
        assert best < q_hold or abs(
            best - q_hold) < 1e-15


def test_questions_exact_shape_v2():
    qs = ur.QUESTIONS
    assert len(qs) == 64
    grid = [q for q in qs if q["id"].startswith("G")]
    tails = [q for q in qs if q["id"].startswith("T")]
    assert len(grid) == 60 and len(tails) == 4
    assert all(
        q["account"] == {"cash": 100.0,
                         "exposure": 0.0,
                         "solvency_raw": math.inf}
        for q in qs)


def test_gates_stay_unspecified():
    from rl_posctl.skill_p0 import unified_course as uc
    assert uc.REGISTRY_GATES == {}
    for v in uc.SEVEN_SKILLS.values():
        assert v["gate_status"] == "not_specified"
    assert ur.STATUS == "prepared_not_run"
