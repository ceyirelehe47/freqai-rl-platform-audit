"""工作包 B:时钟与熵源闭包(B1/B2 + E5/E6;真实生产路径)。

- E5:Builder 用 time.time/time_ns/datetime/monotonic/perf_counter
  影响 pack -> 只能取得冻结纪元 0(跨运行一致,不依赖"三次碰巧
  相同");ctypes raw clock_gettime -> EPERM -> 构建失败;
- E6:os.urandom/secrets/random 只能得到受承诺确定性熵(双跑一致);
  getrandom raw syscall -> EPERM -> 构建失败;numpy 未播种 RNG 跨
  进程不确定 -> precommit 双跑 BuilderUncertainError;
- vDSO 冻结 stub 证明:EDIC 携带 stub 摘要/原始 vDSO 摘要/行为
  探针;PR_SET_TSC rc=0。
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.stage2_6_0i


def _notes_var(body):
    return body


def test_frozen_clock_visible_to_builder(run_attack):
    """E5:time.time()/datetime.now() 等返回冻结纪元 0,pack 携带
    冻结值(不是"接近所以一致",而是恒 0)。"""
    run = run_attack(
        "    import time, datetime\n"
        "    t1 = time.time()\n"
        "    t2 = time.time_ns()\n"
        "    t3 = time.monotonic()\n"
        "    t4 = time.perf_counter()\n"
        "    y = datetime.datetime.now().year\n"
        "    notes = {'t1': t1, 't2': t2, 't3': t3, 't4': t4, 'y': y}\n",
        label="clock-frozen", max_attempts=1)
    assert isinstance(run, dict), run
    edic = run["deterministic_input_report"]
    assert edic["clock"]["behavior"]["time_time"] == 0.0
    assert edic["clock"]["behavior"]["datetime_now_year"] == 1970
    assert edic["clock"]["behavior"]["time_monotonic"] == 0.0
    assert edic["clock"]["behavior"]["time_perf_counter"] == 0.0


def test_double_run_clock_consistency(run_attack):
    """同一"日时间攻击"builder 两次运行:pack/edi/lock 全一致(冻结
    纪元使时间不可作为区分输入)。"""
    body = (
        "    import time\n"
        "    day = int(time.time() // 86400)\n"
        "    notes = {'day': day}\n")
    r1 = run_attack(body, label="clock-double", max_attempts=1)
    r2 = run_attack(body, label="clock-double", max_attempts=1)
    assert isinstance(r1, dict) and isinstance(r2, dict), (r1, r2)
    assert r1["pack_hash"] == r2["pack_hash"]
    assert r1["deterministic_input_hash"] == r2["deterministic_input_hash"]
    assert r1["runtime_lock_hash"] == r2["runtime_lock_hash"]


def test_raw_clock_syscall_rejected(run_attack):
    """E5:ctypes 直接 clock_gettime/time/gettimeofday -> EPERM ->
    构建失败(不是返回真实时间)。"""
    outcome = run_attack(
        "    import ctypes\n"
        "    libc = ctypes.CDLL(None, use_errno=True)\n"
        "    rc = libc.syscall(228, 0, 0)\n"
        "    if rc == 0:\n"
        "        notes = {'leak': True}\n"
        "    else:\n"
        "        raise RuntimeError('clock denied')\n",
        label="clock-raw", max_attempts=1)
    assert not isinstance(outcome, dict), "raw clock syscall 未被拒绝"
    name, msg = outcome
    assert "clock" in msg.lower() or "denied" in msg.lower() or \
        name in ("BuilderRunnerError", "BuilderProvenanceError"), outcome


def test_rdtsc_kills_worker(run_attack):
    """E5:TSC 通道:PR_SET_TSC=SIGSEGV 后执行 rdtsc -> Worker 信号
    死亡(构建失败;无 pack 采信)。"""
    outcome = run_attack(
        "    import ctypes\n"
        "    libc = ctypes.CDLL(None, use_errno=True)\n"
        "    libc.mmap.restype = ctypes.c_void_p\n"
        "    page = libc.mmap(None, 4096, 7, 0x22, -1, 0)\n"
        "    ctypes.memmove(page, b'\\x0f\\x31\\xc3', 3)\n"
        "    fn = ctypes.CFUNCTYPE(ctypes.c_uint64)(page)\n"
        "    tsc = fn()\n"
        "    notes = {'tsc': tsc}\n",
        label="tsc-read", max_attempts=1)
    assert not isinstance(outcome, dict), "rdtsc 未被 PR_SET_TSC 封禁"
    name, msg = outcome
    assert name in ("BuilderRunnerError", "BuilderProvenanceError"), outcome


def test_vdso_stub_evidence(run_attack):
    """EDIC 携带 vDSO 冻结 stub 证明(符号偏移/stub 摘要/原始 vDSO
    字节摘要)与 raw syscall 拒绝矩阵。"""
    run = run_attack("    pass\n", label="vdso-ev", max_attempts=1)
    assert isinstance(run, dict), run
    vdso = run["deterministic_input_report"]["clock"]["vdso"]
    assert vdso["mode"] == "frozen-stub"
    assert vdso["frozen_epoch"] == 0
    assert "__vdso_clock_gettime" in vdso["stubs"]
    assert len(vdso["stub_sha256"]) == 64
    assert len(vdso["original_vdso_sha256"]) == 64
    raw = run["deterministic_input_report"]["clock"]["raw_syscall"]
    for key in ("clock_gettime", "time", "gettimeofday",
                "clock_gettime64"):
        assert raw[key] == "ERRNO1"
    assert run["deterministic_input_report"]["clock"][
        "pr_set_tsc_rc"] == 0


def test_deterministic_entropy_sources(run_attack):
    """E6:os.urandom/secrets/random 只能取得受承诺确定性熵;两次
    运行 pack 一致(熵文件内容进入 manifest)。"""
    body = (
        "    import os, secrets, random\n"
        "    u1 = os.urandom(8).hex()\n"
        "    s1 = secrets.token_hex(4)\n"
        "    r1 = random.random()\n"
        "    notes = {'u1': u1, 's1': s1, 'r1': r1}\n")
    r1 = run_attack(body, label="entropy-det", max_attempts=1)
    r2 = run_attack(body, label="entropy-det", max_attempts=1)
    assert isinstance(r1, dict) and isinstance(r2, dict), (r1, r2)
    assert r1["pack_hash"] == r2["pack_hash"], "确定性熵跨运行漂移"
    edic = r1["deterministic_input_report"]
    assert edic["entropy"]["getrandom"] == "ERRNO1"
    assert edic["entropy"]["dev_urandom_deterministic"] is True
    assert edic["dev"]["urandom_regular_file"] is True


def test_getrandom_raw_rejected(run_attack):
    """E6:getrandom raw syscall -> EPERM -> 构建失败。"""
    outcome = run_attack(
        "    import ctypes\n"
        "    libc = ctypes.CDLL(None, use_errno=True)\n"
        "    buf = ctypes.create_string_buffer(8)\n"
        "    rc = libc.syscall(318, buf, 8, 0)\n"
        "    if rc == 0:\n"
        "        notes = {'leak': True}\n"
        "    else:\n"
        "        raise RuntimeError('getrandom denied')\n",
        label="getrandom-raw", max_attempts=1)
    assert not isinstance(outcome, dict), "getrandom 未被拒绝"


def test_numpy_unseeded_rng_is_deterministic_committed(run_attack):
    """E6:numpy 未播种 RNG 的种子经 os.urandom 取自**受承诺确定性
  熵文件**(getrandom EPERM -> CPython 回退顺序读 /dev/urandom 文件
  首字节)——两个全新 Worker 进程得到相同种子与相同 pack(确定性
  输入语义;真实系统熵不可观察)。"""
    import numpy

    body = (
        "    import numpy as np\n"
        "    v1 = float(np.random.default_rng().random())\n"
        "    notes = {'v1': v1}\n")
    deps = [{"module": "numpy", "version": numpy.__version__}]
    r1 = run_attack(body, external_dependencies=deps,
                    label="np-unseeded", max_attempts=1)
    r2 = run_attack(body, external_dependencies=deps,
                    label="np-unseeded", max_attempts=1)
    assert isinstance(r1, dict) and isinstance(r2, dict), (r1, r2)
    assert r1["pack_hash"] == r2["pack_hash"], (
        "未播种 numpy RNG 跨进程漂移(确定性熵回退未生效)")
    assert r1["deterministic_input_hash"] == r2[
        "deterministic_input_hash"]
    assert r1["runtime_lock_hash"] == r2["runtime_lock_hash"]
    assert r1["deterministic_input_report"]["entropy"][
        "getrandom"] == "ERRNO1"
    assert r1["deterministic_input_report"]["dev"][
        "urandom_regular_file"] is True
