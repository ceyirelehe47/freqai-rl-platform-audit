"""工作包 C8:checkpoint 在候选侧只读(写入/截断/删除全部拒绝)。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from conftest import run_candidate_in_sandbox


def _last_json(proc):
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"probe 无输出: rc={proc.returncode} err={proc.stderr[-500:]}"
    return json.loads(lines[-1])


def test_checkpoint_write_via_mountinfo_denied(sandbox_checkpoint):
    """通过 /proc/self/mountinfo 找到挂载点后尝试写入(最强攻击路径)。"""
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code='''
import os, json
try:
    with open("/proc/self/mountinfo") as f:
        info = f.read()
    mounts = [ln.split(" ")[4] for ln in info.splitlines()]
    model_files = [m for m in mounts if "/model/" in m]
    results = {}
    for p in model_files:
        try:
            with open(p, "r+b") as f:
                f.write(b"tamper")
            results[p] = "WRITTEN"
        except Exception as e:
            results[p] = type(e).__name__
    print(json.dumps({"model_files": model_files, "write": results}))
except Exception as e:
    print(json.dumps({"error": repr(e)}))
''')
    report = _last_json(proc)
    assert report.get("model_files"), f"未找到 model 挂载: {report}"
    for path, outcome in report["write"].items():
        assert outcome != "WRITTEN", f"checkpoint 可写: {path} -> {outcome}"
        assert outcome in ("PermissionError", "OSError"), (path, outcome)


def test_checkpoint_append_truncate_remove_chmod_denied(sandbox_checkpoint):
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code='''
import os, json
try:
    with open("/proc/self/mountinfo") as f:
        info = f.read()
    mounts = [ln.split(" ")[4] for ln in info.splitlines()]
    model_files = [m for m in mounts if "/model/" in m]
    results = {}
    for p in model_files:
        name = os.path.basename(p)
        try:
            with open(p, "ab") as f:
                f.write(b"x")
            results[name + ":append"] = "WRITTEN"
        except Exception as e:
            results[name + ":append"] = type(e).__name__
        try:
            os.remove(p)
            results[name + ":remove"] = "REMOVED"
        except Exception as e:
            results[name + ":remove"] = type(e).__name__
        try:
            os.chmod(p, 0o666)
            results[name + ":chmod"] = "CHMODDED"
        except Exception as e:
            results[name + ":chmod"] = type(e).__name__
    print(json.dumps(results))
except Exception as e:
    print(json.dumps({"error": repr(e)}))
''')
    attempts = _last_json(proc)
    assert attempts and "error" not in attempts, attempts
    for op, outcome in attempts.items():
        assert outcome not in ("WRITTEN", "REMOVED", "CHMODDED"), (
            f"{op} -> {outcome}:checkpoint 可被修改")


def test_checkpoint_sha_unchanged_after_sandbox_run(sandbox_checkpoint):
    """整场沙箱执行后 checkpoint 字节不变(SHA 前后一致)。"""
    before = hashlib.sha256(
        Path(sandbox_checkpoint).read_bytes()).hexdigest()
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code='''
import os
try:
    with open("/proc/self/mountinfo") as f:
        info = f.read()
    mounts = [ln.split(" ")[4] for ln in info.splitlines()]
    for p in [m for m in mounts if "/model/" in m]:
        try:
            open(p, "r+b").write(b"zzz")
        except Exception:
            pass
except Exception:
    pass
''')
    assert proc.returncode in (0, 1)
    after = hashlib.sha256(
        Path(sandbox_checkpoint).read_bytes()).hexdigest()
    assert before == after, "沙箱内执行修改了 checkpoint 原文件"
