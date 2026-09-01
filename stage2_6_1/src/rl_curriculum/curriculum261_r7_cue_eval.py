# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R7:cluster-aware cue 语义评估器(unique event)。

实现 C2CueDetectionSemanticContract-v1 的统计侧(§8/§10/§11):

- unique cue event:matched block 内 4 rung × A/B 共享 cue 表,
  同一 (block_index, cue_bar_index) 只计一次;canonical observation
  = D0/A(冻结);跨 rung/variant 的 cue detection input 不一致 =>
  matched block integrity FAIL(violations 非空);
- cluster unit = matched block:block-cluster bootstrap 重采样完整
  block(cluster 内事件相关,cluster 间独立),单侧 95% LCB/UCB;
- candidate-independent(§8.3;每 corpus 一次,不随 candidate 变化——
  matched tape 合同保证跨 candidate 的 cue 表/pulse/噪声逐位一致):
  positive cue recall / non-cue false-positive / unique cue count /
  block-level cue-event 分布;
- candidate-specific(§8.4;按 candidate/rung/side):payoff-bar
  false-cue UCB / cue precision LCB / payoff-cue confusion。

禁止把同一事件当独立样本重复计数(4 rung × A/B = 8 份重复观测
只计 1 个 unique event),禁止以拆 rung/variant 缩小 CI。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_c2 import C2_REFERENCE_DEFAULTS
from rl_curriculum.curriculum261_r6_tape import MatchedBlock
from rl_curriculum.curriculum261_r7_cue_contract import (
    C2_CUE_PRECISION_MIN,
    C2_NON_CUE_FALSE_POSITIVE_MAX,
    C2_PAYOFF_BAR_FALSE_CUE_MAX,
    CUE_CANONICAL_OBSERVATION,
    CUE_CLUSTER_UNIT,
    CUE_LCB_CONFIDENCE,
    MIN_UNIQUE_POSITIVE_CUES,
)

#: cluster bootstrap 配置(冻结;design/calibration/holdout/final 共用)。
R7_CUE_BOOTSTRAP_RESAMPLES = 20000
R7_CUE_BOOTSTRAP_SEED = 20260925

_READ_TOL = 1e-12


def _readings(episodes: dict[str, dict[str, Any]], t: int) -> list[float]:
    return [float(episodes[r][s].df["%-ret-1"].to_numpy(
        dtype=np.float64)[t])
        for r in ("D0", "D1", "D2", "D3") for s in ("A", "B")]


def canonical_cue_observations(
        blocks: list[MatchedBlock],
        thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """提取 canonical(D0/A)cue 表与 unique cue event 观测。

    返回:
    - violations:跨 rung/variant cue detection input 不一致清单
      (非空 => matched block integrity FAIL);
    - per_block:每 block 的 {t, read, is_positive, over};
    - noncue:每 block 的 non-cue bar (n, over) 计数(canonical;
      non-cue 且 non-payoff bar 的读数跨 rung/variant 逐位一致,
      只计 canonical 一份);
    - cue_table_digest:cue 表身份(跨 candidate 一致性验证用)。
    """
    thr = dict(C2_REFERENCE_DEFAULTS)
    if thresholds:
        thr.update(thresholds)
    cue_thr = float(thr["cue_thr"])
    violations: list[str] = []
    per_block: list[dict[str, Any]] = []
    noncue_blocks: list[dict[str, int]] = []
    digests: list[str] = []
    for blk in blocks:
        episodes = blk.episodes
        ep = episodes[CUE_CANONICAL_OBSERVATION[0]][
            CUE_CANONICAL_OBSERVATION[1]]
        cue_dir = ep.hidden["cue_dir"].to_numpy()
        r1 = ep.df["%-ret-1"].to_numpy(dtype=np.float64)
        for rung in ("D0", "D1", "D2", "D3"):
            for side in ("A", "B"):
                other = episodes[rung][side]
                if not np.array_equal(
                        other.hidden["cue_dir"].to_numpy(), cue_dir):
                    violations.append(
                        f"block{blk.block_index}:{rung}/{side}:"
                        "cue_dir 表与 canonical 不一致")
        events = []
        for t in np.flatnonzero(cue_dir != 0).tolist():
            reads = _readings(episodes, t)
            read = reads[0]
            if max(reads) - min(reads) > _READ_TOL:
                violations.append(
                    f"block{blk.block_index}:bar{t}:cue detection "
                    f"input 跨 rung/variant 不一致(max-min="
                    f"{max(reads) - min(reads):.3e})")
            events.append({
                "t": int(t), "read": float(read),
                "is_positive": bool(cue_dir[t] == 1),
                "over": bool(read > cue_thr)})
        active = ep.hidden["payoff_active"].to_numpy()
        sel = (cue_dir == 0) & (active == 0)
        noncue_blocks.append({
            "n": int(sel.sum()),
            "hit": int((sel & (r1 > cue_thr)).sum())})
        per_block.append({
            "block_index": int(blk.block_index),
            "events": events,
            "n_cues": int(len(events)),
            "n_positive": int(sum(e["is_positive"] for e in events))})
        digests.append(hashlib.sha256(
            json.dumps({
                "block_index": int(blk.block_index),
                "cue_dir": [int(x) for x in cue_dir],
            }, sort_keys=True).encode("utf-8")).hexdigest())
    cue_table_digest = "r7ct-" + hashlib.sha256(
        "".join(digests).encode("utf-8")).hexdigest()
    return {
        "canonical": "/".join(CUE_CANONICAL_OBSERVATION),
        "thresholds": thr,
        "violations": violations,
        "per_block": per_block,
        "noncue_blocks": noncue_blocks,
        "cue_table_digest": cue_table_digest,
    }


def cluster_bootstrap_rate(
        per_block: list[dict[str, int]], *,
        side: str = "lower",
        confidence: float = CUE_LCB_CONFIDENCE,
        n_boot: int = R7_CUE_BOOTSTRAP_RESAMPLES,
        seed: int = R7_CUE_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """block-cluster bootstrap 的比率单侧界。

    per_block: [{"n": 事件数, "hit": 命中数}, ...](cluster=block;
    重采样内 pooled 聚合)。side="lower" 返回 one-sided (1-α) LCB
    (即重采样分布的 α 分位);side="upper" 返回 UCB(1-α 分位)。
    """
    n = len(per_block)
    ns = np.array([b["n"] for b in per_block], dtype=np.int64)
    hits = np.array([b["hit"] for b in per_block], dtype=np.int64)
    total_n = int(ns.sum())
    total_hit = int(hits.sum())
    point = (total_hit / total_n) if total_n else 0.0
    alpha = 1.0 - confidence
    if total_n == 0 or n == 0:
        return {"point": point, "n_events": total_n,
                "n_clusters": n, "side": side,
                "bound": (0.0 if side == "lower" else 1.0),
                "n_boot": 0, "degenerate": True}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot = hits[idx].sum(axis=1) / np.maximum(ns[idx].sum(axis=1), 1)
    q = float(alpha * 100) if side == "lower" else float(
        confidence * 100)
    bound = float(np.percentile(boot, q))
    return {
        "point": float(point), "n_events": total_n, "n_clusters": n,
        "side": side, "bound": bound, "n_boot": n_boot,
        "degenerate": False,
        "bootstrap_se": float(np.std(boot, ddof=1)),
    }


def shared_cue_semantic_gate(
        blocks_by_candidate: dict[str, list[MatchedBlock]],
        thresholds: dict[str, float] | None = None,
        recall_floor_value: float = 0.0,
        min_unique_positive_cues: int = MIN_UNIQUE_POSITIVE_CUES,
) -> dict[str, Any]:
    """§19.1 shared cue semantic gate(每 design corpus 一次)。

    candidate-independent 指标只在第一个 candidate 的 blocks 上计算
    (matched tape 合同保证跨 candidate cue 表/pulse/噪声逐位一致;
    以下显式对比 cue_table_digest 验证该前提)。任一条件 FAIL =>
    整个 R7 design FAIL,不进行 candidate 选择。
    """
    if not blocks_by_candidate:
        raise RuntimeError("shared gate 需要至少一个 candidate 的 blocks")
    ordered = sorted(blocks_by_candidate)
    ref_id = ordered[0]
    obs = canonical_cue_observations(blocks_by_candidate[ref_id],
                                     thresholds)
    # 跨 candidate cue 表一致性(合同前提的显式验证)
    cross_digests = {ref_id: obs["cue_table_digest"]}
    for cid in ordered[1:]:
        other = canonical_cue_observations(blocks_by_candidate[cid],
                                           thresholds)
        cross_digests[cid] = other["cue_table_digest"]
    digests_match = len(set(cross_digests.values())) == 1

    pos_blocks = []
    for pb in obs["per_block"]:
        pos = [e for e in pb["events"] if e["is_positive"]]
        pos_blocks.append({
            "n": len(pos),
            "hit": sum(1 for e in pos if e["over"])})
    n_unique_positive = sum(b["n"] for b in pos_blocks)
    recall = cluster_bootstrap_rate(pos_blocks, side="lower")
    noncue = cluster_bootstrap_rate(obs["noncue_blocks"], side="upper")
    n_pos_dist = [pb["n_positive"] for pb in obs["per_block"]]
    checks = {
        "canonical_consistency": not obs["violations"],
        "cross_candidate_cue_table_identical": digests_match,
        "recall_lcb_ge_floor": bool(
            recall["bound"] >= recall_floor_value),
        "noncue_fp_ucb_le_max": bool(
            noncue["bound"] <= C2_NON_CUE_FALSE_POSITIVE_MAX),
        "n_unique_positive_cues_ge_min": bool(
            n_unique_positive >= min_unique_positive_cues),
        "coverage_complete": bool(
            n_unique_positive == sum(
                b["n"] for b in pos_blocks)),
    }
    return {
        "format": "cur261-r7-shared-cue-semantic-gate-v1",
        "computed_on": ref_id,
        "cross_candidate_cue_table_digests": cross_digests,
        "canonical": obs["canonical"],
        "cluster_unit": CUE_CLUSTER_UNIT,
        "violations": obs["violations"],
        "n_unique_positive_cues": n_unique_positive,
        "min_unique_positive_cues": min_unique_positive_cues,
        "unique_positive_cues_per_block": {
            "min": int(min(n_pos_dist)), "median": float(
                np.median(n_pos_dist)),
            "max": int(max(n_pos_dist))},
        "recall": recall,
        "recall_floor": recall_floor_value,
        "noncue_false_positive": {
            **noncue, "max": C2_NON_CUE_FALSE_POSITIVE_MAX},
        "checks": checks,
        "pass": bool(all(checks.values())),
    }


def candidate_cue_semantics(
        blocks: list[MatchedBlock], candidate_id: str,
        thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """§19.2/§11 candidate-specific cue 语义(按 rung × side)。

    - payoff-bar false-cue:block-cluster bootstrap UCB;每 rung × side
      单独验证(D0-D3 全部单独通过;不得用 D3 稀释 D0);
    - cue precision:同 cluster LCB;每 rung × side 单独验证;
    - payoff/cue confusion 计数(报告性)。
    cue bar 的 detection input 跨 rung/variant 逐位一致(unique event
    去重合法);payoff bar 读数 = eps + alpha·gate·d 依赖
    alpha/gate/rung/side,各自是独立事件、同 block 内相关(cluster)。
    """
    thr = dict(C2_REFERENCE_DEFAULTS)
    if thresholds:
        thr.update(thresholds)
    cue_thr = float(thr["cue_thr"])
    per_rung: dict[str, Any] = {}
    all_ok = True
    for rung in ("D0", "D1", "D2", "D3"):
        per_side: dict[str, Any] = {}
        for side in ("A", "B"):
            payoff_blocks: list[dict[str, int]] = []
            precision_blocks: list[dict[str, int]] = []
            confusion = {"cue_pos_over": 0, "cue_neg_over": 0,
                         "payoff_over_true": 0, "payoff_over": 0,
                         "noncue_over": 0}
            for blk in blocks:
                ep = blk.episodes[rung][side]
                cue = ep.hidden["cue_dir"].to_numpy()
                active = ep.hidden["payoff_active"].to_numpy()
                r1 = ep.df["%-ret-1"].to_numpy(dtype=np.float64)
                over = r1 > cue_thr
                act = active == 1
                payoff_blocks.append({
                    "n": int(act.sum()),
                    "hit": int((act & over).sum())})
                precision_blocks.append({
                    "n": int(over.sum()),
                    "hit": int((over & (cue == 1)).sum())})
                confusion["cue_pos_over"] += int(
                    (over & (cue == 1)).sum())
                confusion["cue_neg_over"] += int(
                    (over & (cue == -1)).sum())
                confusion["payoff_over"] += int((act & over).sum())
                confusion["noncue_over"] += int(
                    (over & (cue == 0) & ~act).sum())
            fc = cluster_bootstrap_rate(payoff_blocks, side="upper")
            prec = cluster_bootstrap_rate(precision_blocks,
                                          side="lower")
            ok = bool(fc["bound"] <= C2_PAYOFF_BAR_FALSE_CUE_MAX
                      and prec["bound"] >= C2_CUE_PRECISION_MIN)
            all_ok = all_ok and ok
            per_side[side] = {
                "payoff_false_cue": {
                    **fc, "max": C2_PAYOFF_BAR_FALSE_CUE_MAX,
                    "pass": bool(
                        fc["bound"] <= C2_PAYOFF_BAR_FALSE_CUE_MAX)},
                "cue_precision": {
                    **prec, "min": C2_CUE_PRECISION_MIN,
                    "pass": bool(
                        prec["bound"] >= C2_CUE_PRECISION_MIN)},
                "confusion": confusion,
                "pass": ok,
            }
        per_rung[rung] = {
            "sides": per_side,
            "d0_hard_requirement_note": "D0(最大 alpha)单独通过是硬"
                                        "要求;本 gate 按 rung × side "
                                        "全部单独通过(更强)",
            "pass": bool(all(v["pass"] for v in per_side.values())),
        }
    return {
        "format": "cur261-r7-candidate-cue-semantics-v1",
        "candidate": candidate_id,
        "cluster_unit": CUE_CLUSTER_UNIT,
        "per_rung": per_rung,
        "pass": bool(all(v["pass"] for v in per_rung.values())),
    }


def cue_semantic_rule_identity() -> str:
    """R7 cue 语义 gate 规则身份(冻结;plan/pack 绑定)。"""
    payload = {
        "contract": "C2CueDetectionSemanticContract-v1",
        "cluster_unit": CUE_CLUSTER_UNIT,
        "canonical": "/".join(CUE_CANONICAL_OBSERVATION),
        "lcb_confidence": CUE_LCB_CONFIDENCE,
        "bootstrap_resamples": R7_CUE_BOOTSTRAP_RESAMPLES,
        "bootstrap_seed": R7_CUE_BOOTSTRAP_SEED,
        "precision_min": C2_CUE_PRECISION_MIN,
        "noncue_fp_max": C2_NON_CUE_FALSE_POSITIVE_MAX,
        "payoff_false_cue_max": C2_PAYOFF_BAR_FALSE_CUE_MAX,
        "min_unique_positive_cues": MIN_UNIQUE_POSITIVE_CUES,
        "shared_gate_checks": [
            "canonical_consistency", "cross_candidate_cue_table_identical",
            "recall_lcb_ge_floor", "noncue_fp_ucb_le_max",
            "n_unique_positive_cues_ge_min", "coverage_complete"],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return "r7csg-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ------------------------------------------- independent 语料(pair cluster)
def independent_cue_semantics(
        records: list[Any], candidate_id: str,
        thresholds: dict[str, float] | None = None,
        recall_floor_value: float = 0.0,
) -> dict[str, Any]:
    """§21/§24 独立-rung 语料的 cluster-aware cue 语义。

    independent pair 语料无 matched block;cluster unit = pair
    (A/B 同 seed 共享噪声流与 cue 表——同一 (pair_index, cue_bar)
    的 8 份重复观测中 A/B cue bar 读数逐位一致,canonical = A 侧
    去重);payoff bar 读数 A/B 不同(gate 绑定不同),按 rung × side
    分别统计,cluster=pair。
    """
    thr = dict(C2_REFERENCE_DEFAULTS)
    if thresholds:
        thr.update(thresholds)
    cue_thr = float(thr["cue_thr"])
    pos_blocks: list[dict[str, int]] = []
    noncue_blocks: list[dict[str, int]] = []
    per_rung_side: dict[str, dict[str, list[dict[str, int]]]] = {}
    violations: list[str] = []
    for rec in records:
        ep_a = rec.episodes["A"]
        ep_b = rec.episodes["B"]
        cue_a = ep_a.hidden["cue_dir"].to_numpy()
        cue_b = ep_b.hidden["cue_dir"].to_numpy()
        if not np.array_equal(cue_a, cue_b):
            violations.append(
                f"pair{rec.pair_index}:{rec.rung}:A/B cue_dir 表不一致")
        r_a = ep_a.df["%-ret-1"].to_numpy(dtype=np.float64)
        r_b = ep_b.df["%-ret-1"].to_numpy(dtype=np.float64)
        pos = np.flatnonzero(cue_a == 1)
        hits = 0
        for t in pos.tolist():
            if abs(float(r_a[t]) - float(r_b[t])) > _READ_TOL:
                violations.append(
                    f"pair{rec.pair_index}:{rec.rung}:bar{t}:A/B cue "
                    "detection input 不一致")
            if r_a[t] > cue_thr:
                hits += 1
        pos_blocks.append({"n": int(len(pos)), "hit": hits})
        active_a = ep_a.hidden["payoff_active"].to_numpy()
        sel = (cue_a == 0) & (active_a == 0)
        noncue_blocks.append({
            "n": int(sel.sum()),
            "hit": int((sel & (r_a > cue_thr)).sum())})
        slot = per_rung_side.setdefault(rec.rung, {"A": [], "B": []})
        for side, ep in (("A", ep_a), ("B", ep_b)):
            cue = ep.hidden["cue_dir"].to_numpy()
            active = ep.hidden["payoff_active"].to_numpy() == 1
            r1 = ep.df["%-ret-1"].to_numpy(dtype=np.float64)
            over = r1 > cue_thr
            slot[side].append({
                "payoff": {"n": int(active.sum()),
                           "hit": int((active & over).sum())},
                "precision": {"n": int(over.sum()),
                              "hit": int((over & (cue == 1)).sum())},
            })
    recall = cluster_bootstrap_rate(pos_blocks, side="lower")
    noncue = cluster_bootstrap_rate(noncue_blocks, side="upper")
    n_unique_positive = sum(b["n"] for b in pos_blocks)
    per_rung: dict[str, Any] = {}
    all_ok = True
    covered_rungs2 = sorted(per_rung_side)
    if set(covered_rungs2) != {"D0", "D1", "D2", "D3"}:
        raise RuntimeError(
            f"independent cue 语义要求覆盖 D0-D3,收到 {covered_rungs2}")
    for rung in covered_rungs2:
        per_side: dict[str, Any] = {}
        for side in ("A", "B"):
            fc = cluster_bootstrap_rate(
                [b["payoff"] for b in per_rung_side[rung][side]],
                side="upper")
            prec = cluster_bootstrap_rate(
                [b["precision"] for b in per_rung_side[rung][side]],
                side="lower")
            ok = bool(fc["bound"] <= C2_PAYOFF_BAR_FALSE_CUE_MAX
                      and prec["bound"] >= C2_CUE_PRECISION_MIN)
            all_ok = all_ok and ok
            per_side[side] = {
                "payoff_false_cue": {
                    **fc, "max": C2_PAYOFF_BAR_FALSE_CUE_MAX,
                    "pass": bool(
                        fc["bound"] <= C2_PAYOFF_BAR_FALSE_CUE_MAX)},
                "cue_precision": {
                    **prec, "min": C2_CUE_PRECISION_MIN,
                    "pass": bool(
                        prec["bound"] >= C2_CUE_PRECISION_MIN)},
                "pass": ok,
            }
        per_rung[rung] = {
            "sides": per_side,
            "pass": bool(all(v["pass"] for v in per_side.values())),
        }
    checks = {
        "canonical_consistency": not violations,
        "recall_lcb_ge_floor": bool(
            recall["bound"] >= recall_floor_value),
        "noncue_fp_ucb_le_max": bool(
            noncue["bound"] <= C2_NON_CUE_FALSE_POSITIVE_MAX),
        "candidate_specific_rung_side": all_ok,
    }
    return {
        "format": "cur261-r7-independent-cue-semantics-v1",
        "candidate": candidate_id,
        "cluster_unit": "independent_pair",
        "canonical": "A",
        "violations": violations,
        "n_unique_positive_cues": n_unique_positive,
        "recall": recall,
        "recall_floor": recall_floor_value,
        "noncue_false_positive": {
            **noncue, "max": C2_NON_CUE_FALSE_POSITIVE_MAX},
        "per_rung": per_rung,
        "checks": checks,
        "pass": bool(all(checks.values())),
    }
