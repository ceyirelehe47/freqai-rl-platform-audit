"""Builder Runner 沙箱 bootstrap(阶段 2.6.0h:工作包 B,最小文件系统)。

本进程由评估主进程通过以下 namespace 包装启动:

    unshare --user --map-root-user --mount --pid --mount-proc --fork --net

阶段 2.6.0h 的沙箱布置(顺序严格,全部 fail closed):

 1. 在 <workdir>/scratch 挂 tmpfs(Builder 唯一可写目录,HOME/TMPDIR);
 2. 构造 newroot 最小 rootfs(<workdir>/newroot):
    - 先自 bind 使 newroot 成为挂载点(bind 不克隆子挂载,必须先
      自 bind 再布置子挂载);
    - rbind /usr(系统库/工具;WSL 下 /usr 含子挂载,--bind 会 EINVAL);
    - 主进程指定的 read_exec 目录(conda env 等)按**相同绝对路径**
      bind(pivot 后路径不变,exec_argv/PYTHONPATH/sys.prefix 不变);
    - <workdir> 自身按相同路径 bind(staging:runtime/builder_pkg/
      scratch;pivot 前重新 remount 只读,TOCTOU 执行侧);
    - 私有最小 /dev:tmpfs + bind null/zero/urandom/random/full +
      /dev/shm 独立 tmpfs(宿主 /dev/dev/shm 完全不可见;每次运行
      全新挂载,precommit 双跑与 exam replay 不共享可写状态)+ fd/
      stdin/stdout/stderr -> /proc/self/fd 符号链接;
    - 全新 /proc(pidns 私有;仅 Landlock 授予最小文件集);
    - 空的 /etc(ld.so 无 cache 时走默认搜索路径,探测已验证);
    - /sys **不创建**(ENOENT,stat 级不可利用);
    - 私有 /tmp tmpfs;bin/lib/lib64/sbin -> usr/* 符号链接;
 3. pivot_root 切换根(宿主路径在新 root 内**不可命名**:候选
    checkpoint/sidecar、/home、宿主 /tmp、宿主 /dev 对 Builder 均为
    ENOENT;umount -l 摘除旧 root);
 4. Landlock deny-by-default(只授予 staging 只读、scratch/dev/tmp
    读写、read_exec 目录、/proc 最小文件 + /proc 与 /proc/self/fd
    的 READ_DIR);
 5. rlimits(CPU/地址空间/文件大小/nofile/nproc;NPROC 附加防线);
 6. 关闭 0/1/2 之外的继承 fd;
 7. 通过 exec 环境向 Runner 传递沙箱布置摘要(RL_SB_*;builder 无
    法伪造,execve 时已定型);
 8. exec Builder Runner worker(seccomp 进程树策略由 runner 在
    import Builder 之前安装;网络 namespace 已隔离)。

与 rl_candidate_runtime.bootstrap 的关键差异:无 checkpoint bind、
无 __CHECKPOINT__ 占位符;pivot_root 最小 rootfs。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_NR_LANDLOCK_CREATE_RULESET = 444
_NR_LANDLOCK_ADD_RULE = 445
_NR_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_CREATE_RULESET_VERSION = 1 << 0

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

#: 私有最小 /dev 的设备节点(与 rl_builder_runtime.PRIVATE_DEV_NODES 一致)
_DEV_NODES = ("null", "zero", "urandom", "random", "full")

#: 传递给 Runner 的沙箱布置摘要环境变量(builder 阶段不可伪造)
_ENV_LANDLOCK_ABI = "RL_SB_LANDLOCK_ABI"
_ENV_LANDLOCK_HANDLED = "RL_SB_LANDLOCK_HANDLED"
_ENV_LANDLOCK_GRANTS = "RL_SB_LANDLOCK_GRANTS"
_ENV_MOUNTOPTS = "RL_SB_MOUNTOPTS"


class BuilderSandboxSetupError(RuntimeError):
    """Builder 沙箱布置失败(fail closed:绝不以弱隔离继续)。"""


def _libc():
    import ctypes

    return ctypes.CDLL(None, use_errno=True)


def _landlock_abi_version() -> int:
    """Landlock ABI 版本探测。"""
    import ctypes

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
    raise BuilderSandboxSetupError(
        "Landlock 权利集探测失败:无法建立受控规则集(fail closed)")


def apply_landlock(*, read_exec: list[str], read_only: list[str],
                   read_write: list[str], read_dir: list[str]) -> dict:
    """应用 deny-by-default Landlock 规则;本进程与其后代不可解除。

    未列出路径的读写/执行全部拒绝;read_dir 只授目录列举权(用于
    /proc 根与 /proc/self/fd 的 pid/fd 枚举,不授予其下文件读)。
    """
    import ctypes

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
        raise BuilderSandboxSetupError(
            f"landlock_create_ruleset 失败 errno={ctypes.get_errno()}")

    class PathBeneath(ctypes.Structure):
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
            raise BuilderSandboxSetupError(
                f"Landlock 规则路径不可打开 {path!r}: {exc}") from exc
        rule = PathBeneath(rights & handled, fd)
        rc = libc.syscall(
            ctypes.c_long(_NR_LANDLOCK_ADD_RULE),
            ctypes.c_int(int(ruleset_fd)),
            ctypes.c_int(1),  # LANDLOCK_RULE_PATH_BENEATH
            ctypes.byref(rule), ctypes.c_uint(0))
        os.close(fd)
        if rc != 0:
            raise BuilderSandboxSetupError(
                f"landlock_add_rule({path}) 失败 errno={ctypes.get_errno()}")
        granted.append({"path": path, "rights": int(rights & handled)})

    for p in read_exec:
        # 非目录目标(单文件)只授予该文件适用的权利位(含 READ_DIR/
        # MAKE_* 会 EINVAL)
        rights = _READ_EXEC if os.path.isdir(p)             else (_LANDLOCK_ACCESS_FS_READ_FILE
                  | _LANDLOCK_ACCESS_FS_EXECUTE)
        add_rule(p, rights)
    for p in read_only:
        add_rule(p, _READ if os.path.isdir(p)
                 else _LANDLOCK_ACCESS_FS_READ_FILE)
    for p in read_write:
        add_rule(p, _RW if os.path.isdir(p)
                 else (_ALL_KNOWN_RIGHTS & ~_LANDLOCK_ACCESS_FS_EXECUTE
                       & ~_LANDLOCK_ACCESS_FS_READ_DIR
                       & ~_LANDLOCK_ACCESS_FS_REMOVE_DIR
                       & ~_LANDLOCK_ACCESS_FS_REMOVE_FILE
                       & ~_LANDLOCK_ACCESS_FS_MAKE_CHAR
                       & ~_LANDLOCK_ACCESS_FS_MAKE_DIR
                       & ~_LANDLOCK_ACCESS_FS_MAKE_REG
                       & ~_LANDLOCK_ACCESS_FS_MAKE_SOCK
                       & ~_LANDLOCK_ACCESS_FS_MAKE_FIFO
                       & ~_LANDLOCK_ACCESS_FS_MAKE_BLOCK
                       & ~_LANDLOCK_ACCESS_FS_MAKE_SYM))
    for p in read_dir:
        add_rule(p, _LANDLOCK_ACCESS_FS_READ_DIR)

    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise BuilderSandboxSetupError(
            f"PR_SET_NO_NEW_PRIVS 失败 errno={ctypes.get_errno()}")
    rc = libc.syscall(
        ctypes.c_long(_NR_LANDLOCK_RESTRICT_SELF),
        ctypes.c_int(int(ruleset_fd)), ctypes.c_uint(0))
    if rc != 0:
        raise BuilderSandboxSetupError(
            f"landlock_restrict_self 失败 errno={ctypes.get_errno()}")
    os.close(int(ruleset_fd))
    return {"landlock_abi": abi, "handled_rights": int(handled),
            "granted": granted}


def _run(cmd: list[str]) -> None:
    # -n:跳过 utab 记账(userns 内 utab 不可写会 exit 16 但系统调用
    # 已成功;显式禁用记账使失败语义干净)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BuilderSandboxSetupError(
            f"Builder 沙箱 mount 布置失败: {' '.join(cmd)} -> "
            f"{proc.stderr.strip() or proc.returncode}")


_M = ["mount", "-n"]


def _build_newroot(workdir: str, read_exec: list[str]) -> dict:
    """构造 pivot 目标最小 rootfs 并切换(B1/B2)。

    read_exec 目录(conda env 等)按相同绝对路径 bind;pivot 后
    路径不变,exec_argv 与 sys.prefix 无需改写。
    """
    workdir = str(Path(workdir).resolve())
    newroot = os.path.join(workdir, "newroot")
    os.makedirs(newroot, exist_ok=True)
    for d in ("usr", "etc", "tmp", "proc", "dev", "run", "oldroot"):
        os.makedirs(os.path.join(newroot, d), exist_ok=True)
    for s, t in (("bin", "usr/bin"), ("lib", "usr/lib"),
                 ("lib64", "usr/lib64"), ("sbin", "usr/sbin")):
        os.symlink(t, os.path.join(newroot, s))
    # 自 bind 必须最先:bind 不克隆子挂载,之后的子挂载才会落在
    # 这个(将被 pivot 的)挂载点上
    _run(_M + ["--bind", newroot, newroot])
    # /usr 整树(WSL /usr 含 9p/overlay 子挂载,--bind EINVAL,须 rbind)
    _run(_M + ["--rbind", "/usr", os.path.join(newroot, "usr")])
    # read_exec 目录同路径 bind(conda env 等)
    for d in read_exec:
        d = str(Path(d).resolve())
        if d == "/usr":
            continue
        os.makedirs(newroot + d, exist_ok=True)
        _run(_M + ["--rbind", d, newroot + d])
    # 私有 /tmp tmpfs 必须先于 workdir bind 挂载(否则会遮蔽挂在
    # newroot/tmp/<workdir> 之下的 staging 子挂载)
    _run(_M + ["-t", "tmpfs", "-o", "size=16m,mode=1777",
               "tmpfs", os.path.join(newroot, "tmp")])
    # scratch tmpfs 必须先挂(在 bind workdir 之前挂载,才会随 bind
    # 进入 newroot 视图)
    runtime = os.path.join(workdir, "runtime")
    builder_pkg = os.path.join(workdir, "builder_pkg")
    scratch = os.path.join(workdir, "scratch")
    os.makedirs(scratch, exist_ok=True)
    _run(_M + ["-t", "tmpfs", "-o", "size=64m,mode=1777",
               "tmpfs", scratch])
    # staging(workdir)同路径 bind;runtime/builder_pkg 只读 remount
    os.makedirs(newroot + workdir, exist_ok=True)
    _run(_M + ["--bind", workdir, newroot + workdir])
    for d in (runtime, builder_pkg):
        if not os.path.isdir(d):
            raise BuilderSandboxSetupError(f"staging 目录缺失: {d}")
        _run(_M + ["--bind", d, newroot + d])
        _run(_M + ["-o", "remount,bind,ro", newroot + d])
    # 私有最小 /dev
    dev = os.path.join(newroot, "dev")
    _run(_M + ["-t", "tmpfs", "-o", "size=4m,mode=755", "tmpfs", dev])
    for node in _DEV_NODES:
        p = os.path.join(dev, node)
        open(p, "wb").close()
        _run(_M + ["--bind", f"/dev/{node}", p])
    os.makedirs(os.path.join(dev, "shm"))
    _run(_M + ["-t", "tmpfs", "-o", "size=16m,mode=1777",
               "tmpfs", os.path.join(dev, "shm")])
    os.symlink("/proc/self/fd", os.path.join(dev, "fd"))
    os.symlink("/proc/self/fd/0", os.path.join(dev, "stdin"))
    os.symlink("/proc/self/fd/1", os.path.join(dev, "stdout"))
    os.symlink("/proc/self/fd/2", os.path.join(dev, "stderr"))
    # 全新 /proc(pidns 私有)
    _run(_M + ["-t", "proc", "proc", os.path.join(newroot, "proc")])
    # /home 只为容纳同路径 conda env 的空目录链(read_exec 循环已建)
    # /sys 故意不创建:stat 级 ENOENT,不可利用
    # pivot
    os.chdir(newroot)
    _run(["/usr/sbin/pivot_root", ".", "oldroot"])
    _run(["/usr/bin/umount", "-l", "/oldroot"])
    return {"runtime": runtime, "builder_pkg": builder_pkg,
            "scratch": scratch, "newroot": "/"}


def _landlock_plan(read_exec: list[str], mounts: dict) -> dict:
    """pivot 后的 Landlock 授权计划(最小授予;其余全拒)。"""
    from rl_builder_runtime import PROC_MINIMAL_FILES

    read_write = [
        mounts["scratch"], "/dev", "/tmp",
    ]
    read_only = [
        mounts["runtime"], mounts["builder_pkg"],
        *list(PROC_MINIMAL_FILES),
    ]
    read_dir = ["/proc", "/proc/self/fd"]
    return {
        "read_exec": [p for p in read_exec if os.path.exists(p)],
        "read_only": [p for p in read_only if os.path.exists(p)],
        "read_write": [p for p in read_write if os.path.exists(p)],
        "read_dir": [p for p in read_dir if os.path.exists(p)],
    }


def _mountopts_digest(workdir: str) -> str:
    """pivot 后实际 mount 集合的规范化摘要(进入 RL_SB_MOUNTOPTS)。

    每行取 挂载点|fstype|ro/rw,排序后 sha256;staging 工作目录(每次运行随机 mkdtemp)替换为 <WORKDIR> 占位——相同 profile 的挂载集合跨运行
    确定,进入 Effective Sandbox Report(esb- 稳定)。
    """
    import hashlib

    rows = []
    with open("/proc/self/mountinfo", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 7:
                continue
            mount_point, options, fstype = parts[4], parts[5], parts[-4]
            mount_point = mount_point.replace(workdir, "<WORKDIR>")
            ro_rw = "ro" if "ro" in options.split(",") else "rw"
            rows.append("|".join((mount_point, fstype, ro_rw)))
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")
                          ).hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(json.dumps({
            "error": "builder-sandbox-bootstrap-error", "detail": "usage: "
                      "python -m rl_builder_runtime.bootstrap <config-json>",
        }), flush=True)
        return 2
    config = json.loads(argv[1])
    try:
        read_exec = [str(d) for d in config.get("read_exec") or []]
        mounts = _build_newroot(str(config["workdir"]), read_exec)
        plan = _landlock_plan(read_exec, mounts)
        landlock_report = apply_landlock(**plan)
        from rl_builder_runtime.bootstrap import apply_rlimits
        rlimit_report = apply_rlimits(config.get("rlimits") or {})
        mountopts = _mountopts_digest(str(config["workdir"]))
    except BuilderSandboxSetupError as exc:
        print(json.dumps({"error": "builder-sandbox-bootstrap-error",
                          "stage": "setup"}), flush=True)
        print(f"builder-bootstrap: {exc}", file=sys.stderr, flush=True)
        return 3
    except Exception as exc:  # noqa: BLE001 - fail closed,不泄漏细节
        print(json.dumps({"error": "builder-sandbox-bootstrap-error",
                          "stage": "setup"}), flush=True)
        print(f"builder-bootstrap: {exc}", file=sys.stderr, flush=True)
        return 3
    # 关闭 0/1/2 之外的继承 fd(Builder 不得拿到父进程多余句柄)
    os.closerange(3, 1 << 16)
    env = dict(config["exec_env"])
    env.setdefault("HOME", mounts["scratch"])
    env.setdefault("TMPDIR", mounts["scratch"])
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    # 沙箱布置摘要(execve 时定型,builder 无法伪造;runner 读取合并
    # 进 Effective Sandbox Report)
    env[_ENV_LANDLOCK_ABI] = str(landlock_report["landlock_abi"])
    env[_ENV_LANDLOCK_HANDLED] = str(landlock_report["handled_rights"])
    _wd = str(Path(config["workdir"]).resolve())
    env[_ENV_LANDLOCK_GRANTS] = json.dumps(
        [dict(g, path=g["path"].replace(_wd, "<WORKDIR>"))
         for g in landlock_report["granted"]],
        sort_keys=True, separators=(",", ":"))
    env[_ENV_MOUNTOPTS] = mountopts
    env["RL_SB_WORKDIR"] = str(Path(config["workdir"]).resolve())
    os.chdir(mounts["scratch"])
    os.execve(config["exec_argv"][0], list(config["exec_argv"]), env)
    return 0  # unreachable


# ---------------------------------------------------------------- rlimits
def apply_rlimits(limits: dict) -> dict:
    """CPU/地址空间/文件大小/nofile/nproc 限制(被 exec 继承)。"""
    import resource

    scale_map = {
        "cpu_seconds": (resource.RLIMIT_CPU, None),
        "address_space_mb": (resource.RLIMIT_AS, 1024 * 1024),
        "file_size_mb": (resource.RLIMIT_FSIZE, 1024 * 1024),
        "nofile": (resource.RLIMIT_NOFILE, None),
        "nproc": (resource.RLIMIT_NPROC, None),
    }
    applied = {}
    for name, (which, scale) in scale_map.items():
        value = limits.get(name)
        if value is None:
            continue
        v = int(value) * scale if scale else int(value)
        try:
            resource.setrlimit(which, (v, v))
            applied[name] = v
        except (ValueError, OSError) as exc:
            raise BuilderSandboxSetupError(
                f"setrlimit({name}) 失败: {exc}") from exc
    return applied


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
