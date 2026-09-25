#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R21 有效收集环境审计器(v4 受控 full 配置的运行期执行端)。

经执行端固定 argv(``-p r21_collection_auditor``,恰一对,值不可换)
注入同一 pytest 进程,在收集可以影响结果之前与完成之后对
**实际生效**的插件注册表与受控收集 hook 实现做来源分类:

  - pytest/pluggy 核心安装目录内的实现 → core(允许);
  - manifest 预批准的 pytest_generate_tests(文件+sha256 与
    执行端 manifest 一致)→ approved_generate_tests(允许);
  - 审计器自身(文件 sha 与 manifest 一致)→ auditor(允许);
  - 其余任何来源(导入式/别名/包装/外部注册/会话中途注册)
    → 违规:configure 阶段直接 UsageError 终止运行;更晚阶段
    把违规写入审计原件,由执行器/核验器在签发前无条件拒绝。

三阶段快照(configure / collection_finish / sessionfinish)逐字
落盘到 ``R21_AUDIT_OUT``;阶段间快照漂移(会话中途注册)同样违规。
环境接线(``R21_AUDIT_MANIFEST``/``R21_AUDIT_OUT`` 缺失、
PYTEST_DISABLE_PLUGIN_AUTOLOAD 未关、PYTEST_ADDOPTS/PYTEST_PLUGINS
在场)先于一切检查拒绝。

常量与 curriculum261_r17_admission_substance 保持同值,漂移由
test_admission_substance 交叉断言暴露。本模块只用标准库 + pytest
运行时对象,不导入项目源码,不触碰任何正式状态。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

AUDIT_FORMAT = "cur261-r22-collection-audit-v1"
AUDIT_STAGES = ("configure", "collection_finish", "sessionfinish")
#: 与 substance 模块同值(交叉断言防漂移)。
FILTERING_HOOKS = frozenset({
    "pytest_pycollect_makeitem", "pytest_collection_modifyitems",
    "pytest_ignore_collect", "pytest_collect_file",
    "pytest_collect_directory", "pytest_collection",
})
GENERATION_HOOKS = frozenset({"pytest_generate_tests"})
GUARDED_HOOKS = FILTERING_HOOKS | GENERATION_HOOKS

_STATE: dict = {"stages": [], "violations": [], "manifest": None,
                "out_path": None, "config": None}


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _core_roots() -> list[Path]:
    import pluggy
    return [Path(pytest.__file__).resolve().parent,
            Path(pluggy.__file__).resolve().parent]


def _module_of(plugin) -> str:
    if hasattr(plugin, "__module__"):
        module = sys.modules.get(getattr(plugin, "__module__"))
        if module is not None and hasattr(module, "__file__"):
            return str(Path(module.__file__).resolve())
    if hasattr(plugin, "__file__"):
        return str(Path(plugin.__file__).resolve())
    return ""


def _module_name(plugin) -> str:
    if hasattr(plugin, "__name__") and isinstance(plugin.__name__, str) \
            and not isinstance(plugin, type):
        return plugin.__name__
    return getattr(type(plugin), "__module__", "") or \
        getattr(plugin, "__module__", "")


def _origin_of(function) -> tuple[str, str, str]:
    code = getattr(function, "__code__", None)
    qualname = getattr(function, "__qualname__", "")
    if code is None or not code.co_filename:
        return "<nonfile>", "", qualname or repr(function)
    path = str(Path(code.co_filename).resolve())
    try:
        return path, _sha256_file(Path(path)), qualname
    except OSError:
        return path, "", qualname


def _core_roots() -> list[Path]:
    import _pytest
    import pluggy
    return [Path(pytest.__file__).resolve().parent,
            Path(_pytest.__file__).resolve().parent,
            Path(pluggy.__file__).resolve().parent]


def _snapshot(config) -> dict:
    core = _core_roots()
    plugins = []
    seen = set()
    for plugin in config.pluginmanager.get_plugins():
        module_name = _module_name(plugin)
        origin = _module_of(plugin)
        token = (module_name, origin)
        if token in seen:
            continue
        seen.add(token)
        plugins.append({"module": module_name, "origin_file": origin,
                        "origin_sha256": _sha256_file(Path(origin))
                        if origin and Path(origin).is_file() else "",
                        "classification": None})
    hooks: dict[str, list] = {}
    for name in sorted(GUARDED_HOOKS):
        caller = getattr(config.pluginmanager.hook, name, None)
        impls = []
        if caller is not None:
            for impl in caller.get_hookimpls():
                origin, sha, qualname = _origin_of(impl.function)
                impls.append({
                    "plugin_name": impl.plugin_name,
                    "qualname": qualname,
                    "origin_file": origin,
                    "origin_sha256": sha,
                    "opts": {key: impl.opts.get(key) for key in
                             ("hookwrapper", "tryfirst", "trylast")
                             if impl.opts.get(key)},
                })
        hooks[name] = impls
    return {"pytest_version": pytest.__version__,
            "python_version": sys.version.split()[0],
            "plugins": plugins, "hooks": hooks,
            "core_roots": [str(p) for p in core]}


def _classify(snapshot: dict, manifest: dict) -> list[dict]:
    violations: list[dict] = []
    core = snapshot["core_roots"]
    auditor_rel = manifest.get("auditor", {}).get("module", "")
    auditor_sha = manifest.get("auditor", {}).get("sha256", "")
    test_root = manifest.get("test_root", "")
    approved = manifest.get("approved_generate_tests", {})
    here = str(Path(__file__).resolve())

    def _is_core(path: str) -> bool:
        return bool(path) and any(path.startswith(root) for root in core)

    for plugin in snapshot["plugins"]:
        origin = plugin["origin_file"]
        if _is_core(origin):
            plugin["classification"] = "core"
        elif origin == here and (not auditor_sha
                                 or plugin["origin_sha256"] == auditor_sha):
            plugin["classification"] = "auditor"
        elif test_root and Path(origin).name == "conftest.py":
            try:
                rel = Path(origin).relative_to(Path.cwd()).as_posix()
            except ValueError:
                rel = ""
            if rel.startswith(test_root.rstrip("/") + "/"):
                plugin["classification"] = "conftest"
                plugin["deploy_relative"] = rel
            else:
                plugin["classification"] = "unapproved"
                violations.append({
                    "kind": "plugin_unapproved",
                    "module": plugin["module"],
                    "origin": origin[:300]})
        else:
            plugin["classification"] = "unapproved"
            violations.append({
                "kind": "plugin_unapproved",
                "module": plugin["module"],
                "origin": origin[:300]})
    used_approvals: set[str] = set()
    for hook, impls in snapshot["hooks"].items():
        for impl in impls:
            origin = impl["origin_file"]
            if _is_core(origin):
                continue
            if origin == here:
                continue
            rel = ""
            try:
                rel = Path(origin).relative_to(Path.cwd()).as_posix()
            except ValueError:
                rel = ""
            if hook in GENERATION_HOOKS and rel in approved \
                    and approved[rel] == impl["origin_sha256"]:
                used_approvals.add(rel)
                continue
            violations.append({
                "kind": "guarded_hook_origin_unapproved",
                "hook": hook,
                "origin": origin[:300],
                "qualname": impl["qualname"][:160]})
    for rel in sorted(set(approved) - used_approvals):
        violations.append({
            "kind": "approval_unused", "file": rel})
    return violations


def _env_violations() -> list[dict]:
    out = []
    if os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1":
        out.append({"kind": "autoload_not_disabled"})
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        if key in os.environ:
            out.append({"kind": "pytest_env_present", "key": key})
    return out
def _noncore_hooks(snapshot: dict) -> str:
    """快照中非核心(受控面)hook 实现集合的规范串;核心插件
    (logging/terminalreporter/funcmanage 等)在启动后期注册属
    pytest 正常生命周期,不构成漂移。"""
    core = snapshot.get("core_roots") or []
    out = {}
    for hook, impls in snapshot.get("hooks", {}).items():
        kept = [impl for impl in impls
                if not any(impl.get("origin_file", "").startswith(root)
                           for root in core)]
        if kept:
            out[hook] = kept
    return json.dumps(out, sort_keys=True)



def _write(stage: str, snapshot: dict, violations: list[dict],
           collected_items: int | None = None) -> None:
    row = {"stage": stage, "utc": _utc(), "pid": os.getpid(),
           "collected_items": collected_items,
           "snapshot": snapshot,
           "violations": violations}
    _STATE["stages"].append(row)
    _STATE["violations"].extend(violations)
    document = {
        "format": AUDIT_FORMAT,
        "pytest_args": list(sys.argv[1:]),
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "env": {"PYTEST_DISABLE_PLUGIN_AUTOLOAD":
                os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD"),
                "PYTEST_ADDOPTS": None,
                "PYTEST_PLUGINS": None},
        "manifest_path": _STATE.get("manifest_path"),
        "stages": _STATE["stages"],
        "violations": _STATE["violations"],
        "verdict": "pass" if not _STATE["violations"] else "violations",
    }
    path = _STATE["out_path"]
    if path is None:
        return
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(document, indent=1, ensure_ascii=False,
                              sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _load_manifest() -> dict:
    path = os.environ.get("R21_AUDIT_MANIFEST", "")
    out = os.environ.get("R21_AUDIT_OUT", "")
    if not path or not out:
        raise pytest.UsageError(
            "r21 auditor: R21_AUDIT_MANIFEST/R21_AUDIT_OUT missing")
    _STATE["out_path"] = Path(out)
    _STATE["manifest_path"] = path
    try:
        manifest = json.loads(
            Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise pytest.UsageError(
            f"r21 auditor: manifest unreadable: {exc}") from exc
    if not isinstance(manifest, dict) or set(
            manifest.get("filtering_hooks", ())) != FILTERING_HOOKS \
            or set(manifest.get("generation_hooks", ())) != GENERATION_HOOKS:
        raise pytest.UsageError(
            "r21 auditor: manifest guarded-hook sets mismatch")
    return manifest


def pytest_configure(config):
    manifest = _load_manifest()
    _STATE["manifest"] = manifest
    _STATE["config"] = config
    snapshot = _snapshot(config)
    violations = _env_violations() + _classify(snapshot, manifest)
    _write("configure", snapshot, violations)
    if violations:
        raise pytest.UsageError(
            "r21 auditor: effective collection environment violations: "
            + json.dumps(violations[:3], ensure_ascii=False))


def pytest_collection_finish(session):
    config = _STATE["config"]
    if config is None:
        return
    snapshot = _snapshot(config)
    reference = _STATE["stages"][0]["snapshot"] \
        if _STATE["stages"] else {}
    drift = []
    if reference and _noncore_hooks(reference) != _noncore_hooks(snapshot):
        drift.append({"kind": "hook_snapshot_drift",
                      "stage": "collection_finish"})
    violations = _classify(snapshot, _STATE["manifest"]) + drift
    _write("collection_finish", snapshot, violations,
           collected_items=len(getattr(session, "items", []) or []))
    if violations:
        raise RuntimeError(
            "r21 auditor: collection-stage violations: "
            + json.dumps(violations[:3], ensure_ascii=False))


def pytest_sessionfinish(session, exitstatus):
    config = _STATE["config"]
    if config is None:
        return
    snapshot = _snapshot(config)
    reference = _STATE["stages"][0]["snapshot"] \
        if _STATE["stages"] else {}
    drift = []
    if reference and _noncore_hooks(reference) != _noncore_hooks(snapshot):
        drift.append({"kind": "hook_snapshot_drift",
                      "stage": "sessionfinish"})
    violations = _classify(snapshot, _STATE["manifest"]) + drift
    _write("sessionfinish", snapshot, violations,
           collected_items=len(getattr(session, "items", []) or []))
