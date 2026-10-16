# -*- coding: utf-8 -*-
"""后处理 v2 测试(可移植版)。

- 纯 Fraction 测试(3 项)**必须**跑;
- 冻结产物测试(2 项)按显式配置的证据目录跑;缺原件仅 skip
  并说明(无证据环境=3 pass/2 skip;有原件=5 pass);
- 从仓库实际路径加载拟提交 postprocess(不 import 证据目录
  外部副本);不运行正式 runner。
"""
import json
import os
import pathlib
import sys
from fractions import Fraction

import pytest

REPO_STAGE = pathlib.Path(
    __file__).resolve().parents[2]
sys.path.insert(0, str(
    REPO_STAGE / "runner"
    / "unified_flat_calibration"))
sys.path.insert(0, str(REPO_STAGE / "src"))

import postprocess_v2 as pp  # noqa

EVIDENCE = os.environ.get(
    "UFC_EVIDENCE_DIR")        # 显式配置,不隐式回退


def _artifacts_present():
    if not EVIDENCE:
        return False
    return all(
        (pathlib.Path(EVIDENCE)
         / name).exists()
        for name in
        ("tier_L0.json", "tier_L1.json",
         "tier_L2.json", "V_L0.npy",
         "V_L1.npy", "V_L2.npy",
         "analysis.json",
         "analysis_v2.json"))


pytestmark_no_ev = pytest.mark.skipif(
    not _artifacts_present(),
    reason=(
        "frozen artifacts not configured: "
        "set UFC_EVIDENCE_DIR to the official "
        "evidence directory (originals kept "
        "locally; skipping only these 2 "
        "frozen-data tests)"))


# ---------- 纯 Fraction(必须跑) --------------------------------
def test_drift_ticks_pass_pass_reject():
    """L2 一步=2/160=1/80;阈值=粗距/2=1/40;1/2/3 tick
    =过/过/拒。"""
    def idxs(d):
        return ([20, 40, 80 - d],
                [41, 81, 161])

    ok1, dr1, th = pp.drift_ok_exact(*idxs(1))
    assert ok1 and dr1 == Fraction(1, 80)
    ok2, dr2, _ = pp.drift_ok_exact(*idxs(2))
    assert ok2 and dr2 == Fraction(1, 40)
    ok3, dr3, _ = pp.drift_ok_exact(*idxs(3))
    assert (not ok3) and dr3 == Fraction(3, 80)
    assert th == Fraction(1, 40)


def test_mirror_and_coords():
    def mirror(idxs, ns):
        return [n - 1 - i
                for i, n in zip(idxs, ns)]

    ns = [41, 81, 161]
    for d in (1, 2, 3):
        idxs = [20, 40, 80 - d]
        ok_a, dr_a, _ = pp.drift_ok_exact(
            idxs, ns)
        ok_b, dr_b, _ = pp.drift_ok_exact(
            mirror(idxs, ns), ns)
        assert ok_a == ok_b and dr_a == dr_b
    c = pp.frac_coord(33, 41)
    assert c == -pp.frac_coord(41 - 1 - 33, 41)
    assert abs(float(c) - (-1 + 66 / 40)) \
        < 1e-15


def test_cli_entry_no_import_argv(monkeypatch):
    """导入期不消费 argv;OUT 默认 None;无参调用拒。"""
    import importlib
    monkeypatch.setattr(
        sys, "argv",
        ["postprocess_v2.py"])
    m = importlib.reload(pp)
    assert m.OUT is None
    with pytest.raises(SystemExit):
        m.main()
    # 显式 out= 库用法可设路径
    assert m.load_tier is not None


# ---------- 冻结产物(显式证据目录;缺则 skip) -------------------
def test_frozen_artifacts_validate_64x3():
    if not _artifacts_present():
        pytest.skip(
            "UFC_EVIDENCE_DIR not set/missing "
            "originals — frozen validation "
            "skipped (documented limitation)")
    import numpy as np
    per = {}
    for tier in ("L0", "L1", "L2"):
        tm, acts, accs, rows = pp.load_tier(
            tier, out=EVIDENCE)
        assert len(rows) == 64
        tables, _ = pp.rehydrate(
            tier, tm, acts, accs, out=EVIDENCE)
        tables["questions"] = rows
        per[tier] = tables
    from rl_posctl.skill_p0 import (
        unified_ref_adapter as ur)
    ur.validate_tier_outputs(per)


def test_analysis_v2_changed_rows_as_measured():
    if not _artifacts_present():
        pytest.skip(
            "UFC_EVIDENCE_DIR not set/missing "
            "originals — analysis check skipped")
    with open(os.path.join(
            EVIDENCE, "analysis_v2.json"),
            encoding="utf-8") as f:
        d = json.load(f)
    assert d["summary"] == {
        "no_act": 52, "not_established": 4,
        "act": 8}
    changed = {c["qid"]: c for c in
               d["changed_rows"]}
    assert set(changed) == {"G018", "G019"}
    for c in changed.values():
        assert c["old_status"] == (
            "not_established")
        assert c["new_status"] == "act"
        assert c["drift_exact"]["drift"] == (
            "1/40")
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
            "not_established")
        assert v["course_gate"] == "not_frozen"
    assert d["course_gate"] == "not_frozen"
