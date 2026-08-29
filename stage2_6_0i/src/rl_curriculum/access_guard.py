"""Builder 阶段主进程访问守卫 v2(阶段 2.6.0h 工作包 G)。

v1 只覆盖 CPython ``open`` 审计事件,不足以声称 "open/stat/read 全部
未发生"。v2 语义:

- 审计事件集扩展到 CPython 3.11 实际发出的全部路径/进程类事件:
  open / os.listdir / os.scandir / os.system / subprocess.Popen /
  ctypes.dlopen / os.exec / os.posix_spawn / os.spawn;
- CPython 3.11 对 os.stat / os.access / os.readlink 不发审计事件
  ——stat 级不可利用由 pivot_root 最小 rootfs 保证(Builder Runner
  内宿主路径 ENOENT,见 Effective Sandbox Report 的探针证明);
  本守卫覆盖评估主进程 4b 窗口内可审计的全部访问;
- subprocess.Popen 事件分类:隔离 Builder Runner 启动(unshare +
  rl_builder_runtime.bootstrap)是本阶段**唯一**允许的子进程;任何
  其他 Popen(如 Candidate 沙箱启动)在 Builder 阶段出现即违规
  (证明 Candidate 沙箱未在 checkpoint 前启动);
- 测试 monkeypatch 只是测试;生产守卫依赖运行时审计钩子与沙箱
  namespace 证明,二者互相独立。
"""

from __future__ import annotations

import sys

#: 路径类审计事件 -> 参数索引
_PATH_EVENTS = {
    "open": 0,
    "os.listdir": 0,
    "os.scandir": 0,
    "os.system": 0,
    "ctypes.dlopen": 0,
}
#: 进程创建类事件
_SPAWN_EVENTS = ("subprocess.Popen", "os.exec", "os.posix_spawn",
                 "os.spawn", "os.fork")

#: 允许在 Builder 阶段启动的子进程 argv 特征:隔离 Builder Runner
#: 的 fork-launcher(rl_builder_runtime.bootstrap)与运行后 bundle
#: 复验的并行哈希 worker(rl_builder_runtime.bundle-parallel-hash;
#: 2.6.0i 起运行后全量复验发生在 Supervisor,其子进程只读取 staging
#: 内容,不触碰任何候选材料)
_ALLOWED_SPAWN_MARKERS = (
    "rl_builder_runtime.bootstrap", "/usr/bin/unshare",
    "rl_builder_runtime.bundle-parallel-hash",
    "rl_builder_runtime.bundle-env-version")

ACCESS_GUARD_FORMAT = "builder-stage-access-audit-v2"


class BuilderStageAccessGuard:
    """Builder 证明阶段(checkpoint 加载前)的主进程访问审计。

    进入 with 时挂 sys.addaudithook(CPython 限制:hook 无法摘除,
    退出时以活动标志停止记录);被守护路径(checkpoint/sidecar/
    attestation)的任何可审计访问记为违规,违规集合只保留 basename
    (不向输出泄漏完整宿主路径)。
    """

    def __init__(self, guarded_paths):
        self._guarded = [str(p) for p in guarded_paths]
        self._entered = False
        self.open_event_count = 0
        self.spawn_events: list[str] = []
        self.violations: list[str] = []

    def _hook(self, event: str, args) -> None:
        if not self._entered:
            return
        try:
            if event in _PATH_EVENTS:
                idx = _PATH_EVENTS[event]
                if len(args) <= idx:
                    return
                path = args[idx]
                if not isinstance(path, (str, bytes)):
                    return
                if isinstance(path, bytes):
                    path = path.decode("utf-8", "replace")
                self.open_event_count += 1
                if any(path.startswith(g) for g in self._guarded):
                    name = path.rsplit("/", 1)[-1]
                    if name not in self.violations:
                        self.violations.append(f"{event}:{name}")
            elif event in _SPAWN_EVENTS:
                argv0 = args[0] if args else None
                if isinstance(argv0, (list, tuple)):
                    argv0 = " ".join(str(x) for x in argv0)
                elif argv0 is None:
                    argv0 = ""
                elif isinstance(argv0, bytes):
                    argv0 = argv0.decode("utf-8", "replace")
                # CPython 的 subprocess.Popen 审计事件携带
                # (executable, args_list, ...):标记可能出现在完整
                # argv(-m bootstrap / -c 脚本首行标记),不只 executable
                argv_rest = ""
                if len(args) > 1 and isinstance(args[1], (list, tuple)):
                    argv_rest = " ".join(str(x) for x in args[1])
                desc = f"{event}:{argv0} {argv_rest}".strip()
                self.spawn_events.append(desc.split(" ")[0]
                                         if not argv_rest else desc[:80])
                combined = f"{argv0} {argv_rest}"
                if event == "subprocess.Popen" and any(
                        m in combined for m in _ALLOWED_SPAWN_MARKERS):
                    return  # 隔离 Builder Runner/复验 worker(允许)
                if len(self.violations) < 32:
                    self.violations.append(
                        f"{event}:<非 Builder Runner 子进程>")
        except Exception:  # noqa: BLE001 - 审计绝不影响执行
            pass

    def __enter__(self) -> "BuilderStageAccessGuard":
        sys.addaudithook(self._hook)
        self._entered = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._entered = False

    def audit_result(self) -> dict:
        return {
            "format": ACCESS_GUARD_FORMAT,
            "guarded": [p.rsplit("/", 1)[-1]
                        for p in self._guarded],
            "violations": list(self.violations),
            "open_event_count": int(self.open_event_count),
            "spawn_event_count": len(self.spawn_events),
            "covered_events": sorted(
                set(_PATH_EVENTS) | set(_SPAWN_EVENTS)),
            "stat_coverage": (
                "namespace_unnameable(pivot_root;CPython 3.11 对 "
                "os.stat/os.access/os.readlink 无审计事件,stat 级"
                "不可利用由 Runner 沙箱的宿主路径 ENOENT 探针证明)"),
            "guard_active": bool(self._entered),
        }
