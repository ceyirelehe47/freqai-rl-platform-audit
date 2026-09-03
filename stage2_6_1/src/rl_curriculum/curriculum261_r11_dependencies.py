# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R11:依赖身份闭环与 Code Freeze 合同(§6/§7.3/§21)。

两部分:
1. 依赖身份表(R9 §6 机制继承):plan lock 前对全部关键符号做模块级
   解析(live import),记录 resolved module / source sha256,
   生成 r11dep- digest —— blind-rename 继承的签名错误在此被显式核对;
2. R11 Code Freeze(§6/§21):正式数据开始前记录全部 R11 源码模块的
   sha256 清单(R11_CODE_FREEZE_SHA + source tree digest);每个正式
   阶段开始前复算,任何漂移 fail closed(永久结束 R11)。
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
from pathlib import Path
from typing import Any

#: 声明依赖表:(symbol, 定义模块)。resolved module 必须精确等于定义
#: 模块(re-export 会导致 __module__ 指向 re-export 处,会被检出)。
#: 硬断言:c2_density_summary 必须定义于 R5(§6;R8 ImportError 教训)。
C2_DENSITY_SUMMARY_DEFINITION_MODULE = (
    "rl_curriculum.curriculum261_r5_pairs")

DEPENDENCY_TABLE_R11: tuple[tuple[str, str], ...] = (
    # ---- 密度 / pair 评估(R5/R6 冻结)----
    ("c2_density_summary", "rl_curriculum.curriculum261_r5_pairs"),
    ("density_gate_r5", "rl_curriculum.curriculum261_r5_pairs"),
    ("evaluate_pair_corpus_r4", "rl_curriculum.curriculum261_r4_pairs"),
    ("rung_report_r4", "rl_curriculum.curriculum261_r4_pairs"),
    ("build_c2_block_evidence_table",
     "rl_curriculum.curriculum261_r6_pairs"),
    ("block_gap_series", "rl_curriculum.curriculum261_r6_pairs"),
    ("simulate_formal_gate_pass_r6_matched",
     "rl_curriculum.curriculum261_r6_pairs"),
    ("c2_matched_conditions", "rl_curriculum.curriculum261_r6_pairs"),
    ("c2_marginal_guard_conditions", "rl_curriculum.curriculum261_r6_pairs"),
    ("corpus_conditions_r6_pair", "rl_curriculum.curriculum261_r6_pairs"),
    # ---- R6 runner(R11 wrapper 的委托目标;签名核对对象)----
    ("generate_fit_bank_r6", "rl_curriculum.curriculum261_r6_calibration"),
    ("fit_preprocessor_v2_from_bank_r6",
     "rl_curriculum.curriculum261_r6_calibration"),
    ("run_calibration_corpus_c13_r6",
     "rl_curriculum.curriculum261_r6_calibration"),
    ("run_c2_matched_corpus_r6",
     "rl_curriculum.curriculum261_r6_calibration"),
    ("run_c2_independent_corpus_r6",
     "rl_curriculum.curriculum261_r6_calibration"),
    ("supervised_learnability_run_r6",
     "rl_curriculum.curriculum261_r6_calibration"),
    ("train_supervised_mlp", "rl_curriculum.ppo262_r2_supervised"),
    # ---- cue 语义(R11 namespace)----
    ("candidate_cue_semantics",
     "rl_curriculum.curriculum261_r11_cue_eval"),
    ("semantic_cue_gate", "rl_curriculum.curriculum261_r11_cue_eval"),
    ("independent_cue_semantics",
     "rl_curriculum.curriculum261_r11_cue_eval"),
    # ---- R11 新合同(核心修复面)----
    ("canonical_episode", "rl_curriculum.curriculum261_r11_reference"),
    ("reference_equivalence_run_r11",
     "rl_curriculum.curriculum261_r11_reference"),
    ("collect_policy_visible_dataset_r11",
     "rl_curriculum.curriculum261_r11_labels"),
    ("build_routing_r11", "rl_curriculum.curriculum261_r11_routing"),
    ("require_eval_routing_r11",
     "rl_curriculum.curriculum261_r11_routing"),
    ("orchestrate_calibration_stage_r11",
     "rl_curriculum.curriculum261_r11_orchestrator"),
    ("supervised_learnability_run_r11",
     "rl_curriculum.curriculum261_r11_calibration"),
    ("run_preplan_full_pipeline_rehearsal_r11",
     "rl_curriculum.curriculum261_r11_rehearsal"),
    ("live_signature_audit_r11",
     "rl_curriculum.curriculum261_r11_delegation"),
    ("delegation_ast_checks_r11",
     "rl_curriculum.curriculum261_r11_delegation"),
    # ---- R11 生成确定性合同(工作包 A)----
    ("EnvelopeRecorder",
     "rl_curriculum.curriculum261_generation_envelope"),
    ("replay_call", "rl_curriculum.curriculum261_generation_envelope"),
    ("compare_envelopes",
     "rl_curriculum.curriculum261_generation_envelope"),
    ("dump_failure_evidence",
     "rl_curriculum.curriculum261_generation_envelope"),
    ("envelope_sink", "rl_curriculum.curriculum261_generation_envelope"),
    ("ledger_sink_factory",
     "rl_curriculum.curriculum261_generation_envelope"),
    ("ledger_rows_digest",
     "rl_curriculum.curriculum261_generation_envelope"),
    ("audit_generator_mutable_state",
     "rl_curriculum.curriculum261_r11_determinism"),
    ("run_cross_process_determinism_matrix",
     "rl_curriculum.curriculum261_r11_determinism"),
    ("generation_determinism_gate",
     "rl_curriculum.curriculum261_r11_determinism"),
    # ---- R11 full-scale shadow(工作包 C)----
    ("run_full_scale_shadow_r11", "rl_curriculum.curriculum261_r11_shadow"),
    ("compare_full_scale_shadow_runs",
     "rl_curriculum.curriculum261_r11_shadow"),
    # ---- 独立性/可观察性(冻结公共实现)----
    ("check_c2_local_cue_independence",
     "rl_curriculum.curriculum261_qualification"),
    ("check_c2_context_observability",
     "rl_curriculum.curriculum261_qualification"),
)

#: R11 code freeze 覆盖的源码模块(sha256 清单;§6/§21)。
R11_CODE_MODULES: tuple[str, ...] = (
    "curriculum261_api.py",
    "curriculum261_generation_envelope.py",
    "curriculum261_r11_calibration.py",
    "curriculum261_r11_cli.py",
    "curriculum261_r11_cue_contract.py",
    "curriculum261_r11_cue_eval.py",
    "curriculum261_r11_delegation.py",
    "curriculum261_r11_dependencies.py",
    "curriculum261_r11_design.py",
    "curriculum261_r11_determinism.py",
    "curriculum261_r11_final.py",
    "curriculum261_r11_labels.py",
    "curriculum261_r11_namespaces.py",
    "curriculum261_r11_noise_replay.py",
    "curriculum261_r11_orchestrator.py",
    "curriculum261_r11_param_pack.py",
    "curriculum261_r11_plan.py",
    "curriculum261_r11_preflight.py",
    "curriculum261_r11_preplan.py",
    "curriculum261_r11_reference.py",
    "curriculum261_r11_rehearsal.py",
    "curriculum261_r11_routing.py",
    "curriculum261_r11_shadow.py",
    "curriculum261_r11_smoke.py",
)


def resolve_dependency_identity_r11() -> dict[str, Any]:
    """解析全部声明符号(fail closed:missing/错模块立即报错)。"""
    rows: dict[str, Any] = {}
    ok = True
    for symbol, defining_module in DEPENDENCY_TABLE_R11:
        try:
            mod = importlib.import_module(defining_module)
            obj = getattr(mod, symbol)
        except (ImportError, AttributeError) as exc:
            rows[symbol] = {
                "declared_module": defining_module,
                "error": repr(exc), "resolved_module": None,
            }
            ok = False
            continue
        resolved = getattr(obj, "__module__", defining_module)
        source_file = inspect.getsourcefile(obj)
        src_hash = None
        if source_file and Path(source_file).is_file():
            src_hash = hashlib.sha256(
                Path(source_file).read_bytes()).hexdigest()
        module_ok = resolved == defining_module
        ok = ok and module_ok
        rows[symbol] = {
            "declared_module": defining_module,
            "resolved_module": resolved,
            "module_match": module_ok,
            "module_matches_declaration": module_ok,
            "resolved": True,
            "callable": callable(obj),
            "source_file": str(source_file) if source_file else None,
            "source_file_sha256": src_hash,
            "source_sha256": src_hash,
        }
    # supervised wrapper 的 keyword-only 硬断言(§7.1;签名层杜绝
    # R9 的位置参数错传)
    from rl_curriculum.curriculum261_r11_calibration import (
        supervised_learnability_run_r11,
    )

    sig = inspect.signature(supervised_learnability_run_r11)
    kwonly = {p.name for p in sig.parameters.values()
              if p.kind is inspect.Parameter.KEYWORD_ONLY}
    required_kwonly = {"namespace", "pairs_per_rung", "train_pair_limit",
                       "model_seeds", "training_config"}
    supervised_kwonly_check = {
        "required": sorted(required_kwonly),
        "actual": sorted(kwonly),
        "pass": required_kwonly <= kwonly,
    }
    ok = ok and required_kwonly <= kwonly
    c2_density_ok = rows.get("c2_density_summary", {}).get(
        "module_match") is True
    result = {
        "format": "cur261-r11-dependency-resolution-v1",
        "iteration": "r11", "symbols": rows,
        "dependencies": rows,
        "n_symbols": len(DEPENDENCY_TABLE_R11),
        "n_declared": len(DEPENDENCY_TABLE_R11),
        "c2_density_summary_definition_module_assert":
            C2_DENSITY_SUMMARY_DEFINITION_MODULE,
        "c2_density_summary_resolved_module":
            rows.get("c2_density_summary", {}).get("resolved_module"),
        "c2_density_summary_module_match": bool(c2_density_ok),
        "supervised_keyword_only": supervised_kwonly_check,
        "problems": [sym for sym, row in rows.items()
                     if isinstance(row, dict)
                     and not (row.get("resolved")
                              and row.get("module_matches_declaration")
                              and row.get("callable"))],
        "pass": bool(ok and c2_density_ok)}
    result["digest"] = dependency_identity_digest_r11(result)
    return result


def dependency_identity_digest_r11(resolution: dict[str, Any]) -> str:
    payload = json.dumps(resolution, sort_keys=True, ensure_ascii=False,
                         default=str)
    return "r11dep-" + hashlib.sha256(
        payload.encode("utf-8")).hexdigest()


def write_dependency_resolution_r11(out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    resolution = resolve_dependency_identity_r11()
    resolution["digest"] = dependency_identity_digest_r11(resolution)
    (out_dir / "dependency_resolution.json").write_text(
        json.dumps(resolution, indent=1, ensure_ascii=False, default=str),
        encoding="utf-8")
    return resolution


# ------------------------------------------------------- Code Freeze(§6)
def source_tree_digest_r11() -> dict[str, Any]:
    """全部 R11 源码模块的 sha256 清单与聚合 digest。"""
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    modules: dict[str, str] = {}
    for name in R11_CODE_MODULES:
        path = root / name
        modules[name] = (hashlib.sha256(path.read_bytes()).hexdigest()
                         if path.is_file() else "MISSING")
    aggregate = "r11src-" + hashlib.sha256(json.dumps(
        modules, sort_keys=True).encode("utf-8")).hexdigest()
    return {"format": "cur261-r11-source-tree-v1",
            "modules": modules, "n_modules": len(modules),
            "source_tree_digest": aggregate,
            "all_present": all(v != "MISSING" for v in modules.values())}


def write_r11_code_freeze(out_dir: Path, *, code_freeze_sha: str) -> dict:
    """记录 Implementation Freeze commit(§6;正式数据前调用一次)。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tree = source_tree_digest_r11()
    if not tree["all_present"]:
        raise RuntimeError("R11 源码树不完整(fail closed)")
    payload = {
        "format": "cur261-r11-code-freeze-v1",
        "iteration": "r11",
        "code_freeze_sha": code_freeze_sha,
        "source_tree_digest": tree["source_tree_digest"],
        "modules": tree["modules"],
        "contract": ("Commit A(Implementation Freeze):全部源码+测试已"
                     "提交且工作树 clean;正式 R11 audit/design/"
                     "calibration 数据开始后源码变化 -> R11 永久结束,"
                     "下一轮必须 R11(§6/§21)"),
    }
    (out_dir / "r11_code_freeze.json").write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    return payload


def verify_r11_code_freeze(out_dir: Path) -> dict[str, Any]:
    """复算源码树与冻结清单比对(每个正式阶段入口;漂移即 fail)。"""
    out_dir = Path(out_dir)
    path = out_dir / "r11_code_freeze.json"
    if not path.is_file():
        return {"pass": False,
                "error": "r11_code_freeze.json 不存在(正式数据开始前"
                         "必须先冻结;§6)"}
    frozen = json.loads(path.read_text(encoding="utf-8"))
    current = source_tree_digest_r11()
    drift = {name: {"frozen": h, "current": current["modules"].get(name)}
             for name, h in frozen["modules"].items()
             if current["modules"].get(name) != h}
    added = sorted(set(current["modules"]) - set(frozen["modules"]))
    removed = sorted(set(frozen["modules"]) - set(current["modules"]))
    return {
        "pass": bool(not drift and not added and not removed),
        "code_freeze_sha": frozen.get("code_freeze_sha"),
        "frozen_tree_digest": frozen.get("source_tree_digest"),
        "current_tree_digest": current["source_tree_digest"],
        "drifted_modules": sorted(drift),
        "added_modules": added,
        "removed_modules": removed,
    }
