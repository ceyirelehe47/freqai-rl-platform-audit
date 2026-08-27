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


def assemble_mock_hidden_pack(
    *, name: str = "mock_hidden_probe_pack",
    version: str = "mock-hidden-v5",
    timeframe: str = "15m",
    null_attempt: int = 0,
) -> "ExamPack":
    """mock 隐藏考试包的实际组装函数(阶段 2.6.0e D6:builder manifest
    绑定的"真正构造 EpisodeSpec 的 builder 函数",模块级可哈希)。

    阶段 2.6.0b:probe_null_block(诊断族)不再进入包;stochvol 加入。
    阶段 2.6.0d(任务书 B2/B4):每族 null_control 扩容到 32 个独立
    seed cluster(seeds 来自 pack_construction namespace 的确定性
    推导,与资格/训练/dev 种子隔离;attempt 推进 seeds——构建规则
    在候选出现前冻结,不依赖任何候选模型成绩)。
    本函数签名不含 candidate/checkpoint/model/policy(D6 签名政策)。
    """
    from rl_curriculum.null_qualification_spec import (
        MIN_PACK_CLUSTERS_PER_FAMILY,
        pack_construction_seeds,
        pack_order_seed,
    )

    episodes: list[EpisodeSpec] = []

    def add(family: str, params: dict[str, Any], seeds,
            split: str) -> None:
        for s in seeds:
            episodes.append(EpisodeSpec(
                family=family, params=dict(params), seed=int(s),
                split=split, timeframe=timeframe))

    add("probe_segmented_drift", BASE_PARAMS, (101, 102, 103), "train")
    add("probe_segmented_drift", BASE_PARAMS, (201, 202, 203),
        "dev_seed_holdout")
    add("probe_segmented_drift", EXTRAPOLATION_PARAMS,
        (301, 302, 303), "param_extrapolation")
    add("probe_smooth_latent_drift", FAMILY_HOLDOUT_PARAMS,
        (401, 402, 403), "family_holdout")
    # 严格 Null 三族:每族 32 个 base seed x (orig, antithetic flip)
    # = 64 Episode = 32 独立 pair cluster(B2/B3);pair 内镜像使
    # 无条件多头优势与累计漂移在 pack 层精确抵消;pair 顺序由
    # 构建 namespace seeded 随机化(镜像关系不可由固定顺序识别)
    import numpy as _np

    for fam in ("probe_null_sign", "probe_null_volstate",
                "probe_null_stochvol"):
        base_seeds = pack_construction_seeds(
            fam, null_attempt, MIN_PACK_CLUSTERS_PER_FAMILY)
        order_rng = _np.random.default_rng(pack_order_seed(fam, null_attempt))
        flip_params = dict(BASE_PARAMS)
        flip_params["antithetic_flip"] = True
        for s in order_rng.permutation(len(base_seeds)):
            episodes.append(EpisodeSpec(
                family=fam, params=dict(flip_params),
                seed=int(base_seeds[s]), split="null_control",
                timeframe=timeframe))
            episodes.append(EpisodeSpec(
                family=fam, params=dict(BASE_PARAMS),
                seed=int(base_seeds[s]), split="null_control",
                timeframe=timeframe))
    return ExamPack(
        name=name, version=version, visibility="mock_hidden",
        charter_hash=charter_hash(audit_probe_charter()),
        spec_versions=spec_versions(),
        episodes=episodes, timeframe=timeframe,
        notes={
            "mock": True,
            "声明": (
                "公开 mock hidden pack:仅用于验证密封考试基础设施,"
                "不构成正式隐藏考试;正式隐藏生成器与种子不进入公开"
                "仓库"
            ),
            "null_families": (
                "严格三族 probe_null_sign/probe_null_volstate/"
                "probe_null_stochvol;probe_null_block 已重新分类为"
                "partial_dependency_destruction 诊断族,不进入正式包"
            ),
            "null_pack_builder": (
                "阶段 2.6.0d:每族 32 独立 seed cluster,seeds 由 "
                "pack_construction namespace 确定性推导并按 "
                "attempt 推进;构建只依赖 pack-level Null 结构"
                "验证,与任何候选 checkpoint 无关"
            ),
        },
    )


def build_mock_hidden_pack(*, name: str = "mock_hidden_probe_pack",
                           version: str = "mock-hidden-v5",
                           timeframe: str = "15m",
                           null_attempt: int = 0,
                           with_builder_log: bool = False):
    """mock 隐藏考试包入口(attempt 循环在此;assemble 在上方模块级
    函数,二者都被 builder manifest 绑定——D6)。

    with_builder_log=True 时返回 (pack, builder_log);builder_log 记录
    各 attempt 的 pack-level 验证结果与匿名拒绝原因(B4)。
    """
    if not with_builder_log:
        return assemble_mock_hidden_pack(
            name=name, version=version, timeframe=timeframe,
            null_attempt=null_attempt)

    # 预注册构建循环(B4):attempt 0..MAX-1,pack-level validity 通过
    # 即选定;全部失败则拒绝构建(记录匿名原因)
    from rl_curriculum.null_pack_validation import (
        MAX_PACK_ATTEMPTS,
        pack_builder_attempt_log,
    )

    cfg = default_eval_config()
    schema = probe_observation_schema()
    # 阶段 2.6.0g(P7):builder 身份显式构造(mock 构建流程自身的
    # 显式 Provider;不存在隐式 fallback)
    from rl_curriculum.builder_identity import MockBuilderIdentityProvider

    identity = MockBuilderIdentityProvider().builder_identity()
    from rl_curriculum.builder_provenance import ATTEMPT_LOG_FORMAT

    attempts: list[dict[str, Any]] = []
    for attempt in range(MAX_PACK_ATTEMPTS):
        pack = assemble_mock_hidden_pack(
            name=name, version=version, timeframe=timeframe,
            null_attempt=attempt)
        report = _validate_pack_ephemeral(
            pack, cfg, schema, builder_identity=identity)
        reject = [] if report["pass"] else report["reasons"][:3]
        attempts.append({
            "attempt": attempt,
            "verdict": "accept" if report["pass"] else "reject",
            "reject_reasons": reject,
        })
        if report["pass"]:
            # 规范化 attempt log(D4:builder-attempt-log-v1——
            # attempt 序号/最大 attempt/每次结果/匿名拒绝原因/最终
            # 选中的 attempt/输出 pack hash,不再只记录条目数量)
            return pack, {
                "format": ATTEMPT_LOG_FORMAT,
                "max_attempts": int(MAX_PACK_ATTEMPTS),
                "attempts": attempts,
                "selected_attempt": attempt,
                "output_pack_hash": pack.pack_hash(),
            }
    raise RuntimeError(
        f"mock null pack 构建在 {MAX_PACK_ATTEMPTS} 次尝试内未通过 "
        f"pack-level validity(不应发生;请检查生成器/参数)")


def mock_build_pack(request):
    """builder-runner-protocol-v2 的 mock build 入口(公开组装器)。

    统一适配形态 ``build_pack(frozen_build_request) -> build_result``
    (精确单 request 位置参数,C1)。mock_payload_assembly 模式的请求
    携带 ``mock_pack_payload``(mock builder 是公开验证基础设施的
    "组装器",其冻结构建输入就是 pack 的公开规范):按载荷确定性
    重建 ExamPack(ExamPack.from_json 完全确定,pack_hash 由证明层
    对账)。返回 builder-build-result-v2(组装模式的规范化 attempt
    log:max_attempts=0,无 attempt 条目——重组装不重跑构建循环,
    这是诚实记录而不是缺失)。

    本函数签名是单 request 位置参数(协议合同),不含
    candidate/checkpoint/model/policy(签名政策)。
    """
    import json as _json

    from rl_curriculum.builder_provenance import (
        ATTEMPT_LOG_FORMAT,
        BUILD_REQUEST_FORMAT,
        BUILD_RESULT_FORMAT,
        BUILDER_RUNNER_PROTOCOL,
    )

    if not isinstance(request, dict) or request.get(
            "format") != BUILD_REQUEST_FORMAT:
        return {
            "format": BUILD_RESULT_FORMAT,
            "runner_protocol": BUILDER_RUNNER_PROTOCOL,
            "status": "failed",
            "pack": None,
            "attempt_log": [],
            "error": (f"冻结构建请求格式无效(需要 "
                      f"{BUILD_REQUEST_FORMAT!r};收到 "
                      f"{type(request).__name__})"),
        }
    payload = request.get("mock_pack_payload")
    if isinstance(payload, dict):
        try:
            pack = ExamPack.from_json(_json.dumps(payload))
        except Exception as exc:  # noqa: BLE001 - 载荷不可解析即 failed
            return {
                "format": BUILD_RESULT_FORMAT,
                "runner_protocol": BUILDER_RUNNER_PROTOCOL,
                "status": "failed",
                "pack": None,
                "attempt_log": [],
                "error": f"mock_pack_payload 无法重建 ExamPack: "
                         f"{type(exc).__name__}: {exc}",
            }
        return {
            "format": BUILD_RESULT_FORMAT,
            "runner_protocol": BUILDER_RUNNER_PROTOCOL,
            "status": "ok",
            "pack": _json.loads(pack.to_json()),
            "attempt_log": {
                "format": ATTEMPT_LOG_FORMAT,
                "max_attempts": 0,
                "attempts": [],
                "selected_attempt": None,
                "output_pack_hash": pack.pack_hash(),
            },
            "error": None,
        }
    try:
        pack, log = build_mock_hidden_pack(
            name=str(request.get("pack_name")
                     or "mock_hidden_probe_pack"),
            version=str(request.get("pack_version")
                        or "mock-hidden-v5"),
            timeframe=str(request.get("timeframe") or "15m"),
            with_builder_log=True)
    except Exception as exc:  # noqa: BLE001 - 构建异常即 failed
        return {
            "format": BUILD_RESULT_FORMAT,
            "runner_protocol": BUILDER_RUNNER_PROTOCOL,
            "status": "failed",
            "pack": None,
            "attempt_log": [],
            "error": f"mock builder 构建失败: {type(exc).__name__}: {exc}",
        }
    return {
        "format": BUILD_RESULT_FORMAT,
        "runner_protocol": BUILDER_RUNNER_PROTOCOL,
        "status": "ok",
        "pack": _json.loads(pack.to_json()),
        "attempt_log": dict(log),
        "error": None,
    }


def _validate_pack_ephemeral(pack: ExamPack, cfg, schema, *,
                             builder_identity=None,
                             ) -> dict[str, Any]:
    """物化 pack 内 null episodes 并执行 pack-level validity(构建期
    选择标准;不涉及任何候选)。

    阶段 2.6.0f:duration 从 pack 全部 required Null Episode 派生的
    全局合同取得(不再取第一个 Episode,无 96 回退);builder 身份由
    Provider 显式传入(mock 流程使用 MockBuilderIdentityProvider)。
    阶段 2.6.0g(P7):隐式 Mock Provider fallback 已删除——
    builder_identity 缺失即 ValueError(不存在"没有 Provider 就自动
    使用 mock builder"的内部回退;调用方必须显式传入)。
    """
    from rl_curriculum.builder_identity import require_builder_identity
    from rl_curriculum.generators import FORMAL_NULL_FAMILIES
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )
    from rl_curriculum.null_pack_validation import build_spec_for_pack
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R

    try:
        identity = require_builder_identity(
            builder_identity, where="_validate_pack_ephemeral")
    except Exception as exc:  # noqa: BLE001 - 转为构建期显式失败
        raise ValueError(
            f"_validate_pack_ephemeral 缺少 builder 身份(2.6.0g P7:"
            f"隐式 Mock Provider fallback 已删除;调用方必须显式传入"
            f" Provider 派生的 BuilderIdentity): {exc}") from exc
    contract = derive_global_null_duration_contract(
        pack, required_families=list(FORMAL_NULL_FAMILIES))
    by_family: dict[str, list[Any]] = {}
    for spec in pack.episodes:
        if spec.split == "null_control":
            by_family.setdefault(spec.family, []).append(
                R[spec.family].generate(
                    dict(spec.params), spec.seed, split=spec.split,
                    timeframe=spec.timeframe))
    qspec = build_spec_for_pack(
        cfg, timeframe=contract["timeframe"],
        episode_bars=int(contract["resolved_bars"]))
    from rl_curriculum.null_pack_validation import validate_null_pack

    return validate_null_pack(
        by_family, cfg=cfg, schema=schema, spec=qspec,
        builder_identity=identity, duration_contract=contract)


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
    power_analysis_report: dict[str, Any] | None = None,
    pack_validity_report: dict[str, Any] | None = None,
    builder_provider: Any = None,
    evidence_path: str | None = None,
) -> SealedExamCommitment:
    """独立评估方在考试开始前创建的密封承诺 v6(全量绑定)。

    阶段 2.6.0c 工作包 B/D:候选运行时逐文件 manifest 绑定;真实
    Null 资格报告绑定(bool-only 占位通道不存在)。
    阶段 2.6.0d(任务书 A3/A4/A5/B2/B4/C2):
    - 绑定 Null 资格规范哈希(nqs-:margin 只来自按 EvalConfig 精确
      计算的往返摩擦;统计协议/聚合规则/功效目标/seed namespace);
    - 绑定确定性功效分析(npa- 报告 hash + npac- 代码 hash + 非敏感
      摘要;targets_met 必须为真);
    - 绑定 pack 构建算法哈希(npb-)与实际 pack 的 pack-level
      validity(npv- 报告 hash + pack_hash + 非敏感摘要;完整报告
      由执行器对物化 pack 现算对账——隐藏 seed 不进公开承诺)。
    阶段 2.6.0f 工作包 A/B/C:
    - builder 身份必须来自 Builder Identity Provider(mock 流程显式
      构造 MockBuilderIdentityProvider;正式私有流程显式传入
      PrivateBuilderIdentityProvider——本函数不读取候选/pack/
      context 中的任何 builder 声明);
    - 绑定全局 strict Null duration contract(ndc-:从 pack 全部
      required Null Episode 派生唯一合同;不再取第一个 Episode,
      无 96 回退);
    - pack validity 报告的 duration contract hash 必须与本合同一致。
    """
    import rl_curriculum.counterfactual as cf_module
    from rl_curriculum.builder_identity import (
        BuilderIdentityProvider,
    )
    from rl_curriculum.generator_binding import generator_bindings
    from rl_curriculum.generators import FORMAL_NULL_FAMILIES
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
        null_duration_contract_hash,
    )
    from rl_curriculum.null_qualification import (
        NULL_BINDING_KEYS,
        qualification_code_hash,
    )
    from rl_curriculum.null_qualification_spec import (
        build_spec_payload,
        null_qualification_spec_hash,
        verify_spec_payload,
    )
    from rl_curriculum.null_power_analysis import (
        power_analysis_code_hash,
        power_analysis_report_hash,
    )
    from rl_curriculum.null_pack_validation import (
        pack_validity_report_hash,
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
    # ---- 工作包 A:builder 身份显式来自 Provider(阶段 2.6.0g P7:
    #      builder_provider=None 的隐式 Mock fallback 已删除——
    #      公开 mock 流程必须显式传入 MockBuilderIdentityProvider,
    #      正式私有流程显式传入评估方自己的 Provider;本函数不读取
    #      候选/pack/context 中的任何 builder 声明)
    if builder_provider is None:
        raise ValueError(
            "build_mock_commitment 必须显式传入 builder_provider"
            "(BuilderIdentityProvider 协议):阶段 2.6.0g 已删除内部"
            "隐式 Mock Provider fallback;公开 mock 流程显式传入 "
            "MockBuilderIdentityProvider()")
    if not isinstance(builder_provider, BuilderIdentityProvider):
        raise ValueError(
            "builder_provider 必须实现 BuilderIdentityProvider 协议"
            "(builder_identity() -> BuilderIdentity);不接受的类型:"
            f"{type(builder_provider)!r}")
    builder_identity = builder_provider.builder_identity()
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
    # 工作包 D(2.6.0c):bool fallback 已删除——必须提供逐族真实资格
    # 报告绑定;阶段 2.6.0d:报告为 v3 三态格式,只有 QUALIFIED 结论
    # 能通过正式验证(cluster 功效门槛 64,见 null_qualification)
    if null_qualification_bindings is None:
        raise ValueError(
            "v3 承诺必须绑定真实 Null 资格报告:先用 qualify_null_family"
            "(每族 >= 64 个独立 seed cluster,阶段 2.6.0d 三态协议)"
            "生成 QUALIFIED 报告,再 build_null_qualification_"
            "bindings(reports) 传入;{qualification_pass: true} 占位"
            "绑定已被禁止(阶段 2.6.0c 工作包 D)")
    for fam, bound in null_qualification_bindings.items():
        if set(bound) != set(NULL_BINDING_KEYS):
            raise ValueError(
                f"Null 族 {fam!r} 的资格绑定不是 v3 结构(缺真实报告"
                f"payload 的 bool-only 绑定被禁止):键 {sorted(bound)}")
    # ---- 阶段 2.6.0e:A5 功效分析与 B2 pack-level validity 必须真实
    if power_analysis_report is None:
        raise ValueError(
            "v5 承诺必须绑定确定性功效分析报告:先 run_power_analysis"
            "(真实 family 报告的经验 cluster 分布,中心化 + 四块完整"
            "硬目标)生成 targets_met 为真的报告再传入;无功效分析的 "
            "Null 资格不得进入考试")
    if power_analysis_report.get("targets", {}).get("targets_met") \
            is not True:
        targets = power_analysis_report.get("targets")
        raise ValueError(
            f"功效分析未达标(targets_met 不为真):{targets}"
            f"——不得降低标准掩盖功效不足")
    if power_analysis_report.get("format") != "null-power-analysis-v2":
        raise ValueError(
            "功效分析报告必须是 null-power-analysis-v2(中心化经验分布"
            "+ 四块 required 硬目标 + Wilson 保守置信界;v1 已弃用)")
    if pack_validity_report is None:
        raise ValueError(
            "v5 承诺必须绑定实际 Null pack 的 pack-level validity 报告"
            ":对物化 null episodes 运行 validate_null_pack(PACK_VALID)"
            " 再传入;只做 family-level 资格而无 pack-level 验证的"
            "考试不得开始")
    if pack_validity_report.get("verdict") != "PACK_VALID":
        raise ValueError(
            f"实际 pack 未通过 pack-level validity("
            f"{pack_validity_report.get('verdict')}):"
            f"{pack_validity_report.get('reasons', [])[:2]}"
            f"(pack 偶然漂移时必须重建 pack,不得用于正式考试)")
    if pack_validity_report.get("format") != "null-pack-validity-v3":
        raise ValueError(
            "pack validity 报告必须是 null-pack-validity-v3(每 seed "
            "恰好 (orig, flip) 各一 + 物化镜像验证 + nuisance 逐位一致"
            "+ 四块中心与置信上界硬门 + Provider 派生 builder hash + 全局"
            " duration contract 绑定;v1/v2 已弃用)")
    # ---- 全局 strict Null duration contract(工作包 C:从 pack 全部
    #      required Null Episode 派生唯一合同;不再取第一个 Episode,
    #      无 96 回退)
    duration_contract = derive_global_null_duration_contract(
        pack, required_families=list(FORMAL_NULL_FAMILIES))
    duration_contract_hash = null_duration_contract_hash(
        duration_contract)
    # ---- 冻结构建请求(阶段 2.6.0g:承诺绑定 builder 重放的冻结
    #      输入;v2 精确字段白名单 + mode 绑定;请求由评估方代码从
    #      identity+pack+合同统一派生,不含候选字段,验证端重放时
    #      输入不可被替换)
    from rl_curriculum.builder_provenance import (
        frozen_build_request_hash,
    )

    builder_build_request = builder_provider.frozen_build_request(
        pack, duration_contract)
    builder_build_request_hash = frozen_build_request_hash(
        builder_build_request)
    # ---- Builder Run Evidence + precommit 双重运行(阶段 2.6.0g
    #      收尾 E2:承诺创建前在两个全新独立运行中执行同一 Builder,
    #      三组 hash(pack/attempt log/runtime lock)必须完全一致;
    #      不一致 -> Builder 不确定,不得创建承诺。完整 evidence 由
    #      调用方写入评估方私有目录,公开承诺只携带摘要)
    from rl_curriculum.builder_evidence import (
        precommit_builder_runs,
    )

    builder_evidence, _runs = precommit_builder_runs(
        builder_provider, builder_build_request)
    # pack validity 报告的 duration contract 必须与本 pack 派生的全局
    # 合同一致(构建期与执行器同源对账)
    if pack_validity_report.get("duration_contract_hash") not in (
            "", None) and pack_validity_report.get(
                "duration_contract_hash") != duration_contract_hash:
        raise ValueError(
            "pack_validity 报告的 duration contract hash 与本 pack 派生"
            "的全局合同不一致(时长不得从个别 Episode 推导)")
    # ---- 资格规范(margin 只来自规范;与本次考试材料绑定;
    #      episode_bars 来自全局合同)
    nq_spec = build_spec_payload(
        eval_config, timeframe=duration_contract["timeframe"],
        episode_bars=int(duration_contract["resolved_bars"]))
    spec_problems = verify_spec_payload(nq_spec)
    if spec_problems:
        raise ValueError(f"qualification spec 自洽失败: {spec_problems}")
    # pack_validity 报告必须对应本 pack(报告由 validate_null_pack 对
    # 物化 episodes 完全确定;执行器将现算同一报告并对账 hash)
    if pack_validity_report.get("verdict") != "PACK_VALID":  # 双保险
        raise ValueError("pack_validity 报告 verdict 非 PACK_VALID")
    pv_pack_hash = pack_validity_report.get("pack_hash")
    if pv_pack_hash not in ("", None) and pv_pack_hash != pack.pack_hash():
        raise ValueError("pack_validity 报告与本 pack 不一致(pack_hash)")
    # 工作包 B:绑定沙箱内实际执行的候选运行时(逐文件内容哈希)
    runtime_manifest = compute_runtime_manifest()
    if evidence_path is not None:
        from rl_curriculum.builder_evidence import (
            write_builder_run_evidence,
        )

        write_builder_run_evidence(evidence_path, builder_evidence)
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
        null_qualification_spec_hash=null_qualification_spec_hash(nq_spec),
        null_power_analysis={
            "report_hash": power_analysis_report_hash(
                power_analysis_report),
            "code_hash": power_analysis_code_hash(),
            "scenario_spec_hash": power_analysis_report.get(
                "scenario_manifest_hash"),
            # 阶段 2.6.0e 工作包 C:public_summary 是从完整报告 **派生**
            # 的摘要(不是信任源;执行器重跑完整报告并逐项对账)
            "public_summary": {
                "margin": power_analysis_report.get("margin"),
                "min_qualification_clusters": power_analysis_report.get(
                    "min_qualification_clusters"),
                "targets_met": bool(power_analysis_report["targets"][
                    "targets_met"]),
                "required_scenario_count": power_analysis_report.get(
                    "required_scenario_count"),
                "max_false_invalid_at_zero": power_analysis_report.get(
                    "targets", {}).get("max_false_invalid_at_zero"),
                "max_false_qualified_at_2x_margin":
                    power_analysis_report.get("targets", {}).get(
                        "max_false_qualified_at_2x_margin"),
                "min_rejection_power_at_1x_margin":
                    power_analysis_report.get("targets", {}).get(
                        "min_rejection_power_at_1x_margin"),
            },
        },
        pack_builder_code_hash=builder_identity.manifest_hash,
        pack_validity={
            "report_hash": pack_validity_report_hash(pack_validity_report),
            "pack_hash": pack.pack_hash(),
            "public_summary": {
                "verdict": "PACK_VALID",
                "per_family_clusters": {
                    fam: fam_block["n_clusters"]
                    for fam, fam_block in (
                        pack_validity_report.get("per_family")
                        or {}).items()},
            },
        },
        null_duration_contract=dict(duration_contract),
        null_duration_contract_hash=duration_contract_hash,
        builder_build_request=dict(builder_build_request),
        builder_build_request_hash=builder_build_request_hash,
        builder_run_evidence={
            k: v for k, v in builder_evidence.items()
            if k != "detail"
        },
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
        notes={"mock": True, "声明": "公开 mock 承诺 v7,验证密封基础设施用"},
    )
