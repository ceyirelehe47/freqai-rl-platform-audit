# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R6:预注册 matched-ladder candidate design、
formal block-count 机械选择与功效分析(§17-§26)。

流程:
1. 在生成任何 design_r6_* episode 前锁定 design plan(candidate grid、
   formal block 选项 {10,15,20}、matched-ladder 合同、随机带身份、
   block attempt 语义、统计方法、全部阈值、选择规则、marginal guard、
   bootstrap seeds、code identity 全部绑定;锁定后不得修改任何字段);
2. 8 个完整 ladder candidate(含 1 个历史非选择性 control)在两个独立
   design corpus(design_r6_matched_main/validation)各 40 matched
   blocks 评估;不同 candidate 的同 block_index 结构带逐位一致
   (block seed 不含难度参数,matched-tape 参数剔除);
3. 对每个 candidate × formal block count n ∈ {10,15,20} × corpus 做
   block bootstrap 功效模拟;资格 = 双语料全部硬门槛通过;
4. 选择规则(§22,机械):**最小 formal block count 优先** → 该 n 下
   maximin score 最高 → 参数偏离历史最小 → candidate id 稳定排序;
5. 全部 n 均无合格组合 → R6 = FAIL(自动产出 power summary,不生成
   pack,不进 calibration,不访问 final namespace,不写 exposure);
6. 选定 → 独立-rung marginal guard 语料(design_r6_independent_
   diagnostic,20 pairs/rung;§16)→ FAIL 则 R6 = FAIL;
7. 通过 → CurriculumR6MatchedLadderPack-v1 锁定。

功效硬门槛(§21,预注册;expected SE = sd(blockwise, ddof=1)/√n,
sd 来自 40-block design corpus):
A. 每段 matched gap mean > 0 且 >= 3.0 × expected SE(n);
B. D3 reference-vs-flat > 0 且 mean >= 2.5 × expected SE(n);
C. 全部 rung 逐基线 margin > 0;D2/D3 margin >= 2.5 × expected SE(n);
D. formal block bootstrap(20000 次,完整 block 重采样)P(pass) >= 0.90;
E. 每段 gap 的 positive-gap block rate >= 0.65;
F. 密度 + 语义(context/cue independence/cue-payoff separation)通过。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
from rl_curriculum.curriculum261_c2 import FAMILY_C2
from rl_curriculum.curriculum261_pairs import (
    family_specs,
    generate_pair,
)
from rl_curriculum.curriculum261_qualification import REQUIRED_BASELINES
from rl_curriculum.curriculum261_r4_pairs import (
    evaluate_pair_corpus_r4,
)
from rl_curriculum.curriculum261_r5_pairs import (
    c2_density_summary,
    density_gate_r5,
)
from rl_curriculum.curriculum261_r6_param_pack import (
    C2_LADDER_CANDIDATES,
    R4_PARAMETER_PACK_DIGEST,
    R5_DESIGN_PLAN_DIGEST,
    ladder_distance_from_historical,
    ladder_pack_payload,
    r6_candidate_grid,
    validate_ladder_semantics,
    write_selected_pack,
)
from rl_curriculum.curriculum261_r6_pairs import (
    C2_CUE_RECALL_MIN,
    C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES_R6,
    C2_DENSITY_MIN_REFERENCE_LONG_RATE_R6,
    C2_PAYOFF_BAR_FALSE_CUE_MAX,
    FORMAL_BLOCK_OPTIONS,
    R6_GATE_SIM_RESAMPLES,
    R6_GATE_SIM_SEED,
    R6_POSITIVE_GAP_RATE_MIN,
    build_c2_block_evidence_table,
    check_c2_cue_payoff_separation,
    c2_marginal_guard_conditions,
    scrambled_gap_control,
    simulate_formal_gate_pass_r6_matched,
    strict_gate_rule_identity,
)
from rl_curriculum.curriculum261_r6_tape import (
    C2_MATCHED_LADDER_BLOCK_VERSION,
    block_attempt_statistics,
    generate_matched_block_with_attempts,
    matched_block_corpus_summary,
    matched_ladder_contract_identity,
)

DESIGN_FORMAT_R6 = "cur261-r6-design-plan-v1"
DESIGN_BLOCKS_PER_CORPUS_R6 = 40
DESIGN_NAMESPACES_R6 = ("design_r6_matched_main",
                        "design_r6_matched_validation")
DESIGN_INDEPENDENT_NAMESPACE_R6 = "design_r6_independent_diagnostic"
DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R6 = 20

#: §21 预注册功效阈值。
DESIGN_TARGET_GAP_FACTOR = 3.0
DESIGN_TARGET_D3_FACTOR = 2.5
DESIGN_TARGET_MARGIN_FACTOR = 2.5
DESIGN_TARGET_GATE_PROB = 0.90

#: design 阶段代码身份(影响 design 数值的模块)。
DESIGN_CODE_MODULES_R6 = (
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
    "curriculum261_r6_design.py",
)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _code_identity_design() -> dict[str, str]:
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in DESIGN_CODE_MODULES_R6:
        f = root / name
        out[name] = hashlib.sha256(
            f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    return out


# ------------------------------------------------------------- plan
def design_plan_payload(*, baseline_commit: str, vendor_pin: str,
                        v2_contract_digest: str,
                        prior_r2_plan_digest: str,
                        prior_diag262r2_plan_digest: str,
                        ) -> dict[str, Any]:
    """构建并返回 R6 design plan payload(锁定后不得修改任何字段)。"""
    from rl_platform.versions import (
        ENV_CORE_VERSION, OBSERVATION_SPEC_VERSION)

    grid = r6_candidate_grid()
    for cand in grid.values():
        problems = validate_ladder_semantics(cand)
        if problems:
            raise RuntimeError(f"candidate grid 语义非法: {problems}")
    return {
        "format": DESIGN_FORMAT_R6,
        "iteration": "r6",
        "baseline_commit": baseline_commit,
        "vendor_pin": vendor_pin,
        "r4_parameter_pack_digest": R4_PARAMETER_PACK_DIGEST,
        "r5_design_plan_digest": R5_DESIGN_PLAN_DIGEST,
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
            "contract_version": C2_MATCHED_LADDER_BLOCK_VERSION,
            "contract_identity": matched_ladder_contract_identity(),
            "base_random_tape": "block seed = derive261_seed(ns, c2_"
                                "context, 'matched_block', block_index, "
                                "attempt);matched-tape 实例从全部随机流"
                                "派生 payload 剔除难度键(alpha_bps/"
                                "wick_kappa/cur261_rung);同 block 四 "
                                "rung 同 seed 共享 cue 表/s 链/w 链/基础"
                                "噪声/volume/wick jitter/初始价/时长/"
                                "时间戳;难度参数只做确定性变换",
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
                "unit": "完整四-rung block(任一 rung 或跨 rung matching "
                        "失败 → 整 block 拒绝重试)",
                "forbidden": ["只重采样失败 rung", "按 PnL 拒绝 block",
                              "无限重采样", "跨 block 挑选"],
                "reject_vocab": ["too_few_cues",
                                 "too_few_aligned_gate_windows",
                                 "context_polarity_missing",
                                 "cross_rung_matching_failed",
                                 "pair_integrity_failed"],
            },
            "policy_leakage": "block ID / rung ID 不进入 observation"
                              "(8 生产特征列不变;matched 只是采样/统计"
                              "合同,不是新的 policy observation 或 reward "
                              "合同)",
        },
        "candidate_grid": {
            "candidates": {k: {r: dict(v[r])
                               for r in ("D0", "D1", "D2", "D3")}
                           for k, v in grid.items()},
            "n_candidates": len(grid),
            "allowed_axes": ["alpha_bps", "wick_kappa"],
            "frozen_structure_keys": [
                "payoff_bars", "vol_bps", "cue_rate", "dir_len_range",
                "width_len_range", "pulse_bps", "wick_base_bps",
                "wide_wick_bps", "narrow_wick_bps"],
            "historical_control": "c2l_historical_control(R5 ladder 的"
                                  "非选择性 control;不达标不得被选中)",
        },
        "design_data": {
            "blocks_per_candidate_per_corpus": DESIGN_BLOCKS_PER_CORPUS_R6,
            "min_blocks": 30,
            "corpora": list(DESIGN_NAMESPACES_R6),
            "corpora_role": "main/validation 均为参数开发数据,不得称为"
                            "holdout",
            "evaluation_mode": "raw(preproc=None;reference 数值与 scaled "
                               "逐位一致由 R4 reference 等价证明背书)",
            "block_schedule_sharing": "不同 candidate 的同 block_index "
                                      "结构带逐位一致(seed 派生不含难度"
                                      "参数;§20 相同 block-index schedule"
                                      "由构造满足)",
        },
        "formal_block_options": list(FORMAL_BLOCK_OPTIONS),
        "statistics": {
            "pair_table": "R4 唯一 pair 证据表(C1/C3 与 C2 每 rung 的 "
                          "A/B 均值;evaluate_pair_corpus_r4 同源)",
            "block_table": "唯一 C2 block 证据表(r6bt schema;行键 "
                           "block_index;gap = blockwise 配对差分)",
            "difficulty": "reference_pair - always_flat_pair",
            "margins": "逐固定基线(无 hindsight)",
            "gap_se": "std(blockwise gap, ddof=1)/sqrt(n_blocks);禁止 "
                      "sqrt(SE_hi^2+SE_lo^2) 独立二次合成(§13)",
            "kappa": 1.5,
            "strict_gate_rule_identity": strict_gate_rule_identity(),
            "scrambled_control": "仅诊断(matched vs unpaired 方差缩减);"
                                 "禁止参与 PASS 判定(§15)",
        },
        "power_targets": {
            "adjacent_gaps_positive_and_ge": DESIGN_TARGET_GAP_FACTOR,
            "d3_vs_flat_ge": DESIGN_TARGET_D3_FACTOR,
            "margins_d2_d3_ge": DESIGN_TARGET_MARGIN_FACTOR,
            "margins_all_rungs_positive": True,
            "formal_gate_pass_probability_min": DESIGN_TARGET_GATE_PROB,
            "positive_gap_block_rate_min": R6_POSITIVE_GAP_RATE_MIN,
            "formal_gate_simulation": {
                "n_formal_block_options": list(FORMAL_BLOCK_OPTIONS),
                "n_sim": R6_GATE_SIM_RESAMPLES,
                "seed": R6_GATE_SIM_SEED,
                "method": "按完整 matched block 重采样(A/B 与四 rung "
                          "不拆散);模拟 corpus 内复算 mean/sd(ddof=1)"
                          "/SE;条件=ordering+3 matched gaps(κ×blockSE)"
                          "+D3(>0,κ×SE)+逐基线 margin(全部 rung,κ×SE);"
                          "密度/语义按 design corpus 实测直接判定",
            },
        },
        "density_thresholds": {
            "median_reference_trades_per_episode_min":
                C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES_R6,
            "reference_long_label_rate_min":
                C2_DENSITY_MIN_REFERENCE_LONG_RATE_R6,
            "n_trades_semantics": "buy+sell 双腿(evaluator EpisodeResult)",
        },
        "semantic_thresholds": {
            "cue_recall_min": C2_CUE_RECALL_MIN,
            "cue_payoff_separation": {
                "cue_precision_min": 0.85,
                "non_cue_false_positive_max": 0.01,
                "payoff_bar_false_cue_max": C2_PAYOFF_BAR_FALSE_CUE_MAX,
            },
            "local_cue_independence": "四象限 mean/std/sign/rate 合同"
                                      "(curriculum261_qualification 冻结"
                                      "实现)",
            "context_observability": "observation-only 判定器 margin >= "
                                     "κ×SE_binomial(冻结实现)",
        },
        "independent_marginal_guard": {
            "namespace": DESIGN_INDEPENDENT_NAMESPACE_R6,
            "pairs_per_rung": DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R6,
            "conditions": "mean ordering / D3 positive / 逐基线 positive "
                          "margin / integrity=1.0 / oracle / 密度 / "
                          "context+cue 语义;无 SE 要求;matched PASS 不可"
                          "覆盖 FAIL;失败 → R6 = FAIL(§16)",
            "timing": "design 选定 candidate 后、pack 锁定前",
        },
        "selection_rule": {
            "qualification": "(candidate, n) 组合在两个 design corpus 均"
                             "满足全部硬门槛(A-F)才合格",
            "order": ["最小 formal block count n(10→15→20)",
                      "maximin score 最大(该 n 下)",
                      "参数偏离历史最小(四档 alpha/kappa Σ|new-hist|/"
                      "hist)", "candidate id 稳定排序"],
            "maximin_score": "min over {gap_D0-D1/SE, gap_D1-D2/SE, "
                             "gap_D2-D3/SE, d3_vs_flat/SE, d3_vs_long/SE, "
                             "d3_vs_local_only/SE, 最弱 positive-gap "
                             "rate/0.65, 密度比 min(trades/8, "
                             "label/0.015), separation 余量 min(1-fc/"
                             "0.06, recall/0.95)} × min over 两 corpus"
                             "(SE 取该 n 的 expected block SE)",
            "hard_rule": "先选最小 n,再选该 n 下 score 最高者;平局取 "
                         "distance 最小;禁止先选收益最好 candidate 再"
                         "增加 block 数;禁止看到 final 后扩大 block 数;"
                         "禁止设计后临时加入 30/40 blocks;禁止删除失败"
                         " candidate",
        },
        "fail_path": {
            "auto_power_summary": "r6_power_analysis.json 由 design 流程"
                                  "自动产出(不得依赖事后手工脚本)",
            "on_no_qualified_combination": "R6 = FAIL;保留原始 block "
                                           "tables;报告最弱 binding "
                                           "condition;不生成 pack;不进 "
                                           "calibration;不访问 final "
                                           "namespace;不写 exposure "
                                           "marker;不运行 full-cold(§26)",
        },
        "code_identity": _code_identity_design(),
    }


def design_plan_digest(plan: dict[str, Any]) -> str:
    payload = {k: v for k, v in plan.items() if k != "created_utc"}
    return "r6dp-" + hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()


def lock_design_plan(out_dir: Path, plan: dict[str, Any]) -> tuple[Path, str]:
    """写 design plan JSON + digest(生成任何 design data 前调用)。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = dict(plan)
    plan.setdefault(
        "created_utc",
        datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path = out_dir / "r6_design_plan.json"
    digest_path = out_dir / "r6_design_plan_digest.txt"
    if path.is_file():
        raise RuntimeError(
            "design plan 已存在;锁定后不得重写(修复须新 iteration + "
            "全新 design namespaces)")
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    digest = design_plan_digest(plan)
    digest_path.write_text(digest, encoding="utf-8")
    return path, digest


def load_locked_design_plan(out_dir: Path) -> tuple[dict[str, Any], str]:
    """读回锁定 design plan 并复算 digest + 校验网格/code 未漂移。"""
    out_dir = Path(out_dir)
    path = out_dir / "r6_design_plan.json"
    digest_path = out_dir / "r6_design_plan_digest.txt"
    if not path.is_file() or not digest_path.is_file():
        raise RuntimeError(
            f"design plan 不存在: {path}(必须先 lock-design-plan 再生成"
            "任何 design episode)")
    plan = json.loads(path.read_text(encoding="utf-8"))
    digest = design_plan_digest(plan)
    locked = digest_path.read_text(encoding="utf-8").strip()
    if digest != locked:
        raise RuntimeError("design plan digest 漂移(fail closed)")
    current_grid = r6_candidate_grid()
    if plan["candidate_grid"]["candidates"] != current_grid:
        raise RuntimeError(
            "design plan 候选网格与代码常量漂移(锁定后禁止增删/修改候选)")
    if plan["formal_block_options"] != list(FORMAL_BLOCK_OPTIONS):
        raise RuntimeError(
            "formal block 选项漂移(锁定后禁止修改 block 数选项)")
    if plan["code_identity"] != _code_identity_design():
        raise RuntimeError(
            "design plan code identity 与当前代码树不一致(design 代码"
            "修改后 plan 失效;须新 iteration)")
    return plan, digest


# ------------------------------------------------------------- 评估
def _se_at_n(sd: float, n: int) -> float:
    return float(sd) / np.sqrt(float(n))


def _reference_long_label_rate(records: list[Any], rung_params: dict,
                               thresholds: dict) -> float:
    """reference 动作的 long bar 占比(raw 模式)。"""
    from rl_curriculum.curriculum261_qualification import build_policy_set
    from rl_curriculum.curriculum261_r4_pairs import EVAL_CFG, RAW_SCHEMA
    from rl_curriculum.evaluator import run_policy_episode

    pol = build_policy_set(FAMILY_C2, dict(rung_params), thresholds)[
        "reference"]
    n_long = 0
    n_total = 0
    for rec in records:
        for side in ("A", "B"):
            ep = rec.episodes[side]
            r = run_policy_episode(pol, ep, EVAL_CFG, RAW_SCHEMA,
                                   return_observations=True)
            actions = np.asarray(r[1])
            n_long += int((actions == 1).sum())
            n_total += int(len(actions))
    return float(n_long / n_total) if n_total else float("nan")


def _evaluate_candidate_matched(
        candidate_id: str, ladder: dict[str, dict[str, Any]],
        corpus_ns: str, thresholds: dict,
        n_blocks: int = DESIGN_BLOCKS_PER_CORPUS_R6,
) -> dict[str, Any]:
    """单 candidate 在单 design corpus:生成 n 个 matched block →
    唯一 pair 表(同源评估)→ 唯一 block 表 → 全部 n 选项的硬门槛。"""
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
    baselines = tuple(REQUIRED_BASELINES[FAMILY_C2])
    gap_series = {
        f"{rungs[k]}-{rungs[k + 1]}": _gap_series(
            block_table, rungs[k], rungs[k + 1])
        for k in range(3)}
    diff_sd = {r: float(np.std(_difficulty(block_table, r), ddof=1))
               for r in rungs}
    margin_sd = {b: {r: float(np.std(_margin(block_table, r, b), ddof=1))
                     for r in rungs} for b in baselines}
    diff_mean = {r: float(np.mean(_difficulty(block_table, r)))
                 for r in rungs}
    margin_mean = {b: {r: float(np.mean(_margin(block_table, r, b)))
                       for r in rungs} for b in baselines}

    per_n: dict[str, Any] = {}
    for n in FORMAL_BLOCK_OPTIONS:
        gap_checks: dict[str, Any] = {}
        gaps_ok = True
        pos_rate_min = 1.0
        for name, series in gap_series.items():
            sd = float(np.std(series, ddof=1))
            se = _se_at_n(sd, n)
            mean = float(np.mean(series))
            rate = float(np.mean(series > 0))
            pos_rate_min = min(pos_rate_min, rate)
            ok = bool(mean > 0 and mean >= DESIGN_TARGET_GAP_FACTOR * se
                      and rate >= R6_POSITIVE_GAP_RATE_MIN)
            gaps_ok = gaps_ok and ok
            gap_checks[name] = {
                "mean": mean, "sd_blockwise": sd, "se_at_n": se,
                "ratio": float(mean / se) if se > 0 else None,
                "positive_gap_block_rate": rate, "ok": ok}
        d3_sd = diff_sd["D3"]
        d3_mean = diff_mean["D3"]
        d3_se = _se_at_n(d3_sd, n)
        d3_ok = bool(d3_mean > 0
                     and d3_mean >= DESIGN_TARGET_D3_FACTOR * d3_se)
        margin_checks: dict[str, Any] = {}
        margins_ok = True
        for b in baselines:
            for r in rungs:
                mean = margin_mean[b][r]
                if r in ("D2", "D3"):
                    ok = bool(mean > 0 and mean
                              >= DESIGN_TARGET_MARGIN_FACTOR
                              * _se_at_n(margin_sd[b][r], n))
                else:
                    ok = bool(mean > 0)
                margins_ok = margins_ok and ok
                margin_checks[f"{b}_{r}"] = {
                    "mean": mean, "ok": ok,
                    "requires_factor_se": r in ("D2", "D3")}
        sim = simulate_formal_gate_pass_r6_matched(
            block_table, n_formal_blocks=n)
        reasons = {
            "ordering_ok": bool(diff_mean["D0"] > diff_mean["D1"]
                                > diff_mean["D2"] > diff_mean["D3"]),
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

    # 密度 + 语义(实测,不随 n 变化)
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

    semantics = {
        "local_cue_independence": check_c2_local_cue_independence(
            records),
        "context_observability": check_c2_context_observability(
            records),
        "cue_payoff_separation": check_c2_cue_payoff_separation(
            records),
    }
    density_ok = all(d["pass"] for d in density_summaries.values())
    semantics_ok = all(v["pass"] for v in semantics.values())
    integrity_ok = bool(all(rec.integrity_ok for rec in records))
    scrambled = scrambled_gap_control(block_table)
    return {
        "candidate": candidate_id,
        "corpus": corpus_ns,
        "n_blocks": n_blocks,
        "block_corpus_summary": matched_block_corpus_summary(blocks),
        "block_attempt_stats": block_attempt_statistics(blocks),
        "block_table": block_table,
        "pair_table_rows": ev["pair_table"]["rows"],
        "difficulty_means": diff_mean,
        "per_formal_block_count": per_n,
        "density_gates": density_summaries,
        "semantics": {
            k: {kk: vv for kk, vv in v.items() if kk != "per_quadrant"}
            for k, v in semantics.items()},
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
    from rl_curriculum.curriculum261_r6_pairs import (
        block_difficulty_series,
    )

    return block_difficulty_series(block_table, rung)


def _margin(block_table: dict[str, Any], rung: str, baseline: str):
    from rl_curriculum.curriculum261_r6_pairs import block_margin_series

    return block_margin_series(block_table, rung, baseline)


def _qualified_at_n(corpus_results: list[dict[str, Any]],
                    n: int) -> bool:
    return all(
        res["per_formal_block_count"][str(n)]["qualified"]
        and res["semantics_pass"] and res["density_pass"]
        and res["pair_integrity_unity"] and res["oracle_positive"]
        for res in corpus_results)


def _maximin_score(corpus_results: list[dict[str, Any]], n: int) -> float:
    """§22 maximin:全部指标 × 两 corpus 取最小(SE 用该 n 的 expected)。"""
    vals: list[float] = []
    pos_rate_min = 1.0
    fc_worst = 0.0
    recall_worst = 1.0
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
        sep = res["semantics"]["cue_payoff_separation"]
        fc_worst = max(fc_worst, sep["payoff_bar_false_cue_rate"])
        recall_worst = min(recall_worst, sep["cue_recall"])
    vals.append(pos_rate_min / R6_POSITIVE_GAP_RATE_MIN)
    vals.append(trades_ratio_min)
    vals.append(max(0.0, 1.0 - fc_worst / C2_PAYOFF_BAR_FALSE_CUE_MAX))
    vals.append(recall_worst / C2_CUE_RECALL_MIN)
    return float(min(vals))


def run_design_stage(out_dir: Path, plan: dict[str, Any],
                     design_digest: str,
                     baseline_commit: str = "") -> dict[str, Any]:
    """design 主流程:plan 已锁 → 全 candidate×两 corpus → 机械选择 →
    marginal guard → pack;无合格组合 → 自动 FAIL summary(§26)。"""
    out_dir = Path(out_dir)
    thresholds = dict(
        family_specs()[FAMILY_C2].reference_defaults)
    grid = plan["candidate_grid"]["candidates"]

    candidate_results: dict[str, Any] = {}
    for cand_id, ladder in grid.items():
        corpora = [
            _evaluate_candidate_matched(
                cand_id, ladder, ns, thresholds,
                n_blocks=plan["design_data"][
                    "blocks_per_candidate_per_corpus"])
            for ns in plan["design_data"]["corpora"]]
        qualified_ns: dict[str, bool] = {}
        scores: dict[str, float] = {}
        for n in FORMAL_BLOCK_OPTIONS:
            qualified_ns[str(n)] = _qualified_at_n(corpora, n)
            if qualified_ns[str(n)]:
                scores[str(n)] = _maximin_score(corpora, n)
        candidate_results[cand_id] = {
            "candidate_params": ladder,
            "corpora": corpora,
            "qualified_by_block_count": qualified_ns,
            "maximin_score_by_qualified_n": scores,
            "qualified_any": any(qualified_ns.values()),
            "param_distance_from_historical": (
                ladder_distance_from_historical(ladder)),
        }
    (out_dir / "r6_candidate_results.json").write_text(json.dumps(
        candidate_results, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")

    # §22 机械选择:最小 n → maximin → distance → id
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
            selected_id, selected = ranked[0]
            selected_n = n
            break

    power = _build_power_summary(
        candidate_results, selected_id, selected_n, design_digest)
    (out_dir / "r6_power_analysis.json").write_text(json.dumps(
        power, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")

    if selected_id is None:
        summary = {
            "format": "cur261-r6-design-stage-v1",
            "iteration": "r6",
            "design_plan_digest": design_digest,
            "n_candidates": len(candidate_results),
            "formal_block_options": list(FORMAL_BLOCK_OPTIONS),
            "qualified_combinations": 0,
            "weakest_binding_condition": power[
                "weakest_binding_condition"],
            "pass": False,
            "verdict": "R6 FAIL:candidate × block count 无合格组合"
                       "(§26);不生成 parameter pack,禁止进入 "
                       "calibration,不访问 final namespace,不写 "
                       "exposure marker,不运行 full-cold",
        }
        (out_dir / "r6_sample_size_selection.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False,
                       default=float), encoding="utf-8")
        return summary

    # 独立-rung marginal guard(§16;选定后、pack 前)
    ladder = candidate_results[selected_id]["candidate_params"]
    indep_records: list[Any] = []
    for rung in CURRICULUM261_RUNGS:
        for idx in range(DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R6):
            indep_records.append(generate_pair(
                FAMILY_C2, rung, idx,
                namespace=DESIGN_INDEPENDENT_NAMESPACE_R6,
                rung_params_override={rung: dict(ladder[rung])}))
    from rl_curriculum.curriculum261_r4_pairs import rung_report_r4

    indep_report = rung_report_r4(
        indep_records, FAMILY_C2, ladder, thresholds,
        preproc=None, corpus=DESIGN_INDEPENDENT_NAMESPACE_R6)
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

    indep_semantics = {
        "local_cue_independence": check_c2_local_cue_independence(
            indep_records),
        "context_observability": check_c2_context_observability(
            indep_records),
        "cue_payoff_separation": check_c2_cue_payoff_separation(
            indep_records),
    }
    marginal = c2_marginal_guard_conditions(
        indep_report,
        density={"pass": all(d["pass"] for d in indep_density.values())},
        semantics=indep_semantics)
    marginal_artifact = {
        "format": "cur261-r6-independent-marginal-design-v1",
        "namespace": DESIGN_INDEPENDENT_NAMESPACE_R6,
        "pairs_per_rung": DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R6,
        "candidate": selected_id,
        "guard": marginal,
        "density_gates": indep_density,
        "semantics": {k: {kk: vv for kk, vv in v.items()
                          if kk != "per_quadrant"}
                      for k, v in indep_semantics.items()},
    }
    (out_dir / "c2_independent_marginal_design.json").write_text(
        json.dumps(marginal_artifact, indent=2, ensure_ascii=False,
                   default=float), encoding="utf-8")

    if not marginal["pass"]:
        summary = {
            "format": "cur261-r6-design-stage-v1",
            "iteration": "r6",
            "design_plan_digest": design_digest,
            "selected_candidate": selected_id,
            "selected_block_count": selected_n,
            "marginal_guard_pass": False,
            "marginal_guard": marginal,
            "pass": False,
            "verdict": "R6 FAIL:选定 ladder 的独立-rung marginal guard "
                       "未通过(§16:matched sampling 不得掩盖 marginal "
                       "分布异常);不生成 pack,禁止进入 calibration",
        }
        (out_dir / "r6_sample_size_selection.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False,
                       default=float), encoding="utf-8")
        return summary

    matched_integrity = candidate_results[selected_id]["corpora"][0][
        "block_corpus_summary"]
    integrity_ok_all = matched_integrity[
        "all_rung_pair_integrity_pass"]
    cross_ok_all = matched_integrity[
        "all_cross_rung_matching_pass"]
    block_integrity_identity = (
        matched_integrity["block_contract"]
        + f"|n={matched_integrity['n_blocks']}"
        + f"|tapes={matched_integrity['distinct_shared_tape_count']}"
        + f"|integrity={integrity_ok_all}"
        + f"|cross={cross_ok_all}")
    pack = ladder_pack_payload(
        selected_c2_candidate=selected_id,
        c2_ladder=ladder,
        selected_block_count=selected_n,
        design_plan_digest=design_digest,
        matched_contract_identity=matched_ladder_contract_identity(),
        block_integrity_identity=block_integrity_identity,
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
        },
        baseline_commit=baseline_commit,
    )
    write_selected_pack(out_dir, pack)

    selection = {
        "format": "cur261-r6-sample-size-selection-v1",
        "iteration": "r6",
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
        "marginal_guard_pass": True,
        "parameter_pack_digest": pack["digest"],
        "pass": True,
    }
    (out_dir / "r6_sample_size_selection.json").write_text(json.dumps(
        selection, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    return selection


def _build_power_summary(candidate_results: dict[str, Any],
                         selected_id: str | None,
                         selected_n: int | None,
                         design_digest: str) -> dict[str, Any]:
    """§26 自动 power summary(含最弱 binding condition;无手工脚本)。"""
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
            global_fail_counts["semantics_gate"] = (
                global_fail_counts.get("semantics_gate", 0) + 1)
        if not all(c["density_pass"] for c in res["corpora"]):
            global_fail_counts["density_gate"] = (
                global_fail_counts.get("density_gate", 0) + 1)
        weakest[cand_id] = cand_weak
    ranked_global = sorted(global_fail_counts.items(),
                           key=lambda kv: (-kv[1], kv[0]))
    return {
        "format": "cur261-r6-power-analysis-v1",
        "iteration": "r6",
        "design_plan_digest": design_digest,
        "provenance": "本文件由 run_design_stage 自动产出(§26:不得依赖"
                      "事后手工脚本);数值派生自唯一 block 证据表",
        "selected_candidate": selected_id,
        "selected_block_count": selected_n,
        "weakest_binding_condition": {
            "rule": "在最多 candidate(×n)组合上失败的硬门槛条件"
                    "(降序;并列按名称排序)",
            "ranked": [{"condition": k, "failed_combinations": v}
                       for k, v in ranked_global],
            "top": ranked_global[0][0] if ranked_global else None,
        },
        "candidates": {cid: {
            "qualified_by_block_count": res["qualified_by_block_count"],
            "maximin_score_by_qualified_n": res[
                "maximin_score_by_qualified_n"],
            "gate_probability_by_n": {
                n: [c["per_formal_block_count"][n][
                        "formal_gate_simulation"]["gate_pass_probability"]
                    for c in res["corpora"]]
                for n in res["corpora"][0]["per_formal_block_count"]},
            "gap_ratios_by_n": {
                n: {g: c["per_formal_block_count"][n]["gap_checks"][g][
                        "ratio"]
                    for g in c["per_formal_block_count"][n][
                        "gap_checks"]}
                for c in res["corpora"][:1]
                for n in c["per_formal_block_count"]},
            "positive_gap_rates": {
                g: [float(np.mean(np.asarray(
                    _gap_series(c["block_table"], *g.split("-"))) > 0))
                    for c in res["corpora"]]
                for g in res["corpora"][0]["per_formal_block_count"]["10"][
                    "gap_checks"]},
            "scrambled_vs_matched_se": {
                c["corpus"]: c["scrambled_control_diagnostic"]["gaps"]
                for c in res["corpora"]},
            "semantics_pass": all(c["semantics_pass"]
                                  for c in res["corpora"]),
            "density_pass": all(c["density_pass"]
                                for c in res["corpora"]),
            "weakest_binding_conditions": weakest[cid],
        } for cid, res in candidate_results.items()},
    }
