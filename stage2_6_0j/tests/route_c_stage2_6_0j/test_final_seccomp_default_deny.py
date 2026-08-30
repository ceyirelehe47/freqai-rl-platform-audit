"""工作包 C/G9:final compute filter 必须 default deny。

- C1:default action 是 EPERM(不是 allow);
- C2:allowlist 精确集合与参数限制(write fd/mmap prot/rt_sigaction);
- G9:多个未列入 allowlist 的无害 syscall raw 探针统一 EPERM——
  证明系统不是"只拒绝已知清单"。
"""

from __future__ import annotations

import errno

import pytest

from rl_builder_runtime.sealed_compute import (
    FINAL_COMPUTE_POLICY,
    FINAL_DEFAULT_ACTION,
    _FINAL_ALLOWLIST,
    canonical_final_filter,
    final_filter_digest,
)


def test_policy_default_action_is_eperm():
    assert FINAL_COMPUTE_POLICY["default_action"] == "EPERM"
    assert FINAL_COMPUTE_POLICY["format"] == "builder-seccomp-final-policy-v3"
    assert FINAL_DEFAULT_ACTION == "EPERM"


def test_policy_allowlist_is_minimal_and_explicit():
    allowed = set(FINAL_COMPUTE_POLICY["allowlist"])
    assert allowed == set(_FINAL_ALLOWLIST)
    # 未列任何文件/元数据/进程/时钟/熵/网络 syscall
    for name in ("open", "openat", "stat", "newfstatat", "statx",
                 "statfs", "fstatfs", "getdents64", "lseek",
                 "sysinfo", "getcpu", "uname", "sched_getaffinity",
                 "getrandom", "clock_gettime", "fork", "vfork", "clone",
                 "clone3", "execve", "execveat", "prctl", "seccomp",
                 "arch_prctl", "ptrace", "memfd_create", "pkey_mprotect",
                 "userfaultfd", "socket", "connect", "sendto", "recvfrom"):
        assert name not in allowed, f"{name} 不得进入 final allowlist"
    # 纯计算必要集(实测 brk/mmap/munmap/mremap/write + 运行时安全网)
    for name in ("write", "close", "mmap", "mprotect", "munmap", "brk",
                 "mremap", "madvise", "futex", "exit", "exit_group",
                 "rt_sigaction", "rt_sigprocmask", "rt_sigreturn"):
        assert name in allowed


def test_policy_argument_limits_declared():
    al = FINAL_COMPUTE_POLICY["allowlist"]
    assert al["write"]["arg_policy"]["rule"] == "fd-in"
    assert al["write"]["arg_policy"]["fds"] == [1, 2, 87]
    assert al["read"]["arg_policy"]["fds"] == [88]
    assert al["mmap"]["arg_policy"]["rule"] == "no-prot-exec"
    assert al["mprotect"]["arg_policy"]["rule"] == "no-prot-exec"
    assert al["rt_sigaction"]["arg_policy"]["rule"] == "signal-not-in"
    assert sorted(al["rt_sigaction"]["arg_policy"]["signals"]) == \
        [4, 7, 8, 11, 31]


def test_filter_digest_stable_and_sc_prefixed():
    d1 = final_filter_digest()
    d2 = final_filter_digest(canonical_final_filter())
    assert d1 == d2 and d1.startswith("scf-")


def _sim(prog, nr, args=(0,) * 6, arch=0xC000003E):
    pc = steps = 0
    acc = 0
    while pc < len(prog):
        i = prog[pc]
        steps += 1
        assert steps < 10000, "filter loop"
        code, k, jt, jf = i["code"], i["k"], i["jt"], i["jf"]
        if code == 0x20:  # LD W ABS
            if k == 4:
                acc = arch & 0xFFFFFFFF
            elif k == 0:
                acc = nr & 0xFFFFFFFF
            elif 16 <= k <= 60:
                idx = (k - 16) // 8
                half = (k - 16) % 8
                v = args[idx] & ((1 << 64) - 1)
                acc = (v >> 32) & 0xFFFFFFFF if half else v & 0xFFFFFFFF
            else:
                acc = 0
        elif code == 0x15:
            pc += jt + 1 if acc == k else jf + 1
            continue
        elif code == 0x55:
            pc += jt + 1 if acc != k else jf + 1
            continue
        elif code == 0x54:
            acc &= k
        elif code == 0x06:
            return "ALLOW" if k == 0x7FFF0000 else f"ERRNO{k & 0xFFFF}"
        pc += 1
    return "FELL-OFF"


def test_bpf_unknown_syscalls_all_denied():
    """G9:未列入 allowlist 的 syscall 编号(含无害与危险)统一 EPERM。"""
    prog = canonical_final_filter()
    unknown = [13 + 1000, 512, 999, 0x4000 + 3, 35, 76, 77, 153,
               435, 437, 424, 334, 436]
    for nr in unknown:
        assert nr not in set(_FINAL_ALLOWLIST.values())
        assert _sim(prog, nr) == "ERRNO1", f"syscall {nr} 未被 default deny"


def test_bpf_argument_filtering():
    prog = canonical_final_filter()
    e = f"ERRNO{errno.EPERM}"
    assert _sim(prog, 1, {0: 87}) == "ALLOW"      # write RESULT_FD
    assert _sim(prog, 1, {0: 1}) == "ALLOW"       # write devnull
    assert _sim(prog, 1, {0: 3}) == e             # write 其他 fd
    assert _sim(prog, 1, {0: (1 << 32) | 87}) == e  # 64 位高位绕过
    assert _sim(prog, 0, {0: 88}) == "ALLOW"      # read ACK 通道
    assert _sim(prog, 0, {0: 0}) == e             # read 其他 fd
    assert _sim(prog, 9, {2: 3}) == "ALLOW"       # mmap RW
    assert _sim(prog, 9, {2: 7}) == e             # mmap RWX
    assert _sim(prog, 9, {2: 5}) == e             # mmap RX
    assert _sim(prog, 10, {2: 3}) == "ALLOW"      # mprotect RW
    assert _sim(prog, 10, {2: 7}) == e            # mprotect RWX
    assert _sim(prog, 13, {0: 11}) == e           # rt_sigaction SIGSEGV
    assert _sim(prog, 13, {0: 15}) == "ALLOW"     # rt_sigaction SIGTERM


@pytest.mark.parametrize("nr,name", [
    (157, "prctl"), (179, "sysinfo"), (309, "getcpu"), (63, "uname"),
    (168, "sched_getaffinity"),
])
def test_bpf_kernel_state_syscalls_denied(nr, name):
    prog = canonical_final_filter()
    assert _sim(prog, nr) == f"ERRNO{errno.EPERM}", name


def test_kernel_state_cannot_reach_pack(run_attack2j):
    """G2:Builder 经 raw syscall 读取内核动态状态并注入 pack——全链路
    真实运行,必须 fail closed。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.syscall.restype = ctypes.c_long\n"
        "vals = []\n"
        "for nr in (179, 309, 63, 168):\n"
        "    try:\n"
        "        rc = libc.syscall(ctypes.c_long(nr),\n"
        "                          *([ctypes.c_long(0)] * 3))\n"
        "        vals.append(str(rc))\n"
        "    except OSError as exc:\n"
        "        vals.append('E%d' % exc.errno)\n"
        "notes = {'kernel_state': vals}\n"
    )
    outcome = run_attack2j(body, label="kernel-state")
    assert not isinstance(outcome, dict), \
        f"内核动态状态进入了 pack: {outcome.get('pack_hash')}"
    name, msg = outcome
    assert name in ("BuilderRunnerError", "BuilderProvenanceError",
                    "BuilderUncertainError"), (name, msg)


def test_sysinfo_direct_attack(run_attack2j):
    """G2:sysinfo 单独攻击(uptime/内存/进程数注入 notes)。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.sysinfo.restype = ctypes.c_long\n"
        "class SI(ctypes.Structure):\n"
        "    _fields_ = [('uptime', ctypes.c_long)]\n"
        "si = SI()\n"
        "rc = libc.sysinfo(ctypes.byref(si))\n"
        "notes = {'uptime': si.uptime if rc == 0 else rc}\n"
    )
    outcome = run_attack2j(body, label="sysinfo")
    assert not isinstance(outcome, dict), "sysinfo 未被拒绝"
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")
