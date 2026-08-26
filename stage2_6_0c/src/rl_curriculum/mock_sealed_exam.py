"""阶段 2.6.0a 工作包 O + 2.6.0b 工作包 J + 2.6.0c 工作包 F:mock 密封
考试基础设施(公开,无正式资格)。

独立评估方用本模块在考试开始前创建:
- mock hidden pack(visibility=mock_hidden;严格三族 Null:
  sign/volstate/stochvol——block shuffle 已降级为诊断族,不在包中);
- 考试上下文 v3(charter / observation schema / 判定器 v3 / EvalConfig
  / sandbox profile;issuer 仅作为展示副本保留——正式信任根唯一来自
  sealed commitment,context 副本必须与承诺逐字段 canonical equality,
  任何不同都 EXAM_INVALID,阶段 2.6.0c 工作包 A);
- sealed commitment v3(绑定 pack/charter/schema/版本/逐族生成器实现
  指纹/evaluator/counterfactual/verdict(含等价区间、复制门槛与 seed
  聚合规则)/EvalConfig/sandbox profile/候选运行时 manifest(B)/
  严格 Null 资格真实报告绑定(D)/受信 issuer/resolved parameter
  semantics/checkpoint 要求)。

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

CONTEXT_FORMAT = "sealed-exam-context-v3"

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
    """写考试上下文 v3(charter/schema/判定器/EvalConfig/沙箱/issuer
    展示副本)。

    阶段 2.6.0c 工作包 A:trusted_issuer 在 context 中只是展示副本,
    不再是信任根来源——正式执行器只从 sealed commitment 构造信任根,
    副本与承诺任何字段不同都会 EXAM_INVALID。
    """
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
            f"(v2 及更早上下文不得进入 v4 执行器:issuer 信任根已收归"
            f"sealed commitment,context issuer 通道已关闭;"
            f"必须用 write_exam_context 重新生成)")
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
    # 工作包 A:issuer 只是展示副本(raw canonical payload),由执行器
    # 与承诺做逐字段 canonical equality 检查——不在此构造信任根
    if data.get("trusted_issuer"):
        out["trusted_issuer_payload"] = dict(data["trusted_issuer"])
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
    """独立评估方在考试开始前创建的密封承诺 v3(全量绑定)。

    阶段 2.6.0c 工作包 B/D:
    - 必须绑定候选运行时 manifest(candidate_runtime_manifest/hash,
      沙箱内实际执行的 rl_candidate_runtime 逐文件内容哈希);
    - null_qualification_bindings 必须是 build_null_qualification_
      bindings(真实资格审查报告) 的输出——缺少任何 required 家族的
      真实报告立即失败,不存在 {qualification_pass: true} 占位通道。
    """
    import rl_curriculum.counterfactual as cf_module
    from rl_curriculum.generator_binding import generator_bindings
    from rl_curriculum.null_qualification import (
        NULL_BINDING_KEYS,
        qualification_code_hash,
    )
    from rl_curriculum.param_resolution import (
        resolved_parameter_semantics_hash,
    )
    from rl_curriculum.sandbox import (
        compute_runtime_manifest,
        default_sandbox_profile,
        runtime_tree_hash,
    )

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
            "v3 承诺必须绑定受信训练签发方(trusted_issuer);"
            "mock 流程使用 mock issuer")
    # 工作包 D:bool fallback 已删除——必须提供逐族真实资格报告绑定
    if null_qualification_bindings is None:
        raise ValueError(
            "v3 承诺必须绑定真实 Null 资格报告:先用 qualify_null_family"
            "(每族)>= 3 个 seed 生成报告,再 build_null_qualification_"
            "bindings(reports) 传入;{qualification_pass: true} 占位"
            "绑定已被禁止(阶段 2.6.0c 工作包 D)")
    for fam, bound in null_qualification_bindings.items():
        if set(bound) != set(NULL_BINDING_KEYS):
            raise ValueError(
                f"Null 族 {fam!r} 的资格绑定不是 v2 结构(缺真实报告"
                f"payload 的 bool-only 绑定被禁止):键 {sorted(bound)}")
    # 工作包 B:绑定沙箱内实际执行的候选运行时(逐文件内容哈希)
    runtime_manifest = compute_runtime_manifest()
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
        candidate_runtime_manifest=runtime_manifest,
        candidate_runtime_hash=runtime_tree_hash(runtime_manifest),
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
            "seed_aggregation": verdict_spec.seed_aggregation,
        },
        null_qualification_bindings=null_qualification_bindings,
        null_qualification_code_hash=qualification_code_hash(),
        trusted_issuer=trusted_issuer.canonical_payload(),
        resolved_parameter_semantics_hash=resolved_parameter_semantics_hash(),
        checkpoint_requirements=req,
        attempt_policy=attempt_policy or {
            "idempotent_retry": True,
            "max_attempts_per_checkpoint_pack": None,
        },
        notes={"mock": True, "声明": "公开 mock 承诺 v3,验证密封基础设施用"},
    )
