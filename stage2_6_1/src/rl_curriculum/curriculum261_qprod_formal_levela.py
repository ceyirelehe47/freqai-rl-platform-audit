"""QProd 正式 Level A 启动适配(RouteC_FormalLaunch_Preparation_v1)。

正式 Level A = QProd 正式上下文/许可/会话/两阶段计划 + 权威
R17 17 步链的真实业务入口(curriculum261_r17_cli chain-run /
execute_workflow_chain_r17)。本模块:

- 构建正式 Level A 数据前 run-plan(绑定入口/门集/真实预算/
  停止边界/smoke 授权口径);
- 只读预检(部署配置/根形态/计划身份/链排程/校准后依赖产出
  映射/状态新鲜度;重复预检内容身份不变);
- launch:全部校验(部署配置、批准原件、正式许可、admission
  在场、状态新鲜、停止边界一致性)在任何受控副作用之前完成,
  失败即拒(零写入);通过后按序创建根→冻结计划→消费许可→
  取会话→派发权威链子进程;``sentinel_before_chain=True`` 在
  权威链执行器调用边界前记录真实解析产物后停止(诚实中断,
  零步骤执行)。

不回落旧 R17/R19 状态:链子进程的 R17 部署绑定被显式指向本
迭代正式 state root(受信任部署配置来源),旧部署根零写。
本模块不实现任何生成/fit/optimizer 叶;真实执行仍 NOT_RUN,
直至用户批准 + formal_ready 部署 + admission/批准/许可齐备。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_qprod_context import (
    QProdContextError, QProdRunSession, harden_root,
)
from rl_curriculum.curriculum261_qprod_plan import (
    QPROD_RESEARCH_PLAN_FORMAT, freeze_research_plan,
    research_plan_digest, research_plan_structure_problems,
)
from rl_curriculum.curriculum261_qprod_permit import consume_permit
from rl_curriculum.curriculum261_qprod_formal_budget import (
    authorization_face as _budget_face,
    build_budget_items as _budget_items,
)
from rl_curriculum.curriculum261_qprod_formal import (
    QPROD_FORMAL_LEVEL_A_ITERATION_ID,
    _read_formal_roots, _utc_now, build_formal_context,
    load_formal_approval, preflight_content_identity,
    validate_formal_approval, validate_formal_permit,
)
from rl_curriculum.curriculum261_qaf_attempt import (
    QAF_ATTEMPT_IDS, qaf_attempt_family, qaf_iteration_id_for_attempt,
)

#: 允许的停止边界:qualify(第 13 步后停;smoke/full-cold/
#: report-read/verify-formal-logs 标 NOT_RUN)或完整链
#: verify-formal-logs(含资格后 256 步 smoke ⇒ 须显式授权模型更新)。
QPROD_FORMAL_STOP_CHOICES = ("qualify", "verify-formal-logs")

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")

#: 正式 Level A 输入范围 = QAF 尝试全新数据面命名空间族
# (RouteC_FormalLaunch_Preparation_v1 修复轮 R1/F06:外层迭代目录
# 不进入 seed 派生;沿用 R17/R18/R19 旧正式名会在新根下重复消费
# 旧 seed 空间。QAF 族为唯一 A 数据面;链内机械面(determinism/
# design/cue-audit/audit/smoke 工程命名空间)按 R18/R19 前例保持
# 冻结工程身份,不属用户预注册数据范围)。
def formal_level_a_input_scope(
        formal_attempt: str = "qaf_v1") -> tuple[str, ...]:
    from rl_curriculum.curriculum261_qaf_attempt import (
        qaf_input_scope_for_attempt,
    )
    return tuple(qaf_input_scope_for_attempt(formal_attempt))


def build_formal_level_a_plan(
        *, code_freeze_sha: str,
        code_identity: dict[str, Any],
        authorized_stop_after: str,
        model_update_authorized: bool,
        formal_attempt: str = "qaf_v1") -> dict[str, Any]:
    """正式 Level A 数据前 run-plan 载荷(冻结前可算 digest)。

    预算面由 curriculum261_qprod_formal_budget 授权面给出
    (R2 修复:逐类计量;R3 修复 A-1:授权语义统一)。

    两类 PPO 更新明确分开(R3 修复 A-1,消除「A1 无模型更新
    但链内嵌 PPO」的矛盾):
    1. **内嵌工程自检 smoke**(preflight-static 第 10 步,链固
       有,R12 冻结):任何 A1/A2 批准都**显式包含**该内嵌
       PPO plumbing smoke(1 次 learn、rollout 256、optimizer.
       step ≤40、验证 ≤50、check_env ≤10、save 1+load 1;
       输入身份=该 attempt 族的 ppo_smoke namespace)——机器可读字段
       run_scope.embedded_preflight_smoke;
    2. **资格后验收 smoke**(第 14 步,条件许可):仅
       authorized_stop_after=verify-formal-logs(A2)且
       model_update_authorized=True 时进入;A1 停在 qualify,
       14-17 步 NOT_RUN(不再宣称「PPO 面恒 0」——内嵌自检
       smoke 的 PPO 计量按第 1 类如实入面)。
    正式教学与两者均分开,独立未授权。监督 MLP 拟合在 A1/A2
    都发生,按预算面逐类批准。
    """
    if authorized_stop_after not in QPROD_FORMAL_STOP_CHOICES:
        raise QProdContextError(
            f"停止边界 {authorized_stop_after!r} 非法(合法: "
            f"{QPROD_FORMAL_STOP_CHOICES})")
    if authorized_stop_after == "verify-formal-logs" \
            and not model_update_authorized:
        raise QProdContextError(
            "完整链含第 14 步资格后验收 smoke(1 次 learn、256 "
            "环境步、optimizer.step ≤40):未批准该步不得请求完整"
            "链(停在 qualify)")
    if authorized_stop_after == "qualify" and model_update_authorized:
        raise QProdContextError(
            "model_update_authorized=True(第 14 步资格后验收 "
            "smoke 授权)而停止边界=qualify:授权与停止边界不一致"
            "(批准口径必须二者一致;A1 停 qualify 即不授权第 14 步)")
    budget_face = _budget_face(stop_after=authorized_stop_after)
    fam = qaf_attempt_family(formal_attempt)
    ppo_smoke_ns = (fam.ppo_smoke if fam is not None
                    else "ppo_smoke_r17")
    budget_items = _budget_items(attempt_family=fam)
    payload = {
        "format": QPROD_RESEARCH_PLAN_FORMAT,
        "level": "level_a",
        "iteration_id": qaf_iteration_id_for_attempt(formal_attempt),
        "profile": "formal",
        "code_freeze_sha": code_freeze_sha,
        "run_scope": {
            "entry": (
                "qprod_formal_level_a_entry launch → "
                "rl_curriculum.curriculum261_r17_cli chain-run"
                "(受信任部署;PYTHONPATH=部署 src)"),
            "gate_set": (
                "r17 权威 17 步(prerequisites/postcondition 语义:"
                "smoke 仅 qualify final PASS 后;full-cold 仅 smoke "
                "PASS 后)+ qualification one_shot exposure"),
            "budget": budget_face,
            "budget_items": budget_items,
            "exposure_policy": (
                "one_shot_window(r17 execgov qualification 委派协议;"
                "不可重开)"),
            "authorized_stop_after": authorized_stop_after,
            "embedded_preflight_smoke": {
                "authorized": True,
                "step": "preflight-static",
                "description": (
                    "链固有内嵌工程自检 smoke(R12 冻结):任何 "
                    "A1/A2 批准显式包含该 PPO plumbing 自检;输入"
                    f"身份 {ppo_smoke_ns}(R3 修复 A-1:授权表示"
                    "与真实可达更新路径一致)"),
                "ppo": {
                    "learn_calls": 1,
                    "rollout_env_steps": 256,
                    "optimizer_steps_upper": 40,
                    "validation_env_steps_upper": 50,
                    "check_env_interactions_upper": 10,
                    "model_save_load_pairs": 1,
                },
            },
            "attempt_identity": {
                "attempt": formal_attempt,
                "audit_bank": (fam.audit_bank if fam is not None
                               else "preplan_smoke_r17"),
                "preplan_smoke": (fam.preplan_smoke
                                  if fam is not None
                                  else "preplan_smoke_r17"),
                "ppo_smoke": ppo_smoke_ns,
                "source": (
                    "qaf_attempt_family 解析;与 r17_cli cmd_audit/"
                    "cmd_preplan_smoke/cmd_preflight_static/smoke "
                    "的链内解析同源(RD06:授权文本与真实可达消费"
                    "身份一致)"),
            },
        },
        "rules": {
            "gate_semantics_ref": (
                "curriculum261_r17_workflow.R17_WORKFLOW_STEPS + "
                "curriculum261_r17_final(资格判定);qualification_"
                "plan 由链第 11 步 lock-plan 在校准后 create-only "
                "冻结,不得事前捏造"),
            "model_update_authorized": model_update_authorized,
            "post_qualification_smoke_authorized":
                model_update_authorized,
            "smoke_policy": (
                "两类 PPO 更新分开(R3 修复 A-1):①内嵌工程自检"
                " smoke=preflight-static 链固有部分,A1/A2 批准均"
                "显式包含(1 次 learn、rollout 256、optimizer.step "
                "上界 40、验证 ≤50、check_env ≤10、save 1+load 1;"
                f"输入身份 {ppo_smoke_ns};机器可读字段 run_scope."
                "embedded_preflight_smoke);②第 14 步资格后验收 "
                "smoke=qualify final PASS 后链内验收的条件许可(同"
                "样逐类计量;仅 A2[stop=verify-formal-logs 且 "
                "model_update_authorized=True]授权),与正式教学分开;"
                "A1 停在 qualify,14-17 步 NOT_RUN——A1 不再宣称"
                "「PPO 面恒 0」,第 ① 类计量已如实入授权面"),
        },
        "quota": {
            # 通用许可配额 schema(4 键;validate_permit 强制正整数)。
            # A 的量纲说明:链不按坐标执行,前两键按链整体 episode
            # 上界声明;逐类分账(fit/MC/optimizer/bootstrap)在
            # run_scope.budget,不与本 4 键混算。
            "max_leaf_calls_per_coordinate":
                budget_face["authorization_cap_generation_episodes"],
            "max_successful_episodes_total":
                budget_face["authorization_cap_generation_episodes"],
            "mc_events_per_coordinate":
                budget_face["mc_events_total"],
            "max_native_executions": 1,
            "v2_preprocessor_fits":
                budget_face["v2_preprocessor_fits"],
            "supervised_mlp_fits":
                budget_face["supervised_mlp_fits"],
            "bootstrap_resamples_upper":
                budget_face["bootstrap_resamples_upper"],
            "ppo_learn_calls": budget_face["ppo_learn_calls"],
            "ppo_rollout_env_steps":
                budget_face["ppo_rollout_env_steps"],
            "ppo_optimizer_steps_upper":
                budget_face["ppo_optimizer_steps_upper"],
            "ppo_validation_env_steps":
                budget_face["ppo_validation_env_steps"],
            "model_save_load_pairs":
                budget_face["model_save_load_pairs"],
        },
        "code_identity": dict(code_identity),
        "stop_mode": "collect_all_k",
        "engineering_only": False,
    }
    problems = research_plan_structure_problems(payload)
    if problems:
        raise QProdContextError(
            f"正式 Level A 计划载荷结构问题(不应发生): {problems}")
    return payload


# ------------------------------------------------ 只读预检 ----------
def preflight_formal_level_a(
        deploy_root: Path | str, *, code_freeze_sha: str,
        code_identity: dict[str, Any],
        authorized_stop_after: str = "qualify",
        formal_attempt: str = "qaf_v1") -> dict[str, Any]:
    """Level A 正式预检(零生成、零写入;重复预检身份稳定)。"""
    from rl_curriculum.curriculum261_r17_admission import deploy_root_of
    from rl_curriculum.curriculum261_r17_workflow import (
        R17_WORKFLOW_STEPS, r17_producer_of_artifact,
        r17_workflow_step_names,
    )

    findings: list[str] = []
    deployment_ok = True
    art = state = authority = None
    try:
        art, state, authority = _read_formal_roots(
            Path(deploy_root), level="level_a",
            iteration_id=qaf_iteration_id_for_attempt(formal_attempt))
    except QProdContextError as exc:
        deployment_ok = False
        findings.append(f"deployment: {exc}")

    payload = build_formal_level_a_plan(
        code_freeze_sha=code_freeze_sha,
        code_identity=code_identity,
        authorized_stop_after=authorized_stop_after,
        model_update_authorized=(
            authorized_stop_after == "verify-formal-logs"),
        formal_attempt=formal_attempt)
    digest = research_plan_digest(payload)
    budget_face = _budget_face(stop_after=authorized_stop_after)
    budget_items = _budget_items(
        attempt_family=qaf_attempt_family(formal_attempt))
    problems = research_plan_structure_problems(payload)
    if problems:
        findings.append(f"plan_structure: {problems}")

    # 根形态:r17 admission 签发/消费按部署尾形解析
    # (state_root 尾部 artifacts/route_c_stage2_6_1_repair{17,18,19}/
    # state;admission 文件位于其上三级目录)。
    admission_dir_ok = False
    admission_present = False
    if state is not None:
        admission_dir = deploy_root_of(state)
        admission_dir_ok = admission_dir is not None
        if not admission_dir_ok:
            findings.append(
                "state_root 形态不满足 r17 admission 部署尾形"
                "(artifacts/route_c_stage2_6_1_repair{17,18,19}/state)")
        else:
            admission_present = (
                admission_dir / ".r17_formal_admission.json").is_file()

    # 校准后依赖产出映射:qualification plan 与校准产物此时必须
    # 不存在——它们由链内步骤产生,不得事前捏造或拿旧件补位。
    produced_by: dict[str, str] = {}
    stale: list[str] = []
    if state is not None:
        for name, producer in (
                ("qualification_plan_r17.json", "lock-plan(第 11 步,"
                 "校准后 create-only 冻结)"),
                ("qprod_research_plan.json", "launch 受控写阶段"
                 "(create-only 冻结)"),
        ):
            produced_by[name] = producer
            if (state / name).is_file():
                stale.append(f"state_root 已存在 {name}")
    if state is not None and (state / "r17_execution_journal.jsonl"
                              ).is_file():
        stale.append("state_root 已存在 r17_execution_journal.jsonl")
    if art is not None:
        for name in ("r17_workflow_plan_formal.json",
                     "r17_bootstrap_accepted.json"):
            if (art / name).is_file():
                stale.append(f"artifact_root 已存在 {name}")
    if stale:
        findings.append(
            f"正式根非新鲜(旧状态/伪 PASS 补位拒绝): {stale}")

    # 链排程:权威 17 步名序 + 每步产物生产者(此产物由该步产生)。
    steps = []
    for s in R17_WORKFLOW_STEPS:
        steps.append({
            "name": s["name"],
            "produces": list(s.get("output_artifacts") or []),
            "data_class": s.get("data_class", ""),
            "postcondition": s.get("postcondition", ""),
        })
    producers = r17_producer_of_artifact()
    not_run_after_stop = [
        n for n in r17_workflow_step_names()
        if authorized_stop_after == "qualify" and n in (
            "smoke", "full-cold", "report-read", "verify-formal-logs")
    ]
    report = {
        "format": "cur261-qprod-formal-preflight-v1",
        "level": "level_a",
        "iteration_id": qaf_iteration_id_for_attempt(formal_attempt),
        "deployment_ok": deployment_ok,
        "deployment_note": (
            "正式执行未授权是预期状态:生产部署配置不存在/非 "
            "formal_ready 时 deployment_ok=false,预检如实记录;"
            "launch 恒拒" if not deployment_ok else
            "受信任部署配置 formal_ready(测试域沙盒)"),
        "admission_shape_ok": admission_dir_ok,
        "admission_present": admission_present,
        "admission_note": (
            "provenance-lock→Commit A→部署同步→批准绑定/签发→"
            "执行:admission 原件在 launch 前由 r17_admission_issue "
            "对最终 Commit A 签发;此处只报在场,不代签"),
        "plan_digest": digest,
        "plan_structure_problems": problems,
        "chain_steps": steps,
        "artifact_producers": {
            k: producers[k] for k in sorted(producers)},
        "calibration_dependents_produced_by": produced_by,
        "stale_state_findings": stale,
        "authorized_stop_after": authorized_stop_after,
        "steps_not_run_under_stop": not_run_after_stop,
        "budget": budget_face,
        "budget_items": budget_items,
        "findings": findings,
        "business_leaf_calls": 0,
        "status": "PREPARED_PENDING_USER_APPROVAL" if (
            deployment_ok and not findings) else "FINDINGS_PRESENT",
        "generated_utc": _utc_now(),
    }
    report["content_identity"] = preflight_content_identity(report)
    return report


# ------------------------------------------------ launch ----------
class FormalLaunchRefused(QProdContextError):
    """launch 门禁拒绝(发生在任何受控副作用之前;零业务叶调用)。"""


def _child_argv_and_env(
        *, project_dir: Path, art: Path, state: Path,
        freeze_sha: str, authorized_stop_after: str,
        formal_attempt: str = "qaf_v1",
) -> tuple[list[str], dict[str, str]]:
    """权威链子进程 argv/env(真实业务入口;显式构造,不继承重定向)。

    - 完整链:直接用权威 CLI 入口 chain-run(与 r17_formal_chain.sh
      同一编排入口);
    - 停止边界=qualify:用本模块 _chain-bounded 入口(同一
      admission 闸门/会话/权威执行器,步骤截到批准前缀并以
      verify-formal-logs --stopped-at qualify 诚实收口);
    - R17 部署绑定显式指向本迭代正式 state root;剥除一切
      R17/QPROD 根重定向环境变量(旧状态零写)。
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(project_dir) / "src")
    env["CURRICULUM261_R17_DEPLOYED_STATE_ROOT"] = str(state)
    for var in ("CURRICULUM261_R17_STATE_ROOT",
                "CURRICULUM261_QPROD_ART_ROOT",
                "CURRICULUM261_QPROD_STATE_ROOT"):
        env.pop(var, None)
    if authorized_stop_after == "verify-formal-logs":
        argv = [sys.executable, "-m",
                "rl_curriculum.curriculum261_r17_cli", "chain-run",
                "--out-dir", str(art), "--freeze-sha", freeze_sha,
                "--formal-namespace-attempt", formal_attempt]
    else:
        argv = [sys.executable, "-m",
                "rl_curriculum.curriculum261_qprod_formal_levela",
                "_chain-bounded", "--out-dir", str(art),
                "--freeze-sha", freeze_sha,
                "--stop-after", authorized_stop_after,
                "--formal-namespace-attempt", formal_attempt]
    return argv, env


def launch_formal_level_a(
        *, deploy_root: Path | str, project_dir: Path | str,
        code_freeze_sha: str, code_identity: dict[str, Any],
        authorized_stop_after: str, model_update_authorized: bool,
        sentinel_before_chain: bool = False,
        child_timeout_s: int | None = None,
        formal_attempt: str = "qaf_v1") -> dict[str, Any]:
    """正式 Level A 启动(门禁→受控写→权威链派发/哨兵停止)。

    门禁(全部先于任何受控副作用;失败抛 FormalLaunchRefused,
    零写入、零业务叶调用):部署配置 formal_ready + 根解析 →
    计划载荷一致且 digest 稳定 → 批准原件逐项绑定 → 正式许可
    校验(计划/批准绑定)→ 冻结 SHA 为真实 commit → admission
    在场且绑定同候选 → 正式根新鲜 → 停止边界与模型更新授权一致。

    受控写(有序):根创建 → run-plan create-only 冻结 → 许可
    一次性消费 → 会话获取(+许可消费记账)。此后哨兵停止或
    派发权威链子进程并按真实结果记终态。
    """
    deploy_root = Path(deploy_root).resolve()
    project_dir = Path(project_dir).resolve()
    authorized_stop_after = str(authorized_stop_after)

    # ---- 门禁(只读) --------------------------------------------
    def _refuse(reason: str) -> FormalLaunchRefused:
        return FormalLaunchRefused(
            f"正式 Level A launch 拒绝(受控副作用前): {reason}")

    if not _SHA40_RE.match(code_freeze_sha or ""):
        raise _refuse(
            f"code_freeze_sha {code_freeze_sha!r} 不是真实 commit id"
            f"(正式链绑定最终 Commit A;草案不得用伪 SHA 启动)")
    try:
        payload = build_formal_level_a_plan(
            code_freeze_sha=code_freeze_sha,
            code_identity=code_identity,
            authorized_stop_after=authorized_stop_after,
            model_update_authorized=model_update_authorized,
            formal_attempt=formal_attempt)
        digest = research_plan_digest(payload)
        _iter = qaf_iteration_id_for_attempt(formal_attempt)
        art, state, authority = _read_formal_roots(
            deploy_root, level="level_a", iteration_id=_iter)
        approval = load_formal_approval(
            authority, level="level_a", iteration_id=_iter)
        validate_formal_approval(
            approval, level="level_a", iteration_id=_iter,
            artifact_root=art, state_root=state,
            authority_dir=authority,
            code_freeze_sha=code_freeze_sha,
            research_plan_digest=digest,
            namespaces=formal_level_a_input_scope(formal_attempt),
            coordinate_ids=[],
            quota=payload["quota"],
            authorized_stop_after=authorized_stop_after,
            model_update_authorized=model_update_authorized)
        ctx = build_formal_context(
            deploy_root, level="level_a", iteration_id=_iter,
            code_freeze_sha=code_freeze_sha,
            research_plan_digest=digest,
            approval_digest=approval["approval_digest"])
        permit = validate_formal_permit(ctx.permit_path, context=ctx)
    except QProdContextError as exc:
        # 门禁阶段全部只读:任何校验失败都以统一拒绝面暴露,
        # 零写入、零业务叶调用(不接受"先写后验")。
        raise _refuse(str(exc)) from exc
    from rl_curriculum.curriculum261_r17_admission import (
        deploy_root_of,
    )
    admission_dir = deploy_root_of(state)
    admission_file = (admission_dir / ".r17_formal_admission.json"
                      if admission_dir else None)
    if admission_file is None or not admission_file.is_file():
        raise _refuse(
            "r17 formal admission 原件缺失(provenance-lock→Commit A"
            "→admission 签发是执行前置;不得绕过签发链)")
    try:
        admission = json.loads(
            admission_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _refuse(f"admission 原件不可解析: {exc}") from exc
    if admission.get("commit_a_sha") != code_freeze_sha:
        raise _refuse(
            f"admission 绑定候选 {admission.get('commit_a_sha')!r} !="
            f" 启动候选 {code_freeze_sha!r}(错候选拒绝)")
    # 状态新鲜(重入/旧状态拒绝)
    for root, names in (
            (state, ("qprod_run_journal.jsonl", "qprod_research_plan"
                     ".json", "r17_execution_journal.jsonl")),
            (art, ("r17_workflow_plan_formal.json",
                   "r17_bootstrap_accepted.json"))):
        for name in names:
            if (root / name).is_file():
                raise _refuse(
                    f"正式根非新鲜: {(root / name)} 已存在(重复/终态"
                    f"重入或旧状态残留拒绝;一轮只有一次被接受的"
                    f"运行)")

    # ---- 签发后目标漂移重查(A2-R2 §A3) -------------------------
    # 消费许可之前按钉死 sha 重查实际目标两件字节(签发后更换/
    # 漂移目标必须在此被捕获,而不是链步 1 消费一次性资格后失败;
    # 与签发前守卫同一绑定)。
    from rl_curriculum.curriculum261_qaf_provenance_guard import (
        inspect_target as _guard_inspect_target,
    )
    _target_recheck = _guard_inspect_target(art)
    if not _target_recheck["ready"] or _target_recheck.get(
            "foreign_objects"):
        raise _refuse(
            "签发后 provenance 目标漂移重查失败(实际 A artifact 根 "
            f"{art} 与钉死字节不一致或有异物 {_target_recheck};"
            "不消费许可,受控停下先核实)")
    if not (Path(project_dir) / "stage2_6_1_runner").is_dir():
        raise _refuse(
            f"project_dir {project_dir} 缺 stage2_6_1_runner(链子"
            f"进程入口不可达;受控停下)")

    # ---- 受控写(有序) ------------------------------------------
    harden_root(art, label="artifact_root", create=True)
    harden_root(state, label="state_root", create=True)
    freeze_research_plan(state, payload)
    consume_permit(ctx.permit_path, context=ctx)
    session = QProdRunSession(
        state, level="level_a",
        iteration_id=qaf_iteration_id_for_attempt(formal_attempt))
    session.acquire({
        "entry": "qprod_formal_level_a_entry.launch",
        "deploy_root": str(deploy_root),
        "code_freeze_sha": code_freeze_sha,
        "research_plan_digest": digest,
        "authorized_stop_after": authorized_stop_after,
        "model_update_authorized": model_update_authorized,
        "sentinel_before_chain": sentinel_before_chain,
    })
    session.record_permit_consumed(permit["permit_id"])

    argv, env = _child_argv_and_env(
        project_dir=project_dir, art=art, state=state,
        freeze_sha=code_freeze_sha,
        authorized_stop_after=authorized_stop_after,
        formal_attempt=formal_attempt)
    handoff = {
        "format": "cur261-qprod-formal-launch-handoff-v1",
        "level": "level_a",
        "iteration_id": qaf_iteration_id_for_attempt(formal_attempt),
        "business_entry": argv[:4],
        "argv": argv,
        "cwd": str(project_dir),
        "env_identity": {
            "PYTHONPATH": env.get("PYTHONPATH"),
            "CURRICULUM261_R17_DEPLOYED_STATE_ROOT": env.get(
                "CURRICULUM261_R17_DEPLOYED_STATE_ROOT"),
            "stripped": ["CURRICULUM261_R17_STATE_ROOT",
                         "CURRICULUM261_QPROD_ART_ROOT",
                         "CURRICULUM261_QPROD_STATE_ROOT"],
        },
        "research_plan_digest": digest,
        "authorized_stop_after": authorized_stop_after,
    }
    if sentinel_before_chain:
        handoff["sentinel"] = {
            "stopped_before": "execute_workflow_chain_r17 调用",
            "steps_executed": 0,
            "business_leaf_calls": 0,
            "note": (
                "边界哨兵:门禁/受控写真实执行后,在权威链执行器"
                "调用前停止;不冒充任何步骤执行或资格判定;本轮"
                "资格/教学 NOT_RUN"),
        }
        (art / "qprod_formal_launch_handoff.json").write_text(
            json.dumps(handoff, ensure_ascii=False, indent=2),
            encoding="utf-8")
        session.record_interruption(
            "sentinel_stop_before_chain_executor",
            attribution="preflight boundary verification")
        session.release()
        return {
            "ok": False, "sentinel_stopped": True,
            "handoff": handoff, "chain_result": None,
            "refusal": None,
        }

    (art / "qprod_formal_launch_handoff.json").write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2),
        encoding="utf-8")
    try:
        proc = subprocess.run(
            argv, cwd=str(project_dir), env=env,
            capture_output=True, text=True,
            timeout=child_timeout_s)
        chain_rc = proc.returncode
        chain_stdout_tail = (proc.stdout or "")[-4000:]
    except subprocess.TimeoutExpired as exc:
        chain_rc = -1
        chain_stdout_tail = f"child timeout: {exc}"
    chain_result_path = art / "r17_chain_result.json"
    chain_result = None
    if chain_result_path.is_file():
        try:
            chain_result = json.loads(
                chain_result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            chain_result = None
    verdict = "PASS" if (
        chain_rc == 0 and chain_result
        and chain_result.get("ok") is True) else (
        "STOPPED_AUTHORIZED" if (
            chain_rc == 0 and authorized_stop_after == "qualify")
        else "FAIL")
    session.record_terminal(
        status="completed" if chain_rc == 0 else "failed",
        verdict=verdict, plan_digest=digest,
        detail=(f"chain rc={chain_rc}; stop_after="
                f"{authorized_stop_after}; stdout_tail="
                f"{chain_stdout_tail[-800:]}"))
    session.release()
    return {
        "ok": chain_rc == 0, "sentinel_stopped": False,
        "handoff": handoff, "chain_result": chain_result,
        "chain_rc": chain_rc,
        "stdout_tail": chain_stdout_tail,
        "refusal": None,
    }


# ------------------------------------------------ 有界链子进程 ----
def run_bounded_formal_chain(
        *, out_dir: Path, freeze_sha: str, stop_after: str,
        formal_attempt: str | None = None) -> int:
    """停止边界受限的权威链子进程入口(_chain-bounded)。

    与 cmd_chain_run 同一治理顺序:存储天花板 → formal admission
    闸门(消费)→ 唯一会话 → 权威 workflow plan →
    execute_workflow_chain_r17。差异只有排程边界:步骤截到
    authorized 前缀(qualify),随后以 verify-formal-logs
    --stopped-at <bound> 诚实收口;未运行步骤不由任何代码冒充。
    必须以 CURRICULUM261_R17_DEPLOYED_STATE_ROOT 指向本迭代正式
    state root 的干净子进程环境调用(launch 负责构造)。
    """
    from rl_curriculum.curriculum261_r17_cli import (
        R17_STORAGE_CEILING_GB, _storage_used_gb)
    from rl_curriculum.curriculum261_r17_execgov import R17ChainSession
    from rl_curriculum.curriculum261_r17_registry import r17_state_root
    from rl_curriculum.curriculum261_r17_workflow import (
        build_workflow_plan_r17, execute_workflow_chain_r17,
    )

    if stop_after not in QPROD_FORMAL_STOP_CHOICES \
            or stop_after != "qualify":
        print("[_chain-bounded] 仅支持 stop_after=qualify;"
              f" 完整链直接用 chain-run(收到 {stop_after!r})")
        return 2
    used_gb = _storage_used_gb()
    if used_gb < 0 or used_gb >= R17_STORAGE_CEILING_GB:
        print(f"[_chain-bounded] FAIL: WSL 存储已用 {used_gb}GB "
              f"达到/超过天花板(fail closed)")
        return 96
    from rl_curriculum.curriculum261_r17_admission import (
        REJECT_RC, enforce_formal_admission,
    )
    reason = enforce_formal_admission(
        state_root=r17_state_root(), freeze_sha=freeze_sha)
    if reason is not None:
        print(f"[_chain-bounded] FAIL: formal admission 拒绝: {reason}")
        return REJECT_RC
    out_dir = Path(out_dir)
    log_dir = out_dir.parent / (out_dir.name + "_chain_logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / "r17_workflow_plan_formal.json"
    binding = {
        "mode": "formal",
        "freeze_sha": freeze_sha,
        "state_root": str(r17_state_root()),
        "out_dir": str(out_dir),
        "argv": ["qprod_formal_level_a_entry", "_chain-bounded",
                 "--stop-after", stop_after,
                 "--formal-namespace-attempt", str(formal_attempt)],
        "authorized_stop_after": stop_after,
    }
    session = R17ChainSession.acquire(binding)
    try:
        plan = build_workflow_plan_r17(
            profile="formal", out_dir=str(out_dir),
            freeze_sha=freeze_sha,
            formal_attempt=formal_attempt)
        plan = bound_workflow_plan_r17(plan, stop_after)
        # R2 修复 B:动作前预算门——链派发前固化授权面 caps;
        # 被门控命令入口 assert_stage_budget_gate 消费(重放拒/
        # 后继不可达拒/篡改放大拒;工程路径无 gate 不门控)。
        from rl_curriculum.curriculum261_qprod_formal_budget import (
            write_chain_budget_gate,
        )
        write_chain_budget_gate(
            out_dir, stop_after=stop_after,
            steps_in_plan=[
                s["name"] for s in plan["steps"]])
        plan_path.write_text(json.dumps(
            plan, ensure_ascii=False, indent=1), encoding="utf-8")
        chain_result = execute_workflow_chain_r17(
            plan, session=session, log_dir=log_dir)
        result_path = out_dir / "r17_chain_result.json"
        result_path.write_text(json.dumps(
            chain_result, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8")
        if chain_result["ok"]:
            session.release(summary=(
                f"authorized stop after {stop_after};后续步骤 "
                f"{plan['not_run_steps']} NOT_RUN(按批准边界;"
                "不冒充完整 17 步)"))
            return 0
        session.record_iteration_aborted(
            chain_result["failure_reason"][:2000])
        session.release(summary=(
            f"bounded chain failed at {chain_result['failed_step']}"))
        return 1
    except BaseException:
        raise


def bound_workflow_plan_r17(plan: dict[str, Any],
                            stop_after: str) -> dict[str, Any]:
    """把权威 workflow plan 截到批准停止边界(纯函数;可单测)。

    保留 stop_after(含)前缀 + 收口步 verify-formal-logs
    (--stopped-at 改指真实停止步);其后步骤记入 not_run_steps,
    不进入排程,不由任何记录冒充执行。
    """
    from rl_curriculum.curriculum261_r17_workflow import (
        r17_workflow_step_names,
    )

    names = list(r17_workflow_step_names())
    bound_idx = names.index(stop_after)
    kept, verify = [], None
    for step in plan["steps"]:
        if step["name"] == "verify-formal-logs":
            verify = step
            continue
        if names.index(step["name"]) <= bound_idx:
            kept.append(step)
    if verify is not None:
        verify["argv"] = _replace_stopped_at(verify["argv"], stop_after)
        kept.append(verify)
    plan["steps"] = kept
    plan["authorized_stop_after"] = stop_after
    plan["not_run_steps"] = [n for n in names
                             if n not in {s["name"] for s in kept}
                             and n != "verify-formal-logs"]
    return plan

def _replace_stopped_at(argv: list[str], value: str) -> list[str]:
    out = list(argv)
    for i, a in enumerate(out):
        if a == "--stopped-at" and i + 1 < len(out):
            out[i + 1] = value
            return out
    return out + ["--stopped-at", value]


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="qprod-formal-levela",
        description="QProd 正式 Level A 启动适配(内部入口)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    bounded = sub.add_parser(
        "_chain-bounded", help="停止边界受限的权威链子进程入口")
    bounded.add_argument("--out-dir", required=True)
    bounded.add_argument("--freeze-sha", required=True)
    bounded.add_argument("--stop-after", required=True)
    bounded.add_argument("--formal-namespace-attempt", default=None,
                         choices=QAF_ATTEMPT_IDS)
    ns = ap.parse_args(argv)
    if ns.cmd == "_chain-bounded":
        return run_bounded_formal_chain(
            out_dir=Path(ns.out_dir), freeze_sha=ns.freeze_sha,
            stop_after=ns.stop_after,
            formal_attempt=getattr(
                ns, "formal_namespace_attempt", None))
    return 2
if __name__ == "__main__":
    raise SystemExit(main())
