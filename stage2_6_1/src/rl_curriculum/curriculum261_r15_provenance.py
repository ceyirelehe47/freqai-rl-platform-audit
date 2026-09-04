"""GateTopologyReconciliation-v2:R15 gate 拓扑修订的历史来源证明。

在任何 R15 design/calibration/final 数据生成前创建并锁定(§五/§六)。
机器绑定 R13/R14 冲突的全部两侧证据,证明 R15 的拓扑修订是修复
Commit A 中 exposure 前已存在的合同矛盾,而非按历史结果调规则:

R13 段(v1 继承):
1. R6 STRICT_GATE_RULE_IDENTITY(live import;旧拓扑字面根:
   c2_matched 条目把 "cue/payoff separation" 列为 binding);
2. R13 Commit A 的 calibration 模块 delegated note(声明侧);
3. R13 run_c2_diagnostics 的 "诊断对照" 定位文字(声明侧);
4. R13 final aggregator 的重复 binding(c2_semantics_pass)
   ——实现侧,与声明冲突;
5. R13 qualification plan 原样继承的 R6 rule(statistics_rule);
6. R13 final FAIL(唯一 false 检查 c2_semantics_pass)与
   exposure marker(terminal=failed)。

R14 段(v2 新增;未被 R14 Agent 报告识别的缺陷):
7. R14 注册表声明四类 cue rate metric 唯一 binding source =
   dedicated 160-block semantic corpus(声明侧),且条目 rule 文字
   自认 "cue 点估计仅 0.90 灾难护栏 + noncue UCB(既有语义)";
8. R14 实现侧:r14_cue_eval.independent_cue_semantics 的 pass 包含
   point recall >= 0.90 与 noncue FP UCB <= 0.01;
   该 pass 被 AND 进 r14 marginal guard.pass →
   c2_independent_marginal_pass → final verdict(传递性双绑定);
9. R14 uniqueness checker 漏检:entry.get("metric_scope", ())
   optional 缺省(fail-open),independent 条目无 metric_scope 键;
10. R14 正式链编排缺陷:runner 缺 preplan-smoke 步,plan-roundtrip
    rc=1,R14 永久 FAIL(raw log manifest 尾记录机械可核)。

结论(写入 payload,机器可核):
- R13/R14 均仍永久 FAIL(不因 R15 修订被追认/撤销/改写);
- R15 修复的是各自 Commit A 中 exposure 前已存在的合同矛盾与
  冻结面内的编排缺陷;
- 不以 R13/R14 observed recall 数值作为规则选择依据;
- R15 不修改 dedicated semantic thresholds 与 160-block 规模。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

R15_PROVENANCE_FORMAT = "GateTopologyReconciliation-v2"
R15_PROVENANCE_ARTIFACT_NAME = "gate_topology_reconciliation.json"

R13_COMMIT_A = "47d3f22f4df97855423ee748f3aa2df5497422a6"
R13_COMMIT_B = "b8e1de05cc3040ddc81634eb36d735a9fe3483da"

R14_BASELINE_COMMIT = R13_COMMIT_B
R14_COMMIT_A = "0b07778d98430791756ca4a4768bc46bf1f05d8f"
R14_COMMIT_B = "14a889c2854571e3ab5245ef51da7c858c83f59b"

R13_CALIBRATION_PATH = (
    "stage2_6_1/src/rl_curriculum/curriculum261_r13_calibration.py")
R13_FINAL_PATH = (
    "stage2_6_1/src/rl_curriculum/curriculum261_r13_final.py")
R13_PLAN_ARTIFACT = (
    "stage2_6_1/artifacts/repair13/qualification_plan_r13.json")
R13_RESULT_ARTIFACT = (
    "stage2_6_1/artifacts/repair13/qualification_result.json")
R13_EXPOSURE_ARTIFACT = (
    "stage2_6_1/artifacts/repair13/qualification_exposure_r13.json")

R14_CUE_EVAL_PATH = (
    "stage2_6_1/src/rl_curriculum/curriculum261_r14_cue_eval.py")
R14_CALIBRATION_PATH = (
    "stage2_6_1/src/rl_curriculum/curriculum261_r14_calibration.py")
R14_FINAL_PATH = (
    "stage2_6_1/src/rl_curriculum/curriculum261_r14_final.py")
R14_GATE_TOPOLOGY_PATH = (
    "stage2_6_1/src/rl_curriculum/curriculum261_r14_gate_topology.py")
R14_FORMAL_RUNNER_PATH = "stage2_6_1/runner/r14_formal_chain.sh"
R14_FAIL_CLOSURE_ARTIFACT = (
    "stage2_6_1/artifacts/repair14/r14_fail_closure_summary.json")
R14_RAW_LOG_MANIFEST = (
    "stage2_6_1/artifacts/repair14/raw_logs/"
    "r14_formal_log_manifest.jsonl")

#: 声明侧与实现侧的关键文本(在 R13 Commit A blob 中机械检索;
#: 找不到任意一条即 fail closed——证明本身不可伪造)。
R13_DECLARATION_MARKERS = {
    "calibration_delegated_note": (
        "cue_semantics_delegated_note"),
    "calibration_delegated_note_text": (
        "cue recall/precision/false-cue 的正式 gate 在 dedicated"),
    "diagnostics_docstring": (
        "C2 三语义诊断(诊断对照;资格判定用 dedicated semantic "
        "corpus)"),
}
R13_IMPLEMENTATION_MARKERS = {
    "final_double_binding_line": (
        '"c2_semantics_pass": bool(all('),
    "final_double_binding_context": (
        'semantics = run_c2_diagnostics_r13('),
}

#: R14 隐藏双绑定的实现侧 marker(R14 Commit A blob 中检索)。
R14_IMPLEMENTATION_MARKERS = {
    "cue_eval_point_recall_in_pass": (
        "point_recall_ge_absolute_floor"),
    "cue_eval_pass_all_checks": (
        '"pass": bool(all(checks.values())),'),
    "guard_ands_cue_pass": (
        'and cue["pass"])'),
    "final_marginal_binding": (
        '"c2_independent_marginal_pass": marginal_pass'),
}

#: R14 声明侧/漏检侧 marker。
R14_DECLARATION_MARKERS = {
    "registry_rule_admits_dual_binding": (
        "cue 点估计仅 0.90 灾难护栏 + noncue UCB(既有语义)"),
    "uniqueness_fail_open_optional_scope": (
        'entry.get("metric_scope", ())'),
}

#: R14 编排缺陷 marker(formal runner blob)。
R14_ORCHESTRATION_MARKERS = {
    "runner_has_plan_roundtrip": "run plan-roundtrip   plan-roundtrip",
    "runner_has_preplan_smoke": "run preplan-smoke",
}


def _release_repo() -> Path:
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit"),
                 Path(__file__).resolve().parents[3] / "freqai-rl-audit"):
        if (cand / ".git").exists():
            return cand
    raise RuntimeError(
        "release repo 不可达(需要 /mnt/e/trading/freqai-rl-audit 或 "
        "E:/trading/freqai-rl-audit 以读取 R13 历史提交)")


def _git_show(repo: Path, commit: str, path: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"],
        capture_output=True, text=True, check=True)
    return out.stdout


def _blob_sha(repo: Path, commit: str, path: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{commit}:{path}"],
        capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _marker_find(haystack: str, marker: str) -> dict[str, Any]:
    idx = haystack.find(marker)
    return {"present": idx >= 0,
            "line": haystack[:idx].count("\n") + 1 if idx >= 0 else None}


def build_gate_topology_reconciliation() -> dict[str, Any]:
    """组装并锁定 GateTopologyReconciliation-v1 证明 payload。"""
    from rl_curriculum.curriculum261_r6_pairs import (
        STRICT_GATE_RULE_IDENTITY,
    )
    from rl_curriculum.curriculum261_r15_gate_topology import (
        R15_GATE_TOPOLOGY_VERSION,
        r15_cue_semantic_binding_uniqueness,
        r15_gate_topology_digest,
    )

    repo = _release_repo()

    # 1) R6 旧拓扑字面根
    r6_rule = json.loads(json.dumps(STRICT_GATE_RULE_IDENTITY,
                                    sort_keys=True, ensure_ascii=False))

    def _as_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    r6_old_topology_marker = _marker_find(
        _as_text(r6_rule.get("c2_matched", "")),
        "cue/payoff separation")

    # 2/3) R13 Commit A 声明侧
    calib_src = _git_show(repo, R13_COMMIT_A, R13_CALIBRATION_PATH)
    declarations = {
        name: _marker_find(calib_src, marker)
        for name, marker in R13_DECLARATION_MARKERS.items()
    }

    # 4) R13 Commit A 实现侧(重复 binding)
    final_src = _git_show(repo, R13_COMMIT_A, R13_FINAL_PATH)
    implementation = {
        name: _marker_find(final_src, marker)
        for name, marker in R13_IMPLEMENTATION_MARKERS.items()
    }

    # 5) R13 qualification plan 继承的 R6 rule
    plan_json = json.loads(
        _git_show(repo, R13_COMMIT_B, R13_PLAN_ARTIFACT))
    stats_rule = plan_json.get("statistics_rule", {})
    plan_inherited_r6 = _marker_find(
        json.dumps(stats_rule, ensure_ascii=False),
        "cue/payoff separation")

    # 6) R13 final FAIL + exposure
    result_json = json.loads(
        _git_show(repo, R13_COMMIT_B, R13_RESULT_ARTIFACT))
    exposure_json = json.loads(
        _git_show(repo, R13_COMMIT_B, R13_EXPOSURE_ARTIFACT))
    r13_failed_checks = sorted(
        k for k, v in result_json.get("checks", {}).items()
        if isinstance(v, bool) and not v)
    failed_check = result_json.get("checks", {}).get(
        "c2_semantics_pass")

    contradiction = {
        "declaration_side": {
            "what": ("calibration wrapper 与 c2_matched_conditions 声明 "
                     "cue 语义 gate delegated 给 dedicated semantic "
                     "corpus;run_c2_diagnostics 定位为诊断对照"),
            "markers": declarations,
            "calibration_blob_sha": _blob_sha(
                repo, R13_COMMIT_A, R13_CALIBRATION_PATH),
        },
        "implementation_side": {
            "what": ("final aggregator 把 matched corpus 点估计 gate "
                     "绑定为 verdict 级 c2_semantics_pass(与声明冲突)"),
            "markers": implementation,
            "final_blob_sha": _blob_sha(
                repo, R13_COMMIT_A, R13_FINAL_PATH),
        },
        "plan_side": {
            "what": ("qualification plan 原样继承 R6 "
                     "STRICT_GATE_RULE_IDENTITY(旧拓扑文字)"),
            "c2_matched_contains_old_text": plan_inherited_r6,
        },
        "r6_root": {
            "what": ("R6 STRICT_GATE_RULE_IDENTITY.c2_matched 把 "
                     "'cue/payoff separation' 列为 matched binding 条目"
                     "(拓扑冲突的字面根)"),
            "marker_in_r6_rule": r6_old_topology_marker,
        },
    }

    all_markers_present = all(
        m["present"] for m in
        list(declarations.values()) + list(implementation.values())
        + [r6_old_topology_marker, plan_inherited_r6])
    r13_binding = {
        "commit_chain": [
            "960dbe19701901f9262614aadf8b7f97742fab4d",
            R13_COMMIT_A,
            R13_COMMIT_B,
        ],
        "r13_verdict": result_json.get("verdict"),
        "r13_failed_checks": r13_failed_checks,
        "c2_semantics_pass_observed": failed_check,
        "exposure_status": exposure_json.get("status"),
        "exposure_count": 1,
        "remains_permanent_fail": True,
        "note": ("R13 不因 R15 修订 gate topology 而被追认、撤销或"
                 "改写为 PASS"),
    }

    # ---- R14 段(v2):隐藏双绑定 + fail-open 漏检 + 编排缺陷 ----
    r14_cue_eval_src = _git_show(
        repo, R14_COMMIT_A, R14_CUE_EVAL_PATH)
    r14_calib_src = _git_show(
        repo, R14_COMMIT_A, R14_CALIBRATION_PATH)
    r14_final_src = _git_show(repo, R14_COMMIT_A, R14_FINAL_PATH)
    r14_topology_src = _git_show(
        repo, R14_COMMIT_A, R14_GATE_TOPOLOGY_PATH)
    r14_runner_src = _git_show(
        repo, R14_COMMIT_A, R14_FORMAL_RUNNER_PATH)
    r14_impl_all_src = "\n".join(
        [r14_cue_eval_src, r14_calib_src, r14_final_src])
    r14_implementation = {
        name: _marker_find(r14_impl_all_src, marker)
        for name, marker in R14_IMPLEMENTATION_MARKERS.items()}
    r14_declaration = {
        name: _marker_find(r14_topology_src, marker)
        for name, marker in R14_DECLARATION_MARKERS.items()}
    r14_orchestration = {
        name: _marker_find(r14_runner_src, marker)
        for name, marker in R14_ORCHESTRATION_MARKERS.items()}
    r14_fail_closure = json.loads(
        _git_show(repo, R14_COMMIT_B, R14_FAIL_CLOSURE_ARTIFACT))
    r14_manifest_lines = [
        json.loads(line) for line in
        _git_show(repo, R14_COMMIT_B, R14_RAW_LOG_MANIFEST).splitlines()
        if line.strip()]
    r14_last_step = r14_manifest_lines[-1] if r14_manifest_lines else {}

    contradiction_r14 = {
        "declaration_side": {
            "what": ("R14 注册表声明四类 cue rate metric 唯一 "
                     "binding source = dedicated 160-block semantic "
                     "corpus;条目 rule 同时自认 marginal guard 保留 "
                     "0.90 灾难护栏 + noncue UCB(声明内即含矛盾)"),
            "markers": r14_declaration,
            "gate_topology_blob_sha": _blob_sha(
                repo, R14_COMMIT_A, R14_GATE_TOPOLOGY_PATH),
        },
        "implementation_side": {
            "what": ("independent_cue_semantics.pass 含 point recall "
                     ">= 0.90 与 noncue FP UCB <= 0.01;该 pass 被 "
                     "AND 进 marginal guard.pass → "
                     "c2_independent_marginal_pass → final verdict"
                     "(dedicated 之外的第二个传递性 binding source)"),
            "markers": r14_implementation,
            "blob_shas": {
                "r14_cue_eval": _blob_sha(
                    repo, R14_COMMIT_A, R14_CUE_EVAL_PATH),
                "r14_calibration": _blob_sha(
                    repo, R14_COMMIT_A, R14_CALIBRATION_PATH),
                "r14_final": _blob_sha(
                    repo, R14_COMMIT_A, R14_FINAL_PATH),
            },
        },
        "uniqueness_blindspot": {
            "what": ("r14 uniqueness checker 只扫显式 metric_scope,"
                     "optional 缺省 fail-open;independent 条目无 "
                     "metric_scope 键 ⇒ 永不参与检查 ⇒ 隐藏绑定"
                     "不可见(R15 v2 修复:构造期强制声明 + 传递闭包"
                     "+ leaf 名交叉检查)"),
            "marker": r14_declaration[
                "uniqueness_fail_open_optional_scope"],
        },
        "orchestration_defect": {
            "what": ("R14 formal runner 缺 preplan-smoke 步"
                     "(rehearsal 有、formal 无——两份独立硬编码列表),"
                     "plan-roundtrip 读 preplan_engineering_smoke.json "
                     "时 FileNotFoundError,rc=1,R14 永久 FAIL"),
            "runner_has_plan_roundtrip":
                r14_orchestration["runner_has_plan_roundtrip"],
            "runner_has_preplan_smoke": {
                **r14_orchestration["runner_has_preplan_smoke"],
                "expected_absent": True,
            },
            "runner_blob_sha": _blob_sha(
                repo, R14_COMMIT_A, R14_FORMAL_RUNNER_PATH),
        },
    }
    r14_markers_ok = bool(
        all(m["present"] for m in r14_implementation.values())
        and all(m["present"] for m in r14_declaration.values())
        and r14_orchestration["runner_has_plan_roundtrip"]["present"]
        and not r14_orchestration[
            "runner_has_preplan_smoke"]["present"])
    r14_binding = {
        "commit_chain": [R14_BASELINE_COMMIT, R14_COMMIT_A,
                         R14_COMMIT_B],
        "r14_verdict": r14_fail_closure.get("verdict"),
        "fail_closure_reason": r14_fail_closure.get("reason"),
        "raw_log_last_step": r14_last_step.get("step"),
        "raw_log_last_rc": r14_last_step.get("rc"),
        "n_manifest_records": len(r14_manifest_lines),
        "remains_permanent_fail": True,
        "note": ("R14 不因 R15 修复隐藏双绑定/编排缺陷而被追认;"
                 "缺陷位于 R14 Commit A 冻结面内"),
    }

    conclusions = {
        "r13_remains_permanent_fail": True,
        "r14_remains_permanent_fail": True,
        "r15_fixes_pre_exposure_contract_contradiction": True,
        "r15_fixes_r14_hidden_dual_binding": True,
        "r15_fixes_r14_uniqueness_fail_open": True,
        "r15_fixes_r14_orchestration_single_source": True,
        "independent_cue_point_metrics_diagnostic_only": True,
        "no_use_of_r13_r14_observed_recall_for_rule_choice": True,
        "rule_choice_basis": (
            "R13 冲突由 R13 Commit A 源码与 plan 文本的声明/实现矛盾"
            "机械证明;R14 隐藏双绑定由 R14 Commit A blob 的实现侧 "
            "marker(cue 点指标进 pass → guard AND → final checks)"
            "机械证明——两者在查看任何 final 数值前已成立;注册表不"
            "含任何 R13/R14 observed 统计量参数"),
        "dedicated_thresholds_unchanged": True,
        "dedicated_thresholds_note": (
            "dedicated 160-block semantic corpus 的 cluster-aware "
            "LCB/UCB 规则与 recall floor 推导(max(0.90, "
            "p_contract - 0.02))原样沿用;R15 不改阈值/不降样本量/"
            "不改 160-block 规模"),
    }
    uniqueness = r15_cue_semantic_binding_uniqueness()

    payload = {
        "format": R15_PROVENANCE_FORMAT,
        "iteration": "r15",
        "r15_gate_topology_version": R15_GATE_TOPOLOGY_VERSION,
        "r15_gate_topology_digest": r15_gate_topology_digest(),
        "cue_semantic_binding_uniqueness": uniqueness,
        "contradiction_evidence": contradiction,
        "contradiction_evidence_r14": contradiction_r14,
        "r13_binding": r13_binding,
        "r14_binding": r14_binding,
        "conclusions": conclusions,
        "pass": bool(all_markers_present and r14_markers_ok
                     and uniqueness["pass"]
                     and r13_binding["exposure_status"] == "failed"
                     and failed_check is False
                     and r14_binding["r14_verdict"] == "FAIL"
                     and r14_binding["raw_log_last_step"]
                     == "plan-roundtrip"
                     and r14_binding["raw_log_last_rc"] == 1),
    }
    digest = "r15gtrec-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    payload["digest"] = digest
    return payload


def write_gate_topology_reconciliation(out_dir: Path) -> dict[str, Any]:
    """写入并锁定 provenance 证据(一次且仅一次;fail closed)。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / R15_PROVENANCE_ARTIFACT_NAME
    if path.is_file():
        raise RuntimeError(
            f"{R15_PROVENANCE_ARTIFACT_NAME} 已存在:provenance 证据"
            "一次且仅一次锁定(§五;不得重写/替换)")
    payload = build_gate_topology_reconciliation()
    if not payload["pass"]:
        raise RuntimeError(
            "GateTopologyReconciliation-v2 证明不完整(markers 缺失或"
            "binding 唯一性不成立或 R14 事实不匹配)——fail closed")
    path.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False),
        encoding="utf-8")
    (out_dir / "gate_topology_reconciliation_digest.txt").write_text(
        payload["digest"] + "\n", encoding="utf-8")
    return payload


def verify_gate_topology_reconciliation(out_dir: Path) -> dict[str, Any]:
    """重算证明并与落盘 digest 比对(正式链 audit 硬 gate)。"""
    out_dir = Path(out_dir)
    path = out_dir / R15_PROVENANCE_ARTIFACT_NAME
    if not path.is_file():
        return {"pass": False, "reason": "provenance artifact 缺失"}
    stored = json.loads(path.read_text(encoding="utf-8"))
    if not stored.get("pass"):
        return {"pass": False, "reason": "stored payload pass=false"}
    recomputed = build_gate_topology_reconciliation()
    return {
        "pass": bool(recomputed["digest"] == stored["digest"]),
        "stored_digest": stored["digest"],
        "recomputed_digest": recomputed["digest"],
        "reason": ("" if recomputed["digest"] == stored["digest"]
                   else "digest 漂移(provenance 与 R13/R14 历史/"
                        "R6 规则不一致)"),
    }
