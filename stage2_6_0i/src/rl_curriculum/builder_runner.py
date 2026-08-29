"""隔离 Builder Runner 启动器(阶段 2.6.0i,评估主进程侧)。

主评估进程对私有 Builder 只允许(沿 0g/0h):

- 读取并哈希 Builder 文件(builder package tree manifest;npb-);
- AST 静态检查(builder_identity 静态部分);
- 创建隔离 Runner(本模块);发送规范化 request;接收 v3 响应。

阶段 2.6.0i 沙箱层次(bootstrap 纯 syscall 布置,deny 降级即拒绝):

    fork launcher(userns[父写映射]/mountns/netns/utsns 固定 hostname)
      -> 内容寻址 bundle 根 fs(bind self + tmpfs dev/tmp/scratch +
         null/zero/full 设备 bind + 确定性熵 ro bind + 根 ro remount)
      -> pidns -> pivot_root -> 挂载摘要 -> umount 旧根
      -> 挂载后 manifest 全量复验(实际挂载内容)
      -> Landlock(/ 只读+exec;scratch/dev/tmp 读写)
      -> rlimits -> exec Worker(无 /proc、无 /usr、无活 conda 树)
      -> Worker:seccomp v2(arch/x32/进程全拒/线程全拒/clock/entropy)
         + vDSO 冻结 stub + PR_SET_TSC + 导入闭包 v3
      -> quiesce 握手:Supervisor 外部 /proc 实测(maps/task/status)
      -> final -> 运行后 staging 全量复验(TOCTOU/E10)

一次正式链路(precommit 双跑 + 重放)复用同一 bundle staging;每次
Worker 启动前在挂载视图内全量复验,运行结束后 Supervisor 再复验。
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rl_curriculum.builder_provenance import (
    BUILDER_RUN_MODE_EXECUTION,
    BuilderProvenanceError,
    canonicalize_attempt_log,
    check_frozen_build_request,
)

MAX_RUNNER_RESPONSE_BYTES = 32 * 1024 * 1024

RUNTIME_LOCK_FORMAT_V3 = "builder-runtime-lock-v3"
EDIC_FORMAT = "builder-deterministic-input-report-v1"
SINGLE_PROCESS = "single_builder_process"
ALLOW_DESCENDANTS = "allow_descendants"
THREAD_POLICY_FORBIDDEN = "threads_forbidden_clone_denied"
BUILDER_WORKER_HOSTNAME = "builder-worker"

#: bundle staging 默认根(必须与 conda env 同文件系统以支持硬链接;
#: $HOME 下不受 /tmp 清理影响)
DEFAULT_BUNDLE_ROOT = Path.home() / ".cache" / "rl_builder_bundles"


class BuilderRunnerError(RuntimeError):
    """隔离 Builder Runner 错误/协议违规/超时/沙箱降级(fail closed)。"""


# ---------------------------------------------------------------- profile
@dataclass(frozen=True)
class BuilderRunnerProfile:
    """Builder Runner 沙箱配置(可哈希,进入 Builder Run Evidence)。

    阶段 2.6.0i(v3):绑定内容寻址 runtime bundle、vDSO 冻结时钟、
    确定性虚拟熵、seccomp v2(arch/x32/进程/线程/时钟/熵)、无 /proc、
    固定 UTS hostname 与线程禁止策略。install_seccomp=False 或
    process_tree_policy=allow_descendants 仅供攻击演示测试——evidence
    校验要求密闭输入证明,此类 run 无法进入正式材料。
    """

    rlimits: dict[str, int] = field(default_factory=lambda: {
        "cpu_seconds": 900,
        "address_space_mb": 4096,
        "file_size_mb": 64,
        "nofile": 256,
        "nproc": 128,
    })
    run_timeout_seconds: float = 900.0
    response_max_bytes: int = MAX_RUNNER_RESPONSE_BYTES
    output_cap_bytes: int = MAX_RUNNER_RESPONSE_BYTES + 65536
    #: C1/C2:seccomp v2 进程/时钟/熵策略(正式链必须 True)
    install_seccomp: bool = True
    #: D1:进程树边界(正式链必须 single_builder_process)
    process_tree_policy: str = SINGLE_PROCESS
    #: bundle staging 根(None=默认 $HOME/.cache/rl_builder_bundles)
    bundle_root: str | None = None
    #: 组装/复验并行度
    bundle_jobs: int = 4

    def __post_init__(self) -> None:
        if self.process_tree_policy not in (SINGLE_PROCESS,
                                            ALLOW_DESCENDANTS):
            raise BuilderRunnerError(
                f"未知进程树策略 {self.process_tree_policy!r}")
        if not self.install_seccomp and \
                self.process_tree_policy == SINGLE_PROCESS:
            raise BuilderRunnerError(
                "seccomp 禁用时不得声明 single_builder_process"
                "(内核级进程树防线缺失,声明与事实不符)")

    def canonical_payload(self) -> dict[str, Any]:
        from rl_builder_runtime import PRIVATE_DEV_NODES
        from rl_builder_runtime.bundle import (
            BUNDLE_EXCLUDE_DIRS,
            BUNDLE_EXCLUDE_SUFFIXES,
            DETERMINISTIC_ENTROPY_SEED,
            RUNTIME_BUNDLE_MANIFEST_FORMAT,
        )
        from rl_builder_runtime.runner import (
            EDIC_FORMAT,
            SECCOMP_PROCESS_POLICY,
            seccomp_filter_digest,
        )

        return {
            "format": "builder-runner-profile-v3",
            "rlimits": {k: int(v) for k, v in sorted(self.rlimits.items())},
            "run_timeout_seconds": float(self.run_timeout_seconds),
            "response_max_bytes": int(self.response_max_bytes),
            "output_cap_bytes": int(self.output_cap_bytes),
            "seccomp": {
                "install": bool(self.install_seccomp),
                "policy": SECCOMP_PROCESS_POLICY,
                "filter_digest": seccomp_filter_digest(),
            },
            "process_tree_policy": self.process_tree_policy,
            "thread_policy": THREAD_POLICY_FORBIDDEN
            if self.process_tree_policy == SINGLE_PROCESS
            else "demo_allow_descendants",
            "runtime_bundle": {
                "manifest_format": RUNTIME_BUNDLE_MANIFEST_FORMAT,
                "content_addressed": True,
                "hardlink_assembly": True,
                "excludes": {
                    "dirs": sorted(BUNDLE_EXCLUDE_DIRS),
                    "suffixes": list(BUNDLE_EXCLUDE_SUFFIXES),
                },
                "mounted_verify_before_exec": True,
                "post_run_verify": True,
                "deterministic_entropy_seed_sha256": hashlib.sha256(
                    DETERMINISTIC_ENTROPY_SEED).hexdigest(),
            },
            "filesystem_view": {
                "pivot_root_bundle_rootfs": True,
                "private_dev_nodes": list(PRIVATE_DEV_NODES),
                "dev_random_urandom": "deterministic-committed-file",
                "private_dev_shm_tmpfs": True,
                "host_usr_visible": False,
                "host_conda_visible": False,
                "proc_mounted": False,
                "root_readonly": True,
                "fresh_scratch_tmpfs": True,
                "uts_hostname": BUILDER_WORKER_HOSTNAME,
            },
            "deterministic_input_report": EDIC_FORMAT,
            "env_whitelist": [
                "PATH", "PYTHONPATH", "PYTHONHOME", "LANG", "LC_ALL", "TZ",
                "PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE", "HOME",
                "TMPDIR", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS",
                "RL_BUILDER_PROCESS_TREE", "RL_SB_LANDLOCK_ABI",
                "RL_SB_LANDLOCK_HANDLED", "RL_SB_LANDLOCK_GRANTS",
                "RL_SB_MOUNTOPTS", "RL_SB_HOSTNAME",
            ],
            "fixed_env": {
                "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
                "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHOME": "/", "OMP_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                "NUMEXPR_NUM_THREADS": "1",
            },
        }

    def profile_hash(self) -> str:
        return "brp-" + hashlib.sha256(
            json.dumps(self.canonical_payload(), sort_keys=True,
                       separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")).hexdigest()


# ------------------------------------------------- 运行时 manifest(rtb-)
def _scan_tree_files(directory: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for f in sorted(directory.rglob("*")):
        rel = f.relative_to(directory)
        if any(part == "__pycache__" for part in rel.parts) \
                or f.suffix == ".pyc":
            continue
        if f.is_symlink():
            raise BuilderRunnerError(
                f"目录包含符号链接 {rel.as_posix()!r}(拒绝;内容绑定"
                f"不得经 symlink 逃逸)")
        if not f.is_file():
            continue
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        files[rel.as_posix()] = h.hexdigest()
    return files


def builder_runtime_manifest() -> dict[str, Any]:
    """rl_builder_runtime 的逐文件内容 manifest(进入 evidence)。"""
    import rl_builder_runtime
    from rl_builder_runtime import (
        BUILDER_RUNTIME_MANIFEST_FORMAT,
        REQUIRED_BUILDER_RUNTIME_FILES,
        RUNTIME_PACKAGE_VERSION,
        BUILDER_WORKER_PROTOCOL,
    )

    src = Path(rl_builder_runtime.__file__).parent
    files = _scan_tree_files(src)
    if not files:
        raise BuilderRunnerError("Builder 运行时目录为空(拒绝)")
    missing = [f for f in REQUIRED_BUILDER_RUNTIME_FILES if f not in files]
    if missing:
        raise BuilderRunnerError(
            f"Builder 运行时缺少必备文件 {missing}(拒绝)")
    return {
        "format": BUILDER_RUNTIME_MANIFEST_FORMAT,
        "runtime_package_version": RUNTIME_PACKAGE_VERSION,
        "worker_protocol": BUILDER_WORKER_PROTOCOL,
        "files": files,
    }


def builder_runtime_tree_hash(manifest: dict[str, Any]) -> str:
    return "rtb-" + hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


# ------------------------------------------------------------ staging(B3)
def _copy_tree(src: Path, dst: Path, *, label: str) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for f in sorted(src.rglob("*")):
        rel = f.relative_to(src)
        if any(part == "__pycache__" for part in rel.parts) \
                or f.suffix == ".pyc":
            continue
        if f.is_symlink():
            raise BuilderRunnerError(
                f"{label} 源包含符号链接 {rel.as_posix()!r}(拒绝复制)")
        if not f.is_file():
            if f.is_dir():
                continue
            raise BuilderRunnerError(
                f"{label} 源包含非普通文件 {rel.as_posix()!r}"
                f"(设备/FIFO 等被拒绝)")
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)


def _tree_manifest_from_staging(staging: Path) -> dict[str, str]:
    return _scan_tree_files(staging)


def _verify_staged_files(
        staged_files: dict[str, str], expected: dict[str, Any], label: str,
) -> None:
    expected_files = {
        e["path"]: e["sha256"] for e in (expected.get("files") or [])}
    extra = sorted(set(staged_files) - set(expected_files))
    missing = sorted(set(expected_files) - set(staged_files))
    changed = sorted(
        k for k in set(expected_files) & set(staged_files)
        if expected_files[k] != staged_files[k])
    if extra or missing or changed:
        raise BuilderRunnerError(
            f"staging {label} 与 identity 不一致(已脱敏:fail closed,"
            f"Builder 启动之前拦截):额外文件 {extra[:8]},缺失文件 "
            f"{missing[:8]},内容变化 {changed[:8]}(TOCTOU 防护:"
            f"复制与执行之间被篡改即拒绝)")


def assemble_builder_staging(
        builder_root: Path | str, base_dir: Path | str,
) -> Path:
    src = Path(builder_root)
    if not src.is_dir():
        raise BuilderRunnerError(
            f"builder package root 不存在或不是目录: {src.name}(已脱敏)")
    dst = Path(base_dir) / "builder_pkg"
    _copy_tree(src, dst, label="builder package")
    return dst


def assemble_runtime_staging(base_dir: Path | str) -> Path:
    import rl_builder_runtime

    src = Path(rl_builder_runtime.__file__).parent
    dst_root = Path(base_dir) / "runtime"
    _copy_tree(src, dst_root / "rl_builder_runtime", label="builder runtime")
    return dst_root


# ------------------------------------------------------------ bundle 池
class RuntimeBundlePool:
    """每条正式链路一个内容寻址 bundle staging(链内复用,跨链重建)。

    组装键 = builder package 内容 + runtime 内容 + conda env 路径;
    相同键的连续请求复用已组装 staging(exec 前挂载视图复验 + 运行后
    复验覆盖链内 TOCTOU)。staging 位于与 conda env 同文件系统的
    $HOME/.cache/rl_builder_bundles(硬链接要求;不受 /tmp 清理)。
    """

    def __init__(self, root: Path | str | None = None, *, jobs: int = 4):
        self.root = Path(root) if root else DEFAULT_BUNDLE_ROOT
        self.jobs = jobs
        self._cache: dict[tuple, dict] = {}
        self._counter = 0

    def bundle_for(self, *, env_root: Path | str,
                   runtime_src: Path | str,
                   builder_pkg_root: Path | str) -> dict:
        import rl_builder_runtime
        from rl_builder_runtime.bundle import (
            assemble_runtime_bundle,
            bundle_manifest_digest,
        )

        rt_files = _scan_tree_files(Path(runtime_src))
        bp_files = _scan_tree_files(Path(builder_pkg_root))
        key = (str(Path(env_root).resolve()),
               bundle_manifest_digest({"rt": rt_files, "bp": bp_files}))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        self._counter += 1
        staging = self.root / f"chain-{int(time.monotonic() * 1000)}-" \
                              f"{os.getpid()}-{self._counter}"
        staging.parent.mkdir(parents=True, exist_ok=True)
        try:
            info = assemble_runtime_bundle(
                env_root=env_root, staging_root=staging,
                runtime_src=runtime_src,
                builder_pkg_root=builder_pkg_root,
                hostname=BUILDER_WORKER_HOSTNAME, jobs=self.jobs)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        entry = {"staging": staging, "manifest": info["manifest"],
                 "digest": info["digest"], "meta": info["meta"]}
        self._cache[key] = entry
        return entry

    def verify_staging(self, entry: dict) -> dict:
        """链内复验(staging 视图;运行后调用)。"""
        from rl_builder_runtime.bundle import verify_runtime_bundle

        manifest = {k: v for k, v in dict(entry["manifest"]).items()
                    if k != "manifest_digest"}
        return verify_runtime_bundle(
            entry["staging"], manifest, jobs=self.jobs,
            expect_digest=entry["digest"])

    def cleanup(self, entry: dict | None = None) -> None:
        targets = [entry["staging"]] if entry is not None else \
            [v["staging"] for v in self._cache.values()]
        for t in targets:
            shutil.rmtree(t, ignore_errors=True)
        if entry is None:
            self._cache.clear()
        else:
            self._cache = {k: v for k, v in self._cache.items()
                           if v["staging"] != entry["staging"]}


#: 进程内共享池(precommit 双跑 + 重放复用同一 bundle;测试隔离用
#: bundle_pool_override 注入)
_SHARED_POOL: RuntimeBundlePool | None = None


def shared_bundle_pool(jobs: int = 4) -> RuntimeBundlePool:
    global _SHARED_POOL
    if _SHARED_POOL is None:
        _SHARED_POOL = RuntimeBundlePool(jobs=jobs)
    return _SHARED_POOL


def _default_env_root(python: str) -> Path:
    py = Path(python).resolve()
    env_root = py.parent.parent  # <env>/bin/python -> <env>
    if not (env_root / "lib" / "python3.11").is_dir():
        raise BuilderRunnerError(
            "python 不在 conda env 布局内(<env>/bin/python3.11 + "
            "<env>/lib/python3.11;2.6.0i bundle 依赖该布局)")
    return env_root


# ------------------------------------------------------------ launcher
def _fixed_exec_env(process_tree_policy: str) -> dict[str, str]:
    """Runner 的固定白名单环境(清洗:只含受控键;路径全部 canonical)。"""
    return {
        "PATH": "/bin",
        "PYTHONHOME": "/",
        "PYTHONPATH": "/runtime",
        "HOME": "/scratch",
        "TMPDIR": "/scratch",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "RL_BUILDER_PROCESS_TREE": process_tree_policy,
    }


def launch_builder_runner(
        profile: BuilderRunnerProfile, *,
        bundle_entry: dict,
        entrypoint_module: str, entrypoint_qualname: str,
        worker_info_fd: int | None = None,
) -> subprocess.Popen:
    """fork-launcher 启动(纯 syscall bootstrap;无外部沙箱命令)。"""
    staging = Path(bundle_entry["staging"])
    exec_argv = [
        "/bin/python3.11", "-m", "rl_builder_runtime.runner",
        "/builder_pkg", entrypoint_module, entrypoint_qualname,
    ]
    exec_env = _fixed_exec_env(profile.process_tree_policy)
    config = {
        "bundle_root": str(staging),
        "hostname": BUILDER_WORKER_HOSTNAME,
        "rlimits": dict(profile.rlimits),
        "exec_argv": exec_argv,
        "exec_env": exec_env,
    }
    if worker_info_fd is not None:
        config["worker_info_fd"] = int(worker_info_fd)
    pass_fds = (int(worker_info_fd),) if worker_info_fd is not None else ()
    argv = [sys.executable, "-m", "rl_builder_runtime.bootstrap",
            json.dumps(config, separators=(",", ":"),
                       ensure_ascii=False)]
    # launcher 进程需要导入 rl_builder_runtime:显式注入其所在目录的
    # 绝对路径(宿主 PYTHONPATH 可能是相对路径,子进程 cwd 变化后失效)
    import rl_builder_runtime

    rt_parent = str(Path(rl_builder_runtime.__file__).resolve()
                    .parent.parent)
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = rt_parent
    return subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=child_env, text=True,
        bufsize=1, cwd=str(staging.parent), close_fds=True,
        pass_fds=pass_fds, start_new_session=True,
    )


def _readline_with_timeout(fd: int, *, timeout: float,
                           max_bytes: int, extra_fds: list[int] = (),
                           on_fd_data=None) -> str:
    import select as _select

    deadline = time.monotonic() + float(timeout)
    buf = ""
    open_extra = list(extra_fds)
    while "\n" not in buf:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BuilderRunnerError(
                f"Builder Runner 响应超时(> {timeout}s):fail closed,"
                f"不采信部分输出")
        ready, _, _ = _select.select([fd] + open_extra, [], [], remaining)
        for x in list(ready):
            if x == fd:
                continue
            data = os.read(x, 64)
            if data:
                if on_fd_data is not None:
                    on_fd_data(x, data)
            else:
                open_extra.remove(x)
        if fd not in ready:
            continue
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="replace")
        if len(buf.encode("utf-8")) > max_bytes:
            raise BuilderRunnerError(
                f"Builder Runner 响应超过 {max_bytes} 字节上限:"
                f"协议违规 fail closed")
    line, _, _ = buf.partition("\n")
    if len(line.encode("utf-8")) > max_bytes:
        raise BuilderRunnerError(
            f"Builder Runner 响应单行超过 {max_bytes} 字节上限:"
            f"协议违规 fail closed")
    return line


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), 9)
    except OSError:
        proc.kill()


# ------------------------------------------------- quiesce 外部实测(D)
def _quiesce_snapshot(worker_pid: int) -> dict:
    """Worker 打印 quiesce 后、ACK 前的外部 /proc 实测(可信侧)。"""
    snap: dict[str, Any] = {}
    status: dict[str, str] = {}
    with open(f"/proc/{worker_pid}/status", encoding="utf-8") as fh:
        for line in fh:
            k, _, v = line.partition(":")
            status[k] = v.strip()
    snap["seccomp_mode"] = int(status.get("Seccomp", "0") or 0)
    snap["no_new_privs"] = int(status.get("NoNewPrivs", "0") or 0)
    nspid = [int(x) for x in (status.get("NSpid") or "").split()]
    snap["nspid"] = nspid
    snap["worker_pidns_pid"] = nspid[-1] if nspid else None
    snap["threads"] = sorted(os.listdir(f"/proc/{worker_pid}/task"))
    snap["thread_count"] = len(snap["threads"])
    task_comms = []
    for tid in snap["threads"]:
        try:
            with open(f"/proc/{worker_pid}/task/{tid}/comm",
                      encoding="utf-8") as fh:
                task_comms.append(fh.read().strip())
        except OSError:
            task_comms.append("<gone>")
    snap["task_comms"] = sorted(task_comms)
    children: list[str] = []
    for tid in snap["threads"]:
        try:
            with open(f"/proc/{worker_pid}/task/{tid}/children",
                      encoding="utf-8") as fh:
                children.extend(fh.read().split())
        except OSError:
            continue
    snap["child_pids"] = sorted(set(children))
    loaded: list[str] = []
    with open(f"/proc/{worker_pid}/maps", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 6:
                continue
            path = parts[5]
            if not path.startswith("/"):
                continue
            if path not in loaded:
                loaded.append(path)
    snap["mapped_paths"] = sorted(loaded)
    return snap


def _native_closure(snap: dict, bundle_entry: dict) -> list[dict]:
    """A2:实际加载 .so 全部绑定 bundle manifest 内容与归属。"""
    from rl_builder_runtime.bundle import sha256_file

    manifest = bundle_entry["manifest"]
    manifest_files = {e["path"]: e["sha256"]
                      for e in manifest["entries"] if e.get("type") == "file"}
    staging = Path(bundle_entry["staging"])
    entries: list[dict] = []
    for path in snap["mapped_paths"]:
        if not (path.endswith(".so") or ".so." in os.path.basename(path)):
            continue
        rel = path[1:] if path.startswith("/") else path
        expected = manifest_files.get(rel)
        if expected is None:
            raise BuilderRunnerError(
                f"加载了 bundle manifest 外的 native library "
                f"{os.path.basename(path)!r}(fail closed;路径已脱敏)")
        actual = sha256_file(staging / rel)
        if actual != expected:
            raise BuilderRunnerError(
                f"native library {os.path.basename(path)!r} 字节与 "
                f"bundle manifest 不一致(TOCTOU;fail closed)")
        entries.append({"path": path, "sha256": actual,
                        "origin": "runtime-bundle"})
    return entries


# ------------------------------------------------- EDIC 校验与合并(D2)
def check_effective_deterministic_input_report(
        report: Any, profile: BuilderRunnerProfile,
        *, bundle_digest: str | None = None,
) -> dict[str, Any]:
    """D2:密闭确定性输入报告的不变量校验(降级即拒绝)。"""
    from rl_builder_runtime import PRIVATE_DEV_NODES
    from rl_builder_runtime.runner import (
        EDIC_FORMAT as FMT,
        SECCOMP_PROCESS_POLICY,
        seccomp_filter_digest,
    )

    if not isinstance(report, dict):
        raise BuilderRunnerError("Runner 响应缺确定性输入报告(fail closed)")
    if report.get("format") != FMT:
        raise BuilderRunnerError(
            f"确定性输入报告 format 必须是 {FMT!r}(收到 "
            f"{report.get('format')!r};0h esb- 报告已不足以表达输入闭包)")
    if report.get("pidns_self_pid") != 1:
        raise BuilderRunnerError("Worker 在 pidns 内不是 pid 1(拒绝)")
    if report.get("root_readonly") is not True:
        raise BuilderRunnerError("bundle 根不是只读(拒绝)")
    if report.get("uts_hostname") != BUILDER_WORKER_HOSTNAME:
        raise BuilderRunnerError("UTS hostname 未固定(拒绝)")
    if report.get("netns_interfaces") != ["lo"]:
        raise BuilderRunnerError(
            "网络 namespace 隔离缺失:接口不止 lo(拒绝)")
    proc = report.get("proc") or {}
    if proc.get("mounted") is not False \
            or proc.get("self_status") != "ENOENT" \
            or proc.get("listing_empty") is not True:
        raise BuilderRunnerError("/proc 对 Builder 不可见未被证明(拒绝)")
    dev = report.get("dev") or {}
    if not dev.get("urandom_regular_file"):
        raise BuilderRunnerError(
            "/dev/urandom 不是确定性普通文件(真实熵设备存在;拒绝)")
    for node in PRIVATE_DEV_NODES:
        if node not in (dev.get("nodes") or []):
            raise BuilderRunnerError(f"/dev 缺少必要节点 {node}(拒绝)")
    if set(dev.get("nodes") or []) - {
            *PRIVATE_DEV_NODES, "shm", "urandom", "random"}:
        raise BuilderRunnerError(
            f"/dev 含未声明节点: {dev.get('nodes')}(拒绝)")
    probes = report.get("probes") or {}
    for probe in ("host_usr", "host_home", "host_etc_hostname",
                  "host_sys", "host_oldroot_usr"):
        if (probes.get(probe) or {}).get("result") != "ENOENT":
            raise BuilderRunnerError(
                f"宿主路径探针 {probe} 未返回 ENOENT(pivot 未生效;拒绝)")
    if report.get("process_tree_policy") != profile.process_tree_policy:
        raise BuilderRunnerError(
            f"报告进程树策略 {report.get('process_tree_policy')!r} 与 "
            f"profile {profile.process_tree_policy!r} 不一致(拒绝)")
    sup = report.get("supervisor") or {}
    if sup.get("worker_pidns_pid") != 1:
        raise BuilderRunnerError("外部 NSpid 实测 Worker 不是 pidns pid 1"
                                 "(拒绝)")
    if sup.get("child_process_count") != 0:
        raise BuilderRunnerError(
            f"quiesce 实测存在后代进程: {sup.get('child_process_count')}"
            f"(拒绝)")
    if profile.process_tree_policy == SINGLE_PROCESS:
        # 密闭策略(正式链):seccomp/时钟/熵/线程全部强制
        if sup.get("seccomp_mode") != 2:
            raise BuilderRunnerError(
                f"seccomp 模式异常: {sup.get('seccomp_mode')}"
                f"(必须为 filter 模式 2;拒绝)")
        if sup.get("no_new_privs") != 1:
            raise BuilderRunnerError("no_new_privs!=1:沙箱降级(拒绝)")
        if report.get("thread_policy") == THREAD_POLICY_FORBIDDEN \
                and sup.get("thread_count") != 1:
            raise BuilderRunnerError(
                f"线程静止证明失败:quiesce 实测 {sup.get('thread_count')} "
                f"个任务(禁止线程策略下必须恰为 1;拒绝)")
        clock = report.get("clock") or {}
        vdso = clock.get("vdso") or {}
        if vdso.get("mode") != "frozen-stub" \
                and vdso.get("vdso") != "absent-at-exec":
            raise BuilderRunnerError(
                "vDSO 未冻结(真实时钟路径存活;拒绝)")
        behavior = clock.get("behavior") or {}
        if behavior.get("time_time") != 0.0 \
                or behavior.get("datetime_now_year") != 1970 \
                or behavior.get("time_monotonic") != 0.0:
            raise BuilderRunnerError("冻结时钟行为探针失败(拒绝)")
        if (clock.get("pr_set_tsc_rc")) != 0:
            raise BuilderRunnerError("PR_SET_TSC 未生效(拒绝)")
        for key, val in (clock.get("raw_syscall") or {}).items():
            if val != f"ERRNO{errno.EPERM}":
                raise BuilderRunnerError(
                    f"时钟 raw syscall {key} 未被拒绝({val};拒绝)")
        entropy = report.get("entropy") or {}
        if entropy.get("getrandom") != f"ERRNO{errno.EPERM}":
            raise BuilderRunnerError("getrandom 未被拒绝(拒绝)")
        if entropy.get("dev_urandom_deterministic") is not True:
            raise BuilderRunnerError("熵源不是确定性承诺文件(拒绝)")
        seccomp = report.get("seccomp") or {}
        if seccomp.get("filter_hash") != seccomp_filter_digest():
            raise BuilderRunnerError("seccomp filter 摘要与期望不符(拒绝)")
        if seccomp.get("policy") != SECCOMP_PROCESS_POLICY:
            raise BuilderRunnerError("seccomp 策略载荷不符(拒绝)")
        if (probes.get("fork_denied") or {}).get("result") != \
                f"ERRNO{errno.EPERM}":
            raise BuilderRunnerError("fork 探针未被拒绝(拒绝)")
        if (probes.get("exec_denied") or {}).get("result") != \
                f"ERRNO{errno.EPERM}":
            raise BuilderRunnerError("exec 探针未被拒绝(拒绝)")
        if (probes.get("clone_thread_denied") or {}).get("result") != \
                f"ERRNO{errno.EPERM}":
            raise BuilderRunnerError("clone(线程)探针未被拒绝(拒绝)")
    bundle = (report.get("runtime_bundle") or {})
    if bundle_digest is not None \
            and bundle.get("manifest_digest") != bundle_digest:
        raise BuilderRunnerError(
            "EDIC 的 bundle 摘要与本次链路不一致(拒绝)")
    verify = sup.get("bundle_verification") or {}
    if verify.get("digest") != bundle.get("manifest_digest"):
        raise BuilderRunnerError(
            "运行后 bundle 复验摘要与 EDIC 不一致(TOCTOU;拒绝)")
    seccomp = report.get("seccomp") or {}
    return {
        "deterministic_input_hash": deterministic_input_report_hash(report),
        "seccomp_filter_hash": seccomp.get("filter_hash"),
        "runtime_bundle_hash": bundle.get("manifest_digest"),
        "kernel_release": (report.get("environment") or {}).get(
            "uname_release"),
    }


def deterministic_input_report_hash(report: dict) -> str:
    return "edi-" + hashlib.sha256(json.dumps(
        report, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


# ------------------------------------------------------------ 单次运行
def run_isolated_builder_run(
        identity: Any, request: dict[str, Any], *,
        builder_root: Path | str,
        profile: BuilderRunnerProfile | None = None,
        python: str | None = None,
        staging_base: Path | str | None = None,
        keep_staging: bool = False,
        bundle_pool: RuntimeBundlePool | None = None,
        skip_post_run_verify: bool = False,
) -> dict[str, Any]:
    """一次完整的密闭 Runner 构建(私有 Builder 专用;2.6.0i 语义)。

    序列:staging 复制与双对账 -> bundle 组装(链内复用)-> fork
    launcher 沙箱启动(挂载后全量复验在 Worker exec 前完成)-> 发送
    冻结请求 -> quiesce 外部实测 -> ACK -> final -> EDIC 不变量校验
    -> 锁 v3 组装(导入闭包 + native 闭包 + 线程静止 + bundle 绑定)
    -> 运行后 staging 全量复验 -> 返回 run record。
    """
    import rl_builder_runtime
    from rl_builder_runtime import BUILDER_WORKER_PROTOCOL
    from rl_curriculum.builder_provenance import (
        access_summary_hash, attempt_log_hash, runtime_lock_hash,
    )
    from rl_curriculum.exam_pack import ExamPack

    check_frozen_build_request(request)
    if request.get("mode") != BUILDER_RUN_MODE_EXECUTION:
        raise BuilderRunnerError(
            "隔离 Runner 只接受 builder_execution 请求"
            "(mock_payload_assembly 属于公开组装通道,不得进入本 Runner)")
    profile = profile or BuilderRunnerProfile()
    tree = dict((identity.manifest or {}).get("package_tree") or {})
    if not tree:
        raise BuilderRunnerError("identity 缺少 package_tree(无法对账)")
    own_cleanup = staging_base is None
    base = Path(staging_base) if staging_base is not None else Path(
        tempfile.mkdtemp(prefix="rl-builder-run-"))
    base.mkdir(parents=True, exist_ok=True)
    (base / "scratch").mkdir(parents=True, exist_ok=True)
    pool = bundle_pool or shared_bundle_pool(profile.bundle_jobs)
    try:
        builder_staging = assemble_builder_staging(builder_root, base)
        _verify_staged_files(
            _tree_manifest_from_staging(builder_staging), tree,
            label="builder package")
        runtime_root = assemble_runtime_staging(base)
        expected_rt = builder_runtime_manifest()
        staged_rt_files = _tree_manifest_from_staging(
            runtime_root / "rl_builder_runtime")
        expected_rt_files = {
            k: v for k, v in (expected_rt.get("files") or {}).items()}
        _verify_staged_files(
            staged_rt_files, {"files": [
                {"path": k, "sha256": v}
                for k, v in expected_rt_files.items()]},
            label="builder runtime")
        # 2.6.0i:内容寻址 bundle(env 硬链接 + runtime + builder_pkg)
        bundle_entry = pool.bundle_for(
            env_root=_default_env_root(python or sys.executable),
            runtime_src=runtime_root / "rl_builder_runtime",
            builder_pkg_root=builder_staging)
        info_r, info_w = os.pipe()
        proc = launch_builder_runner(
            profile, bundle_entry=bundle_entry,
            entrypoint_module=str(tree.get("entrypoint_module") or ""),
            entrypoint_qualname=str(
                tree.get("entrypoint_qualname") or ""),
            worker_info_fd=info_w)
        os.close(info_w)
        state = {"worker_pid": ""}

        def _on_info(fd: int, data: bytes) -> None:
            state["worker_pid"] = data.decode(errors="replace").strip()

        quiesce: dict | None = None
        resp: dict | None = None
        try:
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(
                request, separators=(",", ":"),
                ensure_ascii=False) + "\n")
            proc.stdin.flush()
            line1 = _readline_with_timeout(
                proc.stdout.fileno(),
                timeout=profile.run_timeout_seconds,
                max_bytes=profile.response_max_bytes,
                extra_fds=[info_r], on_fd_data=_on_info)
            if not line1.strip():
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    _kill_tree(proc)
                tail = ""
                try:
                    if proc.stderr is not None:
                        tail = proc.stderr.read(4096) or ""
                except Exception:  # noqa: BLE001
                    tail = ""
                raise BuilderRunnerError(
                    "Builder Worker 无响应即退出(沙箱布置或启动失败;"
                    f"stderr 尾部: {tail[-500:]!r};fail closed)")
            first = json.loads(line1)
            if first.get("protocol") != BUILDER_WORKER_PROTOCOL:
                raise BuilderRunnerError(
                    f"Runner 响应协议不符(期望 {BUILDER_WORKER_PROTOCOL!r},"
                    f"收到 {first.get('protocol')!r};fail closed)")
            if first.get("phase") == "quiesce":
                if not state["worker_pid"].isdigit():
                    raise BuilderRunnerError(
                        "未收到 Worker 全局 pid(worker-info 管道缺失;"
                        "无法做外部静止实测;fail closed)")
                quiesce = _quiesce_snapshot(int(state["worker_pid"]))
                proc.stdin.write("ACK\n")
                proc.stdin.flush()
                line2 = _readline_with_timeout(
                    proc.stdout.fileno(),
                    timeout=min(60.0, profile.run_timeout_seconds),
                    max_bytes=profile.response_max_bytes)
                resp = json.loads(line2)
            else:
                resp = first
        except BrokenPipeError as exc:
            raise BuilderRunnerError(
                "Builder Runner 通信失败(管道断裂;已脱敏)") from exc
        except BuilderRunnerError:
            _kill_tree(proc)
            raise
        finally:
            os.close(info_r)
            stderr_tail = ""
            try:
                proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                proc.wait(timeout=10)
            try:
                if proc.stderr is not None:
                    stderr_tail = proc.stderr.read(4096) or ""
            except Exception:  # noqa: BLE001 - 诊断信息尽力读取
                stderr_tail = ""
        if resp is None or resp.get("protocol") != BUILDER_WORKER_PROTOCOL:
            raise BuilderRunnerError(
                "Builder Runner 响应缺失或协议不符(已脱敏;"
                f"stderr 尾部: {stderr_tail[-200:]!r})")
        if resp.get("phase") != "final":
            raise BuilderRunnerError(
                f"Runner 最终响应 phase 异常: {resp.get('phase')!r}")
        access = dict(resp.get("access_summary")
                      or first.get("access_summary") or {})
        if resp.get("status") != "ok":
            raise BuilderRunnerError(
                f"Builder Runner 构建失败(stage={resp.get('stage')!r},"
                f"error={str(resp.get('error'))[:300]};已脱敏)")
        if quiesce is None:
            raise BuilderRunnerError(
                "成功响应未经 quiesce 静止实测(协议违规;fail closed)")
        result = resp.get("build_result")
        lock_parts = dict(first.get("lock_parts") or {})
        edic = dict(first.get("edic") or {})
        if not isinstance(result, dict) or not lock_parts \
                or not edic:
            raise BuilderRunnerError(
                "Runner 响应缺 build_result/lock_parts/edic"
                "(已脱敏;fail closed)")
        if lock_parts.get("format") != RUNTIME_LOCK_FORMAT_V3:
            raise BuilderRunnerError(
                f"运行时锁必须是 {RUNTIME_LOCK_FORMAT_V3!r}(收到 "
                f"{lock_parts.get('format')!r};0h v2 锁不再被接受)")
        # 运行后 bundle 全量复验(E10:硬链接别名就地改写在此被发现)
        if skip_post_run_verify:
            bundle_verify = {"digest": bundle_entry["digest"],
                             "skipped": "demo-profile"}
        else:
            try:
                bundle_verify = pool.verify_staging(bundle_entry)
            except Exception as exc:  # noqa: BLE001
                raise BuilderRunnerError(
                    f"运行后 bundle 复验失败: {exc}") from exc
        # EDIC 合并(外部实测 + 复验)并校验
        edic["runtime_bundle"] = {
            "manifest_digest": bundle_entry["digest"],
            "file_count": sum(1 for e in bundle_entry["manifest"]["entries"]
                              if e.get("type") == "file"),
            "syslib_sonames":
                bundle_entry["manifest"].get("syslib_sonames") or [],
            "hostname": BUILDER_WORKER_HOSTNAME,
        }
        edic["supervisor"] = {
            "seccomp_mode": quiesce["seccomp_mode"],
            "no_new_privs": quiesce["no_new_privs"],
            "worker_pidns_pid": quiesce["worker_pidns_pid"],
            "thread_count": quiesce["thread_count"],
            "task_comms": quiesce["task_comms"],
            "child_process_count": len(quiesce["child_pids"]),
            "native_libraries": _native_closure(
                quiesce, bundle_entry),
            "bundle_verification": {
                k: v for k, v in bundle_verify.items()
                if k in ("verified_files", "digest", "verified_symlinks")},
        }
        edic_checks = check_effective_deterministic_input_report(
            edic, profile, bundle_digest=bundle_entry["digest"])
        try:
            pack = ExamPack.from_json(json.dumps(result.get("pack")))
            pack_hash = pack.pack_hash()
        except Exception as exc:  # noqa: BLE001
            raise BuilderRunnerError(
                f"Runner 产物的 pack 无法解析为 ExamPack: "
                f"{type(exc).__name__}: {exc}") from exc
        try:
            log = canonicalize_attempt_log(
                result.get("attempt_log"), output_pack_hash=pack_hash,
                attempt_policy=dict(
                    request.get("attempt_policy") or {}))
        except BuilderProvenanceError as exc:
            raise BuilderRunnerError(str(exc)) from exc
        # 锁 v3 组装(worker 部分 + 外部实测)
        # 子进程计数取 max(外部实测后代, 审计尝试):短命子进程在 quiesce
        # 前退出时由审计计数兜底(沿 0h 语义;正式链两者都必须为 0)
        child_count = max(len(quiesce["child_pids"]),
                          int(lock_parts.get("child_process_attempts")
                              or 0))
        lock = dict(lock_parts)
        lock["format"] = RUNTIME_LOCK_FORMAT_V3
        lock["child_process_count"] = int(child_count)
        lock["exec_count"] = int(lock_parts.get("exec_attempts") or 0)
        lock["native_libraries"] = edic["supervisor"]["native_libraries"]
        lock["thread_state"] = {
            "policy": edic["thread_policy"],
            "thread_count_at_quiesce": quiesce["thread_count"],
            "task_comms": quiesce["task_comms"],
        }
        lock["runtime_bundle"] = dict(edic["runtime_bundle"])
        lock["clock_policy"] = {
            "vdso": edic["clock"]["vdso"],
            "pr_set_tsc_rc": edic["clock"]["pr_set_tsc_rc"],
            "raw_syscall": edic["clock"]["raw_syscall"],
            "behavior": edic["clock"]["behavior"],
        }
        lock["entropy_policy"] = {
            "getrandom": edic["entropy"]["getrandom"],
            "dev_urandom_deterministic":
                edic["entropy"]["dev_urandom_deterministic"],
            "deterministic_entropy_sha256_prefix":
                edic["dev"]["deterministic_entropy_sha256_prefix"],
        }
        lock["seccomp_policy"] = edic["seccomp"]["policy"]
        lock["seccomp_filter_hash"] = edic["seccomp"]["filter_hash"]
        lock["worker_pidns_pid"] = quiesce["worker_pidns_pid"]
        from rl_curriculum.builder_provenance import (
            check_runtime_lock_against_static,
        )

        try:
            check_runtime_lock_against_static(
                lock, list((identity.manifest or {}).get(
                    "external_dependencies") or []),
                require_single_process=(
                    profile.process_tree_policy == SINGLE_PROCESS),
                verify_content=(
                    profile.process_tree_policy == SINGLE_PROCESS))
        except BuilderProvenanceError as exc:
            raise BuilderRunnerError(
                f"隔离 Builder Runner 运行失败: {exc}") from exc
        return {
            "mode": BUILDER_RUN_MODE_EXECUTION,
            "status": "ok",
            "pack": pack,
            "pack_hash": pack_hash,
            "attempt_log": log,
            "attempt_log_hash": attempt_log_hash(log),
            "runtime_lock": lock,
            "runtime_lock_hash": runtime_lock_hash(lock),
            "runner_code_hash": builder_runtime_tree_hash(expected_rt),
            "sandbox_profile_hash": profile.profile_hash(),
            "staged_tree_hash": str(tree.get("tree_hash") or ""),
            "access_summary": access,
            "access_summary_hash": access_summary_hash(access),
            "deterministic_input_report": edic,
            "deterministic_input_hash":
                edic_checks["deterministic_input_hash"],
            "runtime_bundle_hash": bundle_entry["digest"],
            "process_tree_policy": lock.get("process_tree_policy"),
            "thread_policy": lock.get("thread_policy"),
            "child_process_count": int(
                lock.get("child_process_count") or 0),
            "child_process_attempts": int(
                lock_parts.get("child_process_attempts") or 0),
            "exec_count": int(lock.get("exec_count") or 0),
            "runner_isolation": "isolated_process",
            "error": None,
        }
    finally:
        if own_cleanup and not keep_staging:
            shutil.rmtree(base, ignore_errors=True)
