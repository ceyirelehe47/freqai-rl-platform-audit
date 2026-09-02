# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R9:candidate evaluator 依赖身份闭环(§6)。

R8 硬输入(正式失败原因):
- R8 的 _evaluate_candidate_matched_r8 在函数体内延迟 import
  `from rl_curriculum.curriculum261_r6_pairs import c2_density_summary`,
  而该函数实际定义于 rl_curriculum.curriculum261_r5_pairs——模块
  import 与全部静态检查都不触发,直到 design plan 锁定后第一个
  candidate 真实评估时 ImportError 爆发,R8 按 §8.4 永久结束。

R9 修复(§6.2):
- 全部关键依赖在模块 import 时解析(见 curriculum261_r9_design 顶部
  import 块);
- 本模块声明依赖表并生成 dependency_resolution artifact:
  symbol / resolved module / source file hash / callable;
- 硬断言 c2_density_summary.__module__ ==
  "rl_curriculum.curriculum261_r5_pairs"。

§6.3 import sweep:plan lock 前运行 python -m compileall + import 全部
R9 模块 + resolve 全部声明符号 + construct evaluator(见
curriculum261_r9_preflight._dependency_resolution_ok_r9 与
curriculum261_r9_preplan 的真实 evaluator smoke)。
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable

#: §6.2 声明依赖表:(symbol, 定义模块)。模块级 import 发生在各消费
#: 模块顶部;本表是权威来源核对清单(resolved module 必须精确等于
#: 定义模块——re-export 会导致 __module__ 仍指向定义处,可检出)。
DEPENDENCY_TABLE_R9: tuple[tuple[str, str], ...] = (
    # ---- 密度(R8 ImportError 的直接修复)----
    ("c2_density_summary", "rl_curriculum.curriculum261_r5_pairs"),
    ("density_gate_r5", "rl_curriculum.curriculum261_r5_pairs"),
    # ---- pair 评估 / block 表 ----
    ("evaluate_pair_corpus_r4", "rl_curriculum.curriculum261_r4_pairs"),
    ("rung_report_r4", "rl_curriculum.curriculum261_r4_pairs"),
    ("build_c2_block_evidence_table",
     "rl_curriculum.curriculum261_r6_pairs"),
    ("block_gap_series", "rl_curriculum.curriculum261_r6_pairs"),
    ("simulate_formal_gate_pass_r6_matched",
     "rl_curriculum.curriculum261_r6_pairs"),
    # ---- cue 语义 ----
    ("candidate_cue_semantics",
     "rl_curriculum.curriculum261_r9_cue_eval"),
    ("semantic_cue_gate", "rl_curriculum.curriculum261_r9_cue_eval"),
    ("independent_cue_semantics",
     "rl_curriculum.curriculum261_r9_cue_eval"),
    # ---- 独立性 / 可观察性(冻结公共实现)----
    ("check_c2_local_cue_independence",
     "rl_curriculum.curriculum261_qualification"),
    ("check_c2_context_observability",
     "rl_curriculum.curriculum261_qualification"),
    # ---- matched 生成(R6 冻结)----
    ("generate_matched_block_with_attempts",
     "rl_curriculum.curriculum261_r6_tape"),
    ("generate_matched_block_once",
     "rl_curriculum.curriculum261_r6_tape"),
    ("block_attempt_statistics",
     "rl_curriculum.curriculum261_r6_tape"),
    # ---- 精确噪声重放 ----
    ("trace_matched_blocks",
     "rl_curriculum.curriculum261_r9_noise_replay"),
    ("matched_block_seed_of",
     "rl_curriculum.curriculum261_r9_noise_replay"),
    ("cue_event_trace",
     "rl_curriculum.curriculum261_r9_noise_replay"),
    # ---- reference long-label rate(R6 冻结;R8 曾延迟 import)----
    ("_reference_long_label_rate",
     "rl_curriculum.curriculum261_r6_design"),
)

#: §6.2 硬断言:c2_density_summary 的定义模块(不可协商)。
C2_DENSITY_SUMMARY_DEFINITION_MODULE = (
    "rl_curriculum.curriculum261_r5_pairs")


def _source_file_hash(obj: Any) -> tuple[str, str]:
    try:
        path = inspect.getsourcefile(obj)
    except TypeError:
        path = None
    if path is None or not Path(path).is_file():
        return ("unknown", "")
    return (str(Path(path).resolve()),
            hashlib.sha256(Path(path).read_bytes()).hexdigest())


def resolve_dependency_identity_r9() -> dict[str, Any]:
    """解析全部声明依赖并生成身份表(任何 unresolved symbol 在 plan
    lock 前暴露;§6.3)。"""
    rows: dict[str, Any] = {}
    problems: list[str] = []
    for symbol, module_name in DEPENDENCY_TABLE_R9:
        entry: dict[str, Any] = {
            "declared_module": module_name,
        }
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            entry.update({"importable": False, "error": str(exc)[:200]})
            problems.append(f"{symbol}:模块 {module_name} 导入失败:"
                            f"{str(exc)[:120]}")
            rows[symbol] = entry
            continue
        obj = getattr(mod, symbol, None)
        if obj is None:
            entry.update({"resolved": False})
            problems.append(
                f"{symbol}:模块 {module_name} 无该符号(R8 缺陷模式:"
                f"unresolved symbol)")
            rows[symbol] = entry
            continue
        actual_module = getattr(obj, "__module__", "")
        src, sha = _source_file_hash(obj)
        callable_ok = isinstance(obj, Callable)
        module_match = bool(actual_module == module_name)
        entry.update({
            "resolved": True,
            "resolved_module": actual_module,
            "module_matches_declaration": module_match,
            "source_file": src,
            "source_file_sha256": sha,
            "callable": callable_ok,
        })
        if not module_match:
            problems.append(
                f"{symbol}:resolved module {actual_module} != 声明 "
                f"{module_name}")
        if not callable_ok:
            problems.append(f"{symbol}:不可调用")
        rows[symbol] = entry
    density = rows.get("c2_density_summary", {})
    density_assert_ok = bool(
        density.get("resolved")
        and density.get("resolved_module")
        == C2_DENSITY_SUMMARY_DEFINITION_MODULE)
    if not density_assert_ok:
        problems.append(
            "硬断言失败:c2_density_summary.__module__ != "
            f"{C2_DENSITY_SUMMARY_DEFINITION_MODULE}(§6.2)")
    report = {
        "format": "cur261-r9-dependency-resolution-v1",
        "n_declared": len(DEPENDENCY_TABLE_R9),
        "dependencies": rows,
        "c2_density_summary_definition_module_assert":
            C2_DENSITY_SUMMARY_DEFINITION_MODULE,
        "c2_density_summary_assert_ok": density_assert_ok,
        "problems": problems,
        "pass": bool(density_assert_ok and not problems),
    }
    report["digest"] = dependency_identity_digest_r9(report)
    return report


def dependency_identity_digest_r9(report: dict[str, Any]) -> str:
    """依赖身份摘要(进入 design plan 的 code identity 链)。"""
    core = {
        "format": report.get("format"),
        "n_declared": report.get("n_declared"),
        "table": {s: {"declared_module": r.get("declared_module"),
                      "resolved_module": r.get("resolved_module"),
                      "source_file_sha256": r.get("source_file_sha256")}
                  for s, r in report.get("dependencies", {}).items()},
        "c2_density_summary_definition_module_assert":
            report.get("c2_density_summary_definition_module_assert"),
    }
    blob = json.dumps(core, sort_keys=True, ensure_ascii=False)
    return "r9dep-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def write_dependency_resolution_r9(out_dir: Path) -> dict[str, Any]:
    """生成 dependency_resolution.json(§32 artifact)。"""
    report = resolve_dependency_identity_r9()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dependency_resolution.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    return report
