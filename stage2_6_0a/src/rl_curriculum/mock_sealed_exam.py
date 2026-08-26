"""阶段 2.6.0a 工作包 O:mock 密封考试基础设施(公开,无正式资格)。

独立评估方用本模块在考试开始前创建:
- mock hidden pack(visibility=mock_hidden,公开标记,只用于测试密封
  考试基础设施,不具备正式考试资格);
- 考试上下文(charter / observation schema / 判定器 / EvalConfig 的
  JSON 载体;任何篡改都会在 sealed 验证时因哈希不匹配失败);
- sealed commitment(绑定 pack/charter/schema/版本/代码哈希/判定器/
  EvalConfig/checkpoint 要求)。

本模块不得创建正式隐藏种子或正式隐藏生成器。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rl_curriculum.charter import charter_hash
from rl_curriculum.evaluator import EvalConfig, evaluator_code_hash
from rl_curriculum.exam_pack import ExamPack
from rl_curriculum.generator_api import EpisodeSpec
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
from rl_curriculum.probe_charter import (
    audit_probe_charter,
    probe_observation_schema,
)
from rl_curriculum.sealed_exam import (
    SealedExamCommitment,
    generator_bindings,
    module_code_hash,
)
from rl_curriculum.verdict_spec import CourseVerdictSpec, probe_course_verdict_spec
from rl_platform.versions import spec_versions

CONTEXT_FORMAT = "sealed-exam-context-v1"

BASE_PARAMS: dict[str, Any] = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "initial_price": 100.0,
}
EXTRAPOLATION_PARAMS: dict[str, Any] = {
    "episode_bars": 96,
    "drift_bps_range": [30.0, 45.0],
    "vol_bps_range": [32.0, 50.0],
    "initial_price": 100.0,
}
FAMILY_HOLDOUT_PARAMS: dict[str, Any] = {
    "episode_bars": 96,
    "theta": 0.02,
    "sigma_mu_bps": 3.0,
    "vol_bps": 36.0,
    "initial_price": 100.0,
}


def build_mock_hidden_pack(*, name: str = "mock_hidden_probe_pack",
                           version: str = "mock-hidden-v2",
                           timeframe: str = "15m") -> ExamPack:
    """mock 隐藏考试包(公开标记;split 覆盖 G4 全部门 + 多 Null 族)。"""
    episodes: list[EpisodeSpec] = []

    def add(family: str, params: dict[str, Any], seeds, split: str) -> None:
        for s in seeds:
            episodes.append(EpisodeSpec(
                family=family, params=dict(params), seed=int(s),
                split=split, timeframe=timeframe))

    add("probe_segmented_drift", BASE_PARAMS, (101, 102, 103), "train")
    add("probe_segmented_drift", BASE_PARAMS, (201, 202, 203),
        "dev_seed_holdout")
    add("probe_segmented_drift", EXTRAPOLATION_PARAMS, (301, 302, 303),
        "param_extrapolation")
    add("probe_smooth_latent_drift", FAMILY_HOLDOUT_PARAMS,
        (401, 402, 403), "family_holdout")
    add("probe_null_sign", BASE_PARAMS, (501, 502), "null_control")
    add("probe_null_block", BASE_PARAMS, (601, 602), "null_control")
    add("probe_null_volstate", BASE_PARAMS, (701, 702), "null_control")
    return ExamPack(
        name=name, version=version, visibility="mock_hidden",
        charter_hash=charter_hash(audit_probe_charter()),
        spec_versions=spec_versions(),
        episodes=episodes, timeframe=timeframe,
        notes={
            "mock": True,
            "声明": (
                "公开 mock hidden pack:仅用于验证密封考试基础设施,"
                "不构成正式隐藏考试;正式隐藏生成器与种子不进入公开仓库"
            ),
        },
    )


def default_eval_config() -> EvalConfig:
    return EvalConfig(
        fee=0.001, slippage_bps=0.0, price_tick=0.0, initial_cash=100.0,
        reward_scale=1.0, window_size=1, deterministic=True,
    )


def write_exam_context(
    path, *, charter: dict[str, Any] | None = None,
    schema=None, verdict_spec: CourseVerdictSpec | None = None,
    eval_config: EvalConfig | None = None,
) -> dict[str, Any]:
    """写考试上下文(charter/schema/判定器/EvalConfig)。"""
    payload = {
        "format": CONTEXT_FORMAT,
        "charter": charter or audit_probe_charter(),
        "observation_schema": (schema or probe_observation_schema())
        .canonical_payload(),
        "verdict_spec": (verdict_spec or probe_course_verdict_spec())
        .canonical_payload(),
        "eval_config": (eval_config or default_eval_config()).manifest(),
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    return payload


def load_exam_context(path) -> dict[str, Any]:
    from rl_curriculum.observation_schema import schema_from_json
    from rl_curriculum.verdict_spec import CourseVerdictSpec as VS

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != CONTEXT_FORMAT:
        raise RuntimeError(
            f"考试上下文格式 {data.get('format')!r} != {CONTEXT_FORMAT!r}")
    cfg = data["eval_config"]
    vs = data["verdict_spec"]
    return {
        "charter": data["charter"],
        "schema": schema_from_json(json.dumps(data["observation_schema"])),
        "verdict_spec": VS(
            version=vs["version"],
            min_effective_net_return=float(vs["min_effective_net_return"]),
            min_seed_pass_ratio_for_cheat=float(
                vs["min_seed_pass_ratio_for_cheat"]),
            min_replication_episodes=int(vs["min_replication_episodes"]),
            required_positive_splits=tuple(vs["required_positive_splits"]),
            vs_always_flat_ci_low_min=float(vs["vs_always_flat_ci_low_min"]),
            vs_rule_baseline_median_diff_min=float(
                vs["vs_rule_baseline_median_diff_min"]),
            seed_pass_ratio_min=float(vs["seed_pass_ratio_min"]),
            median_turnover_max=float(vs["median_turnover_max"]),
            q10_min=vs.get("q10_min"),
            median_max_drawdown_max=vs.get("median_max_drawdown_max"),
            required_counterfactuals=tuple(vs["required_counterfactuals"]),
            required_null_families=tuple(vs["required_null_families"]),
            notes=vs.get("notes", ""),
        ),
        "eval_config": EvalConfig(**cfg),
    }


def build_mock_commitment(
    *, pack: ExamPack, charter: dict[str, Any], schema,
    verdict_spec: CourseVerdictSpec, eval_config: EvalConfig,
    registry: dict[str, Any] | None = None,
    checkpoint_sha256: str | None = None,
    attempt_policy: dict[str, Any] | None = None,
) -> SealedExamCommitment:
    """独立评估方在考试开始前创建的密封承诺。"""
    import rl_curriculum.counterfactual as cf_module

    registry = registry or DEFAULT_GENERATOR_REGISTRY
    req: dict[str, Any] = {}
    if checkpoint_sha256:
        req["checkpoint_sha256"] = checkpoint_sha256
    return SealedExamCommitment(
        pack_hash=pack.pack_hash(),
        charter_hash=charter_hash(charter),
        observation_schema_hash=schema.schema_hash(),
        spec_versions=spec_versions(),
        generator_bindings=generator_bindings(registry),
        evaluator_code_hash=evaluator_code_hash(),
        counterfactual_code_hash=module_code_hash(cf_module),
        verdict_spec_hash=verdict_spec.verdict_spec_hash(),
        eval_config=eval_config.manifest(),
        checkpoint_requirements=req,
        attempt_policy=attempt_policy or {
            "idempotent_retry": True,
            "max_attempts_per_checkpoint_pack": None,
        },
        notes={"mock": True, "声明": "公开 mock 承诺,验证密封基础设施用"},
    )
