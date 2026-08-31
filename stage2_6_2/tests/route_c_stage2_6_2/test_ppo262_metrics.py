"""指标语义测试(§27 Metrics)。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.ppo262_metrics import (
    PPO262_CORE_RUNG_WEIGHTS, PPO262_REQUIRED_BASELINES,
    aggregate_capture, behavior_metrics, capture_table,
    family_core_capture, pair_cluster_bootstrap_ci, pair_level_values,
    retention_ratio,
)


def _row(fam, rung, pair, variant, net):
    return {"family": fam, "rung": rung, "pair_index": pair,
            "variant": variant, "net_return": net, "n_trades": 0,
            "actions": None}


def test_capture_formula_no_clip():
    """capture = (P-B)/(R-B),不 clip;<0 与 >1 都保留。"""
    ppo = [_row("c1_opportunity", "D1", 0, "A", 0.010),
           _row("c1_opportunity", "D1", 0, "B", 0.012)]
    ref = [_row("c1_opportunity", "D1", 0, "A", 0.020),
           _row("c1_opportunity", "D1", 0, "B", 0.020)]
    base = {"always_flat": [_row("c1_opportunity", "D1", 0, "A", 0.0),
                            _row("c1_opportunity", "D1", 0, "B", 0.0)],
            "always_long": [_row("c1_opportunity", "D1", 0, "A", -0.002),
                            _row("c1_opportunity", "D1", 0, "B", -0.002)]}
    t = capture_table(ppo, ref, base)
    cell = t["c1_opportunity/D1"]
    # P=0.011, B=0(best baseline=always_flat), R=0.020
    assert cell["best_baseline"] == "always_flat"
    assert cell["baseline_mean"] == pytest.approx(0.0)
    assert cell["denominator"] == pytest.approx(0.020)
    assert cell["capture"] == pytest.approx(0.011 / 0.020)
    # capture > 1 保留
    ppo2 = [_row("c1_opportunity", "D1", 0, "A", 0.05),
            _row("c1_opportunity", "D1", 0, "B", 0.05)]
    t2 = capture_table(ppo2, ref, base)
    assert t2["c1_opportunity/D1"]["capture"] == pytest.approx(2.5)
    # capture < 0 保留
    ppo3 = [_row("c1_opportunity", "D1", 0, "A", -0.05),
            _row("c1_opportunity", "D1", 0, "B", -0.05)]
    t3 = capture_table(ppo3, ref, base)
    assert t3["c1_opportunity/D1"]["capture"] == pytest.approx(-2.5)


def test_best_required_baseline_selection():
    """B(f,r) = required baselines 中 mean 最高者(family 特异合同)。"""
    ppo = [_row("c3_cost", "D2", 0, v, 0.01) for v in "AB"]
    ref = [_row("c3_cost", "D2", 0, v, 0.03) for v in "AB"]
    base = {
        "always_flat": [_row("c3_cost", "D2", 0, v, 0.0) for v in "AB"],
        "always_long": [_row("c3_cost", "D2", 0, v, -0.002) for v in "AB"],
        "c3_cost_ignorant": [_row("c3_cost", "D2", 0, v, -0.004)
                             for v in "AB"],
    }
    t = capture_table(ppo, ref, base)
    assert t["c3_cost/D2"]["best_baseline"] == "always_flat"
    # 若 cost_ignorant 更高则选它
    base["c3_cost_ignorant"] = [_row("c3_cost", "D2", 0, v, 0.004)
                                for v in "AB"]
    t2 = capture_table(ppo, ref, base)
    assert t2["c3_cost/D2"]["best_baseline"] == "c3_cost_ignorant"
    assert t2["c3_cost/D2"]["baseline_mean"] == pytest.approx(0.004)
    assert t2["c3_cost/D2"]["capture"] == pytest.approx(
        (0.01 - 0.004) / (0.03 - 0.004))


def test_family_core_capture_weights():
    assert PPO262_CORE_RUNG_WEIGHTS == {"D0": 0.20, "D1": 0.30, "D2": 0.50}
    table = {}
    for fam in PPO262_REQUIRED_BASELINES:
        for rung in ("D0", "D1", "D2", "D3"):
            table[f"{fam}/{rung}"] = {
                "capture": 0.5 if rung != "D3" else 9.9}
    # D3 不进核心:三族 core 全部 = 0.5
    for fam in PPO262_REQUIRED_BASELINES:
        assert family_core_capture(table, fam) == pytest.approx(0.5)
    assert aggregate_capture(table) == pytest.approx(0.5)
    # D0/D1/D2 加权正确
    table2 = dict(table)
    table2["c1_opportunity/D0"] = {"capture": 0.0}
    table2["c1_opportunity/D1"] = {"capture": 0.0}
    table2["c1_opportunity/D2"] = {"capture": 1.0}
    assert family_core_capture(table2, "c1_opportunity") == \
        pytest.approx(0.50)


def test_pair_is_cluster_not_ab_episode():
    """A/B 不作为独立样本:pair_level_values 聚合 A/B。"""
    rows = ([_row("f", "D1", 0, "A", 0.10),
             _row("f", "D1", 0, "B", 0.20)]
            + [_row("f", "D1", 1, "A", -0.10),
               _row("f", "D1", 1, "B", 0.10)])
    pv = pair_level_values(rows)
    assert pv[("f", "D1", 0)] == pytest.approx(0.15)
    assert pv[("f", "D1", 1)] == pytest.approx(0.0)
    # bootstrap 以 pair 为单位(结构检验:n_pairs = 2)
    ci = pair_cluster_bootstrap_ci(rows, n_boot=50)
    assert ci["n_pairs"] == 2
    assert ci["point"] == pytest.approx(0.075)
    # 若把 A/B 当独立样本,均值同为 0.075 但 SE 被低估;
    # 验证 bootstrap 只重采样 pair 值(不展开端点)
    vals = sorted(pv.values())
    assert vals[0] == pytest.approx(0.0)
    assert vals[1] == pytest.approx(0.15)


def test_pair_cluster_bootstrap_ci_bounds():
    rng = np.random.default_rng(5)
    rows = []
    for p in range(30):
        base = 0.01 * rng.standard_normal()
        rows.append(_row("f", "D1", p, "A", base + 0.05))
        rows.append(_row("f", "D1", p, "B", base + 0.05))
    ci = pair_cluster_bootstrap_ci(rows, n_boot=500)
    assert ci["ci90_low"] < ci["point"] < ci["ci90_high"]
    assert ci["point"] == pytest.approx(0.05, abs=0.01)


def test_c1_behavior_alignment(small_bank_factory):
    """C1 行为指标:人工 actions 的 selectivity gap 计算正确。"""
    bank = [e for e in small_bank_factory(1)
            if e.key.family == "c1_opportunity"]
    loaded = bank[0]
    h = loaded.episode.hidden
    seg = h["seg_state"].to_numpy()
    acts = np.zeros(len(seg), dtype=int)
    acts[seg == 2] = 1          # 只在 positive opportunity 做多
    rows = [{"family": "c1_opportunity", "rung": "D1",
             "pair_index": loaded.key.pair_index,
             "variant": loaded.key.variant, "net_return": 0.0,
             "n_trades": 0, "actions": list(acts)}]
    beh = behavior_metrics(rows, [loaded])
    c1 = beh["c1_opportunity"]
    assert c1["long_rate_on_positive"] == pytest.approx(1.0)
    assert c1["long_rate_on_neutral"] == 0.0
    assert c1["long_rate_on_negative"] == 0.0
    assert c1["selectivity_gap"] == pytest.approx(1.0)
    assert c1["n_positive"] == int((seg == 2).sum())


def test_c2_behavior_alignment(small_bank_factory):
    bank = [e for e in small_bank_factory(1)
            if e.key.family == "c2_context"]
    loaded = bank[0]
    h = loaded.episode.hidden
    n = len(h)
    cue = h["cue_dir"].to_numpy()
    gate_dir = h["active_gate_is_dir"].to_numpy()
    ctx = np.where(gate_dir == 1, h["wick_dir_state"].to_numpy(),
                   h["wick_width_state"].to_numpy())
    aligned = (cue != 0) & (cue * ctx > 0)
    anti = (cue != 0) & (cue * ctx < 0)
    acts = np.zeros(n, dtype=int)
    acts[aligned] = 1
    rows = [{"family": "c2_context", "rung": "D1",
             "pair_index": loaded.key.pair_index,
             "variant": loaded.key.variant, "net_return": 0.0,
             "n_trades": 0, "actions": list(acts)}]
    beh = behavior_metrics(rows, [loaded])
    c2 = beh["c2_context"]
    assert c2["long_rate_aligned"] == pytest.approx(1.0)
    assert c2["long_rate_anti_aligned"] == 0.0
    assert c2["gating_gap"] == pytest.approx(1.0)
    assert c2["n_aligned"] == int(aligned.sum())
    assert c2["n_anti_aligned"] == int(anti.sum())


def test_c3_behavior_alignment(small_bank_factory):
    bank = [e for e in small_bank_factory(1)
            if e.key.family == "c3_cost"]
    loaded = bank[0]
    h = loaded.episode.hidden
    strength = h["sig_strength"].to_numpy()
    above = h["above_cost"].to_numpy()
    n = len(h)
    acts = np.zeros(n, dtype=int)
    acts[(strength != 0) & (above == 1)] = 1
    rows = [{"family": "c3_cost", "rung": "D1",
             "pair_index": loaded.key.pair_index,
             "variant": loaded.key.variant, "net_return": 0.01,
             "n_trades": 3, "total_fees": 0.002, "actions": list(acts)}]
    beh = behavior_metrics(rows, [loaded])
    c3 = beh["c3_cost"]
    assert c3["long_rate_above_cost"] == pytest.approx(1.0)
    assert c3["cost_selectivity_gap"] == pytest.approx(
        1.0 - c3["long_rate_below_cost"])
    assert c3["n_trades_total"] == 3
    assert c3["transaction_cost_paid"] == pytest.approx(0.002)


def test_retention_math():
    r = retention_ratio(0.8, 0.4)
    assert r["ratio"] == pytest.approx(2.0)
    assert r["status"] == "ok"
    # 分母 <= 0:视为从未学会,不得用比率掩盖
    r2 = retention_ratio(0.5, 0.0)
    assert r2["ratio"] is None
    assert r2["status"].startswith("never_learned")
    r3 = retention_ratio(None, 0.4)
    assert r3["status"] == "unavailable"


def test_retention_gate_thresholds():
    from rl_curriculum.ppo262_final import FINAL_PASS_THRESHOLDS
    assert FINAL_PASS_THRESHOLDS["staged_retention_min"] == {
        "c1": 0.50, "c2": 0.60}
    assert FINAL_PASS_THRESHOLDS["family_core_capture_mean_gt"] == 0.20
    assert FINAL_PASS_THRESHOLDS["aggregate_capture_mean_gt"] == 0.25
    assert FINAL_PASS_THRESHOLDS["behavior_gap_gt"] == {
        "c1_selectivity": 0.15, "c2_gating": 0.15,
        "c3_cost_selectivity": 0.15}
