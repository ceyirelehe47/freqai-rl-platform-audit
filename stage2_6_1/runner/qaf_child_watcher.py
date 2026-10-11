#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QAF 子进程观察器(RouteC_CueAudit_FormalIdentityClosure_v1 §3)。

qaf_v3 A2 轮的 bash 观察器因 ``snap()`` 内 ``local rc_alive`` 与循环
终止条件读取的全局未设值互不可见而永不退出,在封包后继续写
E4_watch.jsonl,导致 RETURN v1 冷读 FAIL。本工具以显式实例状态取代
shell 变量作用域,修正三类终止形态并保留只读语义:

1. 正常: 目标进程结束 **且** rc 文件已落盘 → 再采样一个确认 tick,
   ``reason=rc_recorded_and_process_ended`` 退出;
2. 异常: 目标进程消失但 rc 文件连续 ``grace_ticks`` 个 tick 缺失 →
   ``reason=abnormal_end_no_rc`` 退出(只记录,不重启不补跑);
3. 停止请求: stop 文件出现 → ``reason=stop_requested`` 退出
   (封包前冻结诊断写入源的机制化出口)。

目标日志暂未存在不是错误: 记录 ``present=false``/``bytes=0``。

观察器只读目标实例(进程表/文件尺寸);输出为单一 create-only
JSONL(O_EXCL,不得覆盖既有观察记录)。本工具不执行任何业务动作。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

FORMAT = "cur261-qaf-child-watcher-v1"


def _target_alive(pattern: str) -> bool:
    """纯 stdlib 进程表扫描(/proc/*/cmdline 含 pattern 即目标)。"""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                cmd = fh.read().decode("utf-8", "replace")
        except OSError:
            continue
        if pattern in cmd and int(pid) != os.getpid():
            return True
    return False


class ChildWatcher:
    """单实例显式状态观察器(所有终止判定用实例属性,无作用域陷阱)。"""

    def __init__(self, pattern: str, rc_file: Path, out_file: Path,
                 stop_file: Path | None = None, target_log: Path | None = None,
                 interval_s: float = 60.0, max_ticks: int = 1440,
                 grace_ticks: int = 3) -> None:
        self.pattern = pattern
        self.rc_file = Path(rc_file)
        self.out_file = Path(out_file)
        self.stop_file = Path(stop_file) if stop_file else None
        self.target_log = Path(target_log) if target_log else None
        self.interval_s = float(interval_s)
        self.max_ticks = int(max_ticks)
        self.grace_ticks = int(grace_ticks)
        self._no_rc_streak = 0
        self.tick_index = 0
        self.final_reason: str | None = None

    # -- 单个采样点(纯读取;不 touch 目标)--------------------------
    def _snapshot(self) -> dict:
        alive = _target_alive(self.pattern)
        rc = (self.rc_file.read_text(encoding="utf-8").strip()
              if self.rc_file.is_file() else None)
        log: dict = {"present": False, "bytes": 0, "lines": None}
        if self.target_log is not None and self.target_log.is_file():
            try:
                data = self.target_log.read_bytes()
                log = {"present": True, "bytes": len(data),
                       "lines": data.count(b"\n")}
            except OSError:
                log = {"present": True, "bytes": -1, "lines": None,
                       "read_error": True}
        snap = {
            "format": FORMAT,
            "tick": self.tick_index,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "target_alive": alive,
            "rc": rc,
            "target_log": log,
        }
        # 终止判定(实例状态,非局部变量)
        if self.stop_file is not None and self.stop_file.is_file():
            self.final_reason = "stop_requested"
        elif rc is not None and not alive:
            if self._no_rc_streak == -1:  # 已确认过一轮
                self.final_reason = "rc_recorded_and_process_ended"
            else:
                self._no_rc_streak = -1  # 首见:下一 tick 复核确认
                snap["confirm_tick_pending"] = True
        elif rc is None and not alive:
            self._no_rc_streak += 1
            snap["no_rc_streak"] = self._no_rc_streak
            if self._no_rc_streak >= self.grace_ticks:
                self.final_reason = "abnormal_end_no_rc"
        else:
            self._no_rc_streak = 0
        if self.final_reason is not None:
            snap["final_reason"] = self.final_reason
        return snap

    def run(self) -> int:
        self.out_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.out_file,
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            print(f"观察输出已存在,拒绝覆盖: {self.out_file}",
                  file=sys.stderr)
            return 2
        handle = os.fdopen(fd, "a", encoding="utf-8")
        try:
            while self.tick_index < self.max_ticks:
                snap = self._snapshot()
                handle.write(json.dumps(snap, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                self.tick_index += 1
                if self.final_reason is not None:
                    return 0
                time.sleep(self.interval_s)
            # max_ticks 用尽仍未终止:如实记录,不伪装正常结束
            handle.write(json.dumps({
                "format": FORMAT, "tick": self.tick_index,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                    time.gmtime()),
                "final_reason": "max_ticks_exhausted",
            }, ensure_ascii=False) + "\n")
            return 3
        finally:
            handle.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qaf-child-watcher")
    ap.add_argument("--pattern", required=True,
                    help="目标进程 cmdline 匹配子串")
    ap.add_argument("--rc-file", required=True,
                    help="目标运行的 rc 文件(目标或其包装负责落盘)")
    ap.add_argument("--out", required=True, help="create-only JSONL 输出")
    ap.add_argument("--stop-file", default=None,
                    help="出现即停止(封包前冻结诊断写入源)")
    ap.add_argument("--target-log", default=None,
                    help="被观察日志(仅读尺寸/行数;可不存在)")
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--max-ticks", type=int, default=1440)
    ap.add_argument("--grace-ticks", type=int, default=3)
    args = ap.parse_args(argv)
    w = ChildWatcher(args.pattern, Path(args.rc_file), Path(args.out),
                     Path(args.stop_file) if args.stop_file else None,
                     Path(args.target_log) if args.target_log else None,
                     args.interval, args.max_ticks, args.grace_ticks)
    return w.run()


if __name__ == "__main__":
    raise SystemExit(main())
