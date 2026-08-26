"""阶段 2.6.0a 工作包 E/M + 阶段 2.6.0b 工作包 F/G/H/I:密封考试承诺 v2。

sealed-exam-commitment-v2(阶段 2.6.0b)在 v1 基础上新增绑定:
- 每个生成器族的真实实现指纹(implementation hash,来自实际实现模块/
  类源码/MRO 基类/依赖/资源——不再是共享 generators.py 哈希,F);
- sandbox profile 哈希(系统级沙箱配置,profile 变化 = 新考试,C/I);
- nuisance 双边等价 spec(等价区间/动作一致率/容差预注册,D4);
- 反作弊复制门槛(逐原因最小不同 seed 数/失败 Episode 数,E);
- 严格 Null 资格绑定(逐族 family_version/qualification_pass/report
  hash + 资格审查代码哈希,H4);
- 受信训练签发方(issuer 公钥/指纹/必需 training runner hash/smoke
  策略,attestation 协议版本,G6);
- resolved parameter semantics 哈希(真实时间字段 -> bars 解析语义,A);
- checkpoint 要求改为 attestation 驱动(sidecar 自声明 formal_eligible
  无效,G1)。

v1 承诺(阶段 2.6.0a)不得被 v2 执行器接受:from_json 显式报出
协议版本不兼容(工作包 I:旧 commitment 不得被新执行器自动接受)。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

SEALED_EXAM_PROTOCOL = "sealed-exam-commitment-v2"
_DEPRECATED_PROTOCOLS = ("sealed-exam-commitment-v1",)


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
    #: nuisance 双边等价 spec(canonical payload;工作包 D4)
    nuisance_equivalence_spec: dict[str, Any] = field(default_factory=dict)
    #: 反作弊复制门槛(工作包 E)
    anticheat_replication_spec: dict[str, Any] = field(default_factory=dict)
    #: 严格 Null 资格绑定(工作包 H4)
    null_qualification_bindings: dict[str, dict[str, Any]] = field(
        default_factory=dict)
    null_qualification_code_hash: str = ""
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
            "nuisance_equivalence_spec": self.nuisance_equivalence_spec,
            "anticheat_replication_spec": self.anticheat_replication_spec,
            "null_qualification_bindings": self.null_qualification_bindings,
            "null_qualification_code_hash": self.null_qualification_code_hash,
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
                    f"sealed manifest 协议版本 {data.get('protocol_version')!r}"
                    f" 已弃用(阶段 2.6.0a 及之前):v1 承诺缺少系统级沙箱/"
                    f"attestation/严格 Null/复制门槛绑定,不得被 v2 执行器"
                    f"自动接受;必须以 {SEALED_EXAM_PROTOCOL!r} 重新创建承诺"
                    f"(版本不兼容,工作包 I)")
            raise SealedExamError(
                f"sealed manifest 协议版本 {data.get('protocol_version')!r} "
                f"!= {SEALED_EXAM_PROTOCOL!r}")
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
            nuisance_equivalence_spec=dict(
                data.get("nuisance_equivalence_spec") or {}),
            anticheat_replication_spec=dict(
                data.get("anticheat_replication_spec") or {}),
            null_qualification_bindings=dict(
                data.get("null_qualification_bindings") or {}),
            null_qualification_code_hash=data.get(
                "null_qualification_code_hash", ""),
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
) -> dict[str, Any]:
    """逐项验证密封承诺 v2;任一不匹配抛 SealedExamError(EXAM_INVALID)。

    返回绑定报告(用于证据 artifacts);不提供任何"忽略哈希"通道。
    """
    from rl_curriculum.charter import charter_hash as compute_charter_hash
    from rl_curriculum.evaluator import evaluator_code_hash
    from rl_curriculum.generator_binding import verify_generator_bindings
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

    # 11. 反作弊复制门槛(E:判定器内嵌,双保险)
    ar = {
        "min_distinct_cheat_seeds": verdict_spec.min_distinct_cheat_seeds,
        "min_failing_cheat_episodes": verdict_spec.min_failing_cheat_episodes,
        "min_effective_net_return": verdict_spec.min_effective_net_return,
        "min_seed_pass_ratio_for_cheat":
            verdict_spec.min_seed_pass_ratio_for_cheat,
    }
    check("anticheat_replication_spec",
          ar == commitment.anticheat_replication_spec,
          "反作弊复制门槛与承诺不一致(多 seed 标准被改写)")

    # 12. 严格 Null 资格绑定(H4)
    null_report = verify_null_qualification_bindings(
        commitment.null_qualification_bindings,
        required_families=list(verdict_spec.required_null_families))
    for name, ok in null_report["checks"].items():
        checks[name] = ok
    problems.extend(null_report["problems"])
    actual_nqc = qualification_code_hash()
    check("null_qualification_code_hash",
          actual_nqc == commitment.null_qualification_code_hash,
          f"Null 资格审查代码哈希不匹配:实际 {actual_nqc} 承诺 "
          f"{commitment.null_qualification_code_hash}(资格审查实现被替换)")

    # 13. 受信训练签发方(G6:issuer 公钥/runner hash/smoke 策略)
    if not commitment.trusted_issuer.get("key_fingerprint"):
        problems.append("承诺缺少受信训练签发方(trusted_issuer)配置:"
                        "正式考试必须绑定 issuer 公钥指纹与训练 runner hash")
        checks["trusted_issuer_bound"] = False
    else:
        checks["trusted_issuer_bound"] = True

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
