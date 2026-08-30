"""Builder Runner 沙箱 launcher(阶段 2.6.0i:纯 syscall,无外部命令)。

本进程由评估主进程(Supervisor)作为子进程启动:

    python -m rl_builder_runtime.bootstrap <config-json>

进程树与阶段(全部 fail closed;不再依赖 /usr/bin/unshare、mount(8)
与 /usr/sbin/pivot_root——0h 的沙箱工具路径在 2.6.0i 的 bundle rootfs
内不存在,布置全部改为直接 syscall):

    Supervisor(评估主进程)
      └─ launcher(本进程;fork child1 并代写 uid_map/gid_map
                  ——WSL2 内核拒绝自写)
          └─ child1:userns -> mountns(private) -> netns -> utsns
                  (sethostname builder-worker)-> bundle staging 挂载
                  (bind self + tmpfs dev/tmp/scratch + 设备 bind +
                  确定性熵 ro bind + root ro remount)-> pidns
                  └─ worker(pidns 内 pid 1;pivot_root -> umount
                      oldroot -> 挂载后 manifest 全量复验 -> Landlock
                      -> rlimits -> 关 fd -> execve Worker)

Worker 只见:内容寻址只读 bundle 根(/)、空 /proc、最小 /dev(null/
zero/full + 确定性熵文件 + 私有 shm)、全新 scratch/tmp tmpfs。
Worker 的全局 pid 经 fd3(worker-info 管道)回报 Supervisor,供
quiesce 时刻外部 /proc 实测(native 库、线程静止、seccomp 状态)。
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import resource
import sys
from pathlib import Path

from rl_builder_runtime.bundle import verify_mounted_bundle

_NR_LANDLOCK_CREATE_RULESET = 444
_NR_LANDLOCK_ADD_RULE = 445
_NR_LANDLOCK_RESTRICT_SELF = 446

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
_READ = (_LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_READ_DIR)
_READ_EXEC = _READ | _LANDLOCK_ACCESS_FS_EXECUTE
_RW = _ALL_KNOWN_RIGHTS & ~_LANDLOCK_ACCESS_FS_EXECUTE

#: namespace / mount 常量
CLONE_NEWNS = 0x00020000
CLONE_NEWUTS = 0x04000000
CLONE_NEWUSER = 0x10000000
CLONE_NEWPID = 0x20000000
CLONE_NEWNET = 0x40000000
MS_RDONLY = 1
MS_BIND = 4096
MS_REC = 16384
MS_PRIVATE = 1 << 18
MS_REMOUNT = 32
MNT_DETACH = 2
SYS_pivot_root = 155
SYS_umount2 = 166
SYS_unshare = 272
SYS_sethostname = 170

_DEV_BIND_NODES = ("null", "zero", "full")

_ENV_LANDLOCK_ABI = "RL_SB_LANDLOCK_ABI"
_ENV_LANDLOCK_HANDLED = "RL_SB_LANDLOCK_HANDLED"
_ENV_LANDLOCK_GRANTS = "RL_SB_LANDLOCK_GRANTS"
_ENV_MOUNTOPTS = "RL_SB_MOUNTOPTS"
_ENV_WORKER_HOSTNAME = "RL_SB_HOSTNAME"


class BuilderSandboxSetupError(RuntimeError):
    """Builder 沙箱布置失败(fail closed:绝不以弱隔离继续)。"""


def _libc():
    return ctypes.CDLL(None, use_errno=True)


def _syscall(nr, *args):
    libc = _libc()
    libc.syscall.restype = ctypes.c_long
    ctypes.set_errno(0)
    rc = libc.syscall(ctypes.c_long(nr), *args)
    return rc, ctypes.get_errno()


def _mount(src, tgt, fstype, flags, data=""):
    libc = _libc()
    libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p,
                           ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p]
    ctypes.set_errno(0)
    rc = libc.mount(
        str(src).encode() if src is not None else None,
        str(tgt).encode(), str(fstype).encode() if fstype else None,
        ctypes.c_ulong(flags),
        str(data).encode() if data else None)
    return rc, ctypes.get_errno()


def _die(child_msg: str, errno: int = 0) -> None:
    """child 侧失败:stderr 脱敏短消息后立即退出。"""
    print(json.dumps({"error": "builder-sandbox-bootstrap-error",
                      "stage": child_msg, "errno": errno}),
          file=sys.stderr, flush=True)
    os._exit(3)


# ------------------------------------------------------------ Landlock
def _landlock_abi_version() -> int:
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
    """应用 deny-by-default Landlock 规则;本进程与其后代不可解除。"""
    libc = _libc()
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

    class RulesetAttr(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    libc.syscall.restype = ctypes.c_long
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
        rights = _READ_EXEC if os.path.isdir(p) \
            else (_LANDLOCK_ACCESS_FS_READ_FILE
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


def apply_rlimits(limits: dict) -> dict:
    """CPU/地址空间/文件大小/nofile/nproc 限制(被 exec 继承)。"""
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


# ------------------------------------------------------------ 挂载布置
def _setup_mounts(bundle_root: str) -> dict:
    """child1 侧:bundle staging 的全部挂载(pivot 前)。

    注意:dev/shm 与设备占位文件必须在 dev tmpfs 挂载**之后**创建
    (落在 tmpfs 内,不污染已提交的 staging 树)。
    """
    # 自 bind 最先:使 bundle_root 成为挂载点(子挂载随 bind 视图)
    rc, e = _mount(bundle_root, bundle_root, None, MS_BIND | MS_REC)
    if rc != 0:
        _die("mount-bind-self", e)
    # 私有 tmpfs 子挂载
    rc, e = _mount("tmpfs", f"{bundle_root}/dev", "tmpfs", 0,
                   "size=4m,mode=755")
    if rc != 0:
        _die("mount-tmpfs-dev", e)
    os.makedirs(f"{bundle_root}/dev/shm", exist_ok=True)
    rc, e = _mount("tmpfs", f"{bundle_root}/dev/shm", "tmpfs", 0,
                   "size=16m,mode=1777")
    if rc != 0:
        _die("mount-tmpfs-devshm", e)
    rc, e = _mount("tmpfs", f"{bundle_root}/tmp", "tmpfs", 0,
                   "size=16m,mode=1777")
    if rc != 0:
        _die("mount-tmpfs-tmp", e)
    rc, e = _mount("tmpfs", f"{bundle_root}/scratch", "tmpfs", 0,
                   "size=64m,mode=1777")
    if rc != 0:
        _die("mount-tmpfs-scratch", e)
    # 设备节点(宿主 /dev bind;子挂载先于 ro remount)
    for node in _DEV_BIND_NODES:
        target = f"{bundle_root}/dev/{node}"
        open(target, "wb").close()
        rc, e = _mount(f"/dev/{node}", target, None, MS_BIND)
        if rc != 0:
            _die(f"mount-dev-{node}", e)
    # 确定性虚拟熵源:dev-internal 下受承诺文件 ro bind 到 /dev/*
    for name in ("urandom", "random"):
        src = f"{bundle_root}/dev-internal/{name}"
        target = f"{bundle_root}/dev/{name}"
        open(target, "wb").close()
        rc, e = _mount(src, target, None, MS_BIND)
        if rc != 0:
            _die(f"mount-entropy-{name}", e)
        rc, e = _mount(None, target, None,
                       MS_BIND | MS_REMOUNT | MS_RDONLY)
        if rc != 0:
            _die(f"mount-entropy-ro-{name}", e)
    # /proc 故意不挂载(动态内核状态对 Builder 不可观察)
    # 根只读 remount(子挂载保持各自标志:dev/tmp/scratch 仍 rw)
    rc, e = _mount(None, bundle_root, None,
                   MS_BIND | MS_REMOUNT | MS_RDONLY)
    if rc != 0:
        _die("mount-root-readonly", e)
    return {"bundle_root": bundle_root}


def _mountopts_digest(bundle_root: str) -> str:
    """pivot 后、umount 前的实际挂载集合摘要(经 /oldroot/proc 读取)。

    只计入新根自身的挂载点(过滤 /oldroot 前缀的旧根过渡挂载),使
    摘要跨运行确定(canonical 路径:/、/dev、/tmp、/scratch 等)。
    """
    rows = []
    with open("/oldroot/proc/self/mountinfo", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 7:
                continue
            mount_point, options, fstype = parts[4], parts[5], parts[-4]
            if mount_point == "/oldroot" or mount_point.startswith(
                    "/oldroot/"):
                continue  # 旧根挂载(detach 前的过渡视图)
            ro_rw = "ro" if "ro" in options.split(",") else "rw"
            rows.append("|".join((mount_point, fstype, ro_rw)))
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")
                          ).hexdigest()


# ------------------------------------------------------------ child1
def _child1_main(config: dict, ready_w, go_r, pid_w) -> None:
    bundle_root = str(config["bundle_root"])
    hostname = str(config.get("hostname") or "builder-worker")
    # worker-info 管道(fd3)属于 launcher 主进程,子树必须关闭
    # (Builder 不得获得该 fd 的写端)
    if config.get("worker_info_fd"):
        try:
            os.close(int(config["worker_info_fd"]))
        except OSError:
            pass
    # 1. user namespace(映射由 launcher 父进程写入)
    rc, e = _syscall(SYS_unshare, ctypes.c_int(CLONE_NEWUSER))
    if rc != 0:
        _die("unshare-userns", e)
    os.write(ready_w, b"R")
    if os.read(go_r, 2) != b"GO":
        _die("map-sync")
    # 2. mount namespace + 私有传播
    rc, e = _syscall(SYS_unshare, ctypes.c_int(CLONE_NEWNS))
    if rc != 0:
        _die("unshare-mountns", e)
    rc, e = _mount(None, "/", None, MS_REC | MS_PRIVATE)
    if rc != 0:
        _die("mount-private", e)
    # 3. net namespace
    rc, e = _syscall(SYS_unshare, ctypes.c_int(CLONE_NEWNET))
    if rc != 0:
        _die("unshare-netns", e)
    # 4. UTS namespace + 固定 hostname
    rc, e = _syscall(SYS_unshare, ctypes.c_int(CLONE_NEWUTS))
    if rc != 0:
        _die("unshare-utsns", e)
    libc = _libc()
    libc.sethostname.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
    ctypes.set_errno(0)
    if libc.sethostname(hostname.encode(), len(hostname)) != 0:
        _die("sethostname", ctypes.get_errno())
    # 5. bundle 挂载
    _setup_mounts(bundle_root)
    # 6. pid namespace -> fork:worker 为 pidns 内 pid 1
    rc, e = _syscall(SYS_unshare, ctypes.c_int(CLONE_NEWPID))
    if rc != 0:
        _die("unshare-pidns", e)
    worker_pid = os.fork()
    if worker_pid != 0:
        os.write(pid_w, str(worker_pid).encode())
        os.close(pid_w)
        _, status = os.waitpid(worker_pid, 0)
        code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 129
        os._exit(code)
    # ---- worker 进程(pidns pid 1)----
    os.close(ready_w)
    os.close(go_r)
    os.close(pid_w)
    _worker_main(config, bundle_root)


def _worker_main(config: dict, bundle_root: str) -> None:
    # 7. pivot_root 到 bundle;先经 /oldroot/proc 读取挂载摘要(过滤
    #    旧根过渡挂载),再 umount 旧根
    os.chdir(bundle_root)
    rc, e = _syscall(SYS_pivot_root, ctypes.c_char_p(b"."),
                     ctypes.c_char_p(f"{bundle_root}/oldroot".encode()))
    if rc != 0:
        _die("pivot-root", e)
    mounts_digest = _mountopts_digest(bundle_root)
    rc, e = _syscall(SYS_umount2, ctypes.c_char_p(b"/oldroot"),
                     ctypes.c_int(MNT_DETACH))
    if rc != 0:
        _die("umount-oldroot", e)
    # 8. 挂载后 manifest 全量复验(实际挂载内容;跳过运行时挂载点
    #    dev/tmp/scratch/oldroot——其内容由挂载摘要与 EDIC 探针管辖)
    try:
        verify_mounted_bundle(
            "/", skip_prefixes=("dev/", "tmp/", "scratch/", "oldroot/"))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({
            "error": "builder-sandbox-bootstrap-error",
            "stage": "mounted-bundle-verify",
            "detail": str(exc)[:300]}), file=sys.stderr, flush=True)
        os._exit(3)
    # 9. Landlock deny-by-default(可见即受承诺:/ 只读+exec;
    #    scratch/dev/tmp 读写)
    landlock_report = apply_landlock(
        read_exec=["/"], read_write=["/scratch", "/dev", "/tmp"],
        read_only=[], read_dir=[])
    # 10. rlimits
    rlimit_report = apply_rlimits(config.get("rlimits") or {})
    # 11. 布置摘要(execve 时定型,Worker 无法伪造)
    env = dict(config["exec_env"])
    env[_ENV_LANDLOCK_ABI] = str(landlock_report["landlock_abi"])
    env[_ENV_LANDLOCK_HANDLED] = str(
        landlock_report["handled_rights"])
    env[_ENV_LANDLOCK_GRANTS] = json.dumps(
        landlock_report["granted"], sort_keys=True,
        separators=(",", ":"))
    env[_ENV_MOUNTOPTS] = mounts_digest
    env[_ENV_WORKER_HOSTNAME] = str(config.get("hostname")
                                    or "builder-worker")
    # 12. 关闭 0/1/2 之外的继承 fd,exec Worker
    os.closerange(3, 1 << 16)
    os.chdir("/scratch")
    os.execve(config["exec_argv"][0], list(config["exec_argv"]), env)


# ------------------------------------------------------------ 入口
def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(json.dumps({
            "error": "builder-sandbox-bootstrap-error", "detail": "usage: "
                      "python -m rl_builder_runtime.bootstrap <config-json>",
        }), flush=True)
        return 2
    try:
        config = json.loads(argv[1])
    except json.JSONDecodeError:
        print(json.dumps({"error": "builder-sandbox-bootstrap-error",
                          "detail": "config not json"}), flush=True)
        return 2
    bundle_root = str(config["bundle_root"])
    if not os.path.isdir(bundle_root):
        print(json.dumps({"error": "builder-sandbox-bootstrap-error",
                          "detail": "bundle root missing"}), flush=True)
        return 2
    ready_r, ready_w = os.pipe()
    go_r, go_w = os.pipe()
    pid_r, pid_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(ready_r)
        os.close(go_w)
        os.close(pid_r)
        _child1_main(config, ready_w, go_r, pid_w)
        os._exit(3)  # unreachable
    os.close(ready_w)
    os.close(go_r)
    os.close(pid_w)
    try:
        if os.read(ready_r, 1) != b"R":
            _, status = os.waitpid(pid, 0)
            print(json.dumps({
                "error": "builder-sandbox-bootstrap-error",
                "stage": "child-unshare"}), flush=True)
            return 3
        uid, gid = os.getuid(), os.getgid()
        with open(f"/proc/{pid}/setgroups", "w") as fh:
            fh.write("deny")
        with open(f"/proc/{pid}/uid_map", "w") as fh:
            fh.write(f"0 {uid} 1")
        with open(f"/proc/{pid}/gid_map", "w") as fh:
            fh.write(f"0 {gid} 1")
        os.write(go_w, b"GO")
        os.close(go_w)
        # worker 全局 pid 回报 Supervisor(fd3 由 Supervisor 传入)
        raw = os.read(pid_r, 32)
        os.close(pid_r)
        worker_pid = raw.decode().strip() if raw else ""
        if worker_pid.isdigit() and config.get("worker_info_fd"):
            try:
                os.write(int(config["worker_info_fd"]),
                         (worker_pid + "\n").encode())
            except OSError:
                pass
        _, status = os.waitpid(pid, 0)
        code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 129
        return code
    except OSError as exc:
        print(json.dumps({
            "error": "builder-sandbox-bootstrap-error",
            "stage": "launcher", "errno": exc.errno}), flush=True)
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except OSError:
            pass
        return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
