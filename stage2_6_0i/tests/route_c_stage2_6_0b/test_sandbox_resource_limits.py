"""工作包 C7/C8:资源限制(CPU/内存/文件大小/nofile/nproc/失控子进程)。"""

from __future__ import annotations

import json

import pytest

from conftest import build_probe_code, run_candidate_in_sandbox
from rl_curriculum.sandbox import SandboxProfile


def _parse(proc):
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"probe 无输出: rc={proc.returncode} err={proc.stderr[-500:]}"
    return json.loads(lines[-1])


def _tight_profile(**overrides) -> SandboxProfile:
    from rl_curriculum.sandbox import default_sandbox_profile

    base = default_sandbox_profile()
    rlimits = {"cpu_seconds": 300, "address_space_mb": 1024,
               "file_size_mb": 8, "nofile": 32, "nproc": 6}
    rlimits.update(overrides)
    return SandboxProfile(
        read_exec_dirs=base.read_exec_dirs,
        read_only_dirs=base.read_only_dirs,
        read_write_dirs=base.read_write_dirs,
        rlimits=rlimits)


def test_rlimits_applied_inside_sandbox(sandbox_checkpoint):
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(extra_code='''
import resource
report["extra"]["cpu"] = resource.getrlimit(resource.RLIMIT_CPU)
report["extra"]["as"] = resource.getrlimit(resource.RLIMIT_AS)
report["extra"]["fsize"] = resource.getrlimit(resource.RLIMIT_FSIZE)
report["extra"]["nofile"] = resource.getrlimit(resource.RLIMIT_NOFILE)
report["extra"]["nproc"] = resource.getrlimit(resource.RLIMIT_NPROC)
'''))
    report = _parse(proc)
    ex = report["extra"]
    assert ex["cpu"][1] == 1800
    assert ex["as"][1] == 6144 * 1024 * 1024
    assert ex["fsize"][1] == 64 * 1024 * 1024
    assert ex["nofile"][1] == 256
    assert 0 < ex["nproc"][1] <= 512


def test_file_size_limit_enforced(sandbox_checkpoint):
    """超过 RLIMIT_FSIZE 的写入被 SIGXFSZ 终止。"""
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code='''
import os
try:
    home = os.environ.get("HOME", ".")
    with open(os.path.join(home, "big.bin"), "wb") as f:
        chunk = b"x" * (1024 * 1024)
        for _ in range(200):  # 200MB > 64MB 上限
            f.write(chunk)
    print("WROTE_TOO_MUCH")
except Exception as e:
    import json
    print(json.dumps({"fsize_error": type(e).__name__}))
''')
    assert "WROTE_TOO_MUCH" not in proc.stdout, "文件大小上限未生效"


def test_nproc_limit_blocks_subprocess_explosion(sandbox_checkpoint):
    profile = _tight_profile()
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code='''
import subprocess, sys, json
children = []
spawned = 0
error = None
try:
    while spawned < 24:
        p = subprocess.Popen([sys.executable, "-I", "-c",
                              "import time; time.sleep(30)"])
        children.append(p)
        spawned += 1
except Exception as e:
    error = type(e).__name__
for p in children:
    try:
        p.kill()
    except Exception:
        pass
print(json.dumps({"spawned": spawned, "error": error}))
''', timeout=300, profile=profile)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines
    report = json.loads(lines[-1])
    assert report["spawned"] < 24, "nproc 上限未约束子进程爆炸"


def test_memory_limit_enforced(sandbox_checkpoint):
    profile = _tight_profile(address_space_mb=512)
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code='''
import json
blobs = []
try:
    while True:
        blobs.append(bytearray(128 * 1024 * 1024))
    print(json.dumps({"mem": "unbounded"}))
except MemoryError:
    print(json.dumps({"mem": "MemoryError"}))
''', timeout=300, profile=profile)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    # RLIMIT_AS 使大额分配失败:进程被杀或 MemoryError
    assert not any("unbounded" in ln for ln in lines), "内存上限未生效"


def test_custom_profile_rlimits(sandbox_checkpoint):
    profile = _tight_profile(cpu_seconds=42, nofile=32)
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(extra_code='''
import resource
report["extra"]["cpu"] = resource.getrlimit(resource.RLIMIT_CPU)
report["extra"]["nofile"] = resource.getrlimit(resource.RLIMIT_NOFILE)
'''), profile=profile)
    report = _parse(proc)
    assert report["extra"]["cpu"][1] == 42
    assert report["extra"]["nofile"][1] == 32
