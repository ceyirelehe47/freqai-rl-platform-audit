"""阶段 2.6.0a 工作包 E/M + 2.6.0b 工作包 F/G/H/I + 2.6.0c 工作包
A/B/E:密封考试承诺 v3。

sealed-exam-commitment-v3(阶段 2.6.0c)在 v2 基础上新增/收紧:
- candidate runtime manifest + tree hash(B):沙箱内实际执行的
  rl_candidate_runtime 每个文件的内容哈希逐文件绑定——修改
  bootstrap/worker/guard/versions、增删文件、runtime 协议版本变化
  都使旧承诺失效(v2 只绑定 sandbox profile,不绑定运行时代码);
- issuer 信任根收归承诺(A):正式执行器只从 commitment 的 canonical
  issuer payload 构造 TrustedIssuerConfig(先做自洽校验:重算公钥
  指纹/协议/runner hash 格式/smoke 策略),context 不再是 issuer
  来源——context 携带副本时必须与承诺逐字段 canonical equality;
- Null 资格绑定升级为 v3(阶段 2.6.0d;D):逐族嵌入完整 canonical
  报告 payload(重算 hash + family/version/实现指纹/schema/fee/
  timeframe/seed/checks 全对账),bool-only 绑定(只有
  qualification_pass=true)被拒绝;报告必须是三态协议
  null-qualification-v3——统计单位为 seed cluster(bootstrap n ==
  distinct independent clusters)、经济等价单侧 TOST 带、cluster
  功效门槛 64,且三态结论必须为 QUALIFIED(INSUFFICIENT_EVIDENCE
  不得被自动转换为 PASS);
- 反作弊复制 spec 增加 seed_aggregation 聚合规则(C)。

sealed-exam-commitment-v2(阶段 2.6.0b)新增绑定(继承):
- 每个生成器族的真实实现指纹(implementation hash);
- sandbox profile 哈希(系统级沙箱配置);
- nuisance 双边等价 spec;
- 反作弊复制门槛(逐原因最小不同 seed 数/失败 Episode 数);
- 严格 Null 资格绑定 + 资格审查代码哈希;
- 受信训练签发方(issuer);
- resolved parameter semantics 哈希;
- checkpoint 要求改为 attestation 驱动。

v1/v2 承诺不得被 v3 执行器接受:from_json 显式报出协议版本不兼容
(v2 缺候选运行时内容绑定/真实 Null 报告绑定,issuer 通道曾被
context 覆盖;工作包 E:旧协议不得自动进入新正式考试)。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

SEALED_EXAM_PROTOCOL = "sealed-exam-commitment-v7"
_DEPRECATED_PROTOCOLS = ("sealed-exam-commitment-v1",
                         "sealed-exam-commitment-v2",
                         "sealed-exam-commitment-v3",
                         "sealed-exam-commitment-v4",
                         "sealed-exam-commitment-v5",
                         "sealed-exam-commitment-v6")


class SealedExamError(RuntimeError):
    """密封承诺校验失败(fail closed -> EXAM_INVALID)。"""


def module_code_hash(module: Any) -> str:
    """模块源文件内容哈希(代码身份;实现变化 -> 新哈希)。"""
    src = Path(module.__file__)
    return "m-" + hashlib.sha256(src.read_bytes()).hexdigest()


@dataclass
class SealedExamCommitment:
    """密封考试承诺(独立评估方在考试开始前创建并公布哈希)。"""

    pack_hash: str
    charter_hash: str
    observation_schema_hash: str
    spec_versions: dict[str, str]
    #: 逐族 {family_version, implementation_hash, manifest_hash}(F)
    generator_bindings: dict[str, dict[str, str]]
    evaluator_code_hash: str
    counterfactual_code_hash: str
    verdict_spec_hash: str
    eval_config: dict[str, Any]
    #: 系统级沙箱 profile 哈希(sp-;工作包 C/I)
    sandbox_profile_hash: str = ""
    #: 候选运行时内容绑定(阶段 2.6.0c 工作包 B:逐文件内容哈希
    #: manifest + rt- tree hash;沙箱内实际执行的 rl_candidate_runtime
    #: 全部文件被承诺哈希覆盖,v2 及更早承诺没有此字段)
    candidate_runtime_manifest: dict[str, Any] = field(default_factory=dict)
    candidate_runtime_hash: str = ""
    #: nuisance 双边等价 spec(canonical payload;工作包 D4)
    nuisance_equivalence_spec: dict[str, Any] = field(default_factory=dict)
    #: 反作弊复制门槛(工作包 E)
    anticheat_replication_spec: dict[str, Any] = field(default_factory=dict)
    #: 严格 Null 资格绑定(工作包 H4)
    null_qualification_bindings: dict[str, dict[str, Any]] = field(
        default_factory=dict)
    null_qualification_code_hash: str = ""
    #: Null 资格规范哈希(阶段 2.6.0d A3/A4:margin 只来自规范;统计
    #: 协议/聚合规则/功效目标/seed namespace 经 nqs- 哈希绑定)
    null_qualification_spec_hash: str = ""
    #: 确定性功效分析绑定(阶段 2.6.0d A5:报告 hash + 代码 hash +
    #: 非敏感摘要;完整报告见评估方 artifacts)
    null_power_analysis: dict[str, Any] = field(default_factory=dict)
    #: pack 构建算法哈希(阶段 2.6.0d B4:构建规则在候选出现前冻结)
    pack_builder_code_hash: str = ""
    #: 实际 Null pack 的 pack-level validity(阶段 2.6.0d B2/C3:
    #: 只携带 hash 与非敏感摘要;执行器对物化 pack 现算并逐字段对账,
    #: 失败 -> EXAM_INVALID)
    pack_validity: dict[str, Any] = field(default_factory=dict)
    #: 全局 strict Null duration contract(阶段 2.6.0f 工作包 C:从
    #: 全部 required strict Null family 的 null_control Episode 派生
    #: 的唯一规范化时长合同;公开 duration/timeframe 不属于隐藏 seed)
    null_duration_contract: dict[str, Any] = field(default_factory=dict)
    null_duration_contract_hash: str = ""
    #: builder 冻结构建请求(阶段 2.6.0g P1:builder 重放的冻结输入;
    #: 请求由评估方代码从 identity+pack+duration contract 派生,
    #: 黑名单禁止任何候选字段;执行器重放时输入不可被替换)
    builder_build_request: dict[str, Any] = field(default_factory=dict)
    builder_build_request_hash: str = ""
    #: 受信训练签发方(工作包 G6)
    trusted_issuer: dict[str, Any] = field(default_factory=dict)
    #: 真实时间参数解析语义哈希(工作包 A)
    resolved_parameter_semantics_hash: str = ""
    checkpoint_requirements: dict[str, Any] = field(default_factory=dict)
    attempt_policy: dict[str, Any] = field(default_factory=lambda: {
        "idempotent_retry": True,
        "max_attempts_per_checkpoint_pack": None,
    })
    created_utc: str = ""
    notes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        req = {
            # 工作包 G:正式资格必须来自受信 attestation;
            # sidecar 自声明 boolean 一律无效
            "require_trusted_attestation": True,
            "charter_hash": self.charter_hash,
            "observation_schema_hash": self.observation_schema_hash,
            "checkpoint_sha256": "any-attested",
        }
        req.update(self.checkpoint_requirements)
        self.checkpoint_requirements = req
        if not self.created_utc:
            self.created_utc = pd.Timestamp.now(tz="UTC").isoformat()

    # -------------------------------------------------------------- 规范化
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "protocol_version": SEALED_EXAM_PROTOCOL,
            "pack_hash": self.pack_hash,
            "charter_hash": self.charter_hash,
            "observation_schema_hash": self.observation_schema_hash,
            "spec_versions": self.spec_versions,
            "generator_bindings": self.generator_bindings,
            "evaluator_code_hash": self.evaluator_code_hash,
            "counterfactual_code_hash": self.counterfactual_code_hash,
            "verdict_spec_hash": self.verdict_spec_hash,
            "eval_config": self.eval_config,
            "sandbox_profile_hash": self.sandbox_profile_hash,
            "candidate_runtime_manifest": self.candidate_runtime_manifest,
            "candidate_runtime_hash": self.candidate_runtime_hash,
            "nuisance_equivalence_spec": self.nuisance_equivalence_spec,
            "anticheat_replication_spec": self.anticheat_replication_spec,
            "null_qualification_bindings": self.null_qualification_bindings,
            "null_qualification_code_hash": self.null_qualification_code_hash,
            "null_qualification_spec_hash": self.null_qualification_spec_hash,
            "null_power_analysis": self.null_power_analysis,
            "pack_builder_code_hash": self.pack_builder_code_hash,
            "pack_validity": self.pack_validity,
            "null_duration_contract": self.null_duration_contract,
            "null_duration_contract_hash": self.null_duration_contract_hash,
            "builder_build_request": self.builder_build_request,
            "builder_build_request_hash": self.builder_build_request_hash,
            "trusted_issuer": self.trusted_issuer,
            "resolved_parameter_semantics_hash": (
                self.resolved_parameter_semantics_hash),
            "checkpoint_requirements": self.checkpoint_requirements,
            "attempt_policy": self.attempt_policy,
            "notes": self.notes,
            # created_utc 不进入承诺哈希(创建时间不影响被绑定内容)
        }

    def commitment_hash(self) -> str:
        return "sc-" + hashlib.sha256(
            json.dumps(self.canonical_payload(), sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    # -------------------------------------------------------------- 存取
    def to_json(self) -> str:
        return json.dumps(
            {**self.canonical_payload(), "created_utc": self.created_utc},
            indent=2, ensure_ascii=False,
        )

    @staticmethod
    def from_json(text: str) -> "SealedExamCommitment":
        data = json.loads(text)
        if data.get("protocol_version") != SEALED_EXAM_PROTOCOL:
            if data.get("protocol_version") in _DEPRECATED_PROTOCOLS:
                raise SealedExamError(
                    f"sealed manifest 协议版本 "
                    f"{data.get('protocol_version')!r} 已弃用:v2 及更早"
                    f"缺少候选运行时内容绑定与真实 Null 资格报告绑定,"
                    f"issuer 信任根曾可被 context 覆盖;v3 缺少 Null "
                    f"资格规范/功效分析/pack-level validity 绑定;v4 的"
                    f"power 绑定只含 code_hash + public_summary.targets_"
                    f"met(摘要不是信任源)、margin 公式与冻结账本不一致、"
                    f"pack 构建只哈希 validator 文件且 Oracle/Rule 被降级"
                    f"为只看点估计;v5 的 builder manifest 只绑定手工挑选"
                    f"的函数清单(v1 格式,不覆盖实际 attempt 选择链依赖"
                    f"闭包)、formal verifier 无参数调用默认公开 mock "
                    f"builder hash、duration 从第一个/最后一个 null "
                    f"control Episode 推导且无全局 strict Null duration "
                    f"contract 绑定;v6 的 builder identity 只证明评估"
                    f"环境中存在一组被哈希的文件、不证明这组文件的 "
                    f"builder 实际生成了 pack_hash 绑定的 pack(私有入口"
                    f"返回 None 仍可与公开 mock pack 组合通过 formal "
                    f"verification),entrypoint/attempt-loop 只接受字符串"
                    f"声明无真实存在性验证,禁止参数规则只是 manifest 自我"
                    f"声明,CLI 与承诺创建端 Provider 配置解析不同源,"
                    f"外部依赖为手工少数包清单(阶段 2.6.0g)——不得被 "
                    f"v7 执行器自动接受,必须以 {SEALED_EXAM_PROTOCOL!r} "
                    f"重新创建承诺(版本不兼容显式报错,不静默补默认值)")
            raise SealedExamError(
                f"sealed manifest 协议版本 {data.get('protocol_version')!r} "
                f"!= {SEALED_EXAM_PROTOCOL!r}")
        runtime_manifest = dict(
            data.get("candidate_runtime_manifest") or {})
        runtime_hash = str(data.get("candidate_runtime_hash") or "")
        if not runtime_manifest or not runtime_hash:
            raise SealedExamError(
                "v7 承诺必须绑定候选运行时内容(candidate_runtime_"
                "manifest/hash):沙箱内实际执行的 rl_candidate_runtime "
                "每个文件必须被承诺哈希覆盖;缺少 runtime hash 的承诺"
                "不得进入正式考试(阶段 2.6.0c 工作包 B/E)")
        duration_contract = dict(data.get("null_duration_contract") or {})
        duration_contract_hash = str(
            data.get("null_duration_contract_hash") or "")
        if not duration_contract_hash.startswith("ndc-") or (
                not duration_contract):
            raise SealedExamError(
                "v7 承诺必须绑定全局 strict Null duration contract"
                "(null_duration_contract payload + null_duration_"
                "contract_hash, ndc-):所有 required strict Null family "
                "的 resolved duration 必须唯一并进入承诺;缺全局合同"
                "的旧材料不得静默通过(阶段 2.6.0f 工作包 C/D2)")
        from rl_curriculum.null_duration_contract import (
            NULL_DURATION_CONTRACT_FORMAT,
            null_duration_contract_hash as _ndc_hash,
        )

        if duration_contract.get(
                "format") != NULL_DURATION_CONTRACT_FORMAT:
            raise SealedExamError(
                f"duration contract 格式必须是 "
                f"{NULL_DURATION_CONTRACT_FORMAT!r}(收到 "
                f"{duration_contract.get('format')!r})")
        if _ndc_hash(duration_contract) != duration_contract_hash:
            raise SealedExamError(
                "承诺 null_duration_contract payload 与其 ndc- 哈希不一致"
                "(合同被改写;EXAM_INVALID)")
        spec_hash = str(data.get("null_qualification_spec_hash") or "")
        power = dict(data.get("null_power_analysis") or {})
        pack_validity = dict(data.get("pack_validity") or {})
        if not spec_hash.startswith("nqs-"):
            raise SealedExamError(
                "v7 承诺必须绑定 Null 资格规范哈希(null_qualification_"
                "spec_hash, nqs-):经济 margin/统计协议/分块容差/场景"
                "清单/cluster 阶梯只能来自 qualification spec(阶段"
                "2.6.0e A3/B;生成器参数通道已禁止);缺字段的旧承诺不得"
                "静默补默认值")
        if (not str(power.get("report_hash") or "").startswith("npa-")
                or not str(power.get("code_hash") or "").startswith("npac-")
                or not str(power.get("scenario_spec_hash") or "").startswith(
                    "npss-")
                or (power.get("public_summary") or {}).get("targets_met")
                is not True
                or not isinstance(
                    (power.get("public_summary") or {}).get(
                        "required_scenario_count"), int)):
            raise SealedExamError(
                "v7 承诺必须绑定完整功效分析(null_power_analysis:"
                "{report_hash npa-, code_hash npac-, scenario_spec_hash "
                "npss-, public_summary{targets_met, required_scenario_"
                "count}}):public summary 不是信任源——执行器将用当前"
                "代码确定性重跑完整 power analysis 并对账 npa- 哈希"
                "(阶段 2.6.0e 工作包 C;null-power-analysis-v1 已弃用)")
        if (not str(pack_validity.get("report_hash") or "").startswith("npv-")
                or not str(pack_validity.get("pack_hash") or "")):
            raise SealedExamError(
                "v7 承诺必须绑定实际 Null pack 的 pack-level validity"
                "(pack_validity:{report_hash npv-, pack_hash, "
                "public_summary};完整报告由执行器对物化 pack 现算对账,"
                "隐藏 seed 不进公开承诺——阶段 2.6.0d B2/C3)")
        if not str(data.get("pack_builder_code_hash") or "").startswith(
                "npb-"):
            raise SealedExamError(
                "v7 承诺必须绑定 pack 构建算法 manifest 哈希(pack_"
                "builder_code_hash, npb-):必须绑定真实 builder"
                "(builder package tree + 显式外部依赖 manifest,覆盖"
                "assemble/attempt 选择链/seed 推导/pair 顺序/validator"
                " 完整依赖闭包),只哈希 validator 文件或手工函数清单的"
                "旧绑定已废除(阶段 2.6.0f 工作包 B;构建规则必须在候选"
                " checkpoint 出现前冻结)")
        build_request = dict(data.get("builder_build_request") or {})
        build_request_hash = str(
            data.get("builder_build_request_hash") or "")
        if not build_request_hash.startswith("nbr-") or not build_request:
            raise SealedExamError(
                "v7 承诺必须绑定 builder 冻结构建请求(builder_build_"
                "request payload + builder_build_request_hash, nbr-):"
                "产物来源证明在冻结输入下实际执行 builder 并比对 "
                "pack hash,重放输入必须被承诺绑定且不可被替换;缺请求"
                "的旧材料不得静默通过(阶段 2.6.0g P1)")
        from rl_curriculum.builder_provenance import (
            BuilderProvenanceError,
            check_frozen_build_request,
            frozen_build_request_hash as _nbr_hash,
        )

        try:
            check_frozen_build_request(build_request)
        except BuilderProvenanceError as exc:
            raise SealedExamError(
                f"承诺中的冻结构建请求不合法: {exc}"
                f"(EXAM_INVALID)") from exc
        if _nbr_hash(build_request) != build_request_hash:
            raise SealedExamError(
                "承诺 builder_build_request payload 与其 nbr- 哈希不一致"
                "(构建请求被改写;EXAM_INVALID)")
        c = SealedExamCommitment(
            pack_hash=data["pack_hash"],
            charter_hash=data["charter_hash"],
            observation_schema_hash=data["observation_schema_hash"],
            spec_versions=dict(data["spec_versions"]),
            generator_bindings=dict(data["generator_bindings"]),
            evaluator_code_hash=data["evaluator_code_hash"],
            counterfactual_code_hash=data["counterfactual_code_hash"],
            verdict_spec_hash=data["verdict_spec_hash"],
            eval_config=dict(data["eval_config"]),
            sandbox_profile_hash=data.get("sandbox_profile_hash", ""),
            candidate_runtime_manifest=runtime_manifest,
            candidate_runtime_hash=runtime_hash,
            nuisance_equivalence_spec=dict(
                data.get("nuisance_equivalence_spec") or {}),
            anticheat_replication_spec=dict(
                data.get("anticheat_replication_spec") or {}),
            null_qualification_bindings=dict(
                data.get("null_qualification_bindings") or {}),
            null_qualification_code_hash=data.get(
                "null_qualification_code_hash", ""),
            null_qualification_spec_hash=spec_hash,
            null_power_analysis=power,
            pack_builder_code_hash=str(data["pack_builder_code_hash"]),
            pack_validity=pack_validity,
            null_duration_contract=duration_contract,
            null_duration_contract_hash=duration_contract_hash,
            builder_build_request=build_request,
            builder_build_request_hash=build_request_hash,
            trusted_issuer=dict(data.get("trusted_issuer") or {}),
            resolved_parameter_semantics_hash=data.get(
                "resolved_parameter_semantics_hash", ""),
            checkpoint_requirements=dict(data.get("checkpoint_requirements") or {}),
            attempt_policy=dict(data.get("attempt_policy") or {}),
            created_utc=data.get("created_utc", ""),
            notes=dict(data.get("notes") or {}),
        )
        # 重建后按同一规范化规则回填(避免默认值改变承诺语义)
        c.created_utc = data.get("created_utc", c.created_utc)
        return c

    def save(self, path) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(), encoding="utf-8")
        return str(p)

    @staticmethod
    def load(path) -> "SealedExamCommitment":
        p = Path(path)
        if not p.is_file():
            raise SealedExamError(f"sealed manifest 不存在: {p}")
        return SealedExamCommitment.from_json(p.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 验证
def verify_sealed_commitment(
    commitment: SealedExamCommitment,
    *,
    pack: Any,
    charter: dict[str, Any],
    schema: Any,
    registry: dict[str, Any],
    eval_config: Any,
    verdict_spec: Any,
    counterfactual_module: Any = None,
    evaluator_hash: str | None = None,
    sandbox_profile: Any = None,
    builder_identity: Any = None,
    duration_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """逐项验证密封承诺 v6;任一不匹配抛 SealedExamError(EXAM_INVALID)。

    返回绑定报告(用于证据 artifacts);不提供任何"忽略哈希"通道。

    阶段 2.6.0f 工作包 A/B/C(必填,缺失即 fail closed):
    - builder_identity:评估方 Builder Identity Provider 派生的实际
      身份(与 run_sealed_exam 使用同一个 Provider);承诺的 npb- 必须
      与其一致——不存在默认 mock builder fallback;
    - duration_contract:从 pack 全部 required strict Null Episode 派生
      的全局唯一时长合同;承诺绑定的 ndc- 与本合同对账,qualification
      spec / power 重跑全部使用本合同的 resolved bars 构建(不再取
      第一个/最后一个 null_control Episode,无 96 回退)。
    """
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        require_builder_identity,
    )
    from rl_curriculum.charter import charter_hash as compute_charter_hash
    from rl_curriculum.evaluator import evaluator_code_hash
    from rl_curriculum.generator_binding import verify_generator_bindings
    from rl_curriculum.null_duration_contract import (
        NullDurationContractError,
        null_duration_contract_hash as _ndc_hash,
    )
    from rl_curriculum.null_qualification import (
        qualification_code_hash,
        verify_null_qualification_bindings,
    )
    from rl_curriculum.param_resolution import (
        resolved_parameter_semantics_hash,
    )
    from rl_platform.versions import spec_versions as frozen_spec_versions

    if counterfactual_module is None:
        import rl_curriculum.counterfactual as counterfactual_module  # noqa: F811
    if evaluator_hash is None:
        evaluator_hash = evaluator_code_hash()
    try:
        identity = require_builder_identity(
            builder_identity, where="verify_sealed_commitment")
    except BuilderIdentityError as exc:
        raise SealedExamError(
            f"verify_sealed_commitment 缺少有效的 Builder Identity:"
            f"{exc}(EXAM_INVALID;不存在默认 mock builder fallback)") from exc
    if not isinstance(duration_contract, dict) or not duration_contract:
        raise SealedExamError(
            "verify_sealed_commitment 缺少全局 strict Null duration "
            "contract:正式路径必须传入从全部 required Null Episode "
            "派生的唯一合同(null-duration-contract-v1);不存在取第一"
            "个/最后一个 Episode 或默认 96 bars 的回退(EXAM_INVALID)")

    problems: list[str] = []
    checks: dict[str, bool] = {}

    def check(name: str, ok: bool, message: str) -> None:
        checks[name] = bool(ok)
        if not ok:
            problems.append(message)

    # 1. pack hash(含 timeframe 与 resolved durations)
    check("pack_hash", pack.pack_hash() == commitment.pack_hash,
          f"pack hash 不匹配:实际 {pack.pack_hash()} 承诺 "
          f"{commitment.pack_hash}(考试包被替换或内容变化)")

    # 2. charter hash
    actual_charter = compute_charter_hash(charter)
    check("charter_hash", actual_charter == commitment.charter_hash,
          f"charter hash 不匹配:实际 {actual_charter} 承诺 "
          f"{commitment.charter_hash}")

    # 3. observation schema hash
    actual_schema = schema.schema_hash()
    check("observation_schema_hash",
          actual_schema == commitment.observation_schema_hash,
          f"observation schema hash 不匹配:实际 {actual_schema} 承诺 "
          f"{commitment.observation_schema_hash}")

    # 4. RouteC 规范版本(全部)
    actual_versions = frozen_spec_versions()
    check("spec_versions", actual_versions == commitment.spec_versions,
          f"spec versions 不匹配:实际 {actual_versions} 承诺 "
          f"{commitment.spec_versions}")

    # 5. 生成器绑定(F:逐族真实实现指纹,不再是共享模块哈希)
    pack_families = sorted({e.family for e in pack.episodes})
    gen_report = verify_generator_bindings(
        registry, commitment.generator_bindings,
        required_families=pack_families)
    for name, ok in gen_report["checks"].items():
        checks[name] = ok
    problems.extend(gen_report["problems"])

    # 6. evaluator / counterfactual 代码哈希
    check("evaluator_code_hash", evaluator_hash == commitment.evaluator_code_hash,
          f"evaluator 代码哈希不匹配:实际 {evaluator_hash} 承诺 "
          f"{commitment.evaluator_code_hash}(评估器实现被替换)")
    actual_cf = module_code_hash(counterfactual_module)
    check("counterfactual_code_hash",
          actual_cf == commitment.counterfactual_code_hash,
          f"counterfactual 代码哈希不匹配:实际 {actual_cf} 承诺 "
          f"{commitment.counterfactual_code_hash}")

    # 7. verdict 判定器哈希(含 nuisance 等价/复制门槛)
    actual_verdict = verdict_spec.verdict_spec_hash()
    check("verdict_spec_hash", actual_verdict == commitment.verdict_spec_hash,
          f"判定器哈希不匹配:实际 {actual_verdict} 承诺 "
          f"{commitment.verdict_spec_hash}(及格规则/等价区间/复制门槛被替换)")

    # 8. EvalConfig(完整)
    check("eval_config", eval_config.manifest() == commitment.eval_config,
          f"EvalConfig 不匹配:实际 {eval_config.manifest()} 承诺 "
          f"{commitment.eval_config}(fee/滑点/初始资金/窗口/确定性)")

    # 9. sandbox profile 哈希(C/I:沙箱配置变化 = 新考试)
    if sandbox_profile is not None:
        actual_profile = sandbox_profile.profile_hash()
        check("sandbox_profile_hash",
              actual_profile == commitment.sandbox_profile_hash,
              f"sandbox profile 哈希不匹配:实际 {actual_profile} 承诺 "
              f"{commitment.sandbox_profile_hash}(沙箱配置被替换;"
              f"必须创建新承诺)")
    else:
        check("sandbox_profile_hash", False,
              "正式考试必须提供 sandbox profile(系统级沙箱强制;"
              "任何请求正式考试但未启用沙箱的行为直接 EXAM_INVALID)")

    # 10. nuisance 等价 spec(D4:判定器内嵌,双保险逐字段比对)
    ne = verdict_spec.nuisance_equivalence.canonical_payload()
    check("nuisance_equivalence_spec",
          ne == commitment.nuisance_equivalence_spec,
          "nuisance 双边等价 spec 与承诺不一致(等价区间/容差被改写)")

    # 11. 反作弊复制门槛(E:判定器内嵌,双保险;C:含 seed 聚合规则)
    ar = {
        "min_distinct_cheat_seeds": verdict_spec.min_distinct_cheat_seeds,
        "min_failing_cheat_episodes": verdict_spec.min_failing_cheat_episodes,
        "min_effective_net_return": verdict_spec.min_effective_net_return,
        "min_seed_pass_ratio_for_cheat":
            verdict_spec.min_seed_pass_ratio_for_cheat,
        "seed_aggregation": verdict_spec.seed_aggregation,
    }
    check("anticheat_replication_spec",
          ar == commitment.anticheat_replication_spec,
          "反作弊复制门槛/seed 聚合规则与承诺不一致(多 seed 标准被改写)")

    # 12. 严格 Null 资格绑定(2.6.0d:spec/power 双重绑定 + 重读真实
    #     报告逐项对账;margin 只来自 qualification spec;
    #     2.6.0f 工作包 C:spec 构建使用全局 duration contract 的
    #     resolved bars——不再取第一个 null_control Episode,无 96 回退)
    from rl_curriculum.null_qualification_spec import (
        build_spec_payload as _build_nq_spec,
        null_qualification_spec_hash as _nq_spec_hash,
        verify_spec_payload as _verify_nq_spec,
    )

    # 12a. 全局 duration contract 对账(承诺 ndc- == 执行器从 pack 全部
    #      required strict Null Episode 派生的唯一合同;公开 duration
    #      与 timeframe 不属于隐藏 seed)
    try:
        actual_ndc = _ndc_hash(duration_contract)
        ndc_ok = actual_ndc == commitment.null_duration_contract_hash
        ndc_problem = ""
    except NullDurationContractError as exc:
        actual_ndc, ndc_ok, ndc_problem = "", False, str(exc)
    check("null_duration_contract_hash", ndc_ok,
          f"全局 strict Null duration contract 不匹配:实际 {actual_ndc} "
          f"vs 承诺 {commitment.null_duration_contract_hash}"
          f"{(' / ' + ndc_problem) if ndc_problem else ''}"
          f"(所有 required strict Null family 的 resolved duration 必须"
          f"唯一并与承诺一致;EXAM_INVALID,不判候选 FAIL/作弊)")

    episode_bars = int(duration_contract["resolved_bars"])
    nq_spec = _build_nq_spec(
        eval_config, timeframe=duration_contract["timeframe"],
        episode_bars=episode_bars)
    spec_problems = _verify_nq_spec(nq_spec)
    if spec_problems:
        problems.extend(f"qualification spec 自洽失败: {spec_problems}")
    check("null_qualification_spec_hash",
          _nq_spec_hash(nq_spec) == commitment.null_qualification_spec_hash,
          "Null 资格规范哈希不匹配:margin/统计协议/聚合规则/功效目标/"
          "seed namespace 与承诺不一致(经济 margin 被改写)")
    null_report = verify_null_qualification_bindings(
        commitment.null_qualification_bindings,
        required_families=list(verdict_spec.required_null_families),
        generator_bindings=commitment.generator_bindings,
        observation_schema_hash=commitment.observation_schema_hash,
        eval_config_manifest=commitment.eval_config,
        timeframe=duration_contract["timeframe"],
        qualification_spec_hash=commitment.null_qualification_spec_hash,
        power_analysis_ref=str(
            commitment.null_power_analysis.get("report_hash") or ""))
    for name, ok in null_report["checks"].items():
        checks[name] = ok
    problems.extend(null_report["problems"])
    actual_nqc = qualification_code_hash()
    check("null_qualification_code_hash",
          actual_nqc == commitment.null_qualification_code_hash,
          f"Null 资格审查代码哈希不匹配:实际 {actual_nqc} 承诺 "
          f"{commitment.null_qualification_code_hash}(资格审查实现被替换)")

    # 12b. pack 构建算法 manifest 与 pack-level validity 绑定(阶段
    #      2.6.0f 工作包 A/B:npb- 必须与评估方 Builder Identity Provider
    #      派生的实际身份一致——package tree + 外部依赖闭包;不再无参数
    #      调用默认公开 mock builder hash;此对账先于昂贵的 power 重跑)
    check("pack_builder_code_hash",
          commitment.pack_builder_code_hash == identity.manifest_hash,
          f"pack 构建算法 manifest 哈希不匹配:承诺 "
          f"{commitment.pack_builder_code_hash} vs Provider 实际 "
          f"{identity.manifest_hash}(builder package tree/外部依赖/"
          f"assemble/attempt 选择链任一变化都必须创建新承诺;"
          f"承诺的 builder 与评估方实际 Provider 不一致 -> EXAM_INVALID)")
    pv = commitment.pack_validity
    pv_ok = (
        str(pv.get("pack_hash") or "") == commitment.pack_hash
        and str(pv.get("report_hash") or "").startswith("npv-")
        and (pv.get("public_summary") or {}).get("verdict")
        == "PACK_VALID")
    check("pack_validity_binding", pv_ok,
          "pack-level validity 绑定无效:pack_hash 与承诺不一致/缺 "
          "npv- 报告哈希/verdict 非 PACK_VALID(实际 pack 未通过 "
          "pack-level 验证的考试不得开始;执行器将现算并逐字段对账)")

    # 12d. builder 冻结构建请求绑定(阶段 2.6.0g P1:承诺的 nbr- 必须
    #      与评估方从 identity+pack+duration contract 重新派生的请求
    #      一致,请求不得含任何候选字段;builder 实际执行的产物来源
    #      证明由 formal D1 步骤 4b 在候选加载前完成——本检查是重放
    #      输入的静态对账,先于 power 重跑)。mock 通道的请求携带
    #      pack 规范重放载荷(mock builder 是公开组装器):重算时跟随
    #      承诺的载荷标志,载荷内容从 pack 现算——注入与 pack 不符的
    #      载荷会因 nbr 对账失败被拒;私有通道携带载荷由 4b 的闸拒绝。
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        build_frozen_build_request,
        frozen_build_request_hash as _nbr_recompute,
    )

    include_payload = "mock_pack_payload" in (
        commitment.builder_build_request or {})
    try:
        recomputed_request = build_frozen_build_request(
            identity, pack=pack, duration_contract=duration_contract,
            include_mock_pack_payload=include_payload)
        recomputed_request_hash = _nbr_recompute(recomputed_request)
    except BuilderProvenanceError as exc:
        check("builder_build_request_hash", False,
              f"冻结构建请求派生失败: {exc}")
        recomputed_request_hash = ""
    req_ok = (
        str(commitment.builder_build_request_hash).startswith("nbr-")
        and commitment.builder_build_request_hash == recomputed_request_hash)
    check("builder_build_request_hash", req_ok,
          f"builder 冻结构建请求哈希不匹配:承诺 "
          f"{commitment.builder_build_request_hash} vs Provider 重新派生 "
          f"{recomputed_request_hash}(builder 重放的冻结输入被替换或"
          f"承诺未绑定本 builder 的构建请求;产物来源证明的前提不成立"
          f" -> EXAM_INVALID;阶段 2.6.0g P1)")

    # 12c. 完整 power report 重跑验证(阶段 2.6.0e 工作包 C:public
    #      summary 不再是信任源——执行器用当前代码确定性重跑完整
    #      power analysis,重算 npa- 哈希并对账,重派生 targets_met,
    #      核验场景清单/MC 配置/比例置信界;候选 checkpoint 加载前;
    #      2.6.0f:episode_bars 来自全局 duration contract)
    from rl_curriculum.null_power_reverification import (
        reverify_committed_power_analysis,
    )

    power_reverify = reverify_committed_power_analysis(
        commitment=commitment,
        eval_config=eval_config,
        timeframe=duration_contract["timeframe"],
        episode_bars=episode_bars,
        required_families=list(verdict_spec.required_null_families),
    )
    for name, ok in power_reverify["checks"].items():
        checks[f"power::{name}"] = bool(ok)
    problems.extend(power_reverify["problems"])

    # 13. 受信训练签发方(A:承诺 issuer payload 自洽校验——正式信任根
    #     唯一来源是承诺本身,任何字段不自洽直接 EXAM_INVALID)
    from rl_curriculum.attestation import (
        AttestationError,
        verify_issuer_payload_self_consistency,
    )

    try:
        verify_issuer_payload_self_consistency(
            commitment.trusted_issuer)
        checks["trusted_issuer_self_consistent"] = True
    except AttestationError as exc:
        checks["trusted_issuer_self_consistent"] = False
        problems.append(
            f"承诺 trusted_issuer 自洽校验失败(公钥指纹/协议/runner "
            f"hash/smoke 策略任一不自洽 -> EXAM_INVALID): {exc}")

    # 13b. 候选运行时内容绑定(B:实际执行的 rl_candidate_runtime
    #      逐文件哈希;runtime 代码变化 = 旧承诺失效)
    from rl_curriculum.sandbox import (
        compute_runtime_manifest,
        runtime_tree_hash,
    )

    try:
        actual_rt = compute_runtime_manifest()
        rt_match = actual_rt == commitment.candidate_runtime_manifest
    except Exception as exc:  # noqa: BLE001 - 扫描失败同样 fail closed
        actual_rt = None
        rt_match = False
        problems.append(f"候选运行时 manifest 计算失败: {exc!r}")
    check("candidate_runtime_manifest", rt_match,
          "候选运行时 manifest 不匹配:实际执行的 rl_candidate_runtime "
          "文件内容/集合/协议版本与承诺不一致(bootstrap/worker/guard/"
          "versions 任一变化或文件增删都必须创建新承诺)")
    check("candidate_runtime_hash",
          runtime_tree_hash(commitment.candidate_runtime_manifest)
          == commitment.candidate_runtime_hash,
          "候选运行时 tree hash 与 manifest 不一致(承诺字段被改写)")

    # 14. resolved parameter semantics(A:真实时间解析语义)
    actual_rps = resolved_parameter_semantics_hash()
    check("resolved_parameter_semantics_hash",
          actual_rps == commitment.resolved_parameter_semantics_hash,
          f"真实时间参数解析语义哈希不匹配:实际 {actual_rps} 承诺 "
          f"{commitment.resolved_parameter_semantics_hash}"
          f"(时间字段->bars 绑定被改写)")

    report = {
        "commitment_hash": commitment.commitment_hash(),
        "checks": checks,
        "problems": problems,
        "pack_families": pack_families,
        "pass": not problems,
    }
    if problems:
        raise SealedExamError(
            "密封承诺校验失败(EXAM_INVALID): " + "; ".join(problems))
    return report


def verify_checkpoint_requirements(
    commitment: SealedExamCommitment, manifest: dict[str, Any],
    *,
    checkpoint_sha256: str,
    attestation_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """工作包 F/G:checkpoint 正式资格(受信 attestation 驱动)。

    - sidecar 自行声明的 formal_eligible boolean 被忽略;
    - 必须提供通过 verify_attestation 的报告(attestation_report);
    - 章程/observation/SHA 与承诺要求比对。
    """
    req = commitment.checkpoint_requirements
    problems: list[str] = []
    checks: dict[str, bool] = {}

    checks["require_trusted_attestation"] = bool(
        req.get("require_trusted_attestation", True))
    if not checks["require_trusted_attestation"]:
        problems.append("承诺未要求受信 attestation(v2 承诺必须要求)")

    if attestation_report is None or not attestation_report.get("pass"):
        checks["trusted_attestation"] = False
        problems.append(
            "缺少通过验证的受信 training attestation:正式资格唯一来源"
            "是受信签发方签名(sidecar 自声明 formal_eligible 无效)")
    else:
        checks["trusted_attestation"] = True

    if manifest.get("legacy_engineering_evidence"):
        problems.append("checkpoint 是 legacy 工程证据,正式考试拒绝")

    checks["charter_binding"] = \
        manifest.get("charter_hash") == req.get("charter_hash")
    if not checks["charter_binding"]:
        problems.append(
            f"checkpoint charter hash {manifest.get('charter_hash')!r} 与承诺 "
            f"要求 {req.get('charter_hash')!r} 不符(checkpoint 不属于该课程)")

    checks["observation_binding"] = \
        manifest.get("observation_schema_hash") == req.get(
            "observation_schema_hash")
    if not checks["observation_binding"]:
        problems.append(
            f"checkpoint observation schema hash "
            f"{manifest.get('observation_schema_hash')!r} 与承诺要求 "
            f"{req.get('observation_schema_hash')!r} 不符")

    expected_sha = req.get("checkpoint_sha256")
    checks["checkpoint_sha256"] = (
        expected_sha in (None, "any-attested", "any-formal-eligible")
        or expected_sha == checkpoint_sha256)
    if not checks["checkpoint_sha256"]:
        problems.append(
            f"checkpoint SHA-256 不匹配:承诺指定 {expected_sha!r},"
            f"实际 {checkpoint_sha256}")

    report = {
        "checks": checks, "problems": problems,
        "pass": not problems,
    }
    if problems:
        raise SealedExamError(
            "checkpoint 不满足密封承诺的正式资格要求(EXAM_INVALID): "
            + "; ".join(problems))
    return report
