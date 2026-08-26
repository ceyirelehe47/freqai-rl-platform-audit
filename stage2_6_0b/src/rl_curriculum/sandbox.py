"""阶段 2.6.0b 工作包 C:正式候选系统级密封沙箱(parent 侧启动器)。

2.6.0a 的 JSON-lines 子进程只是 API 隔离:候选与评估主进程共享文件
系统、PID/proc、网络与当前用户权限。本模块建立真实的系统级隔离:

- unshare --user --map-root-user --mount --pid --mount-proc --fork --net:
  独立 mount namespace(tmpfs /tmp + 只读中性 checkpoint 路径)、
  独立 PID namespace + 新 procfs(看不到父进程/评估进程)、独立
  network namespace(只有 down 状态 lo,无路由无 DNS)、独立用户
  namespace(候选以 ns 内 root 运行,外映射为普通 uid);
- Landlock deny-by-default 文件规则(内核 6.18 WSL2,ABI >= v4):
  只授予 allowlist 路径读/执行/读写;评估工作区、隐藏考试包、
  sealed manifest、retirement/attempt registry、生成器与评估源码、
  用户 home 其余部分对候选完全不可见(open 返回 EACCES);
- rlimits:CPU 时间/地址空间/文件大小/nofile/nproc(C7);
- 父进程侧协议限制:单步响应超时、stdout 单行长度上限、整场考试
  看门狗;超时/超限/协议违规 -> CandidateSandboxError -> EXAM_INVALID;
- 沙箱在 checkpoint 加载之前进入(C2):bind-mount 与 Landlock 都在
  bootstrap 内完成,worker 进程从 exec 起就在限制内;
- 最小候选运行时(C6):只有 rl_candidate_runtime(worker 协议 +
  checkpoint 守卫 + bootstrap)被复制进独立 staging 目录挂给候选,
  rl_curriculum 评估代码不进入沙箱。

SandboxProfile 可规范化哈希(sp- 前缀),进入 sealed commitment:
profile 变化 = 新考试(旧承诺校验失败)。
"""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rl_curriculum.policy_api import CandidatePolicy

SANDBOX_PROFILE_FORMAT = "candidate-sandbox-profile-v1"
UNSHARE_BIN = "/usr/bin/unshare"
#: 沙箱内候选的响应行上限(字节;C7)
MAX_RESPONSE_LINE_BYTES = 4096


class CandidateSandboxError(RuntimeError):
    """候选沙箱错误/协议违规/超时(fail closed -> EXAM_INVALID)。"""


class SandboxUnavailableError(RuntimeError):
    """当前环境不满足系统级沙箱能力(正式考试不得降级运行)。"""


# ---------------------------------------------------------------- profile
@dataclass(frozen=True)
class SandboxProfile:
    """候选沙箱配置(可哈希,进入 sealed commitment)。"""

    read_exec_dirs: tuple[str, ...] = ()
    read_only_dirs: tuple[str, ...] = ()
    read_write_dirs: tuple[str, ...] = ()
    rlimits: dict[str, int] = field(default_factory=lambda: {
        "cpu_seconds": 1800,
        "address_space_mb": 6144,
        "file_size_mb": 64,
        "nofile": 256,
        # 注意:RLIMIT_NPROC 按真实 uid 全系统计数(WSL 内该 uid 还有
        # 其他进程),取值必须容纳 torch/libgomp 线程池;仍能约束失控
        # 子进程爆炸(与 cpu_seconds 一起封顶)
        "nproc": 512,
    })
    step_timeout_seconds: float = 60.0
    greeting_timeout_seconds: float = 120.0

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "format": SANDBOX_PROFILE_FORMAT,
            "read_exec_dirs": list(self.read_exec_dirs),
            "read_only_dirs": list(self.read_only_dirs),
            "read_write_dirs": list(self.read_write_dirs),
            "rlimits": {k: int(v) for k, v in sorted(self.rlimits.items())},
            "step_timeout_seconds": float(self.step_timeout_seconds),
            "greeting_timeout_seconds": float(self.greeting_timeout_seconds),
            "max_response_line_bytes": MAX_RESPONSE_LINE_BYTES,
        }

    def profile_hash(self) -> str:
        return "sp-" + __import__("hashlib").sha256(
            json.dumps(self.canonical_payload(), sort_keys=True,
                       separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")).hexdigest()


def _default_runtime_dirs(python_executable: str) -> tuple[tuple[str, ...],
                                                           tuple[str, ...]]:
    """从解释器位置推导运行时只读目录(conda env 根 + 系统 lib)。"""
    py = Path(python_executable).resolve()
    env_root = py.parent.parent  # <env>/bin/python -> <env>
    read_exec = [str(env_root)]
    for d in ("/usr", "/lib", "/lib64", "/lib32", "/bin", "/sbin", "/opt"):
        if os.path.isdir(d):
            read_exec.append(d)
    read_only = [d for d in ("/etc", "/proc", "/sys") if os.path.isdir(d)]
    return tuple(read_exec), tuple(read_only)


def default_sandbox_profile(
    python_executable: str | None = None,
) -> SandboxProfile:
    """默认沙箱 profile:系统运行时只读执行 + /dev 读写(/dev/null 等)。

    注意 /dev 需要写权限(glibc/标准库写 /dev/null、/dev/urandom 读);
    设备节点本身的 DAC 权限在用户 namespace 下仍然生效。
    """
    read_exec, read_only = _default_runtime_dirs(
        python_executable or sys.executable)
    rw = tuple(d for d in ("/dev",) if os.path.isdir(d))
    return SandboxProfile(
        read_exec_dirs=read_exec, read_only_dirs=read_only,
        read_write_dirs=rw,
    )


# ---------------------------------------------------------------- staging
def assemble_runtime_staging(dest_dir, *, source_dir=None) -> Path:
    """把最小候选运行时复制到独立 staging 目录(沙箱外临时位置)。

    staging 不在评估工作区内,也不在项目目录下——候选只知道 staging
    路径本身(内容是公开的最小运行时)。
    """
    import rl_candidate_runtime

    src = Path(source_dir) if source_dir else Path(
        rl_candidate_runtime.__file__).parent
    dst = Path(dest_dir) / "rl_candidate_runtime"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for f in sorted(src.glob("*.py")):
        shutil.copy2(f, dst / f.name)
    return dst.parent


# ---------------------------------------------------------------- launcher
def _existing(paths) -> list[str]:
    return [p for p in paths if os.path.exists(p)]


def build_bootstrap_config(
    profile: SandboxProfile, *, checkpoint_path: str, workdir: str,
    exec_argv: list[str], exec_env: dict[str, str],
    extra_read_exec: list[str] | None = None,
) -> str:
    """传给沙箱 bootstrap 的 JSON 配置(只含 allowlist 路径与限制)。

    extra_read_exec:launch 期附加的只读执行目录(最小运行时 staging;
    匿名临时路径,不进入 profile 哈希,profile 哈希绑定的是运行时
    内容文件哈希,由 sealed commitment 另行绑定)。
    """
    config = {
        "checkpoint_path": str(Path(checkpoint_path).resolve()),
        "workdir": str(Path(workdir).resolve()),
        "landlock": {
            "read_exec": _existing(
                list(profile.read_exec_dirs) + list(extra_read_exec or [])),
            "read_only": _existing(profile.read_only_dirs),
            "read_write": _existing(profile.read_write_dirs),
        },
        "rlimits": dict(profile.rlimits),
        "exec_argv": list(exec_argv),
        "exec_env": dict(exec_env),
    }
    return json.dumps(config, separators=(",", ":"), ensure_ascii=False)


def launch_sandboxed(
    profile: SandboxProfile, *,
    checkpoint_path: str,
    exec_argv: list[str],
    exec_env: dict[str, str],
    staging_dir,
    cwd=None,
    unshare_bin: str = UNSHARE_BIN,
) -> subprocess.Popen:
    """在系统级沙箱内启动 exec_argv(候选 worker 或沙箱探针)。

    沙箱层次:unshare(user+mount+pid+proc+net) -> bootstrap(中性只读
    checkpoint 路径/tmpfs scratch/Landlock/rlimits/关 fd) -> execve。
    staging_dir 是父进程创建的匿名临时目录(<staging>/runtime 为最小
    候选运行时;<staging>/model 与 <staging>/scratch 由 bootstrap 布置)。
    返回的 Popen 的 stdin/stdout/stderr 为管道,其余 fd 已关闭。
    """
    if not os.path.isfile(unshare_bin):
        raise SandboxUnavailableError(
            f"缺少 unshare({unshare_bin}):无法建立系统级沙箱,"
            f"正式考试不得降级为普通子进程")
    staging = assemble_runtime_staging(staging_dir)
    workdir = Path(staging).parent
    Path(workdir, "model").mkdir(parents=True, exist_ok=True)
    Path(workdir, "scratch").mkdir(parents=True, exist_ok=True)
    # checkpoint 先复制到 staging 内的 model_src(Landlock 不授予该目录,
    # bind 挂载源在 /proc/self/mountinfo 中只暴露中性 staging 路径,
    # 不泄露评估工作区/提交路径;副本与 sidecar SHA 由守卫逐字节校验)
    model_src = Path(workdir, "model_src")
    model_src.mkdir(parents=True, exist_ok=True)
    ckpt_name = os.path.basename(checkpoint_path)
    staged_ckpt = model_src / ckpt_name
    shutil.copy2(checkpoint_path, staged_ckpt)
    sidecar_src = str(checkpoint_path) + ".rl_manifest.json"
    if os.path.isfile(sidecar_src):
        shutil.copy2(sidecar_src, str(staged_ckpt) + ".rl_manifest.json")
    # bootstrap 的 execve 会以 exec_env 完全替换环境:worker 运行所需的
    # PYTHONPATH(staging)/PATH 必须显式进入 exec_env;OMP/MKL 单线程
    # 保证 predict 确定性与资源占用下界
    exec_env = dict(exec_env)
    exec_env.setdefault("PYTHONPATH", str(staging))
    exec_env.setdefault("PATH", f"{Path(exec_argv[0]).resolve().parent}"
                          ":/usr/bin:/bin")
    exec_env.setdefault("OMP_NUM_THREADS", "1")
    exec_env.setdefault("MKL_NUM_THREADS", "1")
    exec_env.setdefault("OPENBLAS_NUM_THREADS", "1")
    config_json = build_bootstrap_config(
        profile, checkpoint_path=str(staged_ckpt), workdir=workdir,
        exec_argv=exec_argv, exec_env=exec_env,
        extra_read_exec=[str(staging)])
    argv = [
        unshare_bin,
        "--user", "--map-root-user",
        "--mount", "--pid", "--mount-proc", "--fork", "--net",
        exec_argv[0], "-m", "rl_candidate_runtime.bootstrap", config_json,
    ]
    env = {
        "PATH": f"{Path(exec_argv[0]).resolve().parent}:/usr/bin:/bin",
        "PYTHONPATH": str(staging),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env, text=True, bufsize=1,
        cwd=str(cwd or staging), close_fds=True,
    )


class _LineReader:
    """带超时与单行长度上限的行读取器(C7:协议违规 fail closed)。"""

    def __init__(self, fileobj, *, timeout: float, max_bytes: int):
        self._f = fileobj
        self._timeout = float(timeout)
        self._max = int(max_bytes)
        self._buf = ""

    def readline(self) -> str:
        deadline = time.monotonic() + self._timeout
        fd = self._f.fileno()
        while "\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CandidateSandboxError(
                    f"候选响应超时(> {self._timeout}s):fail closed,"
                    f"不产出部分成绩")
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                raise CandidateSandboxError(
                    f"候选响应超时(> {self._timeout}s):fail closed,"
                    f"不产出部分成绩")
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            self._buf += chunk.decode("utf-8", errors="replace")
            if len(self._buf.encode("utf-8")) > self._max:
                raise CandidateSandboxError(
                    f"候选 stdout 单行超过 {self._max} 字节上限:"
                    f"协议违规 fail closed(EXAM_INVALID)")
        line, _, self._buf = self._buf.partition("\n")
        if len(line.encode("utf-8")) > self._max:
            raise CandidateSandboxError(
                f"候选 stdout 单行超过 {self._max} 字节上限:"
                f"协议违规 fail closed(EXAM_INVALID)")
        return line


class SandboxedCandidate(CandidatePolicy):
    """正式候选执行器:系统级沙箱内运行最小运行时 worker。

    - reset 消息逐字节 {"op": "reset"}(无 Episode 身份 token);
    - checkpoint 在沙箱内以中性路径只读可见(加载发生在隔离生效后);
    - 单步超时/行长上限/进程提前退出 -> CandidateSandboxError
      (formal_exam 映射 EXAM_INVALID)。
    """

    name = "sandboxed_candidate"

    def __init__(
        self,
        checkpoint_path,
        *,
        expected_charter_hash: str,
        expected_observation_schema_hash: str,
        profile: SandboxProfile | None = None,
        python: str | None = None,
        staging_root=None,
    ):
        import tempfile

        self.profile = profile or default_sandbox_profile(python)
        self.python = str(Path(python or sys.executable).resolve())
        self.checkpoint_path = str(Path(checkpoint_path).resolve())
        if not Path(self.checkpoint_path).is_file():
            raise CandidateSandboxError(
                "checkpoint 不存在(已脱敏:不回传路径)")
        self._staging_root = Path(
            staging_root or tempfile.mkdtemp(
                prefix="rl-candidate-sandbox-"))
        self._staging_root.mkdir(parents=True, exist_ok=True)
        self._proc = launch_sandboxed(
            self.profile,
            checkpoint_path=self.checkpoint_path,
            exec_argv=[self.python, "-m", "rl_candidate_runtime.worker",
                       "__CHECKPOINT__",
                       expected_charter_hash,
                       expected_observation_schema_hash],
            exec_env={},
            staging_dir=self._staging_root / "runtime",
        )
        self._stderr_tail: list[str] = []
        self._reader = _LineReader(
            self._proc.stdout,
            timeout=self.profile.greeting_timeout_seconds,
            max_bytes=MAX_RESPONSE_LINE_BYTES)
        greeting = self._reader.readline()
        try:
            payload = json.loads(greeting)
        except json.JSONDecodeError as exc:
            raise CandidateSandboxError(
                "候选沙箱启动失败(bootstrap/worker 未按协议问候,"
                "已脱敏)") from exc
        if payload.get("error"):
            raise CandidateSandboxError(
                f"候选沙箱启动失败(已脱敏): {payload.get('error')}")
        from rl_candidate_runtime import WORKER_PROTOCOL

        if payload.get("protocol") != WORKER_PROTOCOL:
            raise CandidateSandboxError(
                f"候选 worker 协议版本不符:期望 {WORKER_PROTOCOL},"
                f"收到 {payload.get('protocol')!r}")

    # ---------------------------------------------------------- 协议
    def _send(self, payload: dict[str, Any], *, timeout: float | None = None
              ) -> dict[str, Any]:
        reader = self._reader
        if timeout is not None:
            reader._timeout = float(timeout)  # noqa: SLF001
        try:
            assert self._proc.stdin is not None
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise CandidateSandboxError(
                "候选沙箱通信失败(已脱敏:无隐藏参数)") from exc
        line = reader.readline()
        try:
            reply = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CandidateSandboxError(
                "候选沙箱回复无法解析(已脱敏)") from exc
        if "error" in reply:
            raise CandidateSandboxError(
                f"候选沙箱错误(已脱敏): {reply['error']}"
                f"/stage={reply.get('stage', '?')}")
        return reply

    def reset_episode(self) -> None:
        # 工作包 B:消息逐字节 {"op": "reset"}——无任何 Episode 身份 token
        self._send({"op": "reset"})

    def act(self, observation) -> int:
        obs = list(map(float, observation))
        return int(self._send({"op": "act", "obs": obs},
                              timeout=self.profile.step_timeout_seconds
                              )["action"])

    def close(self) -> None:
        try:
            self._send({"op": "close"},
                       timeout=min(self.profile.step_timeout_seconds, 10.0))
            self._proc.wait(timeout=10)
        except Exception:  # noqa: BLE001 - 清理阶段不抛
            self._proc.kill()
        finally:
            for stream in (self._proc.stdin, self._proc.stdout,
                           self._proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass

    # ---------------------------------------------------------- 诊断
    @property
    def worker_returncode(self) -> int | None:
        return self._proc.poll()


# ---------------------------------------------------------------- 能力探测
def sandbox_capability_report() -> dict[str, Any]:
    """WSL 内核沙箱能力矩阵(unshare/landlock/no_new_privs/网络隔离)。"""
    report: dict[str, Any] = {"checked_utc": time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    report["kernel"] = subprocess.run(
        ["uname", "-r"], capture_output=True, text=True).stdout.strip()
    report["unshare_binary"] = os.path.isfile(UNSHARE_BIN)
    # 1) user+mount+pid+proc+net namespace 组合
    try:
        probe = subprocess.run(
            [UNSHARE_BIN, "--user", "--map-root-user", "--mount", "--pid",
             "--mount-proc", "--fork", "--net", "/bin/sh", "-c",
             "id -u && ls /proc/self/uid_map >/dev/null && "
             "grep -c . /proc/net/dev >/dev/null && echo NS-OK"],
            capture_output=True, text=True, timeout=30)
        report["namespaces_user_mount_pid_proc_net"] = (
            probe.returncode == 0 and "NS-OK" in probe.stdout)
    except Exception as exc:  # noqa: BLE001
        report["namespaces_user_mount_pid_proc_net"] = False
        report["namespaces_error"] = repr(exc)
    # 2) tmpfs 挂载能力(mount namespace 内)
    try:
        probe = subprocess.run(
            [UNSHARE_BIN, "--user", "--map-root-user", "--mount", "--fork",
             "/bin/sh", "-c",
             "mkdir -p /tmp/rl_cap && mount -t tmpfs tmpfs /tmp/rl_cap "
             "&& echo TMPFS-OK && umount /tmp/rl_cap"],
            capture_output=True, text=True, timeout=30)
        report["tmpfs_mount"] = probe.returncode == 0 and "TMPFS-OK" in probe.stdout
    except Exception as exc:  # noqa: BLE001
        report["tmpfs_mount"] = False
        report["tmpfs_error"] = repr(exc)
    # 3) 只读 bind mount 能力
    try:
        probe = subprocess.run(
            [UNSHARE_BIN, "--user", "--map-root-user", "--mount", "--fork",
             "/bin/sh", "-c",
             "touch /tmp/rl_cap_src && mkdir -p /tmp/rl_cap_dst && "
             "mount --bind /tmp/rl_cap_src /tmp/rl_cap_dst && "
             "mount -o remount,bind,ro /tmp/rl_cap_dst && "
             "echo x > /tmp/rl_cap_dst 2>/dev/null && echo BIND-WRITABLE "
             "|| echo BIND-RO-OK"],
            capture_output=True, text=True, timeout=30)
        report["bind_mount_readonly"] = (
            probe.returncode == 0 and "BIND-RO-OK" in probe.stdout)
    except Exception as exc:  # noqa: BLE001
        report["bind_mount_readonly"] = False
        report["bind_mount_error"] = repr(exc)
    # 4) 网络命名空间隔离(无外连通性)
    try:
        probe = subprocess.run(
            [UNSHARE_BIN, "--user", "--map-root-user", "--net", "--fork",
             "/bin/sh", "-c",
             "cat /proc/net/route | wc -l"],
            capture_output=True, text=True, timeout=30)
        # 空 netns 只有 lo:路由表应有 0 条外部路由
        lines = [ln for ln in probe.stdout.splitlines() if ln.strip()]
        report["netns_only_loopback"] = probe.returncode == 0 and len(lines) <= 1
    except Exception as exc:  # noqa: BLE001
        report["netns_only_loopback"] = False
        report["netns_error"] = repr(exc)
    # 5) Landlock ABI(bootstrap 探测逻辑的镜像)
    try:
        from rl_candidate_runtime.bootstrap import _landlock_abi_version

        report["landlock_abi"] = _landlock_abi_version()
    except Exception as exc:  # noqa: BLE001
        report["landlock_abi"] = None
        report["landlock_error"] = repr(exc)
    # 6) PR_SET_NO_NEW_PRIVS
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.restype = ctypes.c_int
        rc = libc.prctl(38, 1, 0, 0, 0)
        report["no_new_privs"] = rc == 0
    except Exception as exc:  # noqa: BLE001
        report["no_new_privs"] = False
        report["nnprivs_error"] = repr(exc)

    required = (
        "namespaces_user_mount_pid_proc_net", "tmpfs_mount",
        "bind_mount_readonly", "netns_only_loopback",
    )
    report["system_level_sandbox_available"] = bool(
        all(report.get(k) for k in required)
        and report.get("landlock_abi"))
    return report
