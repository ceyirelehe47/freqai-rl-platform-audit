# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R14:audit-only 确定性噪声重放与 per-event K 落盘。

§11(Exact Noise Replay 与 Per-Event K):
- 与真实 generator 完全相同的 noise seed 派生路径(matched_tape 实例的
  derive_seed({**params, "_noise": "market"}, block_seed));
- 与 curriculum261_api.paired_noise() 完全相同的 RNG 调用顺序:
  逐 source bar t=1..(t+16<n) 依次消耗 3 个抽签
  standard_normal -> random(sign) -> integers(8,17)(gap);
- 相同 standard normal / sign / gap / 累加行为(col[t]+=amp,
  col[t+gap]-=amp)/尾部 break(t+16>=n 整体跳过);
- 对每个 audit episode:replayed_noise == actual_returns - pulse - payoff,
  最大绝对误差 <= 1e-12(反解基准 = curriculum261_r6_tape._reconstruct_eps,
  R6 冻结实现零修改复用);
- 对每个 positive cue event 落盘:block index / cue bar / primary 是否
  存在 / mirror source count K_actual / mirror source positions /
  effective sigma / actual noise / cue read / detected|missed;
  aggregate(K histogram、位置分布、recall)必须能从 event table 复算。

§10 修正后的 mirror candidate 边界(本模块为单一权威实现):
真实 paired_noise 只有 source_t + 16 < n 时才生成 source pair(source
最大值 n-17,不是 n-1),因此 cue bar t 的历史 mirror source 候选:
    lo = max(1, t - 16), hi = min(t - 8, n - 17)
只有 hi >= lo 时才存在候选。逐位置验证:实际 mirror sources 必须逐个
落在该候选集合内(exact bound check;零统计噪声)。

本模块为 audit-only:绝不修改 api/c2/r6_tape(历史 golden hash 锁定);
replay 通过与生成路径相同的派生函数重建 noise seed,不侵入生成器。
"""
from __future__ import annotations

from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_EPISODE_BARS,
    NOISE_PAIR_GAP_RANGE,
)
from rl_curriculum.curriculum261_c2 import (
    C2_REFERENCE_DEFAULTS,
    C2ContextGatingGenerator,
)
from rl_curriculum.curriculum261_r6_tape import (
    _reconstruct_eps,
)

#: 重放与反解对拍容差(§11:<= 1e-12)。
REPLAY_TOL = 1e-12

#: 尾部位置窗口(§12 tail-position 专项):最后 24 bars,覆盖全部
#: 受 n-17 上界影响的 cue 位置(n=288 时正 cue 位置至多 ~282)。
TAIL_WINDOW_BARS = 24


def mirror_candidate_positions(t: int, n: int) -> list[int]:
    """§10 修正后的 mirror source 候选位置(闭区间列表;空即无候选)。

    source s 存在 ⟺ s + NOISE_PAIR_GAP_RANGE[1] < n(即 s <= n-17);
    s 能命中 t ⟺ t - s ∈ [8, 16](即 s ∈ [t-16, t-8])。
    """
    lo = max(1, t - NOISE_PAIR_GAP_RANGE[1])
    hi = min(t - NOISE_PAIR_GAP_RANGE[0],
             n - NOISE_PAIR_GAP_RANGE[1] - 1)
    if hi < lo:
        return []
    return list(range(lo, hi + 1))


def mirror_candidate_count(t: int, n: int) -> int:
    return len(mirror_candidate_positions(t, n))


def primary_source_present(t: int, n: int) -> int:
    """bar t 是否作为配对首元素抽签(paired_noise 从 t=1 起,bar 0
    恒无噪声;source 存在 ⟺ 1 <= t 且 t + 16 < n)。"""
    return 1 if 1 <= t and t + NOISE_PAIR_GAP_RANGE[1] < n else 0


def derive_block_noise_seed(
        rung_params_by_rung: dict[str, dict[str, Any]], block_seed: int,
        rung: str = "D0", side: str = "A") -> int:
    """以与 generate_matched_block_once 完全相同的路径重建 noise seed。

    matched_tape 实例的 derive_seed 从流派生 payload 中剔除
    (alpha_bps, wick_kappa, cur261_rung, pair_variant...),因此 noise
    seed 只依赖 block_seed 与结构参数——与 candidate 数值无关(任意
    rung/side 派生出同一 noise seed;本函数默认 D0/A)。
    """
    gen = C2ContextGatingGenerator(matched_tape=True)
    rung_params = dict(rung_params_by_rung[rung])
    rung_params["cur261_rung"] = rung
    params = gen.base_params(dict(rung_params), side)
    return gen.derive_seed({**params, "_noise": "market"}, block_seed)


def replay_paired_noise(noise_seed: int, n: int,
                        vol: float) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """逐位复刻 paired_noise(rng, n, scale=const vol) 的调用顺序。

    返回 (eps 数组, source 记录列表)。source 记录含
    source_t / gap / sign / abs_g / mirror_t —— per-event K 的复算源。
    """
    rng = np.random.default_rng(int(noise_seed))
    col = np.zeros(n, dtype=np.float64)
    sources: list[dict[str, Any]] = []
    t = 1
    while t < n:
        if t + NOISE_PAIR_GAP_RANGE[1] >= n:
            break
        g = float(rng.standard_normal())
        sign = 1.0 if rng.random() < 0.5 else -1.0
        gap = int(rng.integers(NOISE_PAIR_GAP_RANGE[0],
                               NOISE_PAIR_GAP_RANGE[1] + 1))
        amp = sign * abs(g) * vol
        col[t] += amp
        col[t + gap] -= amp
        sources.append({
            "source_t": int(t), "gap": int(gap),
            "sign": float(sign), "abs_g": float(abs(g)),
            "mirror_t": int(t + gap)})
        t += 1
    return col, sources


def replay_block_noise(
        rung_params_by_rung: dict[str, dict[str, Any]], block_seed: int,
        n: int = int(CURRICULUM261_EPISODE_BARS),
) -> tuple[np.ndarray, list[dict[str, Any]], float]:
    """重放一个 matched block 的基础噪声(eps + sources + vol)。"""
    vol = float(rung_params_by_rung["D0"]["vol_bps"]) * 1e-4
    noise_seed = derive_block_noise_seed(
        rung_params_by_rung, block_seed)
    eps, sources = replay_paired_noise(noise_seed, n, vol)
    return eps, sources, vol


def cue_event_trace(
        episodes: dict[str, dict[str, Any]],
        rung_params_by_rung: dict[str, dict[str, Any]],
        block_seed: int, block_index: int,
        thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """单个 block 的 cue event trace + 重放完整性验证。

    输入 episodes = matched block 的 4 rung × A/B episode 表(只读
    canonical D0/A;跨 rung eps 一致性由 matched block integrity 合同
    保证)。返回:
    - events:每个 positive cue event 一行(block/cue_bar/primary/
      K_actual/mirror_positions/effective_sigma_bps/actual_noise/read/
      detected/bound_ok);
    - integrity:max_replay_abs_error(<=1e-12)、bound_violations(空即
      修正后 mirror 边界在每个事件上逐位置成立)。
    """
    thr = dict(C2_REFERENCE_DEFAULTS)
    if thresholds:
        thr.update(thresholds)
    cue_thr = float(thr["cue_thr"])
    n = int(CURRICULUM261_EPISODE_BARS)
    ep = episodes["D0"]["A"]
    cue = ep.hidden["cue_dir"].to_numpy()
    r1 = ep.df["%-ret-1"].to_numpy(dtype=np.float64)
    eps, sources, vol = replay_block_noise(
        rung_params_by_rung, block_seed, n)
    reconstructed = _reconstruct_eps(ep)
    max_err = float(np.max(np.abs(eps - reconstructed))) if n else 0.0
    source_set = {s["source_t"] for s in sources}
    mirror_index: dict[int, list[int]] = {}
    for s in sources:
        mirror_index.setdefault(s["mirror_t"], []).append(s["source_t"])
    events: list[dict[str, Any]] = []
    bound_violations: list[str] = []
    for t in np.flatnonzero(cue == 1).tolist():
        t = int(t)
        candidates = mirror_candidate_positions(t, n)
        mirrors = sorted(mirror_index.get(t, []))
        k_actual = len(mirrors)
        # exact bound check:实际 mirror 必须逐个落在修正后候选集合内
        bad = [s for s in mirrors if s not in set(candidates)]
        if bad or k_actual > len(candidates):
            bound_violations.append(
                f"block{block_index}:bar{t}:mirror sources {mirrors} "
                f"超出修正后候选集 {candidates}")
        primary = 1 if t in source_set else 0
        # primary 存在性必须与解析定义一致(source s 存在 ⟺ s+16<n)
        if primary != primary_source_present(t, n):
            bound_violations.append(
                f"block{block_index}:bar{t}:primary 存在性与 t+16<n 不符")
        m_expected = primary_source_present(t, n)
        sigma_eff = vol * float(np.sqrt(m_expected + k_actual))
        events.append({
            "block_index": int(block_index),
            "cue_bar": t,
            "primary_present": int(primary),
            "k_actual": int(k_actual),
            "mirror_positions": mirrors,
            "mirror_candidates": len(candidates),
            "effective_sigma_bps": float(sigma_eff * 1e4),
            "actual_noise": float(eps[t]),
            "cue_read": float(r1[t]),
            "detected": bool(r1[t] > cue_thr),
        })
    return {
        "block_index": int(block_index),
        "n_events": len(events),
        "events": events,
        "max_replay_abs_error": max_err,
        "replay_ok": bool(max_err <= REPLAY_TOL),
        "bound_violations": bound_violations,
        "bounds_ok": not bound_violations,
    }


def summarize_events(events: list[dict[str, Any]],
                     n: int = int(CURRICULUM261_EPISODE_BARS),
                     ) -> dict[str, Any]:
    """从 event table 复算全部 aggregate(K 分布/位置分布/recall)。

    §11 要求 aggregate 可从原始 event table 重算——本函数即复算路径
    (audit/semantic 语料的落盘 aggregate 必须与本函数输出一致)。
    """
    n_events = len(events)
    if n_events == 0:
        return {"n_events": 0, "recall": None}
    n_detected = sum(1 for e in events if e["detected"])
    pos_counts: dict[int, int] = {}
    k_counts: dict[int, int] = {}
    for e in events:
        pos_counts[e["cue_bar"]] = pos_counts.get(e["cue_bar"], 0) + 1
        k_counts[e["k_actual"]] = k_counts.get(e["k_actual"], 0) + 1
    tail_events = [e for e in events
                   if e["cue_bar"] >= n - TAIL_WINDOW_BARS]
    tail_detected = sum(1 for e in tail_events if e["detected"])
    return {
        "n_events": n_events,
        "n_detected": int(n_detected),
        "recall": float(n_detected / n_events),
        "cue_position_distribution": {
            str(t): c for t, c in sorted(pos_counts.items())},
        "k_histogram": {str(k): c for k, c in sorted(k_counts.items())},
        "k_mean": float(sum(e["k_actual"] for e in events) / n_events),
        "tail_window_bars": TAIL_WINDOW_BARS,
        "tail": {
            "n_events": len(tail_events),
            "n_detected": int(tail_detected),
            "recall": (float(tail_detected / len(tail_events))
                       if tail_events else None),
        },
    }


def trace_corpus(blocks_or_episodes: list[tuple[int, int, dict[str, Any]]],
                 rung_params_by_rung: dict[str, dict[str, Any]],
                 thresholds: dict[str, float] | None = None,
                 ) -> dict[str, Any]:
    """整语料 trace:(block_index, block_seed, episodes) 列表 -> 汇总。

    返回逐 block trace、全部 events(平铺)、完整性与复算 aggregate。
    """
    block_traces: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []
    for block_index, block_seed, episodes in blocks_or_episodes:
        tr = cue_event_trace(episodes, rung_params_by_rung, block_seed,
                             block_index, thresholds)
        block_traces.append({k: v for k, v in tr.items() if k != "events"})
        all_events.extend(tr["events"])
    agg = summarize_events(all_events)
    return {
        "n_blocks": len(block_traces),
        "block_traces": block_traces,
        "events": all_events,
        "aggregate": agg,
        "all_replay_ok": all(b["replay_ok"] for b in block_traces),
        "all_bounds_ok": all(b["bounds_ok"] for b in block_traces),
        "max_replay_abs_error": max(
            (b["max_replay_abs_error"] for b in block_traces), default=0.0),
    }


def matched_block_seed_of(block: Any) -> int:
    """从 MatchedBlock 的 attempt log 重建其 block seed。"""
    from rl_curriculum.curriculum261_r6_tape import derive261_block_seed

    log = block.attempt_log
    return derive261_block_seed(
        log.seed_namespace, int(log.block_index),
        int(log.selected_attempt or 0))


def trace_matched_blocks(
        blocks: list[Any],
        rung_params_by_rung: dict[str, dict[str, Any]],
        thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """MatchedBlock 列表(attempts-mode 产物)的语料 trace。"""
    return trace_corpus(
        [(int(b.block_index), matched_block_seed_of(b), b.episodes)
         for b in blocks],
        rung_params_by_rung, thresholds)
