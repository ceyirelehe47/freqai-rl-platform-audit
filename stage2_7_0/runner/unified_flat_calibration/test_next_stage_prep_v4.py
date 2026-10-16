# -*- coding: utf-8 -*-
"""v4 测试:真 FakeMix/常数 integrator(零 SciPy/CDF/quad 走
诊断入口);每测试独立预算实例;post-save 在写后推进并断言
真实失败位置/partial 非空/无 completed 冲突;小对象级 B 数学
(纯分支为主)。不运行真实 32 case 表/A 冻结 64 题/DP。"""
import json
import math
import pathlib
import sys

import numpy as np
import pytest

HERE = pathlib.Path(
    __file__).resolve().parent
sys.path.insert(0, str(HERE))

import beta_mass_controls as bm  # noqa
import q_set_diagnostic as qs  # noqa


# ---------- B 小对象数学(纯分支为主) ---------------------------
def test_incbeta_eps_exact_branches():
    assert bm.incbeta_eps(
        1.0, 1.0) == bm.EPS
    # a==1:−expm1(b·log1p(−eps))
    b = 3.0
    want = -math.expm1(
        b * math.log1p(-bm.EPS))
    assert bm.incbeta_eps(
        1.0, b) == want
    # b==1:eps^a
    assert bm.incbeta_eps(
        4.0, 1.0) == bm.EPS ** 4


def test_inv_softplus_roundtrip():
    for target in (1.0, 2.0,
                   17.0, 65.0,
                   499.0):
        raw = bm.inv_softplus(
            target)
        got = bm.softplus(raw) + 1
        assert got == pytest.approx(
            target,
            rel=1e-12,
            abs=1e-12)


def test_decode_float32_cast():
    # α=2,β=5:u=1/5→w=−0.6;float32(−.6)≠−.6
    b = bm.BAsymMixture(
        [-8, 8], [-8, -8, -8, 8],
        bm.inv_softplus(2.0),
        bm.inv_softplus(5.0))
    tag, w = b.decode()
    assert tag == "REBAL"
    assert w == float(
        np.float32(-0.6))
    assert w != -0.6


def test_nudge_and_domain():
    b = bm.BAsymMixture(
        [-8, 8], [-8, -8, -8, 8],
        -100, -100)   # α=β=1
    tag, w = b.decode()
    assert (tag, w) == (
        "REBAL", bm.NUDGE)
    # 域与维度拒
    with pytest.raises(
            ValueError):
        bm.BAsymMixture(
            [-8, 8, 0],
            [-8] * 4, 1, 1)
    with pytest.raises(
            ValueError):
        bm.BAsymMixture(
            [-8, 8], [-8] * 3,
            1, 1)
    with pytest.raises(
            ValueError,
            match="outside"):
        bm.BAsymMixture(
            [-8, 8], [-8] * 4,
            bm.inv_softplus(
                600.0), 1)


def test_band_decomp_dedup_allow():
    b = bm.BAsymMixture(
        [-8, 8], [-6, -8, -9, 8],
        -100, -100)   # uniform 纯
    d1 = b.band_decomposition(
        0.2, 0.6,
        allowed_atoms=(1.0, 1.0))
    d2 = b.band_decomposition(
        0.2, 0.6,
        allowed_atoms=(1.0,))
    assert d1["atoms"] == \
        pytest.approx(
            d2["atoms"], abs=0)
    d3 = b.band_decomposition(
        0.2, 0.6, allow_hold=False)
    assert d3["hold"] == 0.0


# ---------- FakeMix/常数 integrator(诊断入口零数值) -----------
class FakeMix:
    """真替身:固定质量/动作;无 SciPy/CDF/quad。"""

    def __init__(self, case):
        self.alpha = 2.0
        self.beta = 5.0
        self.p_hold = 0.1
        self.p_rebal = 0.9
        self.m = [0.1, 0.1, 0.1,
                  0.7]

    def band_decomposition(
            self, lo, hi,
            allow_hold=True,
            allowed_atoms=()):
        hold = (0.1
                if allow_hold
                else 0.0)
        atoms = 0.1 * len(
            set(allowed_atoms))
        cont = 0.25
        return {
            "total": (hold + atoms
                      + 0.9 * 0.7
                      * cont),
            "hold": hold,
            "atoms": atoms,
            "interior": (0.9 * 0.7
                         * cont),
            "atoms_list": sorted(
                set(
                    allowed_atoms)),
            "band_cont_mass":
                cont}

    def decode(self):
        return ("REBAL", -0.55)

    def quad_band(self, lo, hi,
                  nodes, budget):
        budget.add_quad(nodes)
        why, _ = (
            budget.checkpoint())
        if why:
            raise RuntimeError(
                "guard:%s" % why)
        return 0.25   # 常数积分


def test_run_fake_completed(
        tmp_path):
    out = tmp_path / "d1"
    res = bm.run_diagnostics(
        str(out),
        loader=FakeMix,
        integrator=lambda m, lo,
        hi, n, b: m.quad_band(
            lo, hi, n, b))
    assert res["status"] == (
        "completed")
    assert (out /
            "DONE.marker").exists()
    st = res["stats"]
    assert st["digest"] == \
        bm.table_digest()
    r0 = res["results"][0]
    assert set(
        r0["mass_split"]) == {
        "hold", "atoms",
        "interior"}
    assert r0["p0_action"] == [
        "REBAL", -0.55]
    assert r0["within_tol"]
    assert r0["quad_level_diff"] == 0.0
    assert res["budget_final"]["segments"] == 32
    assert res["budget_final"]["nodes"] == 32 * (4097 + 8193)
    assert res["budget_measurement"] == "after_initial_main_save"
    assert len(res["pair_controls"]) == 8
    # Stub equality is a zero raw delta, never a fabricated expression pass.
    assert res["pair_controls"][0]["matched_minus_opposite"] == 0.0


def test_run_refuses_existing(
        tmp_path):
    out = tmp_path / "d2"
    out.mkdir()
    keep = out / "keep.bin"
    keep.write_bytes(b"orig")
    with pytest.raises(
            FileExistsError):
        bm.run_diagnostics(
            str(out),
            loader=FakeMix)
    assert keep.read_bytes() == \
        b"orig"


def test_post_save_overrun_real(
        tmp_path):
    """post-save 在主报告写完后推进:主报告权威
    failed(无 completed 冲突)、PARTIAL 非空、
    FAILED.marker、无 DONE。"""
    out = tmp_path / "d3"
    saved = {"done": False}
    bud = bm.JobBudget(
        clock=(
            lambda: (999.0
                     if saved[
                         "done"]
                     else 0.0),
            lambda: 0.0))

    def probe():
        saved["done"] = True

    with pytest.raises(
            RuntimeError,
            match="post-save"):
        bm.run_diagnostics(
            str(out),
            loader=FakeMix,
            integrator=lambda m,
            lo, hi, n, b:
            m.quad_band(
                lo, hi, n, b),
            budget=bud,
            post_save_probe=probe)
    main = json.loads(
        (out / "beta_diag.json"
         ).read_text(
             encoding="utf-8"))
    assert main[
        "status"] == "failed"
    assert "post_save" in main[
        "fail_reason"]
    partial = json.loads(
        (out / "PARTIAL.json"
         ).read_text(
             encoding="utf-8"))
    assert partial[
        "partial_results"]
    assert (out /
            "FAILED.marker"
            ).exists()
    assert not (out /
                "DONE.marker"
                ).exists()


def test_budget_isolated_per_run(
        tmp_path):
    """每 job 实例隔离:两次运行计数互不影响。"""
    b1 = bm.JobBudget()
    b2 = bm.JobBudget()
    b1.add_quad(4097)
    b1.add_quad(8193)
    assert b1.nodes == 12290
    assert b2.nodes == 0


def test_segment_and_node_caps_without_numeric_work():
    b = bm.JobBudget()
    for _ in range(65):
        b.add_segment()
    assert b.checkpoint()[0] == "segment_cap"
    b2 = bm.JobBudget()
    for _ in range(bm.QUAD_NODE_CAP // 8193 + 1):
        b2.add_quad(8193)
    assert b2.checkpoint()[0] == "node_cap"
    assert b2.segs == 0


def test_generic_post_save_exception_is_authoritative(tmp_path):
    out = tmp_path / "post-save-exception"
    def boom():
        raise RuntimeError("sentinel-write-after-save")
    with pytest.raises(RuntimeError, match="sentinel-write-after-save"):
        bm.run_diagnostics(
            str(out), loader=FakeMix,
            integrator=lambda m, lo, hi, n, b: m.quad_band(lo, hi, n, b),
            post_save_probe=boom)
    main = json.loads((out / "beta_diag.json").read_text())
    assert main["status"] == "failed"
    assert "sentinel-write-after-save" in main["fail_reason"]
    assert (out / "FAILED.marker").exists()
    assert not (out / "DONE.marker").exists()


def test_post_save_measurement_error_preserves_failure(tmp_path):
    out = tmp_path / "post-save-measurement-error"
    state = {"break": False}
    class BrokenBudget(bm.JobBudget):
        def checkpoint(self):
            if state["break"]:
                raise RuntimeError("sentinel-budget-read")
            return super().checkpoint()
    def probe():
        state["break"] = True
    with pytest.raises(RuntimeError, match="sentinel-budget-read"):
        bm.run_diagnostics(
            str(out), loader=FakeMix,
            integrator=lambda m, lo, hi, n, b: m.quad_band(lo, hi, n, b),
            budget=BrokenBudget(), post_save_probe=probe)
    main = json.loads((out / "beta_diag.json").read_text())
    assert main["status"] == "failed"
    assert "sentinel-budget-read" in main["fail_reason"]
    assert "measurement_error" in main["budget_final"]
    assert (out / "PARTIAL.json").exists()
    assert (out / "FAILED.marker").exists()
    assert not (out / "DONE.marker").exists()


def test_stable_upper_tail_path_is_a_stub(monkeypatch):
    class StubBeta:
        @staticmethod
        def cdf(x, a, b):
            return 1.0  # lower-tail values have rounded together
        @staticmethod
        def sf(x, a, b):
            return {0.6: 0.2, 0.7: 0.1}[x]
    monkeypatch.setattr(bm, "_require_scipy", lambda: StubBeta)
    assert bm.beta_interval_mass(2.0, 5.0, 0.6, 0.7) == pytest.approx(0.1)


# ---------- A:窗口开闭/tail 全正/manifest 负控 -----------------
def test_pair_taus_window_closure():
    r = qs.pair_taus(
        {0: 0.1, 1: 0.9},
        {0: 0.9, 1: 0.2})
    assert r["window"] == [
        0.2, 0.9]
    assert r[
        "lower_closed"] is True
    assert r[
        "upper_closed"] is False


def test_tail_rule_all_nonzero_positive():
    """Call the production helper; a nonzero action with zero regret fails."""
    good = {t: [0.1, 0.0, 0.2] for t in ("L0", "L1", "L2")}
    zeros = {t: 1 for t in good}
    assert qs.tail_nonzero_summary(good, zeros)["all_nonzero_positive"]
    bad = {t: list(v) for t, v in good.items()}
    bad["L1"][2] = 0.0
    assert not qs.tail_nonzero_summary(bad, zeros)["all_nonzero_positive"]
    bad["L1"][2] = -0.1
    assert not qs.tail_nonzero_summary(bad, zeros)["all_nonzero_positive"]


def test_a_run_refuses_existing(
        tmp_path):
    d = tmp_path / "a1"
    d.mkdir()
    sent = d / "s.txt"
    sent.write_text("x")
    with pytest.raises(
            FileExistsError):
        qs.run("/nonexistent",
               str(d))
    assert sent.read_text(
    ) == "x"


def test_a_manifest_mismatch(
        tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir()
    for n in qs.CONSUMED:
        (ev / n).write_text("x")
    out = tmp_path / "ao"
    with pytest.raises(
            ValueError,
            match="manifest"):
        qs.run(str(ev),
               str(out))
    fs = json.loads(
        (out /
         "FAIL_STATE.json"
         ).read_text(
             encoding="utf-8"))
    assert fs[
        "status"] == "failed"
    assert "regrets" in fs


def test_status_and_gate():
    assert bm.STATUS == (
        "PREPARED_NOT_RUN")
    assert qs.STATUS == (
        "PREPARED_NOT_RUN")
    assert bm.COURSE_GATE == (
        "not_frozen")
    st = bm.validate_case_table()
    assert st["cases"] == 32
    assert st[
        "planned_nodes"] == \
        32 * 12290
