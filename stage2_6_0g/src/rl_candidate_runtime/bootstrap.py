"""沙箱 bootstrap:进入系统级隔离后 exec 候选 worker(阶段 2.6.0b 工作包 C)。

本进程由评估主进程通过以下 namespace 包装启动(全部已在 unshare 中生效):

    unshare --user --map-root-user --mount --pid --mount-proc --fork --net

bootstrap 在 mount namespace 内完成沙箱布置,顺序严格为
(C2:必须在加载 checkpoint 之前进入沙箱):

 1. mount tmpfs 于 /tmp(候选的独立临时文件系统);
 2. mkdir /tmp/model 与 /tmp/scratch;
 3. bind-mount checkpoint + sidecar 到 /tmp/model/(中性路径,
    不暴露评估工作区),并 remount 只读;
 4. 应用 Landlock 规则(deny-by-default:只授予 allowlist 路径的
    读/执行/读写;评估工作区/隐藏包/生成器/评估源码一律不可见);
 5. 设置 rlimits(CPU/地址空间/文件大小/nofile/nproc);
 6. 关闭除 0/1/2 之外的继承文件描述符(C4);
 7. exec 候选 worker(网络 namespace 已隔离;Landlock 与 rlimits
    被 exec 继承且不可解除)。

网络隔离(C5)由独立 network namespace 提供(只有 down 状态的 lo,
无路由、无 DNS);PID/proc 隔离(C4)由独立 PID namespace + 新 procfs
提供(候选只能看到沙箱内进程)。

配置以 JSON 形式经 argv 传入(不含任何考试内容:只有 allowlist 路径
与资源限制)。
"""

from __future__ import annotations

import ctypes
import json
import os
import resource
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- Landlock
# Landlock syscalls(x86_64;WSL2 内核 6.18 支持,ABI >= v4)
_NR_LANDLOCK_CREATE_RULESET = 444
_NR_LANDLOCK_ADD_RULE = 445
_NR_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_CREATE_RULESET_VERSION = 1 << 0

# 访问权限位(Landlock ABI)
_LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
_LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
_LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
_LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
_LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
_LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
_LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
_LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
_LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
_LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
_LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
_LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
_LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
_LANDLOCK_ACCESS_FS_REFER = 1 << 13          # ABI v2
_LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14       # ABI v3
_LANDLOCK_ACCESS_FS_IOCTL_DEV = 1 << 15      # ABI v4

_ALL_KNOWN_RIGHTS = (
    _LANDLOCK_ACCESS_FS_EXECUTE | _LANDLOCK_ACCESS_FS_WRITE_FILE
    | _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_READ_DIR
    | _LANDLOCK_ACCESS_FS_REMOVE_DIR | _LANDLOCK_ACCESS_FS_REMOVE_FILE
    | _LANDLOCK_ACCESS_FS_MAKE_CHAR | _LANDLOCK_ACCESS_FS_MAKE_DIR
    | _LANDLOCK_ACCESS_FS_MAKE_REG | _LANDLOCK_ACCESS_FS_MAKE_SOCK
    | _LANDLOCK_ACCESS_FS_MAKE_FIFO | _LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | _LANDLOCK_ACCESS_FS_MAKE_SYM | _LANDLOCK_ACCESS_FS_REFER
    | _LANDLOCK_ACCESS_FS_TRUNCATE | _LANDLOCK_ACCESS_FS_IOCTL_DEV
)

_READ = (
    _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_READ_DIR)
_READ_EXEC = _READ | _LANDLOCK_ACCESS_FS_EXECUTE
_RW = _ALL_KNOWN_RIGHTS & ~_LANDLOCK_ACCESS_FS_EXECUTE
_RO_STRICT = _READ  # 无写/无截断/无删除/无创建


class SandboxSetupError(RuntimeError):
    """沙箱布置失败(fail closed:绝不以弱隔离继续)。"""


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def _landlock_abi_version() -> int:
    """Landlock ABI 版本探测(1/2/4;按内核支持的最大权利集确定)。

    通过尝试以不同权利集创建 ruleset 实现:内核接受 v4 全集 -> 4;
    不接受 TRUNCATE/IOCTL_DEV -> 2;不接受 REFER -> 1;否则不支持。
    """
    libc = _libc()

    class RulesetAttr(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    def _try_rights(rights: int) -> bool:
        libc.syscall.restype = ctypes.c_long
        fd = libc.syscall(
            ctypes.c_long(_NR_LANDLOCK_CREATE_RULESET),
            ctypes.byref(RulesetAttr(rights)),
            ctypes.c_size_t(ctypes.sizeof(RulesetAttr)), ctypes.c_uint(0))
        if fd < 0:
            return False
        os.close(int(fd))
        return True

    if _try_rights(_ALL_KNOWN_RIGHTS):
        return 4
    v2 = _ALL_KNOWN_RIGHTS & ~(_LANDLOCK_ACCESS_FS_TRUNCATE
                               | _LANDLOCK_ACCESS_FS_IOCTL_DEV)
    if _try_rights(v2):
        return 2
    if _try_rights(v2 & ~_LANDLOCK_ACCESS_FS_REFER):
        return 1
    raise SandboxSetupError(
        "Landlock 权利集探测失败:无法建立受控规则集(fail closed)")


def apply_landlock(
    *, read_exec: list[str], read_only: list[str], read_write: list[str],
) -> dict:
    """应用 deny-by-default Landlock 规则;本进程与其后代不可解除。

    未列出的路径:读/写/执行全部拒绝(评估工作区、隐藏考试包、
    生成器与评估源码、用户 home 其余部分对候选完全不可见)。
    """
    abi = _landlock_abi_version()
    if abi >= 4:
        handled = _ALL_KNOWN_RIGHTS
    elif abi == 2:
        handled = _ALL_KNOWN_RIGHTS & ~(
            _LANDLOCK_ACCESS_FS_TRUNCATE | _LANDLOCK_ACCESS_FS_IOCTL_DEV)
    else:
        handled = _ALL_KNOWN_RIGHTS & ~(
            _LANDLOCK_ACCESS_FS_TRUNCATE | _LANDLOCK_ACCESS_FS_IOCTL_DEV
            | _LANDLOCK_ACCESS_FS_REFER)

    libc = _libc()
    libc.syscall.restype = ctypes.c_long

    class RulesetAttr(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    ruleset_fd = libc.syscall(
        ctypes.c_long(_NR_LANDLOCK_CREATE_RULESET),
        ctypes.byref(RulesetAttr(handled)),
        ctypes.c_size_t(ctypes.sizeof(RulesetAttr)), ctypes.c_uint(0))
    if ruleset_fd < 0:
        raise SandboxSetupError(
            f"landlock_create_ruleset 失败 errno={ctypes.get_errno()}")

    class PathBeneath(ctypes.Structure):
        # struct landlock_path_beneath_attr 是 packed 布局:
        # __u64 allowed_access; __s32 parent_fd; (共 12 字节,无尾部填充)
        _pack_ = 1
        _fields_ = [
            ("allowed_access", ctypes.c_uint64),
            ("parent_fd", ctypes.c_int32),
        ]

    granted: list[dict] = []

    def add_rule(path: str, rights: int) -> None:
        try:
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
        except OSError as exc:
            raise SandboxSetupError(
                f"Landlock 规则路径不可打开 {path!r}: {exc}") from exc
        # 注意:字段名为 allowed_access;位置传参避免关键字拼写漂移
        rule = PathBeneath(rights & handled, fd)
        rc = libc.syscall(
            ctypes.c_long(_NR_LANDLOCK_ADD_RULE),
            ctypes.c_int(int(ruleset_fd)),
            ctypes.c_int(1),  # LANDLOCK_RULE_PATH_BENEATH
            ctypes.byref(rule), ctypes.c_uint(0))
        os.close(fd)
        if rc != 0:
            raise SandboxSetupError(
                f"landlock_add_rule({path}) 失败 errno={ctypes.get_errno()}")
        granted.append({"path": path, "rights": int(rights & handled)})

    for p in read_exec:
        add_rule(p, _READ_EXEC)
    for p in read_only:
        add_rule(p, _RO_STRICT)
    for p in read_write:
        add_rule(p, _RW)

    # no_new_privs + restrict_self 后规则对本进程及后代生效
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise SandboxSetupError(
            f"PR_SET_NO_NEW_PRIVS 失败 errno={ctypes.get_errno()}")
    rc = libc.syscall(
        ctypes.c_long(_NR_LANDLOCK_RESTRICT_SELF),
        ctypes.c_int(int(ruleset_fd)), ctypes.c_uint(0))
    if rc != 0:
        raise SandboxSetupError(
            f"landlock_restrict_self 失败 errno={ctypes.get_errno()}")
    os.close(int(ruleset_fd))
    return {"landlock_abi": abi, "handled_rights": int(handled),
            "granted": granted}


# ---------------------------------------------------------------- rlimits
_RLIMIT_MAP = {
    "cpu_seconds": (resource.RLIMIT_CPU, None),
    "address_space_mb": (resource.RLIMIT_AS, 1024 * 1024),
    "file_size_mb": (resource.RLIMIT_FSIZE, 1024 * 1024),
    "nofile": (resource.RLIMIT_NOFILE, None),
    "nproc": (resource.RLIMIT_NPROC, None),
}


def apply_rlimits(limits: dict) -> dict:
    applied = {}
    for name, (which, scale) in _RLIMIT_MAP.items():
        value = limits.get(name)
        if value is None:
            continue
        v = int(value) * scale if scale else int(value)
        try:
            resource.setrlimit(which, (v, v))
            applied[name] = v
        except (ValueError, OSError) as exc:
            raise SandboxSetupError(f"setrlimit({name}) 失败: {exc}") from exc
    return applied


# ---------------------------------------------------------------- mounts
def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SandboxSetupError(
            f"沙箱 mount 布置失败: {' '.join(cmd)} -> "
            f"{proc.stderr.strip() or proc.returncode}")


def setup_mounts(workdir: str, checkpoint_path: str) -> dict:
    """在父进程提供的 staging 目录内布置沙箱文件系统(C2/C3)。

    staging 是评估主进程创建的匿名临时目录(不在评估工作区/项目目录
    下);候选在沙箱内可见:
    - <workdir>/model/checkpoint...    只读 bind mount(中性路径);
    - <workdir>/scratch/               tmpfs(候选唯一可写目录);
    - <workdir>/runtime/               最小候选运行时(只读,父进程复制)。
    其余一切路径(含真实 /tmp 其余内容、评估工作区、用户 home)由
    Landlock deny-by-default 拒绝。
    """
    workdir = str(Path(workdir).resolve())
    model_dir = os.path.join(workdir, "model")
    scratch = os.path.join(workdir, "scratch")
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(scratch, exist_ok=True)
    os.chmod(model_dir, 0o555)
    name = os.path.basename(checkpoint_path)
    dst = os.path.join(model_dir, name)
    # bind mount 挂载点必须先存在(空文件占位,随即被只读绑定覆盖)
    Path(dst).touch(exist_ok=True)
    _run(["mount", "--bind", checkpoint_path, dst])
    _run(["mount", "-o", "remount,bind,ro", dst])
    sidecar_src = checkpoint_path + ".rl_manifest.json"
    if os.path.isfile(sidecar_src):
        sidecar_dst = os.path.join(model_dir, name + ".rl_manifest.json")
        Path(sidecar_dst).touch(exist_ok=True)
        _run(["mount", "--bind", sidecar_src, sidecar_dst])
        _run(["mount", "-o", "remount,bind,ro", sidecar_dst])
    _run(["mount", "-t", "tmpfs", "-o", "size=128m,mode=1777",
          "tmpfs", scratch])
    return {
        "model_dir": model_dir,
        "checkpoint_neutral_path": dst,
        "scratch": scratch,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(json.dumps({
            "error": "sandbox-bootstrap-error", "detail": "usage: "
                      "python -m rl_candidate_runtime.bootstrap <config-json>",
        }), flush=True)
        return 2
    config = json.loads(argv[1])
    try:
        mounts = setup_mounts(config["workdir"], config["checkpoint_path"])
        landlock_report = apply_landlock(
            read_exec=list(config["landlock"]["read_exec"]),
            read_only=list(config["landlock"]["read_only"]) + [
                mounts["model_dir"]],
            read_write=list(config["landlock"]["read_write"]) + [
                mounts["scratch"]],
        )
        rlimit_report = apply_rlimits(config.get("rlimits") or {})
    except SandboxSetupError as exc:
        print(json.dumps({"error": "sandbox-bootstrap-error",
                          "stage": "setup"}), flush=True)
        print(f"bootstrap: {exc}", file=sys.stderr, flush=True)
        return 3
    # C4:关闭 0/1/2 之外的继承 fd
    os.closerange(3, 1 << 16)
    # __CHECKPOINT__ 占位符替换为沙箱内中性只读路径(不暴露评估工作区)
    argv_exec = [
        mounts["checkpoint_neutral_path"] if a == "__CHECKPOINT__" else a
        for a in config["exec_argv"]
    ]
    env = dict(config["exec_env"])
    env.setdefault("HOME", mounts["scratch"])
    env.setdefault("TMPDIR", mounts["scratch"])
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    os.chdir(mounts["scratch"])
    os.execve(argv_exec[0], argv_exec, env)
    return 0  # unreachable


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
