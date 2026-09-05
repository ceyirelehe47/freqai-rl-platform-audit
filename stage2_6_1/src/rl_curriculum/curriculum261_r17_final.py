# -*- coding: utf-8 -*-
"""R17 final qualification 的资格执行者(worker)侧。

R17 生命周期重构(F1/F2 修复)后本模块职责:

1. 链会话由外层协调者持有(r17_workflow);qualify 不再自行
   acquire/release——资格窗口(exposure/grant/revoke/terminal)
   的全部 journal 写入归协调者单写者。

2. 本模块是被委派的资格执行者:静态前置检查(六要素/plan/pack/
   sealed attestation/身份合同)→ pipe 注册自身进程实例身份 →
   接收绑定该身份的 token → verify_executor_token → core。

3. worker 不写权威 journal(单写者合同);异常时落盘 traceback
   并写 abort 请求文件,由协调者代写 chain_iteration_aborted。

4. exposure 先于任何正式数据访问:协调者在 spawn worker 之前
   已持久化 chain_exposure_started;derive261_seed 的 R17 守卫
   在无授权时于第一个 seed 派生前拒绝。

领域计算完全复用 execute_final_core_r17(§3.1:不重写生成分布/
统计规则);R17 只注入 _r17 namespace 与治理外壳。
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r17_final_core import (
    execute_final_core_r17,
)
from rl_curriculum.curriculum261_r17_registry import (
    R17_FORMAL_QUALIFICATION_NAMESPACES,
    qualification_r17_unlocked_detail,
    r17_state_root,
    require_r17_iteration_active,
)
from rl_curriculum.curriculum261_r17_plan import (
    _code_identity_r17,
    load_locked_plan_r17,
)

#: R17 rehearsal final profile(rt3_*_r17 工程 namespace;缩小规模;
#: 不消耗正式 R17 namespace/状态;与 r17_cli 的 R17_RT_FINAL_PROFILE
#: 保持一致——CLI 是唯一权威定义,本 re-export 供 preplan/测试使用)。
R17_RT_FINAL_PROFILE: dict[str, Any] = {
    "final_namespace": "rt3_qualification_r17",
    "fit_namespace": "rt3_fit_qualification_r17",
    "independent_namespace": "rt3_c2_independent_main_r17",
    "semantic_namespace": "rt3_semantic_final_r17",
    "supervised_namespace": "rt3_supervised_main_r17",
    "conditioning_fit_namespace": "rt3_fit_main_r17",
    "c13_pairs_per_rung": 2,
    "c2_blocks": 4,
    "semantic_block_count": 8,
    "independent_pairs_per_rung": 2,
    "supervised_model_seeds": (20270135,),
    "supervised_training_config": {"epochs": 2},
}


def _static_identity_checks_r17(
        plan: dict[str, Any], pack: dict[str, Any],
        out_dir: Path, vendor_dir: Path | None) -> None:
    """不需要 final seed 的静态身份检查(exposure 之前;fail closed)。

    复用 R15 的领域检查实现;代码身份换成 R17 模块清单。
    """
    from rl_curriculum.curriculum261_final import (
        _frozen_contract_integrity,
        _upstream_integrity,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r17_dependencies import (
        verify_r17_code_freeze,
    )

    frozen = _frozen_contract_integrity()
    vendor_dir = vendor_dir or _vendor_dir_default()
    upstream = _upstream_integrity(vendor_dir)
    upstream_ok = (upstream["sha"] == plan["vendor_pin"]
                   and upstream["clean"])
    v2_digest = preprocessing_v2_contract_digest()
    contract_ok = (v2_digest
                   == plan["preprocessing_v2"]["contract_digest"])
    code_ok = (plan["code_identity"] == _code_identity_r17())
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
            "R17 final 静态身份检查失败(frozen contracts/vendor/V2 "
            "digest/code identity/cue semantic contract);在 exposure "
            "之前 fail closed——本轮 qualification_r17 未消耗:"
            f" frozen={frozen['pass']} vendor={upstream_ok} "
            f"v2={contract_ok} code={code_ok} cue={cue_contract_ok}")
    freeze = verify_r17_code_freeze(Path(out_dir))
    if not freeze["pass"]:
        raise RuntimeError(
            f"R17 code freeze 校验失败(正式数据开始后源码漂移;"
            f"§6/§21 永久结束):{freeze}")
    plan_freeze = (plan.get("code_freeze") or {}).get("code_freeze_sha")
    if plan_freeze and freeze.get("code_freeze_sha") != plan_freeze:
        raise RuntimeError("plan 绑定的 code freeze SHA 与冻结清单不一致")


def _vendor_dir_default() -> Path:
    from rl_curriculum.curriculum261_r6_preflight import vendor_dir_default

    return vendor_dir_default()


def run_final_qualification_r17(out_dir: Path,
                                vendor_dir: Path | None = None,
                                *,
                                rehearsal_profile: dict[str, Any] | None
                                = None,
                                control_write_fd: int | None = None,
                                control_read_fd: int | None = None,
                                ) -> dict[str, Any]:
    """执行一次性 R17 final qualification 的资格执行者侧(worker)。

    R17 生命周期(F1 修复):链会话由外层协调者持有;本函数是
    **被委派的资格执行者**,经受控 pipe 协议取得绑定本进程实例
    身份的生成授权后执行 core:

        协调者:exposure 持久化 → spawn(worker) → 读取 worker
        身份 → issue_grant(delegate=worker 身份) → pipe 下发
        token → 等待 worker 结束 → revoke → terminal → 后续步骤

    worker:静态前置检查 → pipe 注册自身实例身份 → pipe 等待
    token → verify_executor_token → execute_final_core_r17 →
    退出(rc=verdict)。worker 不写权威 journal(单写者合同);
    异常时落盘 traceback 并写 abort 请求文件,由协调者代写
    chain_iteration_aborted。

    rehearsal_profile 非 None 时执行 round-trip rehearsal final
    (rt3_*_r17 工程 namespace + 缩小规模;隔离状态根;委派协议
    与正式路径同代码,唯一差异来自预注册 profile 参数)。
    """
    out_dir = Path(out_dir)
    rt = rehearsal_profile is not None
    require_r17_iteration_active()
    plan, digest = load_locked_plan_r17()
    if (plan.get("robustness_gate") or {}).get("pass") is not True:
        raise RuntimeError(
            "R17 plan 的 robustness_gate.pass != true——final "
            "qualification fail closed")
    from rl_curriculum.curriculum261_r17_param_pack import load_selected_pack

    pack = load_selected_pack(r17_state_root())
    if pack["digest"] != plan["parameter_pack"]["digest"]:
        raise RuntimeError(
            "plan 绑定的 parameter pack digest 与 artifact 不一致"
            "(fail closed)")
    from rl_curriculum.curriculum261_r17_preflight import (
        verify_sealed_attestation,
    )

    attestation = verify_sealed_attestation(Path(out_dir))
    if not attestation["pass"]:
        raise RuntimeError(
            f"sealed final preflight attestation 验证失败:"
            f"{attestation}(final 前置条件;fail closed)")
    if attestation["attestation"]["plan_digest"] != digest:
        raise RuntimeError("attestation 绑定的 plan digest 与当前 plan 不符")
    if not rt:
        # 静态资格(六要素)只回答"可以申请开始";执行权由委派
        # token 的实例身份验证承担(§WP2)。
        if not qualification_r17_unlocked_detail()["unlocked"]:
            raise RuntimeError(
                "R17 静态资格(六要素)未解锁;fail closed")
    _static_identity_checks_r17(plan, pack, out_dir, vendor_dir)

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
            profile_name="formal_final_r17",
            final_namespace="qualification_r17",
            fit_namespace="preprocess_fit_qualification_r17",
            c13_pairs_per_rung=10,
            c2_blocks=int(plan["final_sample_counts"][
                "c2_matched_blocks"]),
            semantic_block_count=160,
            independent_pairs_per_rung=20,
            independent_namespace="c2_independent_qualification_r17",
            semantic_namespace_override="cue_semantic_qualification_r17",
            fresh_seed_final_namespace="qualification_r17",
            fresh_seed_holdout_namespace="fresh_holdout_r17")

    # ---- 受控委派协议:注册身份 → 等待绑定本实例的 token ---------
    grant_namespaces = (
        tuple(rehearsal_profile["grant_namespaces"])
        if rt and rehearsal_profile.get("grant_namespaces")
        else R17_FORMAL_QUALIFICATION_NAMESPACES)
    if control_write_fd is not None and control_read_fd is not None:
        _worker_delegate(control_write_fd, control_read_fd,
                         grant_namespaces)
    elif not rt:
        raise RuntimeError(
            "正式 qualification 必须经协调者受控委派启动"
            "(control pipe 缺失;直接调用 worker 入口无法获得"
            "绑定本进程实例的生成授权;§WP1/§WP2)")

    result = execute_final_core_r17(
        out_dir, plan, pack, digest=digest, started=started,
        **core_kwargs)
    return result


def _worker_delegate(write_fd: int, read_fd: int,
                     grant_namespaces: tuple[str, ...]) -> None:
    """pipe 委派协议 worker 侧:注册身份 → 接收并激活 token。

    消息均为单行 JSON(write 由 worker 发起;read 阻塞等待协调者
    下发)。token 只在内存+env;identity 由 /proc 事实构成——
    fork/spawn 出身的进程身份不同,无法冒充。
    """
    import os as _os

    from rl_curriculum.curriculum261_r17_execgov import (
        R17_EXECUTOR_TOKEN_ENV, executor_identity, verify_executor_token,
    )

    ident = executor_identity()
    msg = json.dumps({"kind": "executor_identity", "identity": ident,
                      "namespaces": list(grant_namespaces)})
    with open(write_fd, "w", encoding="utf-8") as fh:
        fh.write(msg + "\n")
        fh.flush()
    with open(read_fd, "r", encoding="utf-8") as fh:
        line = fh.readline()
    grant_msg = json.loads(line)
    if grant_msg.get("kind") != "grant_token":
        raise RuntimeError(
            f"协调者下发消息类型异常:{grant_msg.get('kind')!r}"
            "(期望 grant_token;委派协议 fail closed)")
    token = grant_msg["token"]
    _os.environ[R17_EXECUTOR_TOKEN_ENV] = token
    verify_executor_token(token, grant_msg.get("probe_namespace",
                                               grant_namespaces[0]))


__all__ = [
    "R17_RT_FINAL_PROFILE",
    "run_final_qualification_r17",
    "execute_final_core_r17",
    "_worker_delegate",
]
