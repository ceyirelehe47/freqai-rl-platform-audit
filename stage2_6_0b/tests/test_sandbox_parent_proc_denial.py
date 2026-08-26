"""工作包 C8/C4:PID 与 proc 隔离(候选看不到父进程命令行/环境/fd)。"""

from __future__ import annotations

import json
import os

import pytest

from conftest import build_probe_code, run_candidate_in_sandbox


def _parse(proc):
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"probe 无输出: rc={proc.returncode} err={proc.stderr[-500:]}"
    return json.loads(lines[-1])


def test_proc_shows_only_sandbox_processes(sandbox_checkpoint):
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(extra_code='''
import os
try:
    entries = [e for e in os.listdir("/proc") if e.isdigit()]
    report["extra"]["proc_entries"] = entries
    report["extra"]["my_pid"] = os.getpid()
    report["extra"]["ppid"] = os.getppid()
except Exception as e:
    report["extra"]["proc_error"] = repr(e)
'''))
    report = _parse(proc)
    entries = report["extra"]["proc_entries"]
    # 独立 PID namespace:除自身外最多只有 ns 内 init(自身即 pid 1)
    assert len(entries) <= 2, f"/proc 暴露外部进程: {entries}"
    assert report["extra"]["my_pid"] == 1 or report["extra"]["ppid"] in (
        0, 1, report["extra"]["my_pid"])


def test_parent_cmdline_and_environ_unreachable(sandbox_checkpoint):
    """父进程(评估主进程)的 /proc/<pid>/cmdline 与 environ 不可读:
    新 PID namespace + 新 procfs 使其 pid 根本不存在。"""
    parent_pid = os.getpid()
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(targets=[
            ("parent_cmdline", f"/proc/{parent_pid}/cmdline"),
            ("parent_environ", f"/proc/{parent_pid}/environ"),
            ("parent_fd", f"/proc/{parent_pid}/fd"),
        ]))
    report = _parse(proc)
    for name in ("parent_cmdline", "parent_environ", "parent_fd"):
        t = report["targets"][name]
        assert not t["read"]["ok"], f"{name} 泄漏: {t['read']}"
        assert not t["list"]["ok"], f"{name} 泄漏: {t['list']}"


def test_inherited_fds_beyond_stdio_closed(sandbox_checkpoint, tmp_path):
    """候选只应持有 stdin/stdout/stderr(其余继承 fd 已关闭)。"""
    leak = tmp_path / "leak.txt"
    leak.write_bytes(b"secret-fd-content")
    handle = open(leak, "rb")  # 保持打开:验证 Popen(close_fds)与 bootstrap
    try:
        proc = run_candidate_in_sandbox(
            sandbox_checkpoint,
            probe_code=build_probe_code(
                extra_code='''
import os
fds = []
for fd in range(3, 64):
    try:
        os.fstat(fd)
        fds.append(fd)
    except OSError:
        pass
report["extra"]["open_fds"] = fds
'''))
    finally:
        handle.close()
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines
    report = json.loads(lines[-1])
    assert report["extra"]["open_fds"] == [], (
        f"沙箱内存在多余继承 fd: {report['extra']['open_fds']}")


def test_worker_env_is_scrubbed(sandbox_checkpoint, monkeypatch):
    """worker 环境不携带考试信息变量。"""
    monkeypatch.setenv("EXAM_SEED", "12345")
    monkeypatch.setenv("HIDDEN_PACK_PATH", "/tmp/nowhere")
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(extra_code='''
import os
report["extra"]["env_keys"] = sorted(os.environ.keys())
'''))
    report = _parse(proc)
    keys = report["extra"]["env_keys"]
    for key in keys:
        upper = key.upper()
        for pat in ("SEED", "FAMILY", "SPLIT", "PACK", "EXAM", "CHARTER",
                    "HIDDEN", "PARAMS", "NULL", "VERDICT"):
            assert pat not in upper, f"worker 环境泄漏 {key}"
