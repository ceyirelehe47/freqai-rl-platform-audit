"""隔离 Builder Runner 启动器(阶段 2.6.0g 收尾:工作包 B,评估主进程侧)。

主评估进程对私有 Builder 只允许(B1):

- 读取并哈希 Builder 文件(builder package tree manifest);
- AST 静态检查(builder_identity.validate_builder_entrypoint 的
  静态部分);
- 创建隔离 Runner(本模块);
- 发送规范化 request(builder-build-request-v2);
- 接收规范化 result(builder-runner-worker-v1 响应)。

私有 Builder 的 import 与执行只发生在 rl_builder_runtime.runner
沙箱进程内(unshare user+mount+pid+proc+net + Landlock + rlimits;
挂载集合与 Candidate 沙箱不同:builder staging 只读 + tmpfs 输出,
无 checkpoint/sidecar bind-mount)。

启动序列强制 TOCTOU 防护(B3):

1. builder package 复制到匿名 staging(拒绝 symlink/设备文件;
   __pycache__/*.pyc 排除);
2. 对 staging 重算 tree manifest,与 Provider identity(npb- 绑定的
   package_tree)逐字节对账;
3. rl_builder_runtime 同样复制进 staging 并与当前源码 manifest
   对账(rtb-);
4. 执行的必须是刚验证过的 staging 副本(bootstrap 在 mount namespace
   内把 staging 重新 bind 为只读);不依赖主进程 sys.modules 缓存
   (隔离进程内无缓存可污染:identity 哈希后修改源文件 -> staging
   对账失败;同 root 已缓存旧 module -> Runner 进程内陈旧缓存弹出)。

Candidate 不可见(B4):Runner 的 argv 只有 python -m ...runner +
staging 路径 + module/qualname;env 为固定白名单(PATH/PYTHONPATH=
staging/LANG/TZ/PYTHONHASHSEED/OMP 单线程);stdin 只有冻结构建
请求(精确字段白名单,无任何路径/候选字段);cwd 是 scratch;
mounts 只有 staging 只读 + tmpfs;/proc 是独立 procfs(看不到父
进程);fd 只继承 0/1/2。
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

#: Runner 响应单行上限(字节;pack JSON 产物可达数 MB)
MAX_RUNNER_RESPONSE_BYTES = 32 * 1024 * 1024


class BuilderRunnerError(RuntimeError):
    """隔离 Builder Runner 错误/协议违规/超时(fail closed)。"""


# ---------------------------------------------------------------- profile
@dataclass(frozen=True)
class BuilderRunnerProfile:
    """Builder Runner 沙箱配置(可哈希,进入 Builder Run Evidence)。

    与 Candidate 沙箱 profile(candidate-sandbox-profile-v1)是**不同**
    的最小运行时与挂载集合(B2):无 checkpoint bind-mount、无 model
    目录、staging 重新只读 bind、scratch tmpfs 更小、执行超时适配
    构建(单次运行而非逐步交互)。
    """

    rlimits: dict[str, int] = field(default_factory=lambda: {
        "cpu_seconds": 900,
        "address_space_mb": 4096,
        "file_size_mb": 64,
        "nofile": 256,
        "nproc": 128,
    })
    #: 单次构建(bootstrap+import+build+审计)的执行超时
    run_timeout_seconds: float = 900.0
    #: 响应单行字节上限
    response_max_bytes: int = MAX_RUNNER_RESPONSE_BYTES
    #: stdout/stderr 总量上限(超出即 fail closed)
    output_cap_bytes: int = MAX_RUNNER_RESPONSE_BYTES + 65536

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "format": "builder-runner-profile-v1",
            "rlimits": {k: int(v) for k, v in sorted(self.rlimits.items())},
            "run_timeout_seconds": float(self.run_timeout_seconds),
            "response_max_bytes": int(self.response_max_bytes),
            "output_cap_bytes": int(self.output_cap_bytes),
            "env_whitelist": [
                "PATH", "PYTHONPATH", "LANG", "LC_ALL", "TZ",
                "PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE", "HOME",
                "TMPDIR", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
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


def _fixed_exec_env(staging_root: str, python: str) -> dict[str, str]:
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
    }


# ------------------------------------------------- 运行时 manifest(rtb-)
def _scan_tree_files(directory: Path) -> dict[str, str]:
    """扫描目录全部 regular files(拒绝 symlink;排除 __pycache__)。"""
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
    """Builder 运行时 manifest 的 canonical tree hash(rtb-)。"""
    return "rtb-" + hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


# ------------------------------------------------------------ staging(B3)
def _copy_tree(src: Path, dst: Path, *, label: str) -> None:
    """复制源码树到 staging(拒绝 symlink/设备;排除 pycache)。"""
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
            # 目录在复制文件时按需创建;其余非普通文件(设备/FIFO)拒绝
            if f.is_dir():
                continue
            raise BuilderRunnerError(
                f"{label} 源包含非普通文件 {rel.as_posix()!r}"
                f"(设备/FIFO 等被拒绝)")
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)


def _tree_manifest_from_staging(staging: Path) -> dict[str, str]:
    """对 staging 实际副本重算 {相对路径: sha256}(TOCTOU 对账输入)。"""
    return _scan_tree_files(staging)


def _verify_staged_files(
    staged_files: dict[str, str], expected: dict[str, Any], label: str,
) -> None:
    """staging 副本与 identity manifest 的逐字节对账(fail closed)。"""
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
    """把 builder package 复制到匿名 staging(<base>/builder_pkg)。

    staging 不在评估工作区内;复制全部真实文件(排除 __pycache__/
    *.pyc;新增 helper/资源文件同样进入并被 manifest 对账);
    symlink/设备文件拒绝。
    """
    src = Path(builder_root)
    if not src.is_dir():
        raise BuilderRunnerError(
            f"builder package root 不存在或不是目录: {src.name}(已脱敏)")
    dst = Path(base_dir) / "builder_pkg"
    _copy_tree(src, dst, label="builder package")
    return dst


def assemble_runtime_staging(base_dir: Path | str) -> Path:
    """把最小 Builder 运行时复制到 staging(<base>/runtime)。"""
    import rl_builder_runtime

    src = Path(rl_builder_runtime.__file__).parent
    dst_root = Path(base_dir) / "runtime"
    _copy_tree(src, dst_root / "rl_builder_runtime", label="builder runtime")
    return dst_root


# ------------------------------------------------------------ launcher
def _default_read_exec(python: str) -> list[str]:
    """从解释器位置推导运行时只读执行目录(conda env 根 + 系统 lib)。"""
    py = Path(python).resolve()
    env_root = py.parent.parent  # <env>/bin/python -> <env>
    read_exec = [str(env_root)]
    for d in ("/usr", "/lib", "/lib64", "/lib32", "/bin", "/sbin", "/opt"):
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
    """在系统级沙箱内启动 Builder Runner worker。

    沙箱层次:unshare(user+mount+pid+proc+net) -> rl_builder_runtime.
    bootstrap(staging 只读 bind/tmpfs scratch/Landlock/rlimits/关 fd)
    -> execve rl_builder_runtime.runner。base_dir 含已对账的
    runtime/ 与 builder_pkg/ 副本;argv/env 不含任何候选材料路径。
    """
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
    exec_env = _fixed_exec_env(staging_root, py)
    config = {
        "workdir": str(base.resolve()),
        "landlock": {
            "read_exec": [d for d in _default_read_exec(py) if os.path.exists(d)],
            "read_only": [d for d in ("/etc", "/proc", "/sys")
                          if os.path.exists(d)],
            "read_write": [d for d in ("/dev",) if os.path.isdir(d)],
        },
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
    # 父进程 env 同样走固定白名单(unshare/bootstrap 阶段;runner 的
    # env 由 bootstrap exec_env 完全替换)
    parent_env = _fixed_exec_env(staging_root, py)
    return subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=parent_env, text=True, bufsize=1,
        cwd=str(base / "scratch") if (base / "scratch").is_dir()
        else str(base),
        close_fds=True,
    )


def _readline_with_timeout(proc: subprocess.Popen, *, timeout: float,
                           max_bytes: int) -> str:
    """带超时与字节上限的 stdout 单行读取(select;fail closed)。"""
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
    (TOCTOU;fail closed,绝不启动不一致副本)-> unshare 沙箱启动 ->
    发送冻结构建请求 -> 接收规范化响应 -> 主进程解析 pack/attempt
    log/runtime lock。返回与 mock 组装通道同构的 run record。
    """
    from rl_builder_runtime import BUILDER_WORKER_PROTOCOL
    from rl_curriculum.builder_provenance import (
        attempt_log_hash, runtime_lock_hash,
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
        # B3:staging 复制 + 对刚复制的副本重算 manifest 并与 identity
        # 逐字节对账(执行前拦截复制过程篡改)
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
                f"{resp.get('protocol')!r};D3 fail closed)")
        access = dict(resp.get("access_summary") or {})
        if resp.get("status") != "ok":
            raise BuilderRunnerError(
                f"Builder Runner 构建失败(stage={resp.get('stage')!r},"
                f"error={str(resp.get('error'))[:300]};已脱敏)")
        result = resp.get("build_result")
        lock = dict(resp.get("runtime_lock") or {})
        if not isinstance(result, dict) or not isinstance(lock, dict):
            raise BuilderRunnerError(
                "Builder Runner 响应缺 build_result/runtime_lock"
                "(已脱敏;D3 fail closed)")
        try:
            pack = ExamPack.from_json(json.dumps(result.get("pack")))
            pack_hash = pack.pack_hash()
        except Exception as exc:  # noqa: BLE001 - 解析失败即 fail closed
            raise BuilderRunnerError(
                f"Runner 产物的 pack 无法解析为 ExamPack: "
                f"{type(exc).__name__}: {exc}") from exc
        try:
            log = canonicalize_attempt_log(
                result.get("attempt_log"), output_pack_hash=pack_hash,
                max_attempts=int(request.get("max_attempts") or 0))
        except BuilderProvenanceError as exc:
            raise BuilderRunnerError(str(exc)) from exc
        # G3:实际运行时锁与静态闭包预检立即对账(未注册/版本漂移/
        # <missing> -> fail closed;动态 import 的新依赖在 Runner 运行
        # 层即被拒绝,不等到考试期)
        from rl_curriculum.builder_provenance import (
            check_runtime_lock_against_static,
        )

        try:
            check_runtime_lock_against_static(
                lock, list((identity.manifest or {}).get(
                    "external_dependencies") or []))
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
            "isolated_process": True,
            "error": None,
        }
    finally:
        if own_cleanup and not keep_staging:
            shutil.rmtree(base, ignore_errors=True)
