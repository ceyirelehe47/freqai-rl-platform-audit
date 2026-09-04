# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R15:依赖身份闭环与 Code Freeze 合同(§6/§7.3/§21)。

两部分:
1. 依赖身份表(R9 §6 机制继承):plan lock 前对全部关键符号做模块级
   解析(live import),记录 resolved module / source sha256,
   生成 r15dep- digest —— blind-rename 继承的签名错误在此被显式核对;
2. R15 Code Freeze(§6/§21):正式数据开始前记录全部 R15 源码模块的
   sha256 清单(R15_CODE_FREEZE_SHA + source tree digest);每个正式
   阶段开始前复算,任何漂移 fail closed(永久结束 R15)。
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import subprocess
from pathlib import Path
from typing import Any

#: 声明依赖表:(symbol, 定义模块)。resolved module 必须精确等于定义
#: 模块(re-export 会导致 __module__ 指向 re-export 处,会被检出)。
#: 硬断言:c2_density_summary 必须定义于 R5(§6;R8 ImportError 教训)。
C2_DENSITY_SUMMARY_DEFINITION_MODULE = (
    "rl_curriculum.curriculum261_r5_pairs")

DEPENDENCY_TABLE_R15: tuple[tuple[str, str], ...] = (
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
    # ---- R6 runner(R15 wrapper 的委托目标;签名核对对象)----
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
    # ---- cue 语义(R15 namespace)----
    ("candidate_cue_semantics",
     "rl_curriculum.curriculum261_r15_cue_eval"),
    ("semantic_cue_gate", "rl_curriculum.curriculum261_r15_cue_eval"),
    ("independent_cue_semantics",
     "rl_curriculum.curriculum261_r15_cue_eval"),
    # ---- R15 新合同(核心修复面)----
    ("canonical_episode", "rl_curriculum.curriculum261_r15_reference"),
    ("reference_equivalence_run_r15",
     "rl_curriculum.curriculum261_r15_reference"),
    ("collect_policy_visible_dataset_r15",
     "rl_curriculum.curriculum261_r15_labels"),
    ("build_routing_r15", "rl_curriculum.curriculum261_r15_routing"),
    ("require_eval_routing_r15",
     "rl_curriculum.curriculum261_r15_routing"),
    ("orchestrate_calibration_stage_r15",
     "rl_curriculum.curriculum261_r15_orchestrator"),
    ("supervised_learnability_run_r15",
     "rl_curriculum.curriculum261_r15_calibration"),
    ("run_preplan_full_pipeline_rehearsal_r15",
     "rl_curriculum.curriculum261_r15_rehearsal"),
    ("live_signature_audit_r15",
     "rl_curriculum.curriculum261_r15_delegation"),
    ("delegation_ast_checks_r15",
     "rl_curriculum.curriculum261_r15_delegation"),
    # ---- R15 生成确定性合同(工作包 A)----
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
     "rl_curriculum.curriculum261_r15_determinism"),
    ("run_cross_process_determinism_matrix",
     "rl_curriculum.curriculum261_r15_determinism"),
    ("generation_determinism_gate",
     "rl_curriculum.curriculum261_r15_determinism"),
    # ---- R15 full-scale shadow(工作包 C)----
    ("run_full_scale_shadow_r15", "rl_curriculum.curriculum261_r15_shadow"),
    ("compare_full_scale_shadow_runs",
     "rl_curriculum.curriculum261_r15_shadow"),
    # ---- 独立性/可观察性(冻结公共实现)----
    ("check_c2_local_cue_independence",
     "rl_curriculum.curriculum261_qualification"),
    ("check_c2_context_observability",
     "rl_curriculum.curriculum261_qualification"),
)

#: R15 code freeze 覆盖的源码模块(sha256 清单;§6/§21)。
R15_CODE_MODULES: tuple[str, ...] = (
    "curriculum261_api.py",
    "curriculum261_generation_envelope.py",
    "curriculum261_r15_calibration.py",
    "curriculum261_r15_cli.py",
    "curriculum261_r15_cue_contract.py",
    "curriculum261_r15_cue_eval.py",
    "curriculum261_r15_delegation.py",
    "curriculum261_r15_dependencies.py",
    "curriculum261_r15_design.py",
    "curriculum261_r15_determinism.py",
    "curriculum261_r15_final.py",
    "curriculum261_r15_generation_evidence.py",
    "curriculum261_r15_global_k.py",
    "curriculum261_r15_historical.py",
    "curriculum261_r15_labels.py",
    "curriculum261_r15_namespaces.py",
    "curriculum261_r15_noise_replay.py",
    "curriculum261_r15_orchestrator.py",
    "curriculum261_r15_param_pack.py",
    "curriculum261_r15_plan.py",
    "curriculum261_r15_preflight.py",
    "curriculum261_r15_preplan.py",
    "curriculum261_r15_reference.py",
    "curriculum261_r15_rehearsal.py",
    "curriculum261_r15_routing.py",
    "curriculum261_r15_shadow.py",
    "curriculum261_r15_smoke.py",
)


def resolve_dependency_identity_r15() -> dict[str, Any]:
    """解析全部声明符号(fail closed:missing/错模块立即报错)。"""
    rows: dict[str, Any] = {}
    ok = True
    for symbol, defining_module in DEPENDENCY_TABLE_R15:
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
    from rl_curriculum.curriculum261_r15_calibration import (
        supervised_learnability_run_r15,
    )

    sig = inspect.signature(supervised_learnability_run_r15)
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
        "format": "cur261-r15-dependency-resolution-v1",
        "iteration": "r15", "symbols": rows,
        "dependencies": rows,
        "n_symbols": len(DEPENDENCY_TABLE_R15),
        "n_declared": len(DEPENDENCY_TABLE_R15),
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
    result["digest"] = dependency_identity_digest_r15(result)
    return result


def dependency_identity_digest_r15(resolution: dict[str, Any]) -> str:
    payload = json.dumps(resolution, sort_keys=True, ensure_ascii=False,
                         default=str)
    return "r15dep-" + hashlib.sha256(
        payload.encode("utf-8")).hexdigest()


def write_dependency_resolution_r15(out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    resolution = resolve_dependency_identity_r15()
    resolution["digest"] = dependency_identity_digest_r15(resolution)
    (out_dir / "dependency_resolution.json").write_text(
        json.dumps(resolution, indent=1, ensure_ascii=False, default=str),
        encoding="utf-8")
    return resolution


# ------------------------------------------------------- Code Freeze(§6)
#: R15 code freeze 覆盖的源码模块(sha256 清单;§6/§21)。
R15_CODE_MODULES: tuple[str, ...] = (
    "curriculum261_api.py",
    "curriculum261_generation_envelope.py",
    "curriculum261_r15_calibration.py",
    "curriculum261_r15_cli.py",
    "curriculum261_r15_cue_contract.py",
    "curriculum261_r15_cue_eval.py",
    "curriculum261_r15_delegation.py",
    "curriculum261_r15_dependencies.py",
    "curriculum261_r15_design.py",
    "curriculum261_r15_determinism.py",
    "curriculum261_r15_final.py",
    "curriculum261_r15_gate_topology.py",
    "curriculum261_r15_generation_evidence.py",
    "curriculum261_r15_global_k.py",
    "curriculum261_r15_historical.py",
    "curriculum261_r15_labels.py",
    "curriculum261_r15_namespaces.py",
    "curriculum261_r15_noise_replay.py",
    "curriculum261_r15_orchestrator.py",
    "curriculum261_r15_param_pack.py",
    "curriculum261_r15_plan.py",
    "curriculum261_r15_preflight.py",
    "curriculum261_r15_preplan.py",
    "curriculum261_r15_provenance.py",
    "curriculum261_r15_reference.py",
    "curriculum261_r15_rehearsal.py",
    "curriculum261_r15_routing.py",
    "curriculum261_r15_shadow.py",
    "curriculum261_r15_smoke.py",
    # R15 新增(§四/§六/§七):权威 workflow/阶段精确 fail closure/
    # full-cold reader(R14 清单曾遗漏 full_cold——R15 补齐)
    "curriculum261_r15_full_cold.py",
    "curriculum261_r15_workflow.py",
    "curriculum261_r15_fail_closure.py",
)

#: R15 Implementation Freeze 的完整覆盖面(§六:不得只哈希若干 src
#: 模块——必须覆盖所有可能影响正式执行/诊断/封存/报告的实现文件)。
#: dev 树(WSL 执行面)递归目录:
R15_FREEZE_DEV_DIRS: tuple[str, ...] = (
    "src/rl_curriculum",
    "tests/route_c_stage2_6_1",
)
#: dev 树单文件(RouteC strategy / 依赖锁 / 环境配置 / CLI 启动脚本):
R15_FREEZE_DEV_FILES: tuple[str, ...] = (
    "user_data/strategies/RouteCStrategy.py",
    "requirements-lock.txt",
    "environment.yml",
    "activate-freqtrade.sh",
)
#: release repo(Git 权威)freeze 路径(src/tests/runner;runner 含
#: 正式 CLI 启动脚本/failure closure writer/report gatherer/log
#: collector——R13 Commit B 混入 runner/*.py 的治理缺口由此闭合):
R15_FREEZE_REPO_PATHS: tuple[str, ...] = (
    "stage2_6_1/src",
    "stage2_6_1/tests/route_c_stage2_6_1",
    "stage2_6_1/runner",
)
#: 递归扫描时排除的运行副产品目录(非实现面;__pycache__ 的 .pyc
#: 是解释器产物,不是源码——源码 .py 本身始终在 manifest 内):
R15_FREEZE_EXCLUDE_DIRS: tuple[str, ...] = (
    "__pycache__", ".pytest_cache", ".cache")


def _freeze_dev_root() -> Path:
    import rl_curriculum

    return Path(rl_curriculum.__file__).resolve().parents[2]


def _freeze_release_repo() -> Path:
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if (cand / ".git").exists():
            return cand
    raise RuntimeError(
        "release repo 不可达:R15 freeze 需要 git 权威树"
        "(/mnt/e/trading/freqai-rl-audit 或 E:/trading/freqai-rl-audit)")


def _scan_freeze_dir(root: Path) -> dict[str, dict[str, Any]]:
    """递归扫描一个 dev 目录,产出 path -> {sha256,bytes,exec,symlink}。"""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if any(part in R15_FREEZE_EXCLUDE_DIRS
               for part in path.relative_to(root).parts):
            continue
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            out[rel] = {"symlink_target": os.readlink(path)}
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        out[rel] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "exec": bool(path.stat().st_mode & 0o111),
        }
    return out


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} 失败: {proc.stderr.strip()[:400]}")
    return proc.stdout


def _real_status_entries(repo: Path) -> list[str]:
    """freeze roots 下的真实变化行(过滤 CRLF normalization 噪音)。

    Windows/WSL 混合工作树中 git status 可能把仅行尾差异的文件报
    为 M(autocrlf);用 git diff --quiet(内容级,规范化后比较)
    复核,无内容差异的 M 行不视为漂移。untracked(??)与 staged
    变化直接算。
    """
    status = _git(repo, "status", "--porcelain", "-uall", "--",
                  *R15_FREEZE_REPO_PATHS)
    real: list[str] = []
    for line in status.splitlines():
        if not line.strip():
            continue
        real.append(line)
        if line.startswith("??"):
            continue
        path = line[3:].strip().strip(chr(34))
        # 仅当工作树 diff 与 staged diff 都无内容差异(纯行尾噪音;
        # --ignore-cr-at-eol 显式忽略 CR,兼容 Windows CRLF 工作树
        # +WSL 无 autocrlf 配置的场景)才剔除;任一存在真实差异即
        # 保留(fail closed)
        rcs = []
        for diff_args in (
                ["diff", "--ignore-cr-at-eol", "--quiet", "--", path],
                ["diff", "--cached", "--ignore-cr-at-eol", "--quiet",
                 "--", path]):
            proc = subprocess.run(
                ["git", "-C", str(repo), *diff_args],
                capture_output=True, text=True)
            rcs.append(proc.returncode)
        if all(rc == 0 for rc in rcs):
            real.pop()
    return real


def freeze_surface_manifest_r15() -> dict[str, Any]:
    """R15 全 freeze surface manifest(dev 递归 + repo Git identity)。

    fail closed 检出(§六):modified/added/removed/renamed(路径集
    变化)/untracked executable/source/symlink target drift/runner
    脚本漂移/tests 漂移。
    """
    dev_root = _freeze_dev_root()
    dev_files: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for d in R15_FREEZE_DEV_DIRS:
        p = dev_root / d
        if not p.is_dir():
            missing.append(d)
            continue
        for rel, entry in _scan_freeze_dir(p).items():
            dev_files[f"{d}/{rel}"] = entry
    for f in R15_FREEZE_DEV_FILES:
        p = dev_root / f
        if not p.is_file() and not p.is_symlink():
            missing.append(f)
            continue
        if p.is_symlink():
            dev_files[f] = {"symlink_target": os.readlink(p)}
        else:
            data = p.read_bytes()
            dev_files[f] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "exec": bool(p.stat().st_mode & 0o111),
            }

    repo = _freeze_release_repo()
    ls_files = _git(repo, "ls-files", "-s", "--", *R15_FREEZE_REPO_PATHS)
    tracked: dict[str, dict[str, str]] = {}
    for line in ls_files.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            mode, blob, _stage, path = parts[0], parts[1], parts[2], (
                line.split(None, 3)[3])
            tracked[path] = {"mode": mode, "blob": blob}
    head_commit = _git(repo, "rev-parse", "HEAD").strip()
    head_tree = _git(repo, "rev-parse", "HEAD^{tree}").strip()

    body = {
        "dev_files": dev_files,
        "repo_tracked": tracked,
        "repo_head_commit": head_commit,
        "repo_head_tree": head_tree,
    }
    digest = "r15fs-" + hashlib.sha256(json.dumps(
        body, sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    # R15 §四-8:workflow graph digest 进入 freeze manifest
    # (权威编排定义与 freeze 面绑定;verify 时重算比对)
    from rl_curriculum.curriculum261_r15_workflow import (
        r15_workflow_graph_digest,
    )
    return {
        "format": "cur261-r15-freeze-surface-v1",
        "dev_root": str(dev_root),
        "repo_root": str(repo),
        "dev_files": dev_files,
        "n_dev_files": len(dev_files),
        "repo_tracked": tracked,
        "n_repo_tracked": len(tracked),
        "repo_head_commit": head_commit,
        "repo_head_tree": head_tree,
        "missing_required": sorted(missing),
        "workflow_graph_digest": r15_workflow_graph_digest(),
        "freeze_surface_digest": digest,
    }


def source_tree_digest_r15() -> dict[str, Any]:
    """全部 R15 源码模块的 sha256 清单与聚合 digest(模块级子集)。"""
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    modules: dict[str, str] = {}
    for name in R15_CODE_MODULES:
        path = root / name
        modules[name] = (hashlib.sha256(path.read_bytes()).hexdigest()
                         if path.is_file() else "MISSING")
    aggregate = "r15src-" + hashlib.sha256(json.dumps(
        modules, sort_keys=True).encode("utf-8")).hexdigest()
    return {"format": "cur261-r15-source-tree-v1",
            "modules": modules, "n_modules": len(modules),
            "source_tree_digest": aggregate,
            "all_present": all(v != "MISSING" for v in modules.values())}


def write_r15_code_freeze(out_dir: Path, *, code_freeze_sha: str) -> dict:
    """记录 Implementation Freeze(§六全 surface;一次且仅一次;禁 A′)。

    R15 只有 Commit A(冻结)与 Commit B(结果)两个提交阶段:
    freeze 文件已存在 ⇒ 重复写入被拒绝(不存在 replacement freeze /
    hotfix-after-freeze 恢复路径;任何冻结后实现面变化 = R15 永久
    FAIL,下一轮必须 R16)。code_freeze_sha 必须等于 repo HEAD
    (即 Commit A 的 git commit sha)——冻结的就是这个提交。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "r15_code_freeze.json"
    if path.is_file():
        raise RuntimeError(
            "r15_code_freeze.json 已存在:Implementation Freeze 一次且"
            "仅一次(§六;禁止 A′/replacement freeze/hotfix-after-freeze;"
            "任何冻结后实现面变化 => R15 永久 FAIL,下一轮必须 R16)")
    manifest = freeze_surface_manifest_r15()
    if manifest["missing_required"]:
        raise RuntimeError(
            f"freeze surface 不完整(fail closed): 缺失 "
            f"{manifest['missing_required']}")
    if manifest["repo_head_commit"] != code_freeze_sha:
        raise RuntimeError(
            "code_freeze_sha 与 repo HEAD 不一致——冻结必须绑定"
            f"Commit A 提交(HEAD={manifest['repo_head_commit']},"
            f"传入={code_freeze_sha})")
    real_status = _real_status_entries(Path(manifest["repo_root"]))
    if real_status:
        raise RuntimeError(
            "repo freeze roots 存在未提交变化(fail closed;"
            "Commit A 要求工作树干净;CRLF-only 噪音已过滤):\n"
            + "\n".join(real_status)[:2000])
    payload = {
        "format": "cur261-r15-code-freeze-v1",
        "iteration": "r15",
        "code_freeze_sha": code_freeze_sha,
        "freeze_surface_digest": manifest["freeze_surface_digest"],
        "freeze_surface": manifest,
        "contract": ("Commit A(Implementation Freeze):全部实现面"
                     "(src/tests/runner/strategy/依赖锁/CLI 启动脚本)"
                     "已提交且工作树 clean;正式 R15 任何数据开始后"
                     "实现面变化(modified/added/removed/renamed/"
                     "untracked executable/symlink drift) -> R15 永久"
                     "结束,下一轮必须 R16(§六;不存在 A′/Commit A2/"
                     "hotfix after freeze)"),
    }
    (out_dir / "r15_code_freeze.json").write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    return payload


def verify_r15_code_freeze(out_dir: Path) -> dict[str, Any]:
    """复算全 freeze surface 与冻结 manifest 比对(漂移即 fail)。"""
    out_dir = Path(out_dir)
    path = out_dir / "r15_code_freeze.json"
    if not path.is_file():
        return {"pass": False,
                "error": "r15_code_freeze.json 不存在(正式数据开始前"
                         "必须先冻结;§六)"}
    frozen = json.loads(path.read_text(encoding="utf-8"))
    frozen_surface = frozen.get("freeze_surface") or {}
    frozen_files = frozen_surface.get("dev_files") or {}
    try:
        current = freeze_surface_manifest_r15()
    except Exception as exc:  # noqa: BLE001 —— fail closed
        return {"pass": False,
                "error": f"freeze_surface_manifest_r15 异常(fail "
                         f"closed): {type(exc).__name__}:{exc}"}
    cur_files = current["dev_files"]

    modified: dict[str, Any] = {}
    symlink_drift: list[str] = []
    exec_drift: list[str] = []
    for name, fentry in frozen_files.items():
        centry = cur_files.get(name)
        if centry is None:
            continue  # removed 集合统一处理
        if (fentry.get("symlink_target")
                or centry.get("symlink_target")):
            if fentry.get("symlink_target") != centry.get(
                    "symlink_target"):
                symlink_drift.append(name)
        elif fentry.get("sha256") != centry.get("sha256"):
            modified[name] = {"frozen": fentry.get("sha256"),
                              "current": centry.get("sha256")}
        if (fentry.get("exec") is not None
                and fentry.get("exec") != centry.get("exec")):
            exec_drift.append(name)
    added = sorted(set(cur_files) - set(frozen_files))
    removed = sorted(set(frozen_files) - set(cur_files))

    head_drift = bool(
        current["repo_head_commit"]
        != frozen_surface.get("repo_head_commit"))
    repo_tracked_drift = bool(
        current["repo_tracked"] != frozen_surface.get("repo_tracked"))

    try:
        status = "\n".join(_real_status_entries(
            Path(current["repo_root"])))
    except Exception as exc:  # noqa: BLE001
        return {"pass": False,
                "error": f"git status 失败(fail closed): {exc}"}
    head_ok = bool(current["repo_head_commit"]
                   == frozen.get("code_freeze_sha"))

    drift_types: list[str] = []
    if modified:
        drift_types.append("modified")
    if added:
        drift_types.append("added")
    if removed:
        drift_types.append("removed/renamed")
    if symlink_drift:
        drift_types.append("symlink_target_drift")
    if exec_drift:
        drift_types.append("exec_bit_drift")
    if head_drift or repo_tracked_drift:
        drift_types.append("repo_git_identity_drift")
    if status:
        drift_types.append("uncommitted_or_untracked_in_freeze_roots")

    return {
        "pass": bool(not drift_types and head_ok),
        "code_freeze_sha": frozen.get("code_freeze_sha"),
        "frozen_surface_digest": frozen.get("freeze_surface_digest"),
        "current_surface_digest": current["freeze_surface_digest"],
        "head_matches_commit_a": head_ok,
        "drift_types": drift_types,
        "modified_files": sorted(modified),
        "added_files": added,
        "removed_files": removed,
        "symlink_drift": symlink_drift,
        "exec_drift": exec_drift,
        "repo_status_in_freeze_roots": status[:2000],
        "n_frozen_dev_files": len(frozen_files),
        "n_current_dev_files": len(cur_files),
        "n_repo_tracked_files": current["n_repo_tracked"],
    }
