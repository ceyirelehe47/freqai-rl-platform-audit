# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R15:Dependence-Aware Global Cue-K 审计(C2MirrorCountGlobalAudit-v1)。

R11 的逐位置独立 Binomial 4σ 检查(legacy_positionwise_z_diagnostic)存在三个
统计问题(§7/§11):

1. 多重比较:约 250 个 gated position cell 各自承担 4σ 硬门禁,联合
   family-wise 错误率未校准(名义 Bonferroni ≈ 250×2Φ(-4)≈0.016 只是
   上界且按独立 cell 近似);
2. 共享 mirror source 相关性:同一 block 内相邻位置事件的 K 共享同一批
   source 随机单元(每单元只有一个 gap 抽签,对 9 个可能镜像位置互斥),
   聚合统计量(tail aggregate/corpus aggregate)的方差不能用
   C(t)·p·(1-p)/n_events 的独立 event 公式表达;
3. 离散边界:31 个事件的 K 均值格点结构下 |z|=4.0005 越过 4.0 属于
   格点抖动,连续正态近似的硬阈值在边界处不稳定。

本模块建立预注册的 dependence-aware family-wise 全局判定:

底层随机单元(§8;合同验证见 run_global_k_audit 的图完整性检查):
  unit u = (corpus, block_index, source bar s),s ∈ [1, n-17];
  u 的随机原语 = paired_noise 中该 source bar 的 gap 抽签
  G_u ~ Uniform{8,...,16}(iid;顺序消耗同一 PCG64 流,块间独立种子);
  事件 (b, t) 的镜像命中 K_b(t) = #{u=(b,s): s ∈ cand(t), G_u = t - s},
  cand(t) = [max(1, t-16), min(t-8, n-17)](v2 权威边界)。

结构接受独立性(§8):attempts-mode 的结构接受(c2_structural_issues +
pair_structural_contract + verify_cross_rung_matching + pair integrity)
只读 hidden 结构表(cue_dir/s/w ±1 状态、A/B 共享表、参数差异面),不读
噪声值/mirror hit/K/cue 检出 ⇒ 已接受 corpus 上条件固定
  cue schedule / block membership / candidate incidence graph
只重采样底层 gap 随机单元是合法的 null(该判断预注册于本合同)。

cell 与全局统计量(§9):
  对每个 corpus(model/validation):
    - position cell(t):S = Σ_{events at t} K(权重全 1);
    - corpus aggregate cell:S = Σ_events K(unit 权重 = 该 unit 所属
      block 内以该 source 为候选的事件数,共享单元保留权重);
    - true tail aggregate cell(t >= 264,episode n=288 的最后 24 bars):
      S = Σ_{events t>=264} K。
  预注册 cell 资格(仅依据 cue schedule/candidate graph/null 信息量,
  绝不依据观察到的 K 偏离大小):
    exact null variance > 0  且  n_unique_underlying_units >= 30。
  Z_j = (S_j - μ_j)/σ_j;单元独立 Bernoulli 模型下
    μ_j = Σ_u q_u,σ_j² = Σ_u q_u(1-q_u),q_u = n_u/9
  (n_u = unit u 可命中的 cell 内事件数;每单元单一 gap ⇒ 最多命中
  一个事件——聚合 cell 的权重式 Σw·Bernoulli(1/9) 已被小图精确
  枚举否定并修正)。
  全局统计量 T_obs = max_j |Z_j|(跨 model/validation 的全部合格 cell)。

全局 null 与机械判定(§10):
  预注册固定 RNG stream(seed 20270201,身份绑定 namespace
  cue_k_global_null_r15)逐 replicate 重采样全部 unit gap,保持依赖结构;
  p_global = (1 + #{T_null >= T_obs}) / (B + 1);
  global alpha = 0.05;两层 Monte Carlo continuation:
    第一层 B1 = 50,000:99% Clopper–Pearson 区间
      [lower > 0.05 ⇒ PASS;upper < 0.05 ⇒ FAIL;跨 0.05 ⇒ 继续];
    第二层同 stream 累计 B2 = 200,000(前缀 chunk digest 必须与第一层
    逐位一致;不得换 seed/重置/丢弃);
    仍跨 0.05 ⇒ INDETERMINATE(对 Stage 2.6.1 按 FAIL 处理)。

逐 cell 诊断(§11)与正式条件 p 同源于该 joint-null randomization
(|Z_j,null| >= |Z_j,obs| 逐 cell 累积计数);边际 exact binomial 仅作
marginal_cross_check_only 旁证。本模块不生成任何 episode;输入为既有
event trace(纯统计层),输出 fail-closed 的机械判定。
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_EPISODE_BARS,
    NOISE_PAIR_GAP_RANGE,
)
from rl_curriculum.curriculum261_r15_noise_replay import (
    mirror_candidate_count,
    mirror_candidate_positions,
)

#: 审计合同版本(§7:独立于 C2CueDetectionSemanticContract-v2;本轮变化
#: 的是审计统计方法,不是 cue 生成/检测语义)。
GLOBAL_K_AUDIT_CONTRACT_VERSION = "C2MirrorCountGlobalAudit-v1"

#: 单个 candidate 单元命中概率(gap ~ U{8..16} ⇒ 1/9)。
UNIT_HIT_PROB = 1.0 / 9.0

#: 真正 tail 窗口:episode n=288 的最后 24 bars(t >= 264)。
#: t=226 不是 tail(§2/§12:R11 把 t=226 误称 tail-position failure,
#: 正名为 position-wise mirror-count distribution failure)。
TRUE_TAIL_WINDOW_BARS = 24

#: §9 预注册 cell 资格(数据前锁定;禁止依据观察到的 K 偏离调整)。
MIN_UNIQUE_NULL_UNITS = 30

#: §10 预注册全局判定参数。
GLOBAL_ALPHA = 0.05
NULL_B_TIER1 = 50_000
NULL_B_TIER2 = 200_000
NULL_CHUNK = 1_000
#: 预注册 null RNG stream(身份进入合同 payload;数据后不得修改)。
GLOBAL_K_NULL_RNG_SEED = 20270201
GLOBAL_K_NULL_STREAM_NAMESPACE = "cue_k_global_null_r15"
#: Clopper–Pearson 区间置信水平(双侧 99%)。
CP_CONFIDENCE = 0.99

#: 逐 cell 诊断的边际精确交叉核对(§11:必须明确标注
#: marginal_cross_check_only,不得覆盖 dependence-aware global verdict)。
MARGINAL_CROSS_CHECK_LABEL = "marginal_cross_check_only"

#: §10 落盘的最小完整 trace 样本(replicate 数)。
NULL_TRACE_SAMPLE_REPLICATES = 20


# ----------------------------------------------------------- 合同 payload
def global_k_audit_contract_payload() -> dict[str, Any]:
    """预注册合同身份载荷(任何 R15 正式 cue event 生成前锁定)。"""
    return {
        "version": GLOBAL_K_AUDIT_CONTRACT_VERSION,
        "random_unit": {
            "definition": "unit = (corpus, block_index, source bar s), "
                          "s ∈ [1, n-17];随机原语 = paired_noise 该 "
                          "source bar 的 gap 抽签",
            "gap_distribution": "Uniform{8,...,16}",
            "unit_hit_probability": UNIT_HIT_PROB,
            "event_k_definition": "K_b(t) = #{u=(b,s): s ∈ cand(t), "
                                  "G_u = t - s}",
            "candidate_bound": "cand(t) = [max(1, t-16), min(t-8, n-17)]"
                               " (TailMirrorBoundIntegrity-v2 同源)",
            "shared_source_semantics": "每 unit 单一 gap ⇒ 同 block 内"
                                       " 相邻位置事件共享 unit 且命中"
                                       "互斥(负相关);聚合统计量必须"
                                       "保留 incidence 权重",
            "independence_claims": [
                "同 block 内不同 source bar 的 gap 抽签 iid(顺序消耗"
                "同一 PCG64 流)",
                "不同 block 的噪声种子独立(derive261_block_seed 按 "
                "namespace/block/attempt 哈希派生)",
                "cue 位置表与噪声 gap 由独立派生流决定(cue 主流 vs "
                "'_noise':'market' 流)",
            ],
            "attempts_acceptance_independence": (
                "attempts-mode 结构接受只读 hidden 结构表(cue_dir/s/w "
                "±1 状态、A/B 共享表一致性、参数差异面),不读噪声值/"
                "mirror hit/K/cue 检出 ⇒ 条件固定 cue schedule/block "
                "membership/candidate incidence graph,只重采样底层 "
                "gap 随机单元的 null 合法"),
        },
        "cells": {
            "position_cell": "每 corpus 每 cue 位置 t:S = Σ_{events "
                             "at t} K(unit 权重 1)",
            "corpus_aggregate_cell": "S = Σ_events K(unit 权重 = 所属 "
                                     "block 内以该 source 为候选的事件"
                                     "数;共享单元保留权重)",
            "true_tail_aggregate_cell": "t >= 264(最后 24 bars)的 "
                                        "事件聚合;t=226 不是 tail",
            "eligibility": {
                "exact_null_variance_positive": True,
                "min_unique_underlying_null_units": MIN_UNIQUE_NULL_UNITS,
                "eligibility_basis": "仅 cue schedule/candidate graph/"
                                     "null 信息量;禁止依据观察到的 K "
                                     "偏离大小",
            },
            "statistic": {
                "S_j": "Σ_u H_u;H_u = 1{unit u 的单一 gap 镜像命中 "
                       "cell 内任一事件}(每单元最多命中一个事件;"
                       "小图精确枚举验证)",
                "mu": "Σ_u q_u;q_u = n_u/9(n_u = 该单元可命中的 "
                      "cell 内事件数)",
                "sigma2": "Σ_u q_u(1-q_u)(单元间独立:gap iid)",
                "Z_j": "(S_j - μ_j)/σ_j",
                "T_obs": "max_j |Z_j| 跨 model positions / validation "
                         "positions / model aggregate / validation "
                         "aggregate / model true-tail aggregate / "
                         "validation true-tail aggregate",
            },
        },
        "global_test": {
            "null": "联合 null:固定依赖结构/incidence graph,逐 "
                    "replicate 重采样全部 unit gap",
            "p_global_formula": "(1 + count(T_null >= T_obs)) / (B + 1)",
            "alpha": GLOBAL_ALPHA,
            "tier1_B": NULL_B_TIER1,
            "tier2_B": NULL_B_TIER2,
            "cp_confidence": CP_CONFIDENCE,
            "continuation": "tier2 复用同一预注册 stream(前缀 chunk "
                            "digest 逐位一致;不换 seed/不重置/不丢弃)",
            "indeterminate_rule": "tier2 后 99% CP 区间仍跨 0.05 ⇒ "
                                  "INDETERMINATE ⇒ 按 FAIL 处理",
            "rng_seed": GLOBAL_K_NULL_RNG_SEED,
            "rng_stream_namespace": GLOBAL_K_NULL_STREAM_NAMESPACE,
            "rng_algorithm": "numpy PCG64(default_rng)固定 draw 模式:"
                             "每 replicate 依 corpus 注册顺序(model→"
                             "validation)逐 corpus integers(8,17,"
                             "n_units) 一次",
        },
        "legacy_diagnostic": {
            "name": "legacy_positionwise_z_diagnostic",
            "rule": "逐位置 K 均值 vs Binomial(C(t),1/9),独立 event "
                    "SE,|z| <= 4.0",
            "binding_gate": False,
            "legacy_diagnostic_only": True,
            "note": "R11 t=226 的 |z|=4.000504 属于该 legacy 检查;R15 "
                    "起不再决定 PASS/FAIL",
        },
        "tail_definition": {
            "true_tail": "t >= 264(n=288 的最后 24 bars)",
            "t226_is_tail": False,
            "t226_classification": "position-wise mirror-count "
                                   "distribution failure(非 tail)",
        },
    }


def global_k_audit_contract_digest() -> str:
    blob = json.dumps(global_k_audit_contract_payload(), sort_keys=True,
                      ensure_ascii=False)
    return "r15gk-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ----------------------------------------------------------- incidence 图
@dataclass
class CorpusGraph:
    """单 corpus 的 event→unit incidence 图(从 event trace 重建)。

    字段全部为对齐数组:
    - ev_block/ev_t:事件坐标(block_index, cue_bar);
    - ev_k:观察到的 K(observed);
    - unit_block/unit_source:全部被任一事件候选窗口覆盖的底层单元;
    - per-event candidate 单元索引 CSR:ev_unit_ptr / ev_unit_idx
      (event i 的候选单元 = ev_unit_idx[ev_unit_ptr[i]:ev_unit_ptr[i+1]])。
    """

    corpus: str
    n_blocks: int
    ev_block: np.ndarray
    ev_t: np.ndarray
    ev_k: np.ndarray
    unit_block: np.ndarray
    unit_source: np.ndarray
    ev_unit_ptr: np.ndarray
    ev_unit_idx: np.ndarray
    integrity: dict[str, Any] = field(default_factory=dict)


def build_corpus_graph(
        events: Iterable[dict[str, Any]],
        corpus: str,
        n: int = int(CURRICULUM261_EPISODE_BARS),
) -> CorpusGraph:
    """从 event trace(dict 列表)重建 incidence 图并做完整性验证。

    验证(§8):
    1. 每事件 mirror_candidates == len(analytic cand(t));
    2. mirror_positions ⊆ cand(t) 且 k_actual == len(mirror_positions);
    3. 同一 unit 至多命中一个事件(单一 gap ⇒ 镜像唯一落点);
    4. 观察到的命中单元 gap 反推 = t - s ∈ [8,16];
    5. 事件 (block, t) 唯一。
    """
    ev_rows = sorted(events, key=lambda e: (int(e["block_index"]),
                                            int(e["cue_bar"])))
    seen_events: set[tuple[int, int]] = set()
    problems: list[str] = []
    ev_block: list[int] = []
    ev_t: list[int] = []
    ev_k: list[int] = []
    unit_index: dict[tuple[int, int], int] = {}
    unit_block_l: list[int] = []
    unit_source_l: list[int] = []
    ev_unit_ptr = [0]
    ev_unit_idx: list[int] = []
    hit_units_by_block: dict[int, dict[int, int]] = {}
    for e in ev_rows:
        b = int(e["block_index"])
        t = int(e["cue_bar"])
        if (b, t) in seen_events:
            problems.append(f"corpus {corpus}: duplicate event ({b},{t})")
        seen_events.add((b, t))
        cand = mirror_candidate_positions(t, n)
        c_rep = int(e.get("mirror_candidates", -1))
        if c_rep != len(cand):
            problems.append(
                f"corpus {corpus}: event ({b},{t}) mirror_candidates="
                f"{c_rep} != analytic {len(cand)}")
        mirrors = [int(s) for s in e.get("mirror_positions", [])]
        k_rep = int(e.get("k_actual", -1))
        if k_rep != len(mirrors):
            problems.append(
                f"corpus {corpus}: event ({b},{t}) k_actual={k_rep} != "
                f"len(mirror_positions)={len(mirrors)}")
        cand_set = set(cand)
        for s in mirrors:
            if s not in cand_set:
                problems.append(
                    f"corpus {corpus}: event ({b},{t}) mirror source "
                    f"{s} 超出候选集")
            if not (NOISE_PAIR_GAP_RANGE[0] <= t - s
                    <= NOISE_PAIR_GAP_RANGE[1]):
                problems.append(
                    f"corpus {corpus}: event ({b},{t}) mirror source "
                    f"{s} 反推 gap {t - s} 越界")
        per_block_hits = hit_units_by_block.setdefault(b, {})
        for s in mirrors:
            if s in per_block_hits and per_block_hits[s] != t:
                problems.append(
                    f"corpus {corpus}: unit ({b},{s}) 同时命中 "
                    f"t={per_block_hits[s]} 与 t={t}(单一 gap 违背)")
            per_block_hits[s] = t
        for s in cand:
            key = (b, s)
            if key not in unit_index:
                unit_index[key] = len(unit_block_l)
                unit_block_l.append(b)
                unit_source_l.append(s)
            ev_unit_idx.append(unit_index[key])
        ev_unit_ptr.append(len(ev_unit_idx))
        ev_block.append(b)
        ev_t.append(t)
        ev_k.append(k_rep)
    blocks = sorted({int(e["block_index"]) for e in ev_rows}) if ev_rows \
        else []
    if blocks and blocks != list(range(blocks[0],
                                       blocks[0] + len(blocks))):
        problems.append(f"corpus {corpus}: block 索引非连续:头部"
                        f"{blocks[:3]} 尾部{blocks[-3:]}")
    integrity = {
        "n_events": len(ev_rows),
        "n_blocks": len(blocks),
        "n_unique_units": len(unit_block_l),
        "n_problems": len(problems),
        "problems_sample": problems[:10],
        "ok": not problems,
    }
    return CorpusGraph(
        corpus=corpus,
        n_blocks=len(blocks),
        ev_block=np.asarray(ev_block, dtype=np.int64),
        ev_t=np.asarray(ev_t, dtype=np.int64),
        ev_k=np.asarray(ev_k, dtype=np.int64),
        unit_block=np.asarray(unit_block_l, dtype=np.int64),
        unit_source=np.asarray(unit_source_l, dtype=np.int64),
        ev_unit_ptr=np.asarray(ev_unit_ptr, dtype=np.int64),
        ev_unit_idx=np.asarray(ev_unit_idx, dtype=np.int64),
        integrity=integrity,
    )


# ----------------------------------------------------------- cell 定义
@dataclass
class CellSpec:
    """一个受检 cell:unit → 该单元可命中的 cell 内事件数 n_u。

    每单元只有一个 gap 抽签,镜像只落一个位置 ⇒ 最多命中一个事件,
    对 S 的贡献为 Bernoulli(q_u),q_u = n_u/9(小图精确枚举已验证;
    R15 早期草稿的 w_u×Bernoulli(1/9) 权重式在聚合 cell 上错误)。

    μ_j = Σ_u q_u;σ_j² = Σ_u q_u(1-q_u)(单元间独立:gap iid)。
    n_units = len(unit_event_counts)(资格判定用唯一下层单元数)。
    """

    corpus: str
    kind: str          # position | corpus_aggregate | true_tail_aggregate
    t: int | None      # position cell 的 t;聚合为 None
    unit_event_counts: dict[int, int]  # unit 全局索引 -> 可命中事件数
    label: str

    def unit_weights(self) -> dict[int, float]:
        """兼容诊断口径:unit -> 可命中事件数(float)。"""
        return {u: float(c) for u, c in self.unit_event_counts.items()}

    def hit_probs(self) -> dict[int, float]:
        return {u: c * UNIT_HIT_PROB
                for u, c in self.unit_event_counts.items()}

    def moments(self) -> tuple[float, float]:
        q = np.fromiter(self.hit_probs().values(), dtype=np.float64)
        return (float(q.sum()), float((q * (1.0 - q)).sum()))


def _cell_eligible(cell: CellSpec) -> bool:
    """§9 预注册资格:exact null variance > 0 且 ≥30 唯一底层单元。"""
    _, sigma2 = cell.moments()
    return bool(sigma2 > 0.0
                and len(cell.unit_event_counts) >= MIN_UNIQUE_NULL_UNITS)


def build_cells(graph: CorpusGraph,
                n: int = int(CURRICULUM261_EPISODE_BARS),
                ) -> list[CellSpec]:
    """按预注册规则构建全部 cell(资格判定在构建时固定,不看观察 K)。"""
    cells: list[CellSpec] = []
    tail_start = n - TRUE_TAIL_WINDOW_BARS
    n_events = len(graph.ev_t)
    by_t: dict[int, list[int]] = {}
    for i in range(n_events):
        by_t.setdefault(int(graph.ev_t[i]), []).append(i)
    for t in sorted(by_t):
        counts: dict[int, int] = {}
        for i in by_t[t]:
            for j in range(int(graph.ev_unit_ptr[i]),
                           int(graph.ev_unit_ptr[i + 1])):
                u = int(graph.ev_unit_idx[j])
                counts[u] = counts.get(u, 0) + 1
        spec = CellSpec(graph.corpus, "position", t, counts,
                        label=f"{graph.corpus}/position/t={t}")
        if _cell_eligible(spec):
            cells.append(spec)
    agg: dict[int, int] = {}
    for i in range(n_events):
        for j in range(int(graph.ev_unit_ptr[i]),
                       int(graph.ev_unit_ptr[i + 1])):
            u = int(graph.ev_unit_idx[j])
            agg[u] = agg.get(u, 0) + 1
    spec = CellSpec(graph.corpus, "corpus_aggregate", None, agg,
                    label=f"{graph.corpus}/aggregate")
    if _cell_eligible(spec):
        cells.append(spec)
    tail: dict[int, int] = {}
    for i in range(n_events):
        if int(graph.ev_t[i]) < tail_start:
            continue
        for j in range(int(graph.ev_unit_ptr[i]),
                       int(graph.ev_unit_ptr[i + 1])):
            u = int(graph.ev_unit_idx[j])
            tail[u] = tail.get(u, 0) + 1
    spec = CellSpec(graph.corpus, "true_tail_aggregate", None, tail,
                    label=f"{graph.corpus}/true_tail_aggregate"
                          f"(t>={tail_start})")
    if _cell_eligible(spec):
        cells.append(spec)
    return cells


def observed_cell_sums(graph: CorpusGraph, cells: Sequence[CellSpec],
                       n: int = int(CURRICULUM261_EPISODE_BARS),
                       ) -> list[float]:
    """从观察 K 复算每 cell 的 S_j(与权重口径一致;复算即验证)。"""
    ev_k = graph.ev_k.astype(np.float64)
    by_t: dict[int, float] = {}
    tail_start = n - TRUE_TAIL_WINDOW_BARS
    tail_sum = 0.0
    for i in range(len(graph.ev_t)):
        t = int(graph.ev_t[i])
        by_t[t] = by_t.get(t, 0.0) + float(ev_k[i])
        if t >= tail_start:
            tail_sum += float(ev_k[i])
    total = float(ev_k.sum())
    out: list[float] = []
    for c in cells:
        if c.kind == "position":
            out.append(by_t.get(int(c.t), 0.0))
        elif c.kind == "corpus_aggregate":
            out.append(total)
        else:
            out.append(tail_sum)
    return out


# ----------------------------------------------------------- null 引擎
@dataclass
class _NullPlan:
    """向量化 null 的预计算(单 corpus)。

    - ev_key_sorted/ev_order:事件键排序与原下标映射;
    - pos_cell_of_event:事件 → position cell 槽位(-1 = 无资格 cell);
    - pos_slot_of_cell:cells 数组下标 → position 槽位(-1 = 非位置
      cell);s_cells 通过该索引数组向量化填充(无逐 cell Python 循环);
    - tail_flag_event:事件是否属于 true tail;
    - mu_arr/sigma_arr:cell 解析矩(与 cells 对齐)。
    """

    graph: CorpusGraph
    cells: list[CellSpec]
    ev_key_sorted: np.ndarray
    ev_order: np.ndarray
    pos_cell_of_event: np.ndarray
    pos_slot_of_cell: np.ndarray
    n_pos_cells: int
    agg_cell_idx: int
    tail_cell_idx: int
    tail_event_mask: np.ndarray
    mu_arr: np.ndarray
    sigma_arr: np.ndarray
    unit_block_n: np.ndarray   # unit_block * n(预乘)
    unit_source: np.ndarray
    gap_lo: int
    gap_hi_excl: int


def _make_null_plan(graph: CorpusGraph, cells: Sequence[CellSpec],
                    n: int) -> _NullPlan:
    ev_key = graph.ev_block * n + graph.ev_t
    order = np.argsort(ev_key, kind="stable")
    labels = {c.label: i for i, c in enumerate(cells)}
    pos_slot_of_cell = np.full(len(cells), -1, dtype=np.int64)
    pos_cell_of_event = np.full(len(ev_key), -1, dtype=np.int64)
    slot = 0
    for ci, c in enumerate(cells):
        if c.kind == "position":
            pos_slot_of_cell[ci] = slot
            slot += 1
    for i in range(len(ev_key)):
        t = int(graph.ev_t[i])
        ci = labels.get(f"{graph.corpus}/position/t={t}", -1)
        if ci >= 0:
            pos_cell_of_event[i] = pos_slot_of_cell[ci]
    agg_cell_idx = next((i for i, c in enumerate(cells)
                         if c.kind == "corpus_aggregate"), -1)
    tail_cell_idx = next((i for i, c in enumerate(cells)
                          if c.kind == "true_tail_aggregate"), -1)
    tail_mask = graph.ev_t >= (n - TRUE_TAIL_WINDOW_BARS)
    mu = np.array([c.moments()[0] for c in cells], dtype=np.float64)
    sig = np.array([math.sqrt(c.moments()[1]) for c in cells],
                   dtype=np.float64)
    return _NullPlan(
        graph=graph, cells=list(cells), ev_key_sorted=ev_key[order],
        ev_order=order, pos_cell_of_event=pos_cell_of_event,
        pos_slot_of_cell=pos_slot_of_cell, n_pos_cells=slot,
        agg_cell_idx=agg_cell_idx, tail_cell_idx=tail_cell_idx,
        tail_event_mask=tail_mask, mu_arr=mu, sigma_arr=sig,
        unit_block_n=(graph.unit_block * n).astype(np.int64),
        unit_source=graph.unit_source.astype(np.int64),
        gap_lo=NOISE_PAIR_GAP_RANGE[0],
        gap_hi_excl=NOISE_PAIR_GAP_RANGE[1] + 1,
    )


def _null_replicate_cells(plan: _NullPlan, gaps: np.ndarray,
                          n: int) -> np.ndarray:
    """一次 replicate:返回全部 cell 的 S_j(null)。

    依赖结构保持:unit 集合/块归属/事件坐标/incidence 固定;只重采样
    unit gap。命中 = unit 镜像位置恰为该 block 的某事件位置。
    """
    pair_key = plan.unit_block_n + (plan.unit_source + gaps)
    pos = np.searchsorted(plan.ev_key_sorted, pair_key)
    np.minimum(pos, len(plan.ev_key_sorted) - 1, out=pos)
    hit = plan.ev_key_sorted[pos] == pair_key
    s_cells = np.zeros(len(plan.cells), dtype=np.float64)
    if not hit.any():
        return s_cells
    ev_idx = plan.ev_order[pos[hit]]           # 命中的原事件下标
    pc = plan.pos_cell_of_event[ev_idx]
    pos_hits = pc >= 0
    if pos_hits.any():
        counts = np.bincount(pc[pos_hits], minlength=plan.n_pos_cells)
        s_cells[plan.pos_slot_of_cell >= 0] = counts
    if plan.agg_cell_idx >= 0:
        s_cells[plan.agg_cell_idx] = float(len(ev_idx))
    if plan.tail_cell_idx >= 0:
        s_cells[plan.tail_cell_idx] = float(np.count_nonzero(
            plan.tail_event_mask[ev_idx]))
    return s_cells


def _clopper_pearson(count: int, n_obs: int,
                     conf: float = CP_CONFIDENCE) -> tuple[float, float]:
    """双侧 CP 区间(精确二项)。"""
    from scipy.stats import beta as _beta

    alpha = 1.0 - conf
    if n_obs <= 0:
        return (0.0, 1.0)
    lo = 0.0 if count == 0 else float(
        _beta.ppf(alpha / 2.0, count, n_obs - count + 1))
    hi = 1.0 if count == n_obs else float(
        _beta.ppf(1.0 - alpha / 2.0, count + 1, n_obs - count))
    return (lo, hi)


def run_global_k_null(
        graphs: dict[str, CorpusGraph],
        cells_by_corpus: dict[str, list[CellSpec]],
        t_obs: float,
        b_total: int,
        *,
        observed_z_abs: dict[str, np.ndarray] | None = None,
        seed: int = GLOBAL_K_NULL_RNG_SEED,
        prior_chunks: list[str] | None = None,
        chunk_size: int = NULL_CHUNK,
        trace_sample: int = NULL_TRACE_SAMPLE_REPLICATES,
) -> dict[str, Any]:
    """运行联合 null 到 b_total(同 stream 从头确定性重放)。

    - 每 replicate:依 corpus 注册顺序逐 corpus integers(8,17,n_units)
      一次(固定 draw 模式 = RNG 身份);
    - T_null = 跨全部 cell 的 max |Z|;
    - observed_z_abs 提供时,同步累积逐 cell |Z_null|>=|Z_obs| 计数
      (§11 正式条件 p 的同源计数);
    - prior_chunks(第二层)与重放前缀逐位比对,fail closed。
    """
    if set(graphs) != set(cells_by_corpus):
        raise ValueError("graphs 与 cells_by_corpus 的 corpus 集合不一致")
    plans = {name: _make_null_plan(g, cells_by_corpus[name],
                                   int(CURRICULUM261_EPISODE_BARS))
             for name, g in graphs.items()}
    corpora = list(plans.keys())
    rng = np.random.default_rng(int(seed))
    exceed = 0
    chunk_digests: list[str] = []
    cur_chunk: list[float] = []
    cell_exceed: dict[str, np.ndarray] = {
        name: np.zeros(len(cells_by_corpus[name]), dtype=np.int64)
        for name in corpora}
    cell_z_abs_running_max: dict[str, np.ndarray] = {
        name: np.zeros(len(cells_by_corpus[name]), dtype=np.float64)
        for name in corpora}
    trace: list[dict[str, Any]] = []
    done = 0
    while done < b_total:
        t_max = -1.0
        for name in corpora:
            plan = plans[name]
            gaps = rng.integers(plan.gap_lo, plan.gap_hi_excl,
                                size=len(plan.unit_source),
                                dtype=np.int64)
            s_cells = _null_replicate_cells(plan, gaps,
                                            int(CURRICULUM261_EPISODE_BARS))
            z_abs = np.abs((s_cells - plan.mu_arr) / plan.sigma_arr)
            obs = (observed_z_abs or {}).get(name)
            if obs is not None:
                cell_exceed[name] += z_abs >= obs
            np.maximum(cell_z_abs_running_max[name], z_abs,
                       out=cell_z_abs_running_max[name])
            local = float(z_abs.max()) if len(z_abs) else -1.0
            if local > t_max:
                t_max = local
        cur_chunk.append(t_max)
        if t_max >= t_obs:
            exceed += 1
        done += 1
        if done <= trace_sample:
            trace.append({
                "replicate": done,
                "T_null": t_max,
                "argmax": max(
                    ((plans[name].cells[i].label,
                      float(cell_z_abs_running_max[name][i]))
                     for name in corpora
                     for i in range(len(plans[name].cells))),
                    key=lambda kv: kv[1], default=(None, 0.0))[0],
            })
        if len(cur_chunk) >= chunk_size or done == b_total:
            blob = np.asarray(cur_chunk, dtype=np.float64).tobytes()
            chunk_digests.append(hashlib.sha256(blob).hexdigest())
            cur_chunk = []
    if prior_chunks is not None:
        k = len(prior_chunks)
        if chunk_digests[:k] != list(prior_chunks):
            raise RuntimeError(
                "global K null stream continuation 前缀 digest 不一致"
                "(fail closed;§10 禁止重置/换 seed/丢弃前缀)")
    p_global = (1 + exceed) / (b_total + 1)
    lo, hi = _clopper_pearson(exceed, b_total)
    if lo > GLOBAL_ALPHA:
        verdict = "PASS"
    elif hi < GLOBAL_ALPHA:
        verdict = "FAIL"
    else:
        verdict = "INDETERMINATE"
    return {
        "b_total": b_total,
        "exceedance_count": exceed,
        "p_global": p_global,
        "cp99": [lo, hi],
        "verdict": verdict,
        "chunk_size": chunk_size,
        "n_chunks": len(chunk_digests),
        "chunk_digests": chunk_digests,
        "rng_seed": int(seed),
        "stream_namespace": GLOBAL_K_NULL_STREAM_NAMESPACE,
        "alpha": GLOBAL_ALPHA,
        "prefix_continuation_verified": prior_chunks is not None,
        "cell_exceedance_counts": {
            name: cell_exceed[name].tolist() for name in corpora},
        "cell_z_null_running_max": {
            name: cell_z_abs_running_max[name].tolist()
            for name in corpora},
        "trace_sample": trace,
    }


def run_global_k_audit(
        events_by_corpus: dict[str, list[dict[str, Any]]],
        *,
        b_tier1: int = NULL_B_TIER1,
        b_tier2: int | None = NULL_B_TIER2,
        n: int = int(CURRICULUM261_EPISODE_BARS),
        null_seed: int = GLOBAL_K_NULL_RNG_SEED,
        contract_digest: str | None = None,
) -> dict[str, Any]:
    """正式全局 K 审计入口:图重建 → cell → T_obs → 两层 null 判定。

    b_tier2=None 时只跑第一层(开发/历史重分析);正式合同固定
    50k→200k。返回的 tier 结构包含逐 cell 条件 p 计数(§11)。
    """
    graphs: dict[str, CorpusGraph] = {}
    cells_by_corpus: dict[str, list[CellSpec]] = {}
    for name, events in events_by_corpus.items():
        g = build_corpus_graph(events, name, n)
        graphs[name] = g
        cells_by_corpus[name] = build_cells(g, n)
    base = {
        "format": "cur261-r15-global-k-result-v1",
        "contract_version": GLOBAL_K_AUDIT_CONTRACT_VERSION,
        "contract_digest": (contract_digest
                            if contract_digest is not None
                            else global_k_audit_contract_digest()),
        "graphs": {k: v.integrity for k, v in graphs.items()},
        "b_tier2_registered": b_tier2,
    }
    if not all(g.integrity["ok"] for g in graphs.values()):
        base.update({
            "graph_integrity_ok": False, "pass": False,
            "verdict": "FAIL",
            "fail_reason": "incidence graph 完整性验证失败(fail closed)",
        })
        return base
    base["graph_integrity_ok"] = True
    observed_z_abs: dict[str, np.ndarray] = {}
    obs_rows: list[dict[str, Any]] = []
    t_obs = -1.0
    argmax_label = None
    for name in graphs:
        cells = cells_by_corpus[name]
        obs = observed_cell_sums(graphs[name], cells)
        mu = np.array([c.moments()[0] for c in cells])
        sig = np.array([math.sqrt(c.moments()[1]) for c in cells])
        z = (np.asarray(obs) - mu) / sig
        observed_z_abs[name] = np.abs(z)
        for ci, c in enumerate(cells):
            obs_rows.append({"cell": c.label, "kind": c.kind, "t": c.t,
                             "observed_S": float(obs[ci]),
                             "mu": float(mu[ci]),
                             "z": float(z[ci])})
        if len(z):
            i = int(np.argmax(np.abs(z)))
            if abs(float(z[i])) > t_obs:
                t_obs = abs(float(z[i]))
                argmax_label = cells[i].label
    n_cells_total = sum(len(v) for v in cells_by_corpus.values())
    if n_cells_total == 0:
        base.update({"pass": False, "verdict": "FAIL",
                     "fail_reason": "零合格 cell(数据不足;fail closed)"})
        return base
    tier1 = run_global_k_null(graphs, cells_by_corpus, t_obs, b_tier1,
                              observed_z_abs=observed_z_abs,
                              seed=null_seed)
    base.update({
        "n_eligible_cells": n_cells_total,
        "cells_by_corpus": {k: len(v) for k, v in cells_by_corpus.items()},
        "T_obs": t_obs,
        "argmax_cell": argmax_label,
        "observed_cells": obs_rows,
        "tier1": tier1,
    })
    tier_final = tier1
    if b_tier2 is not None and tier1["verdict"] == "INDETERMINATE":
        tier2 = run_global_k_null(
            graphs, cells_by_corpus, t_obs, int(b_tier2),
            observed_z_abs=observed_z_abs, seed=null_seed,
            prior_chunks=tier1["chunk_digests"])
        base["tier2"] = tier2
        tier_final = tier2
    base["final"] = {
        "b": tier_final["b_total"],
        "p_global": tier_final["p_global"],
        "cp99": tier_final["cp99"],
        "verdict": tier_final["verdict"],
        "indeterminate": tier_final["verdict"] == "INDETERMINATE",
    }
    base["verdict"] = tier_final["verdict"]
    base["pass"] = tier_final["verdict"] == "PASS"
    return base


# ----------------------------------------------------- 逐 cell 诊断(§11)
def cell_diagnostics_from_result(
        result: dict[str, Any],
        events_by_corpus: dict[str, list[dict[str, Any]]],
        n: int = int(CURRICULUM261_EPISODE_BARS),
) -> list[dict[str, Any]]:
    """从 run_global_k_audit 结果构造逐 cell 诊断行(§11 字段全覆盖)。

    正式逐 cell p 基于 joint-null randomization 计数
    (1 + count)/(|Z|null 样本数 + 1);Holm/Bonferroni 在该 p 家族上
    调整。position cell 另附 marginal probability-ordering exact
    binomial 交叉核对(标注 marginal_cross_check_only)。
    """
    from scipy.stats import binom as _binom

    tier = result.get("tier2") or result.get("tier1") or {}
    b_null = int(tier.get("b_total", 0))
    exceed = tier.get("cell_exceedance_counts", {})
    graphs: dict[str, CorpusGraph] = {}
    cells_by: dict[str, list[CellSpec]] = {}
    for name, events in events_by_corpus.items():
        g = build_corpus_graph(events, name, n)
        graphs[name] = g
        cells_by[name] = build_cells(g, n)
    tail_start = n - TRUE_TAIL_WINDOW_BARS
    rows: list[dict[str, Any]] = []
    for name in graphs:
        g = graphs[name]
        cells = cells_by[name]
        obs = observed_cell_sums(g, cells)
        by_t_events: dict[int, list[int]] = {}
        for i in range(len(g.ev_t)):
            by_t_events.setdefault(int(g.ev_t[i]), []).append(i)
        n_tail = int(np.count_nonzero(g.ev_t >= tail_start))
        exc_name = exceed.get(name, [0] * len(cells))
        for ci, c in enumerate(cells):
            mu, sigma2 = c.moments()
            sigma = math.sqrt(sigma2)
            s = float(obs[ci])
            z = (s - mu) / sigma
            k_events = by_t_events.get(int(c.t), []) \
                if c.kind == "position" else None
            row: dict[str, Any] = {
                "corpus": name,
                "cell_kind": c.kind,
                "t": c.t,
                "is_true_tail": (c.t is not None and c.t >= tail_start)
                                or c.kind == "true_tail_aggregate",
                "n_events": (len(k_events) if k_events is not None
                             else len(g.ev_t) if c.kind ==
                             "corpus_aggregate" else n_tail),
                "n_unique_random_units": len(c.unit_event_counts),
                "C_t": (mirror_candidate_count(int(c.t), n)
                        if c.kind == "position" else None),
                "observed_S": s,
                "observed_K_mean": (
                    float(np.mean([g.ev_k[i] for i in k_events]))
                    if k_events is not None else None),
                "null_mean": mu,
                "null_variance": sigma2,
                "standardized_residual": float(z),
                "effect_size_relative_excess": (
                    float((s - mu) / mu) if mu > 0 else None),
                "shared_unit_multiplicity": {
                    "max_unit_event_count": max(
                        c.unit_event_counts.values()),
                    "mean_unit_event_count": float(np.mean(list(
                        c.unit_event_counts.values()))),
                    "n_units_serving_gt1_events": sum(
                        1 for w in c.unit_event_counts.values() if w > 1),
                },
                "unadjusted_conditional_p": (
                    (1 + int(exc_name[ci])) / (b_null + 1)
                    if b_null > 0 else None),
                "conditional_p_basis": (
                    "joint-null randomization |Z_null| >= |Z_obs| "
                    f"(B={b_null})" if b_null > 0 else
                    "null 未运行"),
            }
            if c.kind == "position":
                ntr = len(c.unit_event_counts)
                k_obs = int(round(s))
                dist = _binom(ntr, UNIT_HIT_PROB)
                pmf = dist.pmf(np.arange(ntr + 1))
                p_obs = float(dist.pmf(k_obs))
                p_two = float(pmf[pmf <= p_obs * (1 + 1e-12)].sum())
                row["marginal_cross_check"] = {
                    MARGINAL_CROSS_CHECK_LABEL: True,
                    "definition": "probability-ordering two-sided "
                                  "exact binomial p",
                    "n_trials": ntr,
                    "k_observed": k_obs,
                    "p_two_sided_exact": p_two,
                }
            rows.append(row)
    ps = [r["unadjusted_conditional_p"] for r in rows]
    m = len(ps)
    if m and all(p is not None for p in ps):
        order = sorted(range(m), key=lambda i: ps[i])
        holm = [0.0] * m
        running = 0.0
        for rank, i in enumerate(order):
            running = max(running, (m - rank) * ps[i])
            holm[i] = min(1.0, running)
        for i, r in enumerate(rows):
            r["holm_adjusted_p"] = float(holm[i])
            r["bonferroni_adjusted_p"] = float(min(1.0, m * ps[i]))
            r["m_cells"] = m
    return rows


# ----------------------------------------------------- legacy 诊断(降级)
def legacy_positionwise_z_diagnostic(
        events: list[dict[str, Any]],
        n: int = int(CURRICULUM261_EPISODE_BARS),
        min_events: int = 30,
        z_threshold: float = 4.0,
) -> dict[str, Any]:
    """R11 逐位置 4σ 检查的精确复刻(仅诊断;binding_gate=false)。

    用于 R11 重分析的逐位复现与新语料的 legacy 旁证。
    """
    by_pos: dict[int, list[int]] = {}
    for e in events:
        by_pos.setdefault(int(e["cue_bar"]), []).append(
            int(e["k_actual"]))
    rows: list[dict[str, Any]] = []
    max_z = 0.0
    argmax = None
    for t in sorted(by_pos):
        ks = by_pos[t]
        c = mirror_candidate_count(t, n)
        mean_k = float(np.mean(ks))
        expect = c / 9.0
        if len(ks) >= min_events and c > 0:
            se = math.sqrt((expect * (1.0 - 1.0 / 9.0)) / len(ks))
            z = (mean_k - expect) / se
            rows.append({"t": t, "n_events": len(ks), "c": c,
                         "k_mean": mean_k, "binomial_mean": expect,
                         "se": se, "z": z, "abs_z": abs(z),
                         "legacy_ok": bool(abs(z) <= z_threshold)})
            if abs(z) > max_z:
                max_z = abs(z)
                argmax = t
        else:
            rows.append({"t": t, "n_events": len(ks), "c": c,
                         "k_mean": mean_k, "binomial_mean": expect,
                         "z": None, "legacy_ok": None})
    return {
        "name": "legacy_positionwise_z_diagnostic",
        "rule": "per-position K mean vs Binomial(C(t),1/9), "
                "independent-event SE, |z| <= 4.0",
        "binding_gate": False,
        "legacy_diagnostic_only": True,
        "min_events": min_events,
        "z_threshold": z_threshold,
        "gated_positions": sum(1 for r in rows
                               if r["legacy_ok"] is not None),
        "max_abs_z": max_z,
        "argmax_t": argmax,
        "legacy_all_ok": all(r["legacy_ok"] is not False for r in rows),
        "positions": rows,
    }


# ----------------------------------------------------- 小图精确枚举(§14)
def small_graph_exact_validation(
        n_events: int = 3, n: int = 32, seed: int = 20270202,
        n_randomization: int = 200_000,
) -> dict[str, Any]:
    """§14.1:可枚举小图上 exact 枚举 vs 解析矩 vs randomization。

    构造(刻意触发共享单元依赖):n=32,事件位置 [9,10,11](n_events
    截断),候选窗口 cand(9)={1}、cand(10)={1,2}、cand(11)={1,2,3}
    ——3 个底层单元被 3 个事件共享(unit 1 服务全部事件;单一 gap ⇒
    命中互斥)。对全部 9^3=729 个 gap 组合精确枚举 cell S 分布:
    - exact μ/σ² vs 解析 μ=pΣw、σ²=p(1-p)Σw²(聚合与逐 position);
    - exact global p vs randomization 频率(T=max|Z| 口径);
    - randomization 实现按标准化 Z 校准。
    """
    rng = np.random.default_rng(seed)
    t_candidates = [9 + i for i in range(n_events)][:3]
    events = [{"block_index": 0, "cue_bar": int(t), "k_actual": 0,
               "mirror_positions": [],
               "mirror_candidates": len(
                   mirror_candidate_positions(int(t), n))}
              for t in t_candidates]
    g = build_corpus_graph(events, "exact", n)
    u_src = g.unit_source
    n_units = int(len(u_src))
    if not 1 <= n_units <= 9:
        return {"ok": False,
                "reason": f"小图单元数 {n_units} 超出可枚举范围 [1,9]"}
    # 全 cell(绕过 ≥30 单元资格;矩验证与资格无关)
    pos_weights: dict[int, dict[int, float]] = {t: {} for t in t_candidates}
    agg: dict[int, float] = {}
    for i in range(len(g.ev_t)):
        t = int(g.ev_t[i])
        for j in range(int(g.ev_unit_ptr[i]), int(g.ev_unit_ptr[i + 1])):
            u = int(g.ev_unit_idx[j])
            pos_weights[t][u] = pos_weights[t].get(u, 0.0) + 1.0
            agg[u] = agg.get(u, 0.0) + 1.0
    cells = [CellSpec("exact", "corpus_aggregate", None,
                      {u: int(c) for u, c in agg.items()},
                      "exact/aggregate")] + [
        CellSpec("exact", "position", t, {u: int(c) for u, c in w.items()},
                 f"exact/position/t={t}")
        for t, w in sorted(pos_weights.items())]
    ev_key = g.ev_block * n + g.ev_t
    ev_sorted = np.sort(ev_key)
    order = np.argsort(ev_key, kind="stable")
    unit_block_n = (g.unit_block * n).astype(np.int64)
    from itertools import product as _product

    gap_grid = np.arange(NOISE_PAIR_GAP_RANGE[0],
                         NOISE_PAIR_GAP_RANGE[1] + 1)
    combos = np.array(list(_product(gap_grid, repeat=n_units)),
                      dtype=np.int64)
    s_matrix = np.zeros((len(combos), len(cells)), dtype=np.float64)
    batch = 200_000
    for start in range(0, len(combos), batch):
        chunk = combos[start:start + batch]
        m = u_src[None, :] + chunk                       # (B, units)
        pk = unit_block_n[None, :] + m
        pos = np.searchsorted(ev_sorted, pk)
        np.clip(pos, 0, len(ev_sorted) - 1, out=pos)
        hit = ev_sorted[pos] == pk                        # (B, units)
        cnt_sorted = np.stack([
            np.bincount(pos[b][hit[b]], minlength=len(ev_sorted))
            for b in range(len(chunk))])                   # (B, n_events)
        cnt = cnt_sorted[:, order]                         # 原事件下标
        s_matrix[start:start + batch, 0] = cnt.sum(axis=1)
        for ci in range(1, len(cells)):
            t = cells[ci].t
            s_matrix[start:start + batch, ci] = cnt[:,
                                                   g.ev_t == t].sum(axis=1)
    checks = []
    mu_arr = np.array([c.moments()[0] for c in cells])
    sig_arr = np.array([math.sqrt(c.moments()[1]) for c in cells])
    for ci, cell in enumerate(cells):
        mu, sigma2 = cell.moments()
        exact_mean = float(s_matrix[:, ci].mean())
        exact_var = float(s_matrix[:, ci].var())
        checks.append({
            "cell": cell.label, "n_units": len(cell.unit_event_counts),
            "exact_mean": exact_mean, "analytic_mean": mu,
            "exact_var": exact_var, "analytic_var": sigma2,
            "mean_abs_err": abs(exact_mean - mu),
            "var_abs_err": abs(exact_var - sigma2),
            "ok": bool(abs(exact_mean - mu) < 1e-9
                       and abs(exact_var - sigma2) < 1e-9),
        })
    # ---- exact global p vs randomization 频率(T=max|Z|)----
    # 观察数据 = 随机固定组合(rng 首抽),T_obs 由其 Z 向量给出
    obs_combo = int(rng.integers(0, len(combos)))
    z_obs = np.abs((s_matrix[obs_combo] - mu_arr) / sig_arr)
    t_obs = float(z_obs.max())
    z_null = np.abs((s_matrix - mu_arr) / sig_arr)
    t_null_all = z_null.max(axis=1)
    exact_p = float(np.count_nonzero(t_null_all >= t_obs)
                    / len(combos))
    rng2 = np.random.default_rng(seed + 1)
    plan = _make_null_plan(g, cells, n)
    exceed_rand = 0
    z_cum = np.zeros(len(cells), dtype=np.float64)
    z2_cum = np.zeros(len(cells), dtype=np.float64)
    for _ in range(n_randomization):
        gaps = rng2.integers(NOISE_PAIR_GAP_RANGE[0],
                             NOISE_PAIR_GAP_RANGE[1] + 1,
                             size=n_units, dtype=np.int64)
        s_cells = _null_replicate_cells(plan, gaps, n)
        z = (s_cells - mu_arr) / sig_arr
        z_cum += z
        z2_cum += z * z
        if float(np.abs(z).max()) >= t_obs:
            exceed_rand += 1
    rand_p = (1 + exceed_rand) / (n_randomization + 1)
    mean_z = z_cum / n_randomization
    var_z = z2_cum / n_randomization - mean_z ** 2
    global_p_check = {
        "t_obs": t_obs,
        "exact_p": exact_p,
        "randomization_p": rand_p,
        "abs_diff": abs(exact_p - rand_p),
        "tolerance": 3.0 * math.sqrt(max(exact_p * (1 - exact_p), 1.0)
                                     / n_randomization) + 1e-4,
        "ok": bool(abs(exact_p - rand_p) <= 3.0 * math.sqrt(
            max(exact_p * (1 - exact_p), 1.0) / n_randomization) + 1e-4),
    }
    rand_check = {
        "n_randomization": n_randomization,
        "per_cell_mean_z_max_abs": float(np.max(np.abs(mean_z))),
        "per_cell_var_z_max_abs_dev": float(np.max(np.abs(var_z - 1.0))),
        "ok": bool(np.max(np.abs(mean_z)) < 0.03
                   and np.max(np.abs(var_z - 1.0)) < 0.10),
    }
    return {
        "n_units": n_units, "n_events": len(t_candidates),
        "event_positions": t_candidates,
        "shared_units_design": "cand(9)={1};cand(10)={1,2};"
                               "cand(11)={1,2,3}(unit 1 服务 3 事件)",
        "exact_vs_analytic": {
            "n_units": n_units, "n_enumerations": int(len(combos)),
            "cells": checks, "ok": all(c["ok"] for c in checks)},
        "exact_vs_randomization_global_p": global_p_check,
        "randomization_standardization": rand_check,
        "ok": bool(all(c["ok"] for c in checks)
                   and global_p_check["ok"] and rand_check["ok"]),
    }
