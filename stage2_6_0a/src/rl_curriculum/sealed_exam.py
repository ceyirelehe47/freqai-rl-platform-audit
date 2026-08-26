"""阶段 2.6.0a 工作包 E/M:密封考试承诺(sealed exam commitment)。

阶段 2.6.0 的隐藏考试只"计算当前文件的哈希",没有任何预承诺:
考试包可以在评估前被替换,评估条件可以由命令行临时改写,评估代码/
判定规则可以静默变化。本模块建立独立评估方的预先承诺:

正式 hidden exam 开始前,评估方创建 SealedExamCommitment,绑定:
- expected exam pack hash(含 timeframe 与 resolved durations);
- course charter hash;
- observation schema hash;
- RouteC 规范版本(全部六项);
- generator family version + generator 代码哈希(逐族);
- evaluator 代码哈希(rl_curriculum 包内容哈希);
- counterfactual 代码哈希;
- verdict 判定器哈希;
- 完整 EvalConfig(哈希);
- checkpoint 要求(formal_eligible / charter / observation schema /
  可选指定 checkpoint SHA-256);
- 考试协议版本、创建时间、attempt policy。

正式隐藏 CLI 必须要求 --sealed-manifest 并逐项验证;任一不匹配返回
EXAM_INVALID;不存在"忽略哈希"或"强制继续"的正式参数。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

SEALED_EXAM_PROTOCOL = "sealed-exam-commitment-v1"


class SealedExamError(RuntimeError):
    """密封承诺校验失败(fail closed -> EXAM_INVALID)。"""


def module_code_hash(module: Any) -> str:
    """模块源文件内容哈希(代码身份;实现变化 -> 新哈希)。"""
    src = Path(module.__file__)
    return "m-" + hashlib.sha256(src.read_bytes()).hexdigest()


def generator_bindings(registry: dict[str, Any]) -> dict[str, dict[str, str]]:
    """注册表中每个生成器族的 {family_version, code_hash} 绑定。"""
    import rl_curriculum.generators as generators_module

    bindings: dict[str, dict[str, str]] = {}
    for family, gen in sorted(registry.items()):
        bindings[family] = {
            "family_version": gen.family_version,
            "code_hash": module_code_hash(generators_module),
        }
    return bindings


@dataclass
class SealedExamCommitment:
    """密封考试承诺(独立评估方在考试开始前创建并公布哈希)。"""

    pack_hash: str
    charter_hash: str
    observation_schema_hash: str
    spec_versions: dict[str, str]
    generator_bindings: dict[str, dict[str, str]]
    evaluator_code_hash: str
    counterfactual_code_hash: str
    verdict_spec_hash: str
    eval_config: dict[str, Any]
    checkpoint_requirements: dict[str, Any] = field(default_factory=dict)
    attempt_policy: dict[str, Any] = field(default_factory=lambda: {
        "idempotent_retry": True,
        "max_attempts_per_checkpoint_pack": None,
    })
    created_utc: str = ""
    notes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        req = {
            "formal_eligible": True,
            "charter_hash": self.charter_hash,
            "observation_schema_hash": self.observation_schema_hash,
            "checkpoint_sha256": "any-formal-eligible",
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
) -> dict[str, Any]:
    """逐项验证密封承诺;任一不匹配抛 SealedExamError(EXAM_INVALID)。

    返回绑定报告(用于证据 artifacts);不提供任何"忽略哈希"通道。
    """
    from rl_curriculum.charter import charter_hash as compute_charter_hash
    from rl_curriculum.evaluator import evaluator_code_hash
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

    # 1. pack hash(含 timeframe 与 resolved durations 的规范化内容)
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
          f"{commitment.observation_schema_hash}(特征顺序/维度/窗口/dtype/"
          f"归一化/槽位任一变化)")

    # 4. RouteC 规范版本(全部)
    actual_versions = frozen_spec_versions()
    check("spec_versions", actual_versions == commitment.spec_versions,
          f"spec versions 不匹配:实际 {actual_versions} 承诺 "
          f"{commitment.spec_versions}")

    # 5. generator 绑定:考试包引用的每个族,注册实现的版本与代码哈希
    pack_families = sorted({e.family for e in pack.episodes})
    for family in pack_families:
        bound = commitment.generator_bindings.get(family)
        if bound is None:
            check(f"generator_bound::{family}", False,
                  f"承诺未绑定考试包引用的生成器族 {family!r}")
            continue
        gen = registry.get(family)
        if gen is None:
            check(f"generator_registered::{family}", False,
                  f"注册表缺少生成器族 {family!r}(内容缺失)")
            continue
        check(f"generator_version::{family}",
              gen.family_version == bound["family_version"],
              f"生成器族 {family} 版本不匹配:实际 {gen.family_version} "
              f"承诺 {bound['family_version']}")
        actual_code = module_code_hash(
            __import__("rl_curriculum.generators", fromlist=["x"]))
        check(f"generator_code::{family}",
              actual_code == bound["code_hash"],
              f"生成器代码哈希不匹配(族 {family}):实现被替换;"
              f"任何实现变化都需要新考试包或新承诺")

    # 6. evaluator 代码哈希
    check("evaluator_code_hash", evaluator_hash == commitment.evaluator_code_hash,
          f"evaluator 代码哈希不匹配:实际 {evaluator_hash} 承诺 "
          f"{commitment.evaluator_code_hash}(评估器实现被替换)")

    # 7. counterfactual 代码哈希
    actual_cf = module_code_hash(counterfactual_module)
    check("counterfactual_code_hash",
          actual_cf == commitment.counterfactual_code_hash,
          f"counterfactual 代码哈希不匹配:实际 {actual_cf} 承诺 "
          f"{commitment.counterfactual_code_hash}")

    # 8. verdict 判定器哈希
    actual_verdict = verdict_spec.verdict_spec_hash()
    check("verdict_spec_hash", actual_verdict == commitment.verdict_spec_hash,
          f"判定器哈希不匹配:实际 {actual_verdict} 承诺 "
          f"{commitment.verdict_spec_hash}(及格规则被替换)")

    # 9. EvalConfig(完整)
    check("eval_config", eval_config.manifest() == commitment.eval_config,
          f"EvalConfig 不匹配:实际 {eval_config.manifest()} 承诺 "
          f"{commitment.eval_config}(fee/滑点/初始资金/窗口/确定性)")

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
    *, checkpoint_sha256: str,
) -> dict[str, Any]:
    """工作包 F:checkpoint 正式资格与承诺要求逐项比对。"""
    req = commitment.checkpoint_requirements
    problems: list[str] = []
    checks: dict[str, bool] = {}

    checks["formal_eligible"] = bool(manifest.get("formal_eligible"))
    if not manifest.get("formal_eligible"):
        problems.append(
            "checkpoint formal_eligible != true(legacy/smoke checkpoint "
            "不得参加正式隐藏考试)")
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
        expected_sha in (None, "any-formal-eligible")
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
