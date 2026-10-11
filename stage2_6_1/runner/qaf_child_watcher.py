#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QAF 子进程观察器 v2(RouteC_CueAudit R1/F4)。

v1 缺陷(IndependentReview_33407fd4 §F4):``_target_alive`` 以
cmdline 子串判存活,仅排除自身 PID——父 shell 命令行含 pattern、
无关同名进程、其他观察器都会被误认,导致永不退出。

v2 绑定**运行实例身份**:
- 目标 = (PID, /proc/<pid>/stat 的 starttime 字段 22)。starttime
  在进程创建时由内核单调赋值,PID 复用后 starttime 改变 ⇒ 复用
  立刻被识别为"目标已死",不会误绑新进程。
- PID 来源:--pid(监督/run 身份给定)或 --pid-file(监督启动器
  落盘的 child pid 文件;观察开始时读取一次,不追新值)。
- --pattern 仅诊断字段进快照,**不参与**存活判定。
- --pid-file 与 --pattern 同时缺省时拒绝运行(fail closed,不回退
  子串匹配)。

终止形态与 v1 一致:rc 落盘+进程结束确认(确认 tick)/异常结束
(grace_ticks)/stop 文件/max_ticks 如实记录;输出 create-only。
观察器绝不干预业务进程(不杀/不重启/不写目标任何文件)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

FORMAT = "cur261-qaf-child-watcher-v2"



def _proc_state_and_start(pid: int) -> tuple[str, int] | None:
    """(state, starttime) 或 None(进程不存在)。

    僵尸(state=Z)=目标已终止(等待父进程收尸),按**不存活**处理
    ——否则已被 wait 的目标因 /proc 残留条目被误判为一直运行。
    """
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as fh:
            stat = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    try:
        rest = stat[stat.rindex(")") + 2:].split()
        return rest[0], int(rest[19])
    except (ValueError, IndexError):
        return None


def proc_start_time(pid: int) -> int | None:
    """/proc/<pid>/stat 字段 22(starttime,时钟 tick)。不存在=None。"""
    got = _proc_state_and_start(pid)
    return None if got is None else got[1]


def pid_alive_with_start(pid: int, start_token: int | None) -> bool:
    """pid 存活(非僵尸)**且** starttime 与绑定值一致(防复用)。"""
    got = _proc_state_and_start(pid)
    if got is None or got[0] == "Z":
        return False
    return start_token is None or got[1] == start_token



def cmdline_of(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().decode("utf-8", "replace").replace(
                "\0", " ")
    except OSError:
        return ""


class ChildWatcher:
    """绑定 (pid, starttime) 的单实例显式状态观察器。"""

    def __init__(self, pid: int, rc_file: Path, out_file: Path,
                 stop_file: Path | None = None,
                 target_log: Path | None = None,
                 pattern: str | None = None,
                 interval_s: float = 60.0, max_ticks: int = 1440,
                 grace_ticks: int = 3,
                 start_token: int | None = None) -> None:
        self.pid = int(pid)
        self.start_token = (start_token
                            if start_token is not None
                            else proc_start_time(self.pid))
        self.rc_file = Path(rc_file)
        self.out_file = Path(out_file)
        self.stop_file = Path(stop_file) if stop_file else None
        self.target_log = Path(target_log) if target_log else None
        self.pattern = pattern  # 仅诊断
        self.interval_s = float(interval_s)
        self.max_ticks = int(max_ticks)
        self.grace_ticks = int(grace_ticks)
        self._no_rc_streak = 0
        self.tick_index = 0
        self.final_reason: str | None = None

    def _snapshot(self) -> dict:
        alive = pid_alive_with_start(self.pid, self.start_token)
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
            "pid": self.pid,
            "start_token": self.start_token,
            "target_alive": alive,
            "rc": rc,
            "target_log": log,
        }
        if self.pattern is not None:
            # 诊断字段:同 pattern 其他进程计数(不影响判定)
            snap["pattern_diagnostic"] = {
                "pattern": self.pattern,
                "other_pids_matching": [
                    p for p in os.listdir("/proc")
                    if p.isdigit() and int(p) != self.pid
                    and self.pattern in cmdline_of(int(p))],
            }
        if self.stop_file is not None and self.stop_file.is_file():
            self.final_reason = "stop_requested"
        elif rc is not None and not alive:
            if self._no_rc_streak == -1:
                self.final_reason = "rc_recorded_and_process_ended"
            else:
                self._no_rc_streak = -1
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
    ap = argparse.ArgumentParser(
        prog="qaf-child-watcher",
        description="绑定 PID+starttime 的只读观察器;"
                    "pattern 仅诊断;不提供 pid 绑定时拒绝运行")
    ap.add_argument("--pid", type=int, default=None,
                    help="目标进程 PID(监督/run 身份给定)")
    ap.add_argument("--pid-file", default=None,
                    help="含目标 PID 的文件(监督启动器落盘;"
                         "观察开始时读取一次)")
    ap.add_argument("--rc-file", required=True,
                    help="目标运行的 rc 文件(目标/包装负责落盘)")
    ap.add_argument("--out", required=True, help="create-only JSONL 输出")
    ap.add_argument("--stop-file", default=None,
                    help="出现即停止(封包前冻结诊断写入源)")
    ap.add_argument("--target-log", default=None,
                    help="被观察日志(仅读尺寸/行数;可不存在)")
    ap.add_argument("--pattern", default=None,
                    help="诊断用 cmdline 子串(不参与存活判定)")
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--max-ticks", type=int, default=1440)
    ap.add_argument("--grace-ticks", type=int, default=3)
    args = ap.parse_args(argv)
    pid = args.pid
    if pid is None and args.pid_file:
        try:
            pid = int(Path(args.pid_file).read_text(
                encoding="utf-8").strip())
        except (OSError, ValueError):
            print(f"pid-file 不可读/畸形: {args.pid_file}",
                  file=sys.stderr)
            return 2
    if pid is None:
        print("拒绝运行:未提供 --pid/--pid-file(v1 式纯 pattern "
              "子串判定已移除,fail closed)", file=sys.stderr)
        return 2
    w = ChildWatcher(pid, Path(args.rc_file), Path(args.out),
                     Path(args.stop_file) if args.stop_file else None,
                     Path(args.target_log) if args.target_log else None,
                     args.pattern, args.interval, args.max_ticks,
                     args.grace_ticks)
    return w.run()


if __name__ == "__main__":
    raise SystemExit(main())
