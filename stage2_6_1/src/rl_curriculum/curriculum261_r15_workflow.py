"""R15 权威工作流定义(单一编排来源;Work Package A)。

R14 暴露的编排缺陷(机械坐标):
- runner/r14_formal_chain.sh 在 cue-audit 后直接执行 plan-roundtrip,
  遗漏 preplan-smoke(而 rehearsal 链有该步)——正式链死于此;
- R15_FORMAL_CHAIN_STEPS(r14_cli)与 runner/rehearsal/verifier 各自
  维护互不一致的步骤列表;
- provenance-lock 在 formal runner 里"已存在则静默跳过",而
  verify-formal-logs 的 expected 序列又要求它——manifest 永远不完整。

R15 权威语义(本模块是唯一来源;rehearsal / formal runner /
raw-log verifier / expected 序列 / report 顺序测试全部从这里派生):

1. 正式顺序(17 步,§四建议):
   provenance-verify → determinism-matrix → audit → cue-audit →
   preplan-smoke → plan-roundtrip → design-plan-lock → design →
   calibrate → preflight-static → lock-plan → preflight-sealed →
   qualify → smoke → full-cold → report-read → verify-formal-logs。

2. preplan-smoke 位于 plan-roundtrip 之前(结构上由
   plan-roundtrip.requires_artifacts + validate 强制,缺 producer
   即 validation FAIL,不等 FileNotFoundError)。

3. provenance artifact 在 Commit A 前一次性 lock(链外工程动作);
   Commit A 后 formal 恒执行 provenance-verify 并记录日志
   (manifest 记录 verify,不重新 lock,不做"已存在则跳过")。

4. rehearsal 与 formal 走同一 execute_workflow_chain 执行器;
   允许的差异仅:profile 参数(namespace/规模/--rehearsal 旗标/
   --skip-regression/terminal expectation),不得改变步骤顺序,
   不得跳过 prerequisite producer。

5. 每个 step 声明:prerequisites / requires_artifacts /
   producer(consumer 视角) / output_artifacts / data_class /
   touches_exposure / postcondition / failure_phase;
   validate_r15_workflow() 在 Commit A 前跑通结构校验
   (fail closed),workflow graph digest 进入 freeze/rehearsal/
   formal manifest 与报告。

rehearsal 专属尾步 fail-closure-rehearsal 是链外边界探针
(declared rehearsal_only_tail),不属于正式链步骤集。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

R15_WORKFLOW_VERSION = "AuthoritativeWorkflow-v1"

#: rehearsal 专属链外尾步(§十一 failure closure 边界探针;
#: 不在正式链步骤集内,parity 测试显式豁免)。
R15_REHEARSAL_ONLY_TAIL: tuple[str, ...] = ("fail-closure-rehearsal",)

#: CLI 入口(execute_workflow_chain 的 subprocess 目标)。
R15_WORKFLOW_CLI_MODULE = "rl_curriculum.curriculum261_r15_cli"


def _step(
    name: str, *,
    cli_command: str,
    argv_template: tuple[str, ...],
    rehearsal_argv_extra: tuple[str, ...] = (),
    rehearsal_argv_replace: bool = False,
    prerequisites: tuple[str, ...] = (),
    requires_artifacts: tuple[str, ...] = (),
    output_artifacts: tuple[str, ...] = (),
    data_class: str = "engineering",
    touches_exposure: bool = False,
    postcondition: str | None = None,
    failure_phase: str,
    note: str = "",
) -> dict[str, Any]:
    """构造一个 workflow step 声明(不可变语义:调用方不得原地改)。"""
    return {
        "name": name,
        "cli_command": cli_command,
        "argv_template": list(argv_template),
        "rehearsal_argv_extra": list(rehearsal_argv_extra),
        "rehearsal_argv_replace": bool(rehearsal_argv_replace),
        "prerequisites": list(prerequisites),
        "requires_artifacts": list(requires_artifacts),
        "output_artifacts": list(output_artifacts),
        "data_class": data_class,
        "touches_exposure": touches_exposure,
        "postcondition": postcondition,
        "failure_phase": failure_phase,
        "note": note,
    }


#: ---------------------------------------------------------------------
#: 权威正式流程(§四建议顺序;17 步)。所有消费者(rehearsal runner、
#: formal runner、raw-log verifier、expected 序列、顺序测试)从这里
#: 派生,不得自带第二份列表。
R15_WORKFLOW_STEPS: tuple[dict[str, Any], ...] = (
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
        argv_template=("determinism-matrix",),
        output_artifacts=(
            "determinism/generation_determinism_contract.json",),
        failure_phase="determinism",
        note="写 lock dir 下 determinism/ 子目录;"
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
            "r15_code_freeze.json", "baseline_ancestry.json",
            "historical_evidence_binding.json",
            "r12_abort_binding.json",
            "r12_iteration_failure_binding.json",
            "r14_failure_binding.json",
            "gate_topology_reconciliation_verify.json"),
        failure_phase="audit",
        note="freeze surface + 历史绑定(R12/R14) + 拓扑 v2 verify"),
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
        note="R14 正式链遗漏本步的直接修复:plan-roundtrip 的硬 "
             "prerequisite producer"),
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
        output_artifacts=("r15_design_plan.json",
                          "r15_design_plan_digest.txt"),
        failure_phase="design-plan-lock",
        data_class="design"),
    _step(
        "design",
        cli_command="design",
        argv_template=("design", "--out-dir", "{out_dir}"),
        prerequisites=("design-plan-lock",),
        requires_artifacts=("r15_design_plan.json",),
        output_artifacts=("r15_parameter_pack.json",
                          "r15_parameter_pack_digest.txt"),
        failure_phase="design",
        data_class="design"),
    _step(
        "calibrate",
        cli_command="calibrate",
        argv_template=("calibrate", "--out-dir", "{out_dir}"),
        rehearsal_argv_extra=("--rehearsal",),
        prerequisites=("design",),
        requires_artifacts=("r15_parameter_pack.json",),
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
        requires_artifacts=("r15_parameter_pack.json",),
        output_artifacts=("prelock_static_preflight.json",),
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
        output_artifacts=("qualification_plan_r15.json",
                          "qualification_plan_digest_r15.txt"),
        failure_phase="lock-plan",
        data_class="calibration",
        note="R12 修复的 lock-plan 接口:机械读取四个 calibration "
             "产物的 canonical preprocessor_bundle_hash"),
    _step(
        "preflight-sealed",
        cli_command="preflight-sealed",
        argv_template=("preflight-sealed", "--out-dir", "{out_dir}"),
        prerequisites=("lock-plan",),
        requires_artifacts=("qualification_plan_r15.json",
                            "r15_parameter_pack.json"),
        output_artifacts=("sealed_final_preflight.json",
                          "sealed_final_preflight_digest.txt"),
        failure_phase="sealed-preflight"),
    _step(
        "qualify",
        cli_command="qualify",
        argv_template=("qualify", "--out-dir", "{out_dir}"),
        rehearsal_argv_extra=("--rehearsal",),
        prerequisites=("preflight-sealed",),
        requires_artifacts=("qualification_plan_r15.json",
                            "sealed_final_preflight.json",
                            "r15_parameter_pack.json"),
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
        note="gate_evidence 内嵌于 qualification_result.json"
             "(R15 §八,不是独立文件);phase 细分"
             "(qualification-pre-exposed / -exposed-running / "
             "-terminal)由 exposure marker/ledger 机械判定"
             "(fail closure)"),
    _step(
        "smoke",
        cli_command="smoke",
        argv_template=("smoke", "--out-dir", "{out_dir}"),
        prerequisites=("qualify",),
        requires_artifacts=("r15_parameter_pack.json",
                            "qualification_result.json"),
        output_artifacts=("ppo_256step_smoke.json",),
        postcondition="final_verdict_pass",
        failure_phase="smoke",
        data_class="final",
        note="仅 final qualification PASS 后执行(§四)"),
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
        note="full-cold reader + full-cold 回归套件(formal;"
             "rehearsal --skip-regression——profile 允许的差异)"),
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
        output_artifacts=("r15_report_values.json",),
        failure_phase="report-read",
        note="formal 写 r15_report_values.json;rehearsal 写 "
             "rt_report_values.json(profile 差异:输出文件名)"),
    _step(
        "verify-formal-logs",
        cli_command="verify-formal-logs",
        argv_template=("verify-formal-logs", "--manifest",
                       "{manifest}", "--stopped-at", "report-read",
                       "--out-dir", "{out_dir}"),
        prerequisites=("report-read",),
        output_artifacts=("r15_formal_log_verification.json",),
        failure_phase="verify-formal-logs",
        note="expected 序列由本定义机械派生(expected_formal_log_"
             "prefix);verify 自身的 manifest 记录在其运行后由 "
             "chain 执行器追加(供 Commit B 复核 17 条完整)"),
)

#: 全部 failure phase(§七"至少区分"的超集;qualification 为 step 级
#: 基值——fail closure 按 exposure 状态机械展开为
#: qualification-pre-exposure / -exposed-running / -terminal)。
R15_FAILURE_PHASES: tuple[str, ...] = (
    "pre-provenance", "determinism", "audit", "cue-audit",
    "preplan-smoke", "plan-roundtrip", "design-plan-lock", "design",
    "calibration", "preflight-static", "lock-plan", "sealed-preflight",
    "qualification", "qualification-pre-exposure",
    "qualification-exposed-running", "qualification-terminal",
    "smoke", "full-cold", "report-read", "verify-formal-logs",
)

#: 链外产物(Commit A 前一次性锁定的 pre-freeze 证据;不属于任何
#: workflow step 的输出,但运行时存在性照常检查——§四"provenance
#: artifact 在 Commit A 前一次性 lock,Commit A 后 formal 恒执行
#: provenance-verify")。
R15_EXTERNAL_ARTIFACTS: tuple[str, ...] = (
    "gate_topology_reconciliation.json",)


def r15_workflow_step_names() -> tuple[str, ...]:
    """权威步骤名序列(有序)。"""
    return tuple(s["name"] for s in R15_WORKFLOW_STEPS)


def r15_workflow_steps_by_name() -> dict[str, dict[str, Any]]:
    return {s["name"]: json.loads(json.dumps(s))
            for s in R15_WORKFLOW_STEPS}


def r15_producer_of_artifact() -> dict[str, str]:
    """artifact 文件名 → producer step(机械推导,单一来源)。"""
    mapping: dict[str, str] = {}
    for s in R15_WORKFLOW_STEPS:
        for art in s["output_artifacts"]:
            mapping[art] = s["name"]
    return mapping


def validate_r15_workflow(
        steps: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None
        = None) -> dict[str, Any]:
    """workflow 结构校验(fail closed;Commit A 前必须 PASS)。

    检查:
    - 步骤名唯一;
    - failure_phase 在 R15_FAILURE_PHASES 内;
    - prerequisites 中每个 step 出现在更早位置;
    - requires_artifacts 的每个 artifact 都有 producer step,
      且 producer 位于本步骤之前(缺 producer ⇒ FAIL——
      "删除 preplan-smoke ⇒ validation 必须失败"的机械保证);
    - postcondition 只允许已知值;
    - touches_exposure 仅 qualify 允许(编排层不变量)。
    """
    use = list(steps if steps is not None else R15_WORKFLOW_STEPS)
    problems: list[str] = []
    names = [s["name"] for s in use]
    if len(names) != len(set(names)):
        problems.append("步骤名重复")
    # producer 映射从**传入的 steps**推导(变异测试的正确性前提:
    # 删除 producer step 后其产物必须变成"无 producer")
    producer: dict[str, str] = {}
    for s in use:
        for art in s.get("output_artifacts", ()):
            producer[art] = s["name"]
    pos = {n: i for i, n in enumerate(names)}
    for i, s in enumerate(use):
        if s.get("failure_phase") not in R15_FAILURE_PHASES:
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
            if art in R15_EXTERNAL_ARTIFACTS:
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
        "format": "cur261-r15-workflow-validation-v1",
        "workflow_version": R15_WORKFLOW_VERSION,
        "workflow_graph_digest": r15_workflow_graph_digest(),
        "n_steps": len(use),
        "step_names": names,
        "problems": problems,
        "pass": not problems,
    }


def r15_workflow_payload() -> dict[str, Any]:
    return {
        "version": R15_WORKFLOW_VERSION,
        "iteration": "r15",
        "steps": json.loads(json.dumps(list(R15_WORKFLOW_STEPS))),
        "rehearsal_only_tail": list(R15_REHEARSAL_ONLY_TAIL),
        "failure_phases": list(R15_FAILURE_PHASES),
    }


def r15_workflow_graph_digest(payload: dict[str, Any] | None = None
                              ) -> str:
    """workflow graph 规范 digest(r15wg- 前缀;进 freeze/rehearsal/
    formal manifest 与报告)。"""
    body = payload if payload is not None else r15_workflow_payload()
    return "r15wg-" + hashlib.sha256(json.dumps(
        body, sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def expected_formal_log_prefix(stopped_at: str) -> list[str]:
    """stopped-at 步骤(含)的 expected manifest 记录序列(机械派生)。

    verify-formal-logs 自身不在任何 expected 前缀内(它运行时
    manifest 尚无自身记录;其记录由 chain 执行器在运行后追加)。
    """
    names = list(r15_workflow_step_names())
    if stopped_at not in names:
        raise ValueError(
            f"stopped_at '{stopped_at}' 不在权威 workflow 步骤集中;"
            f"合法值: {names}")
    if stopped_at == "verify-formal-logs":
        raise ValueError(
            "verify-formal-logs 自身不在 expected 前缀内"
            "(stopped-at 应为其前一步 report-read)")
    return names[:names.index(stopped_at) + 1]


# ---------------------------------------------------------------------
# profile 计划展开(formal / rehearsal 共用同一 chain 执行器)
# ---------------------------------------------------------------------
def build_workflow_plan(
        profile: str, *, out_dir: str, freeze_sha: str = "",
        manifest_path: str = "", report_out: str = "",
) -> dict[str, Any]:
    """按 profile 展开 argv(占位符替换 + rehearsal 差异注入)。

    rehearsal 允许的差异(§十一):--rehearsal 旗标(namespace/规模)、
    audit --fit-pairs 2(规模)、full-cold --skip-regression
    (是否实际训练回归)、report 输出文件名(terminal expectation
    语义同)。步骤 name/order 与 formal 完全一致。
    """
    if profile not in ("formal", "rehearsal"):
        raise ValueError(f"未知 workflow profile: {profile!r}")
    if not report_out:
        report_out = str(Path(out_dir) / (
            "r15_report_values.json" if profile == "formal"
            else "rt_report_values.json"))
    if not manifest_path:
        manifest_path = str(Path(out_dir) /
                            "r15_formal_log_manifest.jsonl")
    steps_out = []
    for s in R15_WORKFLOW_STEPS:
        argv = list(s["argv_template"])
        if profile == "rehearsal" and s["rehearsal_argv_extra"]:
            extra = list(s["rehearsal_argv_extra"])
            if s["rehearsal_argv_replace"]:
                argv = extra
            else:
                # --flag 型差异附加在 --out-dir 组之后;
                # 占位符参数(--fit-pairs 2)直接附加
                argv = argv + extra
        argv = [a.replace("{out_dir}", str(out_dir))
                .replace("{freeze_sha}", str(freeze_sha))
                .replace("{manifest}", str(manifest_path))
                .replace("{report_out}", str(report_out))
                for a in argv]
        outputs = list(s["output_artifacts"])
        if (profile == "rehearsal"
                and s["name"] == "report-read"):
            # terminal expectation 差异:rehearsal 写 rt_report_values
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
    plan = {
        "format": "cur261-r15-workflow-plan-v1",
        "profile": profile,
        "workflow_version": R15_WORKFLOW_VERSION,
        "workflow_graph_digest": r15_workflow_graph_digest(),
        "out_dir": str(out_dir),
        "freeze_sha": str(freeze_sha),
        "manifest_path": str(manifest_path),
        "report_out": str(report_out),
        "steps": steps_out,
    }
    return plan


def _postcondition_ok(step: dict[str, Any],
                      out_dir: Path,
                      *, profile: str = "formal",
                      ) -> tuple[bool, str]:
    """步骤入口 postcondition 检查(smoke/full-cold 的运行时前置)。

    profile 语义(§十一 允许的 terminal expectation 差异):
    - formal:smoke 仅 final PASS 后;full-cold 仅 smoke PASS 后
      (严格,链应当在 qualify 停);
    - rehearsal:qualify 阶段缩小样本量,rt final verdict 不作资格
      判定(R14 既定语义);final_verdict_pass 降为"qualification_
      result.json 存在且可读"(接口覆盖仍被强制,verdict 不断链)。
    """
    cond = step.get("postcondition")
    if not cond:
        return True, ""
    if cond == "final_verdict_pass":
        p = out_dir / "qualification_result.json"
        if not p.is_file():
            return False, (
                "postcondition final_verdict_pass: "
                f"{p.name} 不存在(final 未执行或失败)")
        try:
            result = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return False, f"postcondition: 读取 {p.name} 失败: {exc}"
        if profile == "rehearsal":
            return True, ""
        if result.get("verdict") != "PASS":
            return False, (
                f"postcondition final_verdict_pass: verdict="
                f"{result.get('verdict')}"
                "(smoke 仅在 final PASS 后执行;链应当已在 qualify 停)")
    if cond == "smoke_pass":
        p = out_dir / "ppo_256step_smoke.json"
        if not p.is_file():
            return False, (
                f"postcondition smoke_pass: {p.name} 不存在")
        try:
            ok = json.loads(
                p.read_text(encoding="utf-8")).get("pass")
        except (json.JSONDecodeError, OSError) as exc:
            return False, f"postcondition: 读取 {p.name} 失败: {exc}"
        if ok is not True:
            return False, "postcondition smoke_pass: smoke 未 PASS"
    return True, ""


def _env_identity() -> dict[str, str]:
    import platform
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "conda_default_env": os.environ.get("CONDA_DEFAULT_ENV", ""),
        "pythonpath": os.environ.get("PYTHONPATH", ""),
    }


def _sha256_file(p: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def execute_workflow_chain(
        plan: dict[str, Any], *,
        log_dir: str | Path,
        project_dir: str | Path | None = None,
        fail_closure_extra: tuple[str, ...] = (),
) -> dict[str, Any]:
    """权威 chain 执行器(rehearsal 与 formal 共用;§十一/§十三)。

    每步:
    1. prerequisite artifact 存在性检查(缺 ⇒ PrerequisiteError,
       rc=2——不等 FileNotFoundError);
    2. postcondition 检查(smoke 仅 final PASS 后;full-cold 仅
       smoke PASS 后);
    3. 独立 subprocess(python -m curriculum261_r15_cli <argv>);
    4. manifest 追加(argv/cwd/env/start-end UTC/rc/stdout+stderr
       sha256+bytes/输入输出 artifact sha256/workflow digest);
    5. 任一步失败 ⇒ subprocess 调已冻结 fail-closure
       (--failed-step 传递,phase 由其机械判定)并停止。

    返回(不 raise):{"ok": bool, "failed_step": str|None,
    "records": [...]}——调用方(runner/rehearsal)据 ok 决定 rc。
    """
    import time

    profile = plan.get("profile", "formal")
    out_dir = Path(plan["out_dir"])
    manifest_path = Path(plan["manifest_path"])
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if project_dir is None:
        project_dir = Path(__file__).resolve().parents[2]
    project_dir = Path(project_dir)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(project_dir / "src") + os.pathsep + env.get(
        "PYTHONPATH", "")
    records: list[dict[str, Any]] = []
    failed_step: str | None = None
    failure_reason = ""

    for step in plan["steps"]:
        name = step["name"]
        argv = [sys.executable, "-m", R15_WORKFLOW_CLI_MODULE,
                *step["argv"]]
        start_utc = _dt.datetime.now(_dt.timezone.utc).isoformat()
        t0 = time.monotonic()
        pre_missing = [a for a in step.get("requires_artifacts", ())
                       if not (out_dir / a).is_file()]
        # manifest 文件类 artifact(verify-formal-logs 的输入)按
        # 声明路径处理:不在 out_dir 下时忽略存在性(workflow
        # 声明的 requires 均为 out_dir 相对路径;此分支为防御)
        rc = 0
        stdout_txt = stderr_txt = ""
        if pre_missing:
            rc = 2
            stderr_txt = (
                "PrerequisiteError: 缺少前置产物 "
                + ", ".join(pre_missing)
                + "(workflow step '" + name + "' 的 "
                "requires_artifacts;producer step 未运行或失败)")
        else:
            post_ok, post_msg = _postcondition_ok(
                step, out_dir, profile=profile)
            if not post_ok:
                rc = 2
                stderr_txt = "PostconditionError: " + post_msg
            else:
                res = subprocess.run(
                    argv, cwd=str(project_dir), env=env,
                    capture_output=True, text=True)
                rc = res.returncode
                stdout_txt = res.stdout
                stderr_txt = res.stderr
        end_utc = _dt.datetime.now(_dt.timezone.utc).isoformat()
        log_path = log_dir / f"{name}.log"
        err_path = log_dir / f"{name}.err"
        log_path.write_text(stdout_txt, encoding="utf-8")
        err_path.write_text(stderr_txt, encoding="utf-8")
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
            "stdout_path": str(log_path),
            "stderr_path": str(err_path),
            "stdout_sha256": hashlib.sha256(
                stdout_txt.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(
                stderr_txt.encode("utf-8")).hexdigest(),
            "stdout_bytes": len(stdout_txt.encode("utf-8")),
            "stderr_bytes": len(stderr_txt.encode("utf-8")),
            "input_artifacts": in_shas,
            "output_artifacts": out_shas,
        }
        records.append(rec)
        with manifest_path.open("a", encoding="utf-8") as mf:
            mf.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if rc != 0:
            failed_step = name
            failure_reason = (
                f"formal chain step {name} rc={rc}"
                + ("; PrerequisiteError(前置产物缺失)"
                   if rc == 2 and pre_missing else "")
                + ("; PostconditionError" if rc == 2 and not pre_missing
                   else "")
                + "(R15 §十四:停止;只读收尾;不创建新代码;"
                   "下一轮必须 R16)")
            fc_argv = [
                sys.executable, "-m", R15_WORKFLOW_CLI_MODULE,
                "fail-closure", "--out-dir", str(out_dir),
                "--failed-step", name,
                "--verdict", "FAIL",
                "--reason", failure_reason,
                *fail_closure_extra,
            ]
            fc = subprocess.run(fc_argv, cwd=str(project_dir), env=env,
                                capture_output=True, text=True)
            (log_dir / "fail_closure.log").write_text(
                fc.stdout + fc.stderr, encoding="utf-8")
            break

    return {
        "ok": failed_step is None,
        "failed_step": failed_step,
        "failure_reason": failure_reason,
        "profile": profile,
        "workflow_graph_digest": plan["workflow_graph_digest"],
        "records": records,
    }
