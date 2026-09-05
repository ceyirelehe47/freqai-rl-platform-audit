# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R16 final qualification(执行所有权生命周期)。

R15 缺口(§2.3)的全部修复落在本模块:

1. 抢锁与异常处置分离(§6.2):R16FormalSession.acquire 失败只记录
   session_rejected 自身事件并 raise R16OwnershipError——不写
   exposure、不写 abort、不写 qualification_crash_traceback.log、
   不触碰 manifest。竞争请求对正式状态零副作用。

2. 终态在会话控制权有效时提交(§6.3):completed/failed/crashed
   全部通过 session.commit_qualification_terminal(锁内 + journal
   权威 + 持有者校验);不存在"释放锁后补写正常终态"的窗口。

3. 异常只结束自己拥有的操作(§6.4):except 分支先检查
   session.owns();仅在持有所有权时封口 crashed,否则(理论上
   不可达的竞态)保留 journal 事实并如实上抛。终态已提交后的
   后续阶段失败由 CLI/workflow 层处置,不覆写资格终态。

4. exposure 先于任何正式数据访问(§8.1):
   record_exposure_started 在 issue_generation_grant 之前持久化
   (journal durable append + fsync),derive261_seed 的 R16 守卫
   在无授权时于第一个 seed 派生前拒绝。

领域计算完全复用 execute_final_core_r15(§3.1:不重写生成分布/
统计规则);R16 只注入 _r16 namespace 与治理外壳。
"""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r16_final_core import (
    execute_final_core_r16,
)
from rl_curriculum.curriculum261_r16_execgov import (
    R16FormalSession,
    R16OwnershipError,
    exposure_state,
)
from rl_curriculum.curriculum261_r16_namespaces import (
    CURRICULUM261_ITERATION_ID_R16,
    qualification_r16_unlocked_detail,
    r16_state_root,
    require_r16_iteration_active,
)
from rl_curriculum.curriculum261_r16_plan import (
    _code_identity_r16,
    load_locked_plan_r16,
)

#: R16 rehearsal final profile(rt3_*_r16 工程 namespace;缩小规模;
#: 不消耗正式 R16 namespace/状态;与 r16_cli 的 R16_RT_FINAL_PROFILE
#: 保持一致——CLI 是唯一权威定义,本 re-export 供 preplan/测试使用)。
R16_RT_FINAL_PROFILE: dict[str, Any] = {
    "final_namespace": "rt3_qualification_r16",
    "fit_namespace": "rt3_fit_qualification_r16",
    "independent_namespace": "rt3_c2_independent_main_r16",
    "semantic_namespace": "rt3_semantic_final_r16",
    "supervised_namespace": "rt3_supervised_main_r16",
    "conditioning_fit_namespace": "rt3_fit_main_r16",
    "c13_pairs_per_rung": 2,
    "c2_blocks": 4,
    "semantic_block_count": 8,
    "independent_pairs_per_rung": 2,
    "supervised_model_seeds": (20270135,),
    "supervised_training_config": {"epochs": 2},
}


def _static_identity_checks_r16(
        plan: dict[str, Any], pack: dict[str, Any],
        out_dir: Path, vendor_dir: Path | None) -> None:
    """不需要 final seed 的静态身份检查(exposure 之前;fail closed)。

    复用 R15 的领域检查实现;代码身份换成 R16 模块清单。
    """
    from rl_curriculum.curriculum261_final import (
        _frozen_contract_integrity,
        _upstream_integrity,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r16_dependencies import (
        verify_r16_code_freeze,
    )

    frozen = _frozen_contract_integrity()
    vendor_dir = vendor_dir or _vendor_dir_default()
    upstream = _upstream_integrity(vendor_dir)
    upstream_ok = (upstream["sha"] == plan["vendor_pin"]
                   and upstream["clean"])
    v2_digest = preprocessing_v2_contract_digest()
    contract_ok = (v2_digest
                   == plan["preprocessing_v2"]["contract_digest"])
    code_ok = (plan["code_identity"] == _code_identity_r16())
    cue_plan = plan.get("cue_semantic_contract", {})
    cue_contract_ok = bool(
        pack.get("cue_semantic_contract_digest")
        == cue_plan.get("contract_digest")
        and pack.get("cue_semantic_rule_identity")
        == cue_plan.get("rule_identity")
        and float(pack.get("p_contract", -1))
        == float(cue_plan.get("p_contract", -2))
        and float(pack.get("recall_floor", -1))
        == float(cue_plan.get("recall_floor", -2)))
    static_ok = bool(frozen["pass"] and upstream_ok and contract_ok
                     and code_ok and cue_contract_ok)
    if not static_ok:
        raise RuntimeError(
            "R16 final 静态身份检查失败(frozen contracts/vendor/V2 "
            "digest/code identity/cue semantic contract);在 exposure "
            "之前 fail closed——本轮 qualification_r16 未消耗:"
            f" frozen={frozen['pass']} vendor={upstream_ok} "
            f"v2={contract_ok} code={code_ok} cue={cue_contract_ok}")
    freeze = verify_r16_code_freeze(Path(out_dir))
    if not freeze["pass"]:
        raise RuntimeError(
            f"R16 code freeze 校验失败(正式数据开始后源码漂移;"
            f"§6/§21 永久结束):{freeze}")
    plan_freeze = (plan.get("code_freeze") or {}).get("code_freeze_sha")
    if plan_freeze and freeze.get("code_freeze_sha") != plan_freeze:
        raise RuntimeError("plan 绑定的 code freeze SHA 与冻结清单不一致")


def _vendor_dir_default() -> Path:
    from rl_curriculum.curriculum261_r6_preflight import vendor_dir_default

    return vendor_dir_default()


def run_final_qualification_r16(out_dir: Path,
                                vendor_dir: Path | None = None,
                                *,
                                rehearsal_profile: dict[str, Any] | None
                                = None) -> dict[str, Any]:
    """执行一次性 R16 final qualification(§6.3 生命周期)。

    rehearsal_profile 非 None 时执行 round-trip rehearsal final
    (rt3_*_r16 工程 namespace + 缩小规模 + 隔离状态根;治理外壳
    与正式路径同代码,唯一差异来自预注册 profile 参数;verdict 在
    缩小规模下不作资格判定)。
    """
    out_dir = Path(out_dir)
    rt = rehearsal_profile is not None
    require_r16_iteration_active()
    if not rt:
        state = exposure_state()
        if state["exposed"]:
            raise RuntimeError(
                "R16 final qualification 已 exposure(exposure 事件在"
                "权威 journal 中存在)——一次性资格已消耗;继续必须"
                "新迭代与全新 seed space")
    plan, digest = load_locked_plan_r16()
    if (plan.get("robustness_gate") or {}).get("pass") is not True:
        raise RuntimeError(
            "R16 plan 的 robustness_gate.pass != true——final "
            "qualification fail closed")
    from rl_curriculum.curriculum261_r16_param_pack import load_selected_pack

    pack = load_selected_pack(r16_state_root())
    if pack["digest"] != plan["parameter_pack"]["digest"]:
        raise RuntimeError(
            "plan 绑定的 parameter pack digest 与 artifact 不一致"
            "(fail closed)")
    from rl_curriculum.curriculum261_r16_preflight import (
        verify_sealed_attestation,
    )

    attestation = verify_sealed_attestation(Path(out_dir))
    if not attestation["pass"]:
        raise RuntimeError(
            f"sealed final preflight attestation 验证失败:"
            f"{attestation}(final 前置条件;fail closed)")
    if attestation["attestation"]["plan_digest"] != digest:
        raise RuntimeError("attestation 绑定的 plan digest 与当前 plan 不符")
    _static_identity_checks_r16(plan, pack, out_dir, vendor_dir)

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out_dir.mkdir(parents=True, exist_ok=True)
    if rt:
        core_kwargs = dict(
            profile_name="rt_final",
            final_namespace=str(rehearsal_profile["final_namespace"]),
            fit_namespace=str(rehearsal_profile["fit_namespace"]),
            c13_pairs_per_rung=int(
                rehearsal_profile["c13_pairs_per_rung"]),
            c2_blocks=int(rehearsal_profile["c2_blocks"]),
            semantic_block_count=int(
                rehearsal_profile["semantic_block_count"]),
            independent_pairs_per_rung=int(
                rehearsal_profile["independent_pairs_per_rung"]),
            rehearsal=False, shadow=False, rt=True,
            independent_namespace=str(
                rehearsal_profile["independent_namespace"]),
            semantic_namespace_override=str(
                rehearsal_profile["semantic_namespace"]),
            semantic_out_dir=out_dir,
            supervised_namespace_override=str(
                rehearsal_profile["supervised_namespace"]),
            supervised_model_seeds_override=tuple(
                rehearsal_profile["supervised_model_seeds"]),
            supervised_training_config=dict(
                rehearsal_profile["supervised_training_config"]),
            conditioning_fit_namespace=str(
                rehearsal_profile["conditioning_fit_namespace"]))
    else:
        core_kwargs = dict(
            profile_name="formal_final_r16",
            final_namespace="qualification_r16",
            fit_namespace="preprocess_fit_qualification_r16",
            c13_pairs_per_rung=10,
            c2_blocks=int(plan["final_sample_counts"][
                "c2_matched_blocks"]),
            semantic_block_count=160,
            independent_pairs_per_rung=20,
            independent_namespace="c2_independent_qualification_r16",
            semantic_namespace_override="cue_semantic_qualification_r16",
            fresh_seed_final_namespace="qualification_r16",
            fresh_seed_holdout_namespace="fresh_holdout_r16")

    # ---- §6.3 生命周期:唯一会话 → exposure → 授权 → core → 终态 ---
    session = R16FormalSession.acquire(binding={
        "iteration": CURRICULUM261_ITERATION_ID_R16,
        "plan_digest": digest,
        "mode": "rehearsal" if rt else "formal",
        "state_root": str(r16_state_root()),
        "out_dir": str(out_dir),
        "unlocked_detail": qualification_r16_unlocked_detail(),
    })
    try:
        session.record_exposure_started(
            digest, note="rt" if rt else "formal R16 qualification")
    except BaseException:
        # exposure 未持久化 ⇒ 正式机会未消耗;释放会话(无 exposure
        # 无授权的孤儿允许新会话接管),不封口任何终态。
        try:
            session.release(summary="exposure persistence failed")
        except Exception:  # noqa: BLE001 - 不得掩盖原始异常
            pass
        raise
    try:
        grant = session.issue_generation_grant()
    except BaseException:
        # exposure 已持久化但授权失败 ⇒ 孤儿 running;本进程仍持
        # 有所有权,唯一正确处置 = 封口 crashed 后释放。
        try:
            (out_dir / "qualification_crash_traceback.log").write_text(
                traceback.format_exc(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        try:
            session.commit_qualification_terminal(
                "crashed", digest, note="grant issue failed")
            session.release(summary="crashed: grant issue failed")
        except Exception:  # noqa: BLE001
            pass
        raise
    try:
        result = execute_final_core_r16(
            out_dir, plan, pack, digest=digest, started=started,
            **core_kwargs)
    except BaseException:
        # §6.4:异常只结束自己拥有的操作。会话仍归本进程所有 ⇒
        # 本进程正确封口 crashed(崩溃路径日志先落盘);所有权
        # 缺失(不可达竞态)则保留 journal 事实上抛,不伪造终态。
        exc_text = traceback.format_exc()
        try:
            (out_dir / "qualification_crash_traceback.log").write_text(
                exc_text, encoding="utf-8")
        except Exception:  # noqa: BLE001 - 不得掩盖原始异常
            pass
        if session.owns():
            try:
                session.revoke_generation_grant()
                session.commit_qualification_terminal(
                    "crashed", digest, note="final core 异常")
            except Exception:  # noqa: BLE001 - 保留原始异常优先
                pass
            session.release(summary="crashed during final core")
        raise
    session.revoke_generation_grant()
    session.commit_qualification_terminal(
        "completed" if result["verdict"] == "PASS" else "failed",
        digest, note=f"verdict={result['verdict']}")
    session.release(summary=(
        f"R16 qualification finished: verdict={result['verdict']}"))
    return result


__all__ = [
    "R16_RT_FINAL_PROFILE",
    "run_final_qualification_r16",
    "execute_final_core_r16",
]
