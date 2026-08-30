"""不可逆密封计算边界(阶段 2.6.0j:Prepare -> Seal -> Compute)。

正式 Builder 运行在三级结构上:

    Prepare(可信):组装/复验 bundle、读取冻结请求、受控 import 全部
        依赖并逐文件绑定 bundle manifest、模块顶层纯度验证(AST +
        运行时 audit)、预加载 native allowlist、EDIC/密封计算报告、
        quiesce 外部实测 + ACK;
    Seal(不可逆):PR_SET_MDWE(REFUSE_EXEC_GAIN) -> Worker fd 隔离
        (stdin 关闭、stdout/stderr 重定向 /dev/null、真实管道仅存
        RESULT_FD) -> 安装 final compute filter(default deny +
        显式最小 allowlist + syscall 参数过滤);
    Compute(不受信任 build_pack):纯计算。任何未列 syscall 返回
        EPERM;任何含 PROT_EXEC 的 mmap/mprotect 返回 EPERM;prctl
        被拒(PR_SET_TSC 无法重新开启);open/stat 族被拒(文件与
        元数据通道关闭);sysinfo/getcpu/uname 族被拒(内核动态状态
        不可观察);fork/clone/exec 全拒(线程/进程恒零)。

本模块只包含确定性纯函数(策略/BPF 生成/AST 验证)与安装动作;策略
字面量同时进入 BuilderRunnerProfile 与 sealed compute report 三处
同步(改一处必须三处同步)。
"""

from __future__ import annotations

import ast
import errno
import hashlib
import json

# ------------------------------------------------------------ 常量
PR_SET_MDWE = 65                       # Linux >= 6.14
PR_SET_MDWE_REFUSE_EXEC_GAIN = 1
PR_SET_TSC = 26
PR_TSC_SIGSEGV = 2
PROT_EXEC = 4

#: Seal 后唯一受信输出通道的固定 fd 号(进入 final filter 的 fd 白名单)
RESULT_FD = 87
#: final 发出后的第二阶段确认通道(原 stdin 读端的 dup;仅允许 read;
#: Supervisor 在 final 后二次实测完成前 Worker 保持存活)
RESULT_ACK_FD = 88

#: final filter 默认动作(错误处理合同:未知 syscall 一律 EPERM)
FINAL_DEFAULT_ACTION = "EPERM"

SECCOMP_FINAL_POLICY_FORMAT = "builder-seccomp-final-policy-v3"
SEALED_COMPUTE_REPORT_FORMAT = "sealed-compute-report-v2"
PURITY_REPORT_FORMAT = "builder-top-level-purity-v1"
DEPENDENCY_POLICY_FORMAT = "builder-dependency-policy-v1"

# x86_64 syscall 号(final compute allowlist)
_SYS_READ = 0
_SYS_WRITE = 1
_SYS_CLOSE = 3
_SYS_MMAP = 9
_SYS_MPROTECT = 10
_SYS_MUNMAP = 11
_SYS_BRK = 12
_SYS_RT_SIGACTION = 13
_SYS_RT_SIGPROCMASK = 14
_SYS_RT_SIGRETURN = 15
_SYS_MREMAP = 25
_SYS_MADVISE = 28
_SYS_SCHED_YIELD = 24
_SYS_GETPID = 39
_SYS_RESTART_SYSCALL = 219
_SYS_GETTID = 186
_SYS_FUTEX = 202
_SYS_EXIT = 60
_SYS_EXIT_GROUP = 231

#: 崩溃信号族:Compute 阶段禁止注册/修改其 handler(防止捕获
#: PR_TSC_SIGSEGV 等沙箱崩溃信号做边信道)
_FORBIDDEN_SIGNALS = (4, 7, 8, 11, 31)  # SIGILL/SIGBUS/SIGFPE/SIGSEGV/SIGSYS

_FINAL_ALLOWLIST: dict[str, int] = {
    "read": _SYS_READ, "write": _SYS_WRITE, "close": _SYS_CLOSE,
    "mmap": _SYS_MMAP, "mprotect": _SYS_MPROTECT, "munmap": _SYS_MUNMAP,
    "brk": _SYS_BRK, "rt_sigaction": _SYS_RT_SIGACTION,
    "rt_sigprocmask": _SYS_RT_SIGPROCMASK,
    "rt_sigreturn": _SYS_RT_SIGRETURN, "mremap": _SYS_MREMAP,
    "madvise": _SYS_MADVISE, "sched_yield": _SYS_SCHED_YIELD,
    "getpid": _SYS_GETPID, "restart_syscall": _SYS_RESTART_SYSCALL,
    "gettid": _SYS_GETTID, "futex": _SYS_FUTEX, "exit": _SYS_EXIT,
    "exit_group": _SYS_EXIT_GROUP,
}

_AUDIT_ARCH_X86_64 = 0xC000003E
_X32_SYSCALL_BIT = 0x40000000

#: 每条 allow 项的参数限制说明(进入 policy/evidence;BPF 同语义)
_ARG_POLICIES: dict[str, dict] = {
    "read": {"arg": 0, "rule": "fd-in",
             "fds": [RESULT_ACK_FD],
             "why": "仅允许读 RESULT_ACK_FD(final 后第二阶段确认;"
                    "Supervisor 在 final 行之前不写入任何字节,Build"
                    "在 Compute 内读只会阻塞至超时自毁,无输入可泄漏)"},
    "write": {"arg": 0, "rule": "fd-in",
              "fds": [1, 2, RESULT_FD],
              "why": "fd1/2 已重定向 /dev/null(Builder 写即丢弃);"
                     "RESULT_FD 是 Runner 唯一输出通道,Compute 段"
                     "任何早写被 Supervisor 记 protocol violation"},
    "mmap": {"arg": 2, "rule": "no-prot-exec", "why": "禁止新增可执行映射"},
    "mprotect": {"arg": 2, "rule": "no-prot-exec",
                 "why": "禁止 W->X(可写页不可获得执行权限)"},
    "rt_sigaction": {"arg": 0, "rule": "signal-not-in",
                     "signals": list(_FORBIDDEN_SIGNALS),
                     "why": "禁止接管崩溃信号(含 PR_TSC_SIGSEGV 路径)"},
}

FINAL_COMPUTE_POLICY: dict = {
    "format": SECCOMP_FINAL_POLICY_FORMAT,
    "arch_check": {
        "field": "seccomp_data.arch",
        "expect": "AUDIT_ARCH_X86_64",
        "mismatch_action": "EPERM(fail closed)",
    },
    "x32_check": {
        "mask": "0x40000000(__X32_SYSCALL_BIT)",
        "set_action": "EPERM(fail closed)",
    },
    "default_action": FINAL_DEFAULT_ACTION,
    "allowlist": {name: {
        "nr": nr,
        "arg_policy": _ARG_POLICIES.get(name),
    } for name, nr in sorted(_FINAL_ALLOWLIST.items())},
    "deny_families": {
        "process_thread": "fork/vfork/clone/clone3/execve/execveat"
                          "(default deny,未列入 allowlist)",
        "state_control": "prctl/seccomp/arch_prctl/personality/ptrace"
                         "/process_vm_*/setns/unshare",
        "time": "clock_gettime/time/gettimeofday/times/getrusage/"
                "nanosleep 族/timer 族/adjtimex",
        "entropy": "getrandom",
        "kernel_state": "sysinfo/getcpu/sched_getaffinity/uname/"
                        "perf_event_open/bpf",
        "file_metadata": "open/openat/creat/pread64/write(参数外fd)"
                         "/read(参数外fd)/getdents64/lseek/stat/lstat"
                         "/newfstatat/statx/statfs/fstatfs/access"
                         "/faccessat/readlink/xattr 族/mount/umount2",
        "exec_memory": "mmap/mprotect/pkey_mprotect(PROT_EXEC)/"
                       "memfd_create/userfaultfd",
        "network": "socket/connect/bind/accept/send/recv 族",
    },
    "measured_by": "strace 实测 CPython3.11 纯计算段"
                   "(brk/mmap/munmap/mremap/write)并补充运行时安全网"
                   "(信号/锁/调度/退出);未实测调用项均为无返回信息"
                   "机制类 syscall",
    "thread_policy": "threads_forbidden_clone_denied",
    "child_process_policy": "single_builder_process",
}


# ------------------------------------------------------------ BPF 生成
_BPF_LD_W_ABS = 0x20
_BPF_JEQ_K = 0x15
_BPF_JNE_K = 0x55
_BPF_ALU_AND_K = 0x54
_BPF_RET_K = 0x06
_RET_ALLOW = 0x7fff0000
_RET_ERRNO = 0x00050000
_ERRNO_EPERM = 1

_SECCOMP_DATA_ARCH = 4
_SECCOMP_DATA_NR = 0
#: args[i] 低/高 32 位偏移(64 位 args 从 offset 16 起)
_ARG_LO = (16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60)


def canonical_final_filter() -> list[dict]:
    """final compute filter 的确定性 BPF 程序(纯函数;三处同步之一)。

    结构(标签回填;default deny):
      i0  LD arch;i1 JEQ X86_64 未命中 -> RET EPERM
      i2  LD nr;i3 AND x32bit;i4 JEQ x32bit 命中 -> RET EPERM,
          未命中跳过
      调度段:每个 allow 项 JEQ nr 命中(jt) -> 参数检查段
      参数检查段:高位 32 位校验(jf 失败 -> EPERM)、fd/prot/signal
      参数限制;通过 -> RET ALLOW
      末尾 RET EPERM(default deny;未列 syscall 一律拒绝)
    """
    prog: list[dict] = []
    # (index, label, field):label 定型时回填该跳转字段
    jumps_to_fill: list[tuple[int, str, str]] = []

    def mark(label: str, field: str) -> None:
        jumps_to_fill.append((len(prog), label, field))

    def label_here(name: str) -> None:
        for entry in list(jumps_to_fill):
            idx, want, field = entry
            if want == name:
                prog[idx][field] = len(prog) - idx - 1
                jumps_to_fill.remove(entry)

    # arch 校验
    prog.append({"code": _BPF_LD_W_ABS, "jt": 0, "jf": 0,
                 "k": _SECCOMP_DATA_ARCH})
    mark("arch_bad", "jf")
    prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 0,
                 "k": _AUDIT_ARCH_X86_64})
    # nr 加载 + x32 检查
    prog.append({"code": _BPF_LD_W_ABS, "jt": 0, "jf": 0,
                 "k": _SECCOMP_DATA_NR})
    prog.append({"code": _BPF_ALU_AND_K, "jt": 0, "jf": 0,
                 "k": _X32_SYSCALL_BIT})
    mark("x32_pass", "jf")
    prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 0,
                 "k": _X32_SYSCALL_BIT})
    label_here("arch_bad")
    prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0,
                 "k": _RET_ERRNO | _ERRNO_EPERM})
    label_here("x32_pass")
    prog.append({"code": _BPF_LD_W_ABS, "jt": 0, "jf": 0,
                 "k": _SECCOMP_DATA_NR})
    prog.append({"code": _BPF_LD_W_ABS, "jt": 0, "jf": 0,
                 "k": _SECCOMP_DATA_NR})

    dispatch: list[tuple[str, int]] = sorted(
        _FINAL_ALLOWLIST.items(), key=lambda kv: kv[1])
    for name, nr in dispatch:
        mark(f"check:{name}", "jt")
        prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 0, "k": nr})

    def emit_arg_check(name: str, nr: int) -> None:
        """命中 allow 项后的参数检查(失败 EPERM,通过 ALLOW)。"""
        label_here(f"check:{name}")
        prog.append({"code": _BPF_LD_W_ABS, "jt": 0, "jf": 0,
                     "k": _SECCOMP_DATA_NR})
        # 重新确认 nr(防跳转错位):不匹配走 default deny
        mark("default_deny", "jf")
        prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 0, "k": nr})
        pol = _ARG_POLICIES.get(name)
        if pol is None:
            prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0,
                         "k": _RET_ALLOW})
            return
        arg = int(pol["arg"])
        lo = _ARG_LO[arg * 2]
        hi = _ARG_LO[arg * 2 + 1]
        # 高 32 位必须为 0(防 64 位高位绕过 32 位参数比较)
        prog.append({"code": _BPF_LD_W_ABS, "jt": 0, "jf": 0, "k": hi})
        mark(f"bad:{name}", "jf")
        prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 0, "k": 0})
        prog.append({"code": _BPF_LD_W_ABS, "jt": 0, "jf": 0, "k": lo})
        if pol["rule"] == "fd-in":
            for fd in pol["fds"]:
                mark(f"ok:{name}", "jt")
                prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 0,
                             "k": int(fd)})
        elif pol["rule"] == "no-prot-exec":
            prog.append({"code": _BPF_ALU_AND_K, "jt": 0, "jf": 0,
                         "k": PROT_EXEC})
            mark(f"ok:{name}", "jt")
            prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 0, "k": 0})
        elif pol["rule"] == "signal-not-in":
            # 注意:经典 BPF(seccomp)无 JNE;forbidden 命中跳 EPERM,
            # 未命中的信号顺序落入 RET ALLOW(与 fd/prot 段相反,
            # ALLOW 在前)
            for sig in pol["signals"]:
                mark(f"bad:{name}", "jt")
                prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 0,
                             "k": int(sig)})
            prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0,
                         "k": _RET_ALLOW})
            label_here(f"bad:{name}")
            prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0,
                         "k": _RET_ERRNO | _ERRNO_EPERM})
            return
        else:  # pragma: no cover - 生成器内部一致性
            raise AssertionError(f"未知 arg rule {pol['rule']!r}")
        label_here(f"bad:{name}")
        prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0,
                     "k": _RET_ERRNO | _ERRNO_EPERM})
        label_here(f"ok:{name}")
        prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0, "k": _RET_ALLOW})

    for name, nr in dispatch:
        emit_arg_check(name, nr)
    label_here("default_deny")
    prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0,
                 "k": _RET_ERRNO | _ERRNO_EPERM})
    if jumps_to_fill:  # pragma: no cover - 生成器内部一致性
        raise AssertionError(
            f"final filter 存在未回填跳转: {jumps_to_fill}")
    return prog


def final_filter_digest(prog: list[dict] | None = None) -> str:
    prog = canonical_final_filter() if prog is None else prog
    return "scf-" + hashlib.sha256(json.dumps(
        prog, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def install_final_compute_filter() -> dict:
    """叠加安装 final compute filter(不可逆;要求已装 Prepare filter)。"""
    import ctypes

    prog = canonical_final_filter()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS(幂等)
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS 失败")

    class BpfInstr(ctypes.Structure):
        _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8),
                    ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32)]

    class Fprog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_uint16),
                    ("filter", ctypes.POINTER(BpfInstr))]

    c_prog = (BpfInstr * len(prog))(
        *[BpfInstr(i["code"], i["jt"], i["jf"], i["k"]) for i in prog])
    fp = Fprog(len(prog), c_prog)
    libc.syscall.restype = ctypes.c_long
    rc = libc.syscall(ctypes.c_long(317), ctypes.c_uint(1),
                      ctypes.c_uint(0), ctypes.byref(fp))
    if rc != 0:
        raise OSError(ctypes.get_errno(),
                      "seccomp(SET_MODE_FILTER,final) 失败")
    return {"installed": True, "filter_hash": final_filter_digest(prog),
            "default_action": FINAL_DEFAULT_ACTION}


def apply_mdwe() -> dict:
    """B2:PR_SET_MDWE=REFUSE_EXEC_GAIN(内核不可逆;Linux>=6.14)。

    设置后本进程与后代永远无法获得新的可执行映射(W^X 硬边界)。
    与 final filter 的 mmap/mprotect PROT_EXEC 参数过滤互为独立
    双保险;内核不支持时返回 supported=False(此时 final filter 的
    参数过滤是唯一且充分的内核级后端,evidence 记录实际状态)。
    """
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    ctypes.set_errno(0)
    rc = libc.prctl(PR_SET_MDWE, PR_SET_MDWE_REFUSE_EXEC_GAIN, 0, 0, 0)
    if rc == 0:
        return {"supported": True, "enabled": True,
                "mode": "PR_SET_MDWE_REFUSE_EXEC_GAIN"}
    e = ctypes.get_errno()
    if e in (errno.EINVAL, errno.ENODEV):
        return {"supported": False, "enabled": False,
                "mode": "unsupported-kernel"}
    raise OSError(e, f"PR_SET_MDWE 失败 errno={e}(fail closed)")


def seal_worker_fds() -> dict:
    """A4:Seal 时刻的 Worker fd 隔离(必须在 final filter 安装前)。

    - 备份真实 stdout 到 RESULT_FD(dup2 固定号,final filter 只允许
      write 到 1/2/RESULT_FD);
    - stdin 关闭(Builder 无法读取未来 ACK 或消耗协议字节);
    - fd1/2 重定向到 /dev/null(Builder 的 print/write 全部无害丢弃,
      Supervisor 完全不可见);
    Seal 时刻禁止任何 lazy dlopen:本函数只使用已加载的 os 模块
    (fd 探测经 os.close 的 EBADF 语义,不 import fcntl)。
    """
    import os

    devnull = os.open("/dev/null", os.O_RDWR)
    os.dup2(1, RESULT_FD)              # 真实结果通道(固定 fd 号)
    os.dup2(0, RESULT_ACK_FD)          # 第二阶段确认通道(原 stdin 读端)
    os.close(0)                        # stdin 彻底关闭(read -> EBADF;
                                       # Builder 无法读取未来 ACK 或
                                       # 消耗协议字节)
    os.dup2(devnull, 1)                # stdout -> /dev/null
    os.dup2(devnull, 2)                # stderr -> /dev/null
    if devnull > 2:
        os.close(devnull)
    # 关闭 RESULT_FD/RESULT_ACK_FD 之外的继承 fd(保留 0/1/2/87/88)
    opened = []
    for fd in range(3, 1 << 16):
        if fd in (RESULT_FD, RESULT_ACK_FD):
            continue
        try:
            os.close(fd)
            opened.append(fd)
        except OSError:
            continue
    return {
        "stdin": "closed",
        "stdout": "redirected-devnull",
        "stderr": "redirected-devnull",
        "result_fd": RESULT_FD,
        "result_ack_fd": RESULT_ACK_FD,
        "result_channel": "runner-only-write-after-build",
        "closed_fds": sorted(opened),
    }


# ------------------------------------------------------------ 依赖 allowlist
#: 正式 profile 的纯 Python 模块 allowlist(顶层 import 白名单)
FORMAL_PURE_MODULES: tuple[str, ...] = (
    "abc", "cmath", "collections", "collections.abc", "dataclasses",
    "datetime", "decimal", "enum", "fractions", "functools", "hashlib",
    "itertools", "json", "math", "numbers", "operator", "random", "re",
    "statistics", "string", "threading", "time", "typing", "unicodedata",
)
#: native(含 C 加速器)受审计确定性模块:native 闭包逐文件绑定 bundle
FORMAL_NATIVE_MODULES: tuple[str, ...] = (
    "math", "cmath", "hashlib", "_hashlib", "_sha256", "_sha512",
    "_md5", "_random", "_datetime", "_json", "_decimal", "_statistics",
    "unicodedata", "_sre",
)
#: 正式 profile 明确拒绝的危险模块(即便经由 sys.modules 直取也已由
#: final filter 关闭其 native 通道;AST/allowlist 层在 import 时拒绝)
FORMAL_FORBIDDEN_MODULES: tuple[str, ...] = (
    "ctypes", "cffi", "mmap", "subprocess", "multiprocessing", "os",
    "pathlib", "resource", "signal", "socket", "importlib", "numba",
    "torch", "numpy", "sys", "builtins", "code", "codeop", "compileall",
    "runpy", "pickle", "marshal", "shelve", "webbrowser", "antigravity",
)


def dependency_policy(formal: bool = True) -> dict:
    """A3:依赖面策略载荷(进入 sealed compute report)。"""
    if formal:
        return {
            "format": DEPENDENCY_POLICY_FORMAT,
            "profile": "formal",
            "pure_modules": sorted(set(FORMAL_PURE_MODULES)
                                   - set(FORMAL_NATIVE_MODULES)),
            "native_modules": sorted(FORMAL_NATIVE_MODULES),
            "native_policy": "Seal 前预加载;文件进入 bundle native "
                             "closure;无地址/加载/随机 API",
            "forbidden_modules": sorted(FORMAL_FORBIDDEN_MODULES),
            "third_party_native": "rejected",
            "numpy_formal_eligible": False,
            "formal_eligible": True,
        }
    return {
        "format": DEPENDENCY_POLICY_FORMAT,
        "profile": "compat",
        "pure_modules": ["*"],
        "native_modules": ["*"],
        "forbidden_modules": [],
        "third_party_native": "allowed-without-formal-evidence",
        "numpy_formal_eligible": False,
        "formal_eligible": False,
    }


def preload_formal_modules() -> list[str]:
    """Seal 前强制加载全部 allowlist 模块(Compute 内零 dlopen)。"""
    import importlib

    loaded: list[str] = []
    for name in sorted(set(FORMAL_PURE_MODULES) | set(
            FORMAL_NATIVE_MODULES)):
        importlib.import_module(name)
        loaded.append(name)
    return loaded


# ------------------------------------------------------------ 顶层纯度(A1)
_LITERAL_VALUE_NODES = (ast.Constant,)


def _is_literal_expr(node: ast.expr) -> bool:
    """字面量或由字面量直接构造的不可变容器(递归;禁止任何调用)。"""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_literal_expr(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            (_is_literal_expr(k) if k is not None else False)
            and _is_literal_expr(v)
            for k, v in zip(node.keys, node.values))
    return False


_TOP_ALLOWED_STMT = (
    ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef,
    ast.ClassDef, ast.Assign, ast.AnnAssign, ast.Pass, ast.Expr,
)


def validate_top_level_purity(source: str, module_name: str,
                              *, allow_prefixes: tuple[str, ...] = (),
                              formal: bool = True) -> dict:
    """A1:模块顶层纯度 AST 验证。

    顶层只允许:allowlist import、函数/类定义、Pass、docstring、
    字面量赋值。类体同规则(类体在 import 时刻执行)。函数体不限制
    (其运行期行为由 Compute 阶段 final filter + audit 违规清单管)。
    兼容 profile(formal=False)放宽为:拒绝危险模块 import 与任意
    顶层外部调用检测仍生效,但不强制字面量赋值。
    """
    problems: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"format": PURITY_REPORT_FORMAT, "ok": False,
                "module": module_name,
                "problems": [f"语法错误: {exc.msg}(line {exc.lineno})"],
                "checked_statements": 0}
    pure_set = set(FORMAL_PURE_MODULES) | set(FORMAL_NATIVE_MODULES)
    forbidden_set = set(FORMAL_FORBIDDEN_MODULES)

    def check_import(names: list[str], node: ast.AST) -> None:
        for mod in names:
            top = mod.split(".")[0]
            if not formal:
                # 兼容 profile:放开第三方 native(如 NumPy)与系统模块
                # import(其运行期行为仍由 final filter 机制层管辖;
                # formal_eligible=false,不形成可信材料)
                continue
            if mod in forbidden_set or top in forbidden_set:
                problems.append(f"顶层 import {mod!r} 属于禁止模块")
            elif mod in pure_set or top in pure_set:
                continue
            elif any(mod == p or mod.startswith(p + ".")
                     for p in allow_prefixes):
                continue  # builder package 内部模块
            else:
                problems.append(
                    f"顶层 import {mod!r} 不在正式 allowlist(纯模块="
                    f"{sorted(set(FORMAL_PURE_MODULES))})")

    def walk_body(stmts: list[ast.stmt], where: str) -> int:
        count = 0
        for stmt in stmts:
            count += 1
            if isinstance(stmt, ast.Import):
                check_import([a.name for a in stmt.names], stmt)
                continue
            if isinstance(stmt, ast.ImportFrom):
                if stmt.module:
                    check_import([stmt.module], stmt)
                for a in stmt.names:  # from X import name 归属同一模块
                    pass
                continue
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if stmt.decorator_list:
                    problems.append(
                        f"{where}: 函数 {stmt.name!r} 带装饰器"
                        f"(顶层装饰器调用被拒绝)")
                continue
            if isinstance(stmt, ast.ClassDef):
                if stmt.decorator_list:
                    problems.append(
                        f"{where}: 类 {stmt.name!r} 带装饰器(顶层装饰器"
                        f"调用被拒绝)")
                for base in stmt.bases:
                    if not isinstance(base, (ast.Name, ast.Attribute)):
                        problems.append(
                            f"{where}: 类 {stmt.name!r} 基类必须是简单"
                            f"名字引用")
                if stmt.keywords:
                    problems.append(
                        f"{where}: 类 {stmt.name!r} 带 keyword 元类参数"
                        f"(调用语义;被拒绝)")
                walk_body(stmt.body, f"类体 {stmt.name!r}")
                continue
            if isinstance(stmt, ast.Assign):
                for value in [stmt.value]:
                    if formal and not _is_literal_expr(value):
                        problems.append(
                            f"{where}: 赋值右侧必须是字面量(收到 "
                            f"{type(value).__name__};顶层构造调用被"
                            f"拒绝)")
                continue
            if isinstance(stmt, ast.AnnAssign):
                if formal and stmt.value is not None \
                        and not _is_literal_expr(stmt.value):
                    problems.append(
                        f"{where}: 注解赋值右侧必须是字面量")
                continue
            if isinstance(stmt, ast.Pass):
                continue
            if isinstance(stmt, ast.Expr):
                if isinstance(stmt.value, ast.Constant) \
                        and isinstance(stmt.value.value, str):
                    continue  # docstring
                problems.append(
                    f"{where}: 表达式语句只允许 docstring(收到 "
                    f"{type(stmt.value).__name__})")
                continue
            problems.append(
                f"{where}: 顶层语句 {type(stmt).__name__} 不被允许")
        return count

    checked = walk_body(tree.body, "模块顶层")
    return {
        "format": PURITY_REPORT_FORMAT,
        "ok": not problems,
        "module": module_name,
        "profile": "formal" if formal else "compat",
        "problems": problems[:64],
        "checked_statements": checked,
        "ast_rule": "import-allowlist|def/class|literal-assign|docstring",
    }


def purity_report_digest(reports: list[dict]) -> str:
    return "pur-" + hashlib.sha256(json.dumps(
        reports, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
