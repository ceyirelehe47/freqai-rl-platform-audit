# -*- coding: utf-8 -*-
"""R8 §36 测试:design plan digest roundtrip 修复(§8)与 design 流程
(§15/§18/§26)——digest 不自引用、正式 loader roundtrip、不可覆盖、
semantic gate FAIL 短路、最小 n/maximin/tie-break、§8.4 异常→aborted、
matched 核心模块与 R7 baseline 身份一致。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from rl_curriculum.curriculum261_r6_pairs import FORMAL_BLOCK_OPTIONS
from rl_curriculum.curriculum261_r8_design import (
    _qualified_at_n,
    design_plan_digest_r8,
    load_locked_design_plan_r8,
    lock_design_plan_r8,
    run_design_stage_r8,
    verify_matched_core_identity_r7,
)


# ------------------------------------------------ §8 digest roundtrip
def _mini_plan() -> dict:
    from rl_curriculum.curriculum261_r8_cue_eval import (
        cue_semantic_rule_identity,
    )

    grid = {
        f"cand_{i}": {r: dict({"alpha_bps": 70.0 - i, "wick_kappa": 0.5})
                      for r in ("D0", "D1", "D2", "D3")}
        for i in range(3)}
    return {
        "format": "cur261-r8-design-plan-v1",
        "iteration": "r8",
        "candidate_grid": {"candidates": grid, "n_candidates": 3},
        "design_data": {
            "blocks_per_candidate_per_corpus": 2,
            "corpora": ["ns_main", "ns_valid"],
        },
        "semantic_corpora": {
            "blocks_per_corpus": 2,
            "namespaces": ["sem_main", "sem_valid"],
            "min_unique_positive_cues": 1,
        },
        "cue_semantic_contract": {
            "recall_floor": 0.0,
            "rule_identity": cue_semantic_rule_identity(),
            "audit_digest": "r8ca-" + "0" * 64,
            "p_contract": 0.937,
        },
        "code_identity": {},
    }


def test_digest_not_self_referential(tmp_path):
    """§8.1:digest 写入 payload 后复算仍一致(R7 缺陷的回归测试)。"""
    plan = _mini_plan()
    pre = design_plan_digest_r8(plan)
    path, digest = lock_design_plan_r8(tmp_path, plan)
    assert digest == pre
    # 正式 loader 复算成功(R7 在此处永远失败)
    loaded, d2 = load_locked_design_plan_r8(tmp_path)
    assert d2 == digest
    assert loaded["design_plan_digest"] == digest
    # 篡改 payload 任意字段 → 复算 mismatch(fail closed)
    tampered = json.loads(
        (tmp_path / "r8_design_plan.json").read_text(encoding="utf-8"))
    tampered["iteration"] = "r9"
    (tmp_path / "r8_design_plan.json").write_text(
        json.dumps(tampered), encoding="utf-8")
    with pytest.raises(RuntimeError, match="digest 复算不一致"):
        load_locked_design_plan_r8(tmp_path)


def test_existing_plan_not_overwritable(tmp_path):
    plan = _mini_plan()
    lock_design_plan_r8(tmp_path, plan)
    with pytest.raises(RuntimeError, match="禁止删除/覆盖/重锁"):
        lock_design_plan_r8(tmp_path, plan)


def test_matched_core_identity_matches_r7_baseline():
    ident = verify_matched_core_identity_r7()
    assert ident["pass"], ident
    assert set(ident["modules"]) == {
        "curriculum261_c2.py", "curriculum261_r6_tape.py",
        "curriculum261_r6_pairs.py"}


# ------------------------------------------------ 流程(fake 注入)
def _fake_blocks(n_blocks: int, seed0: int = 0):
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
            attempt_log=SimpleNamespace(
                block_index=bi, seed_namespace="ns",
                selected_attempt=0, attempts=[]),
            shared_tape_digest=f"x{bi}",
            cross_rung_integrity={"pass": True}))
    return blocks


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


def test_semantic_gate_fail_short_circuits_design(tmp_path, monkeypatch):
    """§15:任一 semantic corpus gate FAIL → design FAIL,不生成
    candidate blocks(评估函数绝不被调用)。"""
    import rl_curriculum.curriculum261_r8_design as r8design

    monkeypatch.setenv("CURRICULUM261_R8_LOCK_DIR", str(tmp_path))
    plan = _mini_plan()
    monkeypatch.setattr(r8design, "verify_design_code_identity",
                        lambda p: {"pass": True, "drift": {}})
    monkeypatch.setattr(r8design, "require_r8_iteration_active",
                        lambda: None)
    monkeypatch.setattr(r8design, "mark_design_data_started",
                        lambda: None)
    monkeypatch.setattr(r8design, "write_r8_iteration_aborted",
                        lambda reason: None)
    eval_calls: list[str] = []
    monkeypatch.setattr(
        r8design, "_evaluate_candidate_matched_r8",
        lambda *a, **k: eval_calls.append(a[0]) or {})
    monkeypatch.setattr(
        r8design, "generate_matched_block_with_attempts",
        lambda ladder, *, namespace, block_index: _fake_blocks(1)[0])
    # semantic gate 强制 FAIL(不可能 floor)
    monkeypatch.setattr(
        r8design, "semantic_cue_gate",
        lambda *a, **k: {"pass": False, "checks": {}, "n_blocks": 1,
                         "recall": {"bound": 0.1, "point": 0.2},
                         "recall_floor": k.get("recall_floor_value", 0.0),
                         "noncue_false_positive": {"bound": 0.001},
                         "n_unique_positive_cues": 10,
                         "event_trace": []})
    summary = run_design_stage_r8(tmp_path, plan, "r8dp-test")
    assert summary["pass"] is False
    assert summary["semantic_gate_pass"] is False
    assert eval_calls == []  # 未进行 candidate 评估
    assert "不生成" in summary["verdict"]
    # FAIL 路径清洁:无 pack 产物
    assert not (tmp_path / "r8_parameter_pack.json").exists()


def test_design_stage_exception_writes_aborted(tmp_path, monkeypatch):
    """§8.4:plan 锁定后任何异常 → aborted(一次性硬规则)。"""
    import rl_curriculum.curriculum261_r8_design as r8design

    monkeypatch.setenv("CURRICULUM261_R8_LOCK_DIR", str(tmp_path))
    plan = _mini_plan()
    monkeypatch.setattr(r8design, "verify_design_code_identity",
                        lambda p: {"pass": True, "drift": {}})
    monkeypatch.setattr(r8design, "require_r8_iteration_active",
                        lambda: None)
    monkeypatch.setattr(r8design, "mark_design_data_started",
                        lambda: (_ for _ in ()).throw(
                            RuntimeError("started ledger 异常")))
    aborted: list[str] = []
    monkeypatch.setattr(r8design, "write_r8_iteration_aborted",
                        lambda reason: aborted.append(reason))
    with pytest.raises(RuntimeError, match="started ledger 异常"):
        run_design_stage_r8(tmp_path, plan, "r8dp-test")
    assert len(aborted) == 1 and "执行异常" in aborted[0]


def test_selection_min_n_then_maximin_then_distance():
    """§18:最小 n → maximin → distance → id(合成选择段)。"""
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
