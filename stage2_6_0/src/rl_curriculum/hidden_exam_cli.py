"""工作包 K:隐藏评估 CLI(隐藏结果脱敏输出 + 考试包退休)。

用法:
    python -m rl_curriculum.hidden_exam_cli \
        --pack mock_hidden_pack.json --policy rule_trend \
        --out aggregate.json [--retire-registry retired.json] \
        [--detailed detailed.json]

- 默认只输出聚合成绩与状态(逐 Episode trace/种子/参数脱敏);
- --detailed 写出详细结果并立即将该考试包退休(详细结果一旦公开,
  该考试包立即退休,不得再次用于评估);
- 评估记录 checkpoint SHA-256 / 课程章程哈希 / 考试包哈希 / 环境版本 /
  评估器代码哈希 / 依赖版本 / 运行时间 / 完整退出状态。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from rl_platform.fingerprint import dependency_versions
from rl_platform.versions import spec_versions
from rl_curriculum.evaluator import EvalConfig, evaluate_policy, evaluator_code_hash
from rl_curriculum.exam_pack import (
    ExamPack,
    RetirementRegistry,
    materialize_pack,
    redact_report,
)
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
from rl_curriculum.policies import (
    AlwaysLongPolicy,
    AlwaysFlatPolicy,
    HighTurnoverPolicy,
    OneStepGreedyPolicy,
    OracleSegmentedDriftPolicy,
    OracleSmoothLatentDriftPolicy,
    PeriodicTogglePolicy,
    RandomPolicy,
    RuleTrendPolicy,
)
from rl_curriculum.verdicts import ModelStatus, status_of

POLICY_ALIASES = {
    "always_flat": AlwaysFlatPolicy,
    "always_long": AlwaysLongPolicy,
    "random": RandomPolicy,
    "periodic_toggle": PeriodicTogglePolicy,
    "one_step_greedy": OneStepGreedyPolicy,
    "high_turnover": HighTurnoverPolicy,
    "rule_trend": RuleTrendPolicy,
    "oracle_segmented_drift": OracleSegmentedDriftPolicy,
    "oracle_smooth_latent_drift": OracleSmoothLatentDriftPolicy,
}


def build_policy(spec: str):
    if spec.startswith("sb3:"):
        from rl_curriculum.policies import SB3CheckpointPolicy

        path = spec[4:]
        return SB3CheckpointPolicy(path)
    if spec not in POLICY_ALIASES:
        raise SystemExit(
            f"未知策略 {spec!r}:可选 {sorted(POLICY_ALIASES)} 或 sb3:<checkpoint.zip>"
        )
    return POLICY_ALIASES[spec]()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="隐藏考试评估 CLI(脱敏输出)")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--retire-registry", default=None)
    ap.add_argument("--detailed", default=None,
                    help="写出详细结果(将立即退休该考试包)")
    ap.add_argument("--fee", type=float, default=0.001)
    args = ap.parse_args(argv)

    started = pd.Timestamp.now(tz="UTC")
    pack = ExamPack.load(args.pack)
    registry = (
        RetirementRegistry(args.retire_registry)
        if args.retire_registry else RetirementRegistry(
            Path(args.pack).parent / "retired_packs.json")
    )
    cfg = EvalConfig(fee=args.fee)
    policy = build_policy(args.policy)
    try:
        episodes = materialize_pack(
            pack, DEFAULT_GENERATOR_REGISTRY, retire_registry=registry
        )
        report = evaluate_policy(
            policy, episodes, cfg,
            baseline_policies={
                "always_flat": AlwaysFlatPolicy(),
                "rule_trend": RuleTrendPolicy(),
            },
        )
        status = "PASS" if report["overall"]["median"] > 0 else "FAIL"
        machine_status = status_of(status).value
        exit_code = 0
        error = None
    except Exception as exc:  # noqa: BLE001 - 考试无效必须显式记录
        report = None
        machine_status = ModelStatus.EXAM_INVALID.value
        exit_code = 5
        error = repr(exc)

    out = {
        "exam_cli_version": "hidden-exam-cli-v1",
        "pack_name": pack.name,
        "pack_hash": pack.pack_hash(),
        "pack_visibility": pack.visibility,
        "policy": args.policy,
        "status": machine_status,
        "error": error,
        "spec_versions": spec_versions(),
        "evaluator_code_hash": evaluator_code_hash(),
        "dependencies": dependency_versions(),
        "started_utc": started.isoformat(),
        "finished_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "exit_code": exit_code,
        "aggregate": (
            redact_report(report, pack.visibility) if report else None
        ),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[hidden_exam_cli] 状态={machine_status} 输出 -> {args.out}")

    if args.detailed and report is not None:
        registry.retire(
            pack.pack_hash(),
            reason=f"详细结果已公开(--detailed -> {args.detailed})",
        )
        Path(args.detailed).write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(
            f"[hidden_exam_cli] 详细结果 -> {args.detailed};"
            f"考试包 {pack.pack_hash()} 已退休"
        )
    elif args.detailed:
        print(
            "[hidden_exam_cli] 考试无效(EXAM_INVALID),无详细结果可公开,"
            "不退休考试包",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
