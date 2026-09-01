# -*- coding: utf-8 -*-
"""R7 §34 测试:Unique Cue Events 与 Cluster Semantics(§8/§10/§11)。

- 八份重复 cue 只计一次(4 rung × A/B → 1 unique event);
- canonical observation 一致性:跨 rung cue input 不一致 => FAIL;
- cluster bootstrap:全命中 LCB=1/全不命中 LCB=0;重采样不拆 block;
  事件重复 8 份不得缩小 CI;
- payoff false-cue/precision 的 cluster bound 机械裁决;
- independent 语料(pair cluster)evaluator 跑通。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rl_curriculum.curriculum261_r7_cue_eval import (
    candidate_cue_semantics,
    canonical_cue_observations,
    cluster_bootstrap_rate,
    cue_semantic_rule_identity,
    independent_cue_semantics,
    shared_cue_semantic_gate,
)


class _FakeEp:
    def __init__(self, df, hidden):
        self.df = df
        self.hidden = hidden


def _fake_block(block_index: int, n: int = 40, *,
                positive_cues=(3, 9, 15), mutate_rung_read=False):
    """合成 matched block:四 rung × A/B 共享 cue 表与读数。"""
    rng = np.random.default_rng(1000 + block_index)
    r1 = rng.normal(0.0, 0.002, size=n)
    cue = np.zeros(n, dtype=int)
    for t in positive_cues:
        cue[t] = 1
        r1[t] = 0.015 + rng.normal(0.0, 0.002)  # 正 cue 读数
    cue[20] = -1  # 负 cue
    r1[20] = -0.015
    active = np.zeros(n, dtype=int)
    for t in positive_cues:
        active[t + 1] = 1  # payoff bar
    df = pd.DataFrame({"%-ret-1": r1})
    hidden = pd.DataFrame({
        "wick_dir_state": np.zeros(n, dtype=int),
        "wick_width_state": np.zeros(n, dtype=int),
        "cue_dir": cue,
        "payoff_active": active,
        "payoff_dir": np.zeros(n, dtype=int),
        "active_gate_is_dir": np.zeros(n, dtype=int),
    })
    episodes = {}
    for rung in ("D0", "D1", "D2", "D3"):
        sides = {}
        for side in ("A", "B"):
            ep_df = df.copy()
            if mutate_rung_read and rung == "D2":
                vals = ep_df["%-ret-1"].to_numpy().copy()
                vals[positive_cues[0]] += 0.01  # 破坏一致性
                ep_df = pd.DataFrame({"%-ret-1": vals})
            sides[side] = _FakeEp(ep_df, hidden.copy())
        episodes[rung] = sides
    from types import SimpleNamespace

    return SimpleNamespace(
        block_index=block_index, episodes=episodes,
        pair_records={}, attempt_log=None, shared_tape_digest="x",
        cross_rung_integrity={"pass": True})


def test_unique_event_dedup_eight_replicas_count_once():
    """八份重复观测只计一次:3 正 cue → n_unique=3,不是 24。"""
    blocks = [_fake_block(0), _fake_block(1)]
    obs = canonical_cue_observations(blocks)
    assert obs["violations"] == []
    assert all(pb["n_positive"] == 3 for pb in obs["per_block"])
    assert all(pb["n_cues"] == 4 for pb in obs["per_block"])


def test_cross_rung_inconsistency_fails_block():
    """跨 rung cue detection input 不一致 => violations 非空。"""
    blocks = [_fake_block(0, mutate_rung_read=True)]
    obs = canonical_cue_observations(blocks)
    assert obs["violations"], "D2 读数被破坏必须被检出"


def test_cluster_bootstrap_bounds_mechanical():
    """全命中 LCB=1;全不命中 LCB=0;部分命中 LCB < point < 1。"""
    hit_all = cluster_bootstrap_rate(
        [{"n": 10, "hit": 10}] * 8, side="lower")
    assert hit_all["bound"] == 1.0
    miss_all = cluster_bootstrap_rate(
        [{"n": 10, "hit": 0}] * 8, side="lower")
    assert miss_all["bound"] == 0.0
    part = cluster_bootstrap_rate(
        [{"n": 10, "hit": 9}, {"n": 10, "hit": 8}] * 4, side="lower")
    assert part["point"] == pytest.approx(0.85)
    assert part["bound"] < part["point"]
    upper = cluster_bootstrap_rate(
        [{"n": 100, "hit": 1}, {"n": 100, "hit": 3}] * 3, side="upper")
    assert upper["point"] == pytest.approx(0.02)
    assert upper["bound"] > upper["point"]
    degenerate = cluster_bootstrap_rate([], side="lower")
    assert degenerate["degenerate"] and degenerate["bound"] == 0.0


def test_cluster_resampling_does_not_split_blocks():
    """cluster 重采样不拆 block:单 cluster 时重分布退化为该 cluster
    的比率(LCB=point;没有任何 within-cluster 方差被注入)。"""
    single = cluster_bootstrap_rate(
        [{"n": 8, "hit": 6}], side="lower")
    assert single["point"] == pytest.approx(0.75)
    assert single["bound"] == pytest.approx(0.75)


def test_duplicated_events_do_not_shrink_ci():
    """把同一事件的 8 份重复当独立样本会虚假缩小 CI——cluster 版
    必须保持 CI 由 cluster 数决定(重复观测并入同 cluster 不改变
    bound 的数量级)。"""
    per_block = [{"n": 12, "hit": 11}, {"n": 12, "hit": 10},
                 {"n": 12, "hit": 11}, {"n": 12, "hit": 9}]
    clustered = cluster_bootstrap_rate(per_block, side="lower")
    # naive:同一 4 block × 8 份重复被当独立
    naive_blocks = [dict(b) for b in per_block for _ in range(8)]
    naive = cluster_bootstrap_rate(naive_blocks, side="lower")
    # naive 的 cluster 数 8 倍 -> bootstrap_se 更小 -> LCB 更高
    assert naive["bootstrap_se"] < clustered["bootstrap_se"]
    assert naive["bound"] > clustered["bound"]


def test_shared_gate_and_candidate_semantics_synthetic():
    """shared gate:canonical 一致 + 去重 + floor 裁决;candidate:
    payoff fc / precision 的 UCB/LCB 机械裁决。"""
    blocks = {"cand_a": [_fake_block(i) for i in range(6)]}
    gate = shared_cue_semantic_gate(
        blocks, {"cue_thr": 0.0105, "wick_dir_thr": 0.0,
                 "wick_width_thr": 0.0120},
        recall_floor_value=0.5, min_unique_positive_cues=10)
    # 合成读数 ~N(0.015, 0.002) > 0.0105 的概率 ≈ Φ(2.22)≈0.987
    assert gate["n_unique_positive_cues"] == 18
    assert gate["recall"]["point"] > 0.5
    assert gate["pass"] is True
    strict = shared_cue_semantic_gate(
        blocks, {"cue_thr": 0.0105}, recall_floor_value=1.5,
        min_unique_positive_cues=10)
    assert strict["pass"] is False  # floor 不可能满足
    assert strict["checks"]["recall_lcb_ge_floor"] is False

    cand = candidate_cue_semantics(blocks["cand_a"], "cand_a")
    assert cand["pass"] in (True, False)
    assert set(cand["per_rung"]) == {"D0", "D1", "D2", "D3"}
    for rung in ("D0", "D1", "D2", "D3"):
        for side in ("A", "B"):
            entry = cand["per_rung"][rung]["sides"][side]
            assert entry["payoff_false_cue"]["n_events"] > 0
            assert entry["cue_precision"]["n_events"] > 0


def test_independent_cue_semantics_runs(monkeypatch):
    """independent 语料(pair cluster)evaluator:小规模真实生成。"""
    from rl_curriculum.curriculum261_pairs import generate_pair
    from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS

    records = [generate_pair("c2_context", rung, 0,
                             namespace="preplan_smoke_r7")
               for rung in ("D0", "D1", "D2", "D3")]
    result = independent_cue_semantics(records, "test")
    # 覆盖不全的语料被拒绝(D0-D3 全覆盖是合同)
    with pytest.raises(RuntimeError):
        independent_cue_semantics(records[:2], "test")
    assert result["cluster_unit"] == "independent_pair"
    assert result["canonical"] == "A"
    assert result["violations"] == []
    assert result["n_unique_positive_cues"] > 0
    # recall LCB 在合理区间(固有检出率 ~0.94-0.99)
    assert 0.5 < result["recall"]["point"] <= 1.0
    assert isinstance(result["pass"], bool)


def test_rule_identity_stable():
    d = cue_semantic_rule_identity()
    assert d.startswith("r7csg-") and len(d) == 6 + 64
    assert cue_semantic_rule_identity() == d
