#!/usr/bin/env python
"""阶段 2.6.0 工作包 M:审计探针资格验证(产出全部关键证据)。

只使用 Oracle / 规则 / trivial / 故意作弊策略与极短测试级 PPO
(仅用于确认评估器能够读取 SB3 模型)验证整套基础设施;
不训练正式课程模型,不因策略表现调整环境或课程核心合同。

用法(WSL,conda freqtrade-rl):
    python experiments/route_c_stage2_6_0/run_audit.py \
        [--artifacts artifacts/route_c_stage2_6_0]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))

from rl_platform.versions import (  # noqa: E402
    ENV_CORE_VERSION, OBSERVATION_SPEC_VERSION, ACTION_SPEC_VERSION,
    REWARD_SPEC_VERSION, EXECUTION_CONTRACT_VERSION,
    TERMINAL_LIQUIDATION_VERSION, spec_versions,
)
from rl_curriculum.charter import (  # noqa: E402
    canonical_charter, charter_hash, validate_charter,
)
from rl_curriculum.counterfactual import (  # noqa: E402
    classify_cheating,
    test_common_prefix_future_suffix,
    test_cost_monotonicity,
    test_initial_price_invariance,
    test_irrelevant_feature_injection,
    test_irrelevant_feature_shuffle,
    test_episode_length_invariance,
    test_null_control,
    test_price_scale_invariance,
    test_regime_order_randomization,
    test_signal_ablation,
    test_time_shift_invariance,
    test_trend_direction_mirror,
)
from rl_curriculum.evaluator import (  # noqa: E402
    EvalConfig,
    evaluate_policy,
    evaluator_code_hash,
)
from rl_curriculum.exam_pack import (  # noqa: E402
    ExamPack,
    EpisodeSpec,
    RetirementRegistry,
    materialize_pack,
    redact_report,
)
from rl_curriculum.generator_api import (  # noqa: E402
    audit_observation_isolation,
    determinism_check,
)
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY  # noqa: E402
from rl_curriculum.grades import classify_generalization  # noqa: E402
from rl_curriculum.policies import (  # noqa: E402
    AbsolutePriceCheaterPolicy,
    AlwaysFlatPolicy,
    AlwaysLongPolicy,
    HighTurnoverPolicy,
    NullOvertraderPolicy,
    OneStepGreedyPolicy,
    OracleSegmentedDriftPolicy,
    OracleSmoothLatentDriftPolicy,
    PeriodicCheaterPolicy,
    PeriodicTogglePolicy,
    RandomPolicy,
    RuleTrendPolicy,
    StepCounterCheaterPolicy,
)
from rl_curriculum.probe_charter import audit_probe_charter  # noqa: E402
from rl_curriculum.timebase import (  # noqa: E402
    discounted_value_at_real_time,
    duration_to_bars,
    gamma_from_half_life,
    timebase_manifest,
)
from rl_curriculum.transfer import (  # noqa: E402
    TransferProtocolSpec,
    run_blank_demo,
)
from rl_curriculum.verdicts import CourseStatus, ModelStatus  # noqa: E402

TRAIN_PARAMS = {"episode_bars": 96, "drift_bps_range": [18.0, 30.0],
             "vol_bps_range": [20.0, 32.0], "regime_len_range": [12, 40]}
EXTRAP_PARAMS = {"episode_bars": 96, "drift_bps_range": [30.0, 45.0],
              "vol_bps_range": [32.0, 50.0], "regime_len_range": [12, 40]}
# 探针 B 增强参数(独立机制;经三种子集校准:oracle > rule > 0)
B_PARAMS = {"episode_bars": 96, "sigma_mu_bps": 4.0, "vol_bps": 28.0, "theta": 0.015}

TRAIN_SEEDS = list(range(101, 113))   # 12 个训练 seed
HOLDOUT_SEEDS = list(range(201, 209))  # 8 个未见 seed
CFG = EvalConfig(fee=0.001)

GEN_A = DEFAULT_GENERATOR_REGISTRY["probe_segmented_drift"]
GEN_B = DEFAULT_GENERATOR_REGISTRY["probe_smooth_latent_drift"]
GEN_C = DEFAULT_GENERATOR_REGISTRY["probe_null_control"]


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"[run_audit] -> {path.name}")


def eps_a(params=None, seeds=None, split="train"):
    params = params or TRAIN_PARAMS
    return [
        GEN_A.generate(params, seed=s, split=split) for s in (seeds or TRAIN_SEEDS)
    ]


def eps_b(seeds=None, split="family_holdout"):
    return [
        GEN_B.generate(B_PARAMS, seed=s, split=split)
        for s in (seeds or HOLDOUT_SEEDS)
    ]


def eps_c(seeds=None, split="null_control"):
    params = dict(TRAIN_PARAMS)
    return [
        GEN_C.generate(params, seed=s, split=split)
        for s in (seeds or HOLDOUT_SEEDS)
    ]


# ================================================================ WP0 冻结
def artifact_environment_freeze(out: Path) -> None:
    # 修复1证据:终端观察仓位 = 0
    from rl_platform.env import AlignedLongFlatEnv
    import pandas as pd

    rng = np.random.default_rng(11)
    rets = rng.normal(0.0008, 0.004, 40)
    close = 100.0 * np.cumprod(1 + rets)
    open_ = np.concatenate([[100.0], close[:-1]])
    df = pd.DataFrame({
        "open": open_, "high": np.maximum(open_, close) * 1.001,
        "low": np.minimum(open_, close) * 0.999, "close": close,
    })
    env = AlignedLongFlatEnv(features=df[["close"]].pct_change().fillna(0),
                             prices=df)
    env.reset(seed=3)
    obs = None
    info = {}
    for i in range(100):
        obs, _r, term, _tr, info = env.step(1)
        if term:
            break
    fix1 = {
        "terminal_obs_position": float(obs[-1]),
        "ledger_btc_after_liquidation": float(env.ledger.btc),
        "requested_target_position": info.get("requested_target_position"),
        "actual_position_after_liquidation": info.get(
            "actual_position_after_liquidation"),
        "terminal_liquidation_present": "terminal_liquidation" in info,
        "pass": (
            float(obs[-1]) == 0.0 and env.ledger.btc == 0.0
            and info.get("requested_target_position") == 1
            and info.get("actual_position_after_liquidation") == 0
            and "terminal_liquidation" in info
        ),
    }
    manifest = {
        "frozen_utc": "2026-08-26(阶段 2.6.0 工作包 0)",
        "env_core_version": ENV_CORE_VERSION,
        "observation_spec_version": OBSERVATION_SPEC_VERSION,
        "action_spec_version": ACTION_SPEC_VERSION,
        "reward_spec_version": REWARD_SPEC_VERSION,
        "execution_contract_version": EXECUTION_CONTRACT_VERSION,
        "terminal_liquidation_version": TERMINAL_LIQUIDATION_VERSION,
        "spec_versions_full": spec_versions(),
        "pre_freeze_fix_1_terminal_observation": fix1,
        "pre_freeze_fix_2_missing_predictions_dir": {
            "implemented_in": (
                "experiments/freqai_rl_stage2_5_2a/run_experiment.py"
                "(freqtrade 退出码 0 且 backtesting_predictions 缺失 -> "
                "invalid + 退出码 4 + manifest 记录原始异常 + 模型目录保留)"),
            "verified_by": (
                "tests/route_c_stage2_6_0/"
                "test_missing_prediction_dir_is_fatal.py"),
        },
        "freeze_rule": (
            "完成两项修整后不再修改环境核心;课程/生成器/考试失败"
            "默认不得通过修改 env.py/ledger.py/market_execution.py/reward 补救"),
        "version_injection": (
            "spec_versions 注入实验 config(进入指纹)、execution_contract "
            "与 manifest;checkpoint sidecar 携带并逐项校验"),
    }
    write_json(out / "environment_freeze_manifest.json", manifest)


# ================================================================ WPA 时间
def artifact_timebase(out: Path) -> None:
    hl = 72.0
    rows = []
    for tf in ("5m", "15m", "1h"):
        g = gamma_from_half_life(hl, tf)
        for hours in (6.0, 24.0, 72.0, 168.0):
            bars = duration_to_bars(hours, tf)
            compounded = g ** bars
            analytic = discounted_value_at_real_time(hours, hl)
            rows.append({
                "timeframe": tf, "hours": hours, "bars": bars,
                "gamma": g, "gamma^bars": compounded,
                "analytic_0.5^(t/hl)": analytic,
                "abs_error": abs(compounded - analytic),
            })
    max_err = max(r["abs_error"] for r in rows)
    write_json(out / "timebase_equivalence.json", {
        "half_life_hours": hl,
        "gamma_formula": "exp(log(0.5) * step_duration / reward_half_life)",
        "equivalence_rows": rows,
        "max_abs_error": max_err,
        "pass": max_err < 1e-12,
        "conversion_manifest": timebase_manifest("15m", hl),
        "rounding_rule": "ceil(非整数向上取整;规则入 manifest)",
        "note": "本阶段只冻结以真实时间定义 gamma 的机制,不冻结最终数值",
    })


# ================================================================ WPB 章程
def artifact_charter(out: Path) -> None:
    charter = validate_charter(audit_probe_charter())
    ch = charter_hash(charter)
    write_json(out / "course_charter_example.json", {
        "charter": charter,
        "canonical": canonical_charter(charter),
        "charter_hash": ch,
        "validate_pass": True,
        "note": (
            "审计探针课程示例章程(非正式趋势课程);修改生成器/观察/考试"
            "范围/指标/门槛必须生成新版本和新哈希"),
    })


# ============================================================ WPC/WPD 生成器
def artifact_generator_determinism(out: Path) -> None:
    results = []
    for family, gen, params in (
        ("probe_segmented_drift", GEN_A, TRAIN_PARAMS),
        ("probe_smooth_latent_drift", GEN_B, {"episode_bars": 96}),
        ("probe_null_control", GEN_C, dict(TRAIN_PARAMS)),
    ):
        results.append(determinism_check(gen, params, 7))
        results.append(determinism_check(gen, params, 8))
    # 版本敏感性:family_version 变化必须改变哈希
    g1 = GEN_A.fingerprint()
    GEN_A.family_version = "probe-A-v2"
    g2 = GEN_A.fingerprint()
    GEN_A.family_version = "probe-A-v1"
    write_json(out / "generator_determinism.json", {
        "checks": results,
        "pass": all(r["pass"] for r in results),
        "fingerprint_version_sensitivity": {
            "v1": g1, "v2": g2, "changed": g1 != g2,
        },
    })


def artifact_hidden_state_audit(out: Path) -> None:
    rows = []
    for family, gen, params in (
        ("probe_segmented_drift", GEN_A, TRAIN_PARAMS),
        ("probe_smooth_latent_drift", GEN_B, {"episode_bars": 96}),
        ("probe_null_control", GEN_C, dict(TRAIN_PARAMS)),
    ):
        ep = gen.generate(params, seed=9)
        rows.append({
            "family": family,
            **audit_observation_isolation(ep, gen),
        })
    write_json(out / "hidden_state_observation_audit.json", {
        "families": rows,
        "pass": all(r["pass"] for r in rows),
        "forbidden_patterns_note": (
            "观察字段命名审计 + 隐藏列交集检查;修改未来后缀不得改变共同"
            "前缀 observation 由 common_prefix_invariance.json 验证"),
    })


# ================================================================ WPE 排序
def artifact_baseline_ordering(out: Path) -> None:
    def summarize(report):
        return {
            "median": report["overall"]["median"],
            "mean": report["overall"]["mean"],
            "q10": report["overall"]["q10"],
            "worst": report["overall"]["worst"],
            "median_turnover": report["behavior"]["median_turnover"],
            "seed_pass_ratio_vs_flat": report["seed_pass_ratio_vs_always_flat"],
        }

    probe_a = {
        name: summarize(evaluate_policy(p, eps_a(), CFG))
        for name, p in [
            ("always_flat", AlwaysFlatPolicy()),
            ("always_long", AlwaysLongPolicy()),
            ("random", RandomPolicy(seed=0)),
            ("periodic_toggle", PeriodicTogglePolicy(8)),
            ("one_step_greedy", OneStepGreedyPolicy()),
            ("high_turnover", HighTurnoverPolicy()),
            ("rule_trend", RuleTrendPolicy(ma_threshold=0.001)),
            ("oracle", OracleSegmentedDriftPolicy()),
        ]
    }
    probe_b = {
        name: summarize(evaluate_policy(p, eps_b(), CFG))
        for name, p in [
            ("always_flat", AlwaysFlatPolicy()),
            ("always_long", AlwaysLongPolicy()),
            ("random", RandomPolicy(seed=0)),
            ("rule_trend", RuleTrendPolicy(ma_threshold=0.001)),
            ("oracle", OracleSmoothLatentDriftPolicy(3.0)),
        ]
    }
    oracle_gt_rule_a = (
        probe_a["oracle"]["median"] > probe_a["rule_trend"]["median"]
    )
    rule_gt_trivial_a = probe_a["rule_trend"]["median"] > max(
        probe_a["always_flat"]["median"], probe_a["random"]["median"],
        probe_a["periodic_toggle"]["median"],
    )
    long_not_dominant = (
        probe_a["always_long"]["q10"] < probe_a["rule_trend"]["median"]
        or probe_a["always_long"]["worst"] < -0.02
    )
    flat_not_top = probe_a["always_flat"]["median"] <= probe_a["oracle"]["median"]
    write_json(out / "baseline_ordering.json", {
        "probe_segmented_drift": probe_a,
        "probe_smooth_latent_drift": probe_b,
        "qualification": {
            "oracle_gt_rule_A": oracle_gt_rule_a,
            "rule_gt_trivial_A": rule_gt_trivial_a,
            "always_long_not_passing_everywhere": long_not_dominant,
            "always_flat_not_top": flat_not_top,
            "course_status": (
                CourseStatus.QUALIFIED.value
                if (oracle_gt_rule_a and rule_gt_trivial_a and long_not_dominant
                    and flat_not_top)
                else CourseStatus.INVALID_COURSE.value
            ),
        },
    })


# ================================================================ WPH 反事实
def artifact_common_prefix(out: Path) -> None:
    rows = []
    for name, pol in [
        ("oracle", OracleSegmentedDriftPolicy()),
        ("rule_trend", RuleTrendPolicy(ma_threshold=0.001)),
        ("cheater_step_counter", StepCounterCheaterPolicy()),
        ("cheater_absolute_price", AbsolutePriceCheaterPolicy()),
    ]:
        for seed in (301, 302):
            ep = GEN_A.generate(TRAIN_PARAMS, seed=seed)
            r = test_common_prefix_future_suffix(GEN_A, pol, ep, CFG)
            rows.append({"policy": name, "seed": seed, **r.to_record()})
    write_json(out / "common_prefix_invariance.json", {
        "rows": rows,
        "pass_expectation": (
            "oracle/rule 共同前缀动作一致;依赖未来的作弊策略分歧"),
        "oracle_rule_all_pass": all(
            r["pass"] for r in rows if r["policy"] in ("oracle", "rule_trend")
        ),
    })


def artifact_price_scale(out: Path) -> None:
    scale_rows = []
    init_rows = []
    for name, pol in [
        ("oracle", OracleSegmentedDriftPolicy()),
        ("rule_trend", RuleTrendPolicy(ma_threshold=0.001)),
        ("cheater_absolute_price", AbsolutePriceCheaterPolicy()),
    ]:
        ep = GEN_A.generate(TRAIN_PARAMS, seed=303)
        scale_rows.append({
            "policy": name,
            **test_price_scale_invariance(pol, ep, CFG).to_record(),
        })
        init_rows.append({
            "policy": name,
            **test_initial_price_invariance(GEN_A, pol, ep, CFG).to_record(),
        })
    write_json(out / "price_scale_invariance.json", {
        "price_scale": scale_rows,
        "initial_price": init_rows,
        "pass_expectation": (
            "oracle/rule 动作一致(特征为尺度不变量);绝对价格作弊分歧"),
        "oracle_rule_all_pass": all(
            r["pass"] for r in scale_rows + init_rows
            if r["policy"] in ("oracle", "rule_trend")
        ),
    })


def artifact_length_time_regime(out: Path) -> None:
    length_rows, time_rows, regime_rows = [], [], []
    for name, pol in [
        ("oracle", OracleSegmentedDriftPolicy()),
        ("rule_trend", RuleTrendPolicy(ma_threshold=0.001)),
        ("cheater_step_counter", StepCounterCheaterPolicy()),
        ("cheater_periodic", PeriodicCheaterPolicy(6)),
    ]:
        ep = GEN_A.generate(TRAIN_PARAMS, seed=304)
        length_rows.append({
            "policy": name,
            **test_episode_length_invariance(GEN_A, pol, ep, CFG).to_record(),
        })
        time_rows.append({
            "policy": name,
            **test_time_shift_invariance(pol, ep, CFG).to_record(),
        })
        regime_rows.append({
            "policy": name,
            **test_regime_order_randomization(GEN_A, pol, ep, CFG).to_record(),
        })
    write_json(out / "episode_length_invariance.json", {
        "length_invariance": length_rows,
        "time_shift": time_rows,
        "regime_order_randomization": regime_rows,
        "pass_expectation": (
            "oracle/rule 通过;StepCounter 在长度不变性失败,"
            "Periodic 在 regime 重排后暴露不读市场"),
        "oracle_rule_all_pass": all(
            r["pass"] for r in length_rows + time_rows + regime_rows
            if r["policy"] in ("oracle", "rule_trend")
        ),
    })


def artifact_null_report(out: Path) -> None:
    null_eps = eps_c()
    rows = {}
    for name, pol in [
        ("always_flat", AlwaysFlatPolicy()),
        ("rule_trend", RuleTrendPolicy(ma_threshold=0.001)),
        ("oracle", OracleSegmentedDriftPolicy()),
        ("cheater_null_overtrader", NullOvertraderPolicy()),
    ]:
        r = test_null_control(pol, null_eps, CFG)
        rows[name] = r.to_record()
    write_json(out / "null_control_report.json", {
        "construction": (
            "probe_null_control:探针A同参数轨迹收益相位随机化重排,"
            "隐藏 regime 标签保留(与重排后收益独立)"),
        "rows": rows,
        "expectations": {
            "oracle_no_advantage": not rows["oracle"]["extra"].get(
                "excess_positive_ratio", 0) >= 0.75,
            "rule_no_stable_excess": rows["rule_trend"]["pass"],
            "overtrader_fees_loss_high_turnover": (
                rows["cheater_null_overtrader"]["extra"]["high_turnover"]
                and rows["cheater_null_overtrader"]["extra"]["excess_median"] < 0
            ),
            "no_stable_positive_excess_any": all(
                v["pass"] for v in rows.values()
            ),
        },
    })


def artifact_signal_ablation(out: Path) -> None:
    rule = RuleTrendPolicy(ma_threshold=0.001)
    seeds = (305, 306, 307, 308, 309)
    eps_list = [GEN_A.generate(TRAIN_PARAMS, seed=s) for s in seeds]
    rows = [test_signal_ablation(rule, eps_list, CFG).to_record()]
    noise_rows = []
    ep = eps_list[0]
    noise_rows.append({
        "seed": seeds[0],
        **test_irrelevant_feature_injection(rule, ep, CFG).to_record(),
        **test_irrelevant_feature_shuffle(rule, ep, CFG).to_record(),
    })
    mirror_rows = [test_trend_direction_mirror(rule, eps_list, CFG).to_record()]
    cost_rows = []
    for seed in (305,):
        ep = GEN_A.generate(TRAIN_PARAMS, seed=seed)
        cost_rows.append({
            "seed": seed,
            **test_cost_monotonicity(rule, ep, CFG).to_record(),
        })
    write_json(out / "signal_ablation_report.json", {
        "signal_ablation": rows,
        "irrelevant_feature": noise_rows,
        "trend_mirror": mirror_rows,
        "cost_monotonicity": cost_rows,
        "pass": (
            all(r["pass"] for r in rows) and all(r["pass"] for r in mirror_rows)
            and all(r["pass"] for r in cost_rows)
            and all(r["pass"] for r in noise_rows)
        ),
    })


# ======================================================== G2/G3 外推探针
def artifact_extrapolation(out: Path) -> None:
    rule = RuleTrendPolicy(ma_threshold=0.001)
    train_rep = evaluate_policy(rule, eps_a(split="train"), CFG)
    extrap_rep = evaluate_policy(
        rule, eps_a(params=EXTRAP_PARAMS, seeds=HOLDOUT_SEEDS,
                     split="param_extrapolation"),
        CFG,
    )
    write_json(out / "parameter_extrapolation_probe.json", {
        "policy": "rule_trend",
        "train_range": TRAIN_PARAMS["drift_bps_range"],
        "extrapolation_range": EXTRAP_PARAMS["drift_bps_range"],
        "train_median": train_rep["overall"]["median"],
        "extrapolation_median": extrap_rep["overall"]["median"],
        "extrapolation_q10": extrap_rep["overall"]["q10"],
        "g2_pass": extrap_rep["overall"]["median"] > 0,
        "note": "参数外推(drift 超出训练范围)下规则策略仍保持正优势",
    })


def artifact_family_holdout(out: Path) -> None:
    rule = RuleTrendPolicy(ma_threshold=0.001)
    rep = evaluate_policy(rule, eps_b(), CFG)
    write_json(out / "generator_family_holdout_probe.json", {
        "policy": "rule_trend",
        "training_family": "probe_segmented_drift",
        "holdout_family": "probe_smooth_latent_drift(独立代码路径)",
        "holdout_median": rep["overall"]["median"],
        "g3_pass": rep["overall"]["median"] > 0,
        "note": (
            "未见生成机制(OU 平滑漂移)下规则策略保持正优势;"
            "G3 至少要求一个未参与训练的生成机制"),
    })


# ========================================================== WPI 作弊矩阵
def artifact_cheater_matrix(out: Path) -> None:
    policies = [
        ("cheater_step_counter", StepCounterCheaterPolicy()),
        ("cheater_absolute_price", AbsolutePriceCheaterPolicy()),
        ("cheater_periodic", PeriodicCheaterPolicy(6)),
        ("cheater_future_leak", None),  # 单独构造
        ("cheater_null_overtrader", NullOvertraderPolicy()),
    ]
    matrix = {}
    for name, pol in policies:
        rows = []
        if name == "cheater_future_leak":
            from rl_curriculum.policies import FutureLeakProbePolicy

            pol = FutureLeakProbePolicy(fee_threshold=CFG.fee)
        ep = GEN_A.generate(TRAIN_PARAMS, seed=401)
        if name == "cheater_future_leak":
            # 未来泄漏策略对切割点位置敏感:多个 cut_ratio 下,
            # 任一共同前缀动作分歧即构成泄漏证据
            cp_tests = [
                test_common_prefix_future_suffix(GEN_A, pol, ep, CFG,
                                                 cut_ratio=cr)
                for cr in (0.3, 0.5, 0.7)
            ]
            tests = [cp_tests[0]]
        else:
            cp_tests = [test_common_prefix_future_suffix(GEN_A, pol, ep, CFG)]
            tests = list(cp_tests)
        tests += [
            test_price_scale_invariance(pol, ep, CFG),
            test_initial_price_invariance(GEN_A, pol, ep, CFG),
            test_episode_length_invariance(GEN_A, pol, ep, CFG),
            test_time_shift_invariance(pol, ep, CFG),
            test_regime_order_randomization(GEN_A, pol, ep, CFG),
        ]
        null_r = test_null_control(pol, eps_c(seeds=[501, 502, 503, 504]), CFG)
        tests.append(null_r)
        cf = classify_cheating(tests)
        # FutureLeakProbe:观察字段审计 + 多 cut 共同前缀证据
        obs_audit = None
        cp_any_fail = any(not t.pass_ for t in cp_tests)
        null_stable_positive = (
            not null_r.pass_
            and not null_r.extra.get("high_turnover")
        )
        if name == "cheater_future_leak":
            obs_audit = {
                "leaky_observation_fields": ["future_return_1"],
                "detected_by": (
                    "观察字段审计(future_* 命名禁入 observation) + "
                    "共同前缀测试(未来后缀改变共同前缀动作) + "
                    "Null Control 稳定正超额"),
                "common_prefix_any_cut_failed": cp_any_fail,
                "null_stable_positive_without_high_turnover": null_stable_positive,
            }
            if cp_any_fail or null_stable_positive:
                cf = dict(cf)
                cf["suspected_cheating"] = True
                cf["cheat_reasons"] = sorted(
                    set(cf["cheat_reasons"]) | {"future_leak"})
                cf["failed_tests"] = sorted(
                    set(cf["failed_tests"]) | {"common_prefix_future_suffix"})
        matrix[name] = {
            "tests": [t.to_record() for t in tests]
                     + [t.to_record() for t in cp_tests[1:]],
            "classification": cf,
            "observation_field_audit": obs_audit,
        }
    detected = {}
    for name in matrix:
        cls = matrix[name]["classification"]
        if name == "cheater_null_overtrader":
            flags = cls["null_control_flags"]
            detected[name] = bool(
                flags["high_turnover"] and (flags["excess_median"] or 0) < 0
            )
        else:
            detected[name] = cls["suspected_cheating"]
    write_json(out / "cheater_detection_matrix.json", {
        "matrix": matrix,
        "detected": detected,
        "all_detected": all(detected.values()),
        "verdict_rule": (
            "StepCounter/AbsolutePrice/Periodic/FutureLeak -> "
            "SUSPECTED_CHEATING(细分原因);NullOvertrader -> 高换手+"
            "扣费亏损+Null Control 挂科(普通挂科而非作弊高分)"),
    })


# ========================================================== WPF 评估器确定
def artifact_evaluator_determinism(out: Path) -> None:
    pol = RuleTrendPolicy(ma_threshold=0.001)
    eps = eps_a(seeds=[601, 602, 603])
    r1 = evaluate_policy(pol, eps, CFG, baseline_policies={
        "always_flat": AlwaysFlatPolicy(),
        "oracle": OracleSegmentedDriftPolicy(),
    })
    r2 = evaluate_policy(pol, eps, CFG, baseline_policies={
        "always_flat": AlwaysFlatPolicy(),
        "oracle": OracleSegmentedDriftPolicy(),
    })
    identical = json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
    # 文件遍历顺序无关:打乱 episodes 输入顺序(基线配置保持一致)
    r3 = evaluate_policy(pol, list(reversed(eps)), CFG, baseline_policies={
        "always_flat": AlwaysFlatPolicy(),
        "oracle": OracleSegmentedDriftPolicy(),
    })
    order_independent = (
        json.dumps(_strip_episodes(r1), sort_keys=True)
        == json.dumps(_strip_episodes(r3), sort_keys=True)
    )
    write_json(out / "evaluator_determinism.json", {
        "repeat_identical": identical,
        "input_order_independent": order_independent,
        "evaluator_code_hash": evaluator_code_hash(),
        "deterministic_flag": CFG.deterministic,
        "bootstrap_seed": 20260826,
        "pass": identical and order_independent,
    })


def _strip_episodes(report):
    return {k: v for k, v in report.items() if k != "episodes"}


# ========================================================== WPK 考试包
def artifact_mock_hidden_exam(out: Path) -> None:
    charter = audit_probe_charter()
    ch = charter_hash(charter)
    specs = (
        [EpisodeSpec("probe_segmented_drift", dict(TRAIN_PARAMS), s, "train")
         for s in TRAIN_SEEDS[:6]]
        + [EpisodeSpec("probe_segmented_drift", dict(TRAIN_PARAMS), s,
                       "dev_seed_holdout") for s in HOLDOUT_SEEDS[:4]]
        + [EpisodeSpec("probe_segmented_drift", dict(EXTRAP_PARAMS), 701,
                       "param_extrapolation")]
        + [EpisodeSpec("probe_smooth_latent_drift", {"episode_bars": 96}, 702,
                       "family_holdout")]
    )
    pack = ExamPack(
        name="mock_hidden_probe_exam", version="mock-v1",
        visibility="mock_hidden", charter_hash=ch,
        spec_versions=spec_versions(), episodes=specs,
        notes={
            "declaration": (
                "mock-hidden pack 只用于测试隐藏考试基础设施,"
                "不具备正式考试资格;正式隐藏生成器将在课程冻结后由"
                "独立评估 Agent 在另一工作区创建,种子不进公开仓库"),
        },
    )
    pack_path = out / "mock_hidden_pack.json"
    pack.save(pack_path)
    write_json(out / "mock_hidden_exam_manifest.json", {
        "pack_path": pack_path.name,
        "pack_hash": pack.pack_hash(),
        "visibility": pack.visibility,
        "n_episodes": len(pack.episodes),
        "charter_hash": ch,
        "reload_hash_stable": ExamPack.load(pack_path).pack_hash()
                              == pack.pack_hash(),
        "splits": sorted({e.split for e in pack.episodes}),
    })


def artifact_hidden_exam_redaction(out: Path) -> None:
    sys.path.insert(0, str(PROJ_ROOT / "src"))
    from rl_curriculum.hidden_exam_cli import main as exam_main

    pack_path = out / "mock_hidden_pack.json"
    agg_path = out / "hidden_exam_aggregate_demo.json"
    # 幂等:脱敏演示使用独立注册表并在运行前清理,
    # 保证 run_audit 可重复执行(不依赖目录残留状态)
    registry_path = out / "retired_redaction_demo.json"
    registry_path.unlink(missing_ok=True)
    rc = exam_main([
        "--pack", str(pack_path), "--policy", "rule_trend",
        "--out", str(agg_path),
        "--retire-registry", str(registry_path),
    ])
    agg = json.loads(agg_path.read_text())
    aggregate_report = agg["aggregate"]
    redacted_ok = (
        "episodes" not in aggregate_report
        and aggregate_report.get("episodes_redacted") is True
    )
    write_json(out / "hidden_exam_redaction_report.json", {
        "cli_exit_code": rc,
        "status": agg["status"],
        "pack_hash": agg["pack_hash"],
        "redacted_output_has_no_episode_trace": redacted_ok,
        "aggregate_report": aggregate_report,
        "redaction_rule": (
            "默认只返回聚合成绩与状态;逐 Episode trace/种子/参数脱敏;"
            "训练 Agent 不得读取隐藏 Episode 或逐步 trace"),
        "pass": redacted_ok and rc == 0,
    })


def artifact_exam_retirement(out: Path) -> None:
    sys.path.insert(0, str(PROJ_ROOT / "src"))
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.exam_pack import ExamPackError

    pack_path = out / "mock_hidden_pack.json"
    # 幂等:退休演示使用独立注册表并在运行前清理,
    # 保证 run_audit 可重复执行;主 retired_packs.json 不被演示污染
    registry_path = out / "retired_retirement_demo.json"
    registry_path.unlink(missing_ok=True)
    det_path = out / "retirement_detailed_demo.json"
    rc = exam_main([
        "--pack", str(pack_path), "--policy", "rule_trend",
        "--out", str(out / "retirement_aggregate_demo.json"),
        "--retire-registry", str(registry_path),
        "--detailed", str(det_path),
    ])
    detailed_written = det_path.is_file()
    pack = ExamPack.load(pack_path)
    retired_after = RetirementRegistry(registry_path).is_retired(pack.pack_hash())
    # 已退休考试包再次评估必须被拒绝
    rejected = False
    err = None
    try:
        materialize_pack(pack, DEFAULT_GENERATOR_REGISTRY,
                         retire_registry=RetirementRegistry(registry_path))
    except ExamPackError as exc:
        rejected = True
        err = str(exc)
    write_json(out / "exam_retirement_test.json", {
        "detailed_run_exit_code": rc,
        "detailed_written": detailed_written,
        "pack_hash": pack.pack_hash(),
        "retired_after_disclosure": retired_after,
        "reuse_rejected": rejected,
        "reuse_rejection": err,
        "pass": rc == 0 and detailed_written and retired_after and rejected,
    })


# ==================================================== checkpoint 守卫 + SB3
def artifact_checkpoint_guard(out: Path) -> None:
    import shutil
    import tempfile

    from stable_baselines3 import PPO

    from rl_platform.env import AlignedLongFlatEnv
    from rl_curriculum.checkpoints import (
        CheckpointCompatibilityError,
        load_guarded_checkpoint,
        mark_legacy_engineering_evidence,
        save_checkpoint_manifest,
    )
    from rl_curriculum.policies import SB3CheckpointPolicy

    ep = GEN_A.generate(TRAIN_PARAMS, seed=801)
    feature_cols = [c for c in ep.df.columns
                    if c not in ("open", "high", "low", "close", "volume", "date")]
    env = AlignedLongFlatEnv(
        features=ep.df[feature_cols],
        prices=ep.df[["open", "high", "low", "close"]],
        fee=CFG.fee, window_size=1,
    )
    model = PPO("MlpPolicy", env, n_steps=64, batch_size=64, n_epochs=1,
                seed=42, policy_kwargs={"net_arch": [16, 16]}, verbose=0, device="cpu")
    model.learn(total_timesteps=64)  # 极短测试级训练(仅接口验证)
    ckpt = out / "test_ppo_probe.zip"
    model.save(str(ckpt).removesuffix(".zip"))

    charter = audit_probe_charter()
    ch = charter_hash(charter)
    manifest = save_checkpoint_manifest(
        ckpt, checkpoint_name="test_ppo_probe", charter_hash=ch,
        extra={"purpose": "评估器读取 SB3 模型接口验证(测试级,非正式训练)"},
    )
    loaded_model, loaded_manifest = load_guarded_checkpoint(
        ckpt, expected_charter_hash=ch)
    sb3_policy = SB3CheckpointPolicy(ckpt, expected_charter_hash=ch)
    rep = evaluate_policy(sb3_policy, eps_a(seeds=[802, 803]), CFG)

    # 篡改版本 -> 拒绝
    bad_manifest = dict(manifest)
    bad = dict(manifest["spec_versions"])
    bad["env_core_version"] = "RouteCEnvCore-v0.9.0"
    bad_manifest["spec_versions"] = bad
    sidecar = ckpt.with_name(ckpt.name + ".rl_manifest.json")
    orig_sidecar = sidecar.read_text()
    sidecar.write_text(json.dumps(bad_manifest))
    version_mismatch_rejected = False
    vm_err = None
    try:
        load_guarded_checkpoint(ckpt, expected_charter_hash=ch)
    except CheckpointCompatibilityError as exc:
        version_mismatch_rejected = True
        vm_err = str(exc)
    # 章程哈希不匹配 -> 拒绝
    charter_mismatch_rejected = False
    cm_err = None
    sidecar.write_text(orig_sidecar)
    try:
        load_guarded_checkpoint(ckpt, expected_charter_hash="c-deadbeef")
    except CheckpointCompatibilityError as exc:
        charter_mismatch_rejected = True
        cm_err = str(exc)
    # 旧 2.5 smoke checkpoint:复制副本到 artifacts 后标记 legacy 工程证据
    # (不修改 user_data/models 下的原始 2.5.x 产物)
    legacy_dir = sorted(
        (PROJ_ROOT / "user_data" / "models").glob("stage252a-rc-*/sub-train-*")
    )
    legacy_marked = None
    legacy_load_ok = None
    legacy_formal_blocked = None
    if legacy_dir:
        legacy_zip = sorted(legacy_dir[-1].glob("*_model.zip"))
        if legacy_zip:
            legacy_copy = out / "legacy_smoke_checkpoint.zip"
            shutil.copyfile(legacy_zip[-1], legacy_copy)
            m = mark_legacy_engineering_evidence(
                legacy_copy,
                note=(
                    f"阶段 2.5.2a PPO smoke checkpoint 副本("
                    f"{legacy_zip[-1].name}):工程证据,仅接口验证,"
                    f"不作为正式迁移模型"
                ),
            )
            legacy_marked = {
                "source": str(legacy_zip[-1]),
                "copy": str(legacy_copy),
                "formal_eligible": m["formal_eligible"],
                "legacy_engineering_evidence": m["legacy_engineering_evidence"],
            }
            try:
                _mdl, lm = load_guarded_checkpoint(legacy_copy, allow_legacy=True)
                legacy_load_ok = True
                legacy_formal_blocked = not lm["formal_eligible"]
            except Exception as exc:  # noqa: BLE001
                legacy_load_ok = False
                legacy_formal_blocked = str(exc)
    # 清理测试级 checkpoint 目录副作用(保留 zip 供证据复核)
    write_json(out / "checkpoint_compatibility_guard.json", {
        "test_checkpoint": str(ckpt),
        "sidecar_manifest": manifest,
        "load_with_matching_versions_and_charter": loaded_manifest["formal_eligible"],
        "sb3_policy_evaluation_ran": rep["n_episodes"] == 2,
        "sb3_policy_name": sb3_policy.name,
        "version_mismatch_rejected": version_mismatch_rejected,
        "version_mismatch_error": vm_err,
        "charter_mismatch_rejected": charter_mismatch_rejected,
        "charter_mismatch_error": cm_err,
        "legacy_smoke_checkpoint": legacy_marked,
        "legacy_interface_load_ok": legacy_load_ok,
        "legacy_formal_blocked": legacy_formal_blocked,
        "pass": (
            loaded_manifest["formal_eligible"] and rep["n_episodes"] == 2
            and version_mismatch_rejected and charter_mismatch_rejected
            and legacy_load_ok is True and legacy_formal_blocked is True
        ),
    })


# ============================================================ WPG 等级探针
def artifact_generalization_grade(out: Path) -> None:
    cases = {}

    def synth(train, dev, ext, fam):
        return {
            "by_split": {
                "train": {"n": 6, "median": train},
                "dev_seed_holdout": {"n": 4, "median": dev},
                "param_extrapolation": {"n": 4, "median": ext},
                "family_holdout": {"n": 4, "median": fam},
            }
        }

    cases["G0_train_only"] = classify_generalization(synth(.1, -.1, -.1, -.1))
    cases["G1_seed_only"] = classify_generalization(synth(.1, .05, -.1, -.1))
    cases["G2_param_pass_family_fail"] = classify_generalization(
        synth(.1, .05, .05, -.1))
    cases["G3_family_pass_no_cf"] = classify_generalization(
        synth(.1, .05, .05, .05))
    cases["G4_cf_pass"] = classify_generalization(
        synth(.1, .05, .05, .05), counterfactual_all_pass=True)
    cases["G4_cf_fail"] = classify_generalization(
        synth(.1, .05, .05, .05), counterfactual_all_pass=False)
    # 真实策略等级(规则策略,四 split)
    rule = RuleTrendPolicy(ma_threshold=0.001)
    rep = evaluate_policy(
        rule,
        eps_a(split="train")[:6]
        + eps_a(seeds=HOLDOUT_SEEDS, split="dev_seed_holdout")
        + eps_a(params=EXTRAP_PARAMS, seeds=[901, 902], split="param_extrapolation")
        + eps_b(split="family_holdout"),
        CFG,
    )
    real = classify_generalization(rep, counterfactual_all_pass=True)
    expected = {
        "G0_train_only": "G0", "G1_seed_only": "G1",
        "G2_param_pass_family_fail": "G2",
        "G3_family_pass_no_cf": "G3", "G4_cf_pass": "G4",
        "G4_cf_fail": "G3",
    }
    ok = all(cases[k]["grade"] == v for k, v in expected.items())
    write_json(out / "generalization_grade_probe.json", {
        "synthetic_cases": cases,
        "synthetic_expected": expected,
        "real_rule_trend": {
            "report_by_split": {
                k: v for k, v in rep["by_split"].items()
            },
            "grade": real,
        },
        "classification_correct": ok,
        "rules": (
            "G1 不得单独称为真正泛化;G3 至少一个未参与训练的生成机制;"
            "G4 必须含 Null 与共同前缀考试;G5 见 transfer_protocol_demo"),
        "pass": ok,
    })


# ============================================================ WPL 迁移演示
def artifact_transfer_demo(out: Path) -> None:
    spec = TransferProtocolSpec(
        target_course_charter_hash=charter_hash(audit_probe_charter()),
        exam_pack_hash="p-mock(见 mock_hidden_exam_manifest.json)",
        seeds=[1, 2, 3, 4, 5],
        training_budget_steps=0,
        model_capacity={"net_arch": "demo-identical"},
        ppo_params={"demo": True},
        n_eval_runs=1,
    )
    demo = run_blank_demo(spec, lambda arm, seed: 0.0)
    write_json(out / "transfer_protocol_demo.json", demo)


# ============================================================ WPF2 SB3 烟雾
def artifact_sb3_smoke(out: Path) -> None:
    """极短测试级 PPO(仅确认评估器能读取 SB3 模型;不是正式训练)。"""
    from stable_baselines3 import PPO

    from rl_platform.env import AlignedLongFlatEnv
    from rl_curriculum.checkpoints import save_checkpoint_manifest
    from rl_curriculum.policies import SB3CheckpointPolicy

    ep = GEN_A.generate(TRAIN_PARAMS, seed=811)
    feature_cols = [c for c in ep.df.columns
                    if c not in ("open", "high", "low", "close", "volume", "date")]
    env = AlignedLongFlatEnv(
        features=ep.df[feature_cols],
        prices=ep.df[["open", "high", "low", "close"]],
        fee=CFG.fee, window_size=1,
    )
    model = PPO("MlpPolicy", env, n_steps=64, batch_size=32, n_epochs=2,
                seed=7, policy_kwargs={"net_arch": [16, 16]}, verbose=0, device="cpu")
    model.learn(total_timesteps=128)
    ckpt = out / "sb3_interface_smoke.zip"
    model.save(str(ckpt).removesuffix(".zip"))
    ch = charter_hash(audit_probe_charter())
    save_checkpoint_manifest(
        ckpt, checkpoint_name="sb3_interface_smoke", charter_hash=ch,
        extra={"purpose": "SB3 接口烟雾(极短测试级训练)"},
    )
    pol = SB3CheckpointPolicy(ckpt, expected_charter_hash=ch)
    rep = evaluate_policy(pol, eps_a(seeds=[812, 813]), CFG)
    write_json(out / "sb3_interface_smoke.json", {
        "checkpoint": str(ckpt),
        "total_timesteps": 128,
        "note": "极短测试级 PPO:仅确认评估器能读取 SB3 模型,非正式训练",
        "evaluated_episodes": rep["n_episodes"],
        "overall": rep["overall"],
        "pass": rep["n_episodes"] == 2,
    })


# ============================================================ 上游完整性
def artifact_upstream(out: Path) -> None:
    def run(cmd):
        return subprocess.run(
            cmd, capture_output=True, text=True, check=True).stdout.strip()

    write_json(out / "upstream_integrity.json", {
        "tag": run(["git", "-C", str(PROJ_ROOT / "vendor" / "freqtrade"),
                    "describe", "--tags", "--exact-match"]),
        "commit": run(["git", "-C", str(PROJ_ROOT / "vendor" / "freqtrade"),
                       "rev-parse", "HEAD"]),
        "status": run(["git", "-C", str(PROJ_ROOT / "vendor" / "freqtrade"),
                       "status", "--short"]) or "(clean)",
        "clean": run(["git", "-C", str(PROJ_ROOT / "vendor" / "freqtrade"),
                      "status", "--short"]) == "",
    })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", default=str(
        PROJ_ROOT / "artifacts" / "route_c_stage2_6_0"))
    args = ap.parse_args()
    out = Path(args.artifacts)
    out.mkdir(parents=True, exist_ok=True)

    artifact_environment_freeze(out)
    artifact_timebase(out)
    artifact_charter(out)
    artifact_generator_determinism(out)
    artifact_hidden_state_audit(out)
    artifact_baseline_ordering(out)
    artifact_common_prefix(out)
    artifact_price_scale(out)
    artifact_length_time_regime(out)
    artifact_null_report(out)
    artifact_signal_ablation(out)
    artifact_extrapolation(out)
    artifact_family_holdout(out)
    artifact_cheater_matrix(out)
    artifact_evaluator_determinism(out)
    artifact_mock_hidden_exam(out)
    artifact_hidden_exam_redaction(out)
    artifact_exam_retirement(out)
    artifact_checkpoint_guard(out)
    artifact_generalization_grade(out)
    artifact_transfer_demo(out)
    artifact_sb3_smoke(out)
    artifact_upstream(out)
    print("[run_audit] 全部 artifacts 生成完毕")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
