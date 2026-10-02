# -*- coding: utf-8 -*-
"""R10 §36 测试:dedicated semantic corpus gate 与 candidate 语义(§15/
§16/§23/§26)。

覆盖:160 blocks 预注册与 unique-event 去重;block bootstrap LCB/UCB;
min_unique(3600)行为 + per-event K 完整 + noise replay 完整性;
共享语义与 candidate 选择解耦;independent marginal guard 的点护栏
(0.90,无小样本 LCB)。

semantic gate 测试使用真实 matched blocks(preplan_smoke_r10 namespace,
sentinel ladder)——trace/noise replay 必须走真实链路。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS
from rl_curriculum.curriculum261_r10_cue_contract import (
    MIN_UNIQUE_POSITIVE_CUES,
)
from rl_curriculum.curriculum261_r10_cue_eval import (
    R10_CUE_BOOTSTRAP_RESAMPLES,
    candidate_cue_semantics,
    cluster_bootstrap_rate,
    cue_semantic_rule_identity,
    independent_cue_semantics,
    semantic_cue_gate,
)

NS = "preplan_smoke_r10"
LADDER = {r: dict(p) for r, p in C2_RUNG_PARAMS.items()}


def _real_blocks(n_blocks: int, start: int = 200):
    from rl_curriculum.curriculum261_r6_tape import (
        generate_matched_block_with_attempts,
    )

    return [generate_matched_block_with_attempts(
        LADDER, namespace=NS, block_index=start + i)
        for i in range(n_blocks)]


# ------------------------------------------------ bootstrap
def test_bootstrap_lcb_ucb_sanity():
    hit_all = cluster_bootstrap_rate(
        [{"n": 10, "hit": 10}] * 5, side="lower")
    miss_all = cluster_bootstrap_rate(
        [{"n": 10, "hit": 0}] * 5, side="lower")
    assert hit_all["bound"] == 1.0 and miss_all["bound"] == 0.0
    mixed = cluster_bootstrap_rate(
        [{"n": 100, "hit": 95}, {"n": 100, "hit": 96},
         {"n": 100, "hit": 94}] * 13 + [{"n": 100, "hit": 93}],
        side="lower")
    assert mixed["point"] == pytest.approx(
        (95 * 13 + 96 * 13 + 94 * 13 + 93) / (40 * 100), rel=1e-9)
    assert mixed["bound"] < mixed["point"]
    ucb = cluster_bootstrap_rate(
        [{"n": 1000, "hit": 1}] * 40, side="upper")
    assert ucb["bound"] <= 0.01
    assert R10_CUE_BOOTSTRAP_RESAMPLES == 20000


def test_rule_identity_binds_160_and_3600():
    ident = cue_semantic_rule_identity()
    assert ident.startswith("r10csg-")
    assert MIN_UNIQUE_POSITIVE_CUES == 3600
    # 稳定
    assert cue_semantic_rule_identity() == ident


# ------------------------------------------------ semantic gate(真实链路)
def test_semantic_gate_real_blocks_dedup_and_k(tmp_path):
    blocks = _real_blocks(3)
    gate = semantic_cue_gate(blocks, LADDER, recall_floor_value=0.0,
                             min_unique_positive_cues=1, label="test")
    # 去重:unique positives = Σ per-block 正 cue(8 份重复观测只计 1 次)
    n_pos = sum(pb["n_positive"] for pb in map(
        lambda b: {"n_positive": int(np.count_nonzero(
            b.episodes["D0"]["A"].hidden["cue_dir"].to_numpy() == 1))},
        blocks))
    assert gate["n_unique_positive_cues"] == n_pos
    # 全部检查通过(floor=0/min=1 的 plumbing 口径)
    assert gate["checks"]["per_event_k_complete"]
    assert gate["checks"]["noise_replay_integrity"]
    assert gate["checks"]["canonical_consistency"]
    assert gate["checks"]["aggregate_recompute_ok"]
    assert gate["pass"]
    # event trace 完整字段
    assert len(gate["event_trace"]) == n_pos
    ev = gate["event_trace"][0]
    assert {"block_index", "cue_bar", "primary_present", "k_actual",
            "mirror_positions", "effective_sigma_bps", "actual_noise",
            "cue_read", "detected"} <= set(ev)


def test_semantic_gate_min_unique_3600_binding():
    blocks = _real_blocks(2)
    gate = semantic_cue_gate(blocks, LADDER, recall_floor_value=0.0,
                             min_unique_positive_cues=3600,
                             label="test")
    assert not gate["checks"]["n_unique_positive_cues_ge_min"]
    assert not gate["pass"]


def test_semantic_gate_recall_floor_binding():
    blocks = _real_blocks(3)
    gate_hi = semantic_cue_gate(blocks, LADDER, recall_floor_value=0.999,
                                min_unique_positive_cues=1)
    assert not gate_hi["checks"]["recall_lcb_ge_floor"]
    gate_lo = semantic_cue_gate(blocks, LADDER, recall_floor_value=0.0,
                                min_unique_positive_cues=1)
    assert gate_lo["checks"]["recall_lcb_ge_floor"]
    # LCB 与点估计关系
    assert gate_lo["recall"]["bound"] <= gate_lo["recall"]["point"]


# ------------------------------------------------ candidate/independent(fake 可)
def _fake_blocks(n_blocks: int, seed0: int = 0):
    class _FakeEp:
        def __init__(self, df, hidden):
            self.df = df
            self.hidden = hidden

    blocks = []
    for bi in range(n_blocks):
        n = 288
        rng = np.random.default_rng(1000 + seed0 + bi)
        r1 = rng.normal(0.0, 0.002, size=n)
        cue = np.zeros(n, dtype=int)
        for t in range(5, 5 + 26 * 10, 10):
            cue[t] = 1
            r1[t] = 0.015 if rng.random() < 0.95 else 0.002
        df = pd.DataFrame({"%-ret-1": r1})
        hidden = pd.DataFrame({
            "wick_dir_state": np.ones(n, dtype=int),
            "wick_width_state": np.ones(n, dtype=int),
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


def test_candidate_decoupling_no_shared_recall():
    """§16:candidate-specific 语义不含 shared recall(解耦)。"""
    cand = candidate_cue_semantics(_fake_blocks(2), "cand_test")
    flat = json.dumps(cand)
    assert "recall_lcb" not in flat and "recall_floor" not in flat
    for rung in ("D0", "D1", "D2", "D3"):
        for side in ("A", "B"):
            slot = cand["per_rung"][rung]["sides"][side]
            assert "payoff_false_cue" in slot
            assert "cue_precision" in slot


def test_independent_cue_semantics_point_recall_guard():
    """§26:marginal guard 的 recall 判据 = 点估计 ≥0.90(非 LCB)。"""
    recs = []
    i = 0
    for rung in ("D0", "D1", "D2", "D3"):
        for _ in range(4):
            ep = _fake_blocks(1, seed0=50 + i)[0].episodes["D0"]
            recs.append(SimpleNamespace(
                pair_index=i, rung=rung,
                episodes={"A": ep["A"], "B": ep["B"]}))
            i += 1
    res = independent_cue_semantics(recs, "cand", recall_floor_value=0.93)
    assert res["recall_gate_rule"].startswith("point >=")
    assert res["checks"]["point_recall_ge_absolute_floor"] == bool(
        res["recall"]["point"] >= 0.90)
    # precision/false-cue 已降级为诊断(不进 checks)
    assert "candidate_specific_rung_side" not in res["checks"]
    assert res["per_rung"]["D0"]["diagnostic_only"] is True
