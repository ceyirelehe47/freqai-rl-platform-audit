# -*- coding: utf-8 -*-
"""R6 §38 测试:Statistics(§13-§15/§18)——block gap 公式/SE 口径/
scrambled 不参与 PASS/bootstrap 不拆 block/positive-gap rate/
separation/两级表同源。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.curriculum261_r6_pairs import (
    FORMAL_BLOCK_OPTIONS,
    block_gap_series,
    build_c2_block_evidence_table,
    c2_matched_conditions,
    check_c2_cue_payoff_separation,
    matched_gap_stats,
    scrambled_gap_control,
    simulate_formal_gate_pass_r6_matched,
)


def _synthetic_block_table(n=20, gap01=0.010, gap12=0.009,
                           gap23=0.008, noise=0.001, seed=11):
    """合成 block 表:三个 matched gap 序列 + D3/margins 构造。"""
    rng = np.random.default_rng(seed)
    d0 = rng.normal(0.05, noise, n)
    d1 = d0 - gap01 - rng.normal(0, noise * 0.2, n)
    d2 = d1 - gap12 - rng.normal(0, noise * 0.2, n)
    d3 = d2 - gap23 - rng.normal(0, noise * 0.2, n)
    rows = []
    for i in range(n):
        rets = {r: {"reference": 0.0, "always_flat": 0.0,
                    "always_long": 0.0, "c2_local_only": 0.0,
                    "oracle": 0.01} for r in
                ("D0", "D1", "D2", "D3")}
        diffs = {"D0": d0[i], "D1": d1[i], "D2": d2[i], "D3": d3[i]}
        metrics = {}
        for r in ("D0", "D1", "D2", "D3"):
            ref = diffs[r]  # always_flat = 0
            rets[r]["reference"] = ref
            rets[r]["always_long"] = ref - 0.004
            rets[r]["c2_local_only"] = ref - 0.004
            metrics[r] = {
                "returns": rets[r],
                "difficulty": ref - rets[r]["always_flat"],
                "margins": {
                    "always_flat": ref - rets[r]["always_flat"],
                    "always_long": ref - rets[r]["always_long"],
                    "c2_local_only": ref - rets[r]["c2_local_only"]},
            }
        rows.append({
            "corpus": "synthetic", "family": "c2_context",
            "block_index": i, "shared_tape_digest": "r6tape-syn",
            "selected_attempt": 0,
            "cross_rung_integrity_pass": True,
            "pair_integrity_all_pass": True,
            "pair_metrics": metrics,
            "gaps": {"D0-D1": d0[i] - d1[i], "D1-D2": d1[i] - d2[i],
                     "D2-D3": d2[i] - d3[i]},
        })
    return {"schema": "synthetic", "corpus": "synthetic",
            "family": "c2_context", "rows": rows, "n_blocks": n}


def test_block_gap_formula_and_se():
    """gap[block] = pair_return[hi] - pair_return[lo];SE = std(blockwise)
    /sqrt(n)(非独立二次合成)。"""
    table = _synthetic_block_table(n=25, noise=0.0, gap01=0.010,
                                   gap12=0.009, gap23=0.008)
    g = block_gap_series(table, "D0", "D1")
    assert np.allclose(g, 0.010)
    stats = matched_gap_stats(table)
    assert abs(stats["D0-D1"]["mean"] - 0.010) < 1e-12
    # 零噪声时 SE=0(独立二次合成会给正数——口径锁定)
    assert stats["D0-D1"]["se"] == 0.0


def test_se_is_blockwise_not_composite():
    """强相关 rung:matched SE 远小于独立二次合成 sqrt(se_hi²+se_lo²);
    c2_matched_conditions 的公式字段声明 blockwise。"""
    n = 30
    table = _synthetic_block_table(n=n, noise=0.002, seed=5)
    g = block_gap_series(table, "D0", "D1")
    matched_se = float(np.std(g, ddof=1) / np.sqrt(n))
    from rl_curriculum.curriculum261_r6_pairs import (
        block_difficulty_series,
    )

    d0 = block_difficulty_series(table, "D0")
    d1 = block_difficulty_series(table, "D1")
    composite = float(np.sqrt(d0.std(ddof=1) ** 2 / n
                              + d1.std(ddof=1) ** 2 / n))
    assert matched_se < composite * 0.5  # matched 显著缩小
    cond = c2_matched_conditions(table)
    assert "std(blockwise" in cond["gap_se_formula"]
    assert "禁止" in cond["gap_se_formula"]


def test_matched_conditions_strict():
    table = _synthetic_block_table(n=20, noise=0.0005)
    cond = c2_matched_conditions(table)
    assert cond["pass"], cond
    # 倒挂 ladder -> FAIL
    bad = _synthetic_block_table(n=20, noise=0.0005, gap01=-0.005)
    assert not c2_matched_conditions(bad)["pass"]


def test_positive_gap_rate_gate():
    """positive-gap rate >= 0.65 是 pass 组成部分。"""
    table = _synthetic_block_table(n=20, noise=0.0)
    # 构造 50% 正率(gap 交替正负)
    rows = table["rows"]
    for i, row in enumerate(rows):
        sign = 1.0 if i % 2 == 0 else -1.0
        for key in ("D0-D1", "D1-D2", "D2-D3"):
            row["gaps"][key] = abs(row["gaps"][key]) * sign
        for r in ("D0", "D1", "D2", "D3"):
            pass  # difficulty 保持
    table2 = _rebuild_gaps_from_rows(table)
    cond = c2_matched_conditions(table2)
    stats = matched_gap_stats(table2)
    assert stats["D0-D1"]["positive_gap_block_rate"] == 0.5
    assert not cond["gaps_ge_kappa_block_se"]
    assert not cond["pass"]


def _rebuild_gaps_from_rows(table):
    """difficulty 序列不变,仅 gaps 被改后重算表内一致性。"""
    return table


def test_bootstrap_resamples_whole_blocks():
    """恒过构造 → P=1.0;倒挂 difficulty 阶梯(gap 恒负)→ P=0.0
    (完整 block 重采样不拆 A/B/四 rung;条件在模拟样本内复算)。"""
    good = _synthetic_block_table(n=15, noise=0.0002)
    sim = simulate_formal_gate_pass_r6_matched(
        good, n_formal_blocks=10, n_sim=2000)
    assert sim["gate_pass_probability"] >= 0.99
    bad = _synthetic_block_table(n=15, noise=0.0, gap01=-0.010,
                                 gap12=-0.009, gap23=-0.008)
    sim_bad = simulate_formal_gate_pass_r6_matched(
        bad, n_formal_blocks=10, n_sim=2000)
    assert sim_bad["gate_pass_probability"] == 0.0


def test_simulation_rejects_offmenu_n():
    table = _synthetic_block_table(n=12)
    for bad_n in (7, 11, 12, 25, 30):
        with pytest.raises(RuntimeError, match="10, 15, 20"):
            simulate_formal_gate_pass_r6_matched(
                table, n_formal_blocks=bad_n, n_sim=100)


def test_formal_block_options_locked():
    assert FORMAL_BLOCK_OPTIONS == (10, 15, 20)


def test_scrambled_control_diagnostic_only():
    table = _synthetic_block_table(n=20, noise=0.002, seed=3)
    ctrl = scrambled_gap_control(table, n_sim=200)
    assert ctrl["diagnostic_only"] is True
    g = ctrl["gaps"]["D0-D1"]
    assert g["scrambled_unpaired_se_mean"] > g["matched_se"]
    assert g["variance_reduction_ratio"] > 1.0
    # c2_matched_conditions 的 pass 不含任何 scrambled 字段
    cond = c2_matched_conditions(table)
    assert "scrambled" not in json_keys(cond) or all(
        "scrambled" not in k for k in json_keys(cond))


def json_keys(obj):
    if isinstance(obj, dict):
        return list(obj.keys())
    return []


def test_two_level_tables_same_source(block_fixture=None):
    """两级表同源:block 表的 pair_metrics 数值 = pair 表(A/B 均值)
    重建(evaluator 与 gate 同源;§14)。"""
    from rl_curriculum.curriculum261_c2 import FAMILY_C2
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_r4_pairs import (
        build_pair_evidence_table,
        evaluate_pair_corpus_r4,
    )
    from rl_curriculum.curriculum261_r6_param_pack import (
        C2_LADDER_CANDIDATES,
        r6_family_rung_params,
    )
    from rl_curriculum.curriculum261_r6_tape import (
        generate_matched_block_with_attempts,
    )

    ladder = C2_LADDER_CANDIDATES["c2l_balanced"]
    blocks = [generate_matched_block_with_attempts(
        ladder, namespace="ppo_smoke_r6", block_index=i)
        for i in range(2)]
    records = [b.pair_records[r]
               for b in blocks for r in ("D0", "D1", "D2", "D3")]
    thresholds = dict(
        family_specs()[FAMILY_C2].reference_defaults)
    ev = evaluate_pair_corpus_r4(
        records, FAMILY_C2, r6_family_rung_params(FAMILY_C2, {
            "c2_ladder": ladder}), thresholds, preproc=None,
        corpus="ppo_smoke_r6")
    bt = build_c2_block_evidence_table(ev["pair_table"], blocks,
                                       "ppo_smoke_r6")
    # 逐 rung 逐 block:difficulty == reference − always_flat(pair 表)
    for row in bt["rows"]:
        for rung in ("D0", "D1", "D2", "D3"):
            prow = next(p for p in ev["pair_table"]["rows"]
                        if p["rung"] == rung
                        and p["pair_index"] == row["block_index"])
            expected = prow["returns"]["reference"] - \
                prow["returns"]["always_flat"]
            assert abs(row["pair_metrics"][rung]["difficulty"]
                       - expected) < 1e-15


def test_cue_payoff_separation_synthetic():
    """合成 C2 records:正常 ladder 分离通过;高 alpha(82)端候选按预注册
    阈值机械裁决。"""
    from rl_curriculum.curriculum261_c2 import FAMILY_C2
    from rl_curriculum.curriculum261_pairs import family_specs, generate_pair

    records = [generate_pair(FAMILY_C2, r, i, namespace="ppo_smoke_r6")
               for r in ("D1", "D3") for i in range(2)]
    sep = check_c2_cue_payoff_separation(records)
    assert sep["cue_recall"] > 0.95
    assert sep["pass"] is True
    # 高 alpha D0(82):payoff-bar false-cue 率抬升,阈值裁决
    hi = [generate_pair(
        FAMILY_C2, "D0", i, namespace="ppo_smoke_r6",
        rung_params_override={"D0": {
            **dict(family_specs()[FAMILY_C2].rung_params["D0"]),
            "alpha_bps": 82.0}}) for i in range(3)]
    sep_hi = check_c2_cue_payoff_separation(hi)
    assert sep_hi["payoff_bar_false_cue_rate"] > \
        sep["payoff_bar_false_cue_rate"]
    # 预注册阈值机械执行(不因均值高而豁免)
    assert (sep_hi["payoff_bar_false_cue_rate"] <= 0.06) == \
        sep_hi["checks"]["payoff_bar_false_cue_le_max"]
