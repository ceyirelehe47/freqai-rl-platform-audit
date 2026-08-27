"""Builder Runner 沙箱 bootstrap(阶段 2.6.0g 收尾:工作包 B2)。

本进程由评估主进程通过以下 namespace 包装启动(与 Candidate 沙箱
同一隔离层次,但挂载集合不同):

    unshare --user --map-root-user --mount --pid --mount-proc --fork --net

bootstrap 在 mount namespace 内完成 Builder 沙箱布置,顺序严格为:

 1. mount tmpfs 于 <workdir>/scratch(Builder 的独立临时文件系统,
    HOME/TMPDIR 指向这里);
 2. 把 <workdir>/runtime 与 <workdir>/builder_pkg 重新 bind 挂载为
    只读(Builder staging:主进程已复制并对账过的代码副本,Builder
    不可写、不可替换——TOCTOU 防护的执行侧);
 3. 应用 Landlock 规则(deny-by-default:只授予 allowlist 路径的
    读/执行/读写;评估工作区、候选 checkpoint、sidecar、attempt
    registry、隐藏考试 pack 与父进程敏感目录对 Builder 完全不可见);
 4. 设置 rlimits(CPU/地址空间/文件大小/nofile/nproc);
 5. 关闭除 0/1/2 之外的继承文件描述符;
 6. exec Builder Runner worker(网络 namespace 已隔离;Landlock 与
    rlimits 被 exec 继承且不可解除)。

与 rl_candidate_runtime.bootstrap 的关键差异(不同挂载集合):
- 没有 checkpoint/sidecar bind-mount(Candidate 独有);
- 没有 __CHECKPOINT__ 占位符替换;
- Landlock 只授予 staging 只读 + scratch 读写,不授予任何 model 目录。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Landlock syscalls/权限位与 rl_candidate_runtime.bootstrap 保持同一
# 内核接口(WSL2 内核 6.18,ABI >= v4);实现独立维护,Builder 与
# Candidate 的运行时互不依赖。
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
_RO_STRICT = _READ  # 无写/无截断/无删除/无创建


class BuilderSandboxSetupError(RuntimeError):
    """Builder 沙箱布置失败(fail closed:绝不以弱隔离继续)。"""


def _libc():
    import ctypes

    return ctypes.CDLL(None, use_errno=True)


def _landlock_abi_version() -> int:
    """Landlock ABI 版本探测(与 candidate bootstrap 同一探测逻辑)。"""
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


def apply_landlock(
    *, read_exec: list[str], read_only: list[str], read_write: list[str],
) -> dict:
    """应用 deny-by-default Landlock 规则;本进程与其后代不可解除。

    未列出的路径读/写/执行全部拒绝:评估工作区、候选 checkpoint/
    sidecar、attempt registry、隐藏考试 pack、父进程敏感目录对
    Builder 完全不可见(open 返回 EACCES)。
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
        # struct landlock_path_beneath_attr 是 packed 布局
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
        add_rule(p, _READ_EXEC)
    for p in read_only:
        add_rule(p, _RO_STRICT)
    for p in read_write:
        add_rule(p, _RW)

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
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BuilderSandboxSetupError(
            f"Builder 沙箱 mount 布置失败: {' '.join(cmd)} -> "
            f"{proc.stderr.strip() or proc.returncode}")


def setup_mounts(workdir: str) -> dict:
    """在父进程提供的 staging 目录内布置 Builder 沙箱文件系统。

    staging 是评估主进程创建的匿名临时目录;Builder 在沙箱内可见:
    - <workdir>/runtime/     最小 Builder 运行时(重新 bind 只读);
    - <workdir>/builder_pkg/ Builder package staging(重新 bind 只读);
    - <workdir>/scratch/     tmpfs(Builder 唯一可写目录)。
    其余一切路径(含评估工作区、候选材料、用户 home)由 Landlock
    deny-by-default 拒绝。
    """
    workdir = str(Path(workdir).resolve())
    runtime = os.path.join(workdir, "runtime")
    builder_pkg = os.path.join(workdir, "builder_pkg")
    scratch = os.path.join(workdir, "scratch")
    for d in (runtime, builder_pkg):
        if not os.path.isdir(d):
            raise BuilderSandboxSetupError(
                f"staging 目录缺失: {d}(主进程必须在启动前完成复制与对账)")
    os.makedirs(scratch, exist_ok=True)
    # staging 副本重新 bind 为只读:Builder 不可写自己的代码(TOCTOU
    # 执行侧;主进程已在启动前对 staging 重算 manifest 对账)
    _run(["mount", "--bind", runtime, runtime])
    _run(["mount", "-o", "remount,bind,ro", runtime])
    _run(["mount", "--bind", builder_pkg, builder_pkg])
    _run(["mount", "-o", "remount,bind,ro", builder_pkg])
    _run(["mount", "-t", "tmpfs", "-o", "size=64m,mode=1777",
          "tmpfs", scratch])
    return {"runtime": runtime, "builder_pkg": builder_pkg,
            "scratch": scratch}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(json.dumps({
            "error": "builder-sandbox-bootstrap-error", "detail": "usage: "
                      "python -m rl_builder_runtime.bootstrap <config-json>",
        }), flush=True)
        return 2
    config = json.loads(argv[1])
    try:
        mounts = setup_mounts(config["workdir"])
        landlock_report = apply_landlock(
            read_exec=list(config["landlock"]["read_exec"]),
            read_only=list(config["landlock"]["read_only"]) + [
                mounts["runtime"], mounts["builder_pkg"]],
            read_write=list(config["landlock"]["read_write"]) + [
                mounts["scratch"]],
        )
        from rl_builder_runtime.bootstrap import apply_rlimits
        rlimit_report = apply_rlimits(config.get("rlimits") or {})
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
