# -*- coding: utf-8 -*-
"""R7 §34 测试:Design Selection(§12/§14/§19/§20/§21)——
shared gate 先行且 FAIL 即 design FAIL、candidate 选择解耦 recall、
最小 n/maximin/tie-break、marginal guard 不可覆盖、FAIL 路径清洁。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from rl_curriculum.curriculum261_r6_pairs import FORMAL_BLOCK_OPTIONS
from rl_curriculum.curriculum261_r7_design import (
    _qualified_at_n,
    run_design_stage_r7,
)


def _corpus_result(qualified_by_n, semantics=True, density=True,
                   integrity=True, oracle=True):
    per_n = {}
    for n in ("10", "15", "20"):
        per_n[n] = {
            "n_formal_blocks": int(n),
            "gap_checks": {}, "d3_check": {}, "margin_checks": {},
            "formal_gate_simulation": {"gate_pass_probability": 0.95},
            "reasons": {
                "ordering_ok": n in qualified_by_n,
                "gaps_ge_3x_se_and_positive_rate": n in qualified_by_n,
                "d3_ge_2p5x_se": n in qualified_by_n,
                "margins_positive_and_d2_d3_ge_2p5x_se":
                    n in qualified_by_n,
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
    }


def test_qualified_requires_both_corpora_and_semantics():
    good = _corpus_result(("10", "15"))
    bad_n = _corpus_result(("20",))
    assert _qualified_at_n([good, good], 10) is True
    assert _qualified_at_n([good, bad_n], 10) is False
    assert _qualified_at_n([good, good], 20) is False
    sem_bad = _corpus_result(("10",), semantics=False)
    assert _qualified_at_n([sem_bad, good], 10) is False
    dens_bad = _corpus_result(("10",), density=False)
    assert _qualified_at_n([dens_bad, good], 10) is False


def _make_plan(tmp_path, monkeypatch, *, n_cand=2, floor=0.0):
    """合成锁定 plan(绕过真实 plan 文件;direct dict)。"""
    from rl_curriculum.curriculum261_r7_cue_eval import (
        cue_semantic_rule_identity,
    )

    from rl_curriculum.curriculum261_r7_param_pack import (
        r7_candidate_grid,
    )

    full_grid = r7_candidate_grid()
    ids = list(full_grid)[:max(1, n_cand)]
    grid = {cid: full_grid[cid] for cid in ids}
    return {
        "format": "cur261-r7-design-plan-v1",
        "iteration": "r7",
        "candidate_grid": {"candidates": grid},
        "design_data": {
            "blocks_per_candidate_per_corpus": 2,
            "corpora": ["ns_main", "ns_valid"],
        },
        "cue_semantic_contract": {
            "recall_floor": floor,
            "rule_identity": cue_semantic_rule_identity(),
            "audit_digest": "r7ca-" + "0" * 64,
            "p_contract": 0.937,
        },
        "code_identity": {},
    }


def _fake_blocks(n_blocks: int, seed0: int = 0):
    """轻量 fake MatchedBlock(本地合成;不生成真实数据)。"""
    import numpy as np
    import pandas as pd

    class _FakeEp:
        def __init__(self, df, hidden):
            self.df = df
            self.hidden = hidden

    blocks = []
    for bi in range(n_blocks):
        n = 40
        rng = np.random.default_rng(1000 + seed0 + bi)
        r1 = rng.normal(0.0, 0.002, size=n)
        cue = np.zeros(n, dtype=int)
        for t in (3, 9, 15):
            cue[t] = 1
            r1[t] = 0.015 + rng.normal(0.0, 0.002)
        df = pd.DataFrame({"%-ret-1": r1})
        hidden = pd.DataFrame({
            "wick_dir_state": np.zeros(n, dtype=int),
            "wick_width_state": np.zeros(n, dtype=int),
            "cue_dir": cue,
            "payoff_active": np.zeros(n, dtype=int),
            "payoff_dir": np.zeros(n, dtype=int),
            "active_gate_is_dir": np.zeros(n, dtype=int),
        })
        episodes = {r: {"A": _FakeEp(df.copy(), hidden.copy()),
                        "B": _FakeEp(df.copy(), hidden.copy())}
                    for r in ("D0", "D1", "D2", "D3")}
        blocks.append(SimpleNamespace(
            block_index=bi, episodes=episodes, pair_records={},
            attempt_log=None, shared_tape_digest="x",
            cross_rung_integrity={"pass": True}))
    return blocks


def test_shared_gate_fail_short_circuits_design(tmp_path, monkeypatch):
    """§19.1:任一 corpus shared gate FAIL → design FAIL,不进行
    candidate 选择(评估函数绝不被调用)。"""
    import rl_curriculum.curriculum261_r7_design as r7design

    plan = _make_plan(tmp_path, monkeypatch, floor=2.0)  # 不可能 floor
    monkeypatch.setattr(r7design, "verify_design_code_identity",
                        lambda p: {"pass": True, "drift": {}})
    monkeypatch.setattr(r7design, "require_r7_iteration_active",
                        lambda: None)
    monkeypatch.setattr(r7design, "mark_design_data_started",
                        lambda: None)
    eval_calls: list[str] = []
    monkeypatch.setattr(
        r7design, "_evaluate_candidate_matched_r7",
        lambda *a, **k: eval_calls.append(a[0]) or {})
    monkeypatch.setattr(
        r7design, "generate_matched_block_with_attempts",
        lambda ladder, *, namespace, block_index: _fake_blocks(1)[0])
    summary = run_design_stage_r7(tmp_path, plan, "r7dp-test")
    assert summary["pass"] is False
    assert summary["shared_gate_pass"] is False
    assert eval_calls == []  # 未进行 candidate 选择
    assert "不进行 candidate 选择" in summary["verdict"]
    # FAIL 路径清洁:无 pack 产物
    assert not (tmp_path / "r7_parameter_pack.json").exists()


def test_selection_min_n_then_maximin_then_distance(
        tmp_path, monkeypatch):
    """§14:最小 n → maximin → distance → id(合成选择段)。"""
    cand_results = {
        "cand_a": {
            "candidate_params": {}, "corpora": [],
            "qualified_by_block_count": {"10": True, "15": True,
                                         "20": True},
            "maximin_score_by_qualified_n": {"10": 3.0, "15": 3.5,
                                             "20": 4.0},
            "qualified_any": True,
            "param_distance_from_historical": 2.0},
        "cand_b": {
            "candidate_params": {}, "corpora": [],
            "qualified_by_block_count": {"10": True, "15": True,
                                         "20": True},
            "maximin_score_by_qualified_n": {"10": 5.0, "15": 6.0,
                                             "20": 9.0},
            "qualified_any": True,
            "param_distance_from_historical": 8.0},
        "cand_c_only20": {
            "candidate_params": {}, "corpora": [],
            "qualified_by_block_count": {"10": False, "15": False,
                                         "20": True},
            "maximin_score_by_qualified_n": {"20": 99.0},
            "qualified_any": True,
            "param_distance_from_historical": 0.1},
    }
    selected_n = None
    selected_id = None
    for n in FORMAL_BLOCK_OPTIONS:
        combos = [(cid, res) for cid, res in cand_results.items()
                  if res["qualified_by_block_count"][str(n)]]
        if combos:
            ranked = sorted(
                combos,
                key=lambda kv: (
                    -kv[1]["maximin_score_by_qualified_n"][str(n)],
                    kv[1]["param_distance_from_historical"], kv[0]))
            selected_id = ranked[0][0]
            selected_n = n
            break
    assert selected_n == 10
    assert selected_id == "cand_b"  # n=10 下 maximin 最高
    # 平局 → distance 最小
    cand_results["cand_b"]["maximin_score_by_qualified_n"]["10"] = 3.0
    for n in FORMAL_BLOCK_OPTIONS:
        combos = [(cid, res) for cid, res in cand_results.items()
                  if res["qualified_by_block_count"][str(n)]]
        if combos:
            ranked = sorted(
                combos,
                key=lambda kv: (
                    -kv[1]["maximin_score_by_qualified_n"][str(n)],
                    kv[1]["param_distance_from_historical"], kv[0]))
            assert ranked[0][0] == "cand_a"
            break


def test_shared_gate_not_repeated_per_candidate(tmp_path, monkeypatch):
    """§12:shared 指标每 corpus 只计算一次(不会把同一 FAIL 记到
    全部 candidate)。"""
    import rl_curriculum.curriculum261_r7_design as r7design

    plan = _make_plan(tmp_path, monkeypatch)
    monkeypatch.setattr(r7design, "verify_design_code_identity",
                        lambda p: {"pass": True, "drift": {}})
    monkeypatch.setattr(r7design, "require_r7_iteration_active",
                        lambda: None)
    monkeypatch.setattr(r7design, "mark_design_data_started",
                        lambda: None)

    gate_calls: list[str] = []

    def fake_gate(blocks_by_candidate, thresholds, **k):
        gate_calls.append(sorted(blocks_by_candidate)[0])
        return {"pass": True, "recall": {"bound": 0.95, "point": 0.96},
                "recall_floor": k.get("recall_floor_value", 0.0),
                "noncue_false_positive": {"bound": 0.001},
                "n_unique_positive_cues": 500,
                "cue_table_digests": {}}

    monkeypatch.setattr(r7design, "shared_cue_semantic_gate", fake_gate)
    synth_cue = {"per_rung": {
        rung: {"sides": {
            side: {
                "payoff_false_cue": {"bound": 0.02},
                "cue_precision": {"bound": 0.95},
            } for side in ("A", "B")},
            "pass": True} for rung in ("D0", "D1", "D2", "D3")}}
    eval_result = _corpus_result(("10", "15", "20"))
    eval_result.update({
        "candidate": "x", "corpus": "c", "n_blocks": 2,
        "block_corpus_summary": {
            "all_rung_pair_integrity_pass": True,
            "all_cross_rung_matching_pass": True,
            "block_contract": "r6bt", "n_blocks": 2,
            "distinct_shared_tape_count": 2},
        "block_attempt_stats": {}, "block_table": {
            "n_blocks": 2, "rows": []},
        "pair_table_rows": [], "difficulty_means": {},
        "density_gates": {
            r: {"median_reference_trades_per_episode": 10.0,
                "reference_long_label_rate": 0.02}
            for r in ("D0", "D1", "D2", "D3")},
        "semantics": {"cue_semantics_r7_cluster_aware": synth_cue},
        "scrambled_control_diagnostic": {"gaps": {}},
    })
    monkeypatch.setattr(
        r7design, "_evaluate_candidate_matched_r7",
        lambda *a, **k: dict(eval_result))
    monkeypatch.setattr(
        r7design, "generate_matched_block_with_attempts",
        lambda ladder, *, namespace, block_index: _fake_blocks(1)[0])
    # marginal guard 直接 PASS
    monkeypatch.setattr(
        r7design, "_run_independent_marginal_guard",
        lambda *a, **k: {"guard": {"pass": True}, "namespace": "ns",
                         "pairs_per_rung": 20,
                         "cue_semantics": {"pass": True}})
    monkeypatch.setattr(
        r7design, "_build_power_summary_r7",
        lambda *a, **k: {"weakest_binding_condition": "none"})
    summary = run_design_stage_r7(tmp_path, plan, "r7dp-test")
    assert summary["pass"] is True
    # 两个 corpus 各一次,共 2 次(不是 2×candidate 次)
    assert len(gate_calls) == 2
