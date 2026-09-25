#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R24 注册异常部分安装闭合持久沙箱探针(A01-A06 证据采集端)。

审查反例(d872f41 partial_registration_failure):同一插件经公开
register 注册,filter(specname 别名)+release 钩子先装入、后置
非法签名触发 PluginValidationError;宿主捕获后过滤真实生效再公开
注销——pluggy 1.6.0 register 先写注册表再逐个 verify/装入,异常不
回滚,而 pytest 成功通知 pytest_plugin_registered 只在
super().register() 正常返回后发出,v5 成功通知路径对此零事件。

本探针在持久目录采集:

  步骤 0 机制锚定:目标环境版本 + register 源码序 + 裸管理器上
          的部分安装/零安装/公开注销真实行为(不经审计器)。
  步骤 1 无防护基线:partial("late") 树裸 pytest 收集/执行 +
          conftest 事件原件(审查 plugin_events 形状迁移)。
  步骤 2 真实执行器 × 四变体:late(过滤生效 rc=3)/immediate
          (立即清理 rc=4 违规粘住)/zero(零装入残留 rc=3)/
          rejected(前置失败 rc=0 eligible);每步断言审计文档
          与 append-only 流水的注册异常事件/违规/guard 行。
  步骤 3 合法链:canonical 树真实执行器 → 真签发器子进程 →
          消费 → 重复消费拒(v6 record + register_guard 绑定)。

退出码 0 = 全部期望成立;3 = 任一反例/正例偏离设计。原样保存
stdout/stderr/rc/摘要;不修改任何正式状态、不消费真实许可。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_STAGE = Path(__file__).resolve().parents[1]
_TESTS_DIR = REPO_STAGE / "tests" / "route_c_stage2_6_1"


def _load_support():
    spec = importlib.util.spec_from_file_location(
        "r24_support",
        _TESTS_DIR / "r17_admission_substance_test_support.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(index: dict, name: str, **row) -> None:
    row["finished_utc"] = _utc()
    index["steps"][name] = row
    print(name, json.dumps(row, ensure_ascii=False,
                           default=str)[:400])


def _run(command: list, cwd: Path, env: dict | None = None,
         timeout: int = 900):
    started = _utc()
    proc = subprocess.run(command, cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=timeout)
    return {"command": [str(token) for token in command],
            "cwd": str(cwd), "started_utc": started,
            "finished_utc": _utc(), "rc": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:]}


def _mechanism_anchor(support, out_dir: Path) -> dict:
    """步骤 0:目标环境机制锚定(版本/源码序/裸管理器行为)。"""
    import pytest
    import pluggy
    from _pytest.config import PytestPluginManager

    anchor = {
        "python": sys.version.split()[0],
        "pytest": pytest.__version__,
        "pluggy": pluggy.__version__,
        "register_source_order": {
            "name2plugin_before_impls": True,
            "evidence": "pluggy.PluginManager.register 先写 "
                        "_name2plugin[plugin_name] 再按 dir(plugin) "
                        "逐个 parse/verify/add_hookimpl;verify 抛 "
                        "PluginValidationError 时先前安装不回滚",
            "pytest_notification_after_super": True,
            "pytest_evidence": "PytestPluginManager.register 在 "
                               "super().register() 正常返回后才 "
                               "call_historic(pytest_plugin_registered)",
            "source_excerpt": (
                inspect.getsource(pluggy.PluginManager.register)
                + "\n--- PytestPluginManager.register ---\n"
                + inspect.getsource(PytestPluginManager.register)),
        },
    }

    class Partial:
        @pytest.hookimpl(specname="pytest_pycollect_makeitem",
                         tryfirst=True)
        def pytest_a_filter(self, collector, name, obj):
            return None

        @pytest.hookimpl(specname="pytest_collection_finish",
                         tryfirst=True)
        def pytest_b_release(self, session):
            pass

        @pytest.hookimpl(specname="pytest_configure")
        def pytest_z_invalid_signature(self, not_a_pytest_argument):
            pass

    class ZeroFirst:
        @pytest.hookimpl(specname="pytest_configure")
        def pytest_a_bad(self, not_a_pytest_argument):
            pass

    behavior = {}
    manager = PytestPluginManager()
    plugin = Partial()
    try:
        manager.register(plugin, "partial_registration")
        behavior["unexpected_success"] = True
    except pluggy.PluginValidationError as exc:
        behavior["error_type"] = type(exc).__name__
        behavior["remains_registered"] = manager.is_registered(plugin)
        callers = manager.get_hookcallers(plugin) or []
        behavior["installed_hooks"] = sorted(
            caller.name for caller in callers)
        behavior["filter_participates"] = (
            manager.hook.pytest_pycollect_makeitem(
                collector=None, name="x", obj=None) is None
            and any(impl.plugin is plugin
                    for impl in manager.hook
                    .pytest_pycollect_makeitem.get_hookimpls()))
    manager.unregister(plugin)
    behavior["after_unregister_is_registered"] = (
        manager.is_registered(plugin))
    zero = ZeroFirst()
    try:
        manager.register(zero, "zero_install")
        behavior["zero_unexpected_success"] = True
    except pluggy.PluginValidationError:
        behavior["zero_remains_registered"] = manager.is_registered(zero)
        behavior["zero_installed_hooks"] = sorted(
            caller.name for caller in
            (manager.get_hookcallers(zero) or []))
    anchor["bare_manager_behavior"] = behavior
    (out_dir / "mechanism_anchor.json").write_text(
        json.dumps(anchor, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return anchor


def _executor_case(support, out_dir: Path, variant: str,
                   env: dict) -> dict:
    base = out_dir / f"sandbox_{variant}"
    repo, commit_a, parent = support.git_repo_with_candidate(
        base, partial=variant)
    deploy = base / "deploy"
    support.sync_deploy_surface(repo, commit_a, deploy)
    raw = _run([sys.executable, "-m", "pytest",
                "tests/route_c_stage2_6_1", "-q"], deploy, env,
               timeout=300)
    events_path = deploy / "partial_plugin_events.jsonl"
    events = [json.loads(line) for line in
              events_path.read_text(encoding="utf-8").splitlines()
              if line.strip()] if events_path.is_file() else []
    run_dir = out_dir / f"executor_{variant}"
    run_dir_, summary, rc = support.run_executor(
        run_dir, repo, commit_a, deploy, expect_rc=(0, 3, 4))
    audit = json.loads(
        (run_dir / "audit_collection.json").read_text(encoding="utf-8"))
    lifecycle = audit["lifecycle"]
    stream = [json.loads(line) for line in
              (run_dir / "audit_collection.json.lifecycle.jsonl"
               ).read_text(encoding="utf-8").splitlines() if line.strip()]
    from rl_curriculum.curriculum261_r17_admission_substance import (
        SubstanceError, verify_regression_evidence)
    try:
        verify_regression_evidence(
            support.record_path(run_dir), repo, commit_a)
        verify_result = "UNEXPECTED-ACCEPT"
    except SubstanceError as exc:
        verify_result = str(exc)[:200]
    return {
        "variant": variant,
        "raw": raw,
        "conftest_events": events,
        "executor_rc": rc,
        "summary_ok": summary.get("ok"),
        "summary_error": (summary.get("error") or "")[:160],
        "audit_verdict": audit["verdict"],
        "audit_stages": [stage["stage"] for stage in audit["stages"]],
        "violation_kinds": sorted(
            {row["kind"] for row in lifecycle["violations"]}),
        "exception_events": [
            {key: event[key] for key in (
                "seq", "classification", "remains_registered",
                "installed_hooks", "error_type")}
            for event in lifecycle["events"]
            if event.get("phase") == "registration_exception"],
        "register_guard_doc": lifecycle.get("register_guard"),
        "register_guard_stream_rows": sum(
            1 for row in stream if row.get("kind") == "register_guard"),
        "verify_regression_evidence": verify_result,
        "originals": {
            "run_dir": str(run_dir),
            "record_sha256": _sha(support.record_path(run_dir)),
            "audit_sha256": _sha(run_dir / "audit_collection.json"),
            "lifecycle_stream_sha256": _sha(
                run_dir / "audit_collection.json.lifecycle.jsonl"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="新的持久输出目录(必须为空或不存在)")
    args = ap.parse_args(argv)
    out_dir = args.out_dir.resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit("refused: out-dir not empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO_STAGE / "src"))
    support = _load_support()

    index = {"format": "r24-partial-registration-probe-v1",
             "created_utc": _utc(), "interpreter": sys.executable,
             "cwd": os.getcwd(), "pid": os.getpid(), "steps": {}}
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("PYTEST_")}

    # ---- 步骤 0:机制锚定 ----------------------------------------
    anchor = _mechanism_anchor(support, out_dir)
    _record(index, "mechanism_anchor",
            behavior=anchor["bare_manager_behavior"],
            versions={key: anchor[key] for key in
                      ("python", "pytest", "pluggy")})

    # ---- 步骤 1/2:四变体(含无防护基线观察) -------------------
    for variant in ("late", "immediate", "zero", "rejected"):
        case = _executor_case(support, out_dir, variant, env)
        _record(index, f"executor_{variant}", **case)

    # ---- 步骤 3:合法链(canonical → 签发 → 消费 → 拒再消费) --
    legal_base = out_dir / "sandbox_legal"
    repo, commit_a, parent = support.git_repo_with_candidate(legal_base)
    deploy = legal_base / "deploy"
    support.sync_deploy_surface(repo, commit_a, deploy)
    run_l = out_dir / "executor_legal_run"
    _, summary_l, legal_rc = support.run_executor(
        run_l, repo, commit_a, deploy, expect_rc=(0,))
    record_l = support.record_path(run_l)
    state_l = deploy / "artifacts" / "route_c_stage2_6_1_repair18" / (
        "state")
    state_l.mkdir(parents=True, exist_ok=True)
    prereg = support.write_preregistration(
        legal_base / "prereg.json", repo, commit_a, record_l,
        admission_id="r24-probe-legal-0001")
    issue = _run([sys.executable,
                  str(support.runner_repo_path("r17_admission_issue.py")),
                  "--repo", str(repo), "--deploy-root", str(deploy),
                  "--state-root", str(state_l), "--commit-a", commit_a,
                  "--preregistration", str(prereg)], legal_base, env)
    from rl_curriculum.curriculum261_r17_admission import (
        enforce_formal_admission, validate_admission)
    ok, reason, _adm = validate_admission(
        deploy, state_l, commit_a, str(repo))
    consume = enforce_formal_admission(state_l, commit_a, str(repo))
    consume_again = enforce_formal_admission(state_l, commit_a,
                                             str(repo))
    legal_audit = json.loads(
        (run_l / "audit_collection.json").read_text(encoding="utf-8"))
    _record(index, "legal_chain", legal_rc=legal_rc,
            summary_ok=summary_l.get("ok"),
            record_format=json.loads(
                record_l.read_text(encoding="utf-8"))["format"],
            guard_bound=legal_audit["lifecycle"]["register_guard"],
            issue_rc=issue["rc"], issue=issue,
            validate_admission_ok=ok, validate_reason=reason,
            consume_result=consume, consume_again_result=consume_again)

    index["finished_utc"] = _utc()
    (out_dir / "index.json").write_text(
        json.dumps(index, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")

    steps = index["steps"]
    behavior = steps["mechanism_anchor"]["behavior"]
    ok_all = (
        behavior.get("error_type") == "PluginValidationError"
        and behavior.get("remains_registered") is True
        and behavior.get("installed_hooks") == [
            "pytest_collection_finish", "pytest_pycollect_makeitem"]
        and behavior.get("after_unregister_is_registered") is False
        and behavior.get("zero_remains_registered") is True
        and behavior.get("zero_installed_hooks") == []
        and steps["executor_late"]["executor_rc"] == 3
        and steps["executor_late"]["audit_verdict"] == "violations"
        and "lifecycle_registration_exception_partial_install"
        in steps["executor_late"]["violation_kinds"]
        and steps["executor_late"]["verify_regression_evidence"]
        != "UNEXPECTED-ACCEPT"
        and steps["executor_immediate"]["executor_rc"] in (3, 4)
        and "lifecycle_registration_exception_partial_install"
        in steps["executor_immediate"]["violation_kinds"]
        and steps["executor_zero"]["executor_rc"] == 3
        and "lifecycle_registration_exception_unclean"
        in steps["executor_zero"]["violation_kinds"]
        and steps["executor_rejected"]["executor_rc"] == 0
        and steps["executor_rejected"]["summary_ok"] is True
        and steps["executor_rejected"]["audit_verdict"] == "pass"
        and steps["legal_chain"]["legal_rc"] == 0
        and steps["legal_chain"]["summary_ok"] is True
        and steps["legal_chain"]["record_format"] == (
            "cur261-r17-candidate-regression-evidence-v6")
        and steps["legal_chain"]["issue_rc"] == 0
        and ok and consume is None
        and consume_again == "admission_already_consumed")
    print(json.dumps({"ok": bool(ok_all)}, ensure_ascii=False))
    return 0 if ok_all else 3


if __name__ == "__main__":
    sys.exit(main())
