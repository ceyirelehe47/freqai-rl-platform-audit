# -*- coding: utf-8 -*-
"""R12 测试:C2MirrorCountGlobalAudit-v1(§14/§26)。

覆盖:
- random-unit graph reconstruction 与完整性验证;
- k_actual == 观察到的 unit hits 之和;
- shared-source 相关性保留(聚合 cell 解析矩 ≠ 独立事件公式);
- 小图 exact 枚举 vs 解析矩 vs randomization(§14.1);
- model+validation combined max(§14.7);
- global p 有限样本公式;
- 50k→200k stream continuation(前缀 chunk digest 一致;§14.8);
- indeterminate=FAIL;
- true tail 分类与 t=226 非 tail;
- null calibration(§14.4);
- injected bias 拒绝(§14.5);
- 边界 bug(n-1 vs n-17)拒绝(§14.3);
- 合同 payload 完整性与 legacy 降级字段;
- Holm 诊断;
- R11 legacy z 复现(读 release repo 真实 trace;存在时)。
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_EPISODE_BARS,
    NOISE_PAIR_GAP_RANGE,
)
from rl_curriculum.curriculum261_r12_global_k import (
    GLOBAL_ALPHA,
    GLOBAL_K_NULL_RNG_SEED,
    MIN_UNIQUE_NULL_UNITS,
    CellSpec,
    CorpusGraph,
    build_cells,
    build_corpus_graph,
    cell_diagnostics_from_result,
    global_k_audit_contract_digest,
    global_k_audit_contract_payload,
    legacy_positionwise_z_diagnostic,
    observed_cell_sums,
    run_global_k_null,
    run_global_k_audit,
    small_graph_exact_validation,
    _clopper_pearson,
    _make_null_plan,
    _null_replicate_cells,
)
from rl_curriculum.curriculum261_r12_noise_replay import (
    mirror_candidate_count,
    mirror_candidate_positions,
)

N = int(CURRICULUM261_EPISODE_BARS)


def _synthetic_events(seed: int = 7, n_blocks: int = 12, *,
                      hit_bias: float = 0.0,
                      position_bias: int | None = None,
                      boundary_bug: bool = False) -> list[dict]:
    """合成 event trace(真实机制:每 unit 单一 gap;可控偏置注入)。

    - 每 block 抽 8 个位置(20..119),可选注入 position_bias 位置;
    - 每 (block, source) 单元抽一个 gap ∈ U{8..16},镜像落点 = s+gap;
      hit_bias>0 时以该概率强制 gap 对准某事件(整体命中偏置);
      position_bias 指定时,该位置候选窗口内的单元以 0.5+hit_bias
      概率强制命中该位置(特定位置过度命中);
    - K(t) = 落点恰为 t 的镜像数(单一 gap ⇒ 每 unit 至多命中一事件);
    - boundary_bug=True 模拟 R7 的 n-1 边界错误(候选集含越界 source)。
    """
    rng = np.random.default_rng(seed)
    events = []
    for b in range(n_blocks):
        positions = sorted(rng.choice(np.arange(20, 120),
                                      size=8, replace=False).tolist())
        if position_bias is not None:
            positions = sorted(set(positions + [position_bias]))
        cand_by_t = {}
        all_units: set[int] = set()
        for t in positions:
            if boundary_bug:
                cand = list(range(max(1, t - 16),
                                  min(t - 8, N - 1) + 1))
            else:
                cand = mirror_candidate_positions(t, N)
            cand_by_t[t] = cand
            all_units.update(cand)
        # 每 unit 单一 gap 抽签(带可选偏置)
        gap_by_unit: dict[int, int] = {}
        event_set = set(positions)
        for s in sorted(all_units):
            gap = int(rng.integers(NOISE_PAIR_GAP_RANGE[0],
                                   NOISE_PAIR_GAP_RANGE[1] + 1))
            if hit_bias > 0 and rng.random() < hit_bias:
                # 强制对准某个可命中事件(整体命中偏置)
                targets = [t for t in event_set
                           if s in set(cand_by_t[t])]
                if targets:
                    t_hit = targets[int(rng.integers(0, len(targets)))]
                    gap = t_hit - s
            if (position_bias is not None
                    and s in set(cand_by_t.get(position_bias, []))
                    and rng.random() < 0.5 + hit_bias):
                gap = position_bias - s
            gap_by_unit[s] = gap
        mirror_at: dict[int, list[int]] = {}
        for s, g in gap_by_unit.items():
            mirror_at.setdefault(s + g, []).append(s)
        for t in positions:
            mirrors = sorted(mirror_at.get(t, []))
            events.append({
                "block_index": b, "cue_bar": int(t),
                "primary_present": 1 if (1 <= t and t + 16 < N) else 0,
                "k_actual": len(mirrors),
                "mirror_positions": mirrors,
                "mirror_candidates": len(cand_by_t[t]),
            })
    return events


# ------------------------------------------------ 1: 图重建与完整性
def test_graph_reconstruction_integrity():
    events = _synthetic_events()
    g = build_corpus_graph(events, "model")
    assert g.integrity["ok"]
    assert g.integrity["n_events"] == len(events)
    assert g.integrity["n_blocks"] == 12


def test_k_actual_equals_unit_hits_sum():
    """k_actual 必须等于观察到的命中 unit 数(trace 自洽)。"""
    events = _synthetic_events()
    for e in events:
        assert e["k_actual"] == len(e["mirror_positions"])
    g = build_corpus_graph(events, "model")
    assert int(g.ev_k.sum()) == sum(len(e["mirror_positions"])
                                    for e in events)


def test_graph_rejects_candidate_count_mismatch():
    events = _synthetic_events()
    events[0] = dict(events[0])
    events[0]["mirror_candidates"] += 1
    g = build_corpus_graph(events, "model")
    assert not g.integrity["ok"]


def test_graph_rejects_out_of_bound_mirror():
    events = _synthetic_events()
    events[0] = dict(events[0])
    events[0]["mirror_positions"] = list(
        events[0]["mirror_positions"]) + [events[0]["cue_bar"] - 3]
    events[0]["k_actual"] = len(events[0]["mirror_positions"])
    g = build_corpus_graph(events, "model")
    assert not g.integrity["ok"]


def test_graph_rejects_single_gap_double_hit():
    """同一 unit 命中两个事件违背单一 gap 语义。"""
    events = _synthetic_events(seed=11)
    # 找两个相邻位置事件,强行共享一个 mirror source
    by_block: dict[int, list[dict]] = {}
    for e in events:
        by_block.setdefault(e["block_index"], []).append(e)
    b0 = by_block[0]
    t1, t2 = b0[0], b0[1]
    s = t2["cue_bar"] - 8  # s ∈ cand(t2);也构造它在 cand(t1) 内的假命中
    t1["mirror_positions"] = sorted(
        list(t1["mirror_positions"]) + [s])
    t1["k_actual"] = len(t1["mirror_positions"])
    t2["mirror_positions"] = sorted(
        list(t2["mirror_positions"]) + [s])
    t2["k_actual"] = len(t2["mirror_positions"])
    g = build_corpus_graph(events, "model")
    assert not g.integrity["ok"]


# ------------------------------------------------ 2: 共享相关与解析矩
def test_aggregate_moments_not_independent_event_formula():
    """聚合 cell 解析矩必须保留共享单元依赖(≠独立事件公式)。

    构造:2 blocks × 相邻事件,共享 source 单元。
    独立事件公式 Var = Σ_events C(t)p(1-p) 会高估方差(同一 unit
    只能命中一个事件);本实现的 Σq(1-q) 与精确枚举一致。
    """
    events = [
        {"block_index": 0, "cue_bar": 100, "primary_present": 1,
         "k_actual": 0, "mirror_positions": [],
         "mirror_candidates": 9},
        {"block_index": 0, "cue_bar": 101, "primary_present": 1,
         "k_actual": 0, "mirror_positions": [],
         "mirror_candidates": 9},
    ]
    g = build_corpus_graph(events, "m")
    cells = build_cells(g)
    agg = [c for c in cells if c.kind == "corpus_aggregate"]
    # 单元数 17(<30)→ 无资格 cell;直接构造 CellSpec 验矩
    counts: dict[int, int] = {}
    for i in range(len(g.ev_t)):
        for j in range(int(g.ev_unit_ptr[i]),
                       int(g.ev_unit_ptr[i + 1])):
            u = int(g.ev_unit_idx[j])
            counts[u] = counts.get(u, 0) + 1
    spec = CellSpec("m", "corpus_aggregate", None, counts, "m/agg")
    mu, var = spec.moments()
    # 独立事件(错误)公式:2 事件 × 9 单元 × (1/9)(8/9) = 16/9
    wrong = 2 * 9 * (1 / 9) * (8 / 9)
    assert var < wrong  # 共享互斥 ⇒ 方差更小
    # 精确验证(小图枚举函数同源逻辑)
    r = small_graph_exact_validation()
    assert r["ok"]
    # 非平凡共享:至少一个单元服务 >1 事件
    assert max(counts.values()) == 2
    assert mu == pytest.approx(sum(c / 9 for c in counts.values()))


def test_position_cell_moments_classical_binomial():
    """position cell(每单元至多服务 1 事件)退化为经典 Binomial 矩。"""
    events = _synthetic_events(seed=3)
    g = build_corpus_graph(events, "model")
    cells = build_cells(g)
    pos = [c for c in cells if c.kind == "position" and c.t == 100]
    if pos:
        mu, var = pos[0].moments()
        n_units = len(pos[0].unit_event_counts)
        assert mu == pytest.approx(n_units / 9)
        assert var == pytest.approx(n_units * (1 / 9) * (8 / 9))


# ------------------------------------------------ 3: 小图与校准(§14)
def test_small_graph_exact_validation():
    r = small_graph_exact_validation()
    assert r["ok"], r
    assert r["exact_vs_analytic"]["ok"]
    assert r["exact_vs_randomization_global_p"]["ok"]
    assert r["randomization_standardization"]["ok"]


def test_null_calibration_reject_rate():
    """§14.4:正确 null 下 global p 近似均匀(不过度拒绝)。"""
    rng = np.random.default_rng(20270203)
    rejects = 0
    trials = 40
    for trial in range(trials):
        events = _synthetic_events(seed=1000 + trial)
        res = run_global_k_audit({"model": events},
                                 b_tier1=800, b_tier2=None,
                                 null_seed=20270203 + trial)
        if res["final"]["p_global"] <= GLOBAL_ALPHA:
            rejects += 1
    # 40 次试验中拒绝数应与 α=0.05 一致(二项 95% 容差粗界)
    assert rejects <= 6, f"global gate 过度拒绝:{rejects}/{trials}"


def test_injected_hit_bias_rejected():
    """§14.5:source hit 概率偏移必须被拒绝。"""
    events = _synthetic_events(seed=21, hit_bias=0.05)
    res = run_global_k_audit({"model": events}, b_tier1=3000,
                             b_tier2=None, null_seed=20270204)
    assert res["verdict"] == "FAIL"
    assert res["final"]["p_global"] < GLOBAL_ALPHA


def test_injected_position_bias_rejected():
    """§14.5:特定 position 过度命中必须被拒绝。"""
    events = _synthetic_events(seed=22, position_bias=60,
                               hit_bias=0.22)
    res = run_global_k_audit({"model": events}, b_tier1=3000,
                             b_tier2=None, null_seed=20270205)
    assert res["verdict"] == "FAIL"


def test_boundary_bug_rejected():
    """§14.3:n-1 边界错误在尾部位置(t>=272)产生不同 candidate
    graph(N-1 vs N-17),被图完整性与确定性 tail gate 拒绝。"""
    events = []
    for t in (272, 276, 280):
        cand_bug = list(range(max(1, t - 16), min(t - 8, N - 1) + 1))
        events.append({
            "block_index": 0, "cue_bar": t, "primary_present": 0,
            "k_actual": 0, "mirror_positions": [],
            "mirror_candidates": len(cand_bug)})
    g = build_corpus_graph(events, "model")
    assert not g.integrity["ok"]
    # 中部位置(t<272)两者一致——回归保护(同构造必须通过)
    events_mid = [{
        "block_index": 0, "cue_bar": 100, "primary_present": 1,
        "k_actual": 0, "mirror_positions": [],
        "mirror_candidates": len(mirror_candidate_positions(100, N))}]
    g2 = build_corpus_graph(events_mid, "model")
    assert g2.integrity["ok"]


def test_combined_model_validation_max():
    """§14.7:双 corpus 时 T 覆盖双方 cell(单 corpus 通过不必然)。"""
    ev_m = _synthetic_events(seed=31)
    ev_v = _synthetic_events(seed=32, hit_bias=0.06)
    res = run_global_k_audit({"model": ev_m, "validation": ev_v},
                             b_tier1=3000, b_tier2=None)
    assert res["verdict"] == "FAIL"
    assert res["n_eligible_cells"] == sum(
        res["cells_by_corpus"].values())
    # argmax 应在 validation(注入偏置侧)
    assert res["argmax_cell"].startswith("validation/")


def test_global_p_finite_sample_formula():
    """p_global = (1 + count)/(B + 1)(加一修正)。"""
    r = run_global_k_null(
        {("g"): build_corpus_graph(_synthetic_events(41), "g")},
        {"g": build_cells(build_corpus_graph(
            _synthetic_events(41), "g"))},
        t_obs=0.0, b_total=500, seed=123)
    # t_obs=0 ⇒ 全部 T_null >= 0 ⇒ count = B ⇒ p = (B+1)/(B+1) = 1
    assert r["p_global"] == 1.0
    r2 = run_global_k_null(
        {"g": build_corpus_graph(_synthetic_events(41), "g")},
        {"g": build_cells(build_corpus_graph(
            _synthetic_events(41), "g"))},
        t_obs=1e9, b_total=500, seed=123)
    # 不可能超过 ⇒ count=0 ⇒ p = 1/501
    assert r2["p_global"] == pytest.approx(1 / 501)


def test_stream_continuation_prefix_digest():
    """§14.8:tier2 复用同 stream,前缀 chunk digest 逐位一致。"""
    graphs = {"g": build_corpus_graph(_synthetic_events(51), "g")}
    cells = {"g": build_cells(graphs["g"])}
    t1 = run_global_k_null(graphs, cells, 5.0, 2 * 100,
                           seed=GLOBAL_K_NULL_RNG_SEED, chunk_size=100)
    t2 = run_global_k_null(graphs, cells, 5.0, 4 * 100,
                           seed=GLOBAL_K_NULL_RNG_SEED, chunk_size=100,
                           prior_chunks=t1["chunk_digests"])
    assert t2["chunk_digests"][:2] == t1["chunk_digests"]
    # 前缀不一致必须 fail closed
    bad = list(t1["chunk_digests"])
    bad[0] = "0" * 64
    with pytest.raises(RuntimeError):
        run_global_k_null(graphs, cells, 5.0, 4 * 100,
                          seed=GLOBAL_K_NULL_RNG_SEED, chunk_size=100,
                          prior_chunks=bad)


def test_indeterminate_counts_as_fail():
    res = run_global_k_audit(
        {"model": _synthetic_events(61)}, b_tier1=200, b_tier2=400,
        null_seed=GLOBAL_K_NULL_RNG_SEED)
    # 无论 verdict 为何,INDETERMINATE 不得计 PASS
    if res["verdict"] == "INDETERMINATE":
        assert res["pass"] is False
        assert res["final"]["indeterminate"] is True


def test_clopper_pearson_bounds():
    lo, hi = _clopper_pearson(2500, 50_000)
    assert lo < 0.05 < hi  # 0.05 恰好压线 ⇒ 区间跨越
    lo2, hi2 = _clopper_pearson(0, 50_000)
    assert lo2 == 0.0 and hi2 < 0.001
    lo3, hi3 = _clopper_pearson(50_000, 50_000)
    assert hi3 == 1.0 and lo3 > 0.999


# ------------------------------------------------ 4: tail 分类与 legacy
def test_true_tail_classification():
    assert mirror_candidate_positions(270, N)
    cells = build_cells(build_corpus_graph(_synthetic_events(71), "m"))
    tail = [c for c in cells
            if c.kind == "true_tail_aggregate"]
    # 合成语料位置 < 264 ⇒ 无 tail 事件 ⇒ tail cell 不存在
    assert not tail
    ev = _synthetic_events(72)
    # 跨 block 添加 6 个 tail 事件(每事件 ~7-9 单元 ⇒ 合计 ≥30,
    # 满足预注册资格;真实机制由生成器保证单一 gap)
    for b in range(6):
        cand = mirror_candidate_positions(270, N)
        mirrors = cand[:1]  # 命中 1 个(合法:mirror ∈ cand)
        ev.append({
            "block_index": 100 + b, "cue_bar": 270,
            "primary_present": 0,
            "k_actual": len(mirrors),
            "mirror_positions": sorted(mirrors),
            "mirror_candidates": len(cand)})
    cells2 = build_cells(build_corpus_graph(ev, "m"))
    tail_cells = [c for c in cells2
                  if c.kind == "true_tail_aggregate"]
    assert tail_cells, "tail 事件 ≥30 单元 ⇒ tail aggregate 应合格"
    rows = cell_diagnostics_from_result(
        {"tier1": {"b_total": 0}}, {"m": ev})
    tail_rows = [r for r in rows
                 if r["cell_kind"] == "true_tail_aggregate"]
    assert tail_rows and tail_rows[0]["is_true_tail"] is True


def test_t226_is_not_tail():
    """§2/§12:t=226 < 264,不是 tail;合同 payload 明确记录。"""
    payload = global_k_audit_contract_payload()
    assert payload["tail_definition"]["t226_is_tail"] is False
    assert payload["tail_definition"]["true_tail"].startswith(
        "t >= 264")
    assert "position-wise mirror-count distribution failure" \
        in payload["tail_definition"]["t226_classification"]


def test_legacy_diagnostic_demoted_fields():
    events = _synthetic_events(81)
    d = legacy_positionwise_z_diagnostic(events)
    assert d["binding_gate"] is False
    assert d["legacy_diagnostic_only"] is True
    assert d["z_threshold"] == 4.0


def test_contract_payload_and_digest_stable():
    payload = global_k_audit_contract_payload()
    d1 = global_k_audit_contract_digest()
    assert d1.startswith("r12gk-")
    p2 = global_k_audit_contract_payload()
    assert payload == p2  # 纯函数,无状态
    assert global_k_audit_contract_digest() == d1
    assert payload["global_test"]["alpha"] == 0.05
    assert payload["global_test"]["tier1_B"] == 50_000
    assert payload["global_test"]["tier2_B"] == 200_000
    assert payload["cells"]["eligibility"][
        "min_unique_underlying_null_units"] == 30


# ------------------------------------------------ 5: 逐 cell 诊断
def test_cell_diagnostics_holm_and_marginal():
    events = {"model": _synthetic_events(91)}
    res = run_global_k_audit(events, b_tier1=1000, b_tier2=None)
    rows = cell_diagnostics_from_result(res, events)
    assert rows
    m = len(rows)
    for r in rows:
        assert "holm_adjusted_p" in r and "bonferroni_adjusted_p" in r
        assert r["m_cells"] == m
        assert r["bonferroni_adjusted_p"] >= r[
            "unadjusted_conditional_p"] - 1e-12
        assert r["holm_adjusted_p"] >= r[
            "unadjusted_conditional_p"] - 1e-12
        if r["cell_kind"] == "position":
            mc = r["marginal_cross_check"]
            assert mc["marginal_cross_check_only"] is True
            assert "probability-ordering" in mc["definition"]
    # Holm ≤ Bonferroni
    for r in rows:
        assert r["holm_adjusted_p"] <= r[
            "bonferroni_adjusted_p"] + 1e-12


# ------------------------------------------------ 6: R11 legacy 复现
def _r11_trace_path() -> Path | None:
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        p = (cand / "stage2_6_1" / "artifacts" / "repair11"
             / "cue_event_trace.jsonl")
        if p.is_file():
            return p
    return None


def test_r11_legacy_z_reproduction():
    """§13-1:R11 t=226 legacy z≈4.000504 精确复现(trace 存在时)。"""
    p = _r11_trace_path()
    if p is None:
        pytest.skip("R11 event trace 不可达")
    events = {"model": []}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("corpus") == "model":
                events["model"].append(row)
    d = legacy_positionwise_z_diagnostic(events["model"])
    row226 = next(r for r in d["positions"]
                  if r.get("t") == 226 and r.get("z") is not None)
    assert row226["n_events"] == 31
    assert row226["c"] == 9
    assert row226["k_mean"] == pytest.approx(1.6774193548387097,
                                             abs=1e-12)
    assert row226["z"] == pytest.approx(4.000504000506, abs=1e-9)
    assert d["legacy_all_ok"] is False  # legacy FAIL 保持


# ------------------------------------------------ 7: 篡改拒绝(§14.9)
def test_graph_tamper_rejected_via_audit_fail_closed():
    """图/语料篡改 ⇒ 完整性失败 ⇒ audit FAIL(fail closed)。"""
    events = _synthetic_events(101)
    bad = copy.deepcopy(events)
    bad[0]["mirror_candidates"] += 1
    res = run_global_k_audit({"model": bad}, b_tier1=100,
                             b_tier2=None)
    assert res["pass"] is False
    assert res["graph_integrity_ok"] is False


def test_null_seed_is_identity_bounded():
    """null seed 是合同身份:改变 seed ⇒ 不同 chunk digest(可检测)。"""
    graphs = {"g": build_corpus_graph(_synthetic_events(111), "g")}
    cells = {"g": build_cells(graphs["g"])}
    a = run_global_k_null(graphs, cells, 5.0, 200, seed=1,
                          chunk_size=100)
    b = run_global_k_null(graphs, cells, 5.0, 200, seed=2,
                          chunk_size=100)
    assert a["chunk_digests"] != b["chunk_digests"]
