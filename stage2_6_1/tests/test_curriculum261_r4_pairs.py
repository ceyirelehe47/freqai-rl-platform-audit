"""R4 测试:统一 pair 统计(唯一 pair 表/难度口径/逐基线 margin/
pair-cluster/bootstrap)(§10-§13/§33)。

- 唯一 pair 表:全部统计从同一表派生;A/B 聚合为单一 cluster;
- difficulty 只用 reference-vs-flat(不含 always_long 项);
- episode-level hindsight baseline max 路径被拒绝(构造符号翻转场景);
- bootstrap 按 pair 重采样(不拆散 A/B)、固定 seed 决定;
- gate 与 evaluator 数字同源(corpus_conditions 从 pair 表重算一致);
- 功效模拟边界行为(强效应 ~1 / 零均值 ~0)。
"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.curriculum261_r4_pairs import (
    ROBUSTNESS_KAPPA_R4,
    bootstrap_mean_ci,
    build_pair_evidence_table,
    cluster_stats,
    corpus_conditions_r4,
    curriculum_robustness_gate_r4,
    difficulty_metric_validation,
    difficulty_series,
    margin_series,
    simulate_formal_gate_pass,
    table_series,
)


def _episode_rows(per_side: dict[str, list[float]], *, rung: str = "D3",
                  n_pairs: int) -> list[dict]:
    """per_side: {policy: [side_A 值 per pair, side_B 值 per pair]} ->
    episode 行。"""
    rows = []
    for p in range(n_pairs):
        for side in ("A", "B"):
            row: dict = {
                "rung": rung, "pair": p, "side": side,
                "episode_hash": f"ce-{rung}-{p}-{side}"}
            for name, (a_vals, b_vals) in per_side.items():
                row[name] = (a_vals if side == "A" else b_vals)[p]
            rows.append(row)
    return rows


# ------------------------------------------------------------- pair 表
def test_pair_table_aggregates_sides_as_one_cluster():
    n = 4
    rows = _episode_rows({
        "reference": ([0.10, 0.08, 0.12, 0.09],
                      [0.04, 0.06, 0.02, 0.05]),
        "always_flat": ([0.0] * n, [0.0] * n),
        "always_long": ([0.02, 0.01, 0.03, 0.02], [-0.01] * n),
        "oracle": ([0.2] * n, [0.2] * n),
    }, n_pairs=n)
    table = build_pair_evidence_table(rows, "c1_opportunity", "t")
    assert table["n_pairs"] == 4  # 8 episodes -> 4 clusters
    ref = table_series(table, "D3", "reference")
    assert len(ref) == 4
    assert np.allclose(ref, [(0.10 + 0.04) / 2, (0.08 + 0.06) / 2,
                             (0.12 + 0.02) / 2, (0.09 + 0.05) / 2])


def test_pair_table_requires_both_sides():
    rows = _episode_rows({
        "reference": ([0.1, 0.1], [0.1, 0.1]),
        "always_flat": ([0.0, 0.0], [0.0, 0.0]),
    }, n_pairs=2)
    rows = [r for r in rows if r["side"] == "A"]
    with pytest.raises(RuntimeError):
        build_pair_evidence_table(rows, "c1_opportunity", "t")


# ------------------------------------------------------------- 难度口径
def test_difficulty_is_reference_minus_flat_only():
    n = 6
    ref_a = [0.10, 0.08, 0.12, 0.09, 0.11, 0.07]
    ref_b = [0.03, 0.05, 0.01, 0.04, 0.02, 0.06]
    rows = _episode_rows({
        "reference": (ref_a, ref_b),
        "always_flat": ([0.0] * n, [0.0] * n),
        "always_long": ([0.05] * n, [-0.02] * n),
        "oracle": ([0.2] * n, [0.2] * n),
    }, n_pairs=n)
    table = build_pair_evidence_table(rows, "c1_opportunity", "t")
    diff = difficulty_series(table, "D3")
    ref = table_series(table, "D3", "reference")
    flat = table_series(table, "D3", "always_flat")
    assert np.all(flat == 0.0)
    assert np.allclose(diff, ref - flat, atol=1e-15)
    assert not np.allclose(diff, 0.0)  # 非退化
    # 不含 always_long 项:改 always_long 不改变 difficulty
    rows2 = [dict(r, always_long=r["always_long"] + 0.5) for r in rows]
    table2 = build_pair_evidence_table(rows2, "c1_opportunity", "t")
    assert np.allclose(difficulty_series(table2, "D3"), diff, atol=1e-15)
    assert difficulty_metric_validation(table, "c1_opportunity")[
        "pass"] is True


# ------------------------------------------------- 逐基线 margin(反hindsight)
def test_episode_level_hindsight_max_path_rejected():
    """构造符号翻转:per-baseline(对 always_long)mean > 0,而
    episode 级 max(0, always_long) hindsight 口径 mean < 0。

    4 个 pair x A/B:pair0/1 的 always_long 深负(A/B 同值),
    pair2/3 的 always_long 小胜 reference。逐基线 margin 为正;
    hindsight(逐 episode 取 max(0, long))在深负 episode 把基线
    切换为 flat,压低 margin 至负。
    """
    n = 4
    ref_a = [0.01, 0.01, -0.05, -0.05]
    ref_b = [0.01, 0.01, -0.05, -0.05]
    long_a = [-0.20, -0.20, 0.10, 0.10]
    long_b = [-0.20, -0.20, 0.10, 0.10]
    rows = _episode_rows({
        "reference": (ref_a, ref_b),
        "always_flat": ([0.0] * n, [0.0] * n),
        "always_long": (long_a, long_b),
        "oracle": ([0.2] * n, [0.2] * n),
    }, n_pairs=n)
    table = build_pair_evidence_table(rows, "c1_opportunity", "t")
    per_baseline = margin_series(table, "D3", "always_long")
    hindsight_pair = []
    for p in range(n):
        eps = [r for r in rows if r["pair"] == p]
        hindsight_pair.append(float(np.mean([
            r["reference"] - max(0.0, r["always_long"])
            for r in eps])))
    assert float(np.mean(per_baseline)) > 0
    assert float(np.mean(hindsight_pair)) < 0  # hindsight 口径翻转
    # R4 的正式口径 = per-baseline(gate 使用的 margin_series)
    assert float(np.mean(per_baseline)) != pytest.approx(
        float(np.mean(hindsight_pair)))


# ------------------------------------------------------------- bootstrap
def test_bootstrap_resamples_pairs_deterministic():
    vals = np.array([0.10, -0.02, 0.08, 0.11, 0.03, 0.09, 0.07, 0.12,
                     0.05, 0.06])
    ci1 = bootstrap_mean_ci(vals, n_boot=300)
    ci2 = bootstrap_mean_ci(vals, n_boot=300)
    assert ci1 == ci2  # 固定 seed 决定性
    ci3 = bootstrap_mean_ci(vals, n_boot=300, seed=20260903)
    assert ci3["ci_low"] != ci1["ci_low"]
    assert ci1["resamples"] == 300


def test_bootstrap_does_not_split_pairs():
    """bootstrap 输入是 pair 级序列;同 pair 的 A/B 不作为独立样本
    进入重采样(由 build_pair_evidence_table 先聚合保证)。"""
    n = 5
    rows = _episode_rows({
        "reference": ([0.1] * n, [0.1] * n),
        "always_flat": ([0.0] * n, [0.0] * n),
    }, n_pairs=n)
    table = build_pair_evidence_table(rows, "c1_opportunity", "t")
    assert table["n_pairs"] == 5
    assert len(difficulty_series(table, "D3")) == 5  # 不是 10


# ------------------------------------------- gate 与 evaluator 数字同源
def _fake_family_report(mean_d3=0.03, sd=0.006, margin=0.02):
    """构造与 rung_report_r4 同构的报告(全部字段从 pair 表派生,
    与真实实现同款构造:ladder/margins/gaps 全部来自同一张表)。"""
    rng = np.random.default_rng(7)
    rungs = ("D0", "D1", "D2", "D3")
    means = {"D0": 0.20, "D1": 0.10, "D2": 0.06, "D3": mean_d3}
    # 确定性构造:样本均值/样本 sd 精确等于目标(kappa 断言无抽样噪声)
    unit = np.linspace(-1.0, 1.0, 10)
    unit = (unit - unit.mean()) / unit.std(ddof=1)
    rows_all = []
    for r in rungs:
        vals = means[r] + sd * unit
        for i, v in enumerate(vals):
            for side in ("A", "B"):
                rows_all.append({
                    "rung": r, "pair": i, "side": side,
                    "episode_hash": f"ce-{r}-{i}-{side}",
                    "reference": v,
                    "always_flat": 0.0,
                    "always_long": v - margin,
                    "oracle": 0.1,
                })
    table = build_pair_evidence_table(
        rows_all, "c1_opportunity", "t")
    ladder = {}
    for r in rungs:
        st = cluster_stats(difficulty_series(table, r))
        ladder[r] = {**st,
                     "bootstrap_ci": bootstrap_mean_ci(
                         difficulty_series(table, r))}
    margins = {b: {r: {**cluster_stats(margin_series(table, r, b)),
                       "bootstrap_ci": bootstrap_mean_ci(
                           margin_series(table, r, b))}
                   for r in rungs}
               for b in ("always_flat", "always_long")}
    gaps = {}
    for k in range(3):
        hi, lo = rungs[k], rungs[k + 1]
        gap = ladder[hi]["mean"] - ladder[lo]["mean"]
        se = float(np.sqrt(ladder[hi]["se"] ** 2 + ladder[lo]["se"] ** 2))
        gaps[f"{hi}-{lo}"] = {"gap": gap, "se_pair_cluster": se,
                              "gap_over_se": gap / se if se else None}
    return {
        "family": "c1_opportunity", "corpus": "t",
        "pair_table": table,
        "difficulty_ladder": ladder,
        "difficulty_ordering_ok": bool(
            ladder["D0"]["mean"] > ladder["D1"]["mean"]
            > ladder["D2"]["mean"] > ladder["D3"]["mean"]),
        "fixed_baseline_margins": margins,
        "adjacent_rung_gaps": gaps,
        "oracle_positive_all_rungs": True,
        "attempt_stats": {"n_pairs": 40, "mean_attempts": 1.0,
                          "max_attempts_used": 1, "max_attempts": 5},
        "pair_integrity_pass_rate": 1.0,
    }


def test_gate_numbers_derive_from_pair_table():
    rep = _fake_family_report()
    cond = corpus_conditions_r4(rep)
    ladder_d3 = rep["difficulty_ladder"]["D3"]
    assert cond["d3_mean"] == ladder_d3["mean"]
    assert cond["d3_se"] == ladder_d3["se"]
    # margin 数字与直接从 pair 表重算一致(唯一数据源)
    m = margin_series(rep["pair_table"], "D3", "always_long")
    st = cluster_stats(m)
    assert cond["fixed_baseline_margins"]["always_long"]["D3"][
        "mean"] == st["mean"]
    assert cond["fixed_baseline_margins"]["always_long"]["D3"][
        "se"] == st["se"]


def test_gate_uses_kappa_rule():
    sd = 0.006
    # mean = 1.4 x SE -> False;1.6 x SE -> True(kappa = 1.5)
    rep_lo = _fake_family_report(mean_d3=1.4 * sd / np.sqrt(10), sd=sd)
    rep_hi = _fake_family_report(mean_d3=1.6 * sd / np.sqrt(10), sd=sd)
    assert rep_lo["difficulty_ladder"]["D3"]["mean"] < \
        ROBUSTNESS_KAPPA_R4 * rep_lo["difficulty_ladder"]["D3"]["se"]
    assert corpus_conditions_r4(rep_lo)[
        "d3_mean_ge_kappa_se_strict_corpus"] is False
    assert corpus_conditions_r4(rep_hi)[
        "d3_mean_ge_kappa_se_strict_corpus"] is True


def test_gate_requires_both_corpora():
    rep = _fake_family_report()
    main = {"families": {"c1_opportunity": rep,
                         "c2_context": rep, "c3_cost": rep},
            "seed_namespace": "calibration_r4"}
    # 坏 holdout:D3 翻负 -> 逐 corpus d3_positive FAIL -> family FAIL
    hold = {"families": {"c1_opportunity": _fake_family_report(
        mean_d3=-0.002, sd=0.006),
        "c2_context": rep, "c3_cost": rep}}
    gate = curriculum_robustness_gate_r4(main, hold)
    assert gate["families"]["c1_opportunity"]["pass"] is False
    hold2 = {"families": {"c1_opportunity": _fake_family_report(),
                          "c2_context": rep, "c3_cost": rep}}
    gate2 = curriculum_robustness_gate_r4(main, hold2)
    assert gate2["families"]["c1_opportunity"]["pass"] is True
    # pooled 口径存在且量级条件可判定
    assert "pooled_conditions" in gate2["families"]["c1_opportunity"]
    assert gate2["families"]["c1_opportunity"]["pooled_conditions"][
        "d3_pooled_ge_kappa_se"] is True


# ------------------------------------------------------------- 功效模拟
def test_power_simulation_bounds():
    rng = np.random.default_rng(5)
    d3 = rng.normal(0.05, 0.004, 60)
    strong = simulate_formal_gate_pass(
        d3, rng.normal(0.20, 0.01, 60),
        {"always_flat": d3,
         "always_long": rng.normal(0.03, 0.005, 60)},
        n_sim=300)
    assert strong["gate_pass_probability"] > 0.95
    d3z = rng.normal(0.0, 0.01, 60)
    zero = simulate_formal_gate_pass(
        d3z, rng.normal(0.20, 0.01, 60),
        {"always_flat": d3z,
         "always_long": rng.normal(-0.001, 0.01, 60)},
        n_sim=300)
    assert zero["gate_pass_probability"] < 0.05
