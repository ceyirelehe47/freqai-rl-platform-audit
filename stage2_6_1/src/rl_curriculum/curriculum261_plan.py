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

PLAN_FORMAT = "cur261-qualification-plan-v1"

#: 阶段 2.6.1 的课程代码身份(逐模块内容哈希;进入 plan)
PLAN_CODE_MODULES = (
    "curriculum261_api.py",
    "curriculum261_c1.py",
    "curriculum261_c2.py",
    "curriculum261_c3.py",
    "curriculum261_pairs.py",
    "curriculum261_qualification.py",
    "curriculum261_plan.py",
    "curriculum261_smoke.py",
)


def _code_identity() -> dict[str, str]:
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in PLAN_CODE_MODULES:
        f = root / name
        out[name] = hashlib.sha256(
            f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    return out


def build_plan(*, baseline_commit: str, vendor_pin: str,
               frozen_contracts: dict[str, str],
               pairs_per_rung: int = 10) -> dict[str, Any]:
    """构造 qualification plan(锁定内容;不含任何运行结果)。"""
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_EPISODE_BARS,
        CURRICULUM261_MAX_ATTEMPTS,
        CURRICULUM261_TIMEFRAME,
        curriculum261_eval_config,
        curriculum261_observation_schema,
    )
    from rl_curriculum.curriculum261_pairs import family_specs

    specs = family_specs()
    families: dict[str, Any] = {}
    for family, spec in specs.items():
        families[family] = {
            "generator_class": type(spec.generator).__name__,
            "family_version": spec.generator.family_version,
            "rung_params": spec.rung_params,
            "reference_thresholds": dict(spec.reference_defaults),
        }
    schema = curriculum261_observation_schema()
    cfg = curriculum261_eval_config()
    return {
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
            "initial_price": 100.0,
        },
        "observation_schema": schema.canonical_payload(),
        "observation_schema_hash": schema.schema_hash(),
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
        "seed_schedule": {
            "namespaces": ["calibration", "qualification", "fresh_holdout",
                           "training"],
            "derivation": "sha256([stage, namespace, family, rung, pair, "
                          "attempt])[:8];pair A/B 共享同一 seed",
            "corpus_enumeration": "qualification: family x rung x pair 0..9",
            "training_note": "training namespace 本阶段仅用于 PPO plumbing "
                             "smoke;2.6.2 起为正式训练 seed,与 "
                             "qualification corpus 不相交",
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
