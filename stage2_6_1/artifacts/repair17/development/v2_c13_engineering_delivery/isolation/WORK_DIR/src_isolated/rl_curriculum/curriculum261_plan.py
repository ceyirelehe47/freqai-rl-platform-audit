"""阶段 2.6.1 工作包 H:Qualification Plan 构造、锁定与防篡改验证。

Plan 在 final qualification 之前生成并锁定(digest 落盘);final run 的
结果文件必须绑定该 digest。锁定后修改 plan 内容(参数/阈值/seed 表/
指标定义/代码身份)都会改变 canonical digest,被 verify_plan 拒绝。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PLAN_FORMAT = "cur261-qualification-plan-v3"

#: 阶段 2.6.1 的课程代码身份(逐模块内容哈希;进入 plan)
PLAN_CODE_MODULES = (
    "curriculum261_api.py",
    "curriculum261_production_obs.py",
    "curriculum261_c1.py",
    "curriculum261_c2.py",
    "curriculum261_c3.py",
    "curriculum261_pairs.py",
    "curriculum261_qualification.py",
    "curriculum261_plan.py",
    "curriculum261_final.py",
    "curriculum261_smoke.py",
    "curriculum261_cli.py",
)


def _code_identity() -> dict[str, str]:
    import rl_curriculum
    from rl_curriculum.curriculum261_production_obs import (
        route_c_strategy_identity,
    )

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in PLAN_CODE_MODULES:
        f = root / name
        out[name] = hashlib.sha256(
            f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    # repair R1:production observation 的特征构造代码本体
    # (user_data/strategies/RouteCStrategy.py)不在 rl_curriculum 树内,
    # 必须单独进入 code identity(final 运行时复算比对)
    ident = route_c_strategy_identity()
    out["RouteCStrategy.py"] = ident["strategy_file_sha256"]
    out["RouteCStrategy.feature_engineering_standard"] = ident[
        "feature_engineering_standard_sha256"]
    return out


def build_plan(*, baseline_commit: str, vendor_pin: str,
               frozen_contracts: dict[str, str],
               pairs_per_rung: int = 10,
               calibration_evidence: dict[str, Any] | None = None,
               robustness_gate: dict[str, Any] | None = None,
               gate_artifact_digest: str | None = None,
               ) -> dict[str, Any]:
    """构造 qualification plan(锁定内容)。

    repair R2 Layer B(硬合同):robustness_gate 必须非 None 且
    robustness_gate["pass"] is True,否则 RuntimeError——gate FAIL
    禁止生成可执行 qualification plan,不存在"gate FAIL 仍可 lock,
    由 final 裁决"的语义。calibration_evidence 为 lock 前双语料
    校准结果快照(锁定后不得修改)。
    """
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_EPISODE_BARS,
        CURRICULUM261_INITIAL_PRICE,
        CURRICULUM261_MAX_ATTEMPTS,
        CURRICULUM261_TIMEFRAME,
        curriculum261_eval_config,
    )
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_production_obs import (
        curriculum_preprocessing_boundary,
        production_observation_identity,
        production_observation_schema,
        production_runtime_config_identity,
    )

    if robustness_gate is None or robustness_gate.get("pass") is not True:
        raise RuntimeError(
            "robustness gate 未通过(或缺失),禁止锁定 qualification "
            "plan——repair R2 硬合同:Calibration -> Holdout -> Gate "
            "PASS 才允许 Lock -> Final Qualification;gate FAIL 必须"
            "回到设计,本轮 calibration qualification = FAIL 并停止")
    specs = family_specs()
    families: dict[str, Any] = {}
    for family, spec in specs.items():
        families[family] = {
            "generator_class": type(spec.generator).__name__,
            "family_version": spec.generator.family_version,
            "rung_params": spec.rung_params,
            "reference_thresholds": dict(spec.reference_defaults),
        }
    schema = production_observation_schema()
    cfg = curriculum261_eval_config()
    plan = {
        "format": PLAN_FORMAT,
        "stage": "stage2_6_1",
        "created_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "baseline_commit": baseline_commit,
        "vendor_pin": vendor_pin,
        "frozen_contracts": frozen_contracts,
        "episode_contract": {
            "timeframe": CURRICULUM261_TIMEFRAME,
            "episode_bars": CURRICULUM261_EPISODE_BARS,
            "initial_price": CURRICULUM261_INITIAL_PRICE,
        },
        "observation_schema": schema.canonical_payload(),
        "observation_schema_hash": schema.schema_hash(),
        "production_observation_identity": production_observation_identity(),
        "production_runtime_config_identity": (
            production_runtime_config_identity()),
        "preprocessing_boundary": curriculum_preprocessing_boundary(),
        "eval_config": cfg.manifest(),
        "families": families,
        "pair_plan": {
            "pair_count_per_family": 4 * pairs_per_rung,
            "pairs_per_rung": pairs_per_rung,
            "rungs": ["D0", "D1", "D2", "D3"],
            "variants": ["A", "B"],
        },
        "attempts_policy": {
            "policy": "first_pass",
            "max_attempts": CURRICULUM261_MAX_ATTEMPTS,
            "selection": "第一个通过结构性校验的候选(绝不按 PnL 挑选)",
        },
        "iteration": "r2",
        "qualification_namespace": "qualification_r2",
        "seed_schedule": {
            "iteration_id": "r2",
            "namespaces": ["calibration_r2", "calibration_holdout_r2",
                           "qualification_r2", "fresh_holdout_r2",
                           "training_r2", "stress_r2"],
            "derivation": "sha256([stage, namespace, family, rung, pair, "
                          "attempt])[:8];pair A/B 共享同一 seed;"
                          "R2 namespace 与 R0/R1 派生流不相交"
                          "(seed_namespace_integrity 验证)",
            "corpus_enumeration": "qualification_r2: family x rung x "
                                  "pair 0..9(从未在 lock 前生成)",
            "qualification_lock_guard": "qualification_r2 seed 在 "
                                        "qualification_plan.json 存在前"
                                        "对任何代码路径不可访问",
            "training_note": "training_r2 namespace 本阶段仅用于 PPO "
                             "plumbing smoke;2.6.2 起为正式训练 seed,"
                             "与 qualification corpus 不相交",
        },
        "difficulty_metric": {
            "formula": "M_rung = mean(ref_net) - max(0, mean(always_long_"
                       "net))(corpus 级;always_flat 恒 0)",
            "ordering": "M_D0 > M_D1 > M_D2 > M_D3(严格)",
            "d3_exploitability": "M_D3 > 0 且 oracle(诊断)在全部 rung 上"
                                 "净收益 > 0",
            "baseline_superiority": "reference 在每个 rung 上严格优于全部"
                                    "必胜基线(flat/long + family 特异基线)",
        },
        "verdict_thresholds": {
            "pair_integrity_pass_ratio": 1.0,
            "causality_all_pass": True,
            "reproducibility_all_pass": True,
            "fresh_seed_valid_ratio_min": 0.8,
            "ordering_all_families": True,
            "d3_positive_all_families": True,
            "reference_beats_required_all_families": True,
            "oracle_positive_all_families": True,
        },
        "code_identity": _code_identity(),
    }
    plan["calibration_evidence"] = calibration_evidence
    plan["robustness_gate"] = robustness_gate
    plan["robustness_gate_artifact_digest"] = gate_artifact_digest
    return plan


def plan_digest(plan: dict[str, Any]) -> str:
    """plan 的规范化 digest(created_utc 不参与,其余全部字段参与)。"""
    payload = {k: v for k, v in plan.items() if k != "created_utc"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return "qp-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def lock_plan(plan: dict[str, Any], out_dir: Path) -> str:
    """写盘锁定:plan JSON + digest 文本(独立文件)。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = plan_digest(plan)
    (out_dir / "qualification_plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "qualification_plan_digest.txt").write_text(
        digest + "\n", encoding="utf-8")
    return digest


def load_locked_plan(out_dir: Path) -> tuple[dict[str, Any], str]:
    """读取锁定的 plan 与其记录的 digest,并校验内容未被篡改。"""
    plan = json.loads(
        (out_dir / "qualification_plan.json").read_text(encoding="utf-8"))
    recorded = (out_dir / "qualification_plan_digest.txt").read_text(
        encoding="utf-8").strip()
    recomputed = plan_digest(plan)
    if recomputed != recorded:
        raise RuntimeError(
            f"qualification plan 被篡改:记录 digest {recorded} != 重算 "
            f"{recomputed}(任何参数/阈值/seed/代码身份改动都会被拒绝)")
    return plan, recorded


def verify_result_binds_plan(result_path: Path, out_dir: Path) -> bool:
    """final result 必须绑定锁定 plan 的 digest。"""
    result = json.loads(result_path.read_text(encoding="utf-8"))
    _plan, recorded = load_locked_plan(out_dir)
    return result.get("plan_digest") == recorded
