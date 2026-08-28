"""Builder Runner worker:沙箱内执行私有 Builder(阶段 2.6.0h)。

启动形态(由 rl_builder_runtime.bootstrap exec;pivot_root 最小
rootfs + 私有 /dev + Landlock 已生效):

    python -m rl_builder_runtime.runner <builder_pkg_staging> \
        <entrypoint_module> <entrypoint_qualname>

协议(builder-runner-worker-v2;每行一个 JSON):
- stdin:  单行冻结构建请求(builder-build-request-v3)
- stdout: 单行 Runner 响应
  {"protocol": "builder-runner-worker-v2", "status": "ok"|"failed",
   "build_result": {...v3 result...},
   "runtime_lock": {...v2:分布内容验证 + native 绑定 + 进程树...},
   "sandbox_report": {...实际生效沙箱状态 + 探针...},
   "access_summary": {...v2:事件覆盖 + 计数...},
   "error": null | "..."}

阶段 2.6.0h 职责:
- A1:import Builder 前安装 seccomp 进程树策略(fork/vfork/clone3/
  execve/execveat/ptrace/process_vm_*/mount/umount2/unshare/setns 全
  拒;clone 仅允许 CLONE_THREAD 线程;RLIMIT_NPROC 为附加防线);
- A2:ctypes.dlopen 审计 + /proc/self/maps 实际加载 .so 全部绑定
  内容与归属(未绑定 native library 拒绝);
- C1:Effective Sandbox Report 由本进程**实际运行**产生(内核版本/
  nnp/seccomp 模式/挂载摘要/rlimits/继承 fd/pidns 进程/netns 接口/
  fork/exec/宿主路径探针),esb- 哈希进入 evidence;
- D1/D2:运行时依赖锁 v2——sys.modules 差集 -> distribution ->
  RECORD 逐文件重算实际哈希(修改 package 文件而 RECORD 不变会被
  发现) -> distribution content digest;
- G2:audit hook 记录 open/listdir/scandir/dlopen/subprocess/
  os.system 事件(CPython 3.11 无 os.stat 审计事件;stat 级不可
  利用由 pivot_root 宿主路径 ENOENT 保证,见 sandbox_report 探针);
- 任何错误只回脱敏短消息,不回传 traceback/环境/文件内容。
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

from rl_builder_runtime import (
    BUILDER_WORKER_PROTOCOL,
    PRIVATE_DEV_NODES,
    PROC_MINIMAL_FILES,
)

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
RUNTIME_LOCK_FORMAT_V2 = "builder-runtime-lock-v2"
ACCESS_SUMMARY_FORMAT_V2 = "builder-access-summary-v2"
SANDBOX_REPORT_FORMAT = "builder-effective-sandbox-report-v1"
SINGLE_PROCESS = "single_builder_process"
ALLOW_DESCENDANTS = "allow_descendants"

# ------------------------------------------------------------ seccomp(A1)
#: x86_64 syscall 编号(进程树/内核状态修改类)
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

_CLONE_THREAD = 0x00010000

SECCOMP_PROCESS_POLICY = {
    "format": "builder-seccomp-policy-v1",
    "arch": "x86_64",
    "default_action": "allow",
    "deny_eperm": sorted(name for name in (
        "fork", "vfork", "execve", "execveat", "ptrace", "mount",
        "umount2", "unshare", "setns", "process_vm_readv",
        "process_vm_writev", "bpf", "perf_event_open")),
    "clone3_action": "ENOSYS",
    "clone": {"require_any_flag": ["CLONE_THREAD"],
              "missing_flag_action": "EPERM"},
    "thread_creation": "allowed_clone_thread_only",
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


def canonical_seccomp_filter() -> list[dict]:
    """进程树策略的确定性 BPF 程序(纯函数;主进程重算 digest 对账)。"""
    nr = {
        "fork": _SYS_FORK, "vfork": _SYS_VFORK, "execve": _SYS_EXECVE,
        "execveat": _SYS_EXECVEAT, "ptrace": _SYS_PTRACE,
        "mount": _SYS_MOUNT, "umount2": _SYS_UMOUNT2,
        "unshare": _SYS_UNSHARE, "setns": _SYS_SETNS,
        "process_vm_readv": _SYS_PROCESS_VM_READV,
        "process_vm_writev": _SYS_PROCESS_VM_WRITEV, "bpf": _SYS_BPF,
        "perf_event_open": _SYS_PERF_EVENT_OPEN,
    }
    prog = [{"code": _BPF_LD_W_ABS, "jt": 0, "jf": 0, "k": 0}]
    for name in SECCOMP_PROCESS_POLICY["deny_eperm"]:
        prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 1, "k": nr[name]})
        prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0,
                     "k": _RET_ERRNO | _ERRNO_EPERM})
    prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 1, "k": _SYS_CLONE3})
    prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0,
                 "k": _RET_ERRNO | _ERRNO_ENOSYS})
    prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 5, "k": _SYS_CLONE})
    prog.append({"code": _BPF_LD_W_ABS, "jt": 0, "jf": 0, "k": 16})
    prog.append({"code": _BPF_ALU_AND_K, "jt": 0, "jf": 0,
                 "k": _CLONE_THREAD})
    prog.append({"code": _BPF_JEQ_K, "jt": 0, "jf": 1, "k": 0})
    prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0,
                 "k": _RET_ERRNO | _ERRNO_EPERM})
    prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0, "k": _RET_ALLOW})
    prog.append({"code": _BPF_RET_K, "jt": 0, "jf": 0, "k": _RET_ALLOW})
    return prog


def seccomp_filter_digest(prog: list[dict] | None = None) -> str:
    prog = canonical_seccomp_filter() if prog is None else prog
    return "scp-" + hashlib.sha256(json.dumps(
        prog, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def install_seccomp_filter() -> dict:
    """安装进程树策略 seccomp filter(要求 no_new_privs;fail closed)。"""
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


# ------------------------------------------------------------ 访问审计
class _AccessRecorder:
    """audit hook:CPython 实际存在的运行时访问事件(H/B4/G)。

    覆盖:open / os.listdir / os.scandir / os.system / subprocess.
    Popen / ctypes.dlopen。CPython 3.11 对 os.stat/os.access/
    os.readlink 不发审计事件——stat 级不可利用由 pivot_root 最小
    rootfs 保证(宿主路径 ENOENT,见 sandbox_report 探针)。

    phase 感知:report 阶段的内部探针不计入违规与计数;build 阶段
    的 outside 访问/子进程尝试/exec 尝试才是拒绝依据。
    """

    #: 路径类事件 -> 参数索引
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

    def hook(self, event: str, args) -> None:
        try:
            self.event_counts[event] = self.event_counts.get(event, 0) + 1
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
                    return  # PATH 查找名,无目录信息
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
        # 只保留实际可 stat 到的违规路径(pivot 后宿主路径 ENOENT,
        # import finder 的无效探测不构成泄露;读得到的 outside 才算)
        reachable = [p for p in self.outside if os.path.exists(p)]
        return {
            "format": ACCESS_SUMMARY_FORMAT_V2,
            "open_count": len(self.open_events),
            "outside_allowlist": reachable,
            "covered_events": sorted(
                set(self.PATH_EVENTS) | set(self.CHILD_EVENTS)
                | set(self.EXEC_EVENTS)),
            "child_process_attempts": self.child_process_attempts,
            "exec_attempts": self.exec_attempts,
            "dlopen_targets": sorted(self.dlopen_targets),
        }


# ------------------------------------------------------------ 入口验证
def _validate_entrypoint_signature(fn) -> list[str]:
    """C1:build 入口必须是精确的 ``build_pack(request)``。"""
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
    """E2:first_pass attempt log 硬约束(结构 + 选择规则)。

    - 编号从 0 开始、严格连续、唯一、每个 < max_attempts;
    - 选中 attempt 之前全部 reject;选中条目是第一个且唯一 accept;
    - 选中之后不得有条目;selected_attempt 等于该 accept 编号;
    - 没有 accept 时构建必须失败(status!=ok 且 pack=None,由
      result 校验联动;assembly 模式豁免:策略为 assembly 时
      max_attempts=0 无条目)。
    """
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
    # first_pass:编号 0 起连续唯一,范围合法
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
            return  # 全部尝试耗尽后失败:合法的失败日志
        return  # 空日志 + 构建失败由 result 联动校验
    # 有选中
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
    """D3 + E2:result v3 精确字段 + attempt log 联动。"""
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


# ------------------------------------------------- 沙箱报告(C1)
def _read_status_fields() -> dict:
    fields: dict[str, str] = {}
    with open("/proc/self/status", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith(("NoNewPrivs", "Seccomp", "Seccomp_filters")):
                k, _, v = line.strip().partition(":")
                fields[k] = v.strip()
    return fields


def _proc_pids() -> list[int]:
    return sorted(int(n) for n in os.listdir("/proc") if n.isdigit())


def _net_interfaces() -> list[str]:
    # socket.if_nameindex()(syscall 级):Landlock 文件规则对 netns
    # proc superblock(/proc/self/net/*)不生效,接口证明不经文件系统
    import socket

    return sorted(name for _, name in socket.if_nameindex())


def _inherited_fds() -> list[int]:
    """枚举进程当前持续打开的 fd。

    listdir(fd) 内部会 dup 产生短命 fd(枚举噪声);readlink 已消失
    的 fd 视为噪声过滤——只保留枚举后仍稳定打开的 fd(0/1/2 管道)。
    """
    dirfd = os.open("/proc/self/fd", os.O_RDONLY | os.O_DIRECTORY)
    try:
        names = os.listdir(dirfd)
    finally:
        os.close(dirfd)
    stable: list[int] = []
    for n in sorted(int(x) for x in names
                    if x.isdigit() and int(x) != dirfd):
        try:
            os.readlink(f"/proc/self/fd/{n}")
            stable.append(n)
        except OSError:
            continue
    return stable


def _mountopts_digest() -> str:
    workdir = os.environ.get("RL_SB_WORKDIR", "")
    rows = []
    with open("/proc/self/mountinfo", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 7:
                continue
            mount_point = parts[4]
            if workdir:
                mount_point = mount_point.replace(workdir, "<WORKDIR>")
            rows.append("|".join(
                (mount_point, parts[-4],
                 "ro" if "ro" in parts[5].split(",") else "rw")))
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")
                          ).hexdigest()


def _stat_probe(path: str) -> str:
    try:
        os.stat(path)
        return "EXISTS"
    except FileNotFoundError:
        return "ENOENT"
    except OSError as exc:
        return f"ERR{exc.errno}"


def generate_sandbox_report(*, seccomp_state: dict,
                            process_tree_policy: str) -> dict:
    """C1:实际生效沙箱状态报告(bootstrap 证明 + 内核实测 + 探针)。

    hashed core 只含跨运行确定字段;易变细节(ns inode)进 detail。
    """
    env = os.environ
    for var in ("RL_SB_LANDLOCK_ABI", "RL_SB_LANDLOCK_HANDLED",
                "RL_SB_LANDLOCK_GRANTS", "RL_SB_MOUNTOPTS"):
        if not env.get(var):
            raise _RunnerFailure(
                f"沙箱布置摘要缺失({var});bootstrap 摘要未定型,"
                f"拒绝以未知沙箱状态继续")
    status = _read_status_fields()
    pids = _proc_pids()
    core = {
        "format": SANDBOX_REPORT_FORMAT,
        "kernel_release": os.uname().release,
        "landlock": {
            "abi": int(env["RL_SB_LANDLOCK_ABI"]),
            "handled_rights": int(env["RL_SB_LANDLOCK_HANDLED"]),
            "grants_hash": "grt-" + hashlib.sha256(
                env["RL_SB_LANDLOCK_GRANTS"].encode("utf-8")).hexdigest(),
        },
        "mounts_digest": _mountopts_digest(),
        "bootstrap_mountopts_digest": env["RL_SB_MOUNTOPTS"],
        "no_new_privs": int(status.get("NoNewPrivs", "0")),
        "seccomp_mode": int(status.get("Seccomp", "0")),
        "seccomp_filters": int(status.get("Seccomp_filters", "0")),
        "seccomp_filter_hash": seccomp_state.get("filter_hash"),
        "seccomp_policy": SECCOMP_PROCESS_POLICY,
        "namespaces": {
            "user": {"inside_userns_root_uid": os.getuid()},
            "mount": {"pivot_root_applied": True,
                      "root_fstype": "tmpfs"},
            "pid": {"self_pid_in_namespace": os.getpid(),
                    "pids_in_namespace": pids},
            "net": {"interfaces": _net_interfaces()},
        },
        "rlimits": _rlimits_snapshot(),
        "inherited_fds": _inherited_fds(),
        "process_tree_policy": process_tree_policy,
        "child_process_count": max(0, len(pids) - 1),
        "exec_count": 0,
        "private_dev_nodes": list(PRIVATE_DEV_NODES),
        "proc_minimal_files": list(PROC_MINIMAL_FILES),
        "probes": {},
    }
    # 行为探针(phase=report:不污染审计)
    probes: dict[str, dict] = {}
    try:
        pid = os.fork()
    except OSError as exc:
        probes["fork_denied"] = {"result": f"ERRNO{exc.errno}"}
    else:  # seccomp 未启用(allow_descendants 模式)才会走到这里
        if pid == 0:
            os._exit(0)  # pragma: no cover - 探针子进程立即退出
        os.waitpid(pid, 0)
        probes["fork_denied"] = {"result": "LEAKED"}
    if seccomp_state.get("installed"):
        try:
            os.execv(sys.executable, [sys.executable, "-c", ""])  # noqa: S606
            probes["exec_denied"] = {"result": "LEAKED"}
        except OSError as exc:
            probes["exec_denied"] = {"result": f"ERRNO{exc.errno}"}
    else:
        # seccomp 未安装(降级演示模式):execve 会真的替换本进程,
        # 探针跳过(降级本身已由 seccomp_mode=0 暴露)
        probes["exec_denied"] = {"result": "SKIPPED-NO-SECCOMP"}
    probes["host_etc_unnameable"] = {
        "path": "/etc/hostname", "result": _stat_probe("/etc/hostname")}
    probes["host_sys_unnameable"] = {
        "path": "/sys", "result": _stat_probe("/sys")}
    probes["host_home_unnameable"] = {
        "path": "/home/cryptorl/.ssh",
        "result": _stat_probe("/home/cryptorl/.ssh")}
    probes["dev_shm_private"] = {
        "listing": sorted(os.listdir("/dev/shm"))}
    core["probes"] = probes
    report = dict(core)
    report["detail"] = {
        "landlock_grants": json.loads(env["RL_SB_LANDLOCK_GRANTS"]),
    }
    return report


def sandbox_report_core(report: dict) -> dict:
    return {k: v for k, v in report.items() if k != "detail"}


def sandbox_report_hash(report: dict) -> str:
    return "esb-" + hashlib.sha256(json.dumps(
        sandbox_report_core(report), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _rlimits_snapshot() -> dict:
    import resource

    out = {}
    for name, which in (
            ("cpu_seconds", resource.RLIMIT_CPU),
            ("address_space_bytes", resource.RLIMIT_AS),
            ("file_size_bytes", resource.RLIMIT_FSIZE),
            ("nofile", resource.RLIMIT_NOFILE),
            ("nproc", resource.RLIMIT_NPROC)):
        soft, hard = resource.getrlimit(which)
        out[name] = [int(soft), int(hard)]
    return out


# ------------------------------------------------- 运行时依赖锁 v2(D)
def _distribution_content(dist) -> tuple[list[dict], str]:
    """D2:解析 RECORD 清单并对全部有哈希记录的安装文件计算实际哈希。

    返回 (files, content_digest);content_digest 是安装树的
    canonical 实际内容摘要(方案二):修改 package 文件但保持 RECORD
    不变 -> digest 变化 -> 旧 evidence 失效。RECORD 缺失/无条目 ->
    fail closed。
    """
    dist_dir = Path(getattr(dist, "_path", "")).parent
    record_path = Path(getattr(dist, "_path", "")) / "RECORD"
    if not record_path.is_file():
        raise _RunnerFailure(
            "distribution 缺少安装元数据 RECORD,内容无法验证(fail closed)")
    rows: list[tuple[str, str]] = []
    record_mismatches = 0
    text = record_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        rel, hash_spec = parts[0], parts[1]
        if not hash_spec.startswith("sha256="):
            continue
        expected = hash_spec.split("=", 1)[1]
        target = (dist_dir / rel).resolve()
        if not target.is_file():
            continue  # RECORD 中已删除/可选条目
        h = hashlib.sha256()
        with open(target, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        actual = h.hexdigest()
        if actual != expected:
            record_mismatches += 1
        rows.append((rel, actual))
    if not rows:
        raise _RunnerFailure("distribution RECORD 无可验证哈希条目")
    # 方案二:digest 基于**实际文件内容**(RECORD 只作清单来源)。
    # conda-forge 环境会系统性改写安装文件(pyc 重编译/entry point
    # 重写),要求实文件==RECORD 声明的方案一在此环境不可行;基于
    # 实际内容的 canonical tree digest 同样满足 D2/D4:修改 package
    # 文件而 RECORD 不变 -> digest 变化 -> 旧 evidence 失效。
    rows.append((".record_declared_mismatches", str(record_mismatches)))
    canonical = json.dumps(
        sorted(rows), separators=(",", ":"), ensure_ascii=False)
    digest = "dcd-" + hashlib.sha256(
        canonical.encode("utf-8")).hexdigest()
    rows.pop()
    files = [{"path": rel, "sha256": sha} for rel, sha in sorted(rows)]
    return files, digest


def distribution_content_digest(dist) -> str:
    """D2 公共入口:主进程对账用(重算实际内容摘要 dcd-)。"""
    _, digest = _distribution_content(dist)
    return digest


def _native_libraries(staging_root: str) -> list[dict]:
    """D3:/proc/self/maps 实际加载 .so 的内容绑定与归属。

    归属:staging(builder package,npb- 绑定)/ distribution(RECORD
    内)/ system(系统与解释器前缀)。任何其他位置(/dev/shm、/tmp、
    scratch、未知目录)的 native library 一律拒绝。
    """
    import importlib.metadata as md

    loaded: list[str] = []
    with open("/proc/self/maps", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 6:
                continue
            path = parts[5]
            if not path.startswith("/"):
                continue
            if path not in loaded:
                loaded.append(path)
    # distribution 文件集合(用于归属)
    dist_files: dict[str, str] = {}
    for dist_name in md.distributions() or []:
        try:
            base = Path(getattr(dist_name, "_path", "")).parent
            name = str(dist_name.metadata["Name"])
            for f in dist_name.files or []:
                dist_files[str((base / str(f)).resolve())] = name
        except Exception:  # noqa: BLE001 - 归属尽力,内容校验另走 RECORD
            continue
    prefixes = {
        "system:/usr/lib": "/usr/lib",
        "system:/lib": "/lib",
        "system:/lib64": "/lib64",
        f"system:{sys.prefix}": str(Path(sys.prefix).resolve()),
    }
    entries: list[dict] = []
    for path in sorted(loaded):
        resolved = str(Path(path).resolve())
        h = hashlib.sha256()
        try:
            with open(resolved, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        except OSError as exc:
            raise _RunnerFailure(
                f"native library {os.path.basename(resolved)} 内容不可读"
                f"(fail closed): {exc.errno}") from exc
        if resolved.startswith(str(staging_root)):
            origin = "staging"
            dist = ""
        elif resolved in dist_files:
            origin = "distribution"
            dist = dist_files[resolved]
        else:
            origin = ""
            for label, prefix in prefixes.items():
                if resolved.startswith(prefix):
                    origin = label
                    break
            if not origin:
                raise _RunnerFailure(
                    f"加载了未绑定位置的 native library "
                    f"{os.path.basename(resolved)}(仅允许 staging/"
                    f"distribution/系统前缀;fail closed)")
            dist = ""
        entries.append({"path": path, "sha256": h.hexdigest(),
                        "origin": origin, "distribution": dist})
    return entries


def _runtime_import_lock(baseline: frozenset, after: frozenset,
                         staging_root: str, *, child_count: int,
                         child_attempts: int = 0,
                         exec_count: int = 0) -> tuple[dict, str]:
    """D1/D2:实际 import 审计 + distribution 内容验证 + 进程树。"""
    import importlib.metadata as md

    new_modules = sorted(after - baseline)
    top_level: dict[str, list[str]] = {}
    for full in new_modules:
        top = full.split(".")[0]
        top_level.setdefault(top, []).append(full)
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    entries: list[dict] = []
    for top in sorted(top_level):
        if top in stdlib or top == "rl_builder_runtime":
            continue
        mod = sys.modules.get(top)
        origin = str(getattr(mod, "__file__", "") or "")
        if origin.startswith(str(staging_root)):
            continue  # builder package 自身(npb- 绑定)
        if not origin:
            return {}, f"module {top!r} 无源文件,无法验证内容身份"
        dist_names = md.packages_distributions().get(top)
        if not dist_names:
            return {}, (
                f"实际加载的第三方模块 {top!r} 无法映射到任何已安装 "
                f"distribution(未注册依赖 fail closed)")
        dist_name = sorted(dist_names)[0]
        try:
            dist = md.distribution(dist_name)
            version = str(dist.version)
        except Exception as exc:  # noqa: BLE001
            return {}, f"distribution {dist_name!r} 元数据不可读: {exc}"
        try:
            files, content_digest = _distribution_content(dist)
        except _RunnerFailure as exc:
            return {}, str(exc)
        record_path = Path(getattr(dist, "_path", "")) / "RECORD"
        record_sha = hashlib.sha256(
            record_path.read_bytes()).hexdigest()
        entries.append({
            "module": top,
            "distribution": dist_name,
            "version": version,
            "record_sha256": record_sha,
            "content_digest": content_digest,
            "verified_files": len(files),
            "imported": sorted(top_level[top]),
        })
    try:
        native = _native_libraries(staging_root)
    except _RunnerFailure as exc:
        return {}, str(exc)
    lock = {
        "format": RUNTIME_LOCK_FORMAT_V2,
        "python_implementation": sys.implementation.name,
        "python_version": sys.version.split()[0],
        "executable_prefix": str(getattr(sys, "prefix", "")),
        "process_tree_policy": SINGLE_PROCESS,
        "child_process_count": int(child_count),
        "child_process_attempts": int(child_attempts),
        "exec_count": int(exec_count),
        "distributions": entries,
        "native_libraries": native,
    }
    return lock, ""


# ------------------------------------------------------------ 主流程
class _RunnerFailure(Exception):
    """Runner 侧 fail closed 异常(消息必须可脱敏回传)。"""


def _emit(payload: dict) -> None:
    line = json.dumps(payload, ensure_ascii=False,
                      separators=(",", ":"))
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        sys.stdout.write(json.dumps({
            "protocol": BUILDER_WORKER_PROTOCOL,
            "status": "failed",
            "build_result": None, "runtime_lock": None,
            "sandbox_report": None, "access_summary": None,
            "error": "builder-runner-response-limit",
            "stage": "response-limit",
        }) + "\n")
        sys.stdout.flush()
        raise SystemExit(7)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _fail(error: str, stage: str, *, access_summary=None,
          sandbox_report=None) -> int:
    _emit({
        "protocol": BUILDER_WORKER_PROTOCOL,
        "status": "failed",
        "build_result": None,
        "runtime_lock": None,
        "sandbox_report": sandbox_report,
        "access_summary": access_summary,
        "error": str(error)[:500],
        "stage": str(stage),
    })
    return 2


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        return _fail(
            "usage: python -m rl_builder_runtime.runner <staging> "
            "<module> <qualname>", "usage")
    staging_root = str(Path(argv[1]).resolve())
    entrypoint_module = str(argv[2])
    entrypoint_qualname = str(argv[3])
    if not entrypoint_module or not entrypoint_qualname:
        return _fail("entrypoint module/qualname 为空", "usage")
    line = sys.stdin.readline()
    if not line.strip():
        return _fail("未收到冻结构建请求(stdin 为空)", "request")
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        return _fail("请求超过字节上限", "request-limit")
    try:
        request = json.loads(line)
    except json.JSONDecodeError:
        return _fail("请求不是合法 JSON", "request")
    if not isinstance(request, dict):
        return _fail("请求必须是 JSON 对象", "request")
    attempt_policy = dict(request.get("attempt_policy") or {})
    process_tree_policy = os.environ.get(
        "RL_BUILDER_PROCESS_TREE", SINGLE_PROCESS)
    if process_tree_policy not in (SINGLE_PROCESS, ALLOW_DESCENDANTS):
        return _fail(f"未知进程树策略 {process_tree_policy!r}", "policy")

    prefixes = [staging_root, str(Path(sys.prefix).resolve()),
                "/usr", "/lib", "/lib64", "/proc", "/dev", "/tmp"]
    recorder = _AccessRecorder(prefixes)
    baseline = frozenset(sys.modules)
    sys.addaudithook(recorder.hook)
    sandbox_report = None
    try:
        # A1:import Builder 之前安装 seccomp 进程树策略
        if process_tree_policy == SINGLE_PROCESS:
            try:
                seccomp_state = install_seccomp_filter()
            except OSError as exc:
                return _fail(f"seccomp 安装失败: {exc}", "seccomp")
        else:  # allow_descendants 仅供攻击演示测试;evidence 层拒绝
            seccomp_state = {"installed": False,
                             "filter_hash": seccomp_filter_digest(),
                             "no_new_privs": 1}
        # C1:实际生效沙箱报告(报告阶段探针不计入审计)
        recorder.phase = "report"
        sandbox_report = generate_sandbox_report(
            seccomp_state=seccomp_state,
            process_tree_policy=process_tree_policy)
        if process_tree_policy == SINGLE_PROCESS:
            if sandbox_report["seccomp_mode"] != 2:
                return _fail(
                    "seccomp 未实际生效(内核报告非 filter 模式)",
                    "sandbox", sandbox_report=sandbox_report)
            if sandbox_report["probes"]["fork_denied"]["result"] \
                    != f"ERRNO{errno.EPERM}":
                return _fail(
                    "fork 探针未被拒绝:进程树策略未生效", "sandbox",
                    sandbox_report=sandbox_report)
            if sandbox_report["probes"]["exec_denied"]["result"] \
                    != f"ERRNO{errno.EPERM}":
                return _fail(
                    "exec 探针未被拒绝:进程树策略未生效", "sandbox",
                    sandbox_report=sandbox_report)
        if sandbox_report["mounts_digest"] != \
                sandbox_report["bootstrap_mountopts_digest"]:
            return _fail(
                "pivot 后挂载集合与 bootstrap 摘要不一致(沙箱漂移)",
                "sandbox", sandbox_report=sandbox_report)
        for probe in ("host_etc_unnameable", "host_sys_unnameable",
                      "host_home_unnameable"):
            if sandbox_report["probes"][probe]["result"] != "ENOENT":
                return _fail(
                    f"宿主路径探针 {probe} 未返回 ENOENT:pivot_root "
                    f"最小 rootfs 未生效", "sandbox",
                    sandbox_report=sandbox_report)

        # 受控 import(build 阶段开始)
        recorder.phase = "build"
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
        raw = obj(dict(request))
        result = _validate_build_result(
            raw, attempt_policy=attempt_policy)
    except _RunnerFailure as exc:
        return _fail(str(exc), "entrypoint-or-build",
                     access_summary=recorder.summary(),
                     sandbox_report=sandbox_report)
    except ImportError as exc:
        return _fail(f"builder module import 失败: {exc}", "import",
                     access_summary=recorder.summary(),
                     sandbox_report=sandbox_report)
    except Exception as exc:  # noqa: BLE001 - builder 异常一律 fail closed
        return _fail(
            f"builder 执行抛出 {type(exc).__name__}(脱敏)", "execution",
            access_summary=recorder.summary(),
            sandbox_report=sandbox_report)
    # 进程树实测(D1):build 之后 pidns 内不得出现其他进程
    child_count = max(max(0, len(_proc_pids()) - 1),
                      recorder.child_process_attempts)
    exec_count = recorder.exec_attempts
    if process_tree_policy == SINGLE_PROCESS and (
            child_count > 0 or recorder.child_process_attempts > 0
            or exec_count > 0):
        return _fail(
            f"进程树违规:child={child_count},"
            f"attempts={recorder.child_process_attempts},"
            f"exec={exec_count}(single_builder_process 被违反)",
            "process-tree", access_summary=recorder.summary(),
            sandbox_report=sandbox_report)
    try:
        sandbox_report["child_process_count"] = child_count
        sandbox_report["child_process_attempts"] = int(
            recorder.child_process_attempts)
        sandbox_report["exec_count"] = exec_count
        lock, lock_error = _runtime_import_lock(
            baseline, frozenset(sys.modules), staging_root,
            child_count=child_count,
            child_attempts=recorder.child_process_attempts,
            exec_count=exec_count)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"运行时 import 审计失败: {exc}", "runtime-lock",
                     access_summary=recorder.summary(),
                     sandbox_report=sandbox_report)
    if lock_error:
        return _fail(f"运行时依赖锁 fail closed: {lock_error}",
                     "runtime-lock", access_summary=recorder.summary(),
                     sandbox_report=sandbox_report)
    access = recorder.summary()
    if access["outside_allowlist"]:
        names = sorted({os.path.basename(p)
                        for p in access["outside_allowlist"]})[:8]
        return _fail(
            "Builder 访问了 allowlist 之外的路径(已记录并拒绝采信):"
            + ",".join(names), "access", access_summary=access,
            sandbox_report=sandbox_report)
    _emit({
        "protocol": BUILDER_WORKER_PROTOCOL,
        "status": "ok",
        "build_result": result,
        "runtime_lock": lock,
        "sandbox_report": sandbox_report,
        "access_summary": access,
        "error": None,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
