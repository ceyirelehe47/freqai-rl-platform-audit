# -*- coding: utf-8 -*-
"""five_point 手写小控制(零真实 V;小假表;不冒充整批控制流)。"""
import hashlib
import json
import math
import pathlib
import sys

import numpy as np
import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import five_point as FP  # noqa
import root_integrals as RI  # noqa

CFG = json.loads((HERE / "CONFIG_fivepoint.json")
                 .read_text(encoding="utf-8"))
LOCK = json.loads((HERE / "LOCK_FIVEPOINT.json")
                  .read_text(encoding="utf-8"))


def _acc_row():
    acc = np.array([-0.8, -0.5, -0.42, -0.38,
                    -26 / 128, -25 / 128, -0.19, 0.0,
                    0.2, 1.0], float)
    row = np.where(acc < -0.40, 0.02 + 0.5 * acc,
                   0.02 + 1.1 * acc)
    return acc, row


def test_lock_semantics():
    assert LOCK["si"] == 16
    assert LOCK["state"] == [-1, 1, 0.75, 0]
    assert LOCK["interval"]["expected"] == \
        [-0.203125, -0.1953125]
    assert LOCK["interval"]["iR"] == \
        LOCK["interval"]["iL"] + 1
    assert -0.203125 <= LOCK["post_at_mean"] <= -0.1953125
    assert len(LOCK["five_points"]) == 5
    assert LOCK["n_actions"] == 161


def test_fee_branches_and_flat_recovery():
    fee = 0.001
    e, w = -0.19, 0.2
    ff_we = FP.fee_frac(e, w, fee)
    assert ff_we == pytest.approx(
        fee * abs(w - e) / (1 + w * fee), rel=1e-15)
    w2 = -0.2
    ff_wl = FP.fee_frac(e, w2, fee)
    assert ff_wl == pytest.approx(
        fee * abs(w2 - e) / (1 - w2 * fee), rel=1e-15)
    # flat 恢复:C+log1p(-ff(0,w)) = Q_flat;且
    # C = Q_flat_helper + log1p(fee*|w|)(显式恒等)
    acc, row = _acc_row()
    C, _, _ = FP.c_of_w(0.2, 0.0, 0.03, acc, row, 1.25, 450)
    flat_fee_frac = FP.fee_frac(0.0, 0.2, fee)
    lhs = C + math.log1p(-flat_fee_frac)
    # 恒等:C = Qflat + log1p(fee*|w|) → Qflat = C - log1p(fee|w|)
    qflat = C - math.log1p(fee * abs(0.2))
    # 两途径相等(log 代数恒等)
    assert math.log1p(-flat_fee_frac) == pytest.approx(
        -math.log1p(fee * abs(0.2)), rel=1e-12)
    assert lhs == pytest.approx(qflat, rel=1e-15)


def test_w_equal_e_zero_fee_and_w0_close():
    acc, row = _acc_row()
    e = -0.19
    C_e, _, _ = FP.c_of_w(e, 0.0, 0.03, acc, row, 1.25, 450)
    qh = FP.evaluate_point(
        e, [e], [e], 0.0, 0.03, acc, row, 1.25, 450,
        0.001, FP.CCache({"x": 1}))["arms"]["hold:%r" % e]["q"]
    assert qh == pytest.approx(C_e, rel=1e-15)
    # w=0 关仓:C(0)=R(0);Q=R(0)+log1p(-fee_frac(e,0))
    C0, _, _ = FP.c_of_w(0.0, 0.0, 0.03, acc, row, 1.25, 450)
    v0, _ = FP._interp_row(acc, row, 0.0)
    assert C0 == pytest.approx(v0, rel=1e-15)
    q0 = C0 + math.log1p(-FP.fee_frac(e, 0.0, 0.001))
    assert math.isfinite(q0)


def test_negative_w_cross_node_pieces():
    acc, row = _acc_row()
    w = -0.4
    val, segs, bsum = FP.c_of_w(
        w, 0.0, 0.03, acc, row, 1.25, 450)
    assert len(segs) >= 2
    bs = {round(s["b"], 9) for s in segs}
    assert len(bs) >= 1   # 假行节点内分片
    k = math.sqrt(3) * 0.03
    x_lo, x_hi = -k, k

    def f(x):
        lg = RI.flat_root_lg(w, x, fee=0.0)
        e2 = RI.exposure_after(w, x)
        v, _ = FP._interp_row(acc, row, e2)
        return lg + v
    n = 4000
    h = (x_hi - x_lo) / n
    simp = f(x_lo) + f(x_hi)
    for i in range(1, n):
        simp += f(x_lo + i * h) * (4 if i % 2 else 2)
    simp *= h / 3
    assert val == pytest.approx(0.5 / k * simp, abs=1e-8)


def test_const_continuation_shifts_not_gaps():
    acc, row = _acc_row()
    row2 = row + 0.7
    acts = [-0.2, -0.1]
    r1 = FP.evaluate_point(-0.19, acts, [-0.19],
                           0.0, 0.03, acc, row, 1.25,
                           450, 0.001, FP.CCache({}))
    r2 = FP.evaluate_point(-0.19, acts, [-0.19],
                           0.0, 0.03, acc, row2, 1.25,
                           450, 0.001, FP.CCache({}))
    ks = sorted(r1["arms"])
    d1 = (r1["arms"][ks[0]]["q"]
          - r1["arms"][ks[1]]["q"])
    d2 = (r2["arms"][ks[0]]["q"]
          - r2["arms"][ks[1]]["q"])
    assert d1 == pytest.approx(d2, rel=1e-12, abs=1e-15)
    assert r2["F"] == pytest.approx(
        r1["F"] + 0.7, rel=1e-12)


def test_two_line_max_kink_identity():
    """两线性 max 折点:五点 F 与插值缺陷分解精确核对。"""
    eL, eR = -26 / 128, -25 / 128
    pts = [eL, eL + 0.25 * (eR - eL),
           0.5 * (eL + eR),
           eL + 0.75 * (eR - eL), eR]

    def f(e):
        return max(0.3 * (e - eL), 0.3 * (eR - eL)
                   - 0.9 * (e - eL))
    F = [f(e) for e in pts]
    # V31 取 F 本身 → 端点差 0,恒等式闭包 0
    an = FP.interp_analysis(pts, F, [F[0], None,
                                     None, None, F[4]],
                            eL, eR)
    for it in an["identity"]:
        assert it["closure"] == pytest.approx(
            0.0, abs=1e-15)
    # 折点在中点:max 两线交点恰中点 → 细插值在四分点有
    # 负缺陷(凹),粗缺陷≥细缺陷;比值有限非零
    q1, q3 = an["quartiles"]
    # max(两仿射)=凸:弦在上方;折点恰在 q1(谷),
    # q3 落右段共线 → 细缺陷 0(标注不可比,非收敛)
    assert q1["fine_minus_F"] > 0
    assert q3["fine_minus_F"] == 0.0
    assert q3["ratio"] == "incomparable_zero_fine"
    assert q1["abs_coarse"] > q1["abs_fine"]
    assert q1["ratio"] == pytest.approx(1.5, rel=1e-9)


def test_cache_isolation_and_identity_first(
        tmp_path, monkeypatch):
    acc, row = _acc_row()
    c1 = FP.CCache({"id": "a"})
    c2 = FP.CCache({"id": "b"})
    n = {"c": 0}

    def comp():
        n["c"] += 1
        return FP.c_of_w(0.2, 0.0, 0.03, acc, row,
                         1.25, 450)
    c1.get(0.2, comp)
    c1.get(0.2, comp)
    assert (c1.hits, c1.miss) == (1, 1)
    c2.get(0.2, comp)     # 实例隔离:重新计算
    assert (c2.hits, c2.miss) == (0, 1)
    assert n["c"] == 2


def _mk_env(tmp_path, tamper=None):
    ev = tmp_path / ("ev2" if tamper else "ev1")
    ev.mkdir()
    acc = [-0.8, -0.5, -0.42, -0.38,
           -26 / 128, -25 / 128, -0.19, 0.0,
           0.2, 1.0]
    acts = [-1 + 2 * i / 40 for i in range(41)]
    tier = {"tier_meta": {
        "dp_key": CFG["pins"]["dp_key"],
        "actions": acts, "accounts": acc}}
    (ev / "tier_L2.json").write_text(
        json.dumps(tier), encoding="utf-8")
    V = np.zeros((33, 60, 10))
    arr = np.array(acc)
    for t in (30, 31):
        V[t, 16, :] = np.where(
            arr < -0.40, 0.02 + 0.5 * arr,
            0.02 + 1.1 * arr)
    np.save(ev / "V_L2.npy", V)
    lock = json.loads(json.dumps(LOCK))
    lock["v_sha256"] = hashlib.sha256(
        (ev / "V_L2.npy").read_bytes()).hexdigest()
    lock["n_actions"] = 41
    lock["n_accounts"] = 10
    lock["interval"]["iL"] = 3
    lock["interval"]["iR"] = 4
    lp = tmp_path / "lock.json"
    lp.write_text(json.dumps(lock), encoding="utf-8")
    cfg = json.loads(json.dumps(CFG))
    cfg["pins"]["tier_sha256"] = hashlib.sha256(
        (ev / "tier_L2.json").read_bytes()).hexdigest()
    cfg["pins"]["lock_sha256"] = hashlib.sha256(
        lp.read_bytes()).hexdigest()
    cfg["pins"]["v_shape"] = [33, 60, 10]
    cp = tmp_path / "cfg.json"
    cp.write_text(json.dumps(cfg, ensure_ascii=False),
                  encoding="utf-8")
    if tamper == "V":
        # 锁文件改 V sha → run 应拒
        lock2 = json.loads(json.dumps(lock))
        lock2["v_sha256"] = "0" * 64
        lp2 = tmp_path / "lock_tamper.json"
        lp2.write_text(json.dumps(lock2), encoding="utf-8")
        cfg2 = json.loads(json.dumps(cfg))
        cfg2["pins"]["lock_sha256"] = hashlib.sha256(
            lp2.read_bytes()).hexdigest()
        cp2 = tmp_path / "cfg_tamper.json"
        cp2.write_text(json.dumps(cfg2), encoding="utf-8")
        return ev, lp2, cp2
    return ev, lp, cp


def test_identity_gate_before_V(tmp_path, monkeypatch):
    ev, lp, cp = _mk_env(tmp_path)
    monkeypatch.setattr(
        FP, "CONFIG_SHA256",
        hashlib.sha256(cp.read_bytes()).hexdigest())
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("V before gates")
    # 篡改 tier
    cfg2 = json.loads(cp.read_text(encoding="utf-8"))
    cfg2["pins"]["tier_sha256"] = "0" * 64
    cp2 = tmp_path / "c2.json"
    cp2.write_text(json.dumps(cfg2), encoding="utf-8")
    monkeypatch.setattr(
        FP, "CONFIG_SHA256",
        hashlib.sha256(cp2.read_bytes()).hexdigest())
    out = tmp_path / "o1"
    with pytest.raises(ValueError, match="tier SHA"):
        FP.run(str(ev), str(lp), str(out),
               cfg_path=str(cp2), loader_np=boom)
    assert called["n"] == 0
    # V 与锁不符
    ev2, lp2, cp3 = _mk_env(tmp_path, tamper="V")
    monkeypatch.setattr(
        FP, "CONFIG_SHA256",
        hashlib.sha256(cp3.read_bytes()).hexdigest())
    out2 = tmp_path / "o2"
    with pytest.raises(ValueError, match="V SHA"):
        FP.run(str(ev2), str(lp2), str(out2),
               cfg_path=str(cp3), loader_np=boom)
    assert called["n"] == 0


# (删除)旧 test_full_run_and_output_fail 与其内联 guard/输出失败
# 段:原走 41 动作整批真实切段核——已被下方 fake evaluator 版
# 完整取代(调用即失败 spy 防 fallback);独立臂级数学控制保留
# 于本文件他处。历史实际执行(假表真核)不抹除,登记于
# WORK_REGISTRY 说明。


def test_default_config_gate(tmp_path, monkeypatch):
    """默认入口(不猴补 CONFIG_SHA256):过 CONFIG 门后于
    锁文件缺失处失败;真实 loader 未被调用。"""
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("V loaded before gates")
    nofile = tmp_path / "no_such_lock.json"
    out = tmp_path / "o0"
    with pytest.raises(FileNotFoundError):
        FP.run(str(tmp_path), str(nofile), str(out),
               loader_np=boom)   # cfg_path 缺省=HERE 真配置
    assert called["n"] == 0
    assert (out / "FAILED.marker").exists()


def _fake_evaluator_factory(store):
    """手写假 evaluator(完整 run/guard/输出失败控制用);
    不触碰真实切段核。"""

    def ev(w, mu, sigma, acc, row, dd, cap, bud=None):
        v = 0.05 + 0.3 * float(w)
        seg = [{"x_lo": -1.0, "x_hi": 1.0,
                "account_index": 0,
                "a": v, "b": 0.0,
                "series_branch": False,
                "post_bound": 0.0,
                "value": v}]
        store["calls"] += 1
        return v, seg, 0.0
    return ev


def test_full_run_fake_evaluator(tmp_path, monkeypatch):
    ev, lp, cp = _mk_env(tmp_path)
    monkeypatch.setattr(
        FP, "CONFIG_SHA256",
        hashlib.sha256(cp.read_bytes()).hexdigest())
    store = {"calls": 0}
    # spy:真实 c_of_w/RI 一旦被调即失败(防漏回真实核)
    monkeypatch.setattr(
        FP, "c_of_w",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("real kernel hit")))
    import root_integrals as _RI
    monkeypatch.setattr(
        _RI, "seg_integral_bounded",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("real RI hit")))
    out = tmp_path / "o3f"
    rep = FP.run(str(ev), str(lp), str(out),
                 cfg_path=str(cp),
                 evaluator=_fake_evaluator_factory(store))
    assert (out / "DONE.marker").exists()
    assert len(rep["points"]) == 5
    for p in rep["points"]:
        assert len(p["arms"]) == 42
        assert p["winners"]
        for k, a in p["arms"].items():
            assert a["q"] == pytest.approx(
                a["C"] + a["log_fee"], rel=1e-15)
            assert a["closure"] < 1e-9
            assert "I_V31" in p and "coarse_at_e" in p \
                and "fine_at_e" in p
        break   # 逐点字段在 point 层
    for p in rep["points"]:
        assert "I_V31" in p
    assert rep["n_assembled"] == 210
    # 唯一计算臂=41+5=46(cache miss),非 5×42
    assert rep["cache_stats"]["miss"] == 46
    assert store["calls"] == 46
    # Ops 前置计数:arms=46(唯一),assembly=210;pieces 由
    # 真实核 consume 回调计,fake evaluator 不触发(=0)
    assert rep["ops_used"]["arms"] == 46
    assert rep["ops_used"]["assembly"] == 210
    assert rep["ops_used"]["pieces"] == 0


def test_guard_fake_evaluator(tmp_path, monkeypatch):
    ev, lp, cp = _mk_env(tmp_path)
    monkeypatch.setattr(
        FP, "CONFIG_SHA256",
        hashlib.sha256(cp.read_bytes()).hexdigest())
    st = {"n": 0}

    def clock():
        st["n"] += 1
        if st["n"] > 6:
            if st["n"] > 7:
                raise RuntimeError("measure-dead")
            return 1000.0
        return 0.0
    out = tmp_path / "o5f"
    with pytest.raises(RuntimeError, match="wall_clock"):
        FP.run(str(ev), str(lp), str(out),
               cfg_path=str(cp),
               clock=(clock, lambda: 0.0),
               evaluator=_fake_evaluator_factory({"calls": 0}))
    main = json.loads((out / "five_point.json")
                      .read_text(encoding="utf-8"))
    assert main["status"] == "failed"
    assert "wall_clock" in main["fail_reason"]


def test_output_fail_fake_evaluator(tmp_path, monkeypatch):
    ev, lp, cp = _mk_env(tmp_path)
    monkeypatch.setattr(
        FP, "CONFIG_SHA256",
        hashlib.sha256(cp.read_bytes()).hexdigest())
    real = json.dump

    def bad(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(json, "dump", bad)
    out = tmp_path / "o4f"
    with pytest.raises(OSError):
        FP.run(str(ev), str(lp), str(out),
               cfg_path=str(cp),
               evaluator=_fake_evaluator_factory({"calls": 0}))
    assert (out / "FAILED.marker").exists()
    assert not (out / "DONE.marker").exists()


def test_status():
    assert FP.STATUS == "PREPARED_NOT_RUN"
