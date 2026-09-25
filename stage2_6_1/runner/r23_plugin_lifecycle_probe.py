#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R23 插件生命周期闭合持久沙箱探针(A01-A05 证据采集端)。

一次性驱动器:在**新的持久输出目录**内迁移 102e9b2 审查反例
(probe_cases/scoped_specname:pytest_sessionstart 注册 hookimpl
specname 别名临时插件 → 实际过滤失败参数实例 →
pytest_collection_finish tryfirst 注销),并用真实项目链路取证:

  步骤 1 无防护基线:同树同完整目录命令直跑 pytest(无审计器),
        对照数字(11 项含 1 失败 → 10 项全绿)落盘;
  步骤 2 真实执行器:runner/r21_full_collection_regression.py 在
        同一部署面采集 v5 record——收集 rc=0 但审计 verdict=
        violations(lifecycle_guarded_hook_registration)⇒ summary
        fail-closed、执行器 rc=3;同源核验器 verify_regression_
        evidence 拒绝原件留档;
  步骤 3 合法对照:canonical 树(parametrize/参数化 fixture/已批准
        pytest_generate_tests)真实执行器全绿(v5 record)→
        真实签发器子进程签发 → 消费端 validate/enforce → 重复消费
        拒("admission_already_consumed")——许可副作用只发生在
        本沙箱部署根内;
  步骤 4 索引:index.json 汇总命令/解释器/cwd/rc/原件 sha。

不在正式部署面、/tmp 或任何历史目录运行;输出目录必须为空或
不存在。本探针不修改任何被测代码,只调用与全量回归同源的真实
执行器/审计器/签发器/核验器。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
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
        "r17_admission_substance_test_support",
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
    print(f"[probe] {name}: rc={row.get('rc')} " +
          json.dumps({k: v for k, v in row.items()
                      if k not in ("stdout", "stderr", "finished_utc")},
                     ensure_ascii=False)[:400])


def _run(command: list, cwd: Path, env: dict | None = None,
         timeout: int = 900):
    started = _utc()
    proc = subprocess.run(command, cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=timeout)
    return {"command": command, "cwd": str(cwd),
            "interpreter": command[0], "started_utc": started,
            "finished_utc": _utc(), "rc": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:]}


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

    index = {"format": "r23-plugin-lifecycle-probe-v1",
             "created_utc": _utc(), "interpreter": sys.executable,
             "cwd": os.getcwd(), "pid": os.getpid(), "steps": {}}
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PYTEST_")}

    # ---- 步骤 1:无防护基线(scoped 反例树 + probe 对照树) -------
    scoped_base = out_dir / "sandbox_scoped"
    repo_s, commit_s, _ = support.git_repo_with_candidate(
        scoped_base, scoped=True)
    deploy_s = scoped_base / "deploy"
    support.sync_deploy_surface(repo_s, commit_s, deploy_s)
    collect = _run([sys.executable, "-m", "pytest",
                    "tests/route_c_stage2_6_1", "--collect-only", "-q"],
                   deploy_s, env)
    execute = _run([sys.executable, "-m", "pytest",
                    "tests/route_c_stage2_6_1", "-q"], deploy_s, env)
    _record(index, "no_defense_scoped", collect_rc=collect["rc"],
            execute_rc=execute["rc"], collect=collect, execute=execute,
            collected_marker="10 tests collected",
            events_original=str(deploy_s / "scoped_plugin_events.jsonl"))
    probe_base = out_dir / "sandbox_control"
    repo_c, commit_c, _ = support.git_repo_with_candidate(
        probe_base, probe=True)
    deploy_c = probe_base / "deploy"
    support.sync_deploy_surface(repo_c, commit_c, deploy_c)
    control = _run([sys.executable, "-m", "pytest",
                    "tests/route_c_stage2_6_1", "-q"], deploy_c, env)
    _record(index, "no_defense_control", control=control,
            control_rc=control["rc"], failed_marker="1 failed")

    # ---- 步骤 2:真实执行器(scoped 树)⇒ 拒 full -------------------
    run_dir = out_dir / "executor_scoped_run"
    started = _utc()
    proc = subprocess.run(
        [sys.executable, str(support.executor_path()),
         "--repo", str(repo_s), "--commit-a", commit_s,
         "--deploy-root", str(deploy_s), "--out-dir", str(run_dir),
         "--substance-src", str(support.substance_src())],
        capture_output=True, text=True, timeout=1800, env=env)
    row = {"command": proc.args, "cwd": os.getcwd(),
           "interpreter": sys.executable, "started_utc": started,
           "finished_utc": _utc(), "rc": proc.returncode,
           "stdout_tail": proc.stdout[-2000:],
           "stderr_tail": proc.stderr[-2000:]}
    summary = json.loads((run_dir / "summary.json").read_text(
        encoding="utf-8"))
    audit = json.loads((run_dir / "audit_collection.json").read_text(
        encoding="utf-8"))
    row["summary_ok"] = summary.get("ok")
    row["summary_error"] = summary.get("error", "")[:300]
    row["audit_verdict"] = audit["verdict"]
    row["audit_lifecycle_violations"] = audit["lifecycle"]["violations"]
    row["scoped_event"] = [
        event for event in audit["lifecycle"]["events"]
        if event["plugin_name"] == "scoped_collection"]
    collection_stdout = (run_dir / "collection.stdout.txt").read_text(
        encoding="utf-8")
    row["collection_collected_marker"] = (
        "10 tests collected" if "10 tests collected" in collection_stdout
        else "unexpected")
    # 同源核验器对 scoped 运行 record 的拒绝(独立于执行器 summary)
    from rl_curriculum.curriculum261_r17_admission_substance import (
        SubstanceError, verify_regression_evidence)
    try:
        verify_regression_evidence(
            run_dir / "regression_evidence_v3_record.json",
            repo_s, commit_s, deploy_root=deploy_s)
        row["verify_regression_evidence"] = "UNEXPECTED-ACCEPT"
    except SubstanceError as exc:
        row["verify_regression_evidence"] = str(exc)[:300]
    _record(index, "executor_scoped", **row)

    # ---- 步骤 3:合法对照(canonical 树)全链 ----------------------
    legal_base = out_dir / "sandbox_legal"
    repo_l, commit_l, _ = support.git_repo_with_candidate(legal_base)
    deploy_l = legal_base / "deploy"
    support.sync_deploy_surface(repo_l, commit_l, deploy_l)
    run_l = out_dir / "executor_legal_run"
    legal_row, _, legal_rc = support.run_executor(
        run_l, repo_l, commit_l, deploy_l, expect_rc=(0,))
    summary_l = json.loads((run_l / "summary.json").read_text(
        encoding="utf-8"))
    record_l = json.loads(
        (run_l / "regression_evidence_v3_record.json").read_text(
            encoding="utf-8"))
    # 真实签发器子进程 → 消费 → 重复消费
    state_l = deploy_l / "artifacts" / "route_c_stage2_6_1_repair18" / (
        "state")
    state_l.mkdir(parents=True, exist_ok=True)
    prereg_l = support.write_preregistration(
        legal_base / "prereg.json", repo_l, commit_l,
        run_l / "regression_evidence_v3_record.json",
        admission_id="r23-probe-legal-0001")
    issue = _run([sys.executable, str(support.runner_repo_path(
        "r17_admission_issue.py")), "--repo", str(repo_l),
        "--deploy-root", str(deploy_l), "--state-root", str(state_l),
        "--commit-a", commit_l, "--preregistration", str(prereg_l)],
        legal_base, env)
    from rl_curriculum.curriculum261_r17_admission import (
        enforce_formal_admission, validate_admission)
    ok, reason, _adm = validate_admission(
        deploy_l, state_l, commit_l, str(repo_l))
    consume = enforce_formal_admission(state_l, commit_l, str(repo_l))
    consume_again = enforce_formal_admission(state_l, commit_l,
                                             str(repo_l))
    _record(index, "executor_legal_and_chain", legal_rc=legal_rc,
            summary_ok=summary_l.get("ok"),
            record_format=record_l.get("format"),
            issue_rc=issue["rc"], issue=issue,
            validate_admission_ok=ok, validate_reason=reason,
            consume_result=consume, consume_again_result=consume_again,
            admission_file=str(deploy_l / ".r17_formal_admission.json"))

    index["finished_utc"] = _utc()
    index["originals"] = {
        "scoped_run_dir": str(run_dir),
        "scoped_run_record_sha256": _sha(
            run_dir / "regression_evidence_v3_record.json"),
        "scoped_audit_sha256": _sha(run_dir / "audit_collection.json"),
        "scoped_lifecycle_stream_sha256": _sha(
            run_dir / "audit_collection.json.lifecycle.jsonl"),
        "legal_run_dir": str(run_l),
        "legal_run_record_sha256": _sha(
            run_l / "regression_evidence_v3_record.json"),
        "review_counterexample_source": (
            "goal_incoming/RouteC_PluginLifecycle_AnalysisRule_"
            "NextGoal_v1 context ZIP: routec_review_102e9b2/"
            "probe_cases/scoped_specname (untouched original)"),
    }
    (out_dir / "index.json").write_text(
        json.dumps(index, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    ok_all = (index["steps"]["executor_scoped"]["rc"] == 3
              and index["steps"]["executor_scoped"]["audit_verdict"]
              == "violations"
              and index["steps"]["executor_scoped"]
              ["summary_ok"] is False
              and legal_rc == 0 and summary_l.get("ok") is True
              and issue["rc"] == 0 and ok and consume is None
              and consume_again == "admission_already_consumed")
    print(json.dumps({"ok": bool(ok_all)}, ensure_ascii=False))
    return 0 if ok_all else 3


if __name__ == "__main__":
    sys.exit(main())
