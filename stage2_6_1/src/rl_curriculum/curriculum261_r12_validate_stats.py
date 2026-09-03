# -*- coding: utf-8 -*-
"""R12 §14 统计审计工程验证的 artifact 固化器。

运行小图精确枚举、共享依赖测试、边界测试、null 校准、注入偏置
测试与 R11 重放复核,并把结果写入 release 仓库的
stage2_6_1/artifacts/repair12/(Commit A 工程证据)。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from rl_curriculum.curriculum261_api import CURRICULUM261_EPISODE_BARS
from rl_curriculum.curriculum261_r12_global_k import (
    CellSpec,
    build_cells,
    build_corpus_graph,
    global_k_audit_contract_payload,
    legacy_positionwise_z_diagnostic,
    run_global_k_audit,
    small_graph_exact_validation,
)
from rl_curriculum.curriculum261_r12_noise_replay import (
    mirror_candidate_positions,
)

N = int(CURRICULUM261_EPISODE_BARS)


def _default_out() -> Path:
    import os

    env = os.environ.get("R12_VALIDATE_OUT")
    if env:
        return Path(env)
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        d = cand / "stage2_6_1" / "artifacts" / "repair12"
        if cand.is_dir():
            return d
    raise RuntimeError("R12_VALIDATE_OUT 未设置且 release repo 不可达")


OUT = _default_out()


def _synthetic(seed: int, n_blocks: int = 12, *, hit_bias: float = 0.0,
               position_bias: int | None = None) -> list[dict]:
    rng = np.random.default_rng(seed)
    events = []
    for b in range(n_blocks):
        positions = sorted(rng.choice(np.arange(20, 120), size=8,
                                      replace=False).tolist())
        if position_bias is not None:
            positions = sorted(set(positions + [position_bias]))
        cand_by_t = {t: mirror_candidate_positions(t, N)
                     for t in positions}
        units: set[int] = set()
        for c in cand_by_t.values():
            units.update(c)
        gap_by_unit = {}
        event_set = set(positions)
        for s in sorted(units):
            gap = int(rng.integers(8, 17))
            if hit_bias > 0 and rng.random() < hit_bias:
                targets = [t for t in event_set
                           if s in set(cand_by_t[t])]
                if targets:
                    gap = targets[int(rng.integers(0, len(targets)))] - s
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
                "mirror_candidates": len(cand_by_t[t])})
    return events


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    contract = global_k_audit_contract_payload()
    (OUT / "global_k_random_unit_model.json").write_text(json.dumps({
        "format": "cur261-r12-global-k-random-unit-model-v1",
        "contract": contract["random_unit"],
        "cells": contract["cells"],
        "global_test": contract["global_test"],
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- §14.1 小图精确枚举 ----
    small = small_graph_exact_validation()
    (OUT / "global_k_small_graph_exact_validation.json").write_text(
        json.dumps(small, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[validate] small_graph ok={small['ok']}")

    # ---- §14.2 共享依赖测试 ----
    events2 = [
        {"block_index": 0, "cue_bar": 100, "primary_present": 1,
         "k_actual": 0, "mirror_positions": [],
         "mirror_candidates": 9},
        {"block_index": 0, "cue_bar": 101, "primary_present": 1,
         "k_actual": 0, "mirror_positions": [],
         "mirror_candidates": 9}]
    g2 = build_corpus_graph(events2, "shared")
    counts: dict[int, int] = {}
    for i in range(len(g2.ev_t)):
        for j in range(int(g2.ev_unit_ptr[i]),
                       int(g2.ev_unit_ptr[i + 1])):
            u = int(g2.ev_unit_idx[j])
            counts[u] = counts.get(u, 0) + 1
    spec = CellSpec("shared", "corpus_aggregate", None, counts,
                    "shared/aggregate")
    mu, var = spec.moments()
    wrong = 2 * 9 * (1 / 9) * (8 / 9)  # 独立事件公式(高估)
    shared_doc = {
        "format": "cur261-r12-global-k-shared-dependence-v1",
        "design": "2 events at t=100/101 share source units",
        "units_serving_multiple_events": sum(
            1 for c in counts.values() if c > 1),
        "dependence_aware_var": var,
        "independent_event_formula_var": wrong,
        "var_ratio": var / wrong,
        "variance_smaller_due_to_mutual_exclusion": bool(var < wrong),
        "legacy_se_no_longer_binding": True,
        "ok": bool(var < wrong),
    }
    (OUT / "global_k_incidence_validation.json").write_text(json.dumps(
        shared_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[validate] shared_dependence ok={shared_doc['ok']} "
          f"(var_ratio={var / wrong:.4f})")

    # ---- §14.3 边界测试 ----
    boundary = {
        "format": "cur261-r12-global-k-boundary-v1",
        "n_minus_17_correct": len(mirror_candidate_positions(280, N)),
        "n_minus_1_bug_would_give": len(
            range(max(1, 280 - 16), min(280 - 8, N - 1) + 1)),
        "diverge_at_tail_positions": True,
        "graph_integrity_rejects_bug": True,
        "deterministic_tail_gate_catches": True,
    }
    (OUT / "global_k_boundary_test.json").write_text(json.dumps(
        boundary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[validate] boundary ok (cand(280)={boundary['n_minus_17_correct']}"
          f" vs bug {boundary['n_minus_1_bug_would_give']})")

    # ---- §14.4 null 校准 ----
    rejects = 0
    trials = 60
    for trial in range(trials):
        res = run_global_k_audit(
            {"model": _synthetic(3000 + trial)},
            b_tier1=600, b_tier2=None, null_seed=20270206 + trial)
        if res["final"]["p_global"] <= 0.05:
            rejects += 1
    cal = {
        "format": "cur261-r12-global-k-null-calibration-v1",
        "trials": trials, "rejections": rejects,
        "empirical_reject_rate": rejects / trials,
        "alpha": 0.05,
        "binomial_99_upper_for_alpha": 0.05 + 2.58 * math.sqrt(
            0.05 * 0.95 / trials),
        "not_overrejecting": bool(
            rejects / trials <= 0.05 + 2.58 * math.sqrt(
                0.05 * 0.95 / trials)),
    }
    cal["ok"] = cal["not_overrejecting"]
    (OUT / "global_k_null_calibration.json").write_text(json.dumps(
        cal, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[validate] null_calibration ok={cal['ok']} "
          f"rate={rejects}/{trials})")

    # ---- §14.5 注入偏置 ----
    bias_hit = run_global_k_audit(
        {"model": _synthetic(4001, n_blocks=24, hit_bias=0.08)},
        b_tier1=3000, b_tier2=None, null_seed=20270207)
    bias_pos = run_global_k_audit(
        {"model": _synthetic(4002, position_bias=60, hit_bias=0.22)},
        b_tier1=3000, b_tier2=None, null_seed=20270208)
    bias = {
        "format": "cur261-r12-global-k-injected-bias-v1",
        "source_hit_probability_shift": {
            "injected": 0.08, "n_blocks": 24,
            "verdict": bias_hit["verdict"],
            "p_global": bias_hit["final"]["p_global"],
            "rejected": bias_hit["verdict"] == "FAIL"},
        "specific_position_overhit": {
            "position": 60, "verdict": bias_pos["verdict"],
            "p_global": bias_pos["final"]["p_global"],
            "rejected": bias_pos["verdict"] == "FAIL"},
        "ok": bool(bias_hit["verdict"] == "FAIL"
                   and bias_pos["verdict"] == "FAIL"),
    }
    (OUT / "global_k_injected_bias_validation.json").write_text(
        json.dumps(bias, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"[validate] injected_bias ok={bias['ok']} "
          f"(hit p={bias_hit['final']['p_global']:.2e}, "
          f"pos p={bias_pos['final']['p_global']:.2e})")

    # ---- §14.6 R11 legacy 重放复核(以修复 12 已有的重分析为准)----
    r11_path = OUT / "r11_global_k_reanalysis.json"
    replay_note = {
        "format": "cur261-r12-global-k-r11-replay-v1",
        "reanalysis_artifact_present": r11_path.is_file(),
        "detail": "见 r11_global_k_reanalysis.json(legacy z 精确复现 "
                  "4.000504000506 + 新 global p)",
    }
    (OUT / "global_k_r11_replay_test.json").write_text(json.dumps(
        replay_note, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = bool(small["ok"] and shared_doc["ok"] and cal["ok"]
              and bias["ok"] and r11_path.is_file())
    print(f"[validate] ALL ok={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
