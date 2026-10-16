# -*- coding: utf-8 -*-
"""UNIFIED_FLAT_CALIBRATION_V1 三轮测试(真内核单元测试;零三档运行)。"""
import math
import pathlib
import re
import sys

import numpy as np
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
    assert "if False" not in src      # 死分支禁令


def test_binding_verifies_live_consumed_objects():
    ur.hold_step(0.5, 0.01)           # 正常
    ur.UNIFIED_TASK["economy"]["fee_rate"] = 0.009
    try:
        ur.hold_step(0.5, 0.01)
        raised = False
    except RuntimeError as exc:
        raised = "UNIFIED_TASK" in str(exc)
    finally:
        ur.UNIFIED_TASK["economy"][
            "fee_rate"] = 0.001
    assert raised
    ur.hold_step(0.5, 0.01)           # 恢复
    ur.CALIB_CONFIG["fee"] = 0.002
    try:
        ur.liq_value(0.5)
        raised2 = False
    except RuntimeError as exc:
        raised2 = "CALIB_CONFIG" in str(exc)
    finally:
        ur.CALIB_CONFIG["fee"] = 0.001
    assert raised2


def test_rebal_two_sided_fee_and_hold_exact():
    lg, e = ur.rebal_step(0.0, 1.0, 0.0)
    assert abs(lg - (-math.log(1.001))) < 1e-15
    assert abs(e - 1.0) < 1e-15
    fee = 0.001
    lg_up, _ = ur.rebal_step(0.0, 0.5, 0.0)
    assert abs(lg_up - math.log(
        1 - fee * abs(0.5 / (1 + 0.5 * fee)))) < 1e-15
    lg_dn, _ = ur.rebal_step(0.5, 0.25, 0.0)
    assert abs(lg_dn - math.log(
        1 - fee * abs(-0.25 / (1 - 0.25 * fee)))) < 1e-15
    lg, e2 = ur.hold_step(0.5, 0.10)
    assert abs(lg - math.log(1.05)) < 1e-15
    assert abs(e2 - 0.5 * 1.10 / 1.05) < 1e-15


def test_price_path_and_single_liquidation():
    lg1, e1 = ur.hold_step(0.5, 0.10)
    lg2, e2 = ur.hold_step(e1, 99.0 / 110.0 - 1.0)
    assert abs(100.0 * math.exp(lg1 + lg2) - 99.5) < 1e-9
    # 清算腿单参:只收 post_w,先判合法再 log
    assert ur.liq_value(0.0) == 0.0
    fee = 0.001
    assert abs(ur.liq_value(e2)
               - math.log(1 - fee * abs(e2))) < 1e-15
    assert ur.liq_value(1.0 / fee * 2.0) == -math.inf
    with pytest.raises(ValueError):
        ur.liq_value(float("nan"))
    with pytest.raises(ValueError):
        ur.liq_value(True)
    r = 0.01
    lgL, eL = ur.hold_step(0.5, r)
    total = lgL + ur.liq_value(eL)    # 收益一次+清算一次
    manual = math.log(1 + 0.5 * r) + math.log(
        1 - fee * abs(
            0.5 * (1 + r) / (1 + 0.5 * r)))
    assert abs(total - manual) < 1e-12


def test_transition_q_kernel_exact():
    tm = ur.build_transition_matrices()
    q = tm["q"]["matrix"]
    # A11:P=.8I+.2*fresh → q0 对角 .8+.2*.125=.825
    assert abs(q[0, 0] - 0.825) < 1e-12
    # 中间级 fresh=.25 → 对角 .85
    assert abs(q[2, 2] - 0.85) < 1e-12
    assert abs(q[2, 0] - 0.2 * 0.125) < 1e-12
    s = tm["s"]["matrix"]
    assert abs(s[0, 0] - (0.78 + 0.22 / 3)) < 1e-12
    assert abs(s[0, 1] - 0.22 / 3) < 1e-12
    c = tm["c"]["matrix"]
    assert abs(c[0, 0] - (0.75 + 0.25 / 2)) < 1e-12
    for spec in tm.values():
        m = spec["matrix"]
        assert np.allclose(m.sum(axis=1), 1.0)
        assert (m >= 0).all()
    P = ur.full_state_transition()
    assert P.shape == (60, 60)
    assert np.allclose(P.sum(axis=1), 1.0)


def test_strict_query_unchanged():
    good = dict(ur.QUESTIONS[0])
    q = ur.make_query(good)
    assert set(q) == {"s", "c", "q", "g", "remaining",
                      "total", "account"}
    for bad in (dict(good, remaining=-1),
                dict(good, remaining=1.5),
                dict(good, s=True), dict(good, q=9),
                dict(good, remaining=40),
                dict(good, account={
                    "cash": 100.0, "exposure": 0.0,
                    "solvency_raw": 40.0}),
                dict(good, account={
                    "cash": 100.0,
                    "exposure": float("nan"),
                    "solvency_raw": math.inf})):
        with pytest.raises(ValueError):
            ur.make_query(bad)
    with pytest.raises(ValueError):
        ur.make_query(dict(good, future_return=0.1))
    deep = dict(good, account={
        "cash": 100.0, "exposure": 0.0,
        "solvency_raw": math.inf, "future_x": 1})
    with pytest.raises(ValueError):
        ur.make_query(deep)


# ---- 真内核微型单元测试(非三档预算运行) ------------------------
def _mini_tables():
    prof = ur._tier_profile("L0")
    prof["actions"] = np.array([-1.0, 0.0, 1.0])
    prof["accounts"] = np.linspace(-1.25, 1.25, 9)
    prof["gl"] = 5
    prof["bars"] = 3
    res = ur._backward_induction(prof)
    res.update(tier="L0", gl=5,
               actions=prof["actions"],
               accounts=prof["accounts"],
               solver=ur.SOLVER_VERSION)
    return res, prof


def test_backward_induction_kernel_runs():
    res, prof = _mini_tables()
    V = res["V"]
    assert V.shape == (4, 60, 9)
    acc = res["accounts"]
    flat_i = int(np.argmin(np.abs(acc)))
    # 终端:flat 清算=0;有仓=负(费)
    assert abs(V[0, 0, flat_i]) < 1e-15
    assert V[0, 0, 0] < 0            # e=acc[0]<0 → 清付费
    # 中性状态价值应随 bar 保持 ≤0(Jensen/费)
    states = ur.state_space()
    neutral_i = states.index((0, 1, 0.5, 0))
    assert V[3, neutral_i, flat_i] <= 1e-12
    # 强方向状态(s=1,c=1,q=1)价值应高于中性(flat 起点)
    strong_i = states.index((1, 1, 1.0, 0))
    assert V[3, strong_i, flat_i] >= \
        V[3, neutral_i, flat_i] - 1e-15
    assert np.isfinite(V[3, strong_i, flat_i])


def test_query_Q_flat_invariants():
    res, prof = _mini_tables()
    q = ur.make_query({"s": 1, "c": 1, "q": 1.0,
                       "g": 0, "remaining": 3,
                       "total": 32,
                       "account": {"cash": 100.0,
                                   "exposure": 0.0,
                                   "solvency_raw":
                                       math.inf}})
    out = ur.query_Q(q, "L0", res)
    assert math.isfinite(out["q_hold"])
    # flat 下 w=0 与 HOLD 完全等价(零费零漂移)
    assert abs(out["q_rebals"][0.0]
               - out["q_hold"]) < 1e-12
    assert set(out["q_rebals"]) == {-1.0, 0.0, 1.0}
    with pytest.raises(ValueError):
        ur.query_Q(q, "L0",
                   dict(res, solver="other"))


# ---- 预算 guard 实际消费 ---------------------------------------
def test_budget_run_registration_and_refusal():
    assert ur._RUNS["open"] is None
    ur._RUNS["used"] = 0
    h = ur._begin_run("L0")
    assert h["seq"] == 1 and ur._RUNS["used"] == 1
    with pytest.raises(RuntimeError):   # 同时只许一个
        ur._begin_run("L1")
    fin = ur._finish_run()
    assert fin["tier"] == "L0"
    assert fin["stop_reason"] == "completed"
    ur._RUNS["used"] = 3
    with pytest.raises(RuntimeError):   # 第 4 次拒
        ur._begin_run("L2")
    ur._RUNS["used"] = 0


# ---- 完整性强制 ------------------------------------------------
def test_validate_tier_outputs_completeness():
    res, _ = _mini_tables()
    fake = {}
    for t in ("L0", "L1", "L2"):
        fake[t] = dict(res, tier=t,
                       dp_key=ur.dp_cache_key(t),
                       questions=[dict(q)
                                  for q in ur.QUESTIONS])
    # tier 身份错误必拒
    bad1 = dict(fake)
    bad1["L0"] = dict(fake["L0"], tier="L1")
    with pytest.raises(ValueError):
        ur.validate_tier_outputs(bad1)
    # 缺题必拒
    miss = dict(fake)
    miss["L1"] = dict(fake["L1"], questions=[
        dict(q) for q in ur.QUESTIONS
        if q["id"] != "G017"])
    with pytest.raises(ValueError, match="missing"):
        ur.validate_tier_outputs(miss)
    # 重复必拒
    dup = dict(fake)
    qs = [dict(q) for q in ur.QUESTIONS]
    qs[10] = dict(qs[9])
    dup["L2"] = dict(fake["L2"], questions=qs)
    with pytest.raises(ValueError, match="duplicates"):
        ur.validate_tier_outputs(dup)


def _row(qh, rb):
    return {"q_hold": qh, "q_rebals": rb}


def test_analyze_tiers_drift_and_band_units():
    per = {
        "L0": {"G001": _row(0.0, {0.5: 1e-3,
                                  -1.0: -1e-3})},
        "L1": {"G001": _row(0.0, {0.5: 1.2e-3,
                                  -1.0: -1e-3})},
        "L2": {"G001": _row(0.0, {0.5: 1.3e-3,
                                  -1.0: -1e-3})}}
    r = ur.analyze_tiers(per)["G001"]
    assert r["status"] == "act"
    assert "q_units" in "".join(r)
    # best_w 跨档漂移 .1→.5→.9(margin 相同)→not_established
    drift = {
        "L0": {"G002": _row(
            0.0, {0.1: 1e-3, 0.5: 9.9e-4})},
        "L1": {"G002": _row(
            0.0, {0.5: 1e-3, 0.1: 9.9e-4})},
        "L2": {"G002": _row(
            0.0, {0.9: 1e-3, 0.5: 9.9e-4})}}
    r2 = ur.analyze_tiers(drift)["G002"]
    assert r2["status"] == "not_established"
    assert "drifted" in r2["reason"]
    # 公共坐标 Q 值差纳入不确定度
    val_dev = {
        "L0": {"G003": _row(0.0, {0.5: 1.0e-4})},
        "L1": {"G003": _row(0.0, {0.5: 2.0e-4})},
        "L2": {"G003": _row(0.0, {0.5: 1.1e-4})}}
    r3 = ur.analyze_tiers(val_dev)["G003"]
    assert r3["common_coord_value_dev"] >= \
        abs(2.0e-4 - 1.1e-4) - 1e-15
    # unstable 传播
    nan = {
        "L0": {"G004": _row(
            0.0, {0.5: float("nan")})},
        "L1": {"G004": _row(0.0, {0.5: 1e-3})},
        "L2": {"G004": _row(0.0, {0.5: 1e-3})}}
    r4 = ur.analyze_tiers(nan)["G004"]
    assert r4["status"] == "unstable"


def test_tail_boundary_and_status():
    b = ur.last_bar_fee_boundary()
    assert abs(b["lhs"] - 0.0012 * 1.001) < 1e-15
    assert b["rhs"] == 0.002 and b["no_act_proved"]
    tails = [q for q in ur.QUESTIONS
             if q["id"].startswith("T")]
    assert len(tails) == 4
    assert ur.STATUS == "prepared_not_run"
    from rl_posctl.skill_p0 import unified_course as uc
    assert uc.REGISTRY_GATES == {}
