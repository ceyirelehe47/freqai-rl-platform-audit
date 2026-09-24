#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R21 完整参数收集回归执行器(v3 证据采集端)。

在受控部署面上于执行发生时采集 cur261-r17-candidate-regression-
evidence-v3 record 的全部原件:

  步骤 0 预检:候选测试树 → 部署面字节核验(substance 同源实现);
           PYTEST_ADDOPTS/PYTEST_PLUGINS 环境污染拒绝;部署面
           pytest 配置候选扫描 + 过滤内容拒绝(运行前 fail closed)。
  步骤 1 完整收集:python -m pytest <target> --collect-only -q 真实
           子进程,stdout/stderr/rc/起止时间落盘(期望全集权威原件)。
  步骤 2 执行:每个分片目标一个真实子进程(-q --junitxml=...),
           stdout/stderr/rc/起止时间/junit 落盘。
  步骤 3 组装 record(全部原件 sha256 绑定,路径相对 out_dir)。
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
    """子进程环境:剥离 PYTEST_ADDOPTS/PYTEST_PLUGINS;记录剥离值。"""
    env = dict(os.environ)
    removed = {}
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        removed[key] = env.pop(key, None)
    return env, removed


def _env_block(mod, interp: str, cwd: Path, removed: dict) -> dict:
    probe = subprocess.run(
        [interp, "-m", "pytest", "--version", "--version"],
        capture_output=True, text=True, timeout=120, cwd=str(cwd))
    if probe.returncode != 0:
        raise SystemExit("refused: pytest version probe failed")
    scan = []
    for path in mod._scan_config_files(cwd, DEPLOYED_TEST_ROOT):
        scan.append({"path": str(path), "sha256": _sha256_file(path)})
    return {
        "python_version": platform.python_version(),
        "pytest_version_output": probe.stdout.strip(),
        "pytest_addopts": removed.get("PYTEST_ADDOPTS"),
        "pytest_plugins_env": removed.get("PYTEST_PLUGINS"),
        "config_scan": scan,
    }


def _run_pytest(mod, interp: str, cwd: Path, base_env: dict,
                removed: dict, args: list[str],
                out_dir: Path, stem: str) -> tuple[dict, dict]:
    """一个真实 pytest 子进程;原件落盘并返回 (run 条目, env 快照)。"""
    command = [interp, "-m", "pytest", *args]
    stdout_path = out_dir / f"{stem}.stdout.txt"
    stderr_path = out_dir / f"{stem}.stderr.txt"
    env_id = _env_block(mod, interp, cwd, removed)
    started = _utc()
    proc = subprocess.run(command, cwd=str(cwd), env=base_env,
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
    return entry, env_id

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
    if os.environ.get("PYTEST_ADDOPTS") or os.environ.get("PYTEST_PLUGINS"):
        raise SystemExit(
            "refused: PYTEST_ADDOPTS/PYTEST_PLUGINS present in ambient env")
    try:
        mapping = mod.candidate_test_map(args.repo, args.commit_a)
        mod.verify_deployment_surface(deploy_root, mapping)
        for path in mod._scan_config_files(deploy_root, DEPLOYED_TEST_ROOT):
            mod._reject_config_filters(path, path.read_bytes())
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

    env, removed = _child_env()
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    # ---- 步骤 1:完整收集(full=完整目录;差分=声明的 delta 目标)
    collect_targets = ([args.target] if args.protocol == "full"
                       else run_targets)
    collection_entry, collection_env = _run_pytest(
        mod, args.interpreter, deploy_root, env, removed,
        [*collect_targets, "--collect-only", "-q"],
        out_dir, "collection")
    collection_entry["env"] = collection_env
    run_rc_ok = collection_entry["returncode"] == 0

    # ---- 步骤 2:执行(每分片一个真实子进程)
    junit_entries = []
    execution_runs = []
    for index, shard_target in enumerate(run_targets):
        stem = f"execution_{index}" if len(run_targets) > 1 else "execution"
        junit_path = out_dir / f"junit_{index}.xml" \
            if len(run_targets) > 1 else out_dir / "junit.xml"
        entry, entry_env = _run_pytest(
            mod, args.interpreter, deploy_root, env, removed,
            [shard_target, "-q", f"--junitxml={junit_path.resolve()}"],
            out_dir, stem)
        entry["env"] = entry_env
        run_rc_ok = run_rc_ok and entry["returncode"] == 0
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
    deploy_src = deploy_root / "src" / "rl_curriculum"
    deploy_names = {p.name for p in deploy_src.glob("*.py")}
    extra = sorted(deploy_names
                   - {rel.rsplit("/", 1)[-1] for rel in members})
    record = {
        "format": "cur261-r17-candidate-regression-evidence-v3",
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
        },
        "collection_run": {"runs": [collection_entry]},
        "execution": {"runs": execution_runs},
        "junit": junit_entries,
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


if __name__ == "__main__":
    sys.exit(main())
