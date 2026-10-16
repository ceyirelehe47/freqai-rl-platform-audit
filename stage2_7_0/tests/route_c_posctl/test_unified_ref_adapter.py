# -*- coding: utf-8 -*-
"""UNIFIED_FLAT_CALIBRATION_V1 四轮测试。

**零真核运行**(此前 R3 的 3 次微型内核调用已登记 RUNS_REGISTER,
本轮起只用标量/假表/假时钟;三档 H32 待放行)。"""
import math
import pathlib
import re
import sys

import numpy as np
import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rl_posctl.skill_p0 import unified_ref_adapter as ur  # noqa


# ---------- 既有关闭组(保留) ------------------------------------
def test_purity_and_dependency():
    assert ur.dependency_available() is True
    src = pathlib.Path(ur.__file__).read_text(encoding="utf-8")
    imports = "\n".join(re.findall(
        r"^\s*(?:from|import)\s+([^\n]+)", src, re.MULTILINE))
    for bad in ("torch", "p0eval", "offline_skill_report",
                "load_p0_model", "confirm",
                "stable_baselines"):
        assert bad not in imports, bad
    assert "if False" not in src


def test_binding_verifies_live_objects():
    ur.hold_step(0.5, 0.01)
    ur.UNIFIED_TASK["economy"]["fee_rate"] = 0.009
    try:
        ur.hold_step(0.5, 0.01)
        raised = False
    except RuntimeError as exc:
        raised = "UNIFIED_TASK" in str(exc)
    finally:
        ur.UNIFIED_TASK["economy"]["fee_rate"] = 0.001
    assert raised
    ur.hold_step(0.5, 0.01)


def test_fee_math_and_price_path():
    lg, e = ur.rebal_step(0.0, 1.0, 0.0)
    assert abs(lg - (-math.log(1.001))) < 1e-15
    fee = 0.001
    lg_dn, _ = ur.rebal_step(0.5, 0.25, 0.0)
    assert abs(lg_dn - math.log(
        1 - fee * abs(-0.25 / (1 - 0.25 * fee)))) < 1e-15
    lg1, e1 = ur.hold_step(0.5, 0.10)
    lg2, e2 = ur.hold_step(e1, 99.0 / 110.0 - 1.0)
    assert abs(100.0 * math.exp(lg1 + lg2) - 99.5) < 1e-9
    assert ur.liq_value(0.0) == 0.0
    assert ur.liq_value(2000.0) == -math.inf
    with pytest.raises(ValueError):
        ur.liq_value(float("nan"))


def test_transition_q_kernel_exact():
    tm = ur.build_transition_matrices()
    q = tm["q"]["matrix"]
    assert abs(q[0, 0] - 0.825) < 1e-12
    assert abs(q[2, 2] - 0.85) < 1e-12
    s = tm["s"]["matrix"]
    assert abs(s[0, 0] - (0.78 + 0.22 / 3)) < 1e-12
    P = ur.full_state_transition()
    assert P.shape == (60, 60)
    assert np.allclose(P.sum(axis=1), 1.0)


def test_strict_query():
    good = dict(ur.QUESTIONS[0])
    for bad in (dict(good, remaining=-1),
                dict(good, s=True), dict(good, q=9),
                dict(good, remaining=40)):
        with pytest.raises(ValueError):
            ur.make_query(bad)
    q = ur.make_query(good)
    assert "id" not in q


def test_tail_boundary():
    b = ur.last_bar_fee_boundary()
    assert abs(b["lhs"] - 0.0012 * 1.001) < 1e-15
    assert b["rhs"] == 0.002 and b["no_act_proved"]
    assert ur.STATUS == "prepared_not_run"


# ---------- 组2:越界强制清算(标量双侧) --------------------------
def test_forced_liquidation_semantics():
    """越界≠破产:强制清算值有限;仅净值/清算后权益≤0 才 -inf。"""
    # e=20,r=-.04: growth=.2,post=96,因子 .904 → 有限
    v = ur.forced_liquidation_value(20.0, -0.04)
    assert abs(v - (math.log(0.2)
                    + math.log(0.904))) < 1e-12
    # 负侧:e=-20,r=+.04 → post=-104,因子 .896 → 有限
    vn = ur.forced_liquidation_value(-20.0, 0.04)
    assert abs(vn - (math.log(0.2)
                     + math.log(0.896))) < 1e-12
    # post≈1901:因子 1-1.901<0 → 真无效
    assert ur.forced_liquidation_value(
        20.0, -0.0495) == -math.inf
    # 净值≤0 → -inf
    assert ur.forced_liquidation_value(
        1.0, -2.0) == -math.inf
    # forced_invalid 现仅表真无效
    _, post = ur.hold_step(20.0, -0.04)
    assert ur.forced_invalid(post, 0.2) is False
    _, post2 = ur.hold_step(20.0, -0.0495)
    assert ur.forced_invalid(post2, 0.01) is True


# ---------- 组1:guard 累计+假时钟 -------------------------------
class FakeClock:
    def __init__(self):
        self.wall = 1000.0
        self.cpu = 100.0
        self.rss = 0.1

    def wall_fn(self):
        return self.wall

    def cpu_fn(self):
        return self.cpu


@pytest.fixture()
def fake_clock(monkeypatch):
    fc = FakeClock()
    monkeypatch.setattr(ur, "_now_wall", fc.wall_fn)
    monkeypatch.setattr(ur, "_now_cpu", fc.cpu_fn)
    monkeypatch.setattr(ur, "_now_rss_gib",
                        lambda: fc.rss)
    return fc


def test_guard_cumulative_and_refusals(fake_clock):
    ur._RUNS.update(used=0, open=None, total_wall_s=0.0,
                    total_cpu_s=0.0, tiers_used=[])
    # run1: L0, +500 墙/+250 CPU
    h1 = ur._begin_run("L0")
    fake_clock.wall += 500
    fake_clock.cpu += 250
    fin1 = ur._finish_run()
    assert fin1["stop_reason"] == "completed"
    assert fin1["cum_wall_s"] == 500
    # 同档重复拒
    with pytest.raises(RuntimeError,
                       match="repeat refused"):
        ur._begin_run("L0")
    # run2: L1, 进行中累计 500+401=901>900 → checkpoint=wall
    h2 = ur._begin_run("L1")
    fake_clock.wall += 401
    fake_clock.cpu += 300
    why, m = ur._run_checkpoint(h2)
    assert why == "wall_clock" and m["cum_wall_s"] == 901
    fin2 = ur._finish_run(why)
    assert fin2["stop_reason"] == "wall_clock"
    # 累计已越限 → 第三个 run 拒开
    with pytest.raises(RuntimeError,
                       match="cumulative budget"):
        ur._begin_run("L2")
    assert ur._RUNS["used"] == 2
    # budget_allows 累计口径
    ok, why2 = ur.budget_allows(0.0, 0.0)
    assert not ok and why2 == "wall_clock"


def test_guard_cpu_and_rss_paths(fake_clock):
    ur._RUNS.update(used=0, open=None, total_wall_s=0.0,
                    total_cpu_s=0.0, tiers_used=[])
    h = ur._begin_run("L0")
    fake_clock.cpu += 601
    why, _ = ur._run_checkpoint(h)
    assert why == "cpu"
    ur._finish_run("cpu")
    ur._RUNS.update(used=0, open=None,
                    total_wall_s=0.0, total_cpu_s=0.0,
                    tiers_used=[])
    h2 = ur._begin_run("L0")
    fake_clock.rss = 1.5
    why2, _ = ur._run_checkpoint(h2)
    assert why2 == "rss"
    fake_clock.rss = 0.1
    ur._finish_run()
    ur._RUNS.update(used=0, open=None,
                    total_wall_s=0.0, total_cpu_s=0.0,
                    tiers_used=[])


def test_guard_4th_run_refused(fake_clock):
    ur._RUNS.update(used=0, open=None, total_wall_s=0.0,
                    total_cpu_s=0.0, tiers_used=[])
    for t in ("L0", "L1", "L2"):
        ur._begin_run(t)
        fake_clock.wall += 100
        fake_clock.cpu += 50
        ur._finish_run()
    with pytest.raises(RuntimeError,
                       match="4th run refused"):
        ur._begin_run("L0")
    ur._RUNS.update(used=0, open=None,
                    total_wall_s=0.0, total_cpu_s=0.0,
                    tiers_used=[])


def test_solve_exception_closes_run_and_counts(
        fake_clock, monkeypatch):
    """profile/内核异常:运行关闭、名额仍消费。"""

    def boom(profile, checkpoint=None):
        raise MemoryError("synthetic OOM")

    monkeypatch.setattr(ur, "_backward_induction",
                        boom)
    ur._RUNS.update(used=0, open=None,
                    total_wall_s=0.0, total_cpu_s=0.0,
                    tiers_used=[])
    with pytest.raises(MemoryError):
        ur.solve_reference("L0")
    assert ur._RUNS["open"] is None      # 已关闭
    assert ur._RUNS["used"] == 1         # 失败也计
    with pytest.raises(RuntimeError,
                       match="repeat refused"):
        ur.solve_reference("L0")
    ur._RUNS.update(used=0, open=None,
                    total_wall_s=0.0, total_cpu_s=0.0,
                    tiers_used=[])


def test_query_analysis_budget_gate(fake_clock):
    tables = _fake_tables("L0")
    qrow = ur.QUESTIONS[0]
    ur._RUNS.update(used=0, open=None,
                    total_wall_s=950.0, total_cpu_s=0.0,
                    tiers_used=[])
    with pytest.raises(RuntimeError,
                       match="job budget"):
        ur.query_Q(qrow, "L0", tables)
    with pytest.raises(RuntimeError,
                       match="job budget"):
        ur.analyze_tiers(_full_fake())
    ur._RUNS.update(used=0, open=None,
                    total_wall_s=0.0, total_cpu_s=0.0,
                    tiers_used=[])


def test_solve_wiring_with_fake_kernel(fake_clock,
                                       monkeypatch):
    """假内核(无真 DP):验证 solve_reference 的 checkpoint
    接线/部分状态/不可 completed/名额消费。"""
    calls = {"n": 0}

    def fake_kernel(profile, checkpoint=None):
        calls["n"] += 1
        why = checkpoint(2, "bar_begin") if (
            checkpoint is not None) else None
        if why:
            return {"partial": True,
                    "stop_reason": why,
                    "bars_done": 1, "V": None,
                    "solver": ur.SOLVER_VERSION}
        return {"V": np.zeros((33, 60, 113)),
                "accounts": profile["accounts"],
                "actions": profile["actions"],
                "gl": profile["gl"],
                "bars": 32,
                "solver": ur.SOLVER_VERSION}

    monkeypatch.setattr(ur, "_backward_induction",
                        fake_kernel)
    ur._RUNS.update(used=0, open=None,
                    total_wall_s=800.0,
                    total_cpu_s=550.0, tiers_used=[])
    h_probe = ur._begin_run("L2")   # 先占名额接假时钟基准
    fake_clock.wall += 5            # 累计 805<900;仅校准
    ur._finish_run()
    ur._RUNS.update(used=0, open=None,
                    total_wall_s=800.0,
                    total_cpu_s=550.0,
                    tiers_used=[])
    res_holder = {}

    def fake_kernel2(profile, checkpoint=None):
        fake_clock.wall += 150       # 运行中累计 950>900
        return fake_kernel(profile, checkpoint)

    monkeypatch.setattr(ur, "_backward_induction",
                        fake_kernel2)
    res = ur.solve_reference("L0")
    assert res["partial"] is True
    assert res["stop_reason"] == "wall_clock"
    assert res["completed"] is False
    assert res["budget"]["stop_reason"] == "wall_clock"
    assert calls["n"] == 1
    # 失败也计名额:used=1;再开同档拒
    assert ur._RUNS["used"] == 1
    with pytest.raises(RuntimeError):
        ur.solve_reference("L0")
    ur._RUNS.update(used=0, open=None,
                    total_wall_s=0.0, total_cpu_s=0.0,
                    tiers_used=[])


# ---------- 组3:假表验真与内容级强制 ----------------------------
def _fake_tables(tier):
    acc = ur.account_grid(tier)
    n = len(acc)
    V = np.zeros((33, 60, n))
    V[0] = np.log(np.maximum(
        1.0 - 0.001 * np.abs(acc[None, :]), 1e-300))
    return {"V": V, "accounts": acc,
            "actions": ur.action_grid(tier),
            "gl": ur.TIERS[tier]["gauss_legendre"],
            "bars": 32, "tier": tier,
            "solver": ur.SOLVER_VERSION,
            "dp_key": ur.dp_cache_key(tier),
            "completed": True,
            "stop_reason": None}


def test_validate_dp_tables_rejects_bad(fake_clock):
    good = _fake_tables("L0")
    ur.validate_dp_tables("L0", good)
    # 非完成
    with pytest.raises(ValueError, match="completed"):
        ur.validate_dp_tables("L0",
                              dict(good, completed=False))
    # 动作坐标不符(dp_key 保持真值→先撞坐标校验)
    bad_acts = np.linspace(-1, 1, 11)
    with pytest.raises(ValueError,
                       match="action coordinates"):
        ur.validate_dp_tables(
            "L0", dict(good, actions=bad_acts))
    # 账户坐标不符(真键→撞账户校验)
    with pytest.raises(ValueError,
                       match="account coordinates"):
        ur.validate_dp_tables(
            "L0", dict(good, accounts=np.linspace(
                -1.25, 1.25, 9)))
    # 形状不符
    with pytest.raises(ValueError, match="shape"):
        ur.validate_dp_tables(
            "L0", dict(good, V=np.zeros(
                (10, 60, len(good["accounts"])))))
    # GL 不符
    with pytest.raises(ValueError, match="gl"):
        ur.validate_dp_tables(
            "L0", dict(good, gl=13))
    # 键不符
    with pytest.raises(ValueError, match="dp_key"):
        ur.validate_dp_tables(
            "L0", dict(good, dp_key="forged"))
    # partial 标志拒;bars 错拒
    with pytest.raises(ValueError,
                       match="partial"):
        ur.validate_dp_tables(
            "L0", dict(good, completed=True,
                       partial=True))
    with pytest.raises(ValueError, match="bars"):
        ur.validate_dp_tables(
            "L0", dict(good, bars=3))
    # V 含 +inf 拒
    Vp = good["V"].copy()
    Vp[0, 0, 0] = math.inf
    with pytest.raises(ValueError, match="\+inf"):
        ur.validate_dp_tables("L0",
                              dict(good, V=Vp))


def _fake_key(tier, acts):
    import hashlib, json
    return ur._sha({
        "identity": ur.IDENTITY_DIGEST,
        "config": ur.CONFIG_DIGEST,
        "tier": ur.TIERS[tier],
        "actions": [float(x) for x in acts],
        "accounts": [float(x) for x in
                     ur.account_grid(tier)],
        "solver": ur.SOLVER_VERSION})


def test_query_Q_validates_and_outputs(fake_clock):
    tables = _fake_tables("L0")
    qrow = next(q for q in ur.QUESTIONS
                if q["id"] == "G001")
    out = ur.query_Q(qrow, "L0", tables)
    assert out["state"] == [qrow["s"], qrow["c"],
                            qrow["q"], qrow["g"]]
    assert out["remaining"] == 32
    assert set(out["q_rebals"]) == set(
        float(x) for x in ur.action_grid("L0"))
    assert out["grid"]["gl"] == 12
    assert out["grid"]["n_actions"] == 41
    # flat:V=0 表 → q_hold=0 且 w=0 恰等
    assert abs(out["q_hold"]) < 1e-12
    assert abs(out["q_rebals"][0.0]) < 1e-12
    # 部分表拒
    with pytest.raises(ValueError, match="completed"):
        ur.query_Q(qrow, "L0",
                   dict(tables, completed=False))
    # 越界 remaining 拒;total≠32 拒;账户 bool 拒
    with pytest.raises(ValueError):
        ur.query_Q(dict(qrow, remaining=40), "L0",
                   tables)
    with pytest.raises(ValueError, match="fixes total"):
        ur.query_Q(dict(qrow, total=64), "L0",
                   tables)
    bad_acct = dict(qrow, account={
        "cash": 100.0, "exposure": False,
        "solvency_raw": math.inf})
    with pytest.raises(ValueError):
        ur.query_Q(bad_acct, "L0", tables)


def test_validate_tier_outputs_content_level(
        fake_clock):
    acts = {t: [float(x) for x in
                ur.action_grid(t)]
            for t in ("L0", "L1", "L2")}
    per = {}
    for t in ("L0", "L1", "L2"):
        tb = _fake_tables(t)
        tb["questions"] = [
            {"id": q["id"], "s": q["s"], "c": q["c"],
             "q": q["q"], "g": q["g"],
             "remaining": q["remaining"],
             "total": q["total"],
             "q_hold": 0.0,
             "q_rebals": {w: 0.0 for w in acts[t]}}
            for q in ur.QUESTIONS]
        per[t] = tb
    ur.validate_tier_outputs(per)     # 完整合法过
    # 伪元数据:改 s 但 ID 不变 → 拒
    forged = per["L1"]["questions"][3]
    forged["s"] = 1
    with pytest.raises(ValueError,
                       match="content mismatch"):
        ur.validate_tier_outputs(per)
    forged["s"] = ur.QUESTIONS[3]["s"]
    # 只有 ID 无 Q → 拒
    stripped = [dict(q, q_rebals=None)
                for q in per["L2"]["questions"]]
    per["L2"]["questions"] = stripped
    with pytest.raises(ValueError,
                       match="full action set"):
        ur.validate_tier_outputs(per)
    # 缺一题 → 拒
    per["L0"]["questions"] = per["L0"][
        "questions"][:63]
    with pytest.raises(ValueError, match="missing"):
        ur.validate_tier_outputs(per)
    # Q 值域:NaN/+inf/字符串/bool 拒(-inf 允许)
    per = _full_fake()
    per["L0"]["questions"][2]["q_rebals"][
        0.5] = float("nan")
    with pytest.raises(ValueError, match="invalid"):
        ur.validate_tier_outputs(per)
    per["L0"]["questions"][2]["q_rebals"][
        0.5] = "0.5"
    with pytest.raises(ValueError, match="invalid"):
        ur.validate_tier_outputs(per)
    per["L0"]["questions"][2]["q_rebals"][
        0.5] = True
    with pytest.raises(ValueError, match="invalid"):
        ur.validate_tier_outputs(per)
    per["L0"]["questions"][2]["q_rebals"][
        0.5] = -math.inf   # 合法
    ur.validate_tier_outputs(per)


def _full_fake(tiers_rows=None, mutate=None):
    """受控完整假产物:三档真键/坐标/形状+64 条 questions;
    tiers_rows={tier:{qid:(q_hold,{w:q})}} 注入场景行。"""
    per = {}
    for t in ("L0", "L1", "L2"):
        tb = _fake_tables(t)
        qs = []
        for q in ur.QUESTIONS:
            base = {float(x): -1e-3
                    for x in ur.action_grid(t)}
            row = (tiers_rows or {}).get(
                t, {}).get(q["id"])
            qh = -0.5e-3
            if row is not None:
                qh = row[0]
                for k, v in row[1].items():
                    kf = float(k)
                    near = min(base, key=lambda g:
                               abs(g - kf))
                    assert abs(near - kf) < 1e-9
                    base[near] = float(v)
            qs.append({"id": q["id"], "s": q["s"],
                       "c": q["c"], "q": q["q"],
                       "g": q["g"],
                       "remaining": q["remaining"],
                       "total": q["total"],
                       "q_hold": qh,
                       "q_rebals": base})
        tb["questions"] = qs
        per[t] = tb
    if mutate:
        mutate(per)
    return per


def test_analyze_single_official_entry():
    # 完整假产物端到端通过
    rows = {}
    for t in ("L0", "L1", "L2"):
        acts = {0.5: 1e-3, -0.5: -1e-3}
        rows[t] = {"G001": (0.0, acts)}
    r = ur.analyze_tiers(_full_fake(rows))["G001"]
    assert r["status"] == "act"
    # 旧 qid→Q 字典格式 → validate 拒
    with pytest.raises(ValueError):
        ur.analyze_tiers({"L0": {"G001": {
            "q_hold": 0, "q_rebals": {}}}})
    # 缺一档 → 拒
    with pytest.raises(ValueError):
        full = _full_fake()
        del full["L2"]
        ur.analyze_tiers(full)
    # 缺一题 → 拒
    def drop(per):
        per["L1"]["questions"] = \
            per["L1"]["questions"][:63]
    with pytest.raises(ValueError, match="missing"):
        ur.analyze_tiers(_full_fake(mutate=drop))
    # 错身份 → 拒
    def swap(per):
        per["L0"]["tier"] = "L1"
    with pytest.raises(ValueError):
        ur.analyze_tiers(_full_fake(mutate=swap))
    # 漂移 → not_established
    drift_rows = {
        "L0": {"G002": (0.0, {0.1: 1e-3,
                              0.5: 9.9e-4})},
        "L1": {"G002": (0.0, {0.5: 1e-3,
                              0.1: 9.9e-4})},
        "L2": {"G002": (0.0, {0.9: 1e-3,
                              0.5: 9.9e-4})}}
    r2 = ur.analyze_tiers(
        _full_fake(drift_rows))["G002"]
    assert r2["status"] == "not_established"
    assert "drifted" in r2["reason"]
    # 正 margin 小于不确定尺度 → not_established(非 no_act)
    small_rows = {t: {"G003": (0.0, {
        0.5: {"L0": 0.5e-4, "L1": 0.2e-4,
              "L2": 0.05e-4}[t],
        -0.5: -1e-3})}
        for t in ("L0", "L1", "L2")}
    r3 = ur.analyze_tiers(
        _full_fake(small_rows))["G003"]
    assert r3["status"] == "not_established"
    # 无行动(best diff≤0)与无法判定分开
    noact_rows = {t: {"G004": (0.0, {
        0.5: -1e-3, -0.5: -2e-3})}
        for t in ("L0", "L1", "L2")}
    r4 = ur.analyze_tiers(
        _full_fake(noact_rows))["G004"]
    assert r4["status"] == "no_act"
