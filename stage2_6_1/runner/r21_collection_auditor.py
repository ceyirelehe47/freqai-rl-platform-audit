#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R21 有效收集环境审计器(v5 受控 full 配置的运行期执行端)。

经执行端固定 argv(``-p r21_collection_auditor``,恰一对,值不可换)
注入同一 pytest 进程,以两层互补防线核验**实际生效**的插件注册表
与受控收集 hook 实现的来源:

  第一层(三阶段快照,v4 既有):configure / collection_finish /
  sessionfinish 各做一次实际注册表快照并做来源分类——pytest/
  pluggy 核心安装目录内的实现 → core(允许);manifest 预批准的
  pytest_generate_tests → approved_generate_tests(允许);审计器
  自身(文件 sha 与 manifest 一致)→ auditor(允许);其余任何来源
  → 违规。阶段间快照漂移(会话中途注册后仍在场)同样违规。

  第二层(插件生命周期,v5 新增,R23/102e9b2 审查反例):实现
  ``pytest_plugin_registered``(pluggy historic 钩子)。本审计器
  经 ``-p`` 在 preparse 期注册,pluggy 对 historic 钩子重放此前
  全部注册事件,其后每次注册实时通知——因此**进程内每一次
  ``PytestPluginManager.register()`` 都有一条不可撤回的事件记录**:

    - 分类按实际对象来源(定义模块文件),不以注册名字符串、
      方法名拼写或 AST 文本替代;``hookimpl(specname=...)`` 别名
      经 ``impl.plugin is plugin`` 对实际 HookImpl 对象判归属。
    - 临时插件(会话中途注册、影响收集、随后注销)在三阶段快照
      之间出现的注册事件永久落盘(append-only JSONL +
      审计文档内嵌),注销/清理/末尾快照干净都不能消除该事实;
      违规后 verdict 永久为 violations,由执行器/核验器/签发器
      在准入前无条件拒绝。
    - configure 阶段做覆盖对账:快照内每个在场插件必须已有对应
      注册事件(重放或实时),否则 lifecycle_monitor_incomplete
      (fail closed:监测未建立/信息不足不按通过处理)。
    - 正常核心插件的后期注册(funcmanage/logging-plugin/
      terminalreporter 等)分类为 core,不构成违规;合法
      conftest 模块注册(含已批准 pytest_generate_tests)不受
      影响。

环境接线(``R21_AUDIT_MANIFEST``/``R21_AUDIT_OUT`` 缺失、
PYTEST_DISABLE_PLUGIN_AUTOLOAD 未关、PYTEST_ADDOPTS/PYTEST_PLUGINS
在场)先于一切检查拒绝。常量与 curriculum261_r17_admission_substance
保持同值,漂移由 test_admission_substance 交叉断言暴露。本模块
只用标准库 + pytest/pluggy 运行时对象,不导入项目源码,不触碰
任何正式状态。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import time
from pathlib import Path

import pytest

AUDIT_FORMAT = "cur261-r23-collection-audit-v2"
AUDIT_STAGES = ("configure", "collection_finish", "sessionfinish")
#: 生命周期监测钩子(pluggy historic;先于本模块注册的插件经重放
#: 覆盖,其后注册实时通知)。实测锚定 pytest 9.1.1
#: PytestPluginManager.register():super().register 成功后
#: call_historic(kwargs=dict(plugin, plugin_name, manager))。
LIFECYCLE_HOOK = "pytest_plugin_registered"
#: 与 substance 模块同值(交叉断言防漂移)。
FILTERING_HOOKS = frozenset({
    "pytest_pycollect_makeitem", "pytest_collection_modifyitems",
    "pytest_ignore_collect", "pytest_collect_file",
    "pytest_collect_directory", "pytest_collection",
})
GENERATION_HOOKS = frozenset({"pytest_generate_tests"})
GUARDED_HOOKS = FILTERING_HOOKS | GENERATION_HOOKS

_STATE: dict = {"stages": [], "violations": [], "manifest": None,
                "out_path": None, "config": None,
                "lifecycle": {"monitor": None, "events": [],
                              "violations": [], "reconcile": None}}


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _core_roots() -> list[Path]:
    import _pytest
    import pluggy
    return [Path(pytest.__file__).resolve().parent,
            Path(_pytest.__file__).resolve().parent,
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


# ---------------------------------------------------------------- 生命周期
def _lifecycle_log_path() -> Path:
    return Path(str(_STATE["out_path"]) + ".lifecycle.jsonl")


def _append_lifecycle_lines(rows: list[dict]) -> None:
    """append-only 事件/违规流水:先于任何内存状态变更之外落盘,
    进程中断/末尾清理都不能撤销已记录事实。"""
    path = _lifecycle_log_path()
    line = "".join(json.dumps(row, ensure_ascii=False,
                              sort_keys=True) + "\n" for row in rows)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()


def _guarded_impls_for(plugin, manager) -> list[dict]:
    """该**实际注册对象**绑定的受控 hook 实现(经 pluggy HookImpl
    的 plugin 身份判归属;specname 别名同样命中)。"""
    out: list[dict] = []
    for name in sorted(GUARDED_HOOKS):
        caller = getattr(manager.hook, name, None)
        if caller is None:
            continue
        for impl in caller.get_hookimpls():
            if impl.plugin is not plugin:
                continue
            origin, sha, qualname = _origin_of(impl.function)
            specname = (impl.opts.get("specname")
                        if isinstance(impl.opts, dict) else None) \
                or getattr(impl, "specname", "") or ""
            out.append({
                "hook": name,
                "specname": specname or "",
                "qualname": qualname[:160],
                "origin_file": origin,
                "origin_sha256": sha,
            })
    return out


def _classify_registered(plugin, plugin_name: str,
                         manifest: dict) -> tuple[str, str]:
    """按实际对象来源分类一次注册(与快照分类同规则)。

    conftest 分类仅给予 conftest **模块**本身的注册(pytest 以模块
    对象注册 conftest);从 conftest 文件实例化的其他对象(审查反例
    的 sessionstart 临时插件类)不因来源文件名获得 conftest 待遇。
    """
    origin = _module_of(plugin)
    core = _core_roots()
    if origin and any(origin.startswith(str(root)) for root in core):
        return "core", ""
    here = str(Path(__file__).resolve())
    auditor_sha = manifest.get("auditor", {}).get("sha256", "")
    if origin == here and (not auditor_sha
                           or _sha256_file(Path(origin)) == auditor_sha):
        return "auditor", ""
    test_root = manifest.get("test_root", "")
    if test_root and inspect.ismodule(plugin) \
            and Path(origin).name == "conftest.py":
        try:
            rel = Path(origin).relative_to(Path.cwd()).as_posix()
        except ValueError:
            rel = ""
        if rel.startswith(test_root.rstrip("/") + "/"):
            return "conftest", rel
    return "unapproved", ""


def _handle_registration(plugin, plugin_name: str, manager) -> None:
    if _STATE["manifest"] is None:
        _STATE["manifest"] = _load_manifest()
    if _STATE["out_path"] is None:
        out = os.environ.get("R21_AUDIT_OUT", "")
        _STATE["out_path"] = Path(out) if out else None
    lifecycle = _STATE["lifecycle"]
    if lifecycle["monitor"] is None:
        lifecycle["monitor"] = {
            "hook": LIFECYCLE_HOOK,
            "established_utc": _utc(),
            "pid": os.getpid(),
            "note": "pluggy historic replay covers registrations "
                    "before this module; live calls cover the rest",
        }
        _append_lifecycle_lines(
            [{"kind": "monitor", **lifecycle["monitor"]}])
    classification, rel = _classify_registered(
        plugin, plugin_name, _STATE["manifest"])
    guarded = _guarded_impls_for(plugin, manager)
    event = {
        "seq": len(lifecycle["events"]),
        "utc": _utc(),
        "plugin_name": str(plugin_name)[:200],
        "module": _module_name(plugin)[:200],
        "origin_file": _module_of(plugin)[:300],
        "classification": classification,
        "deploy_relative": rel,
        "guarded_hooks": [row["hook"] for row in guarded],
    }
    lifecycle["events"].append(event)
    pending: list[dict] = [{"kind": "event", **event}]
    violation = None
    if classification == "core":
        pass
    elif classification == "auditor":
        pass
    elif classification == "conftest":
        # conftest 模块自身的受控 hook 与静态预批准同规则:
        # 过滤 hook 零容忍;generate_tests 须与批准表逐字节一致。
        approved = _STATE["manifest"].get("approved_generate_tests", {})
        for row in guarded:
            if row["hook"] in FILTERING_HOOKS:
                violation = {
                    "kind": "lifecycle_conftest_filtering_hook",
                    "plugin_name": event["plugin_name"],
                    "hook": row["hook"],
                    "origin": row["origin_file"][:300]}
                break
            if row["hook"] in GENERATION_HOOKS and not (
                    rel in approved
                    and approved[rel] == row["origin_sha256"]):
                violation = {
                    "kind": "lifecycle_generate_tests_unapproved",
                    "plugin_name": event["plugin_name"],
                    "hook": row["hook"],
                    "origin": row["origin_file"][:300]}
                break
    else:
        # 未知来源对象:绑定任何受控 hook(含 specname 别名)即违规;
        # 无受控 hook 的未知注册同样违规(与快照在场语义一致)。
        if guarded:
            violation = {
                "kind": "lifecycle_guarded_hook_registration",
                "plugin_name": event["plugin_name"],
                "hooks": [row["hook"] for row in guarded],
                "specnames": [row["specname"] for row in guarded],
                "origin": event["origin_file"]}
        else:
            violation = {
                "kind": "lifecycle_unapproved_registration",
                "plugin_name": event["plugin_name"],
                "origin": event["origin_file"]}
    if violation is not None:
        lifecycle["violations"].append(violation)
        _STATE["violations"].append(violation)
        pending.append({"kind": "violation", "violation": violation})
    try:
        _append_lifecycle_lines(pending)
    except OSError as exc:
        fallback = {"kind": "lifecycle_log_write_failed",
                    "error": repr(exc)[:200]}
        lifecycle["violations"].append(fallback)
        _STATE["violations"].append(fallback)
    if violation is not None and _STATE["stages"]:
        # 审计文档只在首个阶段写入后存在;configure 前中止的运行
        # 不产生"无违规"残文档(事实在 JSONL,文档缺失即 fail closed)。
        _flush_document()


def pytest_plugin_registered(plugin, plugin_name, manager):
    """每次插件注册的不可撤回检查点(historic 重放 + 实时)。

    除环境接线错误(UsageError)外不抛出:违规以落盘事实 + 永久
    verdict=violations 表达,终止权交给执行器/签发器;注册方捕获
    异常、随即注销、末尾注册表干净都不能消除已记录事实。
    """
    try:
        _handle_registration(plugin, plugin_name, manager)
    except pytest.UsageError:
        raise
    except Exception as exc:  # noqa: BLE001 —— 监测自身缺陷 fail-closed
        lifecycle = _STATE["lifecycle"]
        fallback = {"kind": "lifecycle_monitor_internal_error",
                    "error": repr(exc)[:300]}
        lifecycle["violations"].append(fallback)
        _STATE["violations"].append(fallback)
        try:
            _append_lifecycle_lines(
                [{"kind": "violation", "violation": fallback}])
        except OSError:
            pass
        if _STATE["stages"]:
            _flush_document()


def _reconcile_lifecycle(snapshot: dict) -> dict:
    """configure 对账:快照内每个在场插件的来源文件必须已有注册
    事件(重放或实时);无事件 ⇒ 监测未建立/覆盖不全,fail closed。"""
    lifecycle = _STATE["lifecycle"]
    event_origins = {event["origin_file"] for event in lifecycle["events"]}
    uncovered = sorted({
        (plugin.get("origin_file") or "")[:200]
        for plugin in snapshot.get("plugins", [])
        if plugin.get("origin_file")
        and plugin["origin_file"] not in event_origins})
    report = {
        "stage": "configure",
        "snapshot_plugins": len(snapshot.get("plugins", [])),
        "lifecycle_events": len(lifecycle["events"]),
        "uncovered": uncovered,
    }
    if uncovered:
        violation = {"kind": "lifecycle_monitor_incomplete",
                     "uncovered": uncovered[:3]}
        lifecycle["violations"].append(violation)
        _STATE["violations"].append(violation)
        try:
            _append_lifecycle_lines(
                [{"kind": "violation", "violation": violation}])
        except OSError:
            pass
    return report


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
                        "plugin_name": str(
                            config.pluginmanager.get_name(plugin)
                            or "")[:200],
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
                             ("hookwrapper", "tryfirst", "trylast",
                              "specname")
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


def _document() -> dict:
    lifecycle = _STATE["lifecycle"]
    return {
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
        "lifecycle": {
            "monitor": lifecycle["monitor"],
            "events": lifecycle["events"],
            "violations": lifecycle["violations"],
            "reconcile": lifecycle["reconcile"],
        },
        "violations": _STATE["violations"],
        "verdict": "pass" if not _STATE["violations"] else "violations",
    }


def _flush_document() -> None:
    path = _STATE["out_path"]
    if path is None:
        return
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(_document(), indent=1, ensure_ascii=False,
                              sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write(stage: str, snapshot: dict, violations: list[dict],
           collected_items: int | None = None) -> None:
    row = {"stage": stage, "utc": _utc(), "pid": os.getpid(),
           "collected_items": collected_items,
           "snapshot": snapshot,
           "violations": violations}
    _STATE["stages"].append(row)
    _STATE["violations"].extend(violations)
    _flush_document()


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
    if _STATE["lifecycle"]["monitor"] is None:
        # 防御:注册通知一次都没到过(钩子未生效/环境异常)⇒ 不通过。
        violation = {"kind": "lifecycle_monitor_not_established"}
        _STATE["lifecycle"]["violations"].append(violation)
        _STATE["violations"].append(violation)
    snapshot = _snapshot(config)
    _STATE["lifecycle"]["reconcile"] = _reconcile_lifecycle(snapshot)
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


def pytest_unconfigure(config):
    """封口重放:sessionfinish 之后的任何注册事件也进入最终文档,
    保证文档事件集 == JSONL 事件集(核验器按严格相等检查)。"""
    if _STATE["stages"]:
        _flush_document()
