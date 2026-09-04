# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R15:main/holdout/final bundle routing 合同(§9)。

R9 确认输入(正式失败根因链的一部分):
- R9 CLI 虽然分别拟合 v2_main / v2_hold,但三处 holdout 评估
  (calibration_holdout_r9 的 C1/C3 语料、C2 matched 语料、C2 independent
  语料)继续传入 v2_main —— holdout 从未真正在 holdout bundle 上评估。

R15 修复(§9):
- 显式 R15BundleRouting 数据类:role / fit namespace / 三层 bundle hash,
  唯一 evaluator 入口是 routing.bundle();
- 禁止隐式全局 preprocessor:每个 evaluator 显式收到 routing 并在生成
  第一条评估结果前校验 expected role / expected fit namespace /
  expected bundle hash(fail closed);
- namespace → role 权威映射(正式 + preplan 双表);
- RoutingLedgerR15 落盘完整路由矩阵(§9.4):corpus → expected fit
  namespace → actual fit namespace → expected bundle hash → actual
  bundle hash → pass/fail。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

#: §9.1 正式路由:role → 期望 fit namespace。
R15_ROLE_FIT_NAMESPACE: dict[str, str] = {
    "main": "preprocess_fit_calibration_r15",
    "holdout": "preprocess_fit_holdout_r15",
    "final": "preprocess_fit_qualification_r15",
}

#: §9.1 preplan/rehearsal 路由(execution profile 只换 namespace)。
R15_PREPLAN_ROLE_FIT_NAMESPACE: dict[str, str] = {
    "main": "preplan_fit_main_r15",
    "holdout": "preplan_fit_holdout_r15",
    "final": "preplan_fit_main_r15",  # rehearsal final-like 复用 main fit
    "diagnostic": "preplan_fit_main_r15",
}

#: repair R15(工作包 C):full-scale shadow rehearsal 路由(工程、
#: 非正式;两次独立 cold run;不产生任何参数选择数据)。
R15_SHADOW_ROLE_FIT_NAMESPACE: dict[str, str] = {
    "main": "shadow_fit_main_r15",
    "holdout": "shadow_fit_holdout_r15",
    "final": "shadow_fit_main_r15",  # final-like shadow 复用 main fit
}

#: R15RealArtifactCliRoundTrip-v1(§四-4):rt rehearsal 路由(工程、
#: 非正式;rt_*_r15 rehearsal-only namespace;与 shadow 同构但独立
#: 路由类——rt 的 final 用独立 fit namespace,不复用 main fit)。
R15_RT_ROLE_FIT_NAMESPACE: dict[str, str] = {
    "main": "rt3_fit_main_r15",
    "holdout": "rt3_fit_holdout_r15",
    "final": "rt3_fit_qualification_r15",
}

#: 评估 namespace → 期望 role(§9.1;正式 + preplan + shadow)。
R15_EVAL_NAMESPACE_ROLE: dict[str, str] = {
    # ---- 正式 ----
    "calibration_r15": "main",
    "calibration_holdout_r15": "holdout",
    "qualification_r15": "final",
    "c2_independent_calibration_r15": "main",
    "c2_independent_holdout_r15": "holdout",
    "c2_independent_qualification_r15": "final",
    "supervised_main_r15": "main",
    "supervised_holdout_r15": "holdout",
    "cue_semantic_calibration_r15": "main",
    "cue_semantic_holdout_r15": "holdout",
    "cue_semantic_qualification_r15": "final",
    # ---- preplan / rehearsal / diagnostic(非正式)----
    "reference_diagnostic_main_r15": "diagnostic",
    "reference_diagnostic_holdout_r15": "diagnostic",
    "preplan_smoke_r15": "diagnostic",
    "preplan_candidate_eval_r15": "diagnostic",
    "preplan_supervised_main_r15": "main",
    "preplan_supervised_holdout_r15": "holdout",
    "preplan_calibration_main_r15": "main",
    "preplan_calibration_holdout_r15": "holdout",
    "preplan_final_r15": "final",
    # ---- full-scale shadow(工程;R15 工作包 C)----
    "shadow_supervised_main_r15": "main",
    "shadow_supervised_holdout_r15": "holdout",
    "shadow_calibration_main_r15": "main",
    "shadow_calibration_holdout_r15": "holdout",
    "shadow_semantic_main_r15": "main",
    "shadow_semantic_validation_r15": "holdout",
    "shadow_c2_independent_main_r15": "main",
    "shadow_c2_independent_holdout_r15": "holdout",
    "shadow_semantic_final_r15": "final",
    # ---- R15RealArtifactCliRoundTrip-v1(工程;§四-4)----
    "rt3_calibration_main_r15": "main",
    "rt3_calibration_holdout_r15": "holdout",
    "rt3_supervised_main_r15": "main",
    "rt3_supervised_holdout_r15": "holdout",
    "rt3_semantic_main_r15": "main",
    "rt3_semantic_validation_r15": "holdout",
    "rt3_c2_independent_main_r15": "main",
    "rt3_c2_independent_holdout_r15": "holdout",
    "rt3_qualification_r15": "final",
    "rt3_semantic_final_r15": "final",
    "rt_semantic_design_main_r15": "diagnostic",
    "rt_semantic_design_validation_r15": "diagnostic",
}

_ALLOWED_ROLES = ("main", "holdout", "final", "diagnostic")


class RoutingContractError(RuntimeError):
    """routing 合同违反(fail closed;§9.3)。"""


@dataclass(frozen=True)
class R15BundleRouting:
    """一个已验证的 bundle 路由:role + fit namespace + 三层身份。

    evaluator 只允许通过 bundle() 取得 preprocessor;构造时即校验
    role 与 fit namespace 的权威映射,任何不匹配立即抛
    RoutingContractError(在生成任何评估结果之前)。
    """

    role: str
    fit_namespace: str
    bundle_hash: str
    parameter_state_hash: str
    manifest_multiset_hash: str
    _v2: Any
    preplan: bool = False
    #: repair R15(工作包 C):shadow 路由类(非正式;工程 rehearsal)
    shadow: bool = False
    #: R15RealArtifactCliRoundTrip-v1(§四-4):rt rehearsal 路由类
    rt: bool = False

    @property
    def nonformal(self) -> bool:
        """非正式路由(preplan rehearsal / shadow / rt round-trip)。"""
        return self.preplan or self.shadow or self.rt

    def bundle(self, *, expected_role: str | None = None,
               expected_fit_namespace: str | None = None,
               expected_bundle_hash: str | None = None,
               context: str = "",
               ledger: "RoutingLedgerR15 | None" = None) -> Any:
        """显式取用 evaluator bundle;先校验期望(role/namespace/hash)。

        expected_* 全部可选但 orchestrator/CLI 必须显式传(§9.2);任何
        不匹配在返回 bundle 之前抛错 —— 保证"生成第一条评估结果前失败"。
        """
        exp_role = expected_role or self.role
        exp_ns = expected_fit_namespace or self.fit_namespace
        ok = True
        detail: dict[str, Any] = {
            "corpus": context or "<unnamed>",
            "expected_role": exp_role,
            "actual_role": self.role,
            "expected_fit_namespace": exp_ns,
            "actual_fit_namespace": self.fit_namespace,
            "expected_bundle_hash": expected_bundle_hash or "(unbound)",
            "actual_bundle_hash": self.bundle_hash,
        }
        if self.role != exp_role or self.fit_namespace != exp_ns:
            ok = False
        if expected_bundle_hash is not None \
                and self.bundle_hash != expected_bundle_hash:
            ok = False
        if ledger is not None:
            ledger.record(detail, ok)
        if not ok:
            raise RoutingContractError(
                f"routing 合同违反(context={context or '<unnamed>'}):"
                f"期望 role={exp_role}/fit_namespace={exp_ns}"
                f"/bundle={expected_bundle_hash},实际 role={self.role}"
                f"/fit_namespace={self.fit_namespace}"
                f"/bundle={self.bundle_hash}(fail closed,§9.3)")
        return self._v2


def build_routing_r15(
        role: str, v2: Any, *,
        preplan: bool = False,
        shadow: bool = False,
        rt: bool = False,
        expected_bundle_hash: str | None = None) -> R15BundleRouting:
    """从 fitted V2 构造路由(校验 role↔namespace 权威映射)。

    fail-closed 检查表(§9.3 的全部条目在此实现):
    - role 不在允许集合;
    - fit namespace 与 role 的权威映射不符(main/holdout/final 专用
      namespace 不得交叉);
    - bundle provenance(v2.namespace)与声明的 fit namespace 不一致;
    - expected_bundle_hash 与实际 bundle hash 不符(plan 绑定)。

    repair R15:shadow=True 走 full-scale shadow 路由表(工程)。
    """
    if role not in _ALLOWED_ROLES:
        raise RoutingContractError(f"未知 routing role: {role}")
    if sum(1 for flag in (preplan, shadow, rt) if flag) > 1:
        raise RoutingContractError(
            "preplan/shadow/rt 路由类互斥(至多一个为真)")
    table = (R15_RT_ROLE_FIT_NAMESPACE if rt
             else R15_SHADOW_ROLE_FIT_NAMESPACE if shadow
             else R15_PREPLAN_ROLE_FIT_NAMESPACE if preplan
             else R15_ROLE_FIT_NAMESPACE)
    if role in table and v2.namespace != table[role]:
        raise RoutingContractError(
            f"role={role} 的权威 fit namespace 是 {table[role]},"
            f"bundle 实际 fit namespace 是 {v2.namespace}(fail closed)")
    if v2.namespace not in (list(R15_ROLE_FIT_NAMESPACE.values())
                            + list(
                                R15_PREPLAN_ROLE_FIT_NAMESPACE.values())
                            + list(
                                R15_SHADOW_ROLE_FIT_NAMESPACE.values())
                            + list(
                                R15_RT_ROLE_FIT_NAMESPACE.values())):
        raise RoutingContractError(
            f"bundle fit namespace {v2.namespace} 不属于任何 R15 路由表"
            f"(fail closed)")
    if expected_bundle_hash is not None \
            and v2.bundle_hash != expected_bundle_hash:
        raise RoutingContractError(
            f"bundle hash 与期望不符:expected={expected_bundle_hash} "
            f"actual={v2.bundle_hash}(fail closed)")
    return R15BundleRouting(
        role=role,
        fit_namespace=v2.namespace,
        rt=rt,
        bundle_hash=v2.bundle_hash,
        parameter_state_hash=v2.parameter_state_hash,
        manifest_multiset_hash=v2.manifest_multiset_hash,
        _v2=v2,
        preplan=preplan,
        shadow=shadow,
    )


def require_eval_routing_r15(
        routing: R15BundleRouting, eval_namespace: str, *,
        context: str = "",
        ledger: "RoutingLedgerR15 | None" = None) -> Any:
    """评估 namespace → 期望 role → bundle 的强制检查(§9.1/§9.2)。

    每条评估语料在生成第一条评估结果前调用:eval namespace 必须在权威
    映射中且 routing.role 与映射一致 —— holdout 评估撞 main bundle、
    main 评估撞 holdout bundle、final 用 main/holdout bundle 全部在此
    拒绝(§9.3)。repair R15:非正式路由类(preplan/shadow)不得服务
    正式评估 namespace;正式路由不得服务任何非正式 namespace。
    """
    _NONFORMAL_PREFIXES = ("preplan_", "reference_diagnostic",
                           "shadow_", "rt_", "rt3_")
    expected_role = R15_EVAL_NAMESPACE_ROLE.get(eval_namespace)
    if expected_role is None:
        raise RoutingContractError(
            f"评估 namespace {eval_namespace} 不在 R15 权威路由映射中"
            f"(fail closed;context={context})")
    table = (R15_RT_ROLE_FIT_NAMESPACE if routing.rt
             else R15_SHADOW_ROLE_FIT_NAMESPACE if routing.shadow
             else R15_PREPLAN_ROLE_FIT_NAMESPACE if routing.preplan
             else R15_ROLE_FIT_NAMESPACE)
    if expected_role in table:
        expected_fit_namespace = table[expected_role]
    else:  # diagnostic 等 preplan 专用 role:期望即实际声明值
        expected_fit_namespace = routing.fit_namespace
    if routing.nonformal and not eval_namespace.startswith(
            _NONFORMAL_PREFIXES):
        raise RoutingContractError(
            f"非正式 routing(preplan/shadow)不得服务正式评估 "
            f"namespace {eval_namespace}(fail closed)")
    if not routing.nonformal and eval_namespace.startswith(
            _NONFORMAL_PREFIXES):
        raise RoutingContractError(
            f"正式 routing 不得服务非正式(preplan/shadow)评估 "
            f"namespace {eval_namespace}(fail closed)")
    return routing.bundle(
        expected_role=expected_role,
        expected_fit_namespace=expected_fit_namespace,
        context=context or eval_namespace,
        ledger=ledger,
    )


@dataclass
class RoutingLedgerR15:
    """路由矩阵收集器(§9.4):每条评估一行,pass/fail 由 record 决定。"""

    rows: list[dict[str, Any]] = field(default_factory=list)

    def record(self, detail: dict[str, Any], ok: bool) -> None:
        row = dict(detail)
        row["pass"] = bool(ok)
        self.rows.append(row)

    def matrix(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rows]

    def all_pass(self) -> bool:
        return bool(self.rows) and all(r["pass"] for r in self.rows)


def bundle_routing_contract_digest() -> str:
    """routing 合同 digest(进入 design/final plan identity)。"""
    import hashlib

    payload = bundle_routing_contract_payload()
    return "r15rt-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def bundle_routing_contract_payload() -> dict[str, Any]:
    """§30 bundle_routing_contract:权威映射的可审计表示。"""
    return {
        "format": "cur261-r15-bundle-routing-contract-v1",
        "iteration": "r15",
        "formal_role_fit_namespace": dict(R15_ROLE_FIT_NAMESPACE),
        "preplan_role_fit_namespace": dict(R15_PREPLAN_ROLE_FIT_NAMESPACE),
        "eval_namespace_role": dict(R15_EVAL_NAMESPACE_ROLE),
        "fail_closed_rules": [
            "holdout 评估绑定 main bundle 拒绝",
            "main 评估绑定 holdout bundle 拒绝",
            "namespace 与 bundle provenance 不匹配拒绝",
            "bundle hash 与 plan 不匹配拒绝",
            "fit manifest role 错误拒绝",
            "final 使用 main/holdout bundle 拒绝",
        ],
        "implicit_global_preprocessor": False,
    }
