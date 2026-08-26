"""阶段 2.6.0a 工作包 O + 阶段 2.6.0b 工作包 J:mock 密封考试基础设施
(公开,无正式资格)。

独立评估方用本模块在考试开始前创建:
- mock hidden pack(visibility=mock_hidden;严格三族 Null:
  sign/volstate/stochvol——block shuffle 已降级为诊断族,不在包中);
- 考试上下文(charter / observation schema / 判定器 v2 / EvalConfig /
  sandbox profile / 受信 issuer 公开配置的 JSON 载体;任何篡改都会在
  sealed 验证时因哈希不匹配失败);
- sealed commitment v2(绑定 pack/charter/schema/版本/逐族生成器实现
  指纹/evaluator/counterfactual/verdict(含等价区间与复制门槛)/
  EvalConfig/sandbox profile/严格 Null 资格/受信 issuer/resolved
  parameter semantics/checkpoint 要求)。

本模块不得创建正式隐藏种子或正式隐藏生成器;mock issuer 私钥只存在
于评估方临时目录,不交给候选进程。
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
    module_code_hash,
)
from rl_curriculum.verdict_spec import (
    CourseVerdictSpec,
    probe_course_verdict_spec,
    verdict_spec_from_json,
)
from rl_platform.versions import spec_versions

CONTEXT_FORMAT = "sealed-exam-context-v2"

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
                           version: str = "mock-hidden-v3",
                           timeframe: str = "15m") -> ExamPack:
    """mock 隐藏考试包(公开标记;split 覆盖 G4 全部门 + 严格三族 Null)。

    阶段 2.6.0b:probe_null_block(诊断族)不再进入包;
    probe_null_stochvol(独立实现的随机波动率零漂移)加入严格集合。
    """
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
    add("probe_null_volstate", BASE_PARAMS, (701, 702), "null_control")
    add("probe_null_stochvol", BASE_PARAMS, (801, 802), "null_control")
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
            "null_families": (
                "严格三族 probe_null_sign/probe_null_volstate/"
                "probe_null_stochvol;probe_null_block 已重新分类为"
                "partial_dependency_destruction 诊断族,不进入正式包"
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
    sandbox_profile: Any = None,
    trusted_issuer: Any = None,
) -> dict[str, Any]:
    """写考试上下文 v2(charter/schema/判定器/EvalConfig/沙箱/issuer)。"""
    from rl_curriculum.sandbox import default_sandbox_profile

    profile = sandbox_profile or default_sandbox_profile()
    payload = {
        "format": CONTEXT_FORMAT,
        "charter": charter or audit_probe_charter(),
        "observation_schema": (schema or probe_observation_schema())
        .canonical_payload(),
        "verdict_spec": (verdict_spec or probe_course_verdict_spec())
        .canonical_payload(),
        "eval_config": (eval_config or default_eval_config()).manifest(),
        "sandbox_profile": profile.canonical_payload(),
        "trusted_issuer": (trusted_issuer.canonical_payload()
                           if trusted_issuer is not None else None),
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    return payload


def load_exam_context(path) -> dict[str, Any]:
    from rl_curriculum.observation_schema import schema_from_json
    from rl_curriculum.sandbox import SandboxProfile

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != CONTEXT_FORMAT:
        raise RuntimeError(
            f"考试上下文格式 {data.get('format')!r} != {CONTEXT_FORMAT!r}"
            f"(v1 上下文缺少 sandbox profile/trusted issuer,不得用于"
            f"v3 执行器)")
    cfg = data["eval_config"]
    vs = data["verdict_spec"]
    sp = data.get("sandbox_profile") or {}
    out = {
        "charter": data["charter"],
        "schema": schema_from_json(json.dumps(data["observation_schema"])),
        "verdict_spec": verdict_spec_from_json(vs),
        "eval_config": EvalConfig(**cfg),
        "sandbox_profile": SandboxProfile(
            read_exec_dirs=tuple(sp.get("read_exec_dirs") or ()),
            read_only_dirs=tuple(sp.get("read_only_dirs") or ()),
            read_write_dirs=tuple(sp.get("read_write_dirs") or ()),
            rlimits=dict(sp.get("rlimits") or {}),
            step_timeout_seconds=float(sp.get("step_timeout_seconds", 60.0)),
            greeting_timeout_seconds=float(
                sp.get("greeting_timeout_seconds", 120.0)),
        ),
    }
    if data.get("trusted_issuer"):
        from rl_curriculum.attestation import TrustedIssuerConfig

        ti = data["trusted_issuer"]
        out["trusted_issuer"] = TrustedIssuerConfig(
            issuer_id=ti["issuer_id"],
            public_key_pem=ti["public_key_pem"],
            key_fingerprint=ti["key_fingerprint"],
            required_training_runner_hash=ti["required_training_runner_hash"],
            allow_smoke=bool(ti.get("allow_smoke", False)),
        )
    return out


def build_mock_commitment(
    *, pack: ExamPack, charter: dict[str, Any], schema,
    verdict_spec: CourseVerdictSpec, eval_config: EvalConfig,
    registry: dict[str, Any] | None = None,
    checkpoint_sha256: str | None = None,
    attempt_policy: dict[str, Any] | None = None,
    sandbox_profile: Any = None,
    trusted_issuer: Any = None,
    null_qualification_bindings: dict[str, dict[str, Any]]
    | None = None,
) -> SealedExamCommitment:
    """独立评估方在考试开始前创建的密封承诺 v2(全量绑定)。"""
    import rl_curriculum.counterfactual as cf_module
    from rl_curriculum.generator_binding import generator_bindings
    from rl_curriculum.null_qualification import qualification_code_hash
    from rl_curriculum.param_resolution import (
        resolved_parameter_semantics_hash,
    )
    from rl_curriculum.sandbox import default_sandbox_profile

    registry = registry or DEFAULT_GENERATOR_REGISTRY
    profile = sandbox_profile or default_sandbox_profile()
    req: dict[str, Any] = {}
    if checkpoint_sha256:
        req["checkpoint_sha256"] = checkpoint_sha256
    # 逐族实现绑定(只保留三元组;完整 manifest 存 evidence artifacts)
    bindings = {
        family: {
            "family_version": b["family_version"],
            "implementation_hash": b["implementation_hash"],
            "manifest_hash": b["manifest_hash"],
        }
        for family, b in generator_bindings(registry).items()
    }
    if trusted_issuer is None:
        raise ValueError(
            "v2 承诺必须绑定受信训练签发方(trusted_issuer);"
            "mock 流程使用 mock issuer")
    return SealedExamCommitment(
        pack_hash=pack.pack_hash(),
        charter_hash=charter_hash(charter),
        observation_schema_hash=schema.schema_hash(),
        spec_versions=spec_versions(),
        generator_bindings=bindings,
        evaluator_code_hash=evaluator_code_hash(),
        counterfactual_code_hash=module_code_hash(cf_module),
        verdict_spec_hash=verdict_spec.verdict_spec_hash(),
        eval_config=eval_config.manifest(),
        sandbox_profile_hash=profile.profile_hash(),
        nuisance_equivalence_spec=(
            verdict_spec.nuisance_equivalence.canonical_payload()),
        anticheat_replication_spec={
            "min_distinct_cheat_seeds": (
                verdict_spec.min_distinct_cheat_seeds),
            "min_failing_cheat_episodes": (
                verdict_spec.min_failing_cheat_episodes),
            "min_effective_net_return": (
                verdict_spec.min_effective_net_return),
            "min_seed_pass_ratio_for_cheat": (
                verdict_spec.min_seed_pass_ratio_for_cheat),
        },
        null_qualification_bindings=(
            null_qualification_bindings
            or {f: {"qualification_pass": True} for f in
                verdict_spec.required_null_families}),
        null_qualification_code_hash=qualification_code_hash(),
        trusted_issuer=trusted_issuer.canonical_payload(),
        resolved_parameter_semantics_hash=resolved_parameter_semantics_hash(),
        checkpoint_requirements=req,
        attempt_policy=attempt_policy or {
            "idempotent_retry": True,
            "max_attempts_per_checkpoint_pack": None,
        },
        notes={"mock": True, "声明": "公开 mock 承诺 v2,验证密封基础设施用"},
    )
