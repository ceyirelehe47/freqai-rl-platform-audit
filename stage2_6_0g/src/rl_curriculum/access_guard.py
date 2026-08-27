"""Checkpoint 前访问守卫(阶段 2.6.0g 收尾:工作包 H)。

Builder integrity/provenance 阶段(formal D1 步骤 1 至 4b)必须证明:

- checkpoint 文件从未 open/stat/read;
- sidecar 从未读取;
- attestation 从未验证;
- Candidate 沙箱从未启动(沙箱 spy 断言,见 formal_exam/tests)。

本模块用 ``sys.addaudithook`` 在主评估进程挂载真实访问记录:

- "open" 事件(CPython audit 事件,builtins.open 与 os.open 都触发)
  的路径若位于受保护前缀之下 -> 记录违规(不抛异常、不中断——
  守卫阶段结束时统一判定 fail closed,记录进入 EXAM_INVALID 输出);
- audit hook 内部吞掉一切异常,绝不因审计影响执行语义;
- stat 类访问由配套测试通过 monkeypatch os.stat 等价覆盖(audit
  事件不含 os.stat)。

Runner 侧(rl_builder_runtime.runner)有对称的 audit hook:Builder
进程内全部 open 路径被记录,allowlist 之外的上报主进程并 fail
closed(Landlock deny-by-default 兜底)。
"""

from __future__ import annotations

import sys
from typing import Any


class BuilderStageAccessGuard:
    """builder 阶段主进程访问守卫(audit hook 真实记录)。

    用法::

        with BuilderStageAccessGuard([checkpoint, sidecar, ...]) as g:
            verify_builder_provenance(...)
        audit = g.audit_result()
        if audit["violations"]: fail closed

    with 块期间任何对受保护路径的 open(读/写/创建)都会被记录;
    audit_result() 返回 {guarded_paths(脱敏为 basename), violations,
    open_event_count}。violations 元素只含 basename(不泄漏评估方
    路径到输出)。
    """

    def __init__(self, protected_paths: list[str]):
        self._prefixes = [str(p) for p in protected_paths if p]
        self._entered = False
        self.violations: list[str] = []
        self.open_event_count = 0

    def _hook(self, event: str, args) -> None:
        try:
            if not self._entered or event != "open":
                return
            path = args[0] if args else None
            if not isinstance(path, (str, bytes, int)):
                return
            path = str(path)
            self.open_event_count += 1
            for prefix in self._prefixes:
                if path == prefix or path.startswith(prefix):
                    import os

                    self.violations.append(
                        f"{os.path.basename(path)}"
                        f"({event})")
                    break
        except Exception:  # noqa: BLE001 - 审计绝不影响执行
            pass

    def __enter__(self) -> "BuilderStageAccessGuard":
        sys.addaudithook(self._hook)
        self._entered = True
        return self

    def __exit__(self, *exc_info) -> None:
        # audit hook 无法摘除(CPython 限制);守卫对象标记退出后,
        # _hook 不再记录(active 标志)
        self._entered = False

    def audit_result(self) -> dict[str, Any]:
        import os

        return {
            "format": "builder-stage-access-audit-v1",
            "guarded": [os.path.basename(p) for p in self._prefixes],
            "violations": sorted(set(self.violations)),
            "open_event_count": int(self.open_event_count),
            "guard_active": bool(self._entered),
        }
