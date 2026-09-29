"""阶段 2.6.2 Engineering Bridge:新版资格输入统一锁(qualified input)。

把"新版资格输入身份"变成训练消费侧(bank/env/训练/冷读)的唯一参数与
预处理来源。一个合格输入目录必须同时提供并逐一核验:

1. 资格计划 qualification_plan.json + digest 文件(digest 重算一致);
2. 资格结果 qualification_result.json:绑定同一 plan digest、verdict=PASS、
   与计划同一 source iteration("一个 PASS 字符串"不是资格证明);
3. 一次性 exposure 终态 qualification_exposure.json:绑定同一 plan digest、
   status=completed(terminal,一次性语义);
4. 参数 pack parameter_pack.json:三族 rung_params + reference_thresholds
   的唯一来源,digest 重算并与 plan.parameter_pack.digest 绑定一致;
5. V2 preprocessing bundle preprocessor_envelope.json:复用 2.6.1
   RouteCPreprocessorV2 envelope(自带三层哈希篡改检测),bundle hash 与
   plan.preprocessor_bundle_hash 绑定一致;
6. 资格生产代码身份 Cq(plan.code_identity)与当前训练消费代码身份 Ct 的
   共同执行语义核验:production observation identity、generator family
   versions、vendor pin、V2 预处理合同摘要。Cq 与 Ct 允许不同 commit,
   但共同执行语义漂移必须显式拒绝(不允许宽泛白名单整体豁免);
7. 显式训练授权锚 authorization:绑定 {plan digest, pack digest, bundle
   hash} + profile + scope。授权文件不得位于资格目录内部(自授权拒绝);
   输入文件自行重新哈希不能自授正式训练权限。

任何缺失/错配/旧 R2 冒充/工程件冒充正式/非 PASS/未授权身份漂移,在 bank
真实生成与 optimizer update 之前拒绝(结构化 problems + 边界拒绝计数),
不自动重签、不自动补锚、不回落 R2、不回落源码默认参数。

校验与消费的一致性:load_qualified_input 把全部已验证内容读入内存快照
(QualifiedInput);bank/env/训练/冷读只消费该快照,不再按路径重读。冷读/
新进程路径在消费前用同一公共实现重新完整校验。旧 R2 路径
(_locked_plan / R2_EXPECTED_PLAN_DIGEST / 黄金派生)完全不变。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

#: 工程桥接迭代身份(区别于 official s262_r0)
PPO262E_ITERATION_ID = "s262e_r1"
#: 合格输入 plan 格式
QUALIFICATION_PLAN_FORMAT = "ppo262e-qualification-plan-v1"
#: 资格结果格式
QUALIFICATION_RESULT_FORMAT = "ppo262e-qualification-result-v1"
#: exposure 格式
QUALIFICATION_EXPOSURE_FORMAT = "ppo262e-qualification-exposure-v1"
#: 参数 pack 格式
PARAMETER_PACK_FORMAT = "ppo262e-parameter-pack-v1"
#: 授权锚格式
AUTHORIZATION_FORMAT = "ppo262e-training-authorization-v1"

#: 资格目录内的必需文件(名字是装载合同;身份由 digest 决定,不由路径决定)
QUALIFICATION_PLAN_FILENAME = "qualification_plan.json"
QUALIFICATION_PLAN_DIGEST_FILENAME = "qualification_plan_digest.txt"
QUALIFICATION_RESULT_FILENAME = "qualification_result.json"

QUALIFICATION_EXPOSURE_FILENAME = "qualification_exposure.json"
PARAMETER_PACK_FILENAME = "parameter_pack.json"
PREPROCESSOR_ENVELOPE_FILENAME = "preprocessor_envelope.json"

#: 授权 scope 语义:engineering 只能解锁工程 profile;formal 是未来正式
#: 资格链的位(本轮不存在 formal 授权,凡请求 formal 一律拒绝)
QUALIFICATION_SCOPES = ("engineering", "formal")

#: 正式授权锚注册表:file basename -> 期望 sha256。formal scope 的装载
#: 额外要求授权锚携带与注册表匹配的 admission_anchor(文件存在于部署
#: 树 canonical 路径且字节一致)。本轮注册表为空——正式资格/正式
#: admission 链尚未实现,任何 formal 请求(含手工伪造的 formal 授权
#: JSON)在此一律拒绝;未来正式链落地时以代码变更显式登记。
FORMAL_ADMISSION_REGISTRY: dict[str, str] = {}
_FORMAL_ADMISSION_DIR = Path(__file__).resolve().parents[2] / "artifacts"

#: 授权绑定的三摘要键(顺序进授权摘要)
_AUTH_BINDING_KEYS = (
    "qualification_plan_digest",
    "parameter_pack_digest",
    "preprocessor_bundle_hash",
)


class QualifiedInputError(RuntimeError):
    """合格输入校验失败(fail closed;携带结构化报告)。"""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        problems = report.get("problems") or ["unknown"]
        super().__init__(
            "qualified input 拒绝: " + "; ".join(problems[:6]))


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def qualification_plan_digest(plan: dict[str, Any]) -> str:
    """工程资格 plan digest(与内容绑定,与文件名/路径无关)。"""
    return "qp262e-" + _sha(_canonical(plan))


def parameter_pack_digest(pack: dict[str, Any]) -> str:
    """参数 pack digest(排除 digest/created_utc 自身字段)。"""
    payload = {k: v for k, v in pack.items()
               if k not in ("digest", "created_utc")}
    return "e262pk-" + _sha(_canonical(payload))


def authorization_binding_digest(bindings: dict[str, Any]) -> str:
    """授权锚绑定摘要(三摘要 + profile + scope 的联合哈希)。"""
    payload = {k: bindings[k] for k in _AUTH_BINDING_KEYS}
    payload["profile"] = bindings["profile"]
    payload["scope"] = bindings["scope"]
    return "e262az-" + _sha(_canonical(payload))


# ---------------------------------------------------------------- Ct 侧身份
def consumer_common_contract_now() -> dict[str, Any]:
    """当前训练消费代码身份 Ct 的共同执行语义面(实时重算)。

    Cq(资格生产侧记录)与 Ct 不要求 commit 相等;下面每个字段都是两边
    必须逐字一致的共同执行语义——任何一项漂移都构成拒绝,不存在整体
    白名单豁免。
    """
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_identity,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.ppo262_input_lock import (
        PPO262_EXPECTED_VENDOR_SHA, vendor_status,
    )

    vs = vendor_status()
    return {
        "production_observation_identity": {
            k: v for k, v in production_observation_identity().items()
            if k in ("schema_hash", "feature_columns", "observation_dim",
                     "window_size", "strategy_file_sha256",
                     "feature_engineering_standard_sha256",
                     "env_core_version", "observation_spec_version")},
        "family_versions": {
            fam: spec.generator.family_version
            for fam, spec in family_specs().items()},
        "vendor_sha": vs["sha"],
        "vendor_clean": bool(vs["clean"]),
        "preprocessing_v2_contract_digest": (
            preprocessing_v2_contract_digest()),
        "expected_vendor_sha": PPO262_EXPECTED_VENDOR_SHA,
    }


_CONTRACT_KEYS = ("production_observation_identity", "family_versions",
                  "preprocessing_v2_contract_digest")


def _check_code_compatibility(plan: dict[str, Any],
                              checks: dict[str, bool],
                              problems: list[str]) -> dict[str, Any]:
    """Cq(plan.code_identity)vs Ct(现场重算)共同执行语义比对。"""
    cq = plan.get("code_identity") or {}
    ct = consumer_common_contract_now()
    # B2.1(反例 missing_producer_identity):资格生产者身份是来源证据
    # 的组成部分,缺 producer 的 plan 不装载;版本标签(如
    # family_version)不能替代生产者与共同执行语义证据
    producer = cq.get("producer") or {}
    checks["producer_identity_present"] = bool(
        producer.get("module") and (
            producer.get("module_sha256") or producer.get("sha256")))
    if not checks["producer_identity_present"]:
        problems.append(
            "plan.code_identity 缺 producer 身份(生产者模块+哈希;"
            "来源证据不完整)")
    drift: dict[str, dict[str, Any]] = {}
    for key in _CONTRACT_KEYS:
        cq_v, ct_v = cq.get(key), ct.get(key)
        if _canonical(cq_v) != _canonical(ct_v):
            drift[key] = {"cq": cq_v, "ct": ct_v}
    checks["code_common_contract_unchanged"] = not drift
    if drift:
        problems.append(
            f"资格生产代码身份 Cq 与当前消费身份 Ct 的共同执行语义漂移: "
            f"{sorted(drift)}")
    if ct.get("vendor_sha") != ct.get("expected_vendor_sha"):
        checks["vendor_pin_unchanged"] = False
        problems.append(
            f"vendor pin 漂移: {ct.get('vendor_sha')!r} != 期望 "
            f"{ct.get('expected_vendor_sha')!r}")
    else:
        checks["vendor_pin_unchanged"] = True
    if not ct.get("vendor_clean", False):
        problems.append("vendor 工作树不 clean")
    return ct


# ---------------------------------------------------------------- 快照对象
class QualifiedInput:
    """已验证的新版资格输入内存快照(消费侧唯一来源;不可变约定)。

    - rung_params()/reference_thresholds() 每次返回深拷贝(调用方改副本
      不污染快照);
    - preprocessor 是冻结的 RouteCPreprocessorV2(消费侧无 refit 入口);
    - identities() 进入训练/冷读 manifest 的绑定字段。
    """

    def __init__(self, *, plan: dict[str, Any], plan_digest: str,
                 pack: dict[str, Any], pack_digest: str,
                 preprocessor: Any, bundle_hash: str,
                 authorization: dict[str, Any], scope: str,
                 profile: str, contract_now: dict[str, Any],
                 report: dict[str, Any]):
        self._plan = plan
        self.plan_digest = plan_digest
        self._pack = pack
        self.pack_digest = pack_digest
        self.preprocessor = preprocessor
        self.bundle_hash = bundle_hash
        self.authorization = authorization
        self.scope = scope
        self.profile = profile
        self.contract_now = contract_now
        self.validation_report = report

    # ------------------------------------------------------------ 参数来源
    def rung_params(self) -> dict[str, dict[str, dict[str, Any]]]:
        out: dict[str, dict[str, dict[str, Any]]] = {}
        for fam, fp in self._pack["families"].items():
            out[fam] = json.loads(json.dumps(fp["rung_params"]))
        return out

    def reference_thresholds(self) -> dict[str, Any]:
        return json.loads(json.dumps({
            fam: fp["reference_thresholds"]
            for fam, fp in self._pack["families"].items()}))

    # ------------------------------------------------------------ 身份
    @property
    def source_iteration(self) -> str:
        return str(self._plan.get("source_iteration", ""))

    @property
    def plan_scope(self) -> str:
        return str(self._plan.get("scope", ""))

    def identities(self) -> dict[str, Any]:
        return {
            "iteration": PPO262E_ITERATION_ID,
            "qualification_plan_digest": self.plan_digest,
            "qualification_source_iteration": self.source_iteration,
            "qualification_scope": self.scope,
            "parameter_pack_digest": self.pack_digest,
            "preprocessor_bundle_hash": self.bundle_hash,
            "profile": self.profile,
            "authorization_binding_digest": (
                self.authorization.get("binding_digest")),
            "consumer_common_contract": {
                k: self.contract_now[k] for k in _CONTRACT_KEYS},
        }

    # ------------------------------------------------- 消费边界完整性重验
    def verify_integrity(self) -> None:
        """B2.2(反例 bank_cached_pack_mutation):消费边界重验已验证
        绑定——缓存对象在装载后被正常可达代码污染时,任何真实消费
        (bank 生成/env 训练/冷读/路由解析)之前拒绝。

        重验面:pack digest(含全部 rung_params/thresholds 字节)、
        authorization binding digest、V2 bundle hash、Ct 共同执行
        语义(family versions/vendor/V2 合同摘要,现场重算)。
        """
        problems: list[str] = []
        pack_now = parameter_pack_digest(self._pack)
        if pack_now != self.pack_digest:
            problems.append(
                f"pack 缓存完整性重验失败: 重算 {pack_now} != 已验证 "
                f"{self.pack_digest}(缓存被污染;消费拒绝)")
        auth = self.authorization or {}
        bindings = auth.get("bindings", {})
        expected_binding = authorization_binding_digest({
            **bindings, "profile": auth.get("profile"),
            "scope": auth.get("scope")})
        if auth.get("binding_digest") != expected_binding:
            problems.append("authorization 缓存完整性重验失败(binding "
                            "digest 重算不一致)")
        try:
            bundle_now = self.preprocessor.bundle_hash
        except Exception as exc:  # pragma: no cover - 防御性
            problems.append(f"bundle 重验异常: {exc}")
            bundle_now = None
        if bundle_now != self.bundle_hash:
            problems.append(
                f"bundle 缓存完整性重验失败: 重算 {bundle_now} != 已验证 "
                f"{self.bundle_hash}")
        ct_now = consumer_common_contract_now()
        for key in _CONTRACT_KEYS:
            if _canonical(ct_now.get(key)) != _canonical(
                    self.contract_now.get(key)):
                problems.append(f"共同执行语义漂移(消费时重算): {key}")
        if problems:
            raise QualifiedInputError({
                "format": "ppo262e-snapshot-integrity-reject-v1",
                "problems": problems,
                "checks": {},
                "rejected": True,
            })


# ---------------------------------------------------------------- profile
#: B1:进程级已验证 profile 输入上下文(官方消费入口的共享输入源)。
#: 缺省 None = 全部入口维持 R2 默认;上下文存在时,_locked_rung_params
#: 等共享解析器返回 pack 参数(并在每次解析前做 verify_integrity)。
_ACTIVE_PROFILE: dict[str, Any] = {}


class activated_profile_input:
    """上下文管理器:激活已验证 QualifiedInput 供真实消费入口共享。"""

    def __init__(self, qi: "QualifiedInput"):
        self._qi = qi

    def __enter__(self) -> "QualifiedInput":
        if not isinstance(self._qi, QualifiedInput):
            raise QualifiedInputError({
                "format": "ppo262e-profile-ctx-reject-v1",
                "problems": ["profile 上下文要求已验证的 QualifiedInput"],
            })
        _ACTIVE_PROFILE["qi"] = self._qi
        return self._qi

    def __exit__(self, *exc) -> None:
        _ACTIVE_PROFILE.pop("qi", None)


def active_profile_input() -> "QualifiedInput | None":
    qi = _ACTIVE_PROFILE.get("qi")
    return qi if isinstance(qi, QualifiedInput) else None


# ---------------------------------------------------------------- 装载
def load_qualified_input(
        qual_dir: Path | str, *, authorization_path: Path | str,
        expected_scope: str,
        expected_profile: str | None = None) -> QualifiedInput:
    """完整公共正路径校验;任何一项不成立即 QualifiedInputError。

    expected_scope="formal" 是正式消费入口的位:只有 formal 授权才能通过,
    而本轮不存在签发 formal 授权的资格链——工程件/工程授权在此一律拒绝
    (G01:工程许可不变正式许可)。
    """
    qual_dir = Path(qual_dir)
    authorization_path = Path(authorization_path)
    checks: dict[str, bool] = {}
    problems: list[str] = []

    def _reject() -> "QualifiedInputError":
        return QualifiedInputError({
            "format": "ppo262e-qualified-input-lock-v1",
            "qualification_dir": str(qual_dir),
            "authorization_path": str(authorization_path),
            "expected_scope": expected_scope,
            "checks": checks,
            "problems": problems,
            "rejected": True,
        })

    if expected_scope not in QUALIFICATION_SCOPES:
        raise ValueError(f"未知 scope {expected_scope!r}")

    # 0. 文件存在性 + 自授权拒绝
    required = {
        QUALIFICATION_PLAN_FILENAME: qual_dir / QUALIFICATION_PLAN_FILENAME,
        QUALIFICATION_PLAN_DIGEST_FILENAME: (
            qual_dir / QUALIFICATION_PLAN_DIGEST_FILENAME),
        QUALIFICATION_RESULT_FILENAME: (
            qual_dir / QUALIFICATION_RESULT_FILENAME),
        QUALIFICATION_EXPOSURE_FILENAME: (
            qual_dir / QUALIFICATION_EXPOSURE_FILENAME),
        PARAMETER_PACK_FILENAME: qual_dir / PARAMETER_PACK_FILENAME,
        PREPROCESSOR_ENVELOPE_FILENAME: (
            qual_dir / PREPROCESSOR_ENVELOPE_FILENAME),
    }
    missing = [name for name, p in required.items() if not p.is_file()]
    checks["all_required_files_exist"] = not missing
    if missing:
        problems.append(f"资格输入缺件: {missing}")
    auth_exists = authorization_path.is_file()
    checks["authorization_file_exists"] = auth_exists
    if not auth_exists:
        problems.append(f"缺少训练授权锚: {authorization_path}")
    try:
        _inside = authorization_path.resolve().is_relative_to(
            qual_dir.resolve())
    except (OSError, ValueError):
        _inside = False
    checks["authorization_not_self_issued"] = not _inside
    if _inside:
        problems.append(
            "授权锚位于资格目录内部(自授权拒绝:输入文件重新哈希不能"
            "自授训练权限)")
    if problems:
        raise _reject()

    # 1-2. plan 解析 + digest 重算
    try:
        plan = json.loads(
            required[QUALIFICATION_PLAN_FILENAME].read_text(
                encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"资格 plan 不可解析: {exc}")
        raise _reject()
    checks["plan_format"] = plan.get("format") == QUALIFICATION_PLAN_FORMAT
    if not checks["plan_format"]:
        problems.append(
            f"plan format {plan.get('format')!r} != "
            f"{QUALIFICATION_PLAN_FORMAT!r}(旧 R2/未知格式冒充拒绝)")
    digest = qualification_plan_digest(plan)
    locked_digest = required[QUALIFICATION_PLAN_DIGEST_FILENAME].read_text(
        encoding="utf-8").strip()
    checks["plan_digest_recomputed"] = digest == locked_digest
    if not checks["plan_digest_recomputed"]:
        problems.append(
            f"plan digest 重算 {digest} != 锁定 {locked_digest}")
    plan_scope = plan.get("scope")
    checks["plan_scope_declared"] = plan_scope in QUALIFICATION_SCOPES
    if not checks["plan_scope_declared"]:
        problems.append(f"plan scope {plan_scope!r} 未声明合法 scope")
    if problems:
        raise _reject()

    # 3. result 绑定 + verdict
    result = json.loads(required[QUALIFICATION_RESULT_FILENAME].read_text(
        encoding="utf-8"))
    checks["result_format"] = (
        result.get("format") == QUALIFICATION_RESULT_FORMAT)
    checks["result_binds_plan"] = result.get("plan_digest") == digest
    checks["result_verdict_pass"] = result.get("verdict") == "PASS"
    checks["result_iteration_matches"] = (
        result.get("iteration") == plan.get("iteration"))
    checks["result_source_iteration_present"] = bool(
        result.get("source_iteration"))
    # B2.1(ChatGPT 终审反例 source_iteration_mismatch):source 迭代
    # 身份必须与 plan 实际关联,不是"非空字符串"即可
    checks["result_source_iteration_matches_plan"] = (
        result.get("source_iteration") == plan.get("source_iteration"))
    for ok, msg in (
            (checks["result_format"], "result format 不识别"),
            (checks["result_binds_plan"], "result 未绑定 plan digest"),
            (checks["result_verdict_pass"],
             f"verdict = {result.get('verdict')!r} != PASS"),
            (checks["result_iteration_matches"],
             "result 与 plan 的 iteration 不一致"),
            (checks["result_source_iteration_present"],
             "result 缺 source iteration 身份"),
            (checks["result_source_iteration_matches_plan"],
             "result source_iteration 与 plan source_iteration 不一致"
             "(来源/终态关联未核验)")):
        if not ok:
            problems.append(msg)

    # 4. exposure 绑定 + 一次性终态
    exposure = json.loads(
        required[QUALIFICATION_EXPOSURE_FILENAME].read_text(
            encoding="utf-8"))
    checks["exposure_format"] = (
        exposure.get("format") == QUALIFICATION_EXPOSURE_FORMAT)
    checks["exposure_binds_plan"] = exposure.get("plan_digest") == digest
    checks["exposure_completed"] = exposure.get("status") == "completed"
    checks["exposure_one_shot"] = exposure.get("one_shot") is True
    # B2.1(反例 exposure_iteration_mismatch):终态必须绑定同一执行
    # iteration(与 plan/result 三方一致);可选 source 字段若出现也须一致
    checks["exposure_iteration_matches"] = (
        exposure.get("iteration") == plan.get("iteration"))
    exposure_src = exposure.get("source_iteration")
    checks["exposure_source_iteration_consistent"] = (
        exposure_src is None
        or exposure_src == plan.get("source_iteration"))
    for ok, msg in (
            (checks["exposure_format"], "exposure format 不识别"),
            (checks["exposure_binds_plan"], "exposure 未绑定 plan digest"),
            (checks["exposure_completed"],
             f"exposure status = {exposure.get('status')!r} != completed"),
            (checks["exposure_one_shot"],
             "exposure 未声明一次性终态语义"),
            (checks["exposure_iteration_matches"],
             "exposure iteration 与 plan iteration 不一致(终态与源"
             "迭代未关联)"),
            (checks["exposure_source_iteration_consistent"],
             "exposure source_iteration 与 plan 不一致")):
        if not ok:
            problems.append(msg)

    # 5. pack digest 绑定 + 完整性
    pack = json.loads(required[PARAMETER_PACK_FILENAME].read_text(
        encoding="utf-8"))
    pack_d = parameter_pack_digest(pack)
    checks["pack_format"] = pack.get("format") == PARAMETER_PACK_FORMAT
    pack_bound = plan.get("parameter_pack", {}).get("digest") == pack_d
    checks["pack_binds_plan"] = pack_bound
    fams = pack.get("families", {})
    fams_complete = (
        set(fams) == {"c1_opportunity", "c2_context", "c3_cost"}
        and all(
            set(fams[f].get("rung_params", {})) == {"D0", "D1", "D2", "D3"}
            and isinstance(fams[f].get("reference_thresholds"), dict)
            for f in fams))
    checks["pack_families_complete"] = fams_complete
    for ok, msg in (
            (checks["pack_format"], "pack format 不识别"),
            (checks["pack_binds_plan"], "pack digest 与 plan 绑定不一致"),
            (checks["pack_families_complete"],
             "pack 未覆盖三族 x D0-D3 rung_params + thresholds")):
        if not ok:
            problems.append(msg)

    # 6. V2 bundle envelope(复用 2.6.1 公共实现,自带篡改检测)
    try:
        from rl_curriculum.curriculum261_r4_preprocessing import (
            RouteCPreprocessorV2,
        )
        preproc = RouteCPreprocessorV2.load_envelope(
            required[PREPROCESSOR_ENVELOPE_FILENAME])
        bundle_hash = preproc.bundle_hash
    except RuntimeError as exc:
        checks["preprocessor_envelope_valid"] = False
        problems.append(f"V2 preprocessing envelope 拒绝: {exc}")
        raise _reject()
    checks["preprocessor_envelope_valid"] = True
    checks["bundle_binds_plan"] = (
        plan.get("preprocessor_bundle_hash") == bundle_hash)
    if not checks["bundle_binds_plan"]:
        problems.append(
            f"bundle hash {bundle_hash} != plan 绑定 "
            f"{plan.get('preprocessor_bundle_hash')!r}")

    # 6b. N01(反例 declared_fit_training_namespace_overlap):输入声明
    # 的 fit 来源 namespace 不得兼任任何 seed 派生 namespace(261 全部
    # 正式/研究 namespace 与 262 全部训练/评估 namespace)——声明面与
    # 消费派生面必须隔离;fit manifest 内部 entries 的 namespace 也须
    # 与声明一致(envelope 自校验已覆盖单一批次,这里核声明面)
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_SEED_NAMESPACES,
    )
    from rl_curriculum.ppo262_namespaces import all_262_namespaces

    seed_side = set(CURRICULUM261_SEED_NAMESPACES) | set(
        all_262_namespaces())
    fit_ns = str((plan.get("preprocessing") or {}).get(
        "fit_namespace", ""))
    checks["fit_namespace_isolated_from_seed_derivation"] = (
        bool(fit_ns) and fit_ns not in seed_side)
    if not checks["fit_namespace_isolated_from_seed_derivation"]:
        problems.append(
            f"声明的 fit namespace {fit_ns!r} 为空或与 seed 派生 "
            f"namespace 重合(fit 来源面与训练/评估派生面必须隔离;"
            f"同源串用拒绝)")

    # 7. Cq/Ct 共同执行语义
    contract_now = _check_code_compatibility(plan, checks, problems)

    # 8. 授权锚
    auth = json.loads(authorization_path.read_text(encoding="utf-8"))
    checks["authorization_format"] = (
        auth.get("format") == AUTHORIZATION_FORMAT)
    bindings = auth.get("bindings", {})
    checks["authorization_binds_inputs"] = (
        bindings.get("qualification_plan_digest") == digest
        and bindings.get("parameter_pack_digest") == pack_d
        and bindings.get("preprocessor_bundle_hash") == bundle_hash)
    checks["authorization_binding_digest_valid"] = (
        auth.get("binding_digest") == authorization_binding_digest({
            **bindings, "profile": auth.get("profile"),
            "scope": auth.get("scope")}))
    checks["authorization_scope_matches"] = auth.get("scope") == expected_scope
    if not checks["authorization_scope_matches"]:
        problems.append(
            f"授权 scope = {auth.get('scope')!r} != 要求 {expected_scope!r}"
            f"(工程许可不能解锁正式入口;正式资格未成立)")
    profile = str(auth.get("profile", ""))
    checks["authorization_profile_known"] = bool(profile)
    if expected_profile is not None:
        checks["authorization_profile_matches"] = profile == expected_profile
        if not checks["authorization_profile_matches"]:
            problems.append(
                f"授权 profile = {profile!r} != 要求 {expected_profile!r}")
    for key, ok in (("authorization_format", checks["authorization_format"]),
                    ("authorization_binds_inputs",
                     checks["authorization_binds_inputs"]),
                    ("authorization_binding_digest_valid",
                     checks["authorization_binding_digest_valid"]),
                    ("authorization_profile_known",
                     checks["authorization_profile_known"])):
        if not ok:
            problems.append(f"授权锚校验失败: {key}")

    # 9. formal scope 的 admission 锚注册表防线(空注册表 => 恒拒)
    if expected_scope == "formal":
        anchor = auth.get("admission_anchor") or {}
        anchor_file = str(anchor.get("file", ""))
        registered_sha = FORMAL_ADMISSION_REGISTRY.get(anchor_file)
        anchor_ok = False
        if registered_sha is not None:
            anchor_path = _FORMAL_ADMISSION_DIR / anchor_file
            if anchor_path.is_file():
                anchor_ok = (hashlib.sha256(
                    anchor_path.read_bytes()).hexdigest() == registered_sha)
        checks["formal_admission_anchor_registered"] = anchor_ok
        if not anchor_ok:
            problems.append(
                "formal 装载要求已注册的正式 admission 锚(注册表当前"
                "为空:正式资格/正式 admission 链未实现;工程件或手工"
                "伪造的 formal 授权不能解锁正式训练)")

    report = {
        "format": "ppo262e-qualified-input-lock-v1",
        "qualification_dir": str(qual_dir),
        "authorization_path": str(authorization_path),
        "expected_scope": expected_scope,
        "checks": checks,
        "problems": problems,
        "rejected": bool(problems) or not all(checks.values()),
    }
    if report["rejected"]:
        raise QualifiedInputError(report)
    return QualifiedInput(
        plan=plan, plan_digest=digest, pack=pack, pack_digest=pack_d,
        preprocessor=preproc, bundle_hash=bundle_hash, authorization=auth,
        scope=expected_scope, profile=profile, contract_now=contract_now,
        report=report)
