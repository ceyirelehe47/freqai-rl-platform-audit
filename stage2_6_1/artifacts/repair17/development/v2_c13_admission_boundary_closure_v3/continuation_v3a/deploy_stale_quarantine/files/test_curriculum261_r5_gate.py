"""R5 测试:strict per-corpus gate(§34)。

- main FAIL 不能被 holdout 救;holdout FAIL 不能被 main 救;
- pooled PASS 不能覆盖 strict FAIL(pooled 仅诊断);
- 量级条件(gaps/D3/margins 的 κ×SE)是 pass 的组成部分;
- gate FAIL 阻断 plan 生成;
- 密度 gate 阈值。
"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.curriculum261_qualification import REQUIRED_BASELINES
from rl_curriculum.curriculum261_r4_pairs import (
    build_pair_evidence_table,
)
from rl_curriculum.curriculum261_r5_design import _ladder_from_table
from rl_curriculum.curriculum261_r5_pairs import (
    ROBUSTNESS_KAPPA_R5,
    corpus_conditions_r5,
    curriculum_robustness_gate_r5,
    density_gate_r5,
    strict_gate_rule_identity,
)

RUNGS = ("D0", "D1", "D2", "D3")
BASELINES = ("always_flat", "always_long", "c2_local_only")


def _episode_rows(ladder_means: dict[str, float],
                  margins_add: dict[str, float] | None = None,
                  sd: float = 0.0005, n_pairs: int = 12,
                  seed: int = 5) -> list[dict]:
    """合成 per-episode 行(确定性:均值精确,pair 间 sd 精确 = sd)。

    pair 偏差 = sd × 零均值单位方差 pattern(同一 pair 的 A/B 同偏 ->
    pair 值 = mean + 偏差;无抽样噪声,κ 条件可精确判定)。
    """
    rng = np.random.default_rng(seed)
    margins_add = margins_add or {}
    pattern = np.linspace(-1.0, 1.0, n_pairs)
    pattern = (pattern - pattern.mean())
    pattern = pattern / max(np.std(pattern, ddof=1), 1e-12)
    rows = []
    for rung in RUNGS:
        for pair in range(n_pairs):
            for side in ("A", "B"):
                diff = ladder_means[rung] + sd * pattern[pair] \
                    + 1e-9 * rng.random()
                row = {
                    "rung": rung, "pair": pair, "side": side,
                    "episode_hash": f"h-{rung}-{pair}-{side}",
                    "reference": diff,
                    "always_flat": 0.0,
                    "oracle": diff + 0.01,
                }
                for b in ("always_long", "c2_local_only",
                          "c3_cost_ignorant"):
                    row[b] = diff - margins_add.get(b, 0.01)
                rows.append(row)
    return rows


def _family_report(ladder_means, family="c2_context", seed=5,
                   n_pairs=12, sd=0.0005):
    rows = _episode_rows(ladder_means, seed=seed, n_pairs=n_pairs, sd=sd)
    table = build_pair_evidence_table(rows, family, "test")
    report = _ladder_from_table(table, REQUIRED_BASELINES[family])
    report["pair_integrity_pass_rate"] = 1.0
    report["oracle_positive_all_rungs"] = True
    report["attempt_stats"] = {"n_pairs": n_pairs,
                               "mean_attempts": 1.0,
                               "max_attempts": 5,
                               "max_attempts_used": 1}
    return report


def _corpus(c2_report, c1_report=None, c3_report=None):
    """三族 corpus(c1/c3 缺省用通过性合成报告)。"""
    passing = _c2_passing_means()
    return {
        "seed_namespace": "calibration_r5",
        "families": {
            "c1_opportunity": c1_report or _family_report(
                passing, family="c1_opportunity", seed=7),
            "c2_context": c2_report,
            "c3_cost": c3_report or _family_report(
                passing, family="c3_cost", seed=8),
        },
    }


def _c2_passing_means():
    return {"D0": 0.040, "D1": 0.030, "D2": 0.020, "D3": 0.008}


def test_strict_conditions_all_pass():
    cond = corpus_conditions_r5(_family_report(_c2_passing_means()))
    assert cond["pass"] is True
    assert cond["ordering_ok"] and cond["gaps_ge_kappa_se"]
    assert cond["d3_positive"] and cond["d3_mean_ge_kappa_se"]
    assert cond["margins_ok"]


def test_strict_gap_magnitude_is_part_of_pass():
    """gap>0 但 < κ×SE:strict 口径下 FAIL(R4 口径中曾是诊断字段)。"""
    means = _c2_passing_means()
    means["D2"] = 0.0205  # D2-D3 gap 0.0125 -> 但 D1-D2 gap 0.0095 收窄?
    report = _family_report(means, sd=0.02)  # 大方差 -> κ×SE 超过 gap
    cond = corpus_conditions_r5(report)
    # ordering 可能仍成立,但量级条件必须 FAIL
    assert cond["pass"] is False


def test_strict_d3_magnitude():
    means = _c2_passing_means()
    means["D3"] = 0.0004  # D3>0 但极小
    report = _family_report(means, sd=0.002)
    cond = corpus_conditions_r5(report)
    assert cond["d3_positive"] is True
    assert cond["d3_mean_ge_kappa_se"] is False
    assert cond["pass"] is False


def test_strict_margin_failure_blocks_pass():
    rows = _episode_rows(_c2_passing_means())
    for row in rows:
        if row["rung"] == "D1":
            row["c2_local_only"] = row["reference"] + 0.01  # margin 为负
    table = build_pair_evidence_table(rows, "c2_context", "test")
    report = _ladder_from_table(table, BASELINES)
    report["pair_integrity_pass_rate"] = 1.0
    report["oracle_positive_all_rungs"] = True
    report["attempt_stats"] = {"n_pairs": 12, "mean_attempts": 1.0,
                               "max_attempts": 5, "max_attempts_used": 1}
    cond = corpus_conditions_r5(report)
    assert cond["margins_ok"] is False
    assert cond["pass"] is False


def _gate(main_means, holdout_means, stress=None, c2_diag=None,
          c2_density=None):
    fam_main = _family_report(main_means, seed=5)
    fam_hold = _family_report(holdout_means, seed=6)
    return curriculum_robustness_gate_r5(
        _corpus(fam_main), _corpus(fam_hold),
        kappa=ROBUSTNESS_KAPPA_R5, stress=stress,
        c2_diagnostics=c2_diag, c2_density=c2_density)


def test_main_fail_not_rescued_by_holdout():
    bad = _c2_passing_means()
    bad["D3"] = bad["D2"] + 0.001  # main: D2<D3 倒挂
    gate = _gate(bad, _c2_passing_means())
    fam = gate["families"]["c2_context"]
    assert fam["calibration_r5_conditions_strict"]["pass"] is False
    assert fam["calibration_holdout_r5_conditions_strict"]["pass"] is True
    assert fam["pass"] is False
    assert gate["pass"] is False


def test_holdout_fail_not_rescued_by_main():
    bad = _c2_passing_means()
    bad["D2"] = bad["D1"] + 0.001  # holdout: D1<D2 倒挂
    gate = _gate(_c2_passing_means(), bad)
    fam = gate["families"]["c2_context"]
    assert fam["calibration_r5_conditions_strict"]["pass"] is True
    assert fam["calibration_holdout_r5_conditions_strict"]["pass"] is False
    assert fam["pass"] is False


def test_pooled_cannot_rescue_strict_fail():
    """main+holdout 合并后量级充足,但 main 单独 FAIL -> gate FAIL。"""
    # 人为放大 main 的 D1 均值漂移,确保 main ordering FAIL
    bad = _c2_passing_means()
    bad["D1"] = bad["D0"] + 0.001
    fam_main = _family_report(bad, seed=5, n_pairs=8)
    fam_hold = _family_report(_c2_passing_means(), seed=6, n_pairs=8)
    gate = curriculum_robustness_gate_r5(
        _corpus(fam_main), _corpus(fam_hold))
    fam = gate["families"]["c2_context"]
    assert fam["pass"] is False
    pooled = fam["pooled_diagnostic_not_for_pass"]
    assert pooled["diagnostic_only"] is True
    # 即使 pooled 口径 PASS,也不能改变 strict FAIL
    assert fam["pass"] is False


def test_c2_gate_requires_diagnostics_and_density():
    gate = _gate(_c2_passing_means(), _c2_passing_means(),
                 c2_diag=None, c2_density=None)
    fam = gate["families"]["c2_context"]
    assert fam["pass"] is False  # 缺双诊断/密度 -> 不通过
    ok_diag = {"local_cue_independence": {"pass": True},
               "context_observability": {"pass": True}}
    ok_density = {"main": {"pass": True}, "holdout": {"pass": True}}
    gate = _gate(_c2_passing_means(), _c2_passing_means(),
                 c2_diag=ok_diag, c2_density=ok_density)
    fam = gate["families"]["c2_context"]
    assert fam["c2_diagnostics"] == {
        "local_cue_independence": True, "context_observability": True,
        "behavior_density_gate": True}
    assert fam["pass"] is True


def test_gate_fail_blocks_plan():
    from rl_curriculum.curriculum261_r5_plan import build_plan_r5

    def _kwargs(prep_pass, cur_pass):
        return dict(
            baseline_commit="x", vendor_pin="v",
            frozen_contracts={},
            parameter_pack={"digest": "r5pk-t", "pack_version": "v",
                            "tier": "A",
                            "selected_c2_candidate": "c",
                            "r4_parameter_pack_digest": "r4pk-t"},
            design_plan_digest="r5dp-t",
            selected_c2_candidate="c", tier_executed="A",
            frozen_parameter_identity={"identity": "r5fp-t"},
            preprocessing_v2_contract_digest="r4pc-t",
            calibration_bundle_hash="b1", holdout_bundle_hash="b2",
            preprocessing_robustness_gate={"pass": prep_pass},
            curriculum_robustness_gate={"pass": cur_pass},
            conditioning_gate_constants={}, supervised_gate_constants={},
            kappa=1.5, reference_thresholds_by_family={},
            density_thresholds={},
            prior_r2_plan_digest="qp-t",
            prior_diag262r2_plan_digest="dp-t",
            prior_r4_baseline_commit="d1",
            prior_r4_parameter_pack_digest="r4pk-t")

    with pytest.raises(RuntimeError):
        build_plan_r5(**_kwargs(False, True))
    with pytest.raises(RuntimeError):
        build_plan_r5(**_kwargs(True, False))


def test_density_gate_thresholds():
    ok = density_gate_r5({
        "median_reference_trades_per_episode": 12.5,
        "reference_long_label_rate": 0.033})
    assert ok["pass"] is True
    low_trades = density_gate_r5({
        "median_reference_trades_per_episode": 7.9,
        "reference_long_label_rate": 0.033})
    assert low_trades["pass"] is False
    low_rate = density_gate_r5({
        "median_reference_trades_per_episode": 12.5,
        "reference_long_label_rate": 0.014})
    assert low_rate["pass"] is False


def test_strict_rule_identity_stable():
    ident = strict_gate_rule_identity()
    assert ident.startswith("r5sg-")
    assert len(ident) == len("r5sg-") + 64
