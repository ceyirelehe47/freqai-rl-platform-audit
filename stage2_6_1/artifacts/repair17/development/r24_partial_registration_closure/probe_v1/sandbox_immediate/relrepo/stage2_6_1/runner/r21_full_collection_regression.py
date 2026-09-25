#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R21 完整参数收集回归执行器(v6 证据采集端)。

在受控部署面上于执行发生时采集 cur261-r17-candidate-regression-
evidence-v6 record 的全部原件:

  步骤 0 预检:候选测试树 → 部署面字节核验(substance 同源实现);
           PYTEST_* 环境污染拒绝;部署面 pytest 配置候选扫描 +
           过滤内容拒绝;候选树静态 hook 绑定扫描(过滤 hook 零
           容忍,生成 hook 须与批准清单逐字节一致)。
  步骤 0.5 受控配置先行:审计 manifest 在任何 pytest 运行前落盘
           (受控钩子集 + 生成 hook 批准(恰为候选绑定集合)+
           审计器文件 sha);子进程环境 = 白名单继承 + 执行端强制
           键(插件自动加载关闭、审计接线、PYTHONPATH=部署 runner
           面)。不是"运行时看到什么就批准什么"。
  步骤 1 完整收集:python -m pytest -p r21_collection_auditor
           <target> --collect-only -q 真实子进程(执行端固定 -p,
           恰一对;调用方不可注入),审计器在收集可影响结果之前
           分类实际生效插件/钩子,违规即 UsageError 终止。
  步骤 2 执行:每个分片目标一个真实子进程(-q --junitxml=...),
           同一审计接线;逐运行审计原件三阶段落盘绑定。
  步骤 3 组装 record(全部原件 sha256 绑定,路径相对 out_dir;
           执行面身份 executor/auditor 候选 blob+部署字节;外层
           监护 run 只读关联)。
  步骤 4 自验:同源 verify_regression_evidence(含 deploy_root),
           结果写 summary.json。

不重跑、不重试、不掩盖非零 rc:执行失败如实落盘并以非零码退出
(rc=4 运行失败;rc=3 自验失败;rc=2 预检拒绝)。输出目录必须是
持久目录(证据不落 /tmp)。差分协议经 --differential 传入父证据
块;本执行器不核验父链(由同源核验器递归完成)。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

SUBSTANCE_MODULE = "curriculum261_r17_admission_substance"
DEPLOYED_TEST_ROOT = "tests/route_c_stage2_6_1"
_SRC_PREFIX = "stage2_6_1/src/rl_curriculum/"
_EXECUTOR_SOURCE = "stage2_6_1/runner/r21_full_collection_regression.py"
_AUDITOR_SOURCE = "stage2_6_1/runner/r21_collection_auditor.py"
_AUDITOR_MODULE = "r21_collection_auditor"
#: 子进程环境白名单(与 substance._ENV_INHERIT_KEYS 同值;测试
#: 交叉断言防漂移)。
_ENV_INHERIT_KEYS = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "LANG",
    "TMPDIR", "TEMP", "TMP", "HOSTNAME", "WSL_DISTRO_NAME",
    "WSL_INTEROP",
})
_ENV_INHERIT_PREFIXES = ("LC_",)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_substance(src_dir: Path):
    path = Path(src_dir) / "rl_curriculum" / (SUBSTANCE_MODULE + ".py")
    if not path.is_file():
        raise SystemExit(f"refused: substance module missing: {path}")
    spec = importlib.util.spec_from_file_location(SUBSTANCE_MODULE, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git_out(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise SystemExit("refused: git failed: " + " ".join(args[:2]))
    return proc.stdout


def _child_env() -> tuple[dict, dict]:
    """v4 子进程环境:白名单继承 + 执行端强制键。

    白名单外的环境变量(含一切 PYTEST_* 与未知快速模式键)不进入
    收集/执行子进程;被剥离键只记录键名(存在性),不记录值。
    """
    env: dict[str, str] = {}
    inherited: list[str] = []
    for key, value in os.environ.items():
        if key in _ENV_INHERIT_KEYS \
                or key.startswith(_ENV_INHERIT_PREFIXES):
            env[key] = value
            inherited.append(key)
    return env, {"inherited": sorted(inherited),
                 "dropped_keys": sorted(
                     k for k in os.environ
                     if k not in inherited)}


def _env_block(mod, interp: str, cwd: Path, policy: dict) -> dict:
    """运行身份探针:与真实运行同一(最小化)环境,autoload 关闭,
    探针输出即真实运行可见的插件面。"""
    probe_env = dict(os.environ)
    for key in list(probe_env):
        if key not in _ENV_INHERIT_KEYS \
                and not key.startswith(_ENV_INHERIT_PREFIXES):
            probe_env.pop(key)
    probe_env["PYTHONDONTWRITEBYTECODE"] = "1"
    probe_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    probe = subprocess.run(
        [interp, "-m", "pytest", "--version", "--version"],
        capture_output=True, text=True, timeout=120, cwd=str(cwd),
        env=probe_env)
    if probe.returncode != 0:
        raise SystemExit("refused: pytest version probe failed")
    scan = []
    for path in mod._scan_config_files(cwd, DEPLOYED_TEST_ROOT):
        scan.append({"path": str(path), "sha256": _sha256_file(path)})
    return {
        "python_version": platform.python_version(),
        "pytest_version_output": probe.stdout.strip(),
        "child_env_policy": policy,
        "config_scan": scan,
    }


def _run_pytest(mod, interp: str, cwd: Path, env: dict,
                policy: dict, args: list[str],
                out_dir: Path, stem: str) -> tuple[dict, dict]:
    """一个真实 pytest 子进程(执行端固定 -p 审计器);原件落盘
    并返回 (run 条目, env 快照)。"""
    command = [interp, "-m", "pytest", "-p", _AUDITOR_MODULE, *args]
    audit_path = out_dir / f"audit_{stem}.json"
    lifecycle_path = out_dir / f"audit_{stem}.json.lifecycle.jsonl"
    env = dict(env)
    env["R21_AUDIT_OUT"] = str(audit_path)
    stdout_path = out_dir / f"{stem}.stdout.txt"
    stderr_path = out_dir / f"{stem}.stderr.txt"
    env_id = _env_block(mod, interp, cwd, policy)
    started = _utc()
    proc = subprocess.run(command, cwd=str(cwd), env=env,
                          capture_output=True, timeout=None)
    finished = _utc()
    stdout_path.write_bytes(proc.stdout)
    stderr_path.write_bytes(proc.stderr)
    entry = {
        "command": command,
        "interpreter": interp,
        "cwd": str(cwd),
        "returncode": proc.returncode,
        "started_utc": started,
        "finished_utc": finished,
        "stdout": {"path": stdout_path.name,
                   "sha256": _sha256_bytes(proc.stdout)},
        "stderr": {"path": stderr_path.name,
                   "sha256": _sha256_bytes(proc.stderr)},
    }
    env_id["child_env"] = dict(env)
    if audit_path.is_file():
        entry["audit"] = {"path": audit_path.name,
                          "sha256": _sha256_file(audit_path)}
    if lifecycle_path.is_file():
        # v5:append-only 注册事件流水与审计文档互绑;缺流水 ⇒
        # 核验器拒绝(audit_lifecycle_stream_unbound,fail closed)。
        entry["audit_lifecycle"] = {
            "path": lifecycle_path.name,
            "sha256": _sha256_file(lifecycle_path)}
    return entry, env_id



def _supervision_link(repo: Path, out_dir: Path) -> dict:
    """只读关联外层受监护 run:在 run_supervision 运行史中定位
    business argv 含本次 out_dir 的 run_record。找不到则如实
    present=false(沙箱/定向轮次无外层监护),不虚报。"""
    base = Path(repo) / "stage2_6_1" / "artifacts" / "repair17" / (
        "development") / "run_supervision" / "runs"
    if not base.is_dir():
        return {"present": False}
    token = str(out_dir)
    for run_dir in sorted(base.iterdir(), reverse=True):
        record = run_dir / "run_record.json"
        if not record.is_file():
            continue
        try:
            doc = json.loads(record.read_text(encoding="utf-8"))
            argv = doc.get("argv")
            argv_text = argv if isinstance(argv, str) else json.dumps(
                argv, ensure_ascii=False)
        except (OSError, ValueError):
            continue
        if token in argv_text:
            return {"present": True, "run_id": doc.get("run_id",
                                                       run_dir.name),
                    "run_dir": str(run_dir), "argv_token": token}
    return {"present": False}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--commit-a", required=True)
    ap.add_argument("--deploy-root", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--substance-src", type=Path, default=None,
                    help="substance 模块所在 src 根(默认 deploy_root/src)")
    ap.add_argument("--target", default=DEPLOYED_TEST_ROOT)
    ap.add_argument("--shard", action="append", default=None,
                    help="分片执行目标(可重复;缺省=单次完整目标)")
    ap.add_argument("--protocol", choices=("full", "differential"),
                    default="full")
    ap.add_argument("--differential", type=Path, default=None,
                    help="差分块 JSON(parent_commit/parent_evidence/"
                         "delta_scope/delta_targets)")
    ap.add_argument("--approved-generate-tests", action="append",
                    default=None,
                    help="预批准 pytest_generate_tests 文件(部署根内"
                         "相对路径,可重复;必须与候选树静态绑定集合"
                         "逐字节一致;缺省=无)")
    ap.add_argument("--interpreter", default=sys.executable)
    ap.add_argument("--label", default="r21_full_collection_regression")
    args = ap.parse_args(argv)

    deploy_root = args.deploy_root.resolve()
    out_dir = args.out_dir.resolve()
    if args.interpreter != sys.executable:
        raise SystemExit("refused: interpreter must be the running interpreter")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit("refused: out-dir not empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    mod = _load_substance(args.substance_src or deploy_root / "src")

    # ---- 步骤 0:预检(候选绑定 + 环境污染 + 配置过滤面)
    pytest_pollution = [key for key in os.environ
                        if key.startswith("PYTEST_")]
    if pytest_pollution:
        raise SystemExit(
            "refused: PYTEST_* present in ambient env: "
            + ",".join(sorted(pytest_pollution)))
    try:
        mapping = mod.candidate_test_map(args.repo, args.commit_a)
        mod.verify_deployment_surface(deploy_root, mapping)
        for path in mod._scan_config_files(deploy_root, DEPLOYED_TEST_ROOT):
            mod._reject_config_filters(path, path.read_bytes())
        bindings = mod.candidate_hook_bindings(
            args.repo, args.commit_a, mapping)
        approved: dict[str, str] = {}
        for rel in (args.approved_generate_tests or []):
            path = deploy_root / rel
            if not path.is_file():
                raise SystemExit(
                    f"refused: approved generate-tests file missing: {rel}")
            approved[rel] = _sha256_file(path)
        mod.evaluate_static_hook_policy(bindings, approved)
    except mod.SubstanceError as exc:
        raise SystemExit(f"refused: preflight rejected: {exc}") from None

    differential = None
    if args.protocol == "differential":
        if args.differential is None:
            raise SystemExit("refused: differential requires --differential")
        differential = json.loads(args.differential.read_text("utf-8"))
        if not isinstance(differential.get("delta_targets"), list) \
                or not differential["delta_targets"]:
            raise SystemExit("refused: differential.delta_targets missing")
        run_targets = list(differential["delta_targets"])
    else:
        run_targets = (args.shard if args.shard else [args.target])

    # ---- 步骤 0.5:受控配置先行(审计 manifest 先于一切 pytest 落盘)
    auditor_deploy = deploy_root / "stage2_6_1_runner" / (
        _AUDITOR_MODULE + ".py")
    executor_deploy = deploy_root / "stage2_6_1_runner" / (
        _EXECUTOR_SOURCE.rsplit("/", 1)[-1])
    if not auditor_deploy.is_file() or not executor_deploy.is_file():
        raise SystemExit(
            "refused: deploy runner face missing executor/auditor")
    auditor_sha = _sha256_file(auditor_deploy)
    manifest = {
        "format": mod.AUDIT_MANIFEST_FORMAT,
        "filtering_hooks": sorted(mod.FILTERING_HOOKS),
        "generation_hooks": sorted(mod.GENERATION_HOOKS),
        "test_root": DEPLOYED_TEST_ROOT.rstrip("/"),
        "auditor": {"module": _AUDITOR_MODULE, "sha256": auditor_sha},
        "approved_generate_tests": approved,
    }
    manifest_path = out_dir / "audit_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False,
                   sort_keys=True) + "\n", encoding="utf-8")

    base_env, drop_report = _child_env()
    base_env["PYTHONDONTWRITEBYTECODE"] = "1"
    base_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # 显式两元导入域:部署 src(套件/探测子进程的合法导入面,
    # conftest 本会插入)+ runner 面(审计器)。修复:r11/r12 等
    # 探测子进程以 PYTHONPATH setdefault 假定该键缺失——受控环境
    # 预置后需保证 src 仍在导入域(2026-09-25 全量首跑 8 failed
    # 的根因;失败原件保留于 full_regression_20260925/)。
    base_env["PYTHONPATH"] = (
        str(deploy_root / "src") + os.pathsep
        + str(deploy_root / "stage2_6_1_runner"))
    base_env["R21_AUDIT_MANIFEST"] = str(manifest_path)
    policy = {
        "inherited": drop_report["inherited"],
        "forced": {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONPATH": base_env["PYTHONPATH"],
            "R21_AUDIT_OUT": "per-run audit_<stem>.json",
            "R21_AUDIT_MANIFEST": str(manifest_path),
        },
        "dropped_keys": drop_report["dropped_keys"],
    }

    # ---- 步骤 1:完整收集(full=完整目录;差分=声明的 delta 目标)
    collect_targets = ([args.target] if args.protocol == "full"
                       else run_targets)
    collection_entry, collection_env = _run_pytest(
        mod, args.interpreter, deploy_root, base_env, policy,
        [*collect_targets, "--collect-only", "-q"],
        out_dir, "collection")
    collection_entry["env"] = collection_env
    run_rc_ok = collection_entry["returncode"] == 0
    audit_ok = _audit_ok_collection(collection_entry, out_dir,
                                    mod.AUDIT_RECORD_FORMAT)

    # ---- 步骤 2:执行(每分片一个真实子进程)
    junit_entries = []
    execution_runs = []
    for index, shard_target in enumerate(run_targets):
        stem = f"execution_{index}" if len(run_targets) > 1 else "execution"
        junit_path = out_dir / f"junit_{index}.xml" \
            if len(run_targets) > 1 else out_dir / "junit.xml"
        entry, entry_env = _run_pytest(
            mod, args.interpreter, deploy_root, base_env, policy,
            [shard_target, "-q", f"--junitxml={junit_path.resolve()}"],
            out_dir, stem)
        entry["env"] = entry_env
        run_rc_ok = run_rc_ok and entry["returncode"] == 0
        audit_ok = audit_ok and _audit_ok_collection(
            entry, out_dir, mod.AUDIT_RECORD_FORMAT)
        execution_runs.append(entry)
        if not junit_path.is_file():
            (out_dir / "summary.json").write_text(json.dumps({
                "ok": False,
                "error": "junit_not_produced",
                "run_returncodes": [collection_entry["returncode"]]
                + [e["returncode"] for e in execution_runs]},
                ensure_ascii=False) + "\n", encoding="utf-8")
            return 4
        junit_entries.append({"path": junit_path.name,
                              "sha256": _sha256_file(junit_path)})

    # ---- 步骤 3:组装 record
    aggregate = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    skipped_ids: list[str] = []
    for entry in junit_entries:
        parsed = mod.parse_junit(out_dir / entry["path"])
        for key in aggregate:
            aggregate[key] += parsed[key]
        skipped_ids.extend(parsed["skipped_ids"])
    tree = _git_out(args.repo, "ls-tree", "-r", "--name-only",
                    args.commit_a, "--", _SRC_PREFIX.rstrip("/"))
    members = {}
    for rel in [ln for ln in tree.decode("utf-8").splitlines()
                if ln.endswith(".py")]:
        blob = _git_out(args.repo, "show", f"{args.commit_a}:{rel}")
        members[rel] = _sha256_bytes(blob.replace(b"\r", b""))

    def _face(source: str, deploy_path: Path) -> dict:
        blob = _git_out(args.repo, "show", f"{args.commit_a}:{source}")
        return {"source_path": source,
                "blob_sha256": _sha256_bytes(blob.replace(b"\r", b"")),
                "deploy_sha256": _sha256_file(deploy_path)}

    deploy_src = deploy_root / "src" / "rl_curriculum"
    deploy_names = {p.name for p in deploy_src.glob("*.py")}
    extra = sorted(deploy_names
                   - {rel.rsplit("/", 1)[-1] for rel in members})
    record = {
        "format": mod.REGRESSION_EVIDENCE_FORMAT_V6,
        "scope": "formal",
        "protocol": args.protocol,
        "commit_a_sha": args.commit_a,
        "run": {
            "run_id": f"r21_{time.strftime('%Y%m%d_%H%M%S')}",
            "label": args.label,
            "deploy_root": str(deploy_root),
            "tests_target": args.target,
            "hostname": socket.gethostname(),
            "user": os.environ.get("USER", ""),
            "executor_face": {
                "executor": _face(_EXECUTOR_SOURCE, executor_deploy),
                "auditor": _face(_AUDITOR_SOURCE, auditor_deploy),
            },
            "supervision": _supervision_link(args.repo, out_dir),
        },
        "collection_run": {"runs": [collection_entry]},
        "execution": {"runs": execution_runs},
        "junit": junit_entries,
        "audit_manifest": {"path": manifest_path.name,
                           "sha256": _sha256_file(manifest_path)},
        "counts": aggregate,
        "historical_skip_ids": sorted(set(skipped_ids)),
        "test_files": [
            {"source_path": row["source_path"],
             "deploy_path": row["deploy_path"],
             "deploy_sha256": row["deploy_sha256"],
             "deploy_size": row["deploy_size"],
             "is_test": row["is_test"]}
            for row in mapping.values()],
        "import_surface": {"members": members,
                           "deploy_extra_modules": extra},
        "bound_utc": _utc(),
        "notes": (
            f"collected and executed at run time by {args.label}; "
            "artifacts byte-bound in this record"),
    }
    if differential is not None:
        record["differential"] = differential
    record_path = out_dir / "regression_evidence_v3_record.json"
    record_path.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")

    # ---- 步骤 4:同源自验(写 summary;不重跑)
    summary = {"run_id": record["run"]["run_id"],
               "record_path": record_path.name,
               "record_sha256": _sha256_file(record_path),
               "aggregate": aggregate,
               "run_returncodes": [collection_entry["returncode"]]
               + [e["returncode"] for e in execution_runs]}
    if not run_rc_ok:
        summary["ok"] = False
        summary["error"] = "run_returncode_nonzero"
    elif not audit_ok:
        summary["ok"] = False
        summary["error"] = "audit_verdict_not_pass"
    else:
        try:
            result = mod.verify_regression_evidence(
                record_path, args.repo, args.commit_a,
                deploy_root=deploy_root)
            summary["ok"] = True
            summary["verify"] = {
                "collection_tests": result["collection_tests"],
                "static_tests": result["static_tests"],
                "test_files": result["test_files"]}
        except Exception as exc:  # SubstanceError 逐字入档
            summary["ok"] = False
            summary["error"] = str(exc)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if not run_rc_ok:
        return 4
    return 0 if summary["ok"] else 3


def _audit_ok_collection(entry: dict, out_dir: Path,
                         audit_format: str) -> bool:
    """审计原件核验:路径在 out_dir 内、sha 一致、verdict=pass;
    v6 另要求审计格式 v3 + 生命周期监测与**注册边界守卫**均已
    建立且无违规 + configure 对账干净 + append-only 流水原件绑定
    在场(缺任一 ⇒ 非 pass,由 summary/record fail closed)。"""
    audit = entry.get("audit")
    if not isinstance(audit, dict):
        return False
    path = out_dir / audit["path"] if not Path(
        audit["path"]).is_absolute() else Path(audit["path"])
    if not path.is_file() or _sha256_file(path) != audit.get("sha256"):
        return False
    stream = entry.get("audit_lifecycle")
    if not isinstance(stream, dict):
        return False
    stream_path = out_dir / stream["path"] if not Path(
        stream["path"]).is_absolute() else Path(stream["path"])
    if not stream_path.is_file() \
            or _sha256_file(stream_path) != stream.get("sha256"):
        return False
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return False
    if document.get("verdict") != "pass" or document.get("violations"):
        return False
    if document.get("format") != audit_format:
        return False
    lifecycle = document.get("lifecycle")
    if not isinstance(lifecycle, dict) \
            or not isinstance(lifecycle.get("monitor"), dict) \
            or not lifecycle["monitor"].get("established_utc") \
            or lifecycle.get("violations") \
            or not lifecycle.get("events") \
            or not isinstance(lifecycle.get("reconcile"), dict) \
            or lifecycle["reconcile"].get("uncovered"):
        return False
    guard = lifecycle.get("register_guard")
    if not isinstance(guard, dict) \
            or not guard.get("installed_utc") \
            or guard.get("wrapped_hook") != "register" \
            or not guard.get("manager_class"):
        return False
    return True


if __name__ == "__main__":
    sys.exit(main())
