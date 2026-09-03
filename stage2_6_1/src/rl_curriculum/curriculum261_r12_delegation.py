# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R12:live signature audit 与委托合同(§7)。

R9 确认输入(两处调用错误):
- CLI:supervised_learnability_run_r9(v2_main, pack) 少 namespace →
  TypeError;
- wrapper 内部:_supervised_run(preproc_v2, pack, namespace, **kw)
  把 namespace 传进 R6 实现的第三位置参数 pairs_per_rung。

R12 修复(§7):
- supervised 入口 namespace / pairs_per_rung / train_pair_limit /
  model_seeds / training_config 全部 keyword-only;
- 所有跨版本 delegate 显式关键字(禁止第三位置参数);
- 本模块在 plan lock 前生成 delegation_signature_audit artifact:
  对 9 类 runner 用 inspect.signature 记录 wrapper/underlying 参数、
  keyword-only 集合、forwarded keywords、默认值、source file hash;
- AST 检查(§7.4):R12 源码中 supervised delegate 无第三位置参数、
  CLI/编排显式 namespace=、无 blind-rename 继承的旧错误形态。
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable

#: §7.3 live signature audit 覆盖表:
#: (用途, wrapper 符号, underlying 符号或 None, forwarded keywords,
#:  必须 keyword-only 的参数, 返回关键字段)
DELEGATION_TABLE_R12: tuple[tuple[str, str, str | None,
                                  tuple[str, ...], tuple[str, ...],
                                  tuple[str, ...]], ...] = (
    ("supervised runner",
     "rl_curriculum.curriculum261_r12_calibration:"
     "supervised_learnability_run_r12",
     None,
     ("namespace", "pairs_per_rung", "train_pair_limit", "model_seeds",
      "training_config"),
     ("namespace", "pairs_per_rung", "train_pair_limit", "model_seeds",
      "training_config"),
     ("pass", "families", "namespace", "label_contract",
      "label_alignment", "dataset_identity")),
    ("supervised mlp trainer",
     "rl_curriculum.ppo262_r2_supervised:train_supervised_mlp",
     None,
     ("control", "seed"),
     (),
     ("net",)),
    ("fit-bank builder",
     "rl_curriculum.curriculum261_r12_calibration:generate_fit_bank_r12",
     "rl_curriculum.curriculum261_r6_calibration:generate_fit_bank_r6",
     ("pairs_per_rung",),
     ("pairs_per_rung",),
     ()),
    ("preprocessor fit",
     "rl_curriculum.curriculum261_r12_calibration:"
     "fit_preprocessor_v2_from_bank_r12",
     "rl_curriculum.curriculum261_r6_calibration:"
     "fit_preprocessor_v2_from_bank_r6",
     ("records", "pairs_per_rung", "parameter_pack_identity"),
     ("parameter_pack_identity",),
     ()),
    ("C1/C3 corpus runner",
     "rl_curriculum.curriculum261_r12_calibration:"
     "run_calibration_corpus_c13_r12",
     "rl_curriculum.curriculum261_r6_calibration:"
     "run_calibration_corpus_c13_r6",
     ("pairs_per_rung",),
     ("pairs_per_rung",),
     ("seed_namespace", "families")),
    ("C2 matched runner",
     "rl_curriculum.curriculum261_r12_calibration:"
     "run_c2_matched_corpus_r12",
     "rl_curriculum.curriculum261_r6_calibration:"
     "run_c2_matched_corpus_r6",
     ("n_blocks",),
     ("n_blocks",),
     ("seed_namespace", "block_table", "pair_table")),
    ("C2 independent runner",
     "rl_curriculum.curriculum261_r12_calibration:"
     "run_c2_independent_corpus_r12",
     "rl_curriculum.curriculum261_r6_calibration:"
     "run_c2_independent_corpus_r6",
     ("pairs_per_rung",),
     ("pairs_per_rung",),
     ("seed_namespace",)),
    ("semantic runner",
     "rl_curriculum.curriculum261_r12_calibration:"
     "run_c2_semantic_corpus_r12",
     None,
     ("n_blocks", "out_dir", "artifact_name"),
     ("n_blocks", "out_dir", "artifact_name"),
     ("pass", "shared", "n_blocks")),
    ("robustness builder",
     "rl_curriculum.curriculum261_r12_orchestrator:"
     "preprocessing_robustness_checks_r12",
     None,
     ("profile", "ledger"),
     ("profile", "ledger"),
     ("checks", "pass", "routing_matrix")),
    ("final runner",
     "rl_curriculum.curriculum261_r12_final:run_final_qualification_r12",
     None,
     ("vendor_dir",),
     (),
     ("verdict",)),
    ("full-scale shadow runner",
     "rl_curriculum.curriculum261_r12_shadow:run_full_scale_shadow_r12",
     None,
     ("run_tag",),
     ("run_tag",),
     ("orchestration_stage_completed", "final_like_executed")),
    ("shadow comparison runner",
     "rl_curriculum.curriculum261_r12_shadow:compare_full_scale_shadow_runs",
     None,
     (),
     (),
     ("pass", "ledger_identity_digests_identical")),
    ("determinism matrix runner",
     "rl_curriculum.curriculum261_r12_determinism:"
     "run_cross_process_determinism_matrix",
     None,
     (),
     (),
     ("pass", "scenarios")),
)

#: §7.4 AST 检查的 R12 模块(源码级委托合同)。
AST_MODULES_R12: tuple[str, ...] = (
    "curriculum261_r12_calibration.py",
    "curriculum261_r12_cli.py",
    "curriculum261_r12_orchestrator.py",
    "curriculum261_r12_final.py",
    "curriculum261_r12_labels.py",
    "curriculum261_r12_rehearsal.py",
    "curriculum261_r12_shadow.py",
)


def _resolve(symbol: str) -> Any:
    mod_name, attr = symbol.split(":")
    import importlib

    mod = importlib.import_module(mod_name)
    return getattr(mod, attr)


def _source_sha256(obj: Any) -> tuple[str, int]:
    path = inspect.getsourcefile(obj)
    src = Path(path).read_bytes()
    return hashlib.sha256(src).hexdigest(), len(inspect.getsourcelines(obj)[0])


def _signature_facts(fn: Callable) -> dict[str, Any]:
    sig = inspect.signature(fn)
    params: dict[str, Any] = {}
    keyword_only: list[str] = []
    for name, p in sig.parameters.items():
        params[name] = {
            "kind": str(p.kind).split(".")[-1],
            "default": None if p.default is inspect.Parameter.empty
            else repr(p.default),
        }
        if p.kind is inspect.Parameter.KEYWORD_ONLY:
            keyword_only.append(name)
    return {
        "parameters": params,
        "keyword_only": sorted(keyword_only),
        "n_positional_params": int(sum(
            1 for p in sig.parameters.values()
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                          inspect.Parameter.POSITIONAL_OR_KEYWORD))),
    }


def live_signature_audit_r12() -> dict[str, Any]:
    """§7.3:plan lock 前的委托检查(全部模块级解析,fail closed)。"""
    entries: list[dict[str, Any]] = []
    all_ok = True
    for (use, wrapper_sym, underlying_sym, forwarded,
         must_kwonly, return_keys) in DELEGATION_TABLE_R12:
        wrapper = _resolve(wrapper_sym)
        wf = _signature_facts(wrapper)
        sha, n_lines = _source_sha256(wrapper)
        entry: dict[str, Any] = {
            "use": use,
            "wrapper": wrapper_sym,
            "wrapper_signature": wf,
            "wrapper_source_sha256": sha,
            "wrapper_source_lines": n_lines,
            "forwarded_keywords": list(forwarded),
            "expected_return_keys": list(return_keys),
            "checks": {},
        }
        ok = True
        # keyword-only 合同
        missing_kwonly = [k for k in must_kwonly
                          if k not in wf["keyword_only"]]
        if must_kwonly:
            entry["checks"]["keyword_only_enforced"] = not missing_kwonly
            entry["checks"]["keyword_only_missing"] = missing_kwonly
            ok = ok and not missing_kwonly
        # forwarded keywords 必须存在于 wrapper 签名
        unknown = [k for k in forwarded if k not in wf["parameters"]]
        entry["checks"]["forwarded_keywords_declared"] = not unknown
        entry["checks"]["forwarded_keywords_unknown"] = unknown
        ok = ok and not unknown
        # underlying 签名核对(禁止位置参数错传:forwarded 名称必须存在)
        if underlying_sym is not None:
            underlying = _resolve(underlying_sym)
            uf = _signature_facts(underlying)
            entry["underlying"] = underlying_sym
            entry["underlying_signature"] = uf
            usha, _ = _source_sha256(underlying)
            entry["underlying_source_sha256"] = usha
            fwd_missing = [k for k in forwarded
                           if k not in uf["parameters"]]
            entry["checks"]["forwarded_keywords_in_underlying"] = \
                not fwd_missing
            entry["checks"]["forwarded_keywords_missing_underlying"] = \
                fwd_missing
            ok = ok and not fwd_missing
        entry["checks"]["pass"] = bool(ok)
        all_ok = all_ok and ok
        entries.append(entry)
    digest_payload = json.dumps(entries, sort_keys=True,
                                ensure_ascii=False)
    return {
        "format": "cur261-r12-delegation-signature-audit-v1",
        "iteration": "r12",
        "entries": entries,
        "all_pass": bool(all_ok),
        "digest": "r12sig-" + hashlib.sha256(
            digest_payload.encode("utf-8")).hexdigest(),
    }


# ---------------------------------------------------------- AST 检查(§7.4)
def _ast_call_violations(tree: ast.AST, src_name: str) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = None
        if isinstance(fn, ast.Name):
            name = fn.id
        elif isinstance(fn, ast.Attribute):
            name = fn.attr
        if name == "supervised_learnability_run_r12":
            # §7.4:CLI/编排必须显式传 namespace=
            kw_names = [k.arg for k in node.keywords]
            if "namespace" not in kw_names:
                violations.append(
                    f"{src_name}:supervised_learnability_run_r12 调用"
                    f"缺少显式 namespace= 关键字(第 {node.lineno} 行)")
            if len(node.args) > 2:
                violations.append(
                    f"{src_name}:supervised_learnability_run_r12 调用"
                    f"存在第三位置参数(第 {node.lineno} 行)")
            if "pairs_per_rung" in kw_names and len(node.args) >= 3:
                violations.append(
                    f"{src_name}:pairs_per_rung 不得按位置传递"
                    f"(第 {node.lineno} 行)")
        if name in ("_supervised_mlp", "_train_supervised_mlp",
                    "train_supervised_mlp"):
            kw_names = [k.arg for k in node.keywords]
            if len(node.args) > 2:
                violations.append(
                    f"{src_name}:{name} 委托存在第三位置参数"
                    f"(第 {node.lineno} 行;seed/control 必须关键字)")
            if "seed" in kw_names and len(node.args) >= 4:
                violations.append(
                    f"{src_name}:{name} seed 不得按位置传递"
                    f"(第 {node.lineno} 行)")
    return violations


def delegation_ast_checks_r12() -> dict[str, Any]:
    """§7.4 AST/源码测试的运行时入口(plan lock 前置与测试共用)。"""
    import rl_curriculum

    pkg_dir = Path(rl_curriculum.__file__).parent
    violations: list[str] = []
    scanned: list[str] = []
    for mod in AST_MODULES_R12:
        path = pkg_dir / mod
        if not path.is_file():
            violations.append(f"{mod}:文件不存在(AST 检查 fail closed)")
            continue
        scanned.append(mod)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        violations.extend(_ast_call_violations(tree, mod))
    # R6 旧错误形态的负向断言:R12 模块不得复现
    # _supervised_run(preproc, pack, namespace) 位置第三参(来自 R9 的
    # wrapper 源码模式);R12 的 supervised 实现不经位置参数委托。
    calib = (pkg_dir / "curriculum261_r12_calibration.py")
    if calib.is_file():
        src = calib.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(
                    node.func, ast.Name) \
                    and node.func.id.startswith("_supervised") \
                    and len(node.args) >= 3:
                violations.append(
                    f"curriculum261_r12_calibration.py:"
                    f"{node.func.id} 委托存在第三位置参数"
                    f"(第 {node.lineno} 行;R9 同型错误)")
    return {
        "format": "cur261-r12-delegation-ast-checks-v1",
        "iteration": "r12",
        "scanned_modules": scanned,
        "violations": violations,
        "pass": not violations,
    }


def calibration_call_contract_payload() -> dict[str, Any]:
    """§30 calibration_call_contract:调用合同的可审计表示。"""
    return {
        "format": "cur261-r12-calibration-call-contract-v1",
        "iteration": "r12",
        "r9_defects_closed": [
            "CLI supervised 调用缺 namespace(TypeError)",
            "wrapper 第三位置参数把 namespace 传进 pairs_per_rung",
            "supervised 标签 = raw reference policy on scaled obs",
            "holdout 评估三处错传 v2_main",
        ],
        "supervised_entrypoint": {
            "symbol": ("rl_curriculum.curriculum261_r12_calibration"
                       ".supervised_learnability_run_r12"),
            "keyword_only": ["namespace", "pairs_per_rung",
                             "train_pair_limit", "model_seeds",
                             "training_config"],
            "positional_params": ["preproc_v2", "pack"],
            "third_positional_param_forbidden": True,
            "delegate_style": "explicit keywords only",
        },
        "label_contract": "PolicyVisibleSupervisedLabel-v1",
        "label_source": "canonical_reference_on_canonical_obs",
    }
