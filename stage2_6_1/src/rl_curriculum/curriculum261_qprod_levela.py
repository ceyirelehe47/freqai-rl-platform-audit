# -*- coding: utf-8 -*-
"""QProd Level A:新迭代资格链的工程排练(公共步骤/控制/导出路径)。

从现有 17 步权威流程(R17_WORKFLOW_STEPS)复用步骤名序、依赖与失败
封口语义,叠加新迭代上下文(iteration/profile/产物根/状态根/许可
身份/计划身份/代码冻结身份)。**不是**复制 17 步业务实现,也不是只
改目录名:控制路径(上下文解析、许可一次性消费、会话 journal、
create-only 计划锁、exposure 窗口、raw 判定、失败封口)真实执行;
高成本原生数据/训练叶节点本轮以明确标注的工程原件夹具/替身运行,
步账本(level_a_step_ledger)逐记录 execution ∈
{real, fixture_double, not_run} + 证据路径——不凭遍历 17 个名字
声称全链正式执行。smoke 等会更新模型的叶节点本轮 NOT_RUN。

判定核心 judge_qualification_gates 是导出器复核的同一公共实现:
从 raw 证据文件实际计算 gate(重算摘要/阈值),不接受 PASS 字符串。
工程 profile 的资格判定只产生 engineering verdict,绝不产生正式
合格声明(formal_pass 恒 false;正式链保持 NOT_RUN)。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_qprod_context import (
    QProdContext, QProdContextError, QProdRunSession, _canonical_json,
)
from rl_curriculum.curriculum261_qprod_plan import (
    QPROD_QUALIFICATION_PLAN_FORMAT, freeze_qualification_plan,
    freeze_research_plan, load_qualification_plan,
    load_research_plan, qualification_plan_digest,
    research_plan_digest,
)

QPROD_LEVELA_RESULT_FORMAT = "cur261-qprod-levela-qualification-result-v1"
QPROD_LEVELA_RAW_FORMAT = "cur261-qprod-levela-qualification-raw-v1"
QPROD_LEVELA_EXPOSURE_FORMAT = "cur261-qprod-levela-exposure-v1"
QPROD_LEVELA_LEDGER_NAME = "level_a_step_ledger.json"
QPROD_LEVELA_DESIGN_PLAN_NAME = "qprod_design_plan.json"
QPROD_LEVELA_EXPOSURE_NAME = "qprod_qualification_exposure.json"
QPROD_LEVELA_RESULT_NAME = "qprod_qualification_result.json"
QPROD_LEVELA_RAW_NAME = "qprod_qualification_raw.json"
QPROD_LEVELA_REPORT_NAME = "qprod_report_values.json"

#: 步执行模式(诚实分层:真实调用/工程原件替身/未运行)。
STEP_REAL = "real"
STEP_FIXTURE_DOUBLE = "fixture_double"
STEP_NOT_RUN = "not_run"

#: Level A 代码冻结面(资格链控制+判定模块)。
QPROD_LEVELA_CODE_MODULES = (
    "curriculum261_qprod_context.py",
    "curriculum261_qprod_permit.py",
    "curriculum261_qprod_plan.py",
    "curriculum261_qprod_levela.py",
    "curriculum261_r4_preprocessing.py",
)

#: 判定 gate 集(与 run_scope.gate_set 对拍;顺序即报告顺序)。
QPROD_LEVELA_GATES = (
    "cue_audit_pass",
    "robustness_gate_pass",
    "calibration_bundle_hash_match",
    "parameter_pack_digest_match",
    "c2_marginal_evidence_ok",
    "exposure_one_shot_completed",
)


def levela_code_identity() -> dict[str, str]:
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    return {
        name: (hashlib.sha256((root / name).read_bytes()).hexdigest()
               if (root / name).is_file() else "MISSING")
        for name in QPROD_LEVELA_CODE_MODULES}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                               default=float), encoding="utf-8")


def build_engineering_topology_fixture() -> dict[str, Any]:
    """链外拓扑工程夹具:直接由公共权威函数生成(17 步名+产物
    producer 映射),保证 provenance-verify 的公共对拍可过——
    拓扑不再是自由形状 fixture。"""
    from rl_curriculum.curriculum261_r17_workflow import (
        r17_producer_of_artifact, r17_workflow_step_names,
    )

    producers = r17_producer_of_artifact()
    return {
        "format": "cur261-qprod-fixture-gate-topology-v1",
        "engineering_fixture": True,
        "workflow_steps": list(r17_workflow_step_names()),
        "artifact_producers": dict(sorted(producers.items())),
        "source": "r17_workflow.r17_workflow_step_names()+"
                  "r17_producer_of_artifact()(公共权威;非自由形状)",
    }


def build_engineering_cue_report_fixture() -> dict[str, Any]:
    """cue 审计报告工程夹具:完整 digest 核心形状 + 公共
    cue_contract_audit_digest 实算摘要——判定核心用同一公共函数
    复算对拍,fixture 不可自由伪造摘要。"""
    from rl_curriculum.curriculum261_r17_cue_contract import (
        ABSOLUTE_MINIMUM_RECALL, AUDIT_RNG_SEED,
        C2_CUE_SEMANTIC_CONTRACT_VERSION, NONINFERIORITY_DELTA,
        cue_contract_audit_digest,
    )

    report = {
        "format": "cur261-r17-cue-contract-audit-v1",
        "contract_version": C2_CUE_SEMANTIC_CONTRACT_VERSION,
        "audit_namespaces": {"model": "qprod_eng_fixture_model",
                             "validation": "qprod_eng_fixture_validation"},
        "audit_blocks_per_corpus": 2,
        "audit_rng_seed": AUDIT_RNG_SEED,
        "audit_n_events_mc": 4096,
        "frozen_detector": {
            "cue_thr": 0.0105, "wick_dir_thr": 0.0,
            "wick_width_thr": 0.0, "feature": "%-ret-1",
            "vol_bps": 26.0, "pulse_bps": 30.0, "episode_bars": 288},
        "mirror_bound_v2": {
            "formula": "lo = max(1, t-16); hi = min(t-8, n-17)",
            "r7_bug": "n/a(fixture)", "authority": "fixture"},
        "margin_log": 0.5,
        "p_contract": 0.9504,
        "analytic_weights_source": "fixture(model corpus 直方图替身)",
        "analytic_terms": [],
        "monte_carlo": {"n_events": 4096, "p_hat": 0.9505, "se": 0.0034,
                        "abs_diff_vs_analytic": 0.0001,
                        "tolerance": 0.001, "pass": True},
        "noninferiority": {
            "delta": NONINFERIORITY_DELTA,
            "absolute_minimum_recall": ABSOLUTE_MINIMUM_RECALL,
            "recall_floor": max(ABSOLUTE_MINIMUM_RECALL,
                                0.9504 - NONINFERIORITY_DELTA)},
        "direct_generator": {
            name: {"n_unique_positive_cues": 110,
                   "empirical_recall": 0.9509,
                   "block_cluster": {"point": 0.9509, "se": 0.0199,
                                     "lcb95": 0.918, "ci95": [0.912, 0.99]},
                   "analytic_conditional": 0.9504,
                   "tail": {"n_events": 8, "empirical_recall": 0.95,
                            "analytic_conditional": 0.949},
                   "max_replay_abs_error": 0.0}
            for name in ("model", "validation")},
        "engineering_fixture": True,
        "pass": True,
    }
    report["audit_digest"] = cue_contract_audit_digest(report)
    return report


def level_a_step_execution_plan() -> dict[str, dict[str, str]]:
    """17 步的工程排练执行分类(事前声明;账本照此记录)。

    real     = 控制路径/判定/锁定/校验真实执行;
    double   = 高成本原生数据以明确标注工程原件替身(输入进
               fixture_inputs,输出文件带 engineering_fixture 标记);
    not_run  = 会更新模型的叶节点(本轮零更新边界)。
    """
    return {
        "provenance-verify": {"mode": STEP_REAL},
        "determinism-matrix": {"mode": STEP_FIXTURE_DOUBLE},
        "audit": {"mode": STEP_REAL},
        "cue-audit": {"mode": STEP_FIXTURE_DOUBLE},
        "preplan-smoke": {"mode": STEP_FIXTURE_DOUBLE},
        "plan-roundtrip": {"mode": STEP_REAL},
        "design-plan-lock": {"mode": STEP_REAL},
        "design": {"mode": STEP_FIXTURE_DOUBLE},
        "calibrate": {"mode": STEP_FIXTURE_DOUBLE},
        "preflight-static": {"mode": STEP_REAL},
        "lock-plan": {"mode": STEP_REAL},
        "preflight-sealed": {"mode": STEP_REAL},
        "qualify": {"mode": STEP_REAL},
        "smoke": {"mode": STEP_NOT_RUN},
        "full-cold": {"mode": STEP_REAL},
        "report-read": {"mode": STEP_REAL},
        "verify-formal-logs": {"mode": STEP_REAL},
    }


def open_exposure(art_dir: Path, *, plan_digest: str,
                  iteration_id: str) -> Path:
    """exposure 先行(一次性;已存在即拒——不得重开已消费窗口)。"""
    path = Path(art_dir) / QPROD_LEVELA_EXPOSURE_NAME
    if path.is_file():
        raise QProdContextError(
            f"exposure 已存在 {path}(一次性窗口;终态/在途窗口均"
            f"不可重开——不得删除或换根救活)")
    payload = {
        "format": QPROD_LEVELA_EXPOSURE_FORMAT,
        "status": "running",
        "one_shot": True,
        "plan_digest": plan_digest,
        "iteration_id": iteration_id,
        "opened_utc": _now(),
    }
    _write_json(path, payload)
    return path


def commit_exposure_terminal(art_dir: Path, *, plan_digest: str,
                             status: str) -> dict[str, Any]:
    """exposure 终态(completed|failed;绑定同一 plan digest)。"""
    path = Path(art_dir) / QPROD_LEVELA_EXPOSURE_NAME
    if not path.is_file():
        raise QProdContextError("exposure 窗口未开(终态提交拒绝)")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("plan_digest") != plan_digest:
        raise QProdContextError("exposure 与终态 plan_digest 不一致")
    if payload.get("status") != "running":
        raise QProdContextError(
            f"exposure 已终态 {payload.get('status')!r}(不可重入)")
    payload["status"] = status
    payload["terminal_utc"] = _now()
    _write_json(path, payload)
    return payload


def read_exposure(art_dir: Path) -> dict[str, Any]:
    return json.loads(
        (Path(art_dir) / QPROD_LEVELA_EXPOSURE_NAME).read_text(
            encoding="utf-8"))


def judge_qualification_gates(art_dir: Path,
                              qualification_plan: dict[str, Any],
                              ) -> dict[str, Any]:
    """公共判定核心:从 raw 证据文件实际计算 gate(不读 PASS 字符串
    之外的任何 verdict 声明;每 gate 记录证据文件+摘要)。

    任一 gate 证据文件缺失 => 该 gate fail(fail closed,不因缺件
    放行);全部通过 => verdict PASS(工程 scope)。
    """
    art_dir = Path(art_dir)
    gates: dict[str, dict[str, Any]] = {}

    def evidence(name: str) -> dict[str, Any]:
        p = art_dir / name
        if not p.is_file():
            return {"present": False, "sha256": None}
        return {"present": True, "sha256": _sha(p),
                "parsed": json.loads(p.read_text(encoding="utf-8"))}

    # gate 1:cue 审计合同 pass(公共函数复算 digest + checks/pass 实值)
    # Q1 修复:判定不能只看 pass 字符串——报告完整性用 r17 公共
    # cue_contract_audit_digest 复算对拍,防"改数值不改 digest"。
    from rl_curriculum.curriculum261_r17_cue_contract import (
        cue_contract_audit_digest as _cue_digest,
    )

    ev = evidence("cue_contract_audit.json")
    digest_recomputed = None
    digest_ok = None
    if ev["present"]:
        try:
            digest_recomputed = _cue_digest(ev["parsed"])
            digest_ok = (ev["parsed"].get("audit_digest")
                         == digest_recomputed)
        except (KeyError, TypeError, ValueError):
            digest_ok = False
    cue_ok = bool(ev["present"]
                  and ev["parsed"].get("pass") is True
                  and ev["parsed"].get("audit_digest")
                  and digest_ok is True)
    gates["cue_audit_pass"] = {
        "pass": cue_ok, "evidence": "cue_contract_audit.json",
        "sha256": ev["sha256"],
        "observed": {"pass": (ev["parsed"].get("pass")
                              if ev["present"] else None),
                     "audit_digest": (
                         ev["parsed"].get("audit_digest")
                         if ev["present"] else None),
                     "audit_digest_recomputed": digest_recomputed,
                     "audit_digest_consistent": digest_ok}}

    # gate 2:稳健性 gate
    ev = evidence("robustness_gate.json")
    rb_ok = bool(ev["present"] and ev["parsed"].get("pass") is True)
    gates["robustness_gate_pass"] = {
        "pass": rb_ok, "evidence": "robustness_gate.json",
        "sha256": ev["sha256"],
        "observed": {"pass": (ev["parsed"].get("pass")
                              if ev["present"] else None)}}

    # gate 3:校准 bundle hash 与资格计划绑定一致
    ev = evidence("preprocessor_bundle_calibration.json")
    cal_hash = (ev["parsed"].get("preprocessor_bundle_hash")
                if ev["present"] else None)
    plan_hash = ((qualification_plan.get("preprocessing") or {})
                 .get("bundle_hash")
                 or qualification_plan.get("preprocessor_bundle_hash"))
    gates["calibration_bundle_hash_match"] = {
        "pass": bool(ev["present"] and cal_hash
                     and cal_hash == plan_hash),
        "evidence": "preprocessor_bundle_calibration.json",
        "sha256": ev["sha256"],
        "observed": {"calibration_bundle_hash": cal_hash,
                     "plan_bound_hash": plan_hash}}

    # gate 4:参数 pack digest 与资格计划绑定一致
    # Q1 修复:复用 262 公共 parameter_pack_digest(消费合同同一
    # 实现),不再本地重写一份 digest 算法。
    ev = evidence("parameter_pack.json")
    pack = ev["parsed"] if ev["present"] else {}
    from rl_curriculum.ppo262_qualified_input import (
        parameter_pack_digest as _pack_digest,
    )
    pack_d = _pack_digest(pack) if ev["present"] else None
    plan_pack_d = ((qualification_plan.get("parameter_pack") or {})
                   .get("digest"))
    gates["parameter_pack_digest_match"] = {
        "pass": bool(ev["present"] and pack_d and pack_d == plan_pack_d),
        "evidence": "parameter_pack.json", "sha256": ev["sha256"],
        "observed": {"recomputed_pack_digest": pack_d,
                     "plan_bound_digest": plan_pack_d}}

    # gate 5:C2 独立边际证据(真实阈值判定,fixture 数据)
    ev = evidence("qualification_c2_independent_marginal.json")
    marginal = (ev["parsed"].get("metrics") or {}) if ev[
        "present"] else {}
    thr = (qualification_plan.get("c2_marginal_thresholds") or {})
    marg_ok = bool(ev["present"] and marginal and thr and all(
        float(marginal.get(k, float("inf"))) <= float(v)
        for k, v in thr.items()))
    gates["c2_marginal_evidence_ok"] = {
        "pass": marg_ok,
        "evidence": "qualification_c2_independent_marginal.json",
        "sha256": ev["sha256"],
        "observed": {"metrics": marginal, "thresholds": thr}}

    # gate 6:exposure 一次性终态一致
    ev = evidence(QPROD_LEVELA_EXPOSURE_NAME)
    exp = ev["parsed"] if ev["present"] else {}
    gates["exposure_one_shot_completed"] = {
        "pass": bool(ev["present"]
                     and exp.get("status") == "completed"
                     and exp.get("one_shot") is True
                     and exp.get("plan_digest")
                     == qualification_plan.get(
                         "qualification_plan_digest")),
        "evidence": QPROD_LEVELA_EXPOSURE_NAME, "sha256": ev["sha256"],
        "observed": {"status": exp.get("status"),
                     "one_shot": exp.get("one_shot")}}

    verdict = all(g["pass"] for g in gates.values())
    return {
        "format": QPROD_LEVELA_RAW_FORMAT,
        "judged_utc": _now(),
        "gates": gates,
        "verdict": "PASS" if verdict else "FAIL",
        "scope": "engineering",
        "engineering_only": True,
        "formal_pass": False,
        "note": "工程 scope 判定:真实 gate 计算/失败封口语义;"
                "绝不产生正式合格声明",
    }


def run_level_a_rehearsal(
        ctx: QProdContext, session: QProdRunSession,
        fixture_inputs: dict[str, Any]) -> dict[str, Any]:
    """Level A 工程排练主驱动(17 步账本;失败即封口)。

    fixture_inputs(明确标记的工程原件夹具):
      gate_topology (dict) / cue_audit_report (dict) /
      preplan_smoke (dict) / determinism_contract (dict) /
      parameter_pack (dict) / calibration_artifacts (dict of dict)/
      robustness_gate (dict) / c2_marginal (dict) /
      design_plan (dict) / v2_envelope_path (Path) /
      c2_marginal_thresholds (dict)
    返回 {ledger, result, qualification_plan_digest, verdict}。
    """
    from rl_curriculum.curriculum261_r17_workflow import (
        r17_workflow_step_names,
    )

    art = Path(ctx.artifact_root)
    steps = r17_workflow_step_names()
    plan_exec = level_a_step_execution_plan()
    if set(plan_exec) != set(steps):
        raise QProdContextError(
            "步执行分类与权威 17 步不一致(步骤集漂移即拒绝)")
    ledger: list[dict[str, Any]] = []

    def record(step: str, *, mode: str, ok: bool, note: str,
               evidence: str | None = None) -> None:
        ledger.append({
            "step": step, "execution": mode, "ok": bool(ok),
            "note": note, "evidence": evidence,
            "utc": _now(),
        })

    def fail_closure(step: str, reason: str) -> None:
        record(step, mode=plan_exec[step]["mode"], ok=False,
               note=f"失败封口: {reason}")
        _write_json(art / QPROD_LEVELA_LEDGER_NAME,
                    {"format": "cur261-qprod-levela-step-ledger-v1",
                     "steps": ledger,
                     "failed_at": step, "verdict": "FAIL"})
        session.record_terminal(
            status="failed", verdict="FAIL", detail={
                "failed_step": step, "reason": reason})

    run_plan_payload = {
        "format": "cur261-qprod-research-plan-v1",
        "level": "level_a",
        "iteration_id": ctx.iteration_id,
        "profile": ctx.profile,
        "code_freeze_sha": ctx.code_freeze_sha,
        "run_scope": {
            "entry": "qprod_level_a_entry(rehearse)",
            "gate_set": list(QPROD_LEVELA_GATES),
            "budget": {"native_generation_calls": 0,
                       "optimizer_updates": 0,
                       "training_steps": 0},
            "exposure_policy": "one_shot_window",
        },
        "rules": {"gate_semantics_ref":
                  "curriculum261_qprod_levela.judge_qualification_gates"},
        "quota": {"leaf_calls": 0, "optimizer_updates": 0},
        "code_identity": levela_code_identity(),
        "stop_mode": "collect_all_k",
    }
    _, run_plan_digest = freeze_research_plan(
        ctx.state_root, run_plan_payload)

    try:
        # ---- 1. provenance-verify(真实:链外拓扑与公共权威对拍) ----
        # Q1 修复:复用真实公共业务定义(r17 权威 17 步名与产物
        # producer 映射)核验拓扑,不做"文件存在即通过"的简化。
        # 缺失/结构不符 → 本步 FAIL → 链 FAIL(不允许仍 17 步 PASS)。
        from rl_curriculum.curriculum261_r17_workflow import (
            r17_producer_of_artifact, r17_workflow_step_names,
        )

        topo = fixture_inputs.get("gate_topology")
        topo_problems: list[str] = []
        if not isinstance(topo, dict) or not topo:
            topo_problems.append("gate_topology 缺失(链外拓扑不可核)")
        else:
            declared_steps = topo.get("workflow_steps")
            if declared_steps != list(r17_workflow_step_names()):
                topo_problems.append(
                    "workflow_steps 与权威 R17_WORKFLOW_STEPS 不一致")
            declared_producers = topo.get("artifact_producers") or {}
            canonical = r17_producer_of_artifact()
            for art_name, producer in declared_producers.items():
                if canonical.get(art_name) != producer:
                    topo_problems.append(
                        f"artifact {art_name!r} 声明 producer {producer!r}"
                        f" != 权威 {canonical.get(art_name)!r}")
        if isinstance(topo, dict):
            _write_json(art / "gate_topology_reconciliation.json", topo)
        else:
            (art / "gate_topology_reconciliation.json").write_text(
                json.dumps({}), encoding="utf-8")
        ok = not topo_problems
        record("provenance-verify", mode=STEP_REAL, ok=ok,
               note="链外拓扑与公共权威 17 步/producer 映射对拍"
                    f"(问题: {topo_problems[:3] or '无'})",
               evidence="gate_topology_reconciliation.json")
        if not ok:
            raise QProdContextError(
                f"provenance-verify 失败: {topo_problems}")

        # ---- 2. determinism-matrix(替身) ----
        det = dict(fixture_inputs.get("determinism_contract") or {
            "format": "cur261-qprod-fixture-determinism-v1",
            "engineering_fixture": True,
            "note": "原生确定性矩阵为高成本叶节点,本轮替身;"
                    "原件语义由 Level B 坐标审计原生覆盖"})
        det["engineering_fixture"] = True
        _write_json(art / "determinism" /
                    "generation_determinism_contract.json", det)
        record("determinism-matrix", mode=STEP_FIXTURE_DOUBLE, ok=True,
               note="原生生成替身(engineering_fixture 标注)",
               evidence="determinism/generation_determinism_contract.json")

        # ---- 3. audit(真实:代码冻结面计算) ----
        ident = levela_code_identity()
        freeze_payload = {
            "format": "cur261-qprod-levela-code-freeze-v1",
            "code_identity": ident,
            "declared_freeze_sha": ctx.code_freeze_sha,
            "engineering_only": True,
        }
        _write_json(art / "qprod_code_freeze.json", freeze_payload)
        record("audit", mode=STEP_REAL, ok=True,
               note="控制面模块冻结身份实算(历史绑定面属正式链;"
                    "本轮工程面记录声明索引)",
               evidence="qprod_code_freeze.json")

        # ---- 4. cue-audit(替身;原生三路审计属 Level B 本轮原生面) ----
        cue = dict(fixture_inputs.get("cue_audit_report") or {})
        cue.setdefault("format",
                       "cur261-r17-cue-contract-audit-v1")
        cue["engineering_fixture"] = True
        _write_json(art / "cue_contract_audit.json", cue)
        record("cue-audit", mode=STEP_FIXTURE_DOUBLE, ok=True,
               note="cue 审计报告=工程原件替身(判定 gate 仍真实计算;"
                    "原生坐标审计见 Level B)",
               evidence="cue_contract_audit.json")

        # ---- 5. preplan-smoke(替身) ----
        pp = dict(fixture_inputs.get("preplan_smoke") or {})
        pp.setdefault("format", "cur261-qprod-fixture-preplan-v1")
        pp["engineering_fixture"] = True
        _write_json(art / "preplan_engineering_smoke.json", pp)
        record("preplan-smoke", mode=STEP_FIXTURE_DOUBLE, ok=True,
               note="preplan 原生 smoke 替身",
               evidence="preplan_engineering_smoke.json")

        # ---- 6. plan-roundtrip(真实:前置产物解析+业务依赖核验) ----
        # Q1 修复:preplan-smoke 是 plan-roundtrip 的真实前置——
        # preplan FAIL ⇒ 本步 FAIL ⇒ 链 FAIL(不允许仍 17 步 PASS)。
        rt_problems: list[str] = []
        preplan = None
        cue_report = None
        for n in ("cue_contract_audit.json",
                  "preplan_engineering_smoke.json"):
            if not (art / n).is_file():
                rt_problems.append(f"前置产物缺失 {n}")
                continue
            try:
                doc = json.loads((art / n).read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                rt_problems.append(f"{n} 不可解析: {exc}")
                continue
            if n == "preplan_engineering_smoke.json":
                preplan = doc
            else:
                cue_report = doc
        if preplan is not None and preplan.get("pass") is not True:
            rt_problems.append(
                f"preplan-smoke pass={preplan.get('pass')!r} != True"
                f"(前置业务失败,plan-roundtrip 不得通过)")
        if cue_report is not None:
            from rl_curriculum.curriculum261_r17_cue_contract import (
                cue_contract_audit_digest,
            )
            want = cue_contract_audit_digest(cue_report)
            if cue_report.get("audit_digest") != want:
                rt_problems.append(
                    "cue_contract_audit.json audit_digest 公共函数"
                    "复算不一致")
        rt_ok = not rt_problems
        _write_json(art / "plan_roundtrip_validation.json", {
            "format": "cur261-qprod-plan-roundtrip-v1",
            "inputs_parse_ok": rt_ok,
            "problems": rt_problems,
            "checked": ["cue_contract_audit.json",
                        "preplan_engineering_smoke.json"]})
        record("plan-roundtrip", mode=STEP_REAL, ok=rt_ok,
               note="前置产物解析+preplan pass 依赖+cue digest 公共"
                    f"复算(问题: {rt_problems[:3] or '无'})",
               evidence="plan_roundtrip_validation.json")
        if not rt_ok:
            raise QProdContextError(
                f"plan-roundtrip 失败: {rt_problems}")

        # ---- 7. design-plan-lock(真实:create-only 锁定) ----
        dp = dict(fixture_inputs.get("design_plan") or {})
        dp.setdefault("format", "cur261-qprod-design-plan-v1")
        dp["engineering_fixture_inputs"] = True
        dp_digest = "qadp-" + hashlib.sha256(_canonical_json(
            dp).encode("utf-8")).hexdigest()
        dp["design_plan_digest"] = dp_digest
        _write_json(art / QPROD_LEVELA_DESIGN_PLAN_NAME, dp)
        record("design-plan-lock", mode=STEP_REAL, ok=True,
               note="设计计划 create-only 锁定(数据=工程夹具,锁定真实)",
               evidence=QPROD_LEVELA_DESIGN_PLAN_NAME)

        # ---- 8. design(替身数据:参数 pack 由夹具提供) ----
        pack = dict(fixture_inputs["parameter_pack"])
        pack.setdefault("format", "cur261-qprod-parameter-pack-v1")
        pack["engineering_fixture_inputs"] = True
        pack_body = {k: v for k, v in pack.items()
                     if k not in ("digest", "created_utc")}
        pack["digest"] = "e262pk-" + hashlib.sha256(
            _canonical_json(pack_body).encode("utf-8")).hexdigest()
        pack["created_utc"] = _now()
        _write_json(art / "parameter_pack.json", pack)
        record("design", mode=STEP_FIXTURE_DOUBLE, ok=True,
               note="参数 pack=工程夹具设计输出(digest 实算)",
               evidence="parameter_pack.json")

        # ---- 9. calibrate(替身数据:校准产物夹具) ----
        cal = dict(fixture_inputs.get("calibration_artifacts") or {})
        cal_dig: dict[str, str | None] = {}
        for name in ("preprocessor_bundle_calibration.json",
                     "preprocessor_bundle_holdout.json"):
            body = cal.get(name) or {}
            body.setdefault("format", "cur261-qprod-fixture-cal-v1")
            body["engineering_fixture"] = True
            _write_json(art / name, body)
            cal_dig[name] = _sha(art / name)
        rg = dict(fixture_inputs.get("robustness_gate") or {})
        rg.setdefault("pass", True)
        rg["engineering_fixture"] = True
        _write_json(art / "robustness_gate.json", rg)
        ce = dict(fixture_inputs.get("calibration_evidence") or {})
        ce.setdefault("format", "cur261-qprod-fixture-cal-evidence-v1")
        _write_json(art / "calibration_evidence.json", ce)
        record("calibrate", mode=STEP_FIXTURE_DOUBLE, ok=True,
               note="原生校准=替身;产物 digest 实算供 lock-plan 绑定",
               evidence="preprocessor_bundle_calibration.json")

        # ---- 10. preflight-static(真实:pack 结构/digest 核验) ----
        fams = pack.get("families") or {}
        static_ok = (
            set(fams) == {"c1_opportunity", "c2_context", "c3_cost"}
            and all(set(fams[f].get("rung_params", {}))
                    == {"D0", "D1", "D2", "D3"}
                    and isinstance(fams[f].get("reference_thresholds"),
                                   dict) for f in fams))
        _write_json(art / "prelock_static_preflight.json", {
            "format": "cur261-qprod-static-preflight-v1",
            "pack_families_complete": static_ok,
            "pack_digest": pack["digest"]})
        record("preflight-static", mode=STEP_REAL, ok=static_ok,
               note="pack 三族×D0-D3 结构静态核验(真实)",
               evidence="prelock_static_preflight.json")
        if not static_ok:
            raise QProdContextError("preflight-static 失败")

        # ---- 11. lock-plan(真实:校准后资格计划冻结) ----
        envelope_path = Path(fixture_inputs["v2_envelope_path"])
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        bundle_hash = envelope.get("hashes", {}).get(
            "preprocessor_bundle_hash", "")
        fit_records = [
            {k: e[k] for k in ("pair_index", "episode_hash",
                               "generator_identity")}
            for e in envelope.get("fit_manifest", {}).get("entries", [])]
        fit_ns = envelope.get("fit_manifest", {}).get("namespace", "")
        qp_payload = {
            "format": QPROD_QUALIFICATION_PLAN_FORMAT,
            "level": "level_a",
            "iteration_id": ctx.iteration_id,
            "profile": ctx.profile,
            "scope": "engineering",
            "prior_plan_digest": run_plan_digest,
            "prior_plan_kind": "level_a_run_plan",
            "calibration_artifacts": cal_dig,
            "design_plan_digest": dp_digest,
            "parameter_pack": {"digest": pack["digest"],
                               "path": "parameter_pack.json"},
            "preprocessing": {
                "version": 2,
                "fit_namespace": fit_ns,
                "fit_records": fit_records,
                "source_kind": "qualification_chain",
            },
            "preprocessor_bundle_hash": bundle_hash,
            "c2_marginal_thresholds": dict(
                fixture_inputs.get("c2_marginal_thresholds")
                or {"non_cue_false_positive_max": 0.01}),
            "one_shot_input": {"exposure_policy": "one_shot_window",
                               "consumed_once": True},
            "engineering_only": True,
        }
        _, qp_digest = freeze_qualification_plan(
            ctx.state_root, qp_payload)
        _write_json(art / "qprod_qualification_plan_ref.json", {
            "qualification_plan_digest": qp_digest,
            "state_root_plan": "qprod_qualification_plan.json"})
        record("lock-plan", mode=STEP_REAL, ok=True,
               note="资格计划冻结(绑定校准产物 digest/pack/bundle/fit;"
                    "prior=数据前运行计划 digest,两种计划不混)",
               evidence="qprod_qualification_plan_ref.json")

        # ---- 12. preflight-sealed(真实:锁后全链复核) ----
        qp = load_qualification_plan(ctx.state_root)
        sealed_ok = (
            qp.get("qualification_plan_digest") == qp_digest
            and qp.get("parameter_pack", {}).get("digest")
            == pack["digest"]
            and qp.get("preprocessor_bundle_hash") == bundle_hash
            and len(qp.get("calibration_artifacts") or {}) >= 2)
        _write_json(art / "sealed_final_preflight.json", {
            "format": "cur261-qprod-sealed-preflight-v1",
            "qualification_plan_digest": qp_digest, "ok": sealed_ok})
        record("preflight-sealed", mode=STEP_REAL, ok=sealed_ok,
               note="锁后绑定复核(真实)",
               evidence="sealed_final_preflight.json")
        if not sealed_ok:
            raise QProdContextError("preflight-sealed 失败")

        # ---- 13. qualify(真实:exposure 窗口 + raw 判定 + 终态) ----
        open_exposure(art, plan_digest=qp_digest,
                      iteration_id=ctx.iteration_id)
        marg = dict(fixture_inputs.get("c2_marginal") or {})
        marg.setdefault("format",
                        "cur261-qprod-c2-independent-marginal-v1")
        marg.setdefault("metrics", {"non_cue_false_positive_max": 0.001})
        marg["engineering_fixture"] = True
        _write_json(art / "qualification_c2_independent_marginal.json",
                    marg)
        # envelope 原件进入资格产物面(逐字节复制,保留来源)
        import shutil

        shutil.copyfile(
            envelope_path, art / "preprocessor_envelope.json")
        commit_exposure_terminal(art, plan_digest=qp_digest,
                                 status="completed")
        raw = judge_qualification_gates(art, qp)
        _write_json(art / QPROD_LEVELA_RAW_NAME, raw)
        # Q1 修复:result 绑定 raw 证据字节摘要与校准前置 digest
        # 映射——导出器据此拒绝"raw 数据改坏但外层自洽"与
        # "校准前置缺失/漂移"的成功消费包。
        result = {
            "format": QPROD_LEVELA_RESULT_FORMAT,
            "qualification_plan_digest": qp_digest,
            "iteration_id": ctx.iteration_id,
            "source_iteration": f"{ctx.iteration_id}@producer",
            "scope": "engineering",
            "verdict": raw["verdict"],
            "engineering_only": True,
            "formal_pass": False,
            "gates": {k: v["pass"] for k, v in raw["gates"].items()},
            "raw_evidence": QPROD_LEVELA_RAW_NAME,
            "raw_evidence_sha256": _sha(art / QPROD_LEVELA_RAW_NAME),
            "calibration_artifacts_digests": dict(cal_dig),
            "parameter_pack_digest": pack["digest"],
            "preprocessor_bundle_hash": bundle_hash,
            "completed_utc": _now(),
        }
        _write_json(art / QPROD_LEVELA_RESULT_NAME, result)
        record("qualify", mode=STEP_REAL,
               ok=(raw["verdict"] == "PASS"),
               note="exposure 一次性窗口+公共判定核心实算"
                    f"(verdict={raw['verdict']})",
               evidence=QPROD_LEVELA_RESULT_NAME)
        if raw["verdict"] != "PASS":
            # 资格 FAIL:保持失败并封口(不得由后续步骤救活)
            fail = [k for k, v in raw["gates"].items()
                    if not v["pass"]]
            _write_json(art / QPROD_LEVELA_LEDGER_NAME,
                        {"format": "cur261-qprod-levela-step-ledger-v1",
                         "steps": ledger, "verdict": "FAIL",
                         "failed_gates": fail})
            session.record_terminal(
                status="completed", verdict="FAIL",
                plan_digest=qp_digest,
                detail={"failed_gates": fail})
            return {"ledger": ledger, "result": result,
                    "qualification_plan_digest": qp_digest,
                    "verdict": "FAIL"}

        # ---- 14. smoke(NOT_RUN:零模型更新边界) ----
        record("smoke", mode=STEP_NOT_RUN, ok=True,
               note="模拟边界/NOT_RUN:会更新模型的叶节点本轮不执行"
                    "(新增 optimizer/BC/PPO 更新=0);不假写正式 PASS")

        # ---- 15. full-cold(真实本地 reader;回归套件 skip 标注) ----
        cold_names = [QPROD_LEVELA_RESULT_NAME,
                      QPROD_LEVELA_RAW_NAME, "parameter_pack.json",
                      "preprocessor_envelope.json",
                      QPROD_LEVELA_EXPOSURE_NAME]
        cold_ok = all((art / n).is_file() for n in cold_names)
        try:
            from rl_curriculum.curriculum261_r4_preprocessing import (
                RouteCPreprocessorV2,
            )
            RouteCPreprocessorV2.load_envelope(
                art / "preprocessor_envelope.json")
            envelope_load_ok = True
        except Exception:
            envelope_load_ok = False
        _write_json(art / "full_cold_reader_check.json", {
            "format": "cur261-qprod-full-cold-reader-v1",
            "artifacts_present": cold_ok,
            "envelope_load_ok": envelope_load_ok,
            "regression_suite": "skipped(engineering rehearsal;"
                                "formal 专属步骤)"})
        record("full-cold", mode=STEP_REAL,
               ok=(cold_ok and envelope_load_ok),
               note="本地 reader 真实复读+envelope 真装载"
                    "(回归套件=工程排练差异)",
               evidence="full_cold_reader_check.json")
        if not (cold_ok and envelope_load_ok):
            raise QProdContextError("full-cold reader 失败")

        # ---- 16. report-read(真实) ----
        report_values = {
            "format": "cur261-qprod-report-values-v1",
            "verdict": result["verdict"],
            "qualification_plan_digest": qp_digest,
            "run_plan_digest": run_plan_digest,
            "gates": result["gates"],
            "parameter_pack_digest": pack["digest"],
            "preprocessor_bundle_hash": bundle_hash,
            "step_ledger_modes": {e["step"]: e["execution"]
                                  for e in ledger},
        }
        _write_json(art / QPROD_LEVELA_REPORT_NAME, report_values)
        record("report-read", mode=STEP_REAL, ok=True,
               note="报告值从产物实算",
               evidence=QPROD_LEVELA_REPORT_NAME)

        # ---- 17. verify-formal-logs(真实:步账本序列核验) ----
        # 核验含本步(recorded + 本步名)再比较(F2 修复:自比时本步
        # 尚未记账导致恒 False 的死门);seq_ok=False 走失败封口,
        # 不得封 PASS。
        recorded = [e["step"] for e in ledger]
        seq_ok = recorded + ["verify-formal-logs"] == [
            s for s in steps
            if s not in ("fail-closure-rehearsal",)]
        _write_json(art / "formal_log_verification.json", {
            "format": "cur261-qprod-log-verification-v1",
            "sequence_ok": seq_ok,
            "expected": list(steps),
            "recorded_including_this_step":
                recorded + ["verify-formal-logs"]})
        record("verify-formal-logs", mode=STEP_REAL, ok=seq_ok,
               note="17 步账本序列(含本步)与权威步骤集核验(真实;"
                    "失败即封口 FAIL)",
               evidence="formal_log_verification.json")
        if not seq_ok:
            _write_json(art / QPROD_LEVELA_LEDGER_NAME, {
                "format": "cur261-qprod-levela-step-ledger-v1",
                "steps": ledger, "verdict": "FAIL",
                "failed_at": "verify-formal-logs",
                "reason": "step ledger sequence mismatch"})
            session.record_terminal(
                status="failed", verdict="FAIL", plan_digest=qp_digest,
                detail={"failed_step": "verify-formal-logs",
                        "reason": "step ledger sequence mismatch"})
            return {"ledger": ledger, "result": result,
                    "qualification_plan_digest": qp_digest,
                    "verdict": "FAIL"}

        _write_json(art / QPROD_LEVELA_LEDGER_NAME, {
            "format": "cur261-qprod-levela-step-ledger-v1",
            "steps": ledger, "verdict": "PASS"})
        session.record_terminal(status="completed", verdict="PASS",
                                plan_digest=qp_digest)
        return {"ledger": ledger, "result": result,
                "qualification_plan_digest": qp_digest,
                "verdict": "PASS"}
    except QProdContextError as exc:
        fail_closure(_current_step(ledger, steps), str(exc))
        raise
    except BaseException as exc:  # 中断:可归属,不自动重抽
        step = _current_step(ledger, steps)
        record(step, mode=plan_exec[step]["mode"], ok=False,
               note=f"中断: {type(exc).__name__}: {exc}")
        _write_json(art / QPROD_LEVELA_LEDGER_NAME,
                    {"format": "cur261-qprod-levela-step-ledger-v1",
                     "steps": ledger, "interrupted_at": step,
                     "verdict": "INTERRUPTED"})
        session.record_interruption(
            f"{type(exc).__name__}: {exc}",
            {"step": step, "artifact_root": str(art)})
        raise


def _current_step(ledger: list[dict[str, Any]],
                  steps: tuple[str, ...]) -> str:
    if not ledger:
        return steps[0]
    idx = steps.index(ledger[-1]["step"])
    return steps[min(idx + 1, len(steps) - 1)]


__all__ = [
    "QPROD_LEVELA_RESULT_FORMAT", "QPROD_LEVELA_EXPOSURE_FORMAT",
    "QPROD_LEVELA_GATES", "QPROD_LEVELA_LEDGER_NAME",
    "level_a_step_execution_plan", "judge_qualification_gates",
    "open_exposure", "commit_exposure_terminal", "read_exposure",
    "run_level_a_rehearsal", "levela_code_identity",
    "STEP_REAL", "STEP_FIXTURE_DOUBLE", "STEP_NOT_RUN",
]
