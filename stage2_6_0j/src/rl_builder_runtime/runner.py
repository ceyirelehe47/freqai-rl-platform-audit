"""Builder Runner worker:密闭沙箱内执行私有 Builder(阶段 2.6.0j)。

启动形态(bootstrap 在内容寻址 bundle rootfs 内 exec;无 /proc、无
/usr、无宿主 conda 活树、/dev 无真实熵源设备、Landlock+ro rootfs 已
生效):

    /bin/python3.11 -m rl_builder_runtime.runner <builder_pkg> \
        <entrypoint_module> <entrypoint_qualname>

协议(builder-runner-worker-v4;每行一个 JSON):
- stdin:  单行冻结构建请求(builder-build-request-v3);quiesce 阶段
  再读一行 Supervisor ack(ACK 之后 stdin 立即关闭);
- stdout: 第一行 quiesce(sealed compute report v2 + 运行时锁 worker
  部分 + access 摘要,请求 Supervisor 从外部 /proc 实测 native/线程
  状态),第二行 final(build_result;经 RESULT_FD 单向通道发出)。
  失败路径只发一行 final(status=failed)。

阶段 2.6.0j 职责(在 0i 之上,Prepare -> Seal -> Compute):
- Prepare:v2 filter(进程/时钟/熵)+vDSO 冻结+PR_SET_TSC(SIGSEGV);
  native allowlist 预加载(Seal 前完成全部 dlopen);builder 包逐
  文件顶层纯度 AST 验证;受控 import;导入闭包与逐文件哈希**全部
  在 build 前完成**(Compute 阶段零文件访问);
- Seal(ACK 后不可逆):PR_SET_MDWE(REFUSE_EXEC_GAIN,内核>=6.14;
  不支持时由 final filter 参数过滤作为同级内核后端,evidence 记录
  实际状态) -> fd 隔离(stdin 关闭、1/2 重定向 /dev/null、真实
  管道仅存 RESULT_FD) -> final compute filter(**default deny** +
  最小 allowlist + write/mmap/mprotect/rt_sigaction 参数过滤);
- Compute:build_pack(request) 纯计算——prctl 被拒(PR_TSC_ENABLE
  无法重新开启 TSC)、open/stat/statfs/sysinfo/getcpu/uname/getrandom
  /clock 全拒、PROT_EXEC 全拒、线程/进程全拒、未知 syscall 一律
  EPERM;Compute 内任何 import/open/exec/compile 尝试由 audit hook
  记违规并在采信前拒绝;build 返回后由 Runner 序列化并经 RESULT_FD
  单向发出(Builder 无法直接污染 Supervisor 协议流)。

进程以 os._exit 终止(munmap vDSO 后解释器常规收尾不可靠)。
"""

from __future__ import annotations

import errno
import hashlib
import importlib
import inspect
import json
import os
import sys
import types
from pathlib import Path

from rl_builder_runtime import BUILDER_WORKER_HOSTNAME, BUILDER_WORKER_PROTOCOL

MAX_LINE_BYTES = 32 * 1024 * 1024

FORBIDDEN_PARAM_NAMES = (
    "candidate", "candidate_path", "checkpoint", "checkpoint_path",
    "model", "policy", "score", "scores", "result", "exam_result",
    "verdict", "outcome", "prediction", "ranking",
)

RESULT_FIELDS = frozenset({
    "format", "runner_protocol", "status", "pack", "attempt_log", "error",
})
ATTEMPT_ENTRY_FIELDS = frozenset({"attempt", "verdict", "reject_reasons"})

ATTEMPT_LOG_FORMAT_V2 = "builder-attempt-log-v2"
BUILD_RESULT_FORMAT_V3 = "builder-build-result-v3"
RUNNER_PROTOCOL_V3 = "builder-runner-protocol-v3"
REQUEST_FORMAT_V3 = "builder-build-request-v3"
RUNTIME_LOCK_FORMAT_V4 = "builder-runtime-lock-v4"
ACCESS_SUMMARY_FORMAT_V2 = "builder-access-summary-v2"
#: 2.6.0j:EDIC 升级为 sealed compute report v2(Seal 后计算边界证明)
EDIC_FORMAT = "sealed-compute-report-v2"
SINGLE_PROCESS = "single_builder_process"
ALLOW_DESCENDANTS = "allow_descendants"
THREAD_POLICY_FORBIDDEN = "threads_forbidden_clone_denied"
THREAD_POLICY_DEMO = "demo_allow_descendants"
DEP_PROFILE_FORMAL = "formal"
DEP_PROFILE_COMPAT = "compat"

BUILDER_PKG_MOUNT = "/builder_pkg"
RUNTIME_MOUNT = "/runtime"
BUNDLE_MANIFEST_PATH = "/manifest.json"
BUNDLE_META_PATH = "/bundle_meta.json"
DEV_INTERNAL_MOUNT = "/dev-internal"

# ------------------------------------------------------------ seccomp(C1/C2)
#: x86_64 syscall 编号(进程树/内核状态修改类 + 时钟 + 熵)
_SYS_FORK = 57
_SYS_VFORK = 58
_SYS_CLONE = 56
_SYS_EXECVE = 59
_SYS_PTRACE = 101
_SYS_MOUNT = 165
_SYS_UMOUNT2 = 166
_SYS_UNSHARE = 272
_SYS_SETNS = 308
_SYS_PROCESS_VM_READV = 310
_SYS_PROCESS_VM_WRITEV = 311
_SYS_EXECVEAT = 322
_SYS_BPF = 321
_SYS_PERF_EVENT_OPEN = 298
_SYS_CLONE3 = 435
#: 时钟观测/休眠(rdtsc 由 PR_SET_TSC 封禁;vDSO 由 munmap 封禁)
_SYS_NANOSLEEP = 35
_SYS_GETTIMEOFDAY = 96
_SYS_GETRUSAGE = 98
_SYS_TIMES = 100
_SYS_ADJTIMEX = 159
_SYS_TIME = 201
_SYS_CLOCK_SETTIME = 229
_SYS_CLOCK_GETTIME = 228
_SYS_CLOCK_NANOSLEEP = 230
_SYS_CLOCK_ADJTIME = 305
_SYS_GETRANDOM = 318
_SYS_CLOCK_GETTIME64 = 403

_AUDIT_ARCH_X86_64 = 0xC000003E
_X32_SYSCALL_BIT = 0x40000000

SECCOMP_PROCESS_POLICY = {
    "format": "builder-seccomp-policy-v2",
    "arch_check": {
        "field": "seccomp_data.arch",
        "expect": "AUDIT_ARCH_X86_64",
        "mismatch_action": "EPERM(fail closed)",
    },
    "x32_check": {
        "mask": "0x40000000(__X32_SYSCALL_BIT)",
        "set_action": "EPERM(fail closed)",
    },
    "default_action": "allow",
    "deny_eperm": sorted(name for name in (
        "fork", "vfork", "execve", "execveat", "ptrace", "mount",
        "umount2", "unshare", "setns", "process_vm_readv",
        "process_vm_writev", "bpf", "perf_event_open",
        # B1 时钟族
        "nanosleep", "gettimeofday", "getrusage", "times", "adjtimex",
        "time", "clock_settime", "clock_gettime", "clock_nanosleep",
        "clock_adjtime", "clock_gettime64",
        # B2 熵
        "getrandom")),
    "clone3_action": "ENOSYS",
    "clone_action": "EPERM",
    "thread_policy": THREAD_POLICY_FORBIDDEN,
    "child_process_policy": SINGLE_PROCESS,
}

_BPF_LD_W_ABS = 0x20
_BPF_JEQ_K = 0x15
_BPF_ALU_AND_K = 0x54
_BPF_RET_K = 0x06
_RET_ALLOW = 0x7fff0000
_RET_ERRNO = 0x00050000
_ERRNO_EPERM = 1
_ERRNO_ENOSYS = 38
#: seccomp_data 偏移:arch=4, nr=0
_SECCOMP_DATA_ARCH = 4
_SECCOMP_DATA_NR = 0

# seccomp_data.clone_flags 偏移(x86_64:args[0] -> 24)


def canonical_seccomp_filter() -> list[dict]:
    """进程/时钟/熵策略的确定性 BPF 程序(纯函数;主进程重算对账)。

    指令布局(jt/jf 是相对下一条指令的偏移,逐条显式核算):
      i0 LD arch          (seccomp_data.arch)
      i1 JEQ X86_64, jf=3 -> 非 x86_64 跳到 i5 RET EPERM(arch 校验)
      i2 LD nr
      i3 AND 0x40000000
      i4 JEQ 0x40000000, jf=1 -> x32 置位跳到 i5 RET EPERM(x32 拒绝)
      i5 RET EPERM(arch mismatch / x32)
      i6 LD nr            (AND 破坏 nr 后重载)
      i7.. deny_eperm 逐号 JEQ(命中 -> RET EPERM)
      .. clone3 -> RET ENOSYS;clone -> RET EPERM;其余 RET ALLOW
    """
    nr = {
        "fork": _SYS_FORK, "vfork": _SYS_VFORK, "execve": _SYS_EXECVE,
        "execveat": _SYS_EXECVEAT, "ptrace": _SYS_PTRACE,
        "mount": _SYS_MOUNT, "umount2": _SYS_UMOUNT2,
        "unshare": _SYS_UNSHARE, "setns": _SYS_SETNS,
        "process_vm_readv": _SYS_PROCESS_VM_READV,
        "process_vm_writev": _SYS_PROCESS_VM_WRITEV, "bpf": _SYS_BPF,
        "perf_event_open": _SYS_PERF_EVENT_OPEN,
        "nanosleep": _SYS_NANOSLEEP, "gettimeofday": _SYS_GETTIMEOFDAY,
        "getrusage": _SYS_GETRUSAGE, "times": _SYS_TIMES,
        "adjtimex": _SYS_ADJTIMEX, "time": _SYS_TIME,
        "clock_settime": _SYS_CLOCK_SETTIME,
        "clock_gettime": _SYS_CLOCK_GETTIME,
        "clock_nanosleep": _SYS_CLOCK_NANOSLEEP,
        "clock_adjtime": _SYS_CLOCK_ADJTIME,
        "getrandom": _SYS_GETRANDOM,
        "clock_gettime64": _SYS_CLOCK_GETTIME64,
    }
    denies = [nr[name] for name in SECCOMP_PROCESS_POLICY["deny_eperm"]]
    prog: list[dict] = [
        {"code": _BPF_LD_W_ABS, "jt": 0, "jf": 0, "k": _SECCOMP_DATA_ARCH},
        # i1:match -> i2;不匹配 -> i5(jf=3)
        {"code": _BPF_JEQ_K, "jt": 0, "jf": 3, "k": _AUDIT_ARCH_X86_64},
        {"code": _BPF_LD_W_ABS, "jt": 0, "jf": 0, "k": _SECCOMP_DATA_NR},
        {"code": _BPF_ALU_AND_K, "jt": 0, "jf": 0, "k": _X32_SYSCALL_BIT},
        # i4:x32 置位 -> i5(jt=0);未置位 -> i6(jf=1)
        {"code": _BPF_JEQ_K, "jt": 0, "jf": 1, "k": _X32_SYSCALL_BIT},
        {"code": _BPF_RET_K, "jt": 0, "jf": 0,
         "k": _RET_ERRNO | _ERRNO_EPERM},  # i5:arch mismatch / x32
        {"code": _BPF_LD_W_ABS, "jt": 0, "jf": 0, "k": _SECCOMP_DATA_NR},
    ]
    for n in sorted(denies):
        prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 1, "k": n})
        prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0,
                     "k": _RET_ERRNO | _ERRNO_EPERM})
    prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 1, "k": _SYS_CLONE3})
    prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0,
                 "k": _RET_ERRNO | _ERRNO_ENOSYS})
    prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 1, "k": _SYS_CLONE})
    prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0,
                 "k": _RET_ERRNO | _ERRNO_EPERM})
    prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0, "k": _RET_ALLOW})
    return prog


def seccomp_filter_digest(prog: list[dict] | None = None) -> str:
    prog = canonical_seccomp_filter() if prog is None else prog
    return "scp-" + hashlib.sha256(json.dumps(
        prog, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def install_seccomp_filter() -> dict:
    """安装 v2 filter(要求 no_new_privs;fail closed)。"""
    import ctypes

    prog = canonical_seccomp_filter()
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
        raise OSError(ctypes.get_errno(), "seccomp(SET_MODE_FILTER) 失败")
    return {"installed": True, "filter_hash": seccomp_filter_digest(prog),
            "no_new_privs": 1}


# ---------------------------------------------------- 时钟/熵封禁(B1/B2)
AT_SYSINFO_EHDR = 33
PR_SET_TSC = 26  # prctl.h:PR_GET_TSC=25 / PR_SET_TSC=26(实测验证)
PR_TSC_SIGSEGV = 2
MAP_FIXED = 0x10
MAP_PRIVATE = 0x02
MAP_ANONYMOUS = 0x20
PROT_NONE = 0
PROT_READ = 1
PROT_WRITE = 2
PROT_EXEC = 4
FROZEN_EPOCH_SECONDS = 0

#: vDSO 导出符号 -> 冻结 stub 的 x86_64 机器码(返回冻结纪元 0;
#: 指针参数带 NULL 保护;字节布局由本模块确定性生成并进入证据)
_VDSO_STUB_ASM = {
    # clock_gettime(clk rdi, struct timespec *tp rsi): tp={0,0}; return 0
    "__vdso_clock_gettime": bytes.fromhex(
        "4885f6" "740f"            # test rsi,rsi; je +15
        "48c70600000000"           # mov qword [rsi],0
        "48c7460800000000"         # mov qword [rsi+8],0
        "31c0" "c3"),              # xor eax,eax; ret
    # time(time_t *t rdi): *t=0; return 0
    "__vdso_time": bytes.fromhex(
        "4885ff" "7407"            # test rdi,rdi; je +7
        "48c70700000000"           # mov qword [rdi],0
        "31c0" "c3"),
    # gettimeofday(struct timeval *tv rdi, tz rsi): tv={0,0}; return 0
    "__vdso_gettimeofday": bytes.fromhex(
        "4885ff" "740f"
        "48c70700000000"           # mov qword [rdi],0 (tv_sec)
        "48c7470800000000"         # mov qword [rdi+8],0 (tv_usec)
        "31c0" "c3"),
    # clock_getres(clk rdi, struct timespec *res rsi): res={1,0}; return 0
    "__vdso_clock_getres": bytes.fromhex(
        "4885f6" "740f"
        "48c70601000000"           # mov qword [rsi],1
        "48c7460800000000"         # mov qword [rsi+8],0
        "31c0" "c3"),
    # getcpu(unsigned *cpu rdi, unsigned *node rsi, tcache rdx): 0/0; ret 0
    "__vdso_getcpu": bytes.fromhex(
        "4885ff" "7406" "c70700000000"     # cpu=null? skip : *cpu=0(6B)
        "4885f6" "7406" "c70600000000"     # node=null? skip : *node=0(6B)
        "31c0" "c3"),
}


def _vdso_symbol_offsets(base: int, size: int) -> dict[str, int]:
    """解析 vDSO ELF 的 .dynsym/.dynstr,取冻结目标符号偏移。"""
    import ctypes
    import struct

    blob = ctypes.string_at(ctypes.c_void_p(base), size)
    if blob[:5] != b"\x7fELF\x02":
        raise _RunnerFailure("vDSO 不是 ELF64(意外布局;fail closed)")
    e_phoff = struct.unpack_from("<Q", blob, 0x20)[0]
    e_phentsize = struct.unpack_from("<H", blob, 0x36)[0]
    e_phnum = struct.unpack_from("<H", blob, 0x38)[0]
    loads = []
    dyn_off = None
    dyn_filesz = 0
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type = struct.unpack_from("<I", blob, off)[0]
        if p_type == 1:
            loads.append((struct.unpack_from("<Q", blob, off + 16)[0],
                          struct.unpack_from("<Q", blob, off + 8)[0],
                          struct.unpack_from("<Q", blob, off + 32)[0]))
        elif p_type == 2:
            dyn_off = struct.unpack_from("<Q", blob, off + 8)[0]
            dyn_filesz = struct.unpack_from("<Q", blob, off + 32)[0]
    if not loads or dyn_off is None or dyn_filesz < 16:
        raise _RunnerFailure("vDSO 缺 PT_LOAD/PT_DYNAMIC(fail closed)")

    def v2o(v: int) -> int:
        for vaddr, off, filesz in loads:
            if vaddr <= v < vaddr + filesz:
                return off + (v - vaddr)
        raise _RunnerFailure("vDSO 动态段地址越界(fail closed)")

    symtab = strtab = None
    for i in range(dyn_filesz // 16):
        tag, val = struct.unpack_from("<QQ", blob, dyn_off + i * 16)
        if tag == 0:
            break
        if tag == 6:
            symtab = val
        elif tag == 5:
            strtab = val
    if symtab is None or strtab is None:
        raise _RunnerFailure("vDSO 缺 DT_SYMTAB/DT_STRTAB(fail closed)")
    sym_off, str_off = v2o(symtab), v2o(strtab)
    # .dynsym 条目数 = (strtab - symtab) / 24(相邻惯例);逐条匹配名字
    count = (str_off - sym_off) // 24 if str_off > sym_off else 0
    if count <= 0 or count > 4096:
        raise _RunnerFailure("vDSO dynsym 尺寸异常(fail closed)")
    found: dict[str, int] = {}
    for i in range(count):
        entry = sym_off + i * 24
        st_name = struct.unpack_from("<I", blob, entry)[0]
        st_value = struct.unpack_from("<Q", blob, entry + 8)[0]
        if st_value == 0:
            continue
        end = blob.index(b"\0", str_off + st_name)
        name = blob[str_off + st_name:end].decode("ascii", "replace")
        if name in _VDSO_STUB_ASM:
            found[name] = st_value
    return found


def virtualize_vdso_clock() -> dict:
    """B1:把 vDSO 时钟路径替换为**冻结 stub**(虚拟冻结纪元 0)。

    glibc 在启动时已把 clock_gettime/time/gettimeofday 解析为 vDSO
    内部绝对地址;munmap vDSO 后在**同一基址**重映射匿名页,先整页
    回写原始 vDSO 字节(ld.so 把 vDSO 视作链接映射对象,dlopen 时会
    遍历其 ELF 结构——元数据必须完整),再在原符号偏移处覆写冻结
    stub:任何时钟读取恒返回冻结纪元 0(进入证据的确定性值),真实
    时间不可观察。之后 mprotect 为 R+X(W^X)。原始 vDSO 字节摘要
    与 stub 摘要进入证据。
    """
    import ctypes
    import hashlib as _hashlib
    import struct

    libc = ctypes.CDLL(None, use_errno=True)
    libc.getauxval.restype = ctypes.c_ulong
    base = int(libc.getauxval(ctypes.c_ulong(AT_SYSINFO_EHDR)))
    if not base:
        return {"vdso": "absent-at-exec", "mode": "no-vdso",
                "frozen_epoch": FROZEN_EPOCH_SECONDS,
                "stubs": {}, "original_vdso_sha256": ""}
    # 范围(PT_LOAD 极值)与符号偏移
    header = ctypes.string_at(ctypes.c_void_p(base), 64)
    e_phoff = struct.unpack_from("<Q", header, 0x20)[0]
    e_phentsize = struct.unpack_from("<H", header, 0x36)[0]
    e_phnum = struct.unpack_from("<H", header, 0x38)[0]
    ph = ctypes.string_at(ctypes.c_void_p(base + e_phoff),
                          e_phentsize * e_phnum)
    extent = 0
    for i in range(e_phnum):
        off = i * e_phentsize
        if struct.unpack_from("<I", ph, off)[0] != 1:
            continue
        extent = max(extent,
                     struct.unpack_from("<Q", ph, off + 16)[0]
                     + struct.unpack_from("<Q", ph, off + 40)[0])
    if extent <= 0:
        raise _RunnerFailure("vDSO PT_LOAD 为空(fail closed)")
    size = (extent + 4095) & ~4095
    offsets = _vdso_symbol_offsets(base, size)
    if "__vdso_clock_gettime" not in offsets:
        raise _RunnerFailure(
            "vDSO 缺 __vdso_clock_gettime 符号(无法冻结时钟;"
            "fail closed)")
    blob = ctypes.string_at(ctypes.c_void_p(base), size)
    vdso_sha = _hashlib.sha256(blob).hexdigest()
    # munmap 原vDSO,同基址重映射;整页回写原字节,仅覆写函数 stub
    libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    ctypes.set_errno(0)
    if libc.munmap(ctypes.c_void_p(base), size) != 0:
        raise _RunnerFailure(
            f"vDSO munmap 失败 errno={ctypes.get_errno()}(fail closed)")
    libc.mmap.restype = ctypes.c_void_p
    libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_long]
    ctypes.set_errno(0)
    got = libc.mmap(ctypes.c_void_p(base), size,
                    PROT_READ | PROT_WRITE | PROT_EXEC,
                    MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0)
    if int(got or 0) != base:
        raise _RunnerFailure(
            f"vDSO 基址重映射失败 errno={ctypes.get_errno()}"
            f"(fail closed)")
    ctypes.memmove(ctypes.c_void_p(base), blob, size)
    for name, offset in sorted(offsets.items()):
        stub = _VDSO_STUB_ASM[name]
        if offset + len(stub) > size:
            raise _RunnerFailure("vDSO stub 越界(fail closed)")
        ctypes.memmove(ctypes.c_void_p(base + offset), stub, len(stub))
    ctypes.set_errno(0)
    if libc.mprotect(ctypes.c_void_p(base), size,
                     PROT_READ | PROT_EXEC) != 0:
        raise _RunnerFailure(
            f"vDSO stub mprotect 失败 errno={ctypes.get_errno()}")
    return {
        "vdso": "replaced-with-frozen-stub", "mode": "frozen-stub",
        "frozen_epoch": FROZEN_EPOCH_SECONDS,
        "stubs": {k: offsets[k] for k in sorted(offsets)},
        "stub_sha256": _hashlib.sha256(b"".join(
            _VDSO_STUB_ASM[k] for k in sorted(offsets))).hexdigest(),
        "original_vdso_sha256": vdso_sha,
    }


def disable_tsc() -> int:
    """B1:PR_SET_TSC=PR_TSC_SIGSEGV(RDTSC/RDTSCP 触发 SIGSEGV)。"""
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    ctypes.set_errno(0)
    rc = libc.prctl(PR_SET_TSC, PR_TSC_SIGSEGV, 0, 0, 0)
    if rc != 0:
        raise _RunnerFailure(
            f"PR_SET_TSC 失败 errno={ctypes.get_errno()}(fail closed)")
    return rc


def _raw_syscall_probe(nr: int, *args) -> str:
    """raw syscall 探针(不经 glibc 包装;seccomp 返回 errno)。"""
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    ctypes.set_errno(0)
    rc = libc.syscall(ctypes.c_long(nr),
                      *[ctypes.c_long(a) for a in args])
    e = ctypes.get_errno()
    if rc == 0:
        return "ALLOWED(策略失效!)"
    return f"ERRNO{e}"


# ------------------------------------------------------------ 访问审计
#: Compute 阶段零容忍事件(任何一次出现即拒绝采信 build 结果;
#: syscall 层由 final filter 机制化拒绝,这里是语义层第二道防线)
_COMPUTE_FORBIDDEN_EVENTS = (
    "import", "open", "os.listdir", "os.scandir", "os.system",
    "subprocess.Popen", "ctypes.dlopen", "ctypes.dlsym", "os.fork",
    "os.exec", "os.posix_spawn", "os.spawn", "exec", "compile",
    "builtins.input", "os.putenv", "os.unsetenv",
)
#: toplevel 阶段(builder 模块 import 执行期间)禁令:只禁 import 机制
#: 与受审计库初始化自身不会产生的事件——importlib 的 open/compile/
#: exec/import 是模块加载的合法足迹(路径/模块身份另由 bundle 前缀
#: 检查与导入闭包逐文件绑定管辖;顶层代码自身的任何调用已由 AST
#: 纯度验证拒绝)。native 库初始化(如 OpenBLAS 的 os.putenv)不引入
#: 外部输入,允许;os.environ 的运行期取值仍由 EDIC 白名单快照管辖。
_TOPLEVEL_FORBIDDEN_EVENTS = (
    "os.system", "subprocess.Popen", "ctypes.dlopen", "ctypes.dlsym",
    "os.fork", "os.exec", "os.posix_spawn", "os.spawn",
    "builtins.input",
)
#: toplevel 阶段 open 的合法前缀(bundle 内:builder 包/运行时/标准库)
_TOPLEVEL_OPEN_PREFIXES = ("/builder_pkg/", "/runtime/", "/lib/",
                           "/manifest.json", "/bundle_meta.json")


class _AccessRecorder:
    """audit hook:CPython 实际运行时访问事件(计数/子进程/exec/dlopen)。

    2.6.0j:phase 感知扩展——toplevel(builder import 执行期间)与
    compute(build_pack 执行期间)的危险事件进入违规清单,在结果被
    采信前检查(fail closed);prelude/report/closure/seal 阶段是
    Runner 自身可信逻辑,只计数不计违规。
    """

    PATH_EVENTS = {
        "open": 0, "os.listdir": 0, "os.scandir": 0,
        "os.system": 0, "subprocess.Popen": 0, "ctypes.dlopen": 0,
    }
    CHILD_EVENTS = ("subprocess.Popen", "os.fork", "os.system")
    EXEC_EVENTS = ("os.exec", "os.posix_spawn", "os.spawn")

    def __init__(self, allowlist_prefixes: list[str]):
        self._prefixes = [str(p) for p in allowlist_prefixes]
        self.phase = "prelude"
        self.open_events: list[str] = []
        self.outside: list[str] = []
        self.dlopen_targets: list[str] = []
        self.child_process_attempts = 0
        self.exec_attempts = 0
        self.event_counts: dict[str, int] = {}
        #: toplevel/compute 阶段的违规(事件名,参数摘要);采信前必须为空
        self.phase_violations: list[str] = []

    def _record_violation(self, event: str, args) -> None:
        if len(self.phase_violations) < 256:
            detail = ""
            try:
                if args:
                    first = args[0]
                    if isinstance(first, str):
                        detail = first[:80]
                    elif isinstance(first, bytes):
                        detail = first[:80].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - 审计绝不影响执行
                detail = ""
            self.phase_violations.append(f"{event}:{detail}" if detail
                                         else event)

    def hook(self, event: str, args) -> None:
        try:
            self.event_counts[event] = self.event_counts.get(event, 0) + 1
            if self.phase == "compute":
                if event in _COMPUTE_FORBIDDEN_EVENTS:
                    self._record_violation(event, args)
                if event in self.EXEC_EVENTS:
                    self.exec_attempts += 1
                    return
                if event in self.CHILD_EVENTS:
                    self.child_process_attempts += 1
                    return
                return
            if self.phase == "toplevel":
                if event in _TOPLEVEL_FORBIDDEN_EVENTS:
                    self._record_violation(event, args)
                    if event in self.EXEC_EVENTS:
                        self.exec_attempts += 1
                    elif event in self.CHILD_EVENTS:
                        self.child_process_attempts += 1
                    return
                if event == "ctypes.dlopen":
                    path = args[0] if args else ""
                    if path and path != "0":
                        self.dlopen_targets.append(str(path))
                        self._record_violation(event, args)
                    return
                if event == "open" and args:
                    path = args[0]
                    if isinstance(path, (str, bytes)):
                        p = path.decode("utf-8", "replace") \
                            if isinstance(path, bytes) else path
                        if not any(p.startswith(q)
                                   for q in _TOPLEVEL_OPEN_PREFIXES):
                            self._record_violation(event, args)
                return
            if event in self.EXEC_EVENTS:
                if self.phase == "build":
                    self.exec_attempts += 1
                return
            if event in self.CHILD_EVENTS:
                if self.phase == "build":
                    self.child_process_attempts += 1
                return
            idx = self.PATH_EVENTS.get(event)
            if idx is None or len(args) <= idx:
                return
            path = args[idx]
            if not isinstance(path, (str, bytes, int)):
                return
            if event == "subprocess.Popen":
                argv0 = path if isinstance(path, (str, bytes)) else ""
                if isinstance(argv0, bytes):
                    argv0 = argv0.decode("utf-8", "replace")
                if argv0 and "/" not in argv0:
                    return
                path = argv0
            path = str(path)
            if event == "ctypes.dlopen":
                if path and path != "0" and self.phase == "build":
                    if path not in self.dlopen_targets:
                        self.dlopen_targets.append(path)
                return
            self.open_events.append(path)
            if self.phase != "build":
                return
            if not any(path.startswith(p) for p in self._prefixes):
                if len(self.outside) < 64:
                    self.outside.append(path)
        except Exception:  # noqa: BLE001 - 审计绝不影响执行
            pass

    def summary(self) -> dict:
        reachable = [p for p in self.outside if os.path.exists(p)]
        return {
            "format": ACCESS_SUMMARY_FORMAT_V2,
            "open_count": len(self.open_events),
            "outside_allowlist": reachable,
            "covered_events": sorted(
                set(self.PATH_EVENTS) | set(self.CHILD_EVENTS)
                | set(self.EXEC_EVENTS) | set(_COMPUTE_FORBIDDEN_EVENTS)),
            "child_process_attempts": self.child_process_attempts,
            "exec_attempts": self.exec_attempts,
            "dlopen_targets": sorted(self.dlopen_targets),
            "phase_violations": list(self.phase_violations),
        }


# ------------------------------------------------------------ 入口验证
def _validate_entrypoint_signature(fn) -> list[str]:
    """build 入口必须是精确的 ``build_pack(request)``。"""
    problems: list[str] = []
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        return [f"签名无法解析: {exc}"]
    params = list(sig.parameters.values())
    if len(params) != 1:
        problems.append(
            f"入口必须恰好接受一个 request 参数(收到 {len(params)} 个)")
    for p in params:
        if p.kind == inspect.Parameter.VAR_POSITIONAL:
            problems.append(f"入口不接受 *args(参数 {p.name!r})")
        elif p.kind == inspect.Parameter.VAR_KEYWORD:
            problems.append(f"入口不接受 **kwargs(参数 {p.name!r})")
        elif p.kind == inspect.Parameter.KEYWORD_ONLY:
            problems.append(f"入口不接受 keyword-only 参数(参数 {p.name!r})")
        elif p.default is not inspect.Parameter.empty:
            problems.append(f"入口参数 {p.name!r} 不得有默认值(可选参数被拒绝)")
        if p.name in FORBIDDEN_PARAM_NAMES:
            problems.append(f"入口参数名 {p.name!r} 是候选相关禁止参数")
    return problems


def check_attempt_log_v2(log, *, attempt_policy: dict) -> None:
    """first_pass attempt log 硬约束(结构 + 选择规则;沿 0h)。"""
    if not isinstance(log, dict):
        raise _RunnerFailure(
            f"attempt_log 必须是规范化 dict(收到 {type(log).__name__})")
    if log.get("format") != ATTEMPT_LOG_FORMAT_V2:
        raise _RunnerFailure(
            f"attempt_log.format 必须是 {ATTEMPT_LOG_FORMAT_V2!r}(收到 "
            f"{log.get('format')!r})")
    policy = str((attempt_policy or {}).get("policy") or "")
    ma = log.get("max_attempts")
    if not isinstance(ma, int) or isinstance(ma, bool) or ma < 0:
        raise _RunnerFailure("attempt_log.max_attempts 必须是非负 int")
    req_ma = int((attempt_policy or {}).get("max_attempts") or 0)
    if ma != req_ma:
        raise _RunnerFailure(
            f"attempt_log.max_attempts={ma} 与请求 attempt_policy."
            f"max_attempts={req_ma} 不一致")
    attempts = log.get("attempts")
    if not isinstance(attempts, list):
        raise _RunnerFailure("attempt_log.attempts 必须是 list")
    for entry in attempts:
        if not isinstance(entry, dict) or set(entry) != ATTEMPT_ENTRY_FIELDS:
            raise _RunnerFailure(
                "attempt_log 条目字段必须恰好是 "
                f"{sorted(ATTEMPT_ENTRY_FIELDS)}")
        if not isinstance(entry.get("attempt"), int) \
                or isinstance(entry.get("attempt"), bool):
            raise _RunnerFailure("attempt 条目的 attempt 必须是 int")
        if entry.get("verdict") not in ("accept", "reject"):
            raise _RunnerFailure(
                f"attempt 条目的 verdict 必须是 accept|reject(收到 "
                f"{entry.get('verdict')!r})")
        reasons = entry.get("reject_reasons")
        if not isinstance(reasons, list) or \
                not all(isinstance(r, str) for r in reasons):
            raise _RunnerFailure(
                "attempt 条目的 reject_reasons 必须是字符串列表")
    sel = log.get("selected_attempt")
    if sel is not None and (not isinstance(sel, int)
                            or isinstance(sel, bool)):
        raise _RunnerFailure("attempt_log.selected_attempt 必须是 int 或 null")
    if policy == "assembly":
        if ma != 0 or attempts or sel is not None:
            raise _RunnerFailure(
                "assembly(组装)模式 attempt log 必须为空(max_attempts=0,"
                "无条目,无选中)")
        return
    if policy != "first_pass":
        raise _RunnerFailure(
            f"未知的 attempt 选择策略 {policy!r}(只支持 first_pass)")
    numbers = [e.get("attempt") for e in attempts]
    if numbers != list(range(len(attempts))):
        raise _RunnerFailure(
            "first_pass 违规:attempt 编号必须从 0 开始且严格连续唯一"
            f"(收到 {numbers})")
    if attempts and ma and len(attempts) > ma:
        raise _RunnerFailure(
            f"first_pass 违规:条目数 {len(attempts)} 超出 max_attempts"
            f"={ma}")
    accepts = [i for i, e in enumerate(attempts)
               if e.get("verdict") == "accept"]
    if sel is None:
        if accepts:
            raise _RunnerFailure(
                "first_pass 违规:存在 accept 条目但未选中(没有 accept 的"
                "构建必须失败,不得产出 pack)")
        if attempts and attempts[-1].get("verdict") == "reject" \
                and len(attempts) == ma:
            return
        return
    if len(accepts) != 1:
        raise _RunnerFailure(
            f"first_pass 违规:必须恰好一个 accept(收到 {len(accepts)} 个)")
    if accepts[0] != sel:
        raise _RunnerFailure(
            "first_pass 违规:selected_attempt 必须指向唯一的 accept 条目")
    first_accept = accepts[0]
    for e in attempts[:first_accept]:
        if e.get("verdict") != "reject":
            raise _RunnerFailure(
                "first_pass 违规:选中条目之前必须全部是 reject")
    if len(attempts) != first_accept + 1:
        raise _RunnerFailure(
            "first_pass 违规:选中条目之后不得再有其他条目")


def _validate_build_result(raw, *, attempt_policy: dict) -> dict:
    """result v3 精确字段 + attempt log 联动(沿 0h)。"""
    if raw is None:
        raise _RunnerFailure("build 入口返回 None(必须返回规范化 result)")
    if not isinstance(raw, dict):
        raise _RunnerFailure(
            f"build 入口返回类型 {type(raw).__name__} 不是 dict")
    unknown = sorted(set(raw) - RESULT_FIELDS)
    if unknown:
        raise _RunnerFailure(f"build 结果含未知字段 {unknown}")
    missing = sorted(RESULT_FIELDS - set(raw) - {"error"})
    if missing:
        raise _RunnerFailure(f"build 结果缺少字段 {missing}")
    if raw.get("format") != BUILD_RESULT_FORMAT_V3:
        raise _RunnerFailure(
            f"build 结果 format 必须是 {BUILD_RESULT_FORMAT_V3!r}(收到 "
            f"{raw.get('format')!r})")
    if raw.get("runner_protocol") != RUNNER_PROTOCOL_V3:
        raise _RunnerFailure(
            f"build 结果 runner 协议必须是 {RUNNER_PROTOCOL_V3!r}(收到 "
            f"{raw.get('runner_protocol')!r})")
    log = raw.get("attempt_log")
    check_attempt_log_v2(log, attempt_policy=attempt_policy)
    sel = (log or {}).get("selected_attempt")
    if raw.get("status") != "ok":
        if sel is not None:
            raise _RunnerFailure(
                "构建失败(status!=ok)时 attempt log 不得有选中条目")
        if raw.get("error") in (None, ""):
            raise _RunnerFailure("status!=ok 但 error 为空(不自洽)")
        raise _RunnerFailure(
            f"build 自报失败 status={raw.get('status')!r}: "
            f"{str(raw.get('error'))[:200]}")
    if raw.get("error") not in (None, ""):
        raise _RunnerFailure("status=ok 但 error 非空(不自洽)")
    if sel is None and str(
            (attempt_policy or {}).get("policy") or "") != "assembly":
        raise _RunnerFailure(
            "构建成功(status=ok)必须有选中的 accept 条目"
            "(first_pass:没有 accept 的构建必须失败,不得产出 pack;"
            "组装通道 assembly 除外)")
    if not isinstance(raw.get("pack"), dict):
        raise _RunnerFailure(
            "build 结果的 pack 必须是规范化 pack JSON dict"
            "(ExamPack 规范由主进程解析)")
    return raw


# ---------------------------------------------------- 导入闭包(A2)
#: 允许的 loader 类型(动态/自定义 loader fail closed;bundled zip 允许)
_ALLOWED_LOADERS = frozenset({
    "SourceFileLoader", "ExtensionFileLoader", "SourcelessFileLoader",
    "zipimporter", "BuiltinImporter", "FrozenImporter",
})


class _ClosureError(Exception):
    pass


def _loader_name(mod, spec) -> str:
    """loader 类型名(frozen importer 的 spec.loader 是类本身)。"""
    obj = getattr(spec, "loader", None) if spec is not None else None
    if obj is None:
        obj = getattr(mod, "__loader__", None)
    if obj is None:
        return ""
    if isinstance(obj, type):
        return obj.__name__
    return type(obj).__name__


def _module_entry(name: str, mod, *, manifest_files: dict,
                  manifest_dirs: set, owners: dict,
                  ambiguous_paths: set, stdlib_names: frozenset,
                  root: str = "/") -> dict:
    """单个导入模块的 bundle 绑定与归属(A2;违规抛 _ClosureError)。

    root:manifest 相对路径的解析基(生产为 "/";单元测试可指向
    staging 目录)。
    """
    spec = getattr(mod, "__spec__", None)
    loader_name = _loader_name(mod, spec)
    origin = str(getattr(spec, "origin", "") or "") if spec else ""
    file = str(getattr(mod, "__file__", "") or "")
    top = name.split(".")[0]
    entry: dict = {"module": name, "loader": loader_name,
                   "origin_kind": "", "file": None, "sha256": None,
                   "owner": "", "distribution": None}
    if loader_name and loader_name not in _ALLOWED_LOADERS:
        raise _ClosureError(
            f"模块 {name!r} 使用未允许的 loader {loader_name!r}"
            f"(自定义导入路径 fail closed)")
    if loader_name in ("BuiltinImporter", "FrozenImporter") and not file:
        entry["origin_kind"] = "builtin-frozen"
        entry["owner"] = "python-stdlib"
        return entry
    if file.endswith(".zip") or loader_name == "zipimporter":
        # bundled zip:zip 文件本身必须进 manifest
        root_prefix = str(root).rstrip("/") + "/"
        rel = file[len(root_prefix):] if file.startswith(root_prefix)             else (file[1:] if file.startswith("/") else file)
        if rel not in manifest_files:
            raise _ClosureError(
                f"模块 {name!r} 经 zipimport 加载 bundle 外归档"
                f"(fail closed)")
        entry["origin_kind"] = "zip-bundled"
        entry["file"] = file
        entry["sha256"] = manifest_files[rel]
        entry["owner"] = "bundle-zip"
        return entry
    if not file:
        # namespace package:所有 search locations 必须是 manifest 目录
        locations = list(getattr(spec, "submodule_search_locations", ())
                         or ()) if spec else []
        if not locations:
            if spec is None and loader_name == "":
                # 纯合成运行时模块(Cython 运行时注入 sys.modules 的
                # 无文件命名空间):无代码文件即无 bundle 外输入;记入
                # 闭包保持透明。文件/加载器逃逸仍全部拒绝。
                entry["origin_kind"] = "synthetic-runtime-module"
                entry["owner"] = "runtime-synthetic"
                return entry
            raise _ClosureError(
                f"模块 {name!r} 无源文件且非 namespace package(动态生成"
                f"模块 fail closed)")
        root_prefix = str(root).rstrip("/") + "/"
        for loc in locations:
            locs = str(loc)
            rel = locs[len(root_prefix):] if locs.startswith(root_prefix)                 else (locs[1:] if locs.startswith("/") else locs)
            if rel not in manifest_dirs:
                raise _ClosureError(
                    f"namespace package {name!r} 的 search location "
                    f"{loc!r} 不在 bundle manifest 内(fail closed)")
        entry["origin_kind"] = "namespace-package"
        entry["owner"] = "namespace-dir"
        return entry
    root_prefix = str(root).rstrip("/") + "/"
    rel = file[len(root_prefix):] if file.startswith(root_prefix) else \
        (file[1:] if file.startswith("/") else file)
    sha = manifest_files.get(rel)
    if sha is None:
        raise _ClosureError(
            f"模块 {name!r} 的文件不在 bundle manifest 内"
            f"(bundle 外代码 fail closed;路径已脱敏)")
    h = hashlib.sha256()
    with open(file, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != sha:
        raise _ClosureError(
            f"模块 {name!r} 的文件字节与 bundle manifest 不一致"
            f"(TOCTOU/篡改;fail closed)")
    entry["file"] = file
    entry["sha256"] = sha
    entry["origin_kind"] = "file"
    if file.startswith(BUILDER_PKG_MOUNT):
        entry["owner"] = "builder_package"
    elif file.startswith(RUNTIME_MOUNT):
        entry["owner"] = "rl_builder_runtime"
    elif rel.startswith("lib/python3.11/site-packages/"):
        if rel in ambiguous_paths:
            raise _ClosureError(
                f"模块 {name!r} 的文件被多个 distribution 声明"
                f"(多义归属 fail closed)")
        dists = owners.get(rel) or []
        if len(dists) == 1:
            entry["owner"] = "distribution"
            entry["distribution"] = dists[0]
        else:
            entry["owner"] = "site-packages-unrecorded"
    elif top in stdlib_names:
        entry["owner"] = "python-stdlib"
    else:
        entry["owner"] = "bundle-unrecorded"
    return entry


def _import_closure(baseline: frozenset,
                    root: str = "/") -> tuple[list[dict], list[dict]]:
    """A2:实际导入(sys.modules 差集)逐模块绑定 + top-level 归属。"""
    try:
        manifest = json.loads(
            Path(BUNDLE_MANIFEST_PATH).read_text(encoding="utf-8"))
        meta = json.loads(Path(BUNDLE_META_PATH).read_text(
            encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _ClosureError(f"bundle manifest/meta 不可读: {exc}")
    manifest_files = {e["path"]: e["sha256"] for e in manifest["entries"]
                      if e.get("type") == "file"}
    manifest_dirs = {e["path"] for e in manifest["entries"]
                     if e.get("type") == "dir"}
    owners = dict(meta.get("dist_ownership") or {})
    ambiguous = {a["path"] for a in (meta.get("ambiguous_dist_paths")
                                     or []) if "path" in a}
    stdlib_names = frozenset(getattr(sys, "stdlib_module_names", ()))
    entries: list[dict] = []
    for name in sorted(set(sys.modules) - baseline):
        mod = sys.modules.get(name)
        if mod is None:
            continue
        entries.append(_module_entry(
            name, mod, manifest_files=manifest_files,
            manifest_dirs=manifest_dirs, owners=owners,
            ambiguous_paths=ambiguous, stdlib_names=stdlib_names,
            root=root))
    # top-level 归属聚合(静态 external_dependencies 对账用)
    import importlib.metadata as md

    top_entries: dict[str, dict] = {}
    for e in entries:
        top = e["module"].split(".")[0]
        cur = top_entries.get(top)
        if cur is None:
            top_entries[top] = e
        elif e["distribution"] and not cur["distribution"]:
            top_entries[top] = e
    distributions: list[dict] = []
    for top in sorted(top_entries):
        e = top_entries[top]
        if top in stdlib_names or e["owner"] in (
                "python-stdlib", "rl_builder_runtime",
                "runtime-synthetic"):
            continue
        if e["owner"] == "builder_package":
            continue  # npb- 由主进程对账
        dist = e["distribution"]
        if not dist:
            raise _ClosureError(
                f"实际加载的第三方模块 {top!r} 无法归属到任何 "
                f"distribution(未声明依赖 fail closed;owner="
                f"{e['owner']!r})")
        try:
            version = str(md.distribution(dist).version)
        except Exception as exc:  # noqa: BLE001
            raise _ClosureError(
                f"distribution {dist!r} 元数据不可读: {exc}")
        distributions.append({
            "module": top, "distribution": dist, "version": version,
            "imported": sorted(m["module"] for m in entries
                               if m["module"].split(".")[0] == top),
            "file": e["file"], "sha256": e["sha256"],
        })
    return entries, distributions


# ---------------------------------------------------- EDIC worker 部分(D2)
def _stat_probe(path: str) -> str:
    try:
        os.stat(path)
        return "EXISTS"
    except FileNotFoundError:
        return "ENOENT"
    except OSError as exc:
        return f"ERR{exc.errno}"


def build_edic_worker_part(*, seccomp_state: dict, vdso_state: dict,
                           tsc_rc: int, process_tree_policy: str,
                           scratch_initial: list[str]) -> dict:
    """Effective Deterministic Input Report 的 worker 实测部分。

    只含确定性字段(ASLR 基址等易变值不进入);Supervisor 合并外部
    /proc 实测(seccomp 模式、线程静止、native 绑定、bundle 复验)。
    """
    import socket

    if os.getpid() != 1:
        raise _RunnerFailure(
            f"Worker 在 pidns 内必须是 pid 1(实际 {os.getpid()})")
    hostname = socket.gethostname()
    if hostname != BUILDER_WORKER_HOSTNAME:
        raise _RunnerFailure(
            f"UTS hostname 未固定(期望 {BUILDER_WORKER_HOSTNAME!r},"
            f"实际 {hostname!r})")
    try:
        interfaces = sorted(n for _, n in socket.if_nameindex())
    except OSError as exc:
        raise _RunnerFailure(f"网络接口枚举失败: {exc}")
    if interfaces != ["lo"]:
        raise _RunnerFailure(
            f"网络 namespace 接口异常: {interfaces}(必须只有 lo)")
    # 熵源实测
    with open("/dev/urandom", "rb") as fh:
        entropy_probe = fh.read(32)
    entropy_sha = hashlib.sha256(entropy_probe).hexdigest()
    urandom_st = os.stat("/dev/urandom")
    entropy_regular = not (urandom_st.st_mode & 0o170000 == 0o020000)
    getrandom_probe = _raw_syscall_probe(_SYS_GETRANDOM, 0, 0)
    # 时钟 raw syscall 实测 + 冻结行为探针(vDSO stub 生效证明)
    clock_probes = {
        "clock_gettime": _raw_syscall_probe(_SYS_CLOCK_GETTIME, 0, 0),
        "time": _raw_syscall_probe(_SYS_TIME, 0),
        "gettimeofday": _raw_syscall_probe(_SYS_GETTIMEOFDAY, 0, 0, 0),
        "clock_gettime64": _raw_syscall_probe(_SYS_CLOCK_GETTIME64, 0, 0),
    }
    import datetime as _dt
    import time as _time
    clock_behavior = {
        "time_time": _time.time(),
        "time_monotonic": _time.monotonic(),
        "time_perf_counter": _time.perf_counter(),
        "datetime_now_year": _dt.datetime.now().year,
        "datetime_utcnow_year": _dt.datetime.utcnow().year,
    }
    # 进程树行为探针(report 阶段)
    probes: dict[str, dict] = {}
    try:
        pid = os.fork()
    except OSError as exc:
        probes["fork_denied"] = {"result": f"ERRNO{exc.errno}"}
    else:  # 未装 seccomp(allow_descendants 演示)才会走到这里
        if pid == 0:
            os._exit(0)  # pragma: no cover
        os.waitpid(pid, 0)
        probes["fork_denied"] = {"result": "LEAKED"}
    if seccomp_state.get("installed"):
        try:
            os.execv("/bin/python3.11", ["/bin/python3.11", "-c", ""])
            probes["exec_denied"] = {"result": "LEAKED"}
        except OSError as exc:
            probes["exec_denied"] = {"result": f"ERRNO{exc.errno}"}
    else:
        probes["exec_denied"] = {"result": "SKIPPED-NO-SECCOMP"}
    probes["clone_thread_denied"] = {
        "result": _raw_syscall_probe(_SYS_CLONE, 0)
        if seccomp_state.get("installed") else "SKIPPED-NO-SECCOMP"}
    probes["host_usr"] = {"result": _stat_probe("/usr")}
    probes["host_home"] = {"result": _stat_probe("/home")}
    probes["host_etc_hostname"] = {
        "result": _stat_probe("/etc/hostname")}
    probes["host_sys"] = {"result": _stat_probe("/sys")}
    probes["host_oldroot_usr"] = {"result": _stat_probe("/oldroot/usr")}
    probes["proc_self_status"] = {"result": _stat_probe(
        "/proc/self/status")}
    probes["proc_listing_empty"] = {"result": os.listdir("/proc") == []}
    return {
        "format": EDIC_FORMAT,
        "pidns_self_pid": 1,
        "uts_hostname": hostname,
        "netns_interfaces": interfaces,
        "root_readonly": not os.access("/", os.W_OK),
        "scratch_initial_listing": sorted(scratch_initial),
        "proc": {"mounted": False,
                 "self_status": probes["proc_self_status"]["result"],
                 "listing_empty": probes["proc_listing_empty"]["result"]},
        "dev": {
            "nodes": sorted(os.listdir("/dev")),
            "urandom_regular_file": entropy_regular,
            "deterministic_entropy_sha256_prefix": entropy_sha[:16],
        },
        "clock": {
            "vdso": vdso_state,
            "pr_set_tsc_rc": int(tsc_rc),
            "raw_syscall": clock_probes,
            "behavior": clock_behavior,
        },
        "entropy": {
            "getrandom": getrandom_probe,
            "dev_urandom_deterministic": entropy_regular,
        },
        "seccomp": {
            "installed": bool(seccomp_state.get("installed")),
            "filter_hash": seccomp_state.get("filter_hash"),
            "policy": SECCOMP_PROCESS_POLICY,
        },
        "thread_policy": THREAD_POLICY_FORBIDDEN
        if process_tree_policy == SINGLE_PROCESS else THREAD_POLICY_DEMO,
        "process_tree_policy": process_tree_policy,
        "environment": {
            "environ": {k: os.environ[k] for k in sorted(os.environ)},
            "uname_release": os.uname().release,
            "uname_machine": os.uname().machine,
            "cpu_count": os.cpu_count(),
            "affinity_count": len(os.sched_getaffinity(0)),
            "cwd": os.getcwd(),
        },
        "probes": probes,
    }


def edic_worker_hash(edic: dict) -> str:
    return "edi-" + hashlib.sha256(json.dumps(
        edic, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


# ------------------------------------------------------------ 主流程
class _RunnerFailure(Exception):
    """Runner 侧 fail closed 异常(消息必须可脱敏回传)。"""


def _emit(payload: dict, *, fd: int | None = None) -> None:
    """单行 JSON 输出;fd=None 走 sys.stdout(Prepare 期),否则经
    RESULT_FD 单向通道(Seal 后唯一受信输出路径)。"""
    line = json.dumps(payload, ensure_ascii=False,
                      separators=(",", ":"))
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        if fd is None:
            sys.stdout.write(json.dumps({
                "protocol": BUILDER_WORKER_PROTOCOL,
                "status": "failed", "phase": "final",
                "build_result": None, "edic": None,
                "access_summary": None,
                "error": "builder-runner-response-limit",
                "stage": "response-limit",
            }) + "\n")
            sys.stdout.flush()
            os._exit(7)
        os.write(fd, json.dumps({
            "protocol": BUILDER_WORKER_PROTOCOL,
            "status": "failed", "phase": "final",
            "build_result": None, "edic": None,
            "access_summary": None,
            "error": "builder-runner-response-limit",
            "stage": "response-limit",
        }).encode("utf-8") + b"\n")
        os._exit(7)
    data = (line + "\n").encode("utf-8")
    if fd is None:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    else:
        # 分块写(避免单次 write 超过 pipe 缓冲后部分写;write 在
        # final filter 下对 RESULT_FD 允许)
        off = 0
        while off < len(data):
            off += os.write(fd, data[off:off + 65536])


def _fail(error: str, stage: str, *, access_summary=None,
          edic=None, fd: int | None = None) -> None:
    _emit({
        "protocol": BUILDER_WORKER_PROTOCOL,
        "status": "failed", "phase": "final",
        "build_result": None,
        "edic": edic,
        "access_summary": access_summary,
        "error": str(error)[:500],
        "stage": str(stage),
    }, fd=fd)
    os._exit(2)


def _validate_builder_package_purity(staging_root: str, *,
                                     formal: bool = True) -> dict:
    """A1:builder 包内全部 .py 模块的顶层纯度 AST 验证。"""
    from rl_builder_runtime.sealed_compute import (
        validate_top_level_purity,
    )

    root = Path(staging_root)
    pkg_modules = tuple(sorted(
        str(p.relative_to(root).with_suffix("")).replace(
            "/", ".") for p in root.rglob("*.py")))
    reports = []
    for src in sorted(root.rglob("*.py")):
        rel = str(src.relative_to(root))
        try:
            source = src.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise _RunnerFailure(
                f"builder 包源码不可读: {rel}(脱敏;{type(exc).__name__})")
        reports.append(validate_top_level_purity(
            source, rel, allow_prefixes=pkg_modules, formal=formal))
    if not reports:
        raise _RunnerFailure("builder 包不含任何 .py 模块(拒绝)")
    bad = [r["module"] for r in reports if not r["ok"]]
    if bad:
        sample = "; ".join(
            f"{r['module']}: {r['problems'][:2]}" for r in reports
            if not r["ok"])[:400]
        raise _RunnerFailure(
            f"builder 模块顶层纯度验证失败({len(bad)} 个模块):{sample}")
    return {"ok": True, "modules": len(reports),
            "reports": reports}


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        _fail(
            "usage: /bin/python3.11 -m rl_builder_runtime.runner "
            "<builder_pkg> <module> <qualname>", "usage")
        return 2  # unreachable(os._exit)
    staging_root = str(Path(argv[1]).resolve())
    entrypoint_module = str(argv[2])
    entrypoint_qualname = str(argv[3])
    if not entrypoint_module or not entrypoint_qualname:
        _fail("entrypoint module/qualname 为空", "usage")
    scratch_initial = os.listdir("/scratch")
    line = sys.stdin.readline()
    if not line.strip():
        _fail("未收到冻结构建请求(stdin 为空)", "request")
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        _fail("请求超过字节上限", "request-limit")
    try:
        request = json.loads(line)
    except json.JSONDecodeError:
        _fail("请求不是合法 JSON", "request")
    if not isinstance(request, dict):
        _fail("请求必须是 JSON 对象", "request")
    attempt_policy = dict(request.get("attempt_policy") or {})
    process_tree_policy = os.environ.get(
        "RL_BUILDER_PROCESS_TREE", SINGLE_PROCESS)
    if process_tree_policy not in (SINGLE_PROCESS, ALLOW_DESCENDANTS):
        _fail(f"未知进程树策略 {process_tree_policy!r}", "policy")
    dep_profile = os.environ.get("RL_BUILDER_DEP_PROFILE", DEP_PROFILE_FORMAL)
    if dep_profile not in (DEP_PROFILE_FORMAL, DEP_PROFILE_COMPAT):
        _fail(f"未知依赖策略 {dep_profile!r}", "policy")
    formal = dep_profile == DEP_PROFILE_FORMAL

    from rl_builder_runtime.sealed_compute import (
        FINAL_COMPUTE_POLICY,
        RESULT_ACK_FD,
        RESULT_FD,
        apply_mdwe,
        dependency_policy,
        final_filter_digest,
        install_final_compute_filter,
        preload_formal_modules,
        purity_report_digest,
        seal_worker_fds,
    )

    recorder = _AccessRecorder(["/"])
    baseline = frozenset(sys.modules)
    sys.addaudithook(recorder.hook)
    edic = None
    result = None
    sandbox_probes_bad: list[str] = []
    sealed = False
    seal_state: dict = {}
    try:
        # ================= Prepare(可信初始化) =================
        # C1/C2:v2 filter(arch 校验 + x32 拒绝 + 进程/时钟/熵全拒)
        if process_tree_policy == SINGLE_PROCESS:
            try:
                seccomp_state = install_seccomp_filter()
            except OSError as exc:
                _fail(f"seccomp 安装失败: {exc}", "seccomp")
        else:  # allow_descendants 仅供攻击演示测试;evidence 层拒绝
            seccomp_state = {"installed": False,
                             "filter_hash": seccomp_filter_digest(),
                             "no_new_privs": 1}
        # B1:vDSO 冻结虚拟化 + TSC SIGSEGV
        if process_tree_policy == SINGLE_PROCESS:
            vdso_state = virtualize_vdso_clock()
            tsc_rc = disable_tsc()
        else:
            vdso_state = {"vdso": "demo-mode-not-virtualized",
                          "mode": "demo", "frozen_epoch": None,
                          "stubs": {}, "original_vdso_sha256": ""}
            tsc_rc = -1
        # A3:依赖策略与 native 预加载(Seal 前完成全部 dlopen;
        # Compute 内零动态加载)
        dep_policy = dependency_policy(formal=formal)
        if process_tree_policy == SINGLE_PROCESS:
            import ctypes  # noqa: F401 - 确保 Seal 后零文件访问

            preloaded = preload_formal_modules()
        else:
            import ctypes  # noqa: F401

            preloaded = []
        # D2:sealed compute report v2 的 worker 实测部分(report
        # 阶段探针不计入审计)
        recorder.phase = "report"
        edic = build_edic_worker_part(
            seccomp_state=seccomp_state, vdso_state=vdso_state,
            tsc_rc=tsc_rc, process_tree_policy=process_tree_policy,
            scratch_initial=scratch_initial)
        if process_tree_policy == SINGLE_PROCESS:
            if edic["probes"]["fork_denied"]["result"] != \
                    f"ERRNO{errno.EPERM}":
                sandbox_probes_bad.append("fork")
            if edic["probes"]["exec_denied"]["result"] != \
                    f"ERRNO{errno.EPERM}":
                sandbox_probes_bad.append("exec")
            if edic["probes"]["clone_thread_denied"]["result"] != \
                    f"ERRNO{errno.EPERM}":
                sandbox_probes_bad.append("clone")
            for probe in ("host_usr", "host_home", "host_etc_hostname",
                          "host_sys", "host_oldroot_usr"):
                if edic["probes"][probe]["result"] != "ENOENT":
                    sandbox_probes_bad.append(probe)
            if not edic["proc"]["self_status"] == "ENOENT":
                sandbox_probes_bad.append("proc-visible")
            if not edic["root_readonly"]:
                sandbox_probes_bad.append("root-writable")
            if not edic["dev"]["urandom_regular_file"]:
                sandbox_probes_bad.append("dev-urandom-device")
            if edic["clock"]["vdso"].get("mode") != "frozen-stub" \
                    and edic["clock"]["vdso"].get("vdso") != \
                    "absent-at-exec":
                sandbox_probes_bad.append("vdso-not-frozen")
            if edic["clock"]["behavior"]["time_time"] != \
                    float(FROZEN_EPOCH_SECONDS) \
                    or edic["clock"]["behavior"]["datetime_now_year"] != 1970:
                sandbox_probes_bad.append("clock-not-frozen")
            if edic["clock"]["raw_syscall"]["clock_gettime"] != \
                    f"ERRNO{errno.EPERM}":
                sandbox_probes_bad.append("clock-syscall")
            if edic["entropy"]["getrandom"] != f"ERRNO{errno.EPERM}":
                sandbox_probes_bad.append("getrandom")
        if sandbox_probes_bad:
            _fail(
                "沙箱密闭探针未通过:" + ",".join(sorted(
                    set(sandbox_probes_bad))),
                "sandbox", edic=edic)
        mounts_digest = os.environ.get("RL_SB_MOUNTOPTS", "")
        if not mounts_digest:
            _fail("RL_SB_MOUNTOPTS 缺失(bootstrap 摘要未定型)", "sandbox",
                  edic=edic)
        edic["mounts_digest"] = mounts_digest

        # A1:builder 包顶层纯度 AST 验证(import 前)
        purity = _validate_builder_package_purity(
            staging_root, formal=formal)
        # 受控 import(toplevel 阶段:模块顶层执行受审计监督)
        recorder.phase = "toplevel"
        cached = sys.modules.get(entrypoint_module)
        if cached is not None:
            cached_file = str(getattr(cached, "__file__", "") or "")
            if cached_file and not cached_file.startswith(staging_root):
                sys.modules.pop(entrypoint_module, None)
        sys.path.insert(0, staging_root)
        mod = importlib.import_module(entrypoint_module)
        obj: object = mod
        for part in entrypoint_qualname.split("."):
            if not hasattr(obj, part):
                raise _RunnerFailure(
                    f"qualname {entrypoint_qualname!r} 在 import 后不存在"
                    f"(属性 {part!r} 缺失)")
            obj = getattr(obj, part)
        if not callable(obj):
            raise _RunnerFailure(
                f"入口 {entrypoint_qualname!r} 不是 callable")
        if isinstance(obj, type):
            raise _RunnerFailure(
                f"入口 {entrypoint_qualname!r} 是类构造器,被拒绝")
        if not isinstance(obj, (types.FunctionType, types.MethodType,
                                types.BuiltinFunctionType)):
            raise _RunnerFailure(
                f"入口运行时类型 {type(obj).__name__!r} 不在允许范围")
        problems = _validate_entrypoint_signature(obj)
        if problems:
            raise _RunnerFailure(
                "build 入口签名违规: " + "; ".join(problems))
        if recorder.phase_violations:
            raise _RunnerFailure(
                "builder 模块顶层违规(外部状态/native 通道访问):"
                + "; ".join(recorder.phase_violations[:8]))
        # A2:导入闭包 + 逐文件哈希(**build 前完成**;Compute 零文件
        # 访问的前提)
        recorder.phase = "closure"
        closure_entries, distributions = _import_closure(baseline)
        if process_tree_policy == SINGLE_PROCESS and (
                recorder.child_process_attempts > 0
                or recorder.exec_attempts > 0):
            _fail(
                f"进程树违规:attempts={recorder.child_process_attempts},"
                f"exec={recorder.exec_attempts}(single_builder_process "
                f"被违反)", "process-tree",
                access_summary=recorder.summary(), edic=edic)

        # sealed compute report v2:Prepare 承诺(Seal 参数定型)
        edic["sealed_compute"] = {
            "phase_plan": "prepare->seal->compute",
            "dependency_policy": dep_policy,
            "top_level_purity": {
                "module_count": purity["modules"],
                "all_ok": purity["ok"],
                "digest": purity_report_digest(purity["reports"]),
                "profile": "formal" if formal else "compat",
            },
            "preloaded_modules": sorted(preloaded),
            "final_seccomp": {
                "policy": FINAL_COMPUTE_POLICY,
                "filter_digest": final_filter_digest(),
                "default_action": "EPERM",
                "arg_limits": ["write.fd-in(1,2,RESULT_FD)",
                               "mmap/mprotect.no-prot-exec",
                               "rt_sigaction.signal-not-in("
                               "SIGILL,SIGBUS,SIGFPE,SIGSEGV,SIGSYS)"],
            },
            "compute_forbidden_events": list(_COMPUTE_FORBIDDEN_EVENTS),
            "result_fd": RESULT_FD,
            "tsc": {"pr_set_tsc_rc": int(tsc_rc),
                    "prctl_denied_in_compute": "final-filter-eperm"},
        }
        # quiesce 握手:请求 Supervisor 外部实测(/proc maps/task/status)
        recorder.phase = "quiesce"
        _emit({
            "protocol": BUILDER_WORKER_PROTOCOL,
            "status": "ok", "phase": "quiesce",
            "edic": edic,
            "lock_parts": {
                "format": RUNTIME_LOCK_FORMAT_V4,
                "python_implementation": sys.implementation.name,
                "python_version": sys.version.split()[0],
                "executable_prefix": str(getattr(sys, "prefix", "") or "/"),
                "process_tree_policy": process_tree_policy,
                "thread_policy": edic["thread_policy"],
                "dependency_profile": dep_profile,
                "child_process_attempts": int(recorder.child_process_attempts),
                "exec_attempts": int(recorder.exec_attempts),
                "import_closure": closure_entries,
                "distributions": distributions,
                "dlopen_targets": sorted(recorder.dlopen_targets),
                "bundle_manifest_digest": _bundle_digest_from_file(),
                "environment_identity": edic["environment"],
                "final_seccomp_filter_digest": final_filter_digest(),
            },
            "access_summary": recorder.summary(),
            "error": None,
        })
        ack = sys.stdin.readline()
        if ack.strip() != "ACK":
            os._exit(4)  # Supervisor 未确认静止状态:拒绝采信输出

        # ================= Seal(不可逆安全边界) =================
        recorder.phase = "seal"
        mdwe_state = apply_mdwe()
        fd_state = seal_worker_fds()
        if process_tree_policy == SINGLE_PROCESS:
            final_state = install_final_compute_filter()
        else:
            final_state = {"installed": False,
                           "filter_hash": final_filter_digest(),
                           "default_action": "EPERM",
                           "demo_mode": True}
        sealed = True
        seal_state = {
            "mdwe": mdwe_state,
            "fd_isolation": fd_state,
            "final_filter": final_state,
            "sealed": True,
        }

        # ================= Compute(build_pack 纯计算) =================
        recorder.phase = "compute"
        # 缓存命中的 import 语句不触发 audit "import" 事件(CPython
        # 实测);补 builtins.__import__ 检测层,使零 import 合同在
        # 语义层完整(机制层已由 final filter 拒绝任何新加载——缓存
        # 命中只是取已承诺模块引用,无新代码执行;检测是完整性而非
        # 唯一防线,不构成"只靠 monkeypatch"降级)
        import builtins as _builtins

        _orig_import = _builtins.__import__

        def _guarded_import(name, *args, **kwargs):
            recorder._record_violation("import", (name,))
            return _orig_import(name, *args, **kwargs)

        _builtins.__import__ = _guarded_import
        raw = obj(dict(request))
        result = _validate_build_result(
            raw, attempt_policy=attempt_policy)
        if process_tree_policy == SINGLE_PROCESS \
                and recorder.phase_violations:
            _fail(
                "Compute 阶段违规(import/open/exec/compile/native 通道):"
                + "; ".join(recorder.phase_violations[:8]),
                "compute-violations",
                access_summary=recorder.summary(), edic=edic,
                fd=RESULT_FD)
    except _RunnerFailure as exc:
        _fail(str(exc), "entrypoint-or-build",
              access_summary=recorder.summary(), edic=edic,
              fd=RESULT_FD if sealed else None)
    except ImportError as exc:
        _fail(f"builder module import 失败: {exc}", "import",
              access_summary=recorder.summary(), edic=edic,
              fd=RESULT_FD if sealed else None)
    except BaseException as exc:  # noqa: BLE001 - 一律 fail closed
        _fail(
            f"builder 执行抛出 {type(exc).__name__}(脱敏)", "execution",
            access_summary=recorder.summary(), edic=edic,
            fd=RESULT_FD if sealed else None)

    # final:经 RESULT_FD 单向通道发出(Builder 无法直接写该通道——
    # fd1/2 已是 /dev/null;RESULT_FD 写入只发生在 build 返回之后)。
    # 发出后等待 Supervisor 第二阶段确认(其在 Worker 存活期间完成
    # Compute 后二次外部实测),随后进程终止。
    _emit({
        "protocol": BUILDER_WORKER_PROTOCOL,
        "status": "ok", "phase": "final",
        "build_result": result,
        "seal_state": seal_state,
        "compute_audit": {
            "child_process_attempts": int(recorder.child_process_attempts),
            "exec_attempts": int(recorder.exec_attempts),
            "phase_violations": list(recorder.phase_violations),
            "dlopen_targets": sorted(recorder.dlopen_targets),
        },
        "error": None,
    }, fd=RESULT_FD)
    try:
        os.read(RESULT_ACK_FD, 8)
    except OSError:
        pass  # Supervisor 已关闭写端(异常路径):直接退出 fail closed
    os._exit(0)
    return 0  # unreachable


def _bundle_digest_from_file() -> str:
    try:
        manifest = json.loads(
            Path(BUNDLE_MANIFEST_PATH).read_text(encoding="utf-8"))
        return str(manifest.get("manifest_digest") or "")
    except (OSError, ValueError):
        return ""


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
