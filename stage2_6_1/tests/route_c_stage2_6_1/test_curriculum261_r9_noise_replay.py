# -*- coding: utf-8 -*-
"""R9 §36 测试:Exact Noise Replay 与修正后 Mirror 边界(§10/§11)。

覆盖:
- mirror 候选上界逐位置(episode 开头/内部/n-17/n-16/最后 8-16/
  最后一根)与真实 noise replay 对拍;
- primary 存在边界(t+16<n);
- exact RNG replay 逐位一致(与真实 generator 生成路径对拍 ≤1e-12);
- overlapping pairs(累加而非赋值);
- per-event K 提取与 aggregate 复算。
"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_EPISODE_BARS,
    NOISE_PAIR_GAP_RANGE,
    paired_noise,
)
from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS
from rl_curriculum.curriculum261_r6_tape import (
    derive261_block_seed,
    generate_matched_block_once,
)
from rl_curriculum.curriculum261_r9_noise_replay import (
    REPLAY_TOL,
    cue_event_trace,
    derive_block_noise_seed,
    mirror_candidate_count,
    mirror_candidate_positions,
    primary_source_present,
    replay_block_noise,
    replay_paired_noise,
    summarize_events,
)

N = int(CURRICULUM261_EPISODE_BARS)
NS = "preplan_smoke_r9"
LADDER = {r: dict(p) for r, p in C2_RUNG_PARAMS.items()}


# ------------------------------------------------ mirror 边界(§10)
def test_mirror_bound_episode_start_and_interior():
    # t=1..8:hi=t-8<=0 → 无候选(source 至少在 t-8 且 >=1)
    for t in range(0, 9):
        assert mirror_candidate_positions(t, N) == []
    # 内部位置 t ∈ [17, 271]:满窗 9 个候选(上界不受 n-17 影响)
    for t in (17, 100, 200, 271):
        assert mirror_candidate_count(t, N) == 9
        pos = mirror_candidate_positions(t, N)
        assert pos == list(range(t - 16, t - 8 + 1))


def test_mirror_bound_tail_positions_n_minus_17_cap():
    # 修正点:hi = min(t-8, n-17) —— 尾部候选被 source 存在性上界封顶
    assert mirror_candidate_count(272, N) == 9   # lo=256, hi=264 → 9
    assert mirror_candidate_count(279, N) == 9   # lo=263, hi=271 → 9
    assert mirror_candidate_count(280, N) == 8   # lo=264, hi=271 → 8
    assert mirror_candidate_count(281, N) == 7   # lo=265, hi=271 → 7
    assert mirror_candidate_count(282, N) == 6
    assert mirror_candidate_count(283, N) == 5
    assert mirror_candidate_count(284, N) == 4
    assert mirror_candidate_count(286, N) == 2
    assert mirror_candidate_positions(287, N) == [271]  # lo=271, hi=271
    assert mirror_candidate_positions(288, N) == []  # lo=272 > hi=271


def test_mirror_bound_r7_bug_would_overcount():
    """R7 的 min(hi, n-1) 在 t>=280 高估 C(t);修正后必须更小。"""
    for t in range(280, 288):
        r7_style = min(t - NOISE_PAIR_GAP_RANGE[0], N - 1) - max(
            1, t - NOISE_PAIR_GAP_RANGE[1]) + 1
        assert mirror_candidate_count(t, N) < r7_style, t


def test_primary_present_boundary():
    # source 存在 ⟺ t + 16 < n(n=288 → 最后 source = 271)
    assert primary_source_present(271, N) == 1
    assert primary_source_present(272, N) == 0
    assert primary_source_present(1, N) == 1
    assert primary_source_present(0, N) == 0


# ------------------------------------------------ exact replay(§11)
def test_replay_paired_noise_bit_identical_to_real_call():
    """与真实 paired_noise() 完全相同的 RNG 调用顺序 → 逐位一致。"""
    vol = 0.0020
    for seed in (11, 202, 3003):
        noise_seed = derive_block_noise_seed(LADDER, seed)
        replayed, sources = replay_paired_noise(noise_seed, N, vol)
        real = paired_noise(
            np.random.default_rng(noise_seed), N,
            scale=np.full(N, vol))
        assert np.max(np.abs(replayed - real)) == 0.0  # 逐位一致
        # source 记录与 break 边界一致:全部 source <= n-17
        assert all(s["source_t"] <= N - 17 for s in sources)
        assert all(8 <= s["gap"] <= 16 for s in sources)
        assert all(s["mirror_t"] == s["source_t"] + s["gap"]
                   for s in sources)


def test_replay_overlapping_pairs_accumulate():
    """配对元素重合时累加(非赋值)——构造确定性小样本验证。"""
    eps, sources = replay_paired_noise(20261008, 60, 0.002)
    col = np.zeros(60)
    for s in sources:
        amp = s["sign"] * s["abs_g"] * 0.002
        col[s["source_t"]] += amp
        col[s["mirror_t"]] -= amp
    assert np.array_equal(eps, col)


def test_replay_block_matches_real_generator_episodes():
    """完整链路:block seed → 真实生成 → replay 反解对拍 ≤1e-12。"""
    for bi in range(2):
        block_seed = derive261_block_seed(NS, bi + 50, 0)
        episodes = generate_matched_block_once(LADDER, block_seed, NS)
        eps, _sources, _vol = replay_block_noise(LADDER, block_seed, N)
        from rl_curriculum.curriculum261_r6_tape import _reconstruct_eps

        for rung in ("D0", "D3"):
            for side in ("A", "B"):
                rec = _reconstruct_eps(episodes[rung][side])
                err = float(np.max(np.abs(eps - rec)))
                assert err <= REPLAY_TOL, (bi, rung, side, err)


def test_cue_event_trace_k_and_bounds_on_real_blocks():
    """per-event K 提取 + 修正边界逐事件成立 + aggregate 复算。"""
    events = []
    for bi in range(3):
        block_seed = derive261_block_seed(NS, bi + 60, 0)
        episodes = generate_matched_block_once(LADDER, block_seed, NS)
        tr = cue_event_trace(episodes, LADDER, block_seed, bi)
        assert tr["replay_ok"], tr["max_replay_abs_error"]
        assert tr["bounds_ok"], tr["bound_violations"]
        events.extend(tr["events"])
    agg = summarize_events(events)
    assert agg["n_events"] == len(events)
    assert agg["n_detected"] == sum(1 for e in events if e["detected"])
    # K 一致性:k_actual == len(mirror_positions) 且候选数 == 公式
    for e in events:
        assert e["k_actual"] == len(e["mirror_positions"])
        assert e["mirror_candidates"] == mirror_candidate_count(
            e["cue_bar"], N)
        assert all(s in mirror_candidate_positions(e["cue_bar"], N)
                   for s in e["mirror_positions"])
        # effective sigma = vol·sqrt(m+K)
        m = primary_source_present(e["cue_bar"], N)
        assert e["effective_sigma_bps"] == pytest.approx(
            20.0 * float(np.sqrt(m + e["k_actual"])), rel=1e-9)


def test_summarize_events_tail_window():
    evs = [
        {"cue_bar": 5, "k_actual": 1, "detected": True},
        {"cue_bar": N - 1, "k_actual": 0, "detected": False},
        {"cue_bar": N - 24, "k_actual": 2, "detected": True},
        {"cue_bar": N - 25, "k_actual": 1, "detected": True},
    ]
    agg = summarize_events(evs)
    assert agg["tail"]["n_events"] == 2  # N-1 与 N-24 在窗口内
    assert agg["tail"]["n_detected"] == 1
    assert agg["k_histogram"] == {"0": 1, "1": 2, "2": 1}
