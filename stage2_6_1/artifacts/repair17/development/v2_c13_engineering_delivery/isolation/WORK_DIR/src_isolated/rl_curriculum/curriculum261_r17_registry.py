# -*- coding: utf-8 -*-
"""R17 namespace 注册表与部署绑定(纯常量层;无 execgov 依赖)。

R17 相对 R16 的差异(任务书 §5-§7):
- 正式状态根由冻结部署身份唯一确定并在准入时绑定
  (R17_DEPLOYED_STATE_ROOT);此后不随环境变量变化重新解析;
- 静态资格(六要素)仍为只读检查,回答"可以申请开始
  qualification";动态执行权唯一入口 =
  curriculum261_r17_execgov.require_r17_generation_authorization;
- 白名单单一权威在 curriculum261_api.py(本模块 re-export)。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

CURRICULUM261_ITERATION_ID_R17 = "r17"

#: R17 状态根环境变量(仅准入解析;一致性由 execgov 验证)。
R17_STATE_ROOT_ENV = "CURRICULUM261_R17_STATE_ROOT"

#: 冻结部署状态根(正式部署唯一;rehearsal/测试用 env 覆盖到
#: 隔离目录——env 指向别处时 execgov 的部署绑定检查会拒绝正式面)。
R17_DEPLOYED_STATE_ROOT: str | None = os.environ.get(
    "CURRICULUM261_R17_DEPLOYED_STATE_ROOT") or None

#: R17 正式资格四件套(数据面;§6.5)。
R17_FORMAL_QUALIFICATION_NAMESPACES = (
    "qualification_r17",
    "preprocess_fit_qualification_r17",
    "c2_independent_qualification_r17",
    "cue_semantic_qualification_r17",
)

#: R17 全部 seed namespace(白名单单一权威在 api;此处为派生对齐)。
R17_ALL_NAMESPACES = (
    "cue_contract_model_r17", "cue_contract_validation_r17",
    "cue_k_global_null_r17", "preplan_engineering_smoke_r17",
    "preplan_smoke_r17", "preplan_candidate_eval_r17",
    "preplan_semantic_main_r17", "preplan_semantic_validation_r17",
    "preplan_fit_main_r17", "preplan_fit_holdout_r17",
    "preplan_supervised_main_r17", "preplan_supervised_holdout_r17",
    "preplan_calibration_main_r17", "preplan_calibration_holdout_r17",
    "preplan_final_r17", "shadow_fit_main_r17",
    "shadow_fit_holdout_r17", "shadow_supervised_main_r17",
    "shadow_supervised_holdout_r17", "shadow_calibration_main_r17",
    "shadow_calibration_holdout_r17", "shadow_semantic_main_r17",
    "shadow_semantic_validation_r17", "shadow_c2_independent_main_r17",
    "shadow_c2_independent_holdout_r17", "shadow_semantic_final_r17",
    "reference_diagnostic_main_r17", "reference_diagnostic_holdout_r17",
    "reference_diagnostic_r17", "rt_cue_model_r17",
    "rt_cue_validation_r17", "rt_design_matched_main_r17",
    "rt_design_matched_validation_r17", "rt_design_independent_r17",
    "rt_semantic_design_main_r17", "rt_semantic_design_validation_r17",
    "rt_fit_main_r17", "rt_fit_holdout_r17",
    "rt_fit_qualification_r17", "rt_calibration_main_r17",
    "rt_calibration_holdout_r17", "rt_supervised_main_r17",
    "rt_supervised_holdout_r17", "rt_semantic_main_r17",
    "rt_semantic_validation_r17", "rt_semantic_final_r17",
    "rt_c2_independent_main_r17", "rt_c2_independent_holdout_r17",
    "rt_stress_r17", "rt_qualification_r17", "rt3_fit_main_r17",
    "rt3_fit_holdout_r17", "rt3_fit_qualification_r17",
    "rt3_calibration_main_r17", "rt3_calibration_holdout_r17",
    "rt3_supervised_main_r17", "rt3_supervised_holdout_r17",
    "rt3_semantic_main_r17", "rt3_semantic_validation_r17",
    "rt3_semantic_final_r17", "rt3_c2_independent_main_r17",
    "rt3_c2_independent_holdout_r17", "rt3_stress_r17",
    "rt3_qualification_r17", "cue_semantic_design_main_r17",
    "cue_semantic_design_validation_r17", "design_r17_matched_main",
    "design_r17_matched_validation", "design_r17_independent_marginal",
    "preprocess_fit_calibration_r17", "preprocess_fit_holdout_r17",
    "preprocess_fit_qualification_r17", "supervised_main_r17",
    "supervised_holdout_r17", "cue_semantic_calibration_r17",
    "cue_semantic_holdout_r17", "cue_semantic_qualification_r17",
    "calibration_r17", "calibration_holdout_r17",
    "qualification_r17", "c2_independent_calibration_r17",
    "c2_independent_holdout_r17", "c2_independent_qualification_r17",
    "stress_r17", "fresh_holdout_r17", "training_r17",
    "ppo_smoke_r17",
    # C3 finite-reserve v1: engineering-only; no formal authorization.
    "c3_reserve_main_eng_r17", "c3_reserve_validation_eng_r17",
    # R17 V2 C1/C3 engineering calibration (engineering-only).
    "preplan_v2c13_fit_main_r17", "preplan_v2c13_fit_validation_r17",
    "preplan_v2c13_eval_main_r17", "preplan_v2c13_eval_validation_r17",
)

#: 白名单一致性(api 为单一权威;启动时对齐校验)。
from rl_curriculum.curriculum261_api import (  # noqa: E402
    CURRICULUM261_R17_NAMESPACES,
    CURRICULUM261_R17_FORMAL_NAMESPACES,
    CURRICULUM261_R17_NAMESPACE_ROLES,
)

assert tuple(CURRICULUM261_R17_NAMESPACES) == R17_ALL_NAMESPACES, (
    "R17 registry 与 api 白名单不一致(单一权威在 api;"
    "本断言防两处漂移)")
assert tuple(CURRICULUM261_R17_FORMAL_NAMESPACES) == \
    R17_FORMAL_QUALIFICATION_NAMESPACES


def verify_r17_registry_alignment() -> dict[str, Any]:
    """registry ↔ api 对齐事实(证据用)。"""
    return {
        "n_namespaces": len(R17_ALL_NAMESPACES),
        "n_formal": len(R17_FORMAL_QUALIFICATION_NAMESPACES),
        "api_namespaces_match": tuple(
            CURRICULUM261_R17_NAMESPACES) == R17_ALL_NAMESPACES,
        "api_formal_match": tuple(
            CURRICULUM261_R17_FORMAL_NAMESPACES) ==
        R17_FORMAL_QUALIFICATION_NAMESPACES,
        "unique": len(set(R17_ALL_NAMESPACES)) == len(
            R17_ALL_NAMESPACES),
    }


def r17_state_root() -> Path:
    """R17 状态根(准入解析;部署绑定一致性由 execgov 验证)。

    正式:R17_DEPLOYED_STATE_ROOT(冻结部署身份)。
    工程/rehearsal:R17_STATE_ROOT_ENV 指向隔离临时目录。
    二者都没有 → 无状态根(只读诊断仍可运行,写入面拒绝)。
    """
    env_val = os.environ.get(R17_STATE_ROOT_ENV)
    if env_val:
        return Path(env_val).resolve()
    if R17_DEPLOYED_STATE_ROOT:
        return Path(R17_DEPLOYED_STATE_ROOT).resolve()
    raise RuntimeError(
        "R17 状态根未解析:需要 "
        f"{R17_STATE_ROOT_ENV}(工程)或部署绑定 "
        "CURRICULUM261_R17_DEPLOYED_STATE_ROOT(正式);"
        "不允许隐式缺省写入面")


def require_r17_formal_namespace(namespace: str) -> None:
    """静态资格第一级:namespace 属于 R17 正式面。

    这不是动态执行权(§6.5);执行权唯一入口在 execgov。
    """
    if namespace not in R17_FORMAL_QUALIFICATION_NAMESPACES:
        raise RuntimeError(
            f"namespace {namespace!r} 不属于 R17 正式资格面 "
            f"{R17_FORMAL_QUALIFICATION_NAMESPACES!r}")


def require_r17_namespace_registered(namespace: str) -> None:
    """namespace 属于 R17 全集(防未注册名)。"""
    if namespace not in R17_ALL_NAMESPACES:
        raise RuntimeError(
            f"namespace {namespace!r} 未在 R17 注册表登记")


# ------------------------------------------------- 状态文件名 ----------
R17_DESIGN_PLAN_FILENAME = "r17_design_plan.json"
R17_DESIGN_PLAN_DIGEST_FILENAME = "r17_design_plan_digest.txt"
R17_PARAMETER_PACK_FILENAME = "r17_parameter_pack.json"
R17_DESIGN_DECISION_FILENAME = "r17_design_decision.json"
R17_PLAN_FILENAME = "qualification_plan_r17.json"
R17_PLAN_DIGEST_FILENAME = "qualification_plan_digest_r17.txt"
R17_SEALED_PREFLIGHT_FILENAME = "sealed_final_preflight_r17.json"
R17_SEALED_PREFLIGHT_DIGEST_FILENAME = (
    "sealed_final_preflight_r17_digest.txt")
R17_STATIC_PREFLIGHT_FILENAME = "prelock_static_preflight_r17.json"


def r17_design_plan_path() -> Path:
    return r17_state_root() / R17_DESIGN_PLAN_FILENAME


def r17_design_plan_digest_path() -> Path:
    return r17_state_root() / R17_DESIGN_PLAN_DIGEST_FILENAME


def r17_design_decision_path() -> Path:
    return r17_state_root() / R17_DESIGN_DECISION_FILENAME


def r17_parameter_pack_path() -> Path:
    return r17_state_root() / R17_PARAMETER_PACK_FILENAME


def qualification_r17_plan_path() -> Path:
    return r17_state_root() / R17_PLAN_FILENAME


def qualification_r17_digest_path() -> Path:
    return r17_state_root() / R17_PLAN_DIGEST_FILENAME


def sealed_preflight_r17_path() -> Path:
    return r17_state_root() / R17_SEALED_PREFLIGHT_FILENAME


def sealed_preflight_r17_digest_path() -> Path:
    return r17_state_root() / R17_SEALED_PREFLIGHT_DIGEST_FILENAME


# ------------------------------------------------- 静态资格(六要素) ---
def sealed_preflight_r17_valid() -> bool:
    """sealed attestation 存在、digest 复算一致且绑定通过。"""
    path = sealed_preflight_r17_path()
    digest_path = sealed_preflight_r17_digest_path()
    if not path.is_file() or not digest_path.is_file():
        return False
    try:
        att = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    from rl_curriculum.curriculum261_r15_preflight import (
        sealed_preflight_digest,
    )

    try:
        if sealed_preflight_digest(att) != att.get("digest"):
            return False
    except (KeyError, TypeError):
        return False
    if digest_path.read_text(encoding="utf-8").strip() != \
            att.get("digest"):
        return False
    return bool(att.get("pass") is True)


def sealed_preflight_r17_binds_plan(plan: dict[str, Any]) -> bool:
    """sealed attestation 绑定当前 qualification plan。"""
    path = sealed_preflight_r17_path()
    if not path.is_file():
        return False
    try:
        att = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    from rl_curriculum.curriculum261_r15_plan import plan_digest_r15

    try:
        return att.get("plan_digest") == plan_digest_r15(plan)
    except (KeyError, TypeError):
        return False


def qualification_r17_unlocked_detail() -> dict[str, Any]:
    """六要素逐项事实(只读静态资格;§7.1 静态资格≠动态执行权)。

    要素:plan 存在且 iteration=r17;digest 复算一致;robustness
    gate PASS;parameter pack 绑定一致;sealed preflight 有效;
    sealed 绑定本 plan。
    """
    detail: dict[str, Any] = {
        "iteration": CURRICULUM261_ITERATION_ID_R17,
        "plan_present": qualification_r17_plan_path().is_file(),
        "digest_present": qualification_r17_digest_path().is_file(),
        "plan_iteration_ok": False,
        "digest_match": False,
        "robustness_gate_pass": False,
        "parameter_pack_bound": False,
        "sealed_preflight_valid": False,
        "sealed_binds_plan": False,
    }
    plan_path = qualification_r17_plan_path()
    digest_path = qualification_r17_digest_path()
    if not (detail["plan_present"] and detail["digest_present"]):
        detail["unlocked"] = False
        return detail
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        detail["unlocked"] = False
        return detail
    detail["plan_iteration_ok"] = (
        plan.get("iteration") == CURRICULUM261_ITERATION_ID_R17)
    from rl_curriculum.curriculum261_r15_plan import plan_digest_r15

    try:
        detail["digest_match"] = (
            plan_digest_r15(plan) ==
            digest_path.read_text(encoding="utf-8").strip())
    except (KeyError, TypeError, OSError):
        pass
    gate = plan.get("robustness_gate", {})
    detail["robustness_gate_pass"] = bool(
        isinstance(gate, dict) and gate.get("pass") is True)
    pack_digest_in_plan = (
        plan.get("parameter_pack", {}).get("digest"))
    if pack_digest_in_plan:
        from rl_curriculum.curriculum261_r15_param_pack import (
            load_selected_pack,
        )

        try:
            pack = load_selected_pack(r17_state_root())
            detail["parameter_pack_bound"] = bool(
                pack["digest"] == pack_digest_in_plan)
        except (RuntimeError, OSError):
            pass
    detail["sealed_preflight_valid"] = sealed_preflight_r17_valid()
    detail["sealed_binds_plan"] = (
        sealed_preflight_r17_binds_plan(plan)
        if detail["sealed_preflight_valid"] else False)
    detail["unlocked"] = bool(
        detail["plan_iteration_ok"] and detail["digest_match"]
        and detail["robustness_gate_pass"]
        and detail["parameter_pack_bound"]
        and detail["sealed_preflight_valid"]
        and detail["sealed_binds_plan"])
    return detail


def qualification_r17_unlocked() -> bool:
    return bool(qualification_r17_unlocked_detail()["unlocked"])


# ------------------------------------------------- 状态查询兼容层 ------
# (R16 namespaces 的等价接口;R17 中权威状态全部在 execgov journal。
# 此处函数内延迟 import 以避免 execgov<->registry 循环依赖;
# dependencies 表已覆盖。)


def qualification_r17_exposed() -> bool:
    """exposure 已发生(journal 权威;损坏按已暴露,fail closed)。"""
    from rl_curriculum.curriculum261_r17_execgov import exposure_state

    return bool(exposure_state()["exposed"])


def r17_iteration_aborted() -> bool:
    """iteration 终止判定(journal 权威;损坏即 fail closed)。"""
    from rl_curriculum.curriculum261_r17_execgov import iteration_aborted

    return iteration_aborted(strict=True)


def require_r17_iteration_active() -> None:
    """R17 各阶段入口共用守卫:aborted 后拒绝一切继续执行。"""
    if r17_iteration_aborted():
        raise RuntimeError(
            "R17 iteration 已 aborted;按治理合同永久结束,任何继续"
            "执行(design/calibration/final)均被拒绝")


def qualification_r17_lock_dir() -> Path:
    """兼容别名(R16 namespaces 语义):状态根。"""
    return r17_state_root()


def design_data_started() -> bool:
    """design 阶段正式数据开始事件是否已由协调者写入(journal)。"""
    from rl_curriculum.curriculum261_r17_execgov import journal_entries

    try:
        return any(e["event"] == "design_data_started"
                   for e in journal_entries())
    except Exception:  # noqa: BLE001 —— corruption 视同已开始(fail
        return True    # closed:不得在状态不可知时重跑 design)


def require_design_data_started() -> None:
    """worker 侧断言:协调者已在本步骤启动前写入 design_data_started。

    R17 §5.4:design_data_started 由受控消息交给协调者写入,
    worker 不直接成为第二个 journal writer;worker 只验证。
    """
    if not design_data_started():
        raise RuntimeError(
            "design_data_started 事件缺失:R17 语义下该事件由链"
            "会话协调者在启动 design 步骤子进程之前写入;"
            "worker 不得自行生成正式数据(§WP1)")


def write_r17_iteration_aborted(reason: str) -> dict[str, Any]:
    """失败封口的 R17 语义(分层):

    - 当前进程是活动链会话 owner(单进程/rehearsal)→ 直接写
      journal(chain_iteration_aborted)+投影 marker;
    - 步骤子进程(非 owner)→ 写独立 abort 请求文件
      (abort_request_<pid>.json),由协调者在子进程非零退出时代写;
      子进程绝不直接写权威 journal(单写者合同)。
    """
    from rl_curriculum.curriculum261_r17_execgov import (
        R17ChainSession, write_rejection_evidence,
    )

    # 无活动会话对象可判定时,走请求文件路径(子进程标准路径)。
    # owner 直接调用场景由 R17ChainSession.record_iteration_aborted
    # 承担;本函数是 CLI 异常处置的兼容入口。
    req = {
        "kind": "iteration_abort_request",
        "reason": reason[:2000],
        "requester_identity": __import__(
            "rl_curriculum.curriculum261_r17_execgov",
            fromlist=["executor_identity"]).executor_identity(),
        "utc": _now_utc_compat(),
    }
    try:
        d = r17_state_root() / "pending_abort_requests"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"abort_request_{os.getpid()}_{int(time.time() * 1000)}.json"
        import json as _json

        p.write_text(_json.dumps(req, ensure_ascii=False,
                                 sort_keys=True), encoding="utf-8")
        return {"status": "abort_request_written", "path": str(p)}
    except Exception:  # noqa: BLE001 —— 请求尽力而为
        return {"status": "abort_request_failed"}


def _now_utc_compat() -> str:
    import datetime

    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def mark_design_data_started(note: str = "") -> None:
    """兼容名(worker 侧):R17 语义 = 验证协调者已写(fail closed)。"""
    require_design_data_started()


def verify_r17_namespace_name_isolation() -> dict[str, Any]:
    """名称级隔离静态检查(§WP2.5 覆盖真正的数据入口前置)。

    - 正式四件套不携带历史迭代后缀(_r0.._r17 除 r17 外);
    - roles 的 iteration 一致为 r17;
    - 正式面与工程面不相交。
    """
    problems: list[str] = []
    historical_suffixes = tuple(
        f"_r{n}" for n in range(0, 17)) + (
        "_r2", "_r3", "_r4", "_r5", "_r6", "_r7", "_r8", "_r9",
        "_r10", "_r11", "_r12", "_r13", "_r14", "_r15", "_r16")
    for name in R17_FORMAL_QUALIFICATION_NAMESPACES:
        for suf in historical_suffixes:
            if name.endswith(suf):
                problems.append(
                    f"formal namespace {name!r} 携带历史后缀 {suf!r}")
    for name, role in CURRICULUM261_R17_NAMESPACE_ROLES.items():
        if role.get("iteration") != CURRICULUM261_ITERATION_ID_R17:
            problems.append(f"role iteration 漂移:{name}->{role}")
    formal_set = set(R17_FORMAL_QUALIFICATION_NAMESPACES)
    engineering_set = set(R17_ALL_NAMESPACES) - formal_set
    if formal_set & engineering_set:
        problems.append("正式面与工程面相交")
    return {"pass": not problems, "problems": problems,
            "n_formal": len(formal_set),
            "n_engineering": len(engineering_set)}


#: 兼容别名(r16 namespaces 同名接口;cli/_verify_namespace_safe)。
verify_r17_namespace_isolation = verify_r17_namespace_name_isolation

