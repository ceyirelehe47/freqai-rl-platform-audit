"""隔离 Builder Runner 启动器(阶段 2.6.0h,评估主进程侧)。

主评估进程对私有 Builder 只允许(B1,沿 0g):

- 读取并哈希 Builder 文件(builder package tree manifest);
- AST 静态检查(builder_identity.validate_builder_entrypoint 静态部分);
- 创建隔离 Runner(本模块);
- 发送规范化 request(builder-build-request-v3);
- 接收规范化 result(builder-runner-worker-v2 响应)。

阶段 2.6.0h 沙箱层次(bootstrap 内布置,deny 降级即拒绝):

    unshare --user --map-root-user --mount --pid --mount-proc --fork --net
      -> pivot_root 最小 rootfs(宿主路径不可命名;/sys 不存在;
         /etc 空;私有最小 /dev + 独立 /dev/shm tmpfs;私有 /tmp;
         全新 /proc;conda env 与 /usr 按原路径只读挂载)
      -> Landlock deny-by-default(staging ro/scratch rw//proc 最小文件)
      -> rlimits(NPROC 附加防线)
      -> exec runner(seccomp 进程树策略:fork/clone3/exec/ptrace/...
         全拒,仅 CLONE_THREAD 线程;A1)
      -> Effective Sandbox Report(实际生效状态 + 行为探针;C1)

启动序列强制 TOCTOU 防护(B3,沿 0g):builder package 复制到匿名
staging(拒绝 symlink/设备;排除 __pycache__/*.pyc)-> 对 staging
重算 tree manifest 与 Provider identity(npb-)逐字节对账 ->
rl_builder_runtime 复制并对账(rtb-)-> 执行刚验证过的副本。
"""

from __future__ import annotations

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

UNSHARE_BIN = "/usr/bin/unshare"

MAX_RUNNER_RESPONSE_BYTES = 32 * 1024 * 1024

SANDBOX_REPORT_FORMAT = "builder-effective-sandbox-report-v1"
SINGLE_PROCESS = "single_builder_process"
ALLOW_DESCENDANTS = "allow_descendants"


class BuilderRunnerError(RuntimeError):
    """隔离 Builder Runner 错误/协议违规/超时/沙箱降级(fail closed)。"""


# ---------------------------------------------------------------- profile
@dataclass(frozen=True)
class BuilderRunnerProfile:
    """Builder Runner 沙箱配置(可哈希,进入 Builder Run Evidence)。

    阶段 2.6.0h(v2):绑定 seccomp 进程树策略、私有最小 /dev、/proc
    最小文件集与 pivot_root 最小 rootfs 模板。install_seccomp=False
    或 process_tree_policy=allow_descendants 仅供攻击演示测试——
    evidence 校验要求 seccomp 实际生效与单进程边界,此类 run 无法
    进入正式材料。
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
    #: A1:seccomp 进程树策略(正式链必须 True)
    install_seccomp: bool = True
    #: D1:进程树边界(正式链必须 single_builder_process)
    process_tree_policy: str = SINGLE_PROCESS

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
        from rl_builder_runtime import PRIVATE_DEV_NODES, PROC_MINIMAL_FILES
        from rl_builder_runtime.runner import (
            SECCOMP_PROCESS_POLICY,
            seccomp_filter_digest,
        )

        return {
            "format": "builder-runner-profile-v2",
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
            "filesystem_view": {
                "pivot_root_minimal_rootfs": True,
                "private_dev_nodes": list(PRIVATE_DEV_NODES),
                "private_dev_shm_tmpfs": True,
                "host_etc_visible": False,
                "host_sys_exists": False,
                "private_tmp": True,
                "fresh_proc": True,
            },
            "proc_minimal_files": list(PROC_MINIMAL_FILES),
            "env_whitelist": [
                "PATH", "PYTHONPATH", "LANG", "LC_ALL", "TZ",
                "PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE", "HOME",
                "TMPDIR", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS", "RL_BUILDER_PROCESS_TREE",
                "RL_SB_LANDLOCK_ABI", "RL_SB_LANDLOCK_HANDLED",
                "RL_SB_LANDLOCK_GRANTS", "RL_SB_MOUNTOPTS",
            ],
            "fixed_env": {
                "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
                "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
                "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
            },
        }

    def profile_hash(self) -> str:
        return "brp-" + hashlib.sha256(
            json.dumps(self.canonical_payload(), sort_keys=True,
                       separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")).hexdigest()


def _fixed_exec_env(staging_root: str, python: str,
                    process_tree_policy: str) -> dict[str, str]:
    """Runner 的固定白名单环境(清洗:只含受控键,B4)。"""
    return {
        "PATH": f"{Path(python).resolve().parent}:/usr/bin:/bin",
        "PYTHONPATH": staging_root,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "RL_BUILDER_PROCESS_TREE": process_tree_policy,
    }


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


# ------------------------------------------------------------ launcher
def _default_read_exec(python: str) -> list[str]:
    py = Path(python).resolve()
    env_root = py.parent.parent  # <env>/bin/python -> <env>
    read_exec = [str(env_root)]
    for d in ("/usr",):
        if os.path.isdir(d):
            read_exec.append(d)
    return read_exec


def launch_builder_runner(
    profile: BuilderRunnerProfile, *,
    base_dir: Path | str,
    entrypoint_module: str, entrypoint_qualname: str,
    python: str | None = None,
    unshare_bin: str = UNSHARE_BIN,
    expected_runtime_manifest: dict[str, Any] | None = None,
) -> subprocess.Popen:
    """在系统级沙箱内启动 Builder Runner worker(0h 沙箱层次)。"""
    if not os.path.isfile(unshare_bin):
        raise BuilderRunnerError(
            f"缺少 unshare({unshare_bin}):无法建立 Builder 系统级沙箱,"
            f"正式构建不得降级为普通子进程或进程内执行")
    py = str(Path(python or sys.executable).resolve())
    base = Path(base_dir)
    staging_root = str(base / "runtime")
    exec_argv = [
        py, "-m", "rl_builder_runtime.runner",
        str(base / "builder_pkg"), entrypoint_module, entrypoint_qualname,
    ]
    exec_env = _fixed_exec_env(
        staging_root, py, profile.process_tree_policy)
    config = {
        "workdir": str(base.resolve()),
        # read_exec:conda env 根 + /usr(pivot 后按原路径只读挂载;
        # 其余一切宿主路径不可命名)
        "read_exec": [d for d in _default_read_exec(py)
                      if os.path.exists(d)],
        "rlimits": dict(profile.rlimits),
        "exec_argv": exec_argv,
        "exec_env": exec_env,
    }
    config_json = json.dumps(config, separators=(",", ":"),
                             ensure_ascii=False)
    argv = [
        unshare_bin,
        "--user", "--map-root-user",
        "--mount", "--pid", "--mount-proc", "--fork", "--net",
        py, "-m", "rl_builder_runtime.bootstrap", config_json,
    ]
    parent_env = _fixed_exec_env(
        staging_root, py, profile.process_tree_policy)
    return subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=parent_env, text=True, bufsize=1,
        cwd=str(base / "scratch") if (base / "scratch").is_dir()
        else str(base),
        close_fds=True,
    )


def _readline_with_timeout(proc: subprocess.Popen, *, timeout: float,
                           max_bytes: int) -> str:
    import select as _select

    deadline = time.monotonic() + float(timeout)
    buf = ""
    fd = proc.stdout.fileno()
    while "\n" not in buf:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            proc.kill()
            raise BuilderRunnerError(
                f"Builder Runner 响应超时(> {timeout}s):fail closed,"
                f"不采信部分输出")
        ready, _, _ = _select.select([fd], [], [], remaining)
        if not ready:
            proc.kill()
            raise BuilderRunnerError(
                f"Builder Runner 响应超时(> {timeout}s):fail closed,"
                f"不采信部分输出")
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="replace")
        if len(buf.encode("utf-8")) > max_bytes:
            proc.kill()
            raise BuilderRunnerError(
                f"Builder Runner 响应超过 {max_bytes} 字节上限:"
                f"协议违规 fail closed")
    line, _, _ = buf.partition("\n")
    if len(line.encode("utf-8")) > max_bytes:
        raise BuilderRunnerError(
            f"Builder Runner 响应单行超过 {max_bytes} 字节上限:"
            f"协议违规 fail closed")
    return line


# ------------------------------------------------- 沙箱报告校验(C2/C3)
def check_effective_sandbox_report(
    report: Any, profile: BuilderRunnerProfile,
) -> dict[str, Any]:
    """C3:实际生效沙箱状态的不变量校验(降级即拒绝)。

    返回含 esb- 哈希与关键摘要的检查结果;任何缺失/降级抛
    BuilderRunnerError(fail closed,不以"代码相同"替代状态证明)。
    """
    import errno as _errno

    from rl_builder_runtime import PRIVATE_DEV_NODES
    from rl_builder_runtime.runner import (
        SECCOMP_PROCESS_POLICY,
        sandbox_report_hash,
        seccomp_filter_digest,
    )

    if not isinstance(report, dict):
        raise BuilderRunnerError("Runner 响应缺 sandbox_report(C1 fail closed)")
    if report.get("format") != SANDBOX_REPORT_FORMAT:
        raise BuilderRunnerError(
            f"sandbox_report.format 必须是 {SANDBOX_REPORT_FORMAT!r}"
            f"(收到 {report.get('format')!r})")
    if report.get("no_new_privs") != 1:
        raise BuilderRunnerError("no_new_privs!=1:沙箱降级(拒绝)")
    if report.get("mounts_digest") != report.get(
            "bootstrap_mountopts_digest"):
        raise BuilderRunnerError(
            "实际挂载摘要与 bootstrap 布置摘要不一致(沙箱漂移;拒绝)")
    ns = report.get("namespaces") or {}
    pid_ns = (ns.get("pid") or {})
    if pid_ns.get("pids_in_namespace") != [1]:
        # runner 在私有 pidns 内是唯一进程(pid 1)
        raise BuilderRunnerError(
            "PID namespace 隔离缺失:pidns 内出现其他进程(拒绝)")
    if (ns.get("net") or {}).get("interfaces") != ["lo"]:
        raise BuilderRunnerError(
            "网络 namespace 隔离缺失:接口不止 lo(拒绝)")
    if (ns.get("user") or {}).get("inside_userns_root_uid") != 0:
        raise BuilderRunnerError("user namespace 映射异常(拒绝)")
    mounts = (ns.get("mount") or {})
    if not mounts.get("pivot_root_applied"):
        raise BuilderRunnerError("pivot_root 最小 rootfs 未应用(拒绝)")
    if report.get("inherited_fds") != [0, 1, 2]:
        raise BuilderRunnerError(
            f"继承 fd 集合异常: {report.get('inherited_fds')}(只允许 0/1/2)")
    if report.get("private_dev_nodes") != list(PRIVATE_DEV_NODES):
        raise BuilderRunnerError("私有最小 /dev 节点集不符(拒绝)")
    probes = report.get("probes") or {}
    for probe in ("host_etc_unnameable", "host_sys_unnameable",
                  "host_home_unnameable"):
        if (probes.get(probe) or {}).get("result") != "ENOENT":
            raise BuilderRunnerError(
                f"宿主路径探针 {probe} 未返回 ENOENT(pivot 未生效;拒绝)")
    if (probes.get("dev_shm_private") or {}).get("listing") != []:
        raise BuilderRunnerError("/dev/shm 非私有(非空;拒绝)")
    rlimits = report.get("rlimits") or {}
    expected_limits = {
        "cpu_seconds": int(profile.rlimits.get("cpu_seconds", 0)),
        "nofile": int(profile.rlimits.get("nofile", 0)),
        "nproc": int(profile.rlimits.get("nproc", 0)),
    }
    for key, value in expected_limits.items():
        applied = rlimits.get(key)
        if not isinstance(applied, list) or len(applied) != 2 \
                or applied[0] != value:
            raise BuilderRunnerError(
                f"rlimit {key} 未实际应用(期望 {value},收到 {applied};拒绝)")
    if profile.process_tree_policy == SINGLE_PROCESS:
        if not profile.install_seccomp:
            raise BuilderRunnerError(
                "single_builder_process 声明但 seccomp 禁用(拒绝)")
        if report.get("seccomp_mode") != 2:
            raise BuilderRunnerError(
                f"seccomp 模式异常: {report.get('seccomp_mode')}"
                f"(必须为 filter 模式 2;拒绝)")
        if report.get("seccomp_filter_hash") != seccomp_filter_digest():
            raise BuilderRunnerError(
                "seccomp filter 摘要与进程树策略期望不符(拒绝)")
        if report.get("seccomp_policy") != SECCOMP_PROCESS_POLICY:
            raise BuilderRunnerError("seccomp 策略载荷不符(拒绝)")
        if (probes.get("fork_denied") or {}).get("result") != \
                f"ERRNO{_errno.EPERM}":
            raise BuilderRunnerError("fork 探针未被拒绝(拒绝)")
        if (probes.get("exec_denied") or {}).get("result") not in (
                f"ERRNO{_errno.EPERM}", "SKIPPED-NO-SECCOMP"):
            raise BuilderRunnerError("exec 探针未被拒绝(拒绝)")
    if report.get("process_tree_policy") != profile.process_tree_policy:
        raise BuilderRunnerError(
            f"报告进程树策略 {report.get('process_tree_policy')!r} 与 "
            f"profile {profile.process_tree_policy!r} 不一致(拒绝)")
    if profile.process_tree_policy == SINGLE_PROCESS and (
            report.get("child_process_count") != 0
            or report.get("exec_count") != 0):
        raise BuilderRunnerError(
            f"进程树违规:child={report.get('child_process_count')},"
            f"exec={report.get('exec_count')}(拒绝)")
    return {
        "effective_sandbox_hash": sandbox_report_hash(report),
        "seccomp_filter_hash": report.get("seccomp_filter_hash"),
        "landlock": dict(report.get("landlock") or {}),
        "mounts_digest": report.get("mounts_digest"),
        "kernel_release": report.get("kernel_release"),
    }


# ------------------------------------------------------------ 单次运行
def run_isolated_builder_run(
    identity: Any, request: dict[str, Any], *,
    builder_root: Path | str,
    profile: BuilderRunnerProfile | None = None,
    python: str | None = None,
    staging_base: Path | str | None = None,
    keep_staging: bool = False,
) -> dict[str, Any]:
    """一次完整的隔离 Runner 构建(私有 Builder 专用)。

    序列:staging 复制 -> builder tree 与 runtime manifest 双对账
    (TOCTOU)-> unshare+pivot+Landlock+seccomp 沙箱启动 -> 发送冻结
    构建请求 -> 接收 v2 响应 -> Effective Sandbox Report 不变量校验
    -> 主进程解析 pack/attempt log/runtime lock。返回含 esb-/acs-
    与进程树字段的 run record。
    """
    from rl_builder_runtime import BUILDER_WORKER_PROTOCOL
    from rl_builder_runtime.runner import sandbox_report_hash
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
        proc = launch_builder_runner(
            profile, base_dir=base,
            entrypoint_module=str(tree.get("entrypoint_module") or ""),
            entrypoint_qualname=str(
                tree.get("entrypoint_qualname") or ""),
            python=python,
            expected_runtime_manifest=expected_rt)
        try:
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(
                request, separators=(",", ":"),
                ensure_ascii=False) + "\n")
            proc.stdin.flush()
            line = _readline_with_timeout(
                proc, timeout=profile.run_timeout_seconds,
                max_bytes=profile.response_max_bytes)
        except BrokenPipeError as exc:
            raise BuilderRunnerError(
                "Builder Runner 通信失败(请求管道断裂;已脱敏)") from exc
        finally:
            stderr_tail = ""
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            try:
                if proc.stderr is not None:
                    stderr_tail = proc.stderr.read(
                        4096) or ""
            except Exception:  # noqa: BLE001 - 诊断信息尽力读取
                stderr_tail = ""
        try:
            resp = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BuilderRunnerError(
                "Builder Runner 响应无法解析(已脱敏;"
                f"stderr 尾部: {stderr_tail[-200:]!r})") from exc
        if resp.get("protocol") != BUILDER_WORKER_PROTOCOL:
            raise BuilderRunnerError(
                f"Builder Runner 响应协议不符(期望 "
                f"{BUILDER_WORKER_PROTOCOL!r},收到 "
                f"{resp.get('protocol')!r};fail closed)")
        access = dict(resp.get("access_summary") or {})
        report = resp.get("sandbox_report")
        if resp.get("status") != "ok":
            raise BuilderRunnerError(
                f"Builder Runner 构建失败(stage={resp.get('stage')!r},"
                f"error={str(resp.get('error'))[:300]};已脱敏)")
        sandbox_checks = check_effective_sandbox_report(report, profile)
        result = resp.get("build_result")
        lock = dict(resp.get("runtime_lock") or {})
        if not isinstance(result, dict) or not isinstance(lock, dict):
            raise BuilderRunnerError(
                "Builder Runner 响应缺 build_result/runtime_lock"
                "(已脱敏;fail closed)")
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
            "effective_sandbox": report,
            "effective_sandbox_hash": sandbox_report_hash(report),
            "process_tree_policy": lock.get("process_tree_policy"),
            "child_process_count": int(
                lock.get("child_process_count") or 0),
            "child_process_attempts": int(
                lock.get("child_process_attempts") or 0),
            "exec_count": int(lock.get("exec_count") or 0),
            "runner_isolation": "isolated_process",
            "error": None,
        }
    finally:
        if own_cleanup and not keep_staging:
            shutil.rmtree(base, ignore_errors=True)
