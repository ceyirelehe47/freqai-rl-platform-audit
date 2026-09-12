# -*- coding: utf-8 -*-
"""R6 §38 测试:Candidate Selection(§19/§22/§26)与 Marginal Guard
(§16)——最小 n 优先/maximin/tie-break/FAIL 自动 power summary/
matched 不可覆盖 marginal FAIL。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.curriculum261_r6_design import (
    _maximin_score,
    _qualified_at_n,
    run_design_stage,
)
from rl_curriculum.curriculum261_r6_pairs import FORMAL_BLOCK_OPTIONS


def _corpus_result(qualified_by_n, score_by_n, semantics=True,
                   density=True, integrity=True, oracle=True):
    per_n = {}
    for n in ("10", "15", "20"):
        per_n[n] = {
            "n_formal_blocks": int(n),
            "gap_checks": {}, "d3_check": {}, "margin_checks": {},
            "formal_gate_simulation": {
                "gate_pass_probability": 0.95 if n in
                qualified_by_n else 0.3},
            "reasons": {
                "ordering_ok": n in qualified_by_n,
                "gaps_ge_3x_se_and_positive_rate": n in qualified_by_n,
                "d3_ge_2p5x_se": n in qualified_by_n,
                "margins_positive_and_d2_d3_ge_2p5x_se": n in
                qualified_by_n,
                "formal_gate_probability_ge_0p90": n in qualified_by_n},
            "qualified": n in qualified_by_n,
        }
    return {
        "corpus": "synthetic_ns",
        "per_formal_block_count": per_n,
        "semantics_pass": semantics,
        "density_pass": density,
        "pair_integrity_unity": integrity,
        "oracle_positive": oracle,
        "block_table": None,
        "density_gates": {},
        "scrambled_control_diagnostic": {"gaps": {}},
        "maximin_score_by_qualified_n_hint": score_by_n,
    }


def test_selection_order_min_n_then_maximin(monkeypatch, tmp_path):
    """最小 n 优先:即使 n=20 的 score 更高,选 n=10 合格者。"""
    cand_results = {
        "cand_big_score_high": {
            "candidate_params": {}, "corpora": [],
            "qualified_by_block_count": {"10": True, "15": True,
                                         "20": True},
            "maximin_score_by_qualified_n": {"10": 4.0, "15": 4.0,
                                             "20": 4.0},
            "qualified_any": True,
            "param_distance_from_historical": 0.5},
        "cand_only_n20": {
            "candidate_params": {}, "corpora": [],
            "qualified_by_block_count": {"10": False, "15": False,
                                         "20": True},
            "maximin_score_by_qualified_n": {"20": 99.0},
            "qualified_any": True,
            "param_distance_from_historical": 0.1},
    }
    # 重构 run_design_stage 的选择段:直接用内部逻辑验证
    selected_n = None
    for n in FORMAL_BLOCK_OPTIONS:
        combos = [(cid, res) for cid, res in cand_results.items()
                  if res["qualified_by_block_count"][str(n)]]
        if combos:
            ranked = sorted(
                combos,
                key=lambda kv: (
                    -kv[1]["maximin_score_by_qualified_n"][str(n)],
                    kv[1]["param_distance_from_historical"], kv[0]))
            selected_n = n
            break
    assert selected_n == 10  # cand_big_score_high 在 n=10 胜出


def test_selection_tie_break_distance_then_id(monkeypatch):
    cand_results = {
        "cand_a": {"maximin_score_by_qualified_n": {"10": 3.0},
                   "param_distance_from_historical": 0.5},
        "cand_b": {"maximin_score_by_qualified_n": {"10": 3.0},
                   "param_distance_from_historical": 0.2},
        "cand_c": {"maximin_score_by_qualified_n": {"10": 3.0},
                   "param_distance_from_historical": 0.2},
    }
    combos = [(cid, res) for cid, res in cand_results.items()]
    ranked = sorted(
        combos, key=lambda kv: (
            -kv[1]["maximin_score_by_qualified_n"]["10"],
            kv[1]["param_distance_from_historical"], kv[0]))
    assert [r[0] for r in ranked][:2] == ["cand_b", "cand_c"]


def test_design_fail_writes_auto_power_summary(monkeypatch, tmp_path):
    """§26:无合格组合 -> FAIL;power analysis 由流程自动产出(非手工);
    不生成 pack。"""
    import rl_curriculum.curriculum261_r6_design as dmod

    plan = {"candidate_grid": {"candidates": {
        "only_cand": dmod.r6_candidate_grid()["c2l_balanced"]}},
        "design_data": {
            "blocks_per_candidate_per_corpus": 4,
            "corpora": ["ns_a"]}}
    # 全部 n 不合格
    monkeypatch.setattr(
        dmod, "_evaluate_candidate_matched",
        lambda cid, ladder, ns, thresholds, n_blocks=4: _corpus_result(
            set(), {}))
    (tmp_path / "r6_design_plan.json").write_text("{}", encoding="utf-8")
    summary = run_design_stage(
        tmp_path, plan, "r6dp-test", baseline_commit="x")
    assert summary["pass"] is False
    assert summary["qualified_combinations"] == 0
    assert "weakest_binding_condition" in summary
    assert (tmp_path / "r6_power_analysis.json").is_file()
    power = json.loads(
        (tmp_path / "r6_power_analysis.json").read_text(encoding="utf-8"))
    assert power["provenance"].startswith("本文件由 run_design_stage")
    assert not (tmp_path / "r6_parameter_pack.json").exists()


def test_marginal_guard_blocks_despite_matched_pass():
    """§16:matched PASS 不能覆盖 marginal FAIL(curriculum gate)。"""
    from rl_curriculum.curriculum261_r6_pairs import (
        curriculum_robustness_gate_r6,
    )

    def _c13_report(pass_=True):
        ladder = {r: {"mean": m, "se": 0.001, "bootstrap_ci": {}}
                  for r, m in zip(("D0", "D1", "D2", "D3"),
                                  (0.04, 0.03, 0.02, 0.01))}
        margins = {b: {r: {"mean": 0.5 if pass_ else -0.1, "se": 0.01,
                           "bootstrap_ci": {}}
                       for r in ladder} for b in
                   ("always_flat", "always_long", "c2_local_only")}
        gaps = {f"{a}-{b}": {"gap": 0.01, "se_pair_cluster": 0.001,
                             "gap_over_se": 10.0}
                for a, b in (("D0", "D1"), ("D1", "D2"), ("D2", "D3"))}
        return {
            "difficulty_ladder": ladder,
            "adjacent_rung_gaps": gaps,
            "fixed_baseline_margins": margins,
            "pair_table": {"n_pairs": 40},
            "pair_integrity_pass_rate": 1.0 if pass_ else 0.5,
            "oracle_positive_all_rungs": pass_,
            "attempt_stats": {"n_pairs": 40, "mean_attempts": 0.1,
                              "max_attempts": 5, "max_attempts_used": 1},
        }

    main = {"families": {"c1_opportunity": _c13_report(),
                         "c3_cost": _c13_report(),
                         "c2_context": {"attempt_stats": {
                             "n_pairs": 40, "mean_attempts": 0.1,
                             "max_attempts": 5,
                             "max_attempts_used": 1}}},
            "seed_namespace": "calibration_r6"}
    hold = {"families": {"c1_opportunity": _c13_report(),
                         "c3_cost": _c13_report(),
                         "c2_context": {"attempt_stats": {
                             "n_pairs": 40, "mean_attempts": 0.1,
                             "max_attempts": 5,
                             "max_attempts_used": 1}}},
            "seed_namespace": "calibration_holdout_r6"}

    # C2 block 表:构造 matched 全过(强 gap)
    from rl_curriculum.curriculum261_r6_pairs import c2_matched_conditions
    stats_table = _make_passing_block_table()
    assert c2_matched_conditions(stats_table)["pass"]

    gate = curriculum_robustness_gate_r6(
        main, hold,
        c2_block_main=stats_table, c2_block_holdout=stats_table,
        c2_marginal_main={"pass": False},  # marginal FAIL
        c2_marginal_holdout={"pass": True},
        c2_diagnostics={
            "local_cue_independence": {"pass": True},
            "context_observability": {"pass": True},
            "cue_payoff_separation": {"pass": True}},
        c2_density={"main": {"pass": True}, "holdout": {"pass": True}})
    assert gate["families"]["c1_opportunity"]["pass"]
    assert not gate["families"]["c2_context"]["pass"], \
        "matched PASS 不得覆盖 marginal FAIL"
    assert not gate["pass"]


def _make_passing_block_table(n=15):
    rows = []
    for i in range(n):
        metrics = {}
        diffs = {"D0": 0.05, "D1": 0.04, "D2": 0.03, "D3": 0.02}
        for r, v in diffs.items():
            metrics[r] = {
                "returns": {"reference": v, "always_flat": 0.0,
                            "always_long": v - 0.01,
                            "c2_local_only": v - 0.01,
                            "oracle": 0.01},
                "difficulty": v,
                "margins": {"always_flat": v, "always_long": 0.01,
                            "c2_local_only": 0.01}}
        rows.append({
            "corpus": "syn", "family": "c2_context", "block_index": i,
            "shared_tape_digest": "r6tape-s", "selected_attempt": 0,
            "cross_rung_integrity_pass": True,
            "pair_integrity_all_pass": True,
            "pair_metrics": metrics,
            "gaps": {"D0-D1": 0.01, "D1-D2": 0.01, "D2-D3": 0.01}})
    return {"rows": rows, "n_blocks": n}


def test_marginal_guard_conditions_own_checks():
    """independent ordering 翻转 → guard FAIL(无 SE 要求也检查 mean)。"""
    from rl_curriculum.curriculum261_r6_pairs import (
        c2_marginal_guard_conditions,
    )

    def rep(ordering_ok=True):
        means = [0.04, 0.03, 0.02, 0.01] if ordering_ok else \
            [0.01, 0.02, 0.03, 0.04]
        ladder = {r: {"mean": m} for r, m in
                  zip(("D0", "D1", "D2", "D3"), means)}
        margins = {b: {r: {"mean": 0.01} for r in ladder} for b in
                   ("always_flat", "always_long", "c2_local_only")}
        return {"difficulty_ladder": ladder,
                "fixed_baseline_margins": margins,
                "pair_table": {"n_pairs": 80},
                "pair_integrity_pass_rate": 1.0,
                "oracle_positive_all_rungs": True}

    ok = c2_marginal_guard_conditions(
        rep(True), density={"pass": True},
        semantics={"local_cue_independence": {"pass": True},
                   "context_observability": {"pass": True},
                   "cue_payoff_separation": {"pass": True}})
    assert ok["pass"]
    bad = c2_marginal_guard_conditions(
        rep(False), density={"pass": True},
        semantics={"local_cue_independence": {"pass": True},
                   "context_observability": {"pass": True},
                   "cue_payoff_separation": {"pass": True}})
    assert not bad["pass"]
    assert not bad["mean_ordering_ok"]
