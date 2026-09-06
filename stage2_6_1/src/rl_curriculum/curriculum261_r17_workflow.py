# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R17 权威工作流(AuthoritativeWorkflow-v1 继承)。

R17 设计 §9.1:继续由唯一 authoritative workflow 派生 rehearsal、
formal runner、expected sequence/multiset、日志检查和 stopped-at
prefix;producer/consumer 依赖在执行前校验。本模块从 R15 workflow
继承全部结构合同(17 步、校验规则、profile 差异集),差异仅:

- CLI 目标换 curriculum261_r17_cli(qualify 走 R17 所有权生命周期;
  fail-closure 走 R17 阶段精确封口);
- artifact 文件名换成 R17 状态根布局(design plan/param pack/
  qualification plan/code freeze/report values/manifest);
- bootstrap 边界显式化(§5.4):chain 执行器在被接受为正式会话后
  立即写启动接受证据(bootstrap_accepted.json,不依赖任何 workflow
  步骤成功);interpreter/import/环境失败发生在 workflow 之前的
  事实由外层入口的冻结捕获路径记录(r17_launch_evidence.json),
  二者分开,避免"第二次被拒绝的请求写入正在运行的正式 manifest"。

graph digest 前缀 r17wg-(与 R15 的 r15wg- 区分;payload 含
iteration=r17)。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r15_workflow import (
    _env_identity,
    _postcondition_ok,
    _sha256_file,
    _step,
)

R17_WORKFLOW_VERSION = "AuthoritativeWorkflow-v1"

#: rehearsal 专属链外尾步(继承 R15 语义)。
R17_REHEARSAL_ONLY_TAIL: tuple[str, ...] = ("fail-closure-rehearsal",)

#: CLI 入口(execute_workflow_chain 的 subprocess 目标)。
R17_WORKFLOW_CLI_MODULE = "rl_curriculum.curriculum261_r17_cli"

#: bootstrap 启动接受证据(chain 执行器写;§5.4 会话接受边界)。
R17_BOOTSTRAP_ACCEPTED_NAME = "r17_bootstrap_accepted.json"


#: ---------------------------------------------------------------------
#: 权威正式流程(继承 R15 17 步;artifact 名换 R17 布局)。
R17_WORKFLOW_STEPS: tuple[dict[str, Any], ...] = (
    _step(
        "provenance-verify",
        cli_command="provenance-verify",
        argv_template=("provenance-verify", "--out-dir", "{out_dir}"),
        requires_artifacts=("gate_topology_reconciliation.json",),
        output_artifacts=("gate_topology_provenance_verify.json",),
        failure_phase="pre-provenance",
        note="Commit A 前链外一次性 provenance-lock;Commit A 后 "
             "formal 恒执行 verify 并记录(不重新 lock、不静默跳过)"),
    _step(
        "determinism-matrix",
        cli_command="determinism-matrix",
        argv_template=("determinism-matrix", "--out-dir", "{out_dir}"),
        output_artifacts=(
            "determinism/generation_determinism_contract.json",),
        failure_phase="determinism",
        note="R17:产物写 out_dir/determinism/(工程产物归 out_dir,"
             "状态根只放治理文件);"
             "generation_determinism_contract.json 是 audit 的硬前置"),
    _step(
        "audit",
        cli_command="audit",
        argv_template=("audit", "--out-dir", "{out_dir}",
                       "--code-freeze-sha", "{freeze_sha}"),
        rehearsal_argv_extra=("--fit-pairs", "2"),
        requires_artifacts=(
            "gate_topology_reconciliation.json",
            "determinism/generation_determinism_contract.json"),
        output_artifacts=(
            "r17_code_freeze.json", "baseline_ancestry.json",
            "historical_evidence_binding.json",
            "r12_abort_binding.json",
            "r12_iteration_failure_binding.json",
            "r14_failure_binding.json",
            "r15_failure_binding.json",
            "gate_topology_reconciliation_verify.json"),
        failure_phase="audit",
        note="freeze surface + 历史绑定(R12/R14/R15) + 拓扑 v2 verify"),
    _step(
        "cue-audit",
        cli_command="cue-audit",
        argv_template=("cue-audit", "--out-dir", "{out_dir}"),
        rehearsal_argv_extra=("--rehearsal",),
        output_artifacts=("cue_contract_audit.json",
                          "cue_event_trace.jsonl"),
        failure_phase="cue-audit"),
    _step(
        "preplan-smoke",
        cli_command="preplan-smoke",
        argv_template=("preplan-smoke", "--out-dir", "{out_dir}"),
        output_artifacts=("preplan_engineering_smoke.json",),
        failure_phase="preplan-smoke",
        note="plan-roundtrip 的硬 prerequisite producer"),
    _step(
        "plan-roundtrip",
        cli_command="plan-roundtrip",
        argv_template=("plan-roundtrip", "--out-dir", "{out_dir}"),
        prerequisites=("preplan-smoke", "cue-audit"),
        requires_artifacts=("cue_contract_audit.json",
                            "preplan_engineering_smoke.json"),
        output_artifacts=("plan_roundtrip_validation.json",),
        failure_phase="plan-roundtrip"),
    _step(
        "design-plan-lock",
        cli_command="design-plan-lock",
        argv_template=("design-plan-lock", "--out-dir", "{out_dir}"),
        rehearsal_argv_extra=("--rehearsal",),
        prerequisites=("preplan-smoke",),
        requires_artifacts=("preplan_engineering_smoke.json",),
        output_artifacts=("r17_design_plan.json",
                          "r17_design_plan_digest.txt"),
        failure_phase="design-plan-lock",
        data_class="design"),
    _step(
        "design",
        cli_command="design",
        argv_template=("design", "--out-dir", "{out_dir}"),
        prerequisites=("design-plan-lock",),
        requires_artifacts=("r17_design_plan.json",),
        output_artifacts=("r17_parameter_pack.json",
                          "r17_parameter_pack_digest.txt"),
        failure_phase="design",
        data_class="design"),
    _step(
        "calibrate",
        cli_command="calibrate",
        argv_template=("calibrate", "--out-dir", "{out_dir}"),
        rehearsal_argv_extra=("--rehearsal",),
        prerequisites=("design",),
        requires_artifacts=("r17_parameter_pack.json",),
        output_artifacts=(
            "preprocessor_bundle_calibration.json",
            "preprocessor_bundle_holdout.json",
            "robustness_gate.json", "calibration_evidence.json",
            "preprocessing_v2_requalification.json",
            "supervised_learnability_main.json",
            "supervised_learnability_holdout.json"),
        failure_phase="calibration",
        data_class="calibration"),
    _step(
        "preflight-static",
        cli_command="preflight-static",
        argv_template=("preflight-static", "--out-dir", "{out_dir}"),
        prerequisites=("design",),
        requires_artifacts=("r17_parameter_pack.json",),
        output_artifacts=("prelock_static_preflight_r17.json",),
        failure_phase="preflight-static"),
    _step(
        "lock-plan",
        cli_command="lock-plan",
        argv_template=("lock-plan", "--out-dir", "{out_dir}"),
        prerequisites=("calibrate", "preflight-static"),
        requires_artifacts=(
            "preprocessor_bundle_calibration.json",
            "preprocessor_bundle_holdout.json",
            "robustness_gate.json", "calibration_evidence.json"),
        output_artifacts=("qualification_plan_r17.json",
                          "qualification_plan_digest_r17.txt"),
        failure_phase="lock-plan",
        data_class="calibration",
        note="机械读取四个 calibration 产物的 canonical "
             "preprocessor_bundle_hash(R12 接口修复继承)"),
    _step(
        "preflight-sealed",
        cli_command="preflight-sealed",
        argv_template=("preflight-sealed", "--out-dir", "{out_dir}"),
        prerequisites=("lock-plan",),
        requires_artifacts=("qualification_plan_r17.json",
                            "r17_parameter_pack.json"),
        output_artifacts=("sealed_final_preflight_r17.json",
                          "sealed_final_preflight_r17_digest.txt"),
        failure_phase="sealed-preflight"),
    _step(
        "qualify",
        cli_command="qualify",
        argv_template=("qualify", "--out-dir", "{out_dir}"),
        rehearsal_argv_extra=("--rehearsal",),
        prerequisites=("preflight-sealed",),
        requires_artifacts=("qualification_plan_r17.json",
                            "sealed_final_preflight_r17.json",
                            "r17_parameter_pack.json"),
        output_artifacts=(
            "qualification_result.json", "qualification_raw.json",
            "qualification_preprocessor_bundle.json",
            "qualification_fit_manifest.json",
            "qualification_pair_evidence_table.json",
            "qualification_c2_block_evidence_table.json",
            "qualification_c2_independent_marginal.json"),
        failure_phase="qualification",
        touches_exposure=True,
        data_class="final",
        note="gate_evidence 内嵌于 qualification_result.json;"
             "phase 细分(qualification-pre-exposure / -exposed-"
             "running / -terminal)由权威 journal 机械判定;"
             "R17 执行所有权生命周期(exposure→授权→core→持权终态)"),
    _step(
        "smoke",
        cli_command="smoke",
        argv_template=("smoke", "--out-dir", "{out_dir}"),
        prerequisites=("qualify",),
        requires_artifacts=("r17_parameter_pack.json",
                            "qualification_result.json"),
        output_artifacts=("ppo_256step_smoke.json",),
        postcondition="final_verdict_pass",
        failure_phase="smoke",
        data_class="final",
        note="仅 final qualification PASS 后执行"),
    _step(
        "full-cold",
        cli_command="full-cold",
        argv_template=("full-cold", "--artifacts-dir", "{out_dir}",
                       "--out-dir", "{out_dir}"),
        rehearsal_argv_extra=("--skip-regression",),
        prerequisites=("smoke",),
        requires_artifacts=("qualification_result.json",
                            "qualification_preprocessor_bundle.json",
                            "ppo_256step_smoke.json"),
        output_artifacts=("full_cold_reader_check.json",),
        postcondition="smoke_pass",
        failure_phase="full-cold",
        note="full-cold reader + 回归套件(formal;rehearsal "
             "--skip-regression——profile 允许的差异)"),
    _step(
        "report-read",
        cli_command="report-read",
        argv_template=("report-read", "--artifacts-dir", "{out_dir}",
                       "--out-file", "{report_out}"),
        prerequisites=("full-cold",),
        requires_artifacts=("cue_contract_audit.json",
                            "robustness_gate.json",
                            "qualification_result.json",
                            "ppo_256step_smoke.json",
                            "full_cold_reader_check.json"),
        output_artifacts=("r17_report_values.json",),
        failure_phase="report-read",
        note="formal 写 r17_report_values.json;rehearsal 写 "
             "rt_report_values.json(profile 差异:输出文件名)"),
    _step(
        "verify-formal-logs",
        cli_command="verify-formal-logs",
        argv_template=("verify-formal-logs", "--manifest",
                       "{manifest}", "--stopped-at", "report-read",
                       "--out-dir", "{out_dir}"),
        prerequisites=("report-read",),
        output_artifacts=("r17_formal_log_verification.json",),
        failure_phase="verify-formal-logs",
        note="expected 序列由本定义机械派生;verify 自身的 manifest "
             "记录在其运行后由 chain 执行器追加(供 Commit B 复核 "
             "17 条完整);最后节点后的日志封口边界在冻结前定义"),
)

#: 全部 failure phase(继承 R15 20 条超集语义)。
R17_FAILURE_PHASES: tuple[str, ...] = (
    "bootstrap", "pre-provenance", "determinism", "audit", "cue-audit",
    "preplan-smoke", "plan-roundtrip", "design-plan-lock", "design",
    "calibration", "preflight-static", "lock-plan", "sealed-preflight",
    "qualification", "qualification-pre-exposure",
    "qualification-exposed-running", "qualification-terminal",
    "smoke", "full-cold", "report-read", "verify-formal-logs",
)

#: 链外产物(Commit A 前一次性锁定;运行时存在性照常检查)。
R17_EXTERNAL_ARTIFACTS: tuple[str, ...] = (
    "gate_topology_reconciliation.json",)


def r17_workflow_step_names() -> tuple[str, ...]:
    return tuple(s["name"] for s in R17_WORKFLOW_STEPS)


def r17_workflow_steps_by_name() -> dict[str, dict[str, Any]]:
    return {s["name"]: json.loads(json.dumps(s))
            for s in R17_WORKFLOW_STEPS}


def r17_producer_of_artifact() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for s in R17_WORKFLOW_STEPS:
        for art in s["output_artifacts"]:
            mapping[art] = s["name"]
    return mapping


def validate_r17_workflow(
        steps: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None
        = None) -> dict[str, Any]:
    """workflow 结构校验(fail closed;Commit A 前必须 PASS)。

    继承 R15 全部规则(名称唯一/phase 合法/prerequisite 先行/
    requires 有 producer 且在前/postcondition 白名单/
    touches_exposure 仅 qualify)。
    """
    use = list(steps if steps is not None else R17_WORKFLOW_STEPS)
    problems: list[str] = []
    names = [s["name"] for s in use]
    if len(names) != len(set(names)):
        problems.append("步骤名重复")
    producer: dict[str, str] = {}
    for s in use:
        for art in s.get("output_artifacts", ()):
            producer[art] = s["name"]
    pos = {n: i for i, n in enumerate(names)}
    for i, s in enumerate(use):
        if s.get("failure_phase") not in R17_FAILURE_PHASES:
            problems.append(
                f"{s['name']}: 未知 failure_phase "
                f"{s.get('failure_phase')!r}")
        for pre in s.get("prerequisites", ()):
            if pre not in pos:
                problems.append(
                    f"{s['name']}: prerequisite '{pre}' 不在流程中")
            elif pos[pre] >= i:
                problems.append(
                    f"{s['name']}: prerequisite '{pre}' 位于其后")
        for art in s.get("requires_artifacts", ()):
            if art in R17_EXTERNAL_ARTIFACTS:
                continue
            if art not in producer:
                problems.append(
                    f"{s['name']}: requires '{art}' 无 producer step")
            elif pos.get(producer[art], -1) >= i:
                problems.append(
                    f"{s['name']}: requires '{art}' 的 producer "
                    f"'{producer[art]}' 不在本步骤之前")
        if s.get("postcondition") not in (
                None, "final_verdict_pass", "smoke_pass"):
            problems.append(
                f"{s['name']}: 未知 postcondition "
                f"{s.get('postcondition')!r}")
        if s.get("touches_exposure") and s["name"] != "qualify":
            problems.append(
                f"{s['name']}: touches_exposure 仅 qualify 允许")
    return {
        "format": "cur261-r17-workflow-validation-v1",
        "workflow_version": R17_WORKFLOW_VERSION,
        "workflow_graph_digest": r17_workflow_graph_digest(),
        "n_steps": len(use),
        "step_names": names,
        "problems": problems,
        "pass": not problems,
    }


def r17_workflow_payload() -> dict[str, Any]:
    return {
        "version": R17_WORKFLOW_VERSION,
        "iteration": "r17",
        "steps": json.loads(json.dumps(list(R17_WORKFLOW_STEPS))),
        "rehearsal_only_tail": list(R17_REHEARSAL_ONLY_TAIL),
        "failure_phases": list(R17_FAILURE_PHASES),
    }


def r17_workflow_graph_digest(payload: dict[str, Any] | None = None
                              ) -> str:
    """workflow graph 规范 digest(r17wg- 前缀)。"""
    body = payload if payload is not None else r17_workflow_payload()
    return "r17wg-" + hashlib.sha256(json.dumps(
        body, sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def expected_formal_log_prefix_r17(stopped_at: str) -> list[str]:
    """stopped-at 步骤(含)的 expected manifest 记录序列(机械派生)。"""
    names = list(r17_workflow_step_names())
    if stopped_at not in names:
        raise ValueError(
            f"stopped_at '{stopped_at}' 不在权威 workflow 步骤集中;"
            f"合法值: {names}")
    if stopped_at == "verify-formal-logs":
        raise ValueError(
            "verify-formal-logs 自身不在 expected 前缀内"
            "(stopped-at 应为其前一步 report-read)")
    return names[:names.index(stopped_at) + 1]


def build_workflow_plan_r17(
        profile: str, *, out_dir: str, freeze_sha: str = "",
        manifest_path: str = "", report_out: str = "",
) -> dict[str, Any]:
    """按 profile 展开 argv(占位符替换 + rehearsal 差异注入)。

    rehearsal 允许的差异(继承 R15 §十一):--rehearsal 旗标、
    audit --fit-pairs 2、full-cold --skip-regression、report 输出
    文件名。步骤 name/order 与 formal 完全一致。
    """
    if profile not in ("formal", "rehearsal"):
        raise ValueError(f"未知 workflow profile: {profile!r}")
    if not report_out:
        report_out = str(Path(out_dir) / (
            "r17_report_values.json" if profile == "formal"
            else "rt_report_values.json"))
    if not manifest_path:
        manifest_path = str(Path(out_dir) /
                            "r17_formal_log_manifest.jsonl")
    steps_out = []
    for s in R17_WORKFLOW_STEPS:
        argv = list(s["argv_template"])
        if profile == "rehearsal" and s["rehearsal_argv_extra"]:
            extra = list(s["rehearsal_argv_extra"])
            if s["rehearsal_argv_replace"]:
                argv = extra
            else:
                argv = argv + extra
        argv = [a.replace("{out_dir}", str(out_dir))
                .replace("{freeze_sha}", str(freeze_sha))
                .replace("{manifest}", str(manifest_path))
                .replace("{report_out}", str(report_out))
                for a in argv]
        outputs = list(s["output_artifacts"])
        if (profile == "rehearsal"
                and s["name"] == "report-read"):
            outputs = ["rt_report_values.json"]
        steps_out.append({
            "name": s["name"],
            "cli_command": s["cli_command"],
            "argv": argv,
            "requires_artifacts": list(s["requires_artifacts"]),
            "output_artifacts": outputs,
            "prerequisites": list(s["prerequisites"]),
            "postcondition": s["postcondition"],
            "failure_phase": s["failure_phase"],
            "touches_exposure": s["touches_exposure"],
            "data_class": s["data_class"],
        })
    return {
        "format": "cur261-r17-workflow-plan-v1",
        "profile": profile,
        "workflow_version": R17_WORKFLOW_VERSION,
        "workflow_graph_digest": r17_workflow_graph_digest(),
        "out_dir": str(out_dir),
        "freeze_sha": str(freeze_sha),
        "manifest_path": str(manifest_path),
        "report_out": str(report_out),
        "steps": steps_out,
    }


def execute_workflow_chain_r17(
        plan: dict[str, Any], *,
        session: "R17ChainSession",
        log_dir: str | Path,
        project_dir: str | Path | None = None,
        fail_closure_extra: tuple[str, ...] = (),
) -> dict[str, Any]:
    """权威 chain 执行器(R17 协调者;rehearsal 与 formal 共用)。

    R17 治理(F1-F5 闭合):
    - 本函数在**已持有的链会话**内执行(调用方 cmd_chain_run 已
      acquire;本函数不再自行抢锁,拆掉"父持锁+qualify 抢锁"的
      必然失败接线);bootstrap_accepted、design_data_started、
      步骤事件、manifest 与 qualification 窗口全部由会话 owner
      单写;
    - 每步 subprocess 的 stdout/stderr **流式**重定向到独立
      raw log(打开文件句柄交给 OS 管道;运行中即落盘,零字节
      stderr 与文件缺失严格区分;§8.4);
    - qualify 步经受控 pipe 委派:exposure 先于 worker spawn;
      授权绑定 worker 实例身份;revoke → terminal 由协调者持权
      提交(§6.3);
    - 失败 → chain_step_failed → fail-closure(关闭职责,--rehearsal
      旗标隔离)→ chain_iteration_aborted → release。

    返回(不 raise):{"ok", "failed_step", "records", ...}。
    """
    import time

    profile = plan.get("profile", "formal")
    out_dir = Path(plan["out_dir"])
    manifest_path = Path(plan["manifest_path"])
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    if project_dir is None:
        project_dir = Path(__file__).resolve().parents[2]
    project_dir = Path(project_dir)

    # §5.1:bootstrap accepted 是首个正式可变写入,发生在会话内。
    (out_dir / R17_BOOTSTRAP_ACCEPTED_NAME).write_text(json.dumps({
        "format": "cur261-r17-bootstrap-accepted-v1",
        "utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "profile": profile,
        "workflow_graph_digest": plan["workflow_graph_digest"],
        "manifest_path": str(manifest_path),
        "chain_session": session.session_hash,
        "pid": os.getpid(),
        "env_identity": _env_identity(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(project_dir / "src") + os.pathsep + env.get(
        "PYTHONPATH", "")
    records: list[dict[str, Any]] = []
    failed_step: str | None = None
    failure_reason = ""
    qualification_terminal_status: str | None = None

    # §5.2 监护联动(C11):协调者自行优雅封口的停止接线。
    # 外层监护(登记进程组)发 SIGTERM=带 run/实例关联的停止请求;
    # 协调者终止当前 worker(qualify 委派走 revoke→terminal 既有
    # 路径)、在步骤边界停止新增步骤,并作为唯一 journal writer
    # 按 fail-closure→abort→release 封口。监护器不写 journal。
    stop_state: dict[str, Any] = {"requested": False, "signal": None,
                                  "proc": None}

    def _on_supervision_stop(signum, frame):  # noqa: ANN001
        stop_state["requested"] = True
        stop_state["signal"] = signum
        proc = stop_state.get("proc")
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    _prev_handlers = {}
    for _sig in (signal.SIGTERM, signal.SIGINT):
        _prev_handlers[_sig] = signal.signal(_sig,
                                             _on_supervision_stop)

    def _fail_closure_for(step_label: str, reason: str) -> None:
        fc_argv = [
            sys.executable, "-m", R17_WORKFLOW_CLI_MODULE,
            "fail-closure", "--out-dir", str(out_dir),
            "--failed-step", step_label,
            "--verdict", "FAIL",
            "--reason", reason,
            # rehearsal profile 的 fail-closure 不写正式
            # iteration abort(rehearsal 目录隔离)
            *(("--rehearsal",) if profile == "rehearsal" else ()),
            *fail_closure_extra,
        ]
        fc = subprocess.run(fc_argv, cwd=str(project_dir), env=env,
                            capture_output=True, text=True)
        (log_dir / "fail_closure.log").write_text(
            fc.stdout + fc.stderr, encoding="utf-8")

    try:
        for step in plan["steps"]:
            # 步骤边界停止:已开始的步骤按其真实 rc 处理,未开始的
            # 步骤不再启动(停止请求发生在两步之间时)
            if stop_state["requested"]:
                failed_step = "supervision_stop"
                failure_reason = (
                    f"supervision stop requested(signal="
                    f"{stop_state['signal']});在步骤边界停止,"
                    "未启动新步骤;由协调者唯一 writer 封口"
                    "(R17 §5.2:不重置、不追改已完成步骤/qualification"
                    " 终态)"
                )
                _fail_closure_for("supervision_stop", failure_reason)
                break
            name = step["name"]
            argv = [sys.executable, "-m", R17_WORKFLOW_CLI_MODULE,
                    *step["argv"]]
            start_utc = _dt.datetime.now(_dt.timezone.utc).isoformat()
            t0 = time.monotonic()
            pre_missing = [a for a in step.get("requires_artifacts", ())
                           if not (out_dir / a).is_file()]
            rc = 0
            signal_info: int | None = None
            # §5.4:design 步正式数据开始事件由协调者在 subprocess
            # 启动之前写入(worker 只验证,不自行写 journal)。
            if name == "design" and not pre_missing:
                session.record_design_data_started(
                    note="design step subprocess launch")
            if pre_missing:
                rc = 2
            else:
                post_ok, post_msg = _postcondition_ok(
                    step, out_dir, profile=profile)
                if not post_ok:
                    rc = 2
            log_path = log_dir / f"{name}.log"
            err_path = log_dir / f"{name}.err"
            # 步骤进入执行器即写 started(前置/后置预检失败也属于
            # "已开始但失败";§9.4 状态语义)
            session.record_step_started(name)
            if rc == 0:
                rc, signal_info = _run_step_subprocess(
                    argv, cwd=str(project_dir), env=env,
                    log_path=log_path, err_path=err_path,
                    step=name, session=session, plan=plan,
                    profile=profile, out_dir=out_dir,
                    stop_state=stop_state)
            else:
                # 前置/后置条件失败:零字节真实文件仍要存在(§8.4)
                log_path.write_text("", encoding="utf-8")
                detail = ("PrerequisiteError: 缺少前置产物 "
                          + ", ".join(pre_missing)
                          if pre_missing
                          else "PostconditionError")
                err_path.write_text(detail + "\n", encoding="utf-8")
            end_utc = _dt.datetime.now(_dt.timezone.utc).isoformat()
            if rc == 0:
                session.record_step_completed(name, rc=rc)
            else:
                session.record_step_failed(name, rc=rc)
            in_shas = {a: _sha256_file(out_dir / a)
                       for a in step.get("requires_artifacts", ())}
            out_shas = {a: _sha256_file(out_dir / a)
                        for a in step.get("output_artifacts", ())}
            rec = {
                "step": name,
                "workflow_graph_digest": plan["workflow_graph_digest"],
                "profile": profile,
                "cli_command": step["cli_command"],
                "argv": argv,
                "cwd": str(project_dir),
                "env_identity": _env_identity(),
                "start_utc": start_utc,
                "end_utc": end_utc,
                "duration_s": round(time.monotonic() - t0, 3),
                "rc": rc,
                "signal": signal_info,
                "stdout_path": str(log_path),
                "stderr_path": str(err_path),
                "stdout_sha256": _sha256_file(log_path),
                "stderr_sha256": _sha256_file(err_path),
                "stdout_bytes": log_path.stat().st_size,
                "stderr_bytes": err_path.stat().st_size,
                "input_artifacts": in_shas,
                "output_artifacts": out_shas,
            }
            records.append(rec)
            with manifest_path.open("a", encoding="utf-8") as mf:
                mf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                mf.flush()
            if rc != 0:
                failed_step = name
                failure_reason = (
                    f"formal chain step {name} rc={rc}"
                    + (f" signal={signal_info}" if signal_info else "")
                    + ("; PrerequisiteError(前置产物缺失)"
                       if rc == 2 and pre_missing else "")
                    + ("; PostconditionError" if rc == 2 and not pre_missing
                       else "")
                    + (f"; supervision stop(signal={stop_state['signal']})"
                       " worker 被外层监护终止" if stop_state["requested"]
                       else "")
                    + "(R17:停止后续正式计算;已冻结代码封口;不修代码继续)"
                )
                _fail_closure_for(name, failure_reason)
                break
    finally:
        for _sig, _handler in _prev_handlers.items():
            try:
                signal.signal(_sig, _handler)
            except (OSError, ValueError):
                pass

    return {
        "ok": failed_step is None,
        "failed_step": failed_step,
        "failure_reason": failure_reason,
        "profile": profile,
        "workflow_graph_digest": plan["workflow_graph_digest"],
        "records": records,
        "qualification_terminal_status": qualification_terminal_status,
    }


def _run_step_subprocess(argv: list[str], *, cwd: str, env: dict,
                         log_path: Path, err_path: Path, step: str,
                         session: "R17ChainSession",
                         plan: dict[str, Any], profile: str,
                         out_dir: Path,
                         stop_state: dict[str, Any] | None = None,
                         ) -> tuple[int, int | None]:
    """流式 raw logs 的步骤 subprocess(§8.4);qualify 走委派协议。

    stdout/stderr 直接重定向到已打开的文件句柄:数据经 OS 管道
    即时落盘,不经过父进程内存缓冲;子进程被 kill 时已写前缀
    保留在文件中。stop_state(监护联动)登记当前 proc:协调者
    收到停止信号时先 terminate worker(self 委派路径的 revoke/
    terminal 既有逻辑随后按真实 rc/signal 收口)。
    """
    pass_fds: tuple[int, ...] = ()
    extra_args: list[str] = []
    delegation = None
    if step == "qualify":
        delegation = _qualify_delegation_open(
            session, plan, profile, out_dir)
        pass_fds = delegation["pass_fds"]
        extra_args = ["--await-delegation",
                      str(delegation["write_fd"]),
                      str(delegation["read_fd"])]
    with open(log_path, "wb", buffering=0) as lf, \
            open(err_path, "wb", buffering=0) as ef:
        proc = subprocess.Popen(
            [*argv, *extra_args], cwd=cwd, env=env,
            stdout=lf, stderr=ef, pass_fds=pass_fds)
        if stop_state is not None:
            stop_state["proc"] = proc
            # 竞态:等待登记期间已收到停止请求 → 立即补发
            if stop_state.get("requested") and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
        if delegation is not None:
            _qualify_delegation_handshake(session, delegation, proc)
        rc = proc.wait()
    if stop_state is not None:
        stop_state["proc"] = None
    signal_info = None
    if rc < 0:
        signal_info = -rc
    if delegation is not None:
        _qualify_delegation_close(session, delegation, rc,
                                  signal_info)
    return rc, signal_info


def _qualify_delegation_open(session: "R17ChainSession",
                             plan: dict[str, Any], profile: str,
                             out_dir: Path) -> dict[str, Any]:
    """qualify 委派准备:exposure 先行 + 双向 pipe(§6.3 顺序)。"""
    from rl_curriculum.curriculum261_r17_registry import (
        qualification_r17_digest_path,
    )

    if profile != "rehearsal":
        digest = qualification_r17_digest_path().read_text(
            encoding="utf-8").strip()
        session.open_qualification_window(
            digest, note="qualify step delegation")
    else:
        digest = "rehearsal"
        session.open_qualification_window(
            digest, note="qualify step delegation(rehearsal)")
    r_reg, w_reg = os.pipe()   # worker → 协调者:实例身份
    r_tok, w_tok = os.pipe()   # 协调者 → worker:授权 token
    return {"r_reg": r_reg, "w_reg": w_reg, "r_tok": r_tok,
            "w_tok": w_tok, "pass_fds": (w_reg, r_tok),
            "write_fd": w_reg, "read_fd": r_tok,
            "plan_digest": digest, "grant": None,
            "profile": profile}


def _qualify_delegation_handshake(session: "R17ChainSession",
                                  delegation: dict[str, Any],
                                  proc: subprocess.Popen) -> None:
    """读取 worker 身份 → 发放绑定该身份的授权 → 下发 token。"""
    import json as _json

    with open(delegation["r_reg"], "r", encoding="utf-8") as fh:
        line = fh.readline()
    msg = _json.loads(line)
    if msg.get("kind") != "executor_identity":
        raise RuntimeError(
            f"委派协议:worker 首消息类型异常 {msg.get('kind')!r}")
    namespaces = tuple(msg.get("namespaces") or ())
    if not namespaces:
        raise RuntimeError("委派协议:worker 未声明授权 namespace 范围")
    grant = session.issue_generation_grant(
        namespaces=namespaces,
        delegate_executor_identity=msg["identity"],
        channel="controlled_pipe")
    delegation["grant"] = grant
    with open(delegation["w_tok"], "w", encoding="utf-8") as fh:
        fh.write(_json.dumps(
            {"kind": "grant_token", "token": grant.token,
             "probe_namespace": namespaces[0]}) + "\n")
        fh.flush()


def _qualify_delegation_close(session: "R17ChainSession",
                              delegation: dict[str, Any], rc: int,
                              signal_info: int | None) -> None:
    """worker 结束:revoke → 持权提交 qualification terminal(§6.3)。"""
    grant = delegation.get("grant")
    if grant is not None:
        try:
            session.revoke_generation_grant(grant)
        except Exception:  # noqa: BLE001 —— revoke 失败也要尝试终态
            pass
    digest = delegation["plan_digest"]
    if rc == 0:
        session.commit_qualification_terminal(
            "completed", digest, note="verdict=PASS(worker rc=0)")
    elif signal_info is not None:
        session.commit_qualification_terminal(
            "crashed", digest,
            note=f"worker killed by signal {signal_info}")
    else:
        session.commit_qualification_terminal(
            "failed", digest, note=f"verdict=FAIL(worker rc={rc})")
    for key in ("r_reg", "w_reg", "r_tok", "w_tok"):
        fd = delegation.get(key)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


expected_formal_log_prefix = expected_formal_log_prefix_r17

#: 机械转换后的 r17_cli 使用的名称别名(同一实现;显式别名而非
#: 第二实现——避免同一执行器出现两份定义)。
build_workflow_plan = build_workflow_plan_r17
execute_workflow_chain = execute_workflow_chain_r17


__all__ = [
    "R17_WORKFLOW_VERSION",
    "R17_REHEARSAL_ONLY_TAIL",
    "R17_WORKFLOW_CLI_MODULE",
    "R17_BOOTSTRAP_ACCEPTED_NAME",
    "R17_WORKFLOW_STEPS",
    "R17_FAILURE_PHASES",
    "R17_EXTERNAL_ARTIFACTS",
    "r17_workflow_step_names",
    "r17_workflow_steps_by_name",
    "r17_producer_of_artifact",
    "validate_r17_workflow",
    "r17_workflow_payload",
    "r17_workflow_graph_digest",
    "expected_formal_log_prefix_r17",
    "build_workflow_plan_r17",
    "execute_workflow_chain_r17",
]
