"""GateTopologyReconciliation-v1:R14 gate 拓扑修订的历史来源证明。

在任何 R14 design/calibration/final 数据生成前创建并锁定(§五)。
机器绑定 R13 冲突的全部两侧证据,证明 R14 的拓扑修订是修复
Commit A 中 exposure 前已存在的合同矛盾,而非按 R13 结果调规则:

1. R6 STRICT_GATE_RULE_IDENTITY(live import;旧拓扑字面根:
   c2_matched 条目把 "cue/payoff separation" 列为 binding);
2. R13 Commit A 的 calibration 模块 delegated note(cue 语义由
   dedicated semantic corpus 承担——声明侧);
3. R13 run_c2_diagnostics 的 "诊断对照" 定位文字(声明侧);
4. R13 final aggregator 的重复 binding('"c2_semantics_pass":
   bool(all(...))'——实现侧,与声明冲突);
5. R13 qualification plan 原样继承的 R6 rule(statistics_rule);
6. R13 final FAIL(qualification_result.json 唯一 false 检查
   c2_semantics_pass)与 exposure marker(terminal=failed)。

结论(写入 payload,机器可核):
- R13 仍永久 FAIL(不因 R14 修订被追认/撤销/改写);
- R14 修复的是 Commit A 中 exposure 前已存在的合同矛盾;
- 不以 R13 observed recall 数值(0.948571...)作为规则选择依据;
- R14 不修改 dedicated semantic thresholds。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

R14_PROVENANCE_FORMAT = "GateTopologyReconciliation-v1"
R14_PROVENANCE_ARTIFACT_NAME = "gate_topology_reconciliation.json"

R13_COMMIT_A = "47d3f22f4df97855423ee748f3aa2df5497422a6"
R13_COMMIT_B = "b8e1de05cc3040ddc81634eb36d735a9fe3483da"

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
    from rl_curriculum.curriculum261_r14_gate_topology import (
        R14_GATE_TOPOLOGY_VERSION,
        r14_cue_semantic_binding_uniqueness,
        r14_gate_topology_digest,
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
        "note": ("R13 不因 R14 修订 gate topology 而被追认、撤销或"
                 "改写为 PASS"),
    }
    conclusions = {
        "r13_remains_permanent_fail": True,
        "r14_fixes_pre_exposure_contract_contradiction": True,
        "no_use_of_r13_observed_recall_for_rule_choice": True,
        "rule_choice_basis": (
            "拓扑冲突由 R13 Commit A 源码与 plan 文本的声明/实现矛盾"
            "机械证明(上方 markers),在查看任何 R13 final 数值前已"
            "成立;注册表不含任何 R13 observed 统计量参数"),
        "dedicated_thresholds_unchanged": True,
        "dedicated_thresholds_note": (
            "dedicated 160-block semantic corpus 的 cluster-aware "
            "LCB/UCB 规则与 recall floor 推导(max(0.90, "
            "p_contract - 0.02))原样沿用;R14 不改阈值/不降样本量"),
    }
    uniqueness = r14_cue_semantic_binding_uniqueness()

    payload = {
        "format": R14_PROVENANCE_FORMAT,
        "iteration": "r14",
        "r14_gate_topology_version": R14_GATE_TOPOLOGY_VERSION,
        "r14_gate_topology_digest": r14_gate_topology_digest(),
        "cue_semantic_binding_uniqueness": uniqueness,
        "contradiction_evidence": contradiction,
        "r13_binding": r13_binding,
        "conclusions": conclusions,
        "pass": bool(all_markers_present and uniqueness["pass"]
                     and r13_binding["exposure_status"] == "failed"
                     and failed_check is False),
    }
    digest = "r14gtrec-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    payload["digest"] = digest
    return payload


def write_gate_topology_reconciliation(out_dir: Path) -> dict[str, Any]:
    """写入并锁定 provenance 证据(一次且仅一次;fail closed)。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / R14_PROVENANCE_ARTIFACT_NAME
    if path.is_file():
        raise RuntimeError(
            f"{R14_PROVENANCE_ARTIFACT_NAME} 已存在:provenance 证据"
            "一次且仅一次锁定(§五;不得重写/替换)")
    payload = build_gate_topology_reconciliation()
    if not payload["pass"]:
        raise RuntimeError(
            "GateTopologyReconciliation-v1 证明不完整(markers 缺失或"
            "binding 唯一性不成立)——fail closed")
    path.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False),
        encoding="utf-8")
    (out_dir / "gate_topology_reconciliation_digest.txt").write_text(
        payload["digest"] + "\n", encoding="utf-8")
    return payload


def verify_gate_topology_reconciliation(out_dir: Path) -> dict[str, Any]:
    """重算证明并与落盘 digest 比对(正式链 audit 硬 gate)。"""
    out_dir = Path(out_dir)
    path = out_dir / R14_PROVENANCE_ARTIFACT_NAME
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
                   else "digest 漂移(provenance 与 R13 历史/R6 规则"
                        "不一致)"),
    }
