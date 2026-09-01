"""R5 测试:candidate design(grid 锁定/Tier B 机械触发/maximin 选择/
全-ladder n=10 bootstrap 正确性)(§34)。"""

from __future__ import annotations

import json

import numpy as np
import pytest

import rl_curriculum.curriculum261_r5_design as r5d
from rl_curriculum.curriculum261_r5_design import (
    _score_candidate,
    _select_from_tier,
    lock_design_plan,
)
from rl_curriculum.curriculum261_r5_pairs import (
    simulate_formal_gate_pass_r5,
)


def _plan_kwargs():
    return dict(
        baseline_commit="95bb927f3ba46fa18b98602ea05c37ed67df198b",
        vendor_pin="52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
        v2_contract_digest="r4pc-test",
        prior_r2_plan_digest="qp-test",
        prior_diag262r2_plan_digest="dp-test",
    )


def test_design_plan_lock_once_and_drift(monkeypatch, tmp_path):
    plan = r5d.design_plan_payload(**_plan_kwargs())
    path, digest = lock_design_plan(tmp_path, plan)
    assert path.is_file() and digest.startswith("r5dp-")

    # 重复锁定:拒绝(plan 不可重写)
    with pytest.raises(RuntimeError):
        lock_design_plan(tmp_path, plan)

    loaded, d2 = r5d.load_locked_design_plan(tmp_path)
    assert d2 == digest

    # digest 漂移:拒绝
    (tmp_path / "r5_design_plan_digest.txt").write_text(
        "r5dp-drift", encoding="utf-8")
    with pytest.raises(RuntimeError):
        r5d.load_locked_design_plan(tmp_path)


def test_design_plan_grid_and_code_drift(monkeypatch, tmp_path):
    plan = r5d.design_plan_payload(**_plan_kwargs())
    lock_design_plan(tmp_path, plan)

    orig_grid = r5d.r5_candidate_grid
    # 候选网格漂移(锁定后修改代码常量):拒绝
    drifted = {"tier_a_c2_d3_only": {"c2_new": dict(
        next(iter(plan["tier_a"]["candidates"].values())))},
        "tier_b_c2_joint": plan["tier_b"]["candidates"]}
    monkeypatch.setattr(r5d, "r5_candidate_grid",
                        lambda: drifted)
    with pytest.raises(RuntimeError):
        r5d.load_locked_design_plan(tmp_path)

    # code identity 漂移:拒绝
    monkeypatch.setattr(r5d, "r5_candidate_grid", orig_grid)
    monkeypatch.setattr(r5d, "_code_identity_design",
                        lambda: {"x.py": "deadbeef"})
    with pytest.raises(RuntimeError):
        r5d.load_locked_design_plan(tmp_path)


def test_design_plan_binds_preregistration(tmp_path):
    plan = r5d.design_plan_payload(**_plan_kwargs())
    assert plan["tier_a"]["namespaces"] == [
        "design_r5_tier_a_main", "design_r5_tier_a_validation"]
    assert plan["tier_b"]["namespaces"] == [
        "design_r5_tier_b_main", "design_r5_tier_b_validation"]
    assert len(plan["tier_a"]["candidates"]) == 6
    assert len(plan["tier_b"]["candidates"]) == 3
    assert plan["power_targets"]["gap_d2_d3_positive_and_ge"] == 3.0
    assert plan["power_targets"]["d3_vs_flat_ge"] == 2.5
    assert plan["power_targets"]["formal_gate_pass_probability_min"] \
        == 0.90
    assert plan["density_thresholds"][
        "median_reference_trades_per_episode_min"] == 8.0
    assert plan["density_thresholds"][
        "reference_long_label_rate_min"] == 0.015
    assert plan["statistics"]["kappa"] == 1.5


# --------------------------------------------- 全-ladder n=10 bootstrap
def _always_pass_arrays():
    """条件恒过的合成 ladder(间隔远大于 SE;margin 恒正)。"""
    rng = np.random.default_rng(7)
    base = {"D0": 0.040, "D1": 0.030, "D2": 0.020, "D3": 0.008}
    lad = {r: base[r] + rng.normal(0, 0.0005, 40) for r in base}
    margins = {r: {b: lad[r] + 0.002 + rng.normal(0, 0.0005, 40)
                   for b in ("always_flat", "always_long",
                             "c2_local_only")}
               for r in base}
    return lad, margins


def test_formal_gate_simulation_always_pass():
    lad, margins = _always_pass_arrays()
    sim = simulate_formal_gate_pass_r5(
        lad, margins, ("always_flat", "always_long", "c2_local_only"),
        n_sim=500, seed=11)
    assert sim["gate_pass_probability"] == 1.0
    for k, v in sim["per_condition_pass_probability"].items():
        assert v == 1.0


def test_formal_gate_simulation_ordering_violation():
    lad, margins = _always_pass_arrays()
    lad["D3"] = lad["D2"] + 0.002  # D2 < D3 倒挂
    sim = simulate_formal_gate_pass_r5(
        lad, margins, ("always_flat", "always_long", "c2_local_only"),
        n_sim=500, seed=11)
    assert sim["gate_pass_probability"] == 0.0
    assert sim["per_condition_pass_probability"]["ordering"] == 0.0


def test_formal_gate_simulation_borderline_deterministic():
    lad, margins = _always_pass_arrays()
    lad["D3"] = lad["D3"] * 0.35
    lad["D2"] = lad["D2"] * 0.9
    args = (lad, margins, ("always_flat", "always_long",
                           "c2_local_only"))
    p1 = simulate_formal_gate_pass_r5(
        *args, n_sim=800, seed=20260912)["gate_pass_probability"]
    p2 = simulate_formal_gate_pass_r5(
        *args, n_sim=800, seed=20260912)["gate_pass_probability"]
    assert p1 == p2  # 预注册 RNG:同 seed 同结果
    assert 0.0 <= p1 <= 1.0


def test_formal_gate_gap_condition_binding():
    """gap 条件含 D0-D1/D1-D2(全 ladder;不只 D2-D3)。"""
    lad, margins = _always_pass_arrays()
    lad["D1"] = lad["D0"] + 0.002  # D0-D1 倒挂(gap 恒负)
    sim = simulate_formal_gate_pass_r5(
        lad, margins, ("always_flat", "always_long", "c2_local_only"),
        n_sim=500, seed=11)
    assert sim["gate_pass_probability"] == 0.0
    assert sim["per_condition_pass_probability"]["gap_D0-D1"] == 0.0
    assert sim["per_condition_pass_probability"]["ordering"] == 0.0


# ------------------------------------------------------------- 选择规则
def _cand(name, score, distance, qualified=True):
    return name, {
        "tier": "A",
        "candidate_params": {},
        "qualified_both_corpora": qualified,
        "maximin_score": score,
        "param_distance_from_historical": distance,
    }


def test_maximin_selection_rules():
    tier = {"candidates": dict([
        _cand("a", 3.0, 0.5),
        _cand("b", 4.2, 0.9),
        _cand("c", 4.2, 0.2),   # 与 b 平局但更保守
        _cand("d", 5.0, 2.0, qualified=False),  # 高分但不合格
    ])}
    name, sel = _select_from_tier(tier)
    assert name == "c"  # 合格者中 score 最高;平局取 distance 最小
    assert name != "d"  # 不合格者不得入选


def test_maximin_score_is_min_over_metrics_and_corpora():
    r1 = {"maximin_metrics": {"a": 5.0, "b": 2.0}}
    r2 = {"maximin_metrics": {"a": 1.5, "b": 3.0}}
    assert _score_candidate([r1, r2]) == 1.5
    assert _score_candidate([r1]) == 2.0


def test_select_requires_qualified():
    tier = {"candidates": dict([_cand("a", 9.0, 0.1, qualified=False)])}
    with pytest.raises(RuntimeError):
        _select_from_tier(tier)
