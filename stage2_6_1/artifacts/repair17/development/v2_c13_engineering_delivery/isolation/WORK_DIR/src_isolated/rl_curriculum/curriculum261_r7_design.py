# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R7:clean matched-ladder design(shared cue gate
先行 + candidate 选择解耦 + §16.2 硬治理)。

R6 教训(R7 硬输入):
- R6 的 cue recall 点阈值(0.95)在生成器固有检出率期望之上且
  matched 下跨 candidate 相同,8 个 candidate 被同一共享指标同时
  误杀(§2.4)——R7 把 shared cue 指标与 candidate selection 解耦
  (§12):shared gate 每 corpus 一次,FAIL 即整个 design FAIL;
  candidate 之间只比较 matched power/margins/payoff false-cue/
  precision/density/observability/independence;
- R6 在 design plan 锁定并生成数据后改统计代码、删旧 plan 同
  namespace 重锁——formal evidence 无效(§2.3)。R7 治理(§16.2):
  design data 生成开始即写 started 事件;此后任何代码/评估器缺陷
  => write_r7_iteration_aborted + 本 iteration 永久结束(不删 plan、
  不重锁、不复用 namespace)。

matched-ladder 核心(R6 冻结实现,零修改复用):generate_matched_
block_with_attempts / build_c2_block_evidence_table / matched_gap_
stats / simulate_formal_gate_pass_r6_matched / scrambled_gap_control
全部 import 自 curriculum261_r6_tape / curriculum261_r6_pairs
(R6 模块 sha256 进入本模块 DESIGN_CODE_MODULES_R7 的 code identity)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
from rl_curriculum.curriculum261_c2 import FAMILY_C2
from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
from rl_curriculum.curriculum261_r6_pairs import (
    C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES_R6,
    C2_DENSITY_MIN_REFERENCE_LONG_RATE_R6,
    FORMAL_BLOCK_OPTIONS,
    R6_POSITIVE_GAP_RATE_MIN,
    block_difficulty_series,
    block_margin_series,
    build_c2_block_evidence_table,
    c2_marginal_guard_conditions,
    check_c2_cue_payoff_separation,
    scrambled_gap_control,
    simulate_formal_gate_pass_r6_matched,
)
from rl_curriculum.curriculum261_r6_param_pack import (
    R4_PARAMETER_PACK_DIGEST,
    R5_DESIGN_PLAN_DIGEST,
    ladder_distance_from_historical,
    validate_ladder_semantics,
)
from rl_curriculum.curriculum261_r6_tape import (
    block_attempt_statistics,
    generate_matched_block_with_attempts,
    matched_block_corpus_summary,
    matched_ladder_contract_identity,
)
from rl_curriculum.curriculum261_r5_pairs import (
    corpus_conditions_r5,
    density_gate_r5,
)
from rl_curriculum.curriculum261_r4_pairs import evaluate_pair_corpus_r4
from rl_curriculum.curriculum261_r7_cue_contract import (
    ABSOLUTE_MINIMUM_RECALL,
    C2_CUE_PRECISION_MIN,
    C2_NON_CUE_FALSE_POSITIVE_MAX,
    C2_PAYOFF_BAR_FALSE_CUE_MAX,
    C2_CUE_SEMANTIC_CONTRACT_VERSION,
    MIN_UNIQUE_POSITIVE_CUES,
    NONINFERIORITY_DELTA,
    cue_semantic_contract_digest,
    recall_floor,
)
from rl_curriculum.curriculum261_r7_cue_eval import (
    candidate_cue_semantics,
    cue_semantic_rule_identity,
    shared_cue_semantic_gate,
)
from rl_curriculum.curriculum261_r7_namespaces import (
    design_data_started,
    mark_design_data_started,
    require_r7_iteration_active,
    write_r7_iteration_aborted,
)
from rl_curriculum.curriculum261_r7_param_pack import (
    C2_LADDER_CANDIDATES_R7,
    R6_DESIGN_PLAN_DIGEST,
    R7_PACK_VERSION,
    ladder_pack_payload_r7,
    ladder_distance_from_historical_r7,
    pack_digest_r7,
    r7_candidate_grid,
    validate_r7_grid_semantics,
    write_selected_pack_r7,
)

DESIGN_FORMAT_R7 = "cur261-r7-design-plan-v1"
DESIGN_BLOCKS_PER_CORPUS_R7 = 40
DESIGN_NAMESPACES_R7 = ("design_r7_matched_main",
                        "design_r7_matched_validation")
DESIGN_INDEPENDENT_NAMESPACE_R7 = "design_r7_independent_marginal"
DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R7 = 20

DESIGN_TARGET_GAP_FACTOR = 3.0
DESIGN_TARGET_D3_FACTOR = 2.5
DESIGN_TARGET_MARGIN_FACTOR = 2.5
DESIGN_TARGET_GATE_PROB = 0.90

#: §16.1/§17 code identity 覆盖面(R7 全部实现 + R6 冻结复用模块 +
#: 合同依赖;design data 生成开始后任何漂移 => iteration aborted)。
DESIGN_CODE_MODULES_R7 = (
    "curriculum261_api.py",
    "curriculum261_c2.py",
    "curriculum261_pairs.py",
    "curriculum261_qualification.py",
    "curriculum261_r4_pairs.py",
    "curriculum261_r5_pairs.py",
    "curriculum261_r6_tape.py",
    "curriculum261_r6_param_pack.py",
    "curriculum261_r6_namespaces.py",
    "curriculum261_r6_pairs.py",
    "curriculum261_r7_cue_contract.py",
    "curriculum261_r7_cue_eval.py",
    "curriculum261_r7_namespaces.py",
    "curriculum261_r7_param_pack.py",
    "curriculum261_r7_design.py",
)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _code_identity_design() -> dict[str, str]:
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in DESIGN_CODE_MODULES_R7:
        f = root / name
        out[name] = hashlib.sha256(
            f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    return out


# ------------------------------------------------------------- plan
def design_plan_payload_r7(*, baseline_commit: str, vendor_pin: str,
                           v2_contract_digest: str,
                           prior_r2_plan_digest: str,
                           prior_diag262r2_plan_digest: str,
                           cue_audit: dict[str, Any],
                           preplan_smoke_identity: dict[str, Any],
                           ) -> dict[str, Any]:
    """构建并返回 R7 design plan payload(锁定后不得修改任何字段)。

    §17 绑定清单全集:baseline/vendor/R4 pack/R5+R6 historical digests/
    V2 contract/matched contract/cue semantic contract/p_contract/
    noninferiority delta/recall floor/cluster bootstrap 方法/CI 方法/
    candidate grid/formal block options/design block count/全部阈值/
    selection rule/independent marginal guard/code identity/Route C
    identity/preplan smoke identity。
    """
    from rl_platform.versions import (
        ENV_CORE_VERSION, OBSERVATION_SPEC_VERSION)

    grid = r7_candidate_grid()
    problems = validate_r7_grid_semantics()
    if problems:
        raise RuntimeError(f"R7 candidate grid 语义非法: {problems}")
    p_contract = float(cue_audit["p_contract"])
    floor = recall_floor(p_contract)
    return {
        "format": DESIGN_FORMAT_R7,
        "iteration": "r7",
        "baseline_commit": baseline_commit,
        "vendor_pin": vendor_pin,
        "r4_parameter_pack_digest": R4_PARAMETER_PACK_DIGEST,
        "r5_design_plan_digest": R5_DESIGN_PLAN_DIGEST,
        "r6_design_plan_digest": R6_DESIGN_PLAN_DIGEST,
        "preprocessing_v2_contract_digest": v2_contract_digest,
        "prior_digests": {
            "stage2_6_1_r2_qualification_plan_digest": prior_r2_plan_digest,
            "stage2_6_2_r2_diagnostic_plan_digest":
                prior_diag262r2_plan_digest,
        },
        "route_c_identities": {
            "env_core_version": ENV_CORE_VERSION,
            "observation_spec_version": OBSERVATION_SPEC_VERSION,
        },
        "matched_ladder": {
            "contract_version": "C2MatchedLadderBlock-v1",
            "contract_identity": matched_ladder_contract_identity(),
            "implementation": "R6 冻结实现零修改复用(import,不复制);"
                              "R6 tape/pairs 模块 sha256 进入 "
                              "code_identity,design data 生成开始后任何"
                              "漂移 => iteration aborted(§16.2)",
            "shared_components": [
                "cue_time_table", "cue_direction_table",
                "wick_direction_context_chain",
                "wick_width_context_chain", "volume_path",
                "base_noise_innovations", "wick_jitter",
                "initial_price", "episode_duration", "bar_timestamps",
                "ab_variant_structure"],
            "rung_varying": ["alpha_bps", "wick_kappa"],
            "block_attempt_semantics": {
                "max_attempts": 5,
                "unit": "完整四-rung block",
            },
        },
        "cue_semantic_contract": {
            "version": C2_CUE_SEMANTIC_CONTRACT_VERSION,
            "contract_digest": cue_semantic_contract_digest(),
            "rule_identity": cue_semantic_rule_identity(),
            "audit_digest": cue_audit["audit_digest"],
            "p_contract": p_contract,
            "noninferiority_delta": NONINFERIORITY_DELTA,
            "absolute_minimum_recall": ABSOLUTE_MINIMUM_RECALL,
            "recall_floor": floor,
            "recall_floor_formula": "max(absolute_minimum_recall, "
                                    "p_contract - noninferiority_delta)",
            "cluster_unit": "matched_block",
            "canonical_observation": "D0/A",
            "cluster_bootstrap": {
                "resamples": 20000, "seed": 20260925,
                "method": "重采样完整 matched block;cluster 内 pooled "
                          "聚合;lower = α 分位(单侧 95% LCB),upper = "
                          "1-α 分位(单侧 95% UCB)",
            },
            "shared_gate_candidate_independent": True,
            "candidate_specific": ["payoff-bar false-cue UCB",
                                   "cue precision LCB"],
            "thresholds": {
                "cue_precision_min": C2_CUE_PRECISION_MIN,
                "non_cue_false_positive_max":
                    C2_NON_CUE_FALSE_POSITIVE_MAX,
                "payoff_bar_false_cue_max": C2_PAYOFF_BAR_FALSE_CUE_MAX,
                "min_unique_positive_cues": MIN_UNIQUE_POSITIVE_CUES,
            },
        },
        "candidate_grid": {
            "candidates": {k: {r: dict(v[r])
                               for r in ("D0", "D1", "D2", "D3")}
                           for k, v in grid.items()},
            "n_candidates": len(grid),
            "allowed_axes": ["alpha_bps", "wick_kappa"],
            "historical_control": "c2l_historical_control(冻结默认;"
                                  "非选择性 control,不达标不得被选中)",
            "grid_bounds": "§13:数量 3-4;非历史 candidate 的 D3 alpha "
                           "∈[28,32];严格单调;不含 R6 已证明 D3 margin "
                           "不足的 α<=26 方案",
        },
        "design_data": {
            "blocks_per_candidate_per_corpus": DESIGN_BLOCKS_PER_CORPUS_R7,
            "corpora": list(DESIGN_NAMESPACES_R7),
            "corpora_role": "main/validation 均为参数开发数据,不得称为"
                            "holdout",
            "evaluation_mode": "raw(preproc=None)",
            "block_schedule_sharing": "不同 candidate 的同 block_index "
                                      "结构带逐位一致(seed 派生不含难度"
                                      "参数);shared gate 显式对比跨 "
                                      "candidate cue 表 digest 验证",
        },
        "formal_block_options": list(FORMAL_BLOCK_OPTIONS),
        "statistics": {
            "pair_table": "R4 唯一 pair 证据表(evaluate_pair_corpus_r4)",
            "block_table": "唯一 C2 block 证据表(r6bt schema)",
            "difficulty": "reference_pair - always_flat_pair",
            "gap_se": "std(blockwise gap, ddof=1)/sqrt(n_blocks);禁止 "
                      "sqrt(SE_hi^2+SE_lo^2)",
            "power_targets": {
                "gap_ge": f"{DESIGN_TARGET_GAP_FACTOR}x expected block SE",
                "d3_ge": f"{DESIGN_TARGET_D3_FACTOR}x expected block SE",
                "margins_d2_d3_ge": f"{DESIGN_TARGET_MARGIN_FACTOR}x "
                                    "expected block SE",
                "positive_gap_block_rate_min": R6_POSITIVE_GAP_RATE_MIN,
                "formal_gate_probability_min": DESIGN_TARGET_GATE_PROB,
            },
            "formal_gate_simulation": {
                "n_sim": 20000, "seed": 20260922,
                "resample_unit": "完整 block(bootstrap 不拆块)",
            },
            "scrambled_control": "仅诊断(permute 后 unpaired SE 对比;"
                                 "不参与任何 PASS 判定)",
        },
        "independent_marginal_guard": {
            "namespace": DESIGN_INDEPENDENT_NAMESPACE_R7,
            "pairs_per_rung": DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R7,
            "conditions": "marginal ordering / D3 positive / 基线 margins"
                          ">0 / integrity=1.0 / oracle / 密度 / local "
                          "cue independence / context observability / "
                          "cluster-aware cue semantic gate;不要求 "
                          "matched gap 1.5xSE;matched PASS 不可覆盖 "
                          "FAIL;失败 → R7 = FAIL(§21)",
            "timing": "design 选定 candidate 后、pack 锁定前",
        },
        "selection_rule": {
            "qualification": "(candidate, n) 在两个 design corpus 均满足"
                             "全部 matched power 硬门槛 + candidate-"
                             "specific 语义(§19.2/§19.3);shared cue "
                             "gate 与 selection 解耦(§12)",
            "order": ["最小 formal block count n(10→15→20)",
                      "maximin score 最大(该 n 下)",
                      "参数偏离历史最小", "candidate id 稳定排序"],
            "maximin_score": "min over {gap/SE ×3, d3/SE, d3 margin/SE "
                             "×2, pos_rate/0.65, 密度比, payoff-fc UCB "
                             "余量 1-fc/0.06, precision LCB 余量 "
                             "prec/0.85} × 两 corpus(不含 shared recall;"
                             "§12)",
            "hard_rule": "先选最小 n,再选该 n 下 score 最高者;平局取 "
                         "distance 最小;禁止事后扩大 block 数;禁止删除"
                         "失败 candidate;不得用 R6 的 n=15 结果预指定",
        },
        "fail_path": {
            "on_shared_gate_fail": "任一 corpus shared cue semantic gate "
                                   "FAIL → R7 design FAIL(不进行 "
                                   "candidate 选择)",
            "on_no_qualified_combination": "R7 = FAIL;自动 power/semantic "
                                           "summary;保留 block tables;"
                                           "报告 binding condition;不生成"
                                           " pack;不访问 marginal/"
                                           "calibration/final namespace;"
                                           "不写 exposure marker;不运行 "
                                           "full-cold(§20)",
            "no_rescue": "不得通过修改 recall floor/delta/candidate/n "
                         "救援",
        },
        "preplan_smoke_identity": preplan_smoke_identity,
        "code_identity": _code_identity_design(),
    }


def design_plan_digest_r7(plan: dict[str, Any]) -> str:
    payload = dict(plan)
    payload.pop("locked_utc", None)
    return "r7dp-" + hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()


def lock_design_plan_r7(out_dir: Path, plan: dict[str, Any],
                        ) -> tuple[Path, str]:
    """锁定 design plan(O_CREAT|O_EXCL;已存在即拒——不删旧重锁)。"""
    from datetime import datetime, timezone

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "r7_design_plan.json"
    if path.exists():
        raise RuntimeError(
            f"R7 design plan 已存在: {path}(§16.2 禁止删除/覆盖/重锁;"
            "重锁必须换新 iteration R7.1/R8)")
    digest = design_plan_digest_r7(plan)
    plan = dict(plan)
    plan["design_plan_digest"] = digest
    plan["locked_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    (out_dir / "r7_design_plan_digest.txt").write_text(
        digest, encoding="utf-8")
    return path, digest


def load_locked_design_plan_r7(out_dir: Path,
                               ) -> tuple[dict[str, Any], str]:
    out_dir = Path(out_dir)
    path = out_dir / "r7_design_plan.json"
    if not path.is_file():
        raise RuntimeError(f"R7 design plan 未锁定: {path}")
    plan = json.loads(path.read_text(encoding="utf-8"))
    digest = design_plan_digest_r7(plan)
    if plan.get("design_plan_digest") != digest:
        raise RuntimeError("R7 design plan digest 复算不一致(fail closed)")
    digest_path = out_dir / "r7_design_plan_digest.txt"
    if not digest_path.is_file() or \
            digest_path.read_text(encoding="utf-8").strip() != digest:
        raise RuntimeError("R7 design plan digest 文件与 payload 不一致")
    return plan, digest


def verify_design_code_identity(plan: dict[str, Any]) -> dict[str, Any]:
    """§16.2:design data 已生成后 code identity 漂移 => aborted。"""
    current = _code_identity_design()
    locked = plan.get("code_identity", {})
    drift = {k: {"locked": locked.get(k), "current": current[k]}
             for k in current
             if locked.get(k) != current[k]}
    if drift and design_data_started():
        write_r7_iteration_aborted(
            f"design data 已生成后 code identity 漂移: {sorted(drift)}")
    return {
        "current": current,
        "drift": drift,
        "pass": not drift,
    }


# ------------------------------------------------- candidate 评估
def _se_at_n(sd: float, n: int) -> float:
    return float(sd) / float(np.sqrt(n))


def _reference_long_label_rate(records: list[Any], rung_params: dict,
                               thresholds: dict) -> float:
    from rl_curriculum.curriculum261_r6_design import (
        _reference_long_label_rate as _impl,
    )

    return _impl(records, rung_params, thresholds)


def _evaluate_candidate_matched_r7(
        candidate_id: str, ladder: dict[str, dict[str, Any]],
        corpus_ns: str, thresholds: dict,
        blocks: list[Any] | None = None,
        n_blocks: int = DESIGN_BLOCKS_PER_CORPUS_R7,
) -> dict[str, Any]:
    """单 candidate 在单 design corpus:matched blocks(可注入已生成的
    blocks——shared gate 需要先于 candidate 评估且复用同一批数据)→
    唯一 pair 表 → 唯一 block 表 → 全部 n 选项硬门槛 + R7 语义。"""
    if blocks is None:
        blocks = [generate_matched_block_with_attempts(
            ladder, namespace=corpus_ns, block_index=i)
            for i in range(n_blocks)]
    records = [blk.pair_records[rung]
               for blk in blocks for rung in CURRICULUM261_RUNGS]
    ev = evaluate_pair_corpus_r4(
        records, FAMILY_C2, ladder, thresholds,
        preproc=None, corpus=corpus_ns)
    block_table = build_c2_block_evidence_table(
        ev["pair_table"], blocks, corpus_ns)

    rungs = CURRICULUM261_RUNGS
    baselines = ("always_long", "c2_local_only")
    gap_series = {
        f"{rungs[k]}-{rungs[k + 1]}": _gap_series(
            block_table, rungs[k], rungs[k + 1])
        for k in range(3)}

    per_n: dict[str, Any] = {}
    for n in FORMAL_BLOCK_OPTIONS:
        gap_checks: dict[str, Any] = {}
        gaps_ok = True
        for name, series in gap_series.items():
            sd = float(np.std(series, ddof=1))
            se = _se_at_n(sd, n)
            mean = float(np.mean(series))
            rate = float(np.mean(series > 0))
            ok = bool(mean > 0 and mean >= DESIGN_TARGET_GAP_FACTOR * se
                      and rate >= R6_POSITIVE_GAP_RATE_MIN)
            gaps_ok = gaps_ok and ok
            gap_checks[name] = {
                "mean": mean, "sd_blockwise": sd, "se_at_n": se,
                "ratio": float(mean / se) if se > 0 else None,
                "positive_gap_block_rate": rate, "ok": ok}
        d3_series = _difficulty(block_table, "D3")
        d3_mean = float(np.mean(d3_series))
        d3_se = _se_at_n(float(np.std(d3_series, ddof=1)), n)
        d3_ok = bool(d3_mean > 0
                     and d3_mean >= DESIGN_TARGET_D3_FACTOR * d3_se)
        margin_checks: dict[str, Any] = {}
        margins_ok = True
        for b in baselines:
            for r in rungs:
                series = _margin(block_table, r, b)
                mean = float(np.mean(series))
                if r in ("D2", "D3"):
                    ok = bool(mean > 0 and mean
                              >= DESIGN_TARGET_MARGIN_FACTOR
                              * _se_at_n(float(np.std(series, ddof=1)), n))
                else:
                    ok = bool(mean > 0)
                margins_ok = margins_ok and ok
                margin_checks[f"{b}_{r}"] = {
                    "mean": mean, "ok": ok,
                    "requires_factor_se": r in ("D2", "D3")}
        sim = simulate_formal_gate_pass_r6_matched(
            block_table, n_formal_blocks=n)
        diff_means = {r: float(np.mean(_difficulty(block_table, r)))
                      for r in rungs}
        reasons = {
            "ordering_ok": bool(diff_means["D0"] > diff_means["D1"]
                                > diff_means["D2"] > diff_means["D3"]),
            "gaps_ge_3x_se_and_positive_rate": gaps_ok,
            "d3_ge_2p5x_se": d3_ok,
            "margins_positive_and_d2_d3_ge_2p5x_se": margins_ok,
            "formal_gate_probability_ge_0p90": bool(
                sim["gate_pass_probability"] >= DESIGN_TARGET_GATE_PROB),
        }
        per_n[str(n)] = {
            "n_formal_blocks": n,
            "gap_checks": gap_checks,
            "d3_check": {"mean": d3_mean, "se_at_n": d3_se,
                         "ratio": float(d3_mean / d3_se),
                         "ok": d3_ok},
            "margin_checks": margin_checks,
            "formal_gate_simulation": sim,
            "reasons": reasons,
            "qualified": bool(all(reasons.values())),
        }

    # 密度(R6 冻结 gate) + R7 candidate-specific cue 语义 + 独立性/
    # 可观察性(冻结公共实现)
    from rl_curriculum.curriculum261_r6_pairs import c2_density_summary

    density_summaries: dict[str, Any] = {}
    for r in rungs:
        d = c2_density_summary(
            [row for row in ev["episodes"] if row["rung"] == r], r)
        d["reference_long_label_rate"] = _reference_long_label_rate(
            [blk.pair_records[r] for blk in blocks], ladder[r],
            thresholds)
        density_summaries[r] = density_gate_r5(d)
    from rl_curriculum.curriculum261_qualification import (
        check_c2_context_observability,
        check_c2_local_cue_independence,
    )

    cue_sem = candidate_cue_semantics(blocks, candidate_id, thresholds)
    semantics = {
        "local_cue_independence": check_c2_local_cue_independence(
            records),
        "context_observability": check_c2_context_observability(
            records),
        "cue_semantics_r7_cluster_aware": cue_sem,
        # R6 点阈值分离检查仅作诊断对照(绝不进入 R7 资格判定;
        # recall 点估计与 ladder 无关,precision/fc 由 cluster 版取代)
        "r6_point_separation_diagnostic_only": {
            k: v for k, v in check_c2_cue_payoff_separation(
                records).items() if k != "per_rung"},
    }
    density_ok = all(d["pass"] for d in density_summaries.values())
    semantics_ok = bool(
        semantics["local_cue_independence"]["pass"]
        and semantics["context_observability"]["pass"]
        and cue_sem["pass"])
    integrity_ok = bool(all(rec.integrity_ok for rec in records))
    scrambled = scrambled_gap_control(block_table)
    return {
        "candidate": candidate_id,
        "corpus": corpus_ns,
        "n_blocks": int(block_table["n_blocks"]),
        "block_corpus_summary": matched_block_corpus_summary(blocks),
        "block_attempt_stats": block_attempt_statistics(blocks),
        "block_table": block_table,
        "pair_table_rows": ev["pair_table"]["rows"],
        "difficulty_means": {r: float(np.mean(
            _difficulty(block_table, r))) for r in rungs},
        "per_formal_block_count": per_n,
        "density_gates": density_summaries,
        "semantics": semantics,
        "semantics_pass": semantics_ok,
        "density_pass": density_ok,
        "pair_integrity_unity": integrity_ok,
        "oracle_positive": bool(all(
            float(np.mean([row["oracle"] for row in ev["episodes"]
                           if row["rung"] == r])) > 0 for r in rungs)),
        "scrambled_control_diagnostic": scrambled,
    }


def _gap_series(block_table: dict[str, Any], hi: str, lo: str):
    from rl_curriculum.curriculum261_r6_pairs import block_gap_series

    return block_gap_series(block_table, hi, lo)


def _difficulty(block_table: dict[str, Any], rung: str):
    return block_difficulty_series(block_table, rung)


def _margin(block_table: dict[str, Any], rung: str, baseline: str):
    return block_margin_series(block_table, rung, baseline)


def _qualified_at_n(corpus_results: list[dict[str, Any]], n: int) -> bool:
    return all(
        res["per_formal_block_count"][str(n)]["qualified"]
        and res["semantics_pass"] and res["density_pass"]
        and res["pair_integrity_unity"] and res["oracle_positive"]
        for res in corpus_results)


def _maximin_score_r7(corpus_results: list[dict[str, Any]],
                      n: int) -> float:
    """§12/§14 maximin(不含 shared recall——与 selection 解耦)。"""
    vals: list[float] = []
    pos_rate_min = 1.0
    fc_ucb_worst = 0.0
    prec_lcb_worst = float("inf")
    trades_ratio_min = float("inf")
    for res in corpus_results:
        block_table = res["block_table"]
        rungs = CURRICULUM261_RUNGS
        for k in range(3):
            hi, lo = rungs[k], rungs[k + 1]
            series = _gap_series(block_table, hi, lo)
            se = _se_at_n(float(np.std(series, ddof=1)), n)
            mean = float(np.mean(series))
            if se > 0:
                vals.append(mean / se)
            pos_rate_min = min(pos_rate_min, float(np.mean(series > 0)))
        d3 = _difficulty(block_table, "D3")
        d3_se = _se_at_n(float(np.std(d3, ddof=1)), n)
        if d3_se > 0:
            vals.append(float(np.mean(d3)) / d3_se)
        for b in ("always_long", "c2_local_only"):
            m = _margin(block_table, "D3", b)
            mse = _se_at_n(float(np.std(m, ddof=1)), n)
            if mse > 0:
                vals.append(float(np.mean(m)) / mse)
        for d in res["density_gates"].values():
            trades_ratio_min = min(
                trades_ratio_min,
                d["median_reference_trades_per_episode"]
                / C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES_R6,
                d["reference_long_label_rate"]
                / C2_DENSITY_MIN_REFERENCE_LONG_RATE_R6)
        for per_rung in res["semantics"][
                "cue_semantics_r7_cluster_aware"]["per_rung"].values():
            for side in per_rung["sides"].values():
                fc_ucb_worst = max(
                    fc_ucb_worst,
                    side["payoff_false_cue"]["bound"])
                prec_lcb_worst = min(
                    prec_lcb_worst, side["cue_precision"]["bound"])
    vals.append(pos_rate_min / R6_POSITIVE_GAP_RATE_MIN)
    vals.append(trades_ratio_min)
    vals.append(max(0.0, 1.0 - fc_ucb_worst / C2_PAYOFF_BAR_FALSE_CUE_MAX))
    vals.append(max(0.0, prec_lcb_worst / C2_CUE_PRECISION_MIN))
    return float(min(vals))


# ------------------------------------------------- 主流程
def run_design_stage_r7(out_dir: Path, plan: dict[str, Any],
                        design_digest: str,
                        baseline_commit: str = "") -> dict[str, Any]:
    """R7 design 主流程:治理检查 → 全部 blocks 生成 → shared gate
    (每 corpus 一次)→ candidate 评估 → 机械选择 → marginal guard →
    pack;shared gate FAIL / 无合格组合 → 自动 FAIL summary(§20)。"""
    require_r7_iteration_active()
    out_dir = Path(out_dir)
    identity = verify_design_code_identity(plan)
    if not identity["pass"]:
        raise RuntimeError(
            f"R7 design plan code identity 与当前代码不一致:"
            f"{sorted(identity['drift'])}(§16.2)")
    thresholds = dict(
        family_specs()[FAMILY_C2].reference_defaults)
    grid = plan["candidate_grid"]["candidates"]
    n_blocks = plan["design_data"]["blocks_per_candidate_per_corpus"]
    floor = float(plan["cue_semantic_contract"]["recall_floor"])
    cue_rule = cue_semantic_rule_identity()
    if cue_rule != plan["cue_semantic_contract"]["rule_identity"]:
        raise RuntimeError("cue semantic rule identity 与 plan 不一致")

    # ---- 生成全部 candidate × corpus 的 matched blocks(§18)----
    # 第一条 design episode 生成前记录 design_data_started(§16.2)
    mark_design_data_started()
    blocks_by: dict[str, dict[str, list[Any]]] = {}
    for corpus_ns in plan["design_data"]["corpora"]:
        blocks_by[corpus_ns] = {}
        for cand_id, ladder in grid.items():
            blocks_by[corpus_ns][cand_id] = [
                generate_matched_block_with_attempts(
                    ladder, namespace=corpus_ns, block_index=i)
                for i in range(n_blocks)]

    # ---- §19.1 shared cue semantic gate(每 corpus 一次)----
    shared_gates: dict[str, Any] = {}
    shared_pass = True
    for corpus_ns in plan["design_data"]["corpora"]:
        gate = shared_cue_semantic_gate(
            blocks_by[corpus_ns], thresholds, recall_floor_value=floor)
        shared_gates[corpus_ns] = gate
        shared_pass = shared_pass and gate["pass"]
    (out_dir / "shared_cue_semantic_gate.json").write_text(json.dumps(
        shared_gates, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    if not shared_pass:
        summary = {
            "format": "cur261-r7-design-stage-v1",
            "iteration": "r7",
            "design_plan_digest": design_digest,
            "n_candidates": len(grid),
            "shared_cue_gates": shared_gates,
            "shared_gate_pass": False,
            "pass": False,
            "verdict": "R7 design FAIL:shared cue semantic gate 未在"
                       "全部 design corpus 通过(§19.1);不进行 "
                       "candidate 选择;不生成 parameter pack;不访问 "
                       "marginal/calibration/final namespace;不写 "
                       "exposure marker;不运行 full-cold(§20)",
        }
        (out_dir / "r7_sample_size_selection.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False,
                       default=float), encoding="utf-8")
        return summary

    # ---- candidate × corpus 评估(复用已生成的 blocks)----
    candidate_results: dict[str, Any] = {}
    for cand_id, ladder in grid.items():
        corpora = [
            _evaluate_candidate_matched_r7(
                cand_id, ladder, ns, thresholds,
                blocks=blocks_by[ns][cand_id], n_blocks=n_blocks)
            for ns in plan["design_data"]["corpora"]]
        qualified_ns: dict[str, bool] = {}
        scores: dict[str, float] = {}
        for n in FORMAL_BLOCK_OPTIONS:
            qualified_ns[str(n)] = _qualified_at_n(corpora, n)
            if qualified_ns[str(n)]:
                scores[str(n)] = _maximin_score_r7(corpora, n)
        candidate_results[cand_id] = {
            "candidate_params": ladder,
            "corpora": corpora,
            "qualified_by_block_count": qualified_ns,
            "maximin_score_by_qualified_n": scores,
            "qualified_any": any(qualified_ns.values()),
            "param_distance_from_historical": (
                ladder_distance_from_historical_r7(ladder)),
        }
    (out_dir / "r7_candidate_results.json").write_text(json.dumps(
        candidate_results, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")

    # ---- §14 机械选择:最小 n → maximin → distance → id ----
    selected_n: int | None = None
    selected_id: str | None = None
    for n in FORMAL_BLOCK_OPTIONS:
        combos = [(cid, res) for cid, res in candidate_results.items()
                  if res["qualified_by_block_count"][str(n)]]
        if combos:
            ranked = sorted(
                combos,
                key=lambda kv: (-kv[1]["maximin_score_by_qualified_n"][
                                    str(n)],
                                kv[1]["param_distance_from_historical"],
                                kv[0]))
            selected_id, _selected = ranked[0]
            selected_n = n
            break

    power = _build_power_summary_r7(
        candidate_results, shared_gates, selected_id, selected_n,
        design_digest)
    (out_dir / "r7_power_analysis.json").write_text(json.dumps(
        power, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")

    if selected_id is None:
        summary = {
            "format": "cur261-r7-design-stage-v1",
            "iteration": "r7",
            "design_plan_digest": design_digest,
            "n_candidates": len(candidate_results),
            "formal_block_options": list(FORMAL_BLOCK_OPTIONS),
            "shared_gate_pass": True,
            "shared_cue_gates": {
                ns: {
                    "recall_lcb": g["recall"]["bound"],
                    "recall_floor": g["recall_floor"],
                    "noncue_fp_ucb": g["noncue_false_positive"]["bound"],
                    "n_unique_positive_cues": g[
                        "n_unique_positive_cues"],
                } for ns, g in shared_gates.items()},
            "qualified_combinations": 0,
            "weakest_binding_condition": power[
                "weakest_binding_condition"],
            "pass": False,
            "verdict": "R7 FAIL:candidate × block count 无合格组合"
                       "(§20);保留 block tables;不生成 parameter pack;"
                       "不访问 marginal/calibration/final namespace;"
                       "不写 exposure marker;不运行 full-cold",
        }
        (out_dir / "r7_sample_size_selection.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False,
                       default=float), encoding="utf-8")
        return summary

    # ---- §21 独立-rung marginal guard(选定后、pack 前)----
    ladder = candidate_results[selected_id]["candidate_params"]
    marginal_artifact = _run_independent_marginal_guard(
        out_dir, ladder, selected_id, thresholds)
    if not marginal_artifact["guard"]["pass"]:
        summary = {
            "format": "cur261-r7-design-stage-v1",
            "iteration": "r7",
            "design_plan_digest": design_digest,
            "selected_candidate": selected_id,
            "selected_block_count": selected_n,
            "marginal_guard_pass": False,
            "marginal_guard": marginal_artifact["guard"],
            "pass": False,
            "verdict": "R7 FAIL:选定 ladder 的独立-rung marginal guard "
                       "未通过(§21:matched PASS 不可覆盖);不生成 pack,"
                       "禁止进入 calibration",
        }
        (out_dir / "r7_sample_size_selection.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False,
                       default=float), encoding="utf-8")
        return summary

    # ---- §22 parameter pack ----
    matched_integrity = candidate_results[selected_id]["corpora"][0][
        "block_corpus_summary"]
    integrity_ok_all = matched_integrity[
        "all_rung_pair_integrity_pass"]
    cross_ok_all = matched_integrity["all_cross_rung_matching_pass"]
    block_integrity_identity = (
        matched_integrity["block_contract"]
        + f"|n={matched_integrity['n_blocks']}"
        + f"|tapes={matched_integrity['distinct_shared_tape_count']}"
        + f"|integrity={integrity_ok_all}"
        + f"|cross={cross_ok_all}")
    pack = ladder_pack_payload_r7(
        selected_c2_candidate=selected_id,
        c2_ladder=ladder,
        selected_block_count=selected_n,
        design_plan_digest=design_digest,
        matched_contract_identity=matched_ladder_contract_identity(),
        block_integrity_identity=block_integrity_identity,
        cue_semantic_contract_digest=cue_semantic_contract_digest(),
        cue_semantic_rule_identity=cue_rule,
        cue_audit_digest=plan["cue_semantic_contract"]["audit_digest"],
        p_contract=plan["cue_semantic_contract"]["p_contract"],
        recall_floor_value=floor,
        candidate_evidence={
            "maximin_score": candidate_results[selected_id][
                "maximin_score_by_qualified_n"][str(selected_n)],
            "param_distance": candidate_results[selected_id][
                "param_distance_from_historical"],
            "corpora": [c["corpus"] for c in
                        candidate_results[selected_id]["corpora"]],
            "gate_probability_at_n": [
                c["per_formal_block_count"][str(selected_n)][
                    "formal_gate_simulation"]["gate_pass_probability"]
                for c in candidate_results[selected_id]["corpora"]],
            "shared_gate_recall_lcb": {
                ns: g["recall"]["bound"]
                for ns, g in shared_gates.items()},
        },
        marginal_guard_evidence={
            "namespace": marginal_artifact["namespace"],
            "pairs_per_rung": marginal_artifact["pairs_per_rung"],
            "cue_semantics_pass": marginal_artifact["cue_semantics"][
                "pass"],
        },
        baseline_commit=baseline_commit,
    )
    write_selected_pack_r7(out_dir, pack)
    # write 为副本补 digest 落盘;重新 load 保证 selection 引用的
    # digest 与盘上 artifact 逐位一致(fail closed)
    from rl_curriculum.curriculum261_r7_param_pack import (
        load_selected_pack,
    )

    pack = load_selected_pack(out_dir)

    selection = {
        "format": "cur261-r7-sample-size-selection-v1",
        "iteration": "r7",
        "design_plan_digest": design_digest,
        "selected_candidate": selected_id,
        "selected_block_count": selected_n,
        "formal_block_options": list(FORMAL_BLOCK_OPTIONS),
        "selection_order": ["min formal block count", "maximin score",
                            "min param distance", "candidate id"],
        "maximin_score": candidate_results[selected_id][
            "maximin_score_by_qualified_n"][str(selected_n)],
        "param_distance_from_historical": candidate_results[
            selected_id]["param_distance_from_historical"],
        "qualified_combinations": int(sum(
            1 for res in candidate_results.values()
            for q in res["qualified_by_block_count"].values() if q)),
        "shared_gate_pass": True,
        "shared_cue_gates": {
            ns: {
                "recall_lcb": g["recall"]["bound"],
                "recall_floor": g["recall_floor"],
                "recall_point": g["recall"]["point"],
                "noncue_fp_ucb": g["noncue_false_positive"]["bound"],
                "n_unique_positive_cues": g[
                    "n_unique_positive_cues"],
            } for ns, g in shared_gates.items()},
        "marginal_guard_pass": True,
        "parameter_pack_digest": pack["digest"],
        "pass": True,
    }
    (out_dir / "r7_sample_size_selection.json").write_text(json.dumps(
        selection, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    return selection


def _run_independent_marginal_guard(
        out_dir: Path, ladder: dict[str, dict[str, Any]],
        selected_id: str, thresholds: dict) -> dict[str, Any]:
    """§21:design_r7_independent_marginal 语料的 marginal guard。"""
    from rl_curriculum.curriculum261_r7_cue_eval import (
        independent_cue_semantics,
    )
    from rl_curriculum.curriculum261_r4_pairs import rung_report_r4
    from rl_curriculum.curriculum261_r6_pairs import c2_density_summary

    indep_records: list[Any] = []
    for rung in CURRICULUM261_RUNGS:
        for idx in range(DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R7):
            indep_records.append(generate_pair(
                FAMILY_C2, rung, idx,
                namespace=DESIGN_INDEPENDENT_NAMESPACE_R7,
                rung_params_override={rung: dict(ladder[rung])}))
    indep_report = rung_report_r4(
        indep_records, FAMILY_C2, ladder, thresholds,
        preproc=None, corpus=DESIGN_INDEPENDENT_NAMESPACE_R7)
    indep_density: dict[str, Any] = {}
    for r in CURRICULUM261_RUNGS:
        d = c2_density_summary(
            [row for row in indep_report["by_rung"][r]["episodes"]
             if row["rung"] == r], r)
        d["reference_long_label_rate"] = _reference_long_label_rate(
            [rec for rec in indep_records if rec.rung == r],
            ladder[r], thresholds)
        indep_density[r] = density_gate_r5(d)
    from rl_curriculum.curriculum261_qualification import (
        check_c2_context_observability,
        check_c2_local_cue_independence,
    )

    indep_cue = independent_cue_semantics(
        indep_records, selected_id, thresholds)
    indep_semantics = {
        "local_cue_independence": check_c2_local_cue_independence(
            indep_records),
        "context_observability": check_c2_context_observability(
            indep_records),
        "cue_semantics": indep_cue,
    }
    marginal = c2_marginal_guard_conditions(
        indep_report,
        density={"pass": all(d["pass"] for d in indep_density.values())},
        semantics=indep_semantics)
    artifact = {
        "format": "cur261-r7-independent-marginal-design-v1",
        "namespace": DESIGN_INDEPENDENT_NAMESPACE_R7,
        "pairs_per_rung": DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R7,
        "candidate": selected_id,
        "guard": marginal,
        "density_gates": indep_density,
        "cue_semantics": indep_cue,
        "semantics": {k: {kk: vv for kk, vv in v.items()
                          if kk not in ("per_rung", "per_quadrant")}
                      for k, v in indep_semantics.items()},
    }
    (out_dir / "c2_independent_marginal_design.json").write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    return artifact


def _build_power_summary_r7(candidate_results: dict[str, Any],
                            shared_gates: dict[str, Any],
                            selected_id: str | None,
                            selected_n: int | None,
                            design_digest: str) -> dict[str, Any]:
    """§20 自动 power/semantic summary(含最弱 binding condition)。"""
    weakest: dict[str, Any] = {}
    global_fail_counts: dict[str, int] = {}
    for cand_id, res in candidate_results.items():
        cand_weak: dict[str, Any] = {}
        for n_str, n_res in res["corpora"][0][
                "per_formal_block_count"].items():
            for name, ok in n_res["reasons"].items():
                if not ok:
                    cand_weak.setdefault(n_str, {})[name] = False
                    key = f"n={n_str}:{name}"
                    global_fail_counts[key] = (
                        global_fail_counts.get(key, 0) + 1)
        if not all(c["semantics_pass"] for c in res["corpora"]):
            cand_weak["semantics"] = False
            global_fail_counts["semantics"] = (
                global_fail_counts.get("semantics", 0) + 1)
        if not all(c["density_pass"] for c in res["corpora"]):
            cand_weak["density"] = False
            global_fail_counts["density"] = (
                global_fail_counts.get("density", 0) + 1)
        weakest[cand_id] = cand_weak
    ranked = sorted(global_fail_counts.items(), key=lambda kv: -kv[1])
    gate_margins = {
        ns: {
            "recall_lcb_minus_floor": g["recall"]["bound"]
            - g["recall_floor"],
            "noncue_max_minus_ucb": g["noncue_false_positive"]["max"]
            - g["noncue_false_positive"]["bound"],
        } for ns, g in shared_gates.items()}
    return {
        "format": "cur261-r7-power-analysis-v1",
        "design_plan_digest": design_digest,
        "selected_candidate": selected_id,
        "selected_block_count": selected_n,
        "shared_gate_margins": gate_margins,
        "per_candidate_weakest": weakest,
        "global_fail_counts": dict(ranked),
        "weakest_binding_condition": (
            ranked[0][0] if ranked else "none(all qualified)"
            if selected_id else ranked[0][0] if ranked else "none"),
    }
