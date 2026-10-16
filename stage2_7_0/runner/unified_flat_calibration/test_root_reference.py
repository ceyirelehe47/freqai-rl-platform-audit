# -*- coding: utf-8 -*-
"""root_reference v2 手写小测(零真实 V/Q;小假表;official 接线)。
v2 新覆盖:真实阈值 why、首次超限保首错、坏 CONFIG 收尾、
负 w 连续异斜率行(暴露账户索引错)。"""
import hashlib
import json
import math
import pathlib
import sys

import numpy as np
import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import root_reference as RR  # noqa
import root_integrals as RI  # noqa

CFG = json.loads((HERE / "CONFIG_rootref.json").read_text(encoding="utf-8"))
TRIGGER_CALL = 36   # 实测:计算期恰 36 次,guard1=第 37 次


def test_P_and_Vprev_row():
    states, P = RR.build_P(CFG["kernel_frozen"])
    assert len(states) == 60
    a = states.index((-1, 0, 0.0, 0))
    diag = ((.78 + .22 / 3) * (.75 + .125)
            * (.8 + .2 * .125) * (.8 + .1))
    assert P[a, a] == pytest.approx(diag, rel=1e-12)
    np.testing.assert_allclose(P.sum(axis=1), 1.0, rtol=1e-12)
    Vprev = np.zeros((60, 5))
    Vprev[3] = 1.0
    row = (P @ Vprev)[10]
    np.testing.assert_allclose(row, P[10, 3], rtol=1e-15)


V0 = 0.05
BP = -0.40   # 断点在 w=-.4 的 post 值域 [-.431,-.372] 内


def _cont_row(e):
    """连续异斜率:e<BP 斜率 .5,e>=BP 斜率 1.3(BP 处连续=V0)。"""
    if e < BP:
        return V0 + 0.5 * (e - BP)
    return V0 + 1.3 * (e - BP)


def _fake_acc_row():
    acc = np.array([-0.8, -0.5, -0.41, -0.40, -0.2, 0.0,
                    0.2, 0.395, 0.405, 0.6, 1.0, 1.25], float)
    row = np.array([_cont_row(e) for e in acc])
    return acc, row


def test_cross_pieces_negative_w_diff_slopes():
    acc, row = _fake_acc_row()
    w, mu, sigma, fee = -0.4, 0.0, 0.03, 0.001
    val, segs, bsum = RR.rebal_reference(
        w, mu, sigma, fee, acc, row, 1.25, 450)
    assert len(segs) >= 3
    xs = [s["x_lo"] for s in segs]
    assert xs == sorted(xs)
    # 断点两侧实际访问的片段斜率至少两种(BP 生效)
    bs = {round(seg["b"], 9) for seg in segs}
    assert len(bs) >= 2
    # 切点(node=-0.40)在支撑内(局部 k 重算,先后序无关)
    _k = math.sqrt(3) * sigma
    _x_lo, _x_hi = mu - _k, mu + _k
    xc = RI.solve_x_at_exposure(w, -0.40)
    assert _x_lo < xc < _x_hi
    # 每段 series_branch 布尔存在
    assert all(isinstance(s["series_branch"], bool)
               for s in segs)
    # Simpson 独立参考(4000;同假行分段,暴露索引错位)
    k = math.sqrt(3) * sigma
    x_lo, x_hi = mu - k, mu + k

    def f(x):
        lg = RI.flat_root_lg(w, x, fee)
        e = RI.exposure_after(w, x)
        v, _ = RR._interp_row(acc, row, e)
        return lg + v
    n = 4000
    h = (x_hi - x_lo) / n
    simp = f(x_lo) + f(x_hi)
    for i in range(1, n):
        simp += f(x_lo + i * h) * (4 if i % 2 else 2)
    simp *= h / 3
    assert val == pytest.approx(0.5 / k * simp, rel=1e-9)
    assert bsum >= 0.0


def test_w0_and_w_plus_one_degenerate():
    acc, row = _fake_acc_row()
    v0, segs, b = RR.rebal_reference(
        0.0, 0.0, 0.03, 0.001, acc, row, 1.25, 450)
    assert len(segs) == 1
    assert v0 == pytest.approx(_cont_row(0.0), abs=1e-15)
    v1, segs1, _ = RR.rebal_reference(
        1.0, 0.0, 0.03, 0.001, acc, row, 1.25, 450)
    assert len(segs1) == 1
    assert int(segs1[0]["account_index"]) == \
        int(np.searchsorted(acc, 1.0, side="right")) - 1


def test_dense_domain_violation_and_cap():
    acc, row = _fake_acc_row()
    with pytest.raises(ValueError, match="dense"):
        RR.rebal_reference(-1.0, 0.0, 0.5, 0.001, acc, row, 1.25, 450)
    acc2 = np.linspace(-1.2, 1.2, 300)
    row2 = 0.1 + 0.5 * acc2
    with pytest.raises(ValueError, match="cap"):
        RR.rebal_reference(0.5, 0.0, 0.03, 0.001, acc2, row2, 1.25, 2)


def test_real_threshold_why():
    c1 = {"n": [0.0]}
    def nw1():
        c1["n"][0] += 100.0   # t0=100;下次 200→wall=100>10
        return c1["n"][0]
    bud = RR.JobBudget(
        {"wall_s": 10.0, "cpu_s": 5.0, "rss_kib": 131072},
        clock=(nw1, lambda: 0.0))
    why, m = bud.checkpoint()
    assert why == "wall_clock"
    c2 = {"n": [0.0]}
    def nc2():
        c2["n"][0] += 50.0    # c0=50;下次 100→cpu=50>5
        return c2["n"][0]
    bud2 = RR.JobBudget(
        {"wall_s": 10.0, "cpu_s": 5.0, "rss_kib": 131072},
        clock=(lambda: 0.0, nc2))
    why2, _ = bud2.checkpoint()
    assert why2 == "cpu"


def _mk_env(tmp_path, tamper=None):
    ev = tmp_path / ("ev2" if tamper else "ev1")
    ev.mkdir()
    man = json.loads((HERE / "LOCKED_MANIFEST.json")
                     .read_text(encoding="utf-8"))
    acc = [-0.8, -0.5, -0.41, -0.40, -0.2, 0.0,
           0.2, 0.395, 0.405, 0.6, 1.0, 1.25]
    tier = {"tier_meta": {"dp_key": CFG["pins"]["dp_key"],
                          "gl": 48, "budget": {"tier": "L2"},
                          "accounts": acc},
            "questions": []}
    for qid in man["per_root"]:
        tier["questions"].append({
            "id": qid, "s": -1, "c": 1, "q": 0.75, "g": 0,
            "remaining": 32, "total": 32,
            "q_hold": 0.0, "q_rebals": {"0.2": 0.0}})
    (ev / "tier_L2.json").write_text(json.dumps(tier), encoding="utf-8")
    arr = np.array(acc)
    V = np.zeros((33, 60, 12))
    V[31, :, :] = np.where(arr < 0, 0.1 + 0.5 * arr,
                           0.1 + 1.2 * arr)
    np.save(ev / "V_L2.npy", V)
    vsha = hashlib.sha256((ev / "V_L2.npy").read_bytes()).hexdigest()
    if tamper != "V":
        man["v_l2"]["sha256"] = vsha
    mp = tmp_path / "man.json"
    mp.write_text(json.dumps(man), encoding="utf-8")
    cfg = json.loads(json.dumps(CFG))
    cfg["pins"]["tier_L2_sha256"] = hashlib.sha256(
        (ev / "tier_L2.json").read_bytes()).hexdigest()
    cfg["pins"]["locked_manifest_sha256"] = hashlib.sha256(
        mp.read_bytes()).hexdigest()
    cfg["pins"]["v_shape"] = [33, 60, 12]
    cp = tmp_path / "cfg.json"
    cp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return ev, mp, cp, cfg


def _pin_cfg(monkeypatch, cp):
    monkeypatch.setattr(
        RR, "CONFIG_SHA256",
        hashlib.sha256(cp.read_bytes()).hexdigest())


def test_wrong_sha_before_V(tmp_path, monkeypatch):
    ev, mp, cp, cfg = _mk_env(tmp_path)
    _pin_cfg(monkeypatch, cp)
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("V consumed before SHA gate")
    cfg2 = json.loads(cp.read_text(encoding="utf-8"))
    cfg2["pins"]["tier_L2_sha256"] = "0" * 64
    cp2 = tmp_path / "cfg2.json"
    cp2.write_text(json.dumps(cfg2), encoding="utf-8")
    monkeypatch.setattr(
        RR, "CONFIG_SHA256",
        hashlib.sha256(cp2.read_bytes()).hexdigest())
    out = tmp_path / "o1"
    with pytest.raises(ValueError, match="tier SHA"):
        RR.run(str(ev), str(mp), str(out),
               cfg_path=str(cp2), loader_np=boom)
    assert called["n"] == 0
    ev2, mp2, cp3, _ = _mk_env(tmp_path, tamper="V")
    monkeypatch.setattr(
        RR, "CONFIG_SHA256",
        hashlib.sha256(cp3.read_bytes()).hexdigest())
    out2 = tmp_path / "o2"
    with pytest.raises(ValueError, match="V_L2"):
        RR.run(str(ev2), str(mp2), str(out2),
               cfg_path=str(cp3), loader_np=boom)
    assert called["n"] == 0


def test_bad_config_fail_closed(tmp_path, monkeypatch):
    ev, mp, cp, cfg = _mk_env(tmp_path)
    # 不改 pin:直接用坏字节文件
    bad = tmp_path / "bad.json"
    bad.write_text("{}\n", encoding="utf-8")
    out = tmp_path / "o3"
    with pytest.raises(ValueError, match="CONFIG SHA"):
        RR.run(str(ev), str(mp), str(out), cfg_path=str(bad))
    assert (out / "FAILED.marker").exists()
    assert not (out / "RUNNING.marker").exists()
    main = json.loads((out / "root_reference.json")
                      .read_text(encoding="utf-8"))
    assert main["status"] == "failed"


def test_hold_no_fee_and_run_ok(tmp_path, monkeypatch):
    ev, mp, cp, cfg = _mk_env(tmp_path)
    _pin_cfg(monkeypatch, cp)
    out = tmp_path / "o4"
    rep = RR.run(str(ev), str(mp), str(out), cfg_path=str(cp))
    assert (out / "DONE.marker").exists()
    holds = [it for it in rep["items"] if it["kind"] == "HOLD"]
    assert len(holds) == 8
    for it in holds:
        assert it["reference_value"] == pytest.approx(0.1, abs=1e-12)
        assert it["segments"][0]["lg"] == 0.0
    assert rep["n_items"] == 24
    # v2 补充输出
    assert rep["input_shas"]["V_L2"]
    assert rep["config_sha256"]
    assert rep["param_digest"]
    for qid, m in rep["root_meta"].items():
        assert m["state"] == [-1, 1, 0.75, 0]
        assert m["remaining"] == 32
        assert 0 <= m["si"] < 60
    for qid, d in rep["root_diffs"].items():
        assert set(d) >= {
            "gl48_second_minus_hold",
            "delta_best_hold_vs_gl48",
            "delta_second_hold_vs_gl48",
            "delta_best_second_vs_gl48"}
    for it in rep["items"]:
        if it["kind"] in ("best", "second"):
            assert all(isinstance(s.get("series_branch"), bool)
                       for s in it["segments"])


def test_first_overrun_keeps_first_error(
        tmp_path, monkeypatch):
    ev, mp, cp, cfg = _mk_env(tmp_path)
    _pin_cfg(monkeypatch, cp)
    state = {"t": [0.0]}

    def clock_wall():
        state["t"][0] += 1.0
        t = state["t"][0]
        if 3.0 < t <= 6.0:
            return 1000.0    # wall 巨大→超限(真实阈值路径)
        if t > 6.0:
            raise RuntimeError("measure-dead")
        return 0.0
    out = tmp_path / "o5"
    with pytest.raises(RuntimeError, match="wall_clock"):
        RR.run(str(ev), str(mp), str(out),
               cfg_path=str(cp),
               clock=(clock_wall, lambda: 0.0))
    main = json.loads((out / "root_reference.json")
                      .read_text(encoding="utf-8"))
    assert main["status"] == "failed"
    assert "wall_clock" in main["fail_reason"]
    fs_ok = True
    if (out / "FAIL_STATE.json").exists():
        pass
    assert (out / "FAILED.marker").exists()
    assert not (out / "DONE.marker").exists()
    assert not (out / "RUNNING.marker").exists()


def test_official_snapshot_wiring(tmp_path):
    """launcher 快照含 LOCKED_MANIFEST+helper(stages 桩跑通)。
    零真实数据;仅验证 snapshot 内容面。"""
    import subprocess
    d = HERE
    fa = tmp_path / "att"
    fa.mkdir()
    r = subprocess.run(
        ["bash", str(d / "launch_rootref.sh"), str(fa),
         "wire", "stages",
         "bash", "-c", "exit 0", "--",
         "/usr/bin/timeout", "-k", "1", "10", "/usr/bin/time", "-v",
         "bash", "-c", "exit 0"],
        capture_output=True, text=True)
    assert r.returncode == 0
    snapdirs = list(fa.glob("wire_*"))
    assert len(snapdirs) == 1
    snap = snapdirs[0] / "snapshot"
    for name in ("launch_rootref.sh", "inner_rootref.sh",
                 "root_reference.py", "root_integrals.py",
                 "test_root_reference.py", "CONFIG_rootref.json"):
        assert (snap / name).exists()
    man = (snap / "sha256.manifest").read_text()
    assert "root_integrals.py" in man


def test_guard1_first_post_save(tmp_path, monkeypatch):
    """精确触发第一次写后 guard1:首因 wall_clock 保留,
    收尾测量再抛错仅入 measurement_error。"""
    ev, mp, cp, cfg = _mk_env(tmp_path)
    _pin_cfg(monkeypatch, cp)
    st = {"n": 0}

    def clock_wall():
        st["n"] += 1
        if st["n"] > TRIGGER_CALL:
            if st["n"] > TRIGGER_CALL + 1:
                raise RuntimeError("measure-dead")
            return 1000.0
        return 0.0
    out = tmp_path / "o6"
    with pytest.raises(RuntimeError, match="wall_clock"):
        RR.run(str(ev), str(mp), str(out),
               cfg_path=str(cp),
               clock=(clock_wall, lambda: 0.0))
    main = json.loads((out / "root_reference.json")
                      .read_text(encoding="utf-8"))
    assert main["status"] == "failed"
    assert "wall_clock" in main["fail_reason"]
    assert main["measurement_point"] == \
        "after_initial_main_save_guard1"
    assert "measure-dead" in main.get(
        "measurement_error", "")
    assert not (out / "DONE.marker").exists()


def test_default_config_load_positive(tmp_path):
    """默认 CONFIG(无 monkeypatch):只读本配置即通过
    SHA+digest 门(后续在 manifest 处失败=证明过了配置门)。"""
    dummy = tmp_path / "notman.json"
    dummy.write_text("{}", encoding="utf-8")
    out = tmp_path / "o7"
    with pytest.raises(ValueError,
                       match="manifest SHA"):
        RR.run(str(tmp_path), str(dummy),
               str(out))   # cfg_path 缺省=HERE 真配置
    assert (out / "FAILED.marker").exists()


def test_status():
    assert RR.STATUS == "PREPARED_NOT_RUN"
