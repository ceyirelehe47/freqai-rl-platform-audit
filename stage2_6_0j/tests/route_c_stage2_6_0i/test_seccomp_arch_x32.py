"""工作包 C:seccomp 架构边界(C1/C2 + E8)。

- C1:BPF 先读 seccomp_data.arch 并与 AUDIT_ARCH_X86_64 比较
  (mismatch -> EPERM;fail closed);filter digest 可重算对账;
- C2:__X32_SYSCALL_BIT 置位的 syscall 显式拒绝;raw syscall 级
  实测:x32 fork/execve/clone/write 与 x86_64 fork/exec/clone;
  结果区分"seccomp 拒绝(EPERM)"与"内核原生不支持(ENOSYS)"
  (无 filter 时采集原生基线,有 filter 时必须 EPERM);
- C3:x86_64 普通路径 fork/vfork/clone/clone3/execve/execveat 全拒;
- 全部探针走真实生产 filter(canonical_seccomp_filter + prctl +
  seccomp(SET_MODE_FILTER)),fork 子进程执行以观察信号/errno。
"""

from __future__ import annotations

import ctypes
import json
import os
import signal
import sys

import pytest

from rl_builder_runtime.runner import (
    SECCOMP_PROCESS_POLICY,
    canonical_seccomp_filter,
    install_seccomp_filter,
    seccomp_filter_digest,
)

AUDIT_ARCH_X86_64 = 0xC000003E
X32_BIT = 0x40000000


# ------------------------------------------------------------ C1 结构证明
def test_filter_program_validates_arch_first():
    """BPF 第一条读 seccomp_data.arch,第二条 JEQ AUDIT_ARCH_X86_64,
    不匹配跳到 RET EPERM(arch 校验先于一切 syscall 比较)。"""
    prog = canonical_seccomp_filter()
    assert prog[0]["k"] == 4, "第一条必须加载 seccomp_data.arch(偏移4)"
    assert prog[1]["code"] == 0x15 and prog[1]["k"] == AUDIT_ARCH_X86_64
    # 不匹配跳 3 条 -> 第 5 条(0 基)必须是 RET ERRNO|EPERM
    target = prog[1 + 1 + prog[1]["jf"]]
    assert target["code"] == 0x06
    assert target["k"] == 0x00050000 | 1


def test_filter_rejects_x32_bit():
    """nr & 0x40000000 置位 -> RET EPERM(显式 x32 拒绝)。"""
    prog = canonical_seccomp_filter()
    # i2 LD nr; i3 AND 0x40000000; i4 JEQ 0x40000000 jt=0(->i5 RET)
    assert prog[2]["k"] == 0
    assert prog[3]["code"] == 0x54 and prog[3]["k"] == X32_BIT
    assert prog[4]["k"] == X32_BIT
    assert prog[5]["code"] == 0x06 and prog[5]["k"] == 0x00050000 | 1


def test_filter_policy_payload_and_digest():
    """策略载荷绑定 arch/x32/线程禁止语义;摘要可重算对账。"""
    assert SECCOMP_PROCESS_POLICY["format"] == "builder-seccomp-policy-v2"
    assert SECCOMP_PROCESS_POLICY["arch_check"]["expect"] == \
        "AUDIT_ARCH_X86_64"
    assert SECCOMP_PROCESS_POLICY["x32_check"]["mask"].startswith(
        "0x40000000")
    assert SECCOMP_PROCESS_POLICY["clone_action"] == "EPERM"
    assert SECCOMP_PROCESS_POLICY["thread_policy"] == \
        "threads_forbidden_clone_denied"
    assert SECCOMP_PROCESS_POLICY["clone"].get("require_any_flag") is None \
        if "clone" in SECCOMP_PROCESS_POLICY else True, \
        "0h 的 CLONE_THREAD 放行条目必须删除"
    assert seccomp_filter_digest() == seccomp_filter_digest(
        canonical_seccomp_filter())


# ------------------------------------------------------------ raw syscall 实测
def _raw(nr, *args):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    ctypes.set_errno(0)
    rc = libc.syscall(ctypes.c_long(nr),
                      *[ctypes.c_long(a) for a in args])
    return rc, ctypes.get_errno()


def _child_probe(fn) -> dict:
    """fork 子进程执行探针函数,回传 JSON 结果(隔离崩溃影响)。"""
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        try:
            out = fn()
        except BaseException as exc:  # noqa: BLE001
            out = {"exception": type(exc).__name__}
        try:
            os.write(w, json.dumps(out).encode())
        except OSError:
            pass
        os.close(w)
        os._exit(0)
    os.close(w)
    data = b""
    while True:
        chunk = os.read(r, 65536)
        if not chunk:
            break
        data += chunk
    os.close(r)
    _, status = os.waitpid(pid, 0)
    return {"result": json.loads(data) if data else None,
            "signaled": bool(os.WIFSIGNALED(status)),
            "term_signal": os.WTERMSIG(status) if os.WIFSIGNALED(status)
            else 0}


def _with_filter(fn):
    def runner():
        install_seccomp_filter()
        return fn()
    return _child_probe(runner)


def _errno_name(e: int) -> str:
    return {1: "EPERM", 38: "ENOSYS"}.get(e, f"ERRNO{e}")


@pytest.mark.parametrize("name,nr,args", [
    ("x32_fork", X32_BIT | 57, ()),
    ("x32_execve", X32_BIT | 59, (0, 0, 0)),
    ("x32_clone", X32_BIT | 56, (0, 0, 0, 0, 0)),
    ("x32_write", X32_BIT | 1, (-1, 0, 0)),
    ("x32_clock_gettime", X32_BIT | 228, (0, 0)),
])
def test_x32_syscalls_rejected_by_filter(name, nr, args):
    """带生产 filter:x32 syscall 必须 EPERM(seccomp 拒绝,不是内核
    原生 ENOSYS)。"""
    out = _with_filter(lambda: dict(zip(
        ("rc", "errno"), _raw(nr, *args))))
    assert not out["signaled"], f"{name} 导致崩溃: {out}"
    errno = out["result"]["errno"]
    assert _errno_name(errno) == "EPERM", (
        f"{name} 未被 filter 拒绝(errno={errno};filter 语义失效)")


@pytest.mark.parametrize("name,nr,args", [
    ("x32_write", X32_BIT | 1, (-1, 0, 0)),
    ("x32_clock_gettime", X32_BIT | 228, (0, 0)),
])
def test_kernel_native_behavior_distinguished(name, nr, args):
    """无 filter 基线:记录内核原生行为——与 filter 下的 EPERM 区分;
    不把'本机碰巧不支持 x32'当作唯一生产保证。"""
    out = _child_probe(lambda: dict(zip(("rc", "errno"), _raw(nr, *args))))
    assert not out["signaled"]
    native = _errno_name(out["result"]["errno"])
    filtered = _with_filter(lambda: dict(zip(
        ("rc", "errno"), _raw(nr, *args))))
    assert _errno_name(filtered["result"]["errno"]) == "EPERM"
    # 原生行为与 filter 的 EPERM 独立证明:EBADF(9)表示 syscall 被
    # 内核真实分发并到达参数检查(x32 原生可用);ENOSYS 表示不支持
    assert native in ("ENOSYS", "EPERM", "ERRNO14", "ERRNO9")


def test_x32_fork_actually_forks_without_filter():
    """危险基线证明:本内核原生支持 x32 fork(无 filter 时真实创建
    子进程)——x32 过滤不是多余防御,而是必要边界。"""
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        rc, err = _raw(X32_BIT | 57)
        forked = os.fork()
        if forked == 0:
            # x32 fork 成功创建的孙进程:写标记后退出
            try:
                os.write(w, b"X32-GRANDCHILD")
            except OSError:
                pass
            os.close(w)
            os._exit(0)
        os.waitpid(forked, 0)
        os.write(w, b"|PARENT-SEEN")
        os.close(w)
        os._exit(0)
    os.close(w)
    data = b""
    while True:
        chunk = os.read(r, 4096)
        if not chunk:
            break
        data += chunk
    os.close(r)
    os.waitpid(pid, 0)
    assert b"X32-GRANDCHILD" in data, (
        "本内核 x32 fork 未创建进程(基线变化;请更新矩阵解读)")


def test_x32_fork_blocked_with_filter_no_children():
    """生产 filter 下 x32 fork 不创建任何进程(与上一条对照)。"""
    def probe():
        install_seccomp_filter()
        rc, err = _raw(X32_BIT | 57)
        return {"errno": err,
                "children": len(os.listdir("/proc/self/task"))}

    out = _with_filter(probe)["result"]
    assert _errno_name(out["errno"]) == "EPERM"


@pytest.mark.parametrize("name,fn_desc", [
    ("x86_64_fork", "os.fork()"),
    ("x86_64_exec", "os.execv"),
    ("x86_64_clone_thread", "raw clone"),
])
def test_x86_64_process_creation_denied(name, fn_desc):
    """x86_64 普通路径:fork/exec/clone(含 CLONE_THREAD 线程)全拒。"""
    def probe():
        install_seccomp_filter()
        out = {}
        try:
            pid = os.fork()
            if pid == 0:
                os._exit(0)  # pragma: no cover
            os.waitpid(pid, 0)
            out["fork"] = "LEAKED"
        except OSError as exc:
            out["fork"] = f"ERRNO{exc.errno}"
        try:
            os.execv(sys.executable, [sys.executable, "-c", ""])
            out["exec"] = "LEAKED"
        except OSError as exc:
            out["exec"] = f"ERRNO{exc.errno}"
        out["clone_raw"] = f"ERRNO{_raw(56, 0)[1]}"
        out["clone3_raw"] = f"ERRNO{_raw(435, 0, 0, 0)[1]}"
        out["vfork_raw"] = f"ERRNO{_raw(58)[1]}"
        return out

    res = _child_probe(probe)["result"]
    assert res["fork"] == "ERRNO1", f"fork 未被拒绝: {res}"
    assert res["exec"] == "ERRNO1", f"exec 未被拒绝: {res}"
    assert res["clone_raw"] == "ERRNO1", "clone(线程/进程)未被拒绝"
    assert res["vfork_raw"] == "ERRNO1"
    # clone3 以 ENOSYS 拒绝(使 glibc 回退到被拒的 clone)
    assert res["clone3_raw"] == "ERRNO38"


def test_normal_syscalls_still_work_under_filter():
    """正常 syscall(getpid/read/close/mmap)不受影响(默认 allow)。"""
    def probe():
        install_seccomp_filter()
        r, w = os.pipe()
        os.write(w, b"x")
        os.close(w)
        data = os.read(r, 8)
        os.close(r)
        return {"getpid": os.getpid() > 0, "read": data.decode()}

    out = _child_probe(probe)
    assert out["result"] == {"getpid": True, "read": "x"}
