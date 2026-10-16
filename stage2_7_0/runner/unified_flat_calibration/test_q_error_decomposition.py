# -*- coding: utf-8 -*-
"""q_error_decomposition v2 手写单测(fake loader 不包真实表):
16 行/proxy 重现/首次写后超限/一般异常/收尾再故障/对齐拒绝。"""
import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(
    __file__).resolve().parent
sys.path.insert(0, str(HERE))

import q_error_decomposition as qd  # noqa


def test_align_rejects_bad():
    ok = {
        "L0": [-1 + 2 * i / 40
               for i in
               range(41)],
        "L1": [-1 + 2 * i / 80
               for i in
               range(81)],
        "L2": [-1 + 2 * i / 160
               for i in
               range(161)]}
    qd.align_common(ok)
    import copy
    bad_len = copy.deepcopy(ok)
    bad_len["L1"] = bad_len[
        "L1"][:80]
    with pytest.raises(
            ValueError):
        qd.align_common(bad_len)
    bad_c = copy.deepcopy(ok)
    bad_c["L2"][80] = 0.5
    with pytest.raises(
            ValueError):
        qd.align_common(bad_c)


def test_original_proxy_formula():
    root_qs = {
        "L0": {
            "all_Q": [1.0, 0.9],
            "hold": 0.5,
            "common_Q": [
                1.0, 0.95]},
        "L1": {
            "all_Q": [1.05, 0.9],
            "hold": 0.5,
            "common_Q": [
                1.05, 0.93]},
        "L2": {
            "all_Q": [1.02, 0.9],
            "hold": 0.5,
            "common_Q": [
                1.02, 0.90]}}
    px = qd.original_proxy(
        root_qs)
    # margins: L0=.5,L1=.55,L2=.52→cross=.05
    assert px["margins"] == {
        "L0": 0.5, "L1": 0.55,
        "L2": 0.52}
    assert px["cross"] == \
        pytest.approx(
            0.05, abs=1e-15)
    # val_dev=max|L0−L2|,|L1−L2|=.03,.05
    assert px["val_dev"] == \
        pytest.approx(
            0.05, abs=1e-15)
    assert px["proxy"] == \
        pytest.approx(
            0.05, abs=1e-15)


def _fake_tier_json(shifts):
    """手写 8 根迷你 tier(真 41/81/161 网格,常数+已知漂移)。"""
    import math
    for t, n in qd.TIER_LEN.items():
        acts = [-1 + 2 * i / (n - 1) for i in range(n)]
        qs = {}
        for k, qid in enumerate(qd.ROOTS):
            base_q = 0.5 + 0.1 * (k % 3)
            hold = 0.4 + 0.05 * (k % 2)
            all_q = [base_q + 0.01
                     * math.sin(a + shifts[t] * (k + 1))
                     for a in acts]
            cm = [all_q[qd.TIER_MAP[t](i)] for i in range(41)]
            qs[qid] = {"hold": hold, "all_Q": all_q, "common_Q": cm}
        yield t, acts, qs


def _mk_evidence(tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir()
    shifts = {"L0": 0.03, "L1": 0.015, "L2": 0.0}
    tiers = {}
    for t, acts, qs in _fake_tier_json(shifts):
        tiers[t] = (acts, qs)
        d = {"tier_meta": {"actions": acts},
             "questions": [
                 {"id": qid,
                  "q_rebals": {"%.17g" % a: v
                               for a, v in zip(acts, qs[qid]["all_Q"])},
                  "q_hold": qs[qid]["hold"]}
                 for qid in qd.ROOTS]}
        (ev / ("tier_%s.json" % t)).write_text(
            json.dumps(d), encoding="utf-8")
    # analysis_v2(手写 proxy 原值=重现值)
    prox = {}
    for qid in qd.ROOTS:
        rq = {t: {
            "all_Q":
                tiers[t][1][
                    qid][
                    "all_Q"],
            "hold":
                tiers[t][1][
                    qid][
                    "hold"],
            "common_Q":
                tiers[t][1][
                    qid][
                    "common_Q"]}
            for t in tiers}
        prox[qid] = qd.\
            original_proxy(
                rq)["proxy"]
    v2 = {"analysis_v2": {
        qid: {
            "uncertainty_q_units":
                prox[qid]}
        for qid in qd.ROOTS}}
    (ev / "analysis_v2"
     ).with_suffix(
        ".json").write_text(
        json.dumps(v2),
        encoding="utf-8")
    return ev


def test_production_run_16rows_proxy(
        tmp_path, monkeypatch):
    ev = _mk_evidence(
        tmp_path)
    monkeypatch.setattr(
        qd, "verify_inputs",
        lambda d: {
            n: "f" * 64
            for n in qd.\
            EXPECTED_SHAS})
    out = tmp_path / "o"
    rep = qd.run(str(ev),
                 str(out))
    assert (out /
            "DONE.marker"
            ).exists()
    assert rep[
        "n_rows"] == 16
    assert len(rep[
        "proxy"]) == 8
    for qid, px in rep[
            "proxy"].items():
        assert px[
            "matches_original"] \
            is True
    for row in rep["rows"]:
        assert row["n_points"] == 41
        assert row["identity_closure"] < 1e-12
        assert row["tier_max_rebal_used"]
        # 逐点 signed delta/base/shape + 坐标 + 索引入报告
        pts = row["points"]
        assert len(pts) == 41
        assert set(pts[0]) == {
            "delta", "base", "shape"}
        assert row["common_coords"][
            0] == pytest.approx(
            -1.0, abs=1e-15)
        assert row["common_coords"][
            40] == pytest.approx(
            1.0, abs=1e-15)
        step = {"L0": 1,
                "L1": 2}[row["tier"]]
        assert row[
            "tier_common_indices"] == [
            step * i
            for i in range(41)]
        assert row[
            "L2_common_indices"] == [
            4 * i
            for i in range(41)]
        # 逐点恒等复核(独立于生产代码路径)
        for p in pts:
            assert p["delta"] == \
                pytest.approx(
                    p["base"]
                    + p["shape"],
                    abs=1e-15)


def test_post_save_overrun(
        tmp_path, monkeypatch):
    ev = _mk_evidence(
        tmp_path)
    monkeypatch.setattr(
        qd, "verify_inputs",
        lambda d: {
            n: "f" * 64
            for n in qd.\
            EXPECTED_SHAS})
    real = qd.JobBudget.\
        checkpoint
    calls = {"n": 0}

    def late(self):
        calls["n"] += 1
        if calls["n"] >= 17:
            # 计算后、写后首查起超时
            import time as _t
            self.nw = (
                lambda: (
                    _t.perf_counter()
                    + 999))
        return real(self)

    monkeypatch.setattr(
        qd.JobBudget,
        "checkpoint", late)
    out = tmp_path / "o2"
    with pytest.raises(
            RuntimeError,
            match="post-save"):
        qd.run(str(ev),
               str(out))
    main = json.loads(
        (out /
         "q_error_decomp.json"
         ).read_text(
             encoding="utf-8"))
    assert main[
        "status"] == "failed"
    assert (out /
            "FAILED.marker"
            ).exists()
    assert not (out /
                "DONE.marker"
                ).exists()


def test_generic_fault_preserves(
        tmp_path, monkeypatch):
    ev = _mk_evidence(
        tmp_path)
    monkeypatch.setattr(
        qd, "verify_inputs",
        lambda d: {
            n: "f" * 64
            for n in qd.\
            EXPECTED_SHAS})
    monkeypatch.setattr(
        qd, "load_tier",
        lambda d, t: (
            _boom()))
    out = tmp_path / "o3"
    with pytest.raises(
            RuntimeError,
            match="boom"):
        qd.run(str(ev),
               str(out))
    fs = json.loads(
        (out /
         "FAIL_STATE.json"
         ).read_text(
             encoding="utf-8"))
    assert fs[
        "status"] == "failed"
    assert (out /
            "FAILED.marker"
            ).exists()
    assert not (out /
                "DONE.marker"
                ).exists()


def _boom():
    raise RuntimeError(
        "load boom")


def test_finalize_refail_measurement_error(
        tmp_path, monkeypatch):
    """收尾预算读取再错:measurement_error=预算错,
    抛出原 mid-late 异常;无 DONE。"""
    ev = _mk_evidence(tmp_path)
    monkeypatch.setattr(
        qd, "verify_inputs",
        lambda d: {n: "f" * 64
                   for n in qd.EXPECTED_SHAS})
    real = qd.JobBudget.checkpoint
    state = {"phase": 0}
    calls = {"n": 0}

    class Dying(qd.JobBudget):
        def checkpoint(self):
            if state["phase"] == 1:
                raise RuntimeError(
                    "budget-read-dead")
            calls["n"] += 1
            if calls["n"] >= 17:
                state["phase"] = 1
                raise RuntimeError(
                    "mid-late boom")
            return real(self)

    monkeypatch.setattr(
        qd, "JobBudget", Dying)
    out = tmp_path / "o4"
    with pytest.raises(
            RuntimeError,
            match="mid-late"):
        qd.run(str(ev), str(out))
    fs = json.loads(
        (out / "FAIL_STATE.json"
         ).read_text(
             encoding="utf-8"))
    assert "budget-read-dead" in \
        fs.get("measurement_error",
               "")
    assert "mid-late" in \
        fs["reason"]
    assert not (out /
                "DONE.marker"
                ).exists()


def test_gates():
    assert qd.STATUS == (
        "PREPARED_NOT_RUN")
    assert qd.COURSE_GATE == (
        "not_frozen")
    assert len(qd.ROOTS) == 8
    assert qd.EXPECTED_SHAS[
        "analysis_v2.json"
    ].startswith(
        "edfdc25e")


def test_guard1_first_reason_preserved(
        tmp_path, monkeypatch):
    """guard1 命中即 raise;收尾中 checkpoint
    再抛错不掩盖首个 wall 超限原因。"""
    ev = _mk_evidence(tmp_path)
    monkeypatch.setattr(
        qd, "verify_inputs",
        lambda d: {n: "f" * 64
                   for n in
                   qd.EXPECTED_SHAS})
    real = qd.JobBudget.checkpoint
    state = {"phase": 0}
    calls = {"n": 0}

    class G1ThenDead(
            qd.JobBudget):
        def checkpoint(self):
            if state["phase"] == 1:
                raise RuntimeError(
                    "second-"
                    "measurement-"
                    "dead")
            calls["n"] += 1
            why, m = real(self)
            if calls["n"] >= 17 \
                    and why is None:
                # guard1 时刻注入超限
                state["phase"] = 1
                return ("wall_clock",
                        m)
            if state["phase"] == 1:
                raise RuntimeError(
                    "second-"
                    "measurement-"
                    "dead")
            return why, m

    monkeypatch.setattr(
        qd, "JobBudget",
        G1ThenDead)
    out = tmp_path / "o5"
    with pytest.raises(
            RuntimeError,
            match="post-save-"
                  "guard1"):
        qd.run(str(ev),
               str(out))
    main = json.loads(
        (out /
         "q_error_decomp.json"
         ).read_text(
             encoding="utf-8"))
    assert main[
        "status"] == "failed"
    assert ("wall_clock"
            in main[
                "fail_reason"])
    fs = json.loads(
        (out /
         "FAIL_STATE.json"
         ).read_text(
             encoding="utf-8"))
    assert ("wall_clock"
            in fs["reason"])
    assert ("second-"
            "measurement-"
            "dead") in fs.get(
        "measurement_error",
        "")
    assert not (out /
                "DONE.marker"
                ).exists()
