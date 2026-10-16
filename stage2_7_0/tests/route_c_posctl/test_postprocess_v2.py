# -*- coding: utf-8 -*-
"""后处理 v2 测试:Fraction 精确漂移(1/2/3 tick)、±镜像、
64×3 冻结原件身份/数值/键完整校验。纯后处理,零求解/零 GL。"""
import os
import sys
from fractions import Fraction

OUT = ("/mnt/f/trading/"
       "unified_flat_calib_official_attempt2_20261016")
SRC = ("/mnt/f/trading/freqai-rl-audit/"
       "stage2_7_0/src")
sys.path.insert(0, SRC)
sys.path.insert(0, OUT)

import postprocess_v2 as pp  # noqa


def _idxs(tick_offsets):
    """各档 argmax 索引:L2 偏移 tick_offsets 个 1/160 刻度。"""
    n0, n1, n2 = 41, 81, 161
    mid0, mid1, mid2 = 20, 40, 80
    d = tick_offsets
    return [mid0, mid1, mid2 - d], [n0, n1, n2]


def test_drift_ticks_pass_pass_reject():
    # L2 一步 = 2/160 = 1/80(统一 160 刻度);阈值=粗距/2=1/40
    ok1, dr1, th = pp.drift_ok_exact(
        *_idxs(1))          # 1 tick = 1/80 < 1/40
    assert ok1 and dr1 == Fraction(1, 80)
    ok2, dr2, _ = pp.drift_ok_exact(
        *_idxs(2))          # 2 tick = 1/40 = 阈值 → 通过
    assert ok2 and dr2 == Fraction(1, 40)
    ok3, dr3, _ = pp.drift_ok_exact(
        *_idxs(3))          # 3 tick = 3/80 > 1/40 → 拒
    assert (not ok3) and dr3 == Fraction(3, 80)
    assert th == Fraction(1, 40)


def test_mirror_symmetry():
    def mirror(idxs, ns):
        return [n - 1 - i
                for i, n in zip(idxs, ns)]

    for d in (1, 2, 3):
        idxs, ns = _idxs(d)
        ok_a, dr_a, _ = pp.drift_ok_exact(
            idxs, ns)
        ok_b, dr_b, _ = pp.drift_ok_exact(
            mirror(idxs, ns), ns)
        assert ok_a == ok_b and dr_a == dr_b
    # ±镜像坐标集相同
    i2, n2 = _idxs(2)[0][2], 161
    c = pp.frac_coord(i2, n2)
    cm = pp.frac_coord(
        160 - i2, 161)
    assert c == -cm


def test_exact_coords_match_linspace():
    i, n = 33, 41
    want = -1.0 + 2.0 * i / (n - 1)
    assert abs(float(
        pp.frac_coord(i, n)) - want) < 1e-15


def test_frozen_artifacts_validate_64x3():
    """冻结原件 64×3 身份/数值/键完整校验(只读)。"""
    import numpy as np
    from rl_posctl.skill_p0 import (
        unified_ref_adapter as ur)
    per = {}
    for tier in ("L0", "L1", "L2"):
        tm, acts, accs, rows = pp.load_tier(
            tier, out=OUT)
        assert len(rows) == 64
        tables, _ = pp.rehydrate(
            tier, tm, acts, accs, out=OUT)
        tables["questions"] = rows
        per[tier] = tables
    ur.validate_tier_outputs(per)   # 任何漂移即抛


def test_analysis_v2_changed_rows_as_measured():
    import json
    with open(os.path.join(
            OUT, "analysis_v2.json"),
            encoding="utf-8") as f:
        d = json.load(f)
    assert d["summary"] == {
        "no_act": 52, "not_established": 4,
        "act": 8}
    changed = {c["qid"]: c for c in
               d["changed_rows"]}
    assert set(changed) == {"G018", "G019"}
    for c in changed.values():
        assert (c["old_status"]
                == "not_established")
        assert c["new_status"] == "act"
        assert c["drift_exact"][
            "drift"] == "1/40"
        assert c["drift_exact"][
            "threshold"] == "1/40"
        assert c["drift_exact"]["pass"] is True
    a2 = d["analysis_v2"]
    for qid in ("G015", "G016", "G055",
                "G056"):
        v = a2[qid]
        assert v["status"] == (
            "not_established")
        assert (v["margin_final"]
                <= v["uncertainty_q_units"])
    acts = [v for v in a2.values()
            if v["status"] == "act"]
    assert len(acts) == 8
    for v in acts:
        assert v["amplitude_status"] == (
            "not_established")   # 次优gap≤unc
        assert v["course_gate"] == "not_frozen"
    assert d["course_gate"] == "not_frozen"
