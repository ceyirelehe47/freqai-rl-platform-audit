# -*- coding: utf-8 -*-
"""tau v2 官方小测:两根不同 ε 确定值;生产 run 真调用
(仅测试内替换 verify_inputs,生产钉 SHA 不动);写后一般
故障与收尾预算再故障。零真实输入文件。"""
import json
import math
import pathlib
import sys

import pytest

HERE = pathlib.Path(
    __file__).resolve().parent
sys.path.insert(0, str(HERE))

import tau_sensitivity as ts  # noqa


def test_two_roots_different_eps_exact():
    L, U = ts.lu_bounds([0.2, 0.4],
                        0.01)
    assert L == pytest.approx(
        [0.18, 0.38], abs=1e-15)
    assert U == pytest.approx(
        [0.22, 0.42], abs=1e-15)
    Lb, Ub = ts.lu_bounds(
        [0.3, 0.05], 0.02)
    assert Lb == pytest.approx(
        [0.26, 0.01], abs=1e-15)
    assert Ub == pytest.approx(
        [0.34, 0.09], abs=1e-15)
    w = ts.robust_window(
        [0.2, 0.4], [0.3, 0.05],
        0.01, 0.02)
    # lower=max(.22,.09)=.22;
    # per-pt maxL=(.26,.36)→upper=.26
    assert w["lower"] == pytest.approx(
        0.22, abs=1e-15)
    assert w["upper"] == pytest.approx(
        0.26, abs=1e-15)
    assert w["nonempty"] is True
    assert w["lower_closed"] and not \
        w["upper_closed"]


def _mk_inputs(tmp_path):
    """8 根/41 点/8 个不同 proxy 手写输入。"""
    roots = ts.ROOTS
    a_regrets = {}
    v2 = {"analysis_v2": {}}
    for k, r in enumerate(roots):
        R = [round(
            0.01 + 0.002
            * ((i * (7 + k)) % 41),
            6)
            for i in range(41)]
        a_regrets[r] = {
            "common_R": R}
        v2["analysis_v2"][r] = {
            "uncertainty_q_units":
                0.002 + 0.001 * k}
    a = {"regrets": a_regrets}
    pa = tmp_path / "a.json"
    pv = tmp_path / "v2.json"
    pa.write_text(
        json.dumps(a),
        encoding="utf-8")
    pv.write_text(
        json.dumps(v2),
        encoding="utf-8")
    return pa, pv, a, v2


def test_production_run_assembly(
        tmp_path, monkeypatch):
    pa, pv, a, v2 = \
        _mk_inputs(tmp_path)
    monkeypatch.setattr(
        ts, "verify_inputs",
        lambda p, q: (
            "fa" * 32, "fv" * 32))
    out = tmp_path / "out"
    rep = ts.run(str(pa), str(pv),
                 str(out))
    assert (out /
            "DONE.marker").exists()
    assert rep[
        "status"] == "completed"
    assert rep["inputs"][
        "verified"] is True
    assert rep[
        "measurement_point"] == \
        "after_initial_main_save"
    assert "budget_final" in rep
    assert set(
        rep["roots"]) == set(
        ts.ROOTS)
    assert set(
        rep["pairs"]) == set(
        ts.PAIRS)
    # 抽根核:R/proxy/两情景 L·U 装配
    r0 = ts.ROOTS[0]
    R = a["regrets"][r0][
        "common_R"]
    px = v2["analysis_v2"][
        r0][
        "uncertainty_q_units"]
    rr = rep["roots"][r0]
    assert rr["R"] == R
    assert rr["proxy"] == px
    assert rr["scenarios"][
        "eps_zero"]["L"] == [
        max(0.0, x) for x in R]
    assert rr["scenarios"][
        "eps_proxy"]["U"] == [
        x + 2 * px for x in R]
    # 抽对核:公式重算
    n0 = next(iter(ts.PAIRS))
    qa, qb = ts.PAIRS[n0]
    for scn in ("eps_zero",
                "eps_proxy"):
        e = (0.0 if scn
             == "eps_zero"
             else rep["roots"][
                 qa]["proxy"])
        w = rep["pairs"][n0][
            scn]
        La = [
            max(0.0, x - 2 * e)
            for x in
            a["regrets"][qa][
                "common_R"]]
        Lb = [
            max(0.0, x - 2 * e)
            for x in
            a["regrets"][qb][
                "common_R"]]
        upper = min(
            max(u, v)
            for u, v in
            zip(La, Lb))
        assert w["upper"] == \
            pytest.approx(
                upper, abs=1e-12)


def test_post_save_generic_fault(
        tmp_path, monkeypatch):
    """写后一般故障:主报告权威 failed,roots/pairs
    保留,FAILED.marker,无 DONE;原异常抛出。"""
    pa, pv, _a, _v = \
        _mk_inputs(tmp_path)
    real_ckpt = ts.JobBudget.\
        checkpoint
    calls = {"n": 0}

    def flaky(self):
        calls["n"] += 1
        # 前 8+4 次正常(计算期);写后首查即抛
        if calls["n"] >= 13:
            raise RuntimeError(
                "post-write "
                "probe")
        return real_ckpt(self)

    monkeypatch.setattr(
        ts.JobBudget,
        "checkpoint", flaky)
    monkeypatch.setattr(
        ts, "verify_inputs",
        lambda p, q: ("f",
                      "f"))
    out = tmp_path / "o2"
    with pytest.raises(
            RuntimeError,
            match="post-write"):
        ts.run(str(pa),
               str(pv), str(out))
    main = json.loads(
        (out /
         "tau_sensitivity.json"
         ).read_text(
             encoding="utf-8"))
    assert main[
        "status"] == "failed"
    assert "post-write" in \
        main["fail_reason"]
    assert main["roots"] and \
        main["pairs"]
    fs = json.loads(
        (out /
         "FAIL_STATE.json"
         ).read_text(
             encoding="utf-8"))
    assert fs["status"] == \
        "failed"
    assert (out /
            "FAILED.marker"
            ).exists()
    assert not (out /
                "DONE.marker"
                ).exists()


def test_finalize_budget_refail_keeps_original(
        tmp_path, monkeypatch):
    """收尾预算读取再抛错:记 measurement_error,
    保留原错(抛出原 post-write probe 而非 budget 错)。"""
    pa, pv, _a, _v = \
        _mk_inputs(tmp_path)
    real_ckpt = ts.JobBudget.\
        checkpoint
    calls = {"n": 0}

    def dying(self):
        calls["n"] += 1
        if calls["n"] >= 13:
            raise RuntimeError(
                "post-write "
                "probe")
        return real_ckpt(self)

    def dead_in_finalize(
            self):
        # except 内再读预算即死
        raise RuntimeError(
            "budget-read-dead")

    orig_class = \
        ts.JobBudget
    state = {"phase": 0}

    class TwoPhase(
            orig_class):
        def checkpoint(
                self):
            if state[
                    "phase"] == 0:
                calls["n"] += 1
                if calls[
                        "n"] >= 13:
                    state[
                        "phase"] = 1
                    raise (
                        RuntimeError
                        ("post-write"
                         " probe"))
                return \
                    orig_class.\
                    checkpoint(
                        self)
            raise (
                RuntimeError
                ("budget-read-"
                 "dead"))

    monkeypatch.setattr(
        ts, "JobBudget",
        TwoPhase)
    monkeypatch.setattr(
        ts, "verify_inputs",
        lambda p, q: ("f",
                      "f"))
    out = tmp_path / "o3"
    with pytest.raises(
            RuntimeError,
            match="post-write"):
        ts.run(str(pa),
               str(pv), str(out))
    fs = json.loads(
        (out /
         "FAIL_STATE.json"
         ).read_text(
             encoding="utf-8"))
    assert (
        "budget-read-"
        "dead") in fs.get(
            "measurement_"
            "error", "")
    assert "post-write" in \
        fs["reason"]
    main = json.loads(
        (out /
         "tau_sensitivity.json"
         ).read_text(
             encoding="utf-8"))
    assert main[
        "status"] == "failed"
    assert not (out /
                "DONE.marker"
                ).exists()


def test_mid_compute_fault_keeps_partial(
        tmp_path, monkeypatch):
    """中途预算失败:已算 roots 随权威 failed
    报告保留(空容器即挂+增量更新),pairs 空。"""
    pa, pv, _a, _v = \
        _mk_inputs(tmp_path)
    real_ckpt = ts.JobBudget.\
        checkpoint
    calls = {"n": 0}

    def die_at_3(self):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RuntimeError(
                "mid-compute " "boom")
        return real_ckpt(self)

    monkeypatch.setattr(
        ts.JobBudget,
        "checkpoint", die_at_3)
    monkeypatch.setattr(
        ts, "verify_inputs",
        lambda p, q: ("f", "f"))
    out = tmp_path / "o4"
    with pytest.raises(
            RuntimeError,
            match="mid-compute"):
        ts.run(str(pa),
               str(pv), str(out))
    # 中途失败发生在初次主报告写之前:
    # 主报告文件不存在;partial 由 FAIL_STATE 权威保留
    assert not (out /
                "tau_sensitivity.json"
                ).exists()
    fs = json.loads(
        (out /
         "FAIL_STATE.json"
         ).read_text(
             encoding="utf-8"))
    assert fs[
        "status"] == "failed"
    assert 0 < len(
        fs["roots"]) < 8
    assert fs["pairs"] == {}
    assert (out /
            "FAILED.marker"
            ).exists()
    assert not (out /
                "DONE.marker"
                ).exists()
