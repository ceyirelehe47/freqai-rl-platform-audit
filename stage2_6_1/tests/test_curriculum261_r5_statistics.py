"""R5 测试:唯一 pair 表与统计口径(§34 Statistics)。

- 唯一 pair 表(行键 (rung, pair_index));A/B 不拆;
- difficulty 定义唯一(ref − flat;flat 恒 0);
- 逐固定基线 margin,无 hindsight max/动态选对手;
- gap SE 二次合成与 rung_report 逐数值一致;
- _ladder_from_table 与 rung_report_r4 同源(evaluator 与 gate 一致)。
"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.curriculum261_c2 import FAMILY_C2
from rl_curriculum.curriculum261_pairs import (
    family_specs,
    generate_pair,
)
from rl_curriculum.curriculum261_qualification import REQUIRED_BASELINES
from rl_curriculum.curriculum261_r4_pairs import (
    build_pair_evidence_table,
    difficulty_series,
    evaluate_pair_corpus_r4,
    margin_series,
    rung_report_r4,
    table_series,
)
from rl_curriculum.curriculum261_r5_design import _ladder_from_table

RUNGS = ("D0", "D1", "D2", "D3")


def _rows():
    rows = []
    for rung in RUNGS:
        for pair in range(3):
            for side in ("A", "B"):
                ref = {"D0": 0.04, "D1": 0.03, "D2": 0.02,
                       "D3": 0.008}[rung]
                rows.append({
                    "rung": rung, "pair": pair, "side": side,
                    "episode_hash": f"h-{rung}-{pair}-{side}",
                    "reference": ref + (0.001 if side == "A" else -0.001),
                    "always_flat": 0.0,
                    "always_long": ref - 0.005,
                    "c2_local_only": ref - 0.02,
                    "oracle": ref + 0.01,
                    "reference_trades": 12,
                })
    return rows


def test_pair_table_unique_keys_and_ab_not_split():
    rows = _rows()
    table = build_pair_evidence_table(rows, FAMILY_C2, "test")
    assert table["n_pairs"] == 12
    keys = {(row["rung"], row["pair_index"]) for row in table["rows"]}
    assert len(keys) == 12

    # 缺 A 端 -> pair cluster 不可拆散:拒绝
    broken = [r for r in rows if not (r["rung"] == "D1"
                                      and r["pair"] == 1
                                      and r["side"] == "A")]
    with pytest.raises(RuntimeError):
        build_pair_evidence_table(broken, FAMILY_C2, "test")


def test_pair_value_is_ab_mean():
    rows = _rows()
    table = build_pair_evidence_table(rows, FAMILY_C2, "test")
    for row in table["rows"]:
        if row["rung"] == "D0":
            assert row["returns"]["reference"] == pytest.approx(0.04)


def test_difficulty_definition_unique():
    table = build_pair_evidence_table(_rows(), FAMILY_C2, "test")
    for rung in RUNGS:
        diff = difficulty_series(table, rung)
        ref = table_series(table, rung, "reference")
        flat = table_series(table, rung, "always_flat")
        assert np.allclose(diff, ref - flat, atol=1e-15)
        assert np.all(flat == 0.0)


def test_margins_fixed_baseline_no_hindsight():
    """margin 恒为 reference − 指名基线;不做 max/事后选优。"""
    rows = _rows()
    # 构造 always_long 在部分 pair 上优于 reference 的情形
    for row in rows:
        if row["rung"] == "D2" and row["pair"] == 0:
            row["always_long"] = row["reference"] + 0.01
    table = build_pair_evidence_table(rows, FAMILY_C2, "test")
    m_long = margin_series(table, "D2", "always_long")
    m_local = margin_series(table, "D2", "c2_local_only")
    # pair0 的 long margin 必须为负(逐 pair 如实;无 max 救援)
    assert m_long[0] == pytest.approx(-0.01, abs=1e-15)
    # 与逐基线名一一对应(不同基线不同序列)
    assert not np.allclose(m_long, m_local)


def test_gap_se_quadratic_composition():
    table = build_pair_evidence_table(_rows(), FAMILY_C2, "test")
    lad = _ladder_from_table(
        table, REQUIRED_BASELINES[FAMILY_C2])["difficulty_ladder"]
    gap = lad["D1"]["mean"] - lad["D2"]["mean"]
    se = float(np.sqrt(lad["D1"]["se"] ** 2 + lad["D2"]["se"] ** 2))
    gaps = _ladder_from_table(
        table, REQUIRED_BASELINES[FAMILY_C2])["adjacent_rung_gaps"]
    assert gaps["D1-D2"]["gap"] == pytest.approx(gap)
    assert gaps["D1-D2"]["se_pair_cluster"] == pytest.approx(se)



def test_ladder_helper_matches_rung_report_bitwise():
    """evaluator 与 gate 同源:_ladder_from_table 复算 rung_report_r4
    的 ladder/margins/gaps 逐数值一致(真实小语料,ppo_smoke_r5)。"""
    specs = family_specs()[FAMILY_C2]
    thresholds = dict(specs.reference_defaults)
    records = [generate_pair(FAMILY_C2, rung, idx,
                             namespace="ppo_smoke_r5")
               for rung in RUNGS for idx in range(2)]
    report = rung_report_r4(records, FAMILY_C2,
                            {r: dict(specs.rung_params[r])
                             for r in RUNGS},
                            thresholds, None, corpus="ppo_smoke_r5")
    merged = _ladder_from_table(report["pair_table"],
                                REQUIRED_BASELINES[FAMILY_C2])
    for r in RUNGS:
        assert merged["difficulty_ladder"][r]["mean"] == \
            pytest.approx(report["difficulty_ladder"][r]["mean"])
        assert merged["difficulty_ladder"][r]["sd"] == \
            pytest.approx(report["difficulty_ladder"][r]["sd"])
        assert merged["difficulty_ladder"][r]["se"] == \
            pytest.approx(report["difficulty_ladder"][r]["se"])
    for b in REQUIRED_BASELINES[FAMILY_C2]:
        for r in RUNGS:
            assert merged["fixed_baseline_margins"][b][r]["mean"] == \
                pytest.approx(
                    report["fixed_baseline_margins"][b][r]["mean"])
    for k in ("D0-D1", "D1-D2", "D2-D3"):
        assert merged["adjacent_rung_gaps"][k]["gap"] == \
            pytest.approx(report["adjacent_rung_gaps"][k]["gap"])
        assert merged["adjacent_rung_gaps"][k][
            "se_pair_cluster"] == pytest.approx(
                report["adjacent_rung_gaps"][k]["se_pair_cluster"])
    assert merged["difficulty_ordering_ok"] == \
        report["difficulty_ordering_ok"]
