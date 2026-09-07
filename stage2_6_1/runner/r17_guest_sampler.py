#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 guest 采样模块(任务书 WP2;自 blocker_diagnosis/observers/
guest_sampler.py 提取并按审查修正记录 §7-13 修正)。

与历史版本的差异(提取修正清单):
- 去决策化:历史 B4 streak/marker 判定逻辑整体移除,本模块只采样;
  判定归 r17_supervision.py 的策略引擎(sampler 不落任何 marker);
- 可停线程:while True 无限循环改为 threading.Event 控制的线程,
  supervisor 可干净收尾;
- 身份修正:页大小用 sysconf(_SC_PAGESIZE)(不再固定 4K);comm 解析
  取最后一个 ')';每进程 starttime(/proc/<pid>/stat field 22 ticks)
  作实例身份——PID 复用(starttime 变)后计数器不拼接、速率不出现负值;
- 测量扩展:CPU 累计(utime+stime ticks→秒)、/proc/<pid>/io(权限
  边界:EPERM→unavailable,不填零)、smaps_rollup PSS/私有内存低频
  (默认 30s 或告警时;权限失败记 unavailable)、线程/子进程数、状态;
- cgroup:沿目标进程 cgroup 及祖先解析有效 memory.max/memory.current/
  memory.events(无 memory.max=unlimited→该项记 not_limited,不报错;
  事件文件不存在→unavailable 降级);
- 任务树:登记 pgid 为主口径(/proc stat field 5 pgrp 匹配,进程被
  重新托管后仍在组内),辅以根 PID 后代;roots 文件机制移除,改为
  pgid 列表参数(由 supervisor 登记);
- 自身开销:每样本记录采样耗时/自身 RSS。

只读 /proc 与自身输出;不持有业务锁/token/pipe;不写任何正式
journal(源码不含执行治理接口)。
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

PAGE_SIZE = os.sysconf("SC_PAGESIZE")  # 实际页大小(非假定 4K)
CLK_TCK = os.sysconf("SC_CLK_TCK")

MEMINFO_KEYS = (
    "MemTotal", "MemFree", "MemAvailable", "AnonPages", "Cached",
    "SReclaimable", "Dirty", "Writeback", "SwapTotal", "SwapFree",
    "Slab", "KernelStack", "PageTables",
)


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------ /proc 解析(纯函数,可测)
def parse_proc_stat(text: str) -> dict:
    """解析 /proc/<pid>/stat(健壮:comm 含空格/括号取最后 ')')。"""
    rp = text.rindex(")")
    # 格式:pid (comm) state ppid pgrp session ... field22=starttime
    head = text[: text.index("(")].strip()
    pid = int(head)
    fields = text[rp + 2:].split()
    return {
        "pid": pid,
        "comm": text[text.index("(") + 1: rp],
        "state": fields[0],
        "ppid": int(fields[1]),
        "pgrp": int(fields[2]),
        "num_threads": int(fields[17]),
        "starttime_ticks": int(fields[19]),
        "utime_ticks": int(fields[11]),
        "stime_ticks": int(fields[12]),
    }


def parse_statm(text: str) -> dict:
    """statm:rss/pages 字段按实际页大小换算 kB。"""
    parts = text.split()
    return {
        "rss_kb": int(parts[1]) * PAGE_SIZE // 1024,
        "shared_kb": int(parts[2]) * PAGE_SIZE // 1024,
    }


def read_meminfo() -> dict:
    out: dict = {}
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[0].rstrip(":") in MEMINFO_KEYS:
                    out[parts[0].rstrip(":")] = int(parts[1])  # kB
    except OSError:
        return {"unavailable": True}
    return out


def read_psi(path: str) -> dict:
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError:
        return {"unavailable": True}
    out: dict = {}
    for seg in text.split("\n"):
        seg = seg.strip()
        if not seg:
            continue
        parts = seg.split()
        for kv in parts[1:]:
            if "=" in kv:
                k, v = kv.split("=", 1)
                try:
                    out[f"{parts[0]}_{k}"] = float(v)
                except ValueError:
                    pass
    return out


def read_vmstat_swap() -> dict:
    out: dict = {}
    try:
        with open("/proc/vmstat") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) == 2 and parts[0] in (
                        "pswpin", "pswpout"):
                    out[parts[0]] = int(parts[1])
    except OSError:
        pass
    return out


def read_pid_io(pid: int) -> dict:
    try:
        with open(f"/proc/{pid}/io") as fh:
            text = fh.read()
    except PermissionError:
        return {"unavailable": "permission"}
    except OSError:
        return {"unavailable": True}
    out: dict = {}
    for line in text.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip()
            if v.isdigit():
                out[k.replace("_", "").lower()] = int(v)
    return out


def read_pid_smaps_rollup(pid: int) -> dict:
    """低频明细:PSS/私有内存。权限失败→unavailable(不填零)。"""
    try:
        with open(f"/proc/{pid}/smaps_rollup") as fh:
            text = fh.read()
    except PermissionError:
        return {"unavailable": "permission"}
    except OSError:
        return {"unavailable": True}
    out: dict = {}
    for line in text.split("\n"):
        m = re.match(r"^(Pss|Private_Clean|Private_Dirty|Rss):\s+(\d+) kB", line)
        if m:
            out[m.group(1).replace("_", "").lower()] = int(m.group(2))
    return out


def _cgroup_chain(pid: int) -> list[str]:
    """/proc/<pid>/cgroup 的层级路径链(自身→祖先)。"""
    try:
        with open(f"/proc/{pid}/cgroup") as fh:
            text = fh.read()
    except OSError:
        return []
    # v2 统一挂载:0::/path;取每行 path 段
    paths = []
    for line in text.strip().split("\n"):
        parts = line.split(":", 2)
        if len(parts) == 3:
            p = parts[2] if parts[0] == "0" else None
            if p is not None and p not in paths:
                paths.append(p)
    chain: list[str] = []
    cur = paths[0] if paths else "/"
    while True:
        chain.append(cur)
        if cur == "/":
            break
        cur = cur.rsplit("/", 1)[0] or "/"
    return chain


def read_cgroup_memory(pid: int) -> dict:
    """沿 cgroup 及祖先取有效 memory.max/current/events。

    语义:无 memory.max(或值为 max)→not_limited(该保护项不适用,
    不报错不填零);memory.events 不存在→unavailable 降级。
    """
    base = Path("/sys/fs/cgroup")
    for rel in _cgroup_chain(pid):
        d = base / rel.lstrip("/")
        try:
            mx = (d / "memory.max").read_text().strip()
        except OSError:
            continue
        if mx == "max":
            return {"effective_limit": "not_limited", "path": rel}
        try:
            cur = int((d / "memory.current").read_text().strip())
        except OSError:
            cur = None
        events: dict = {}
        try:
            for line in (d / "memory.events").read_text().split("\n"):
                if " " in line:
                    k, v = line.split()
                    if v.isdigit():
                        events[k] = int(v)
        except OSError:
            events = {"unavailable": True}
        return {"effective_limit": int(mx), "current": cur,
                "events": events, "path": rel}
    return {"effective_limit": "unavailable"}


# ------------------------------------------------ 任务树扫描
def proc_table() -> dict[int, dict]:
    table: dict[int, dict] = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            with open(f"/proc/{pid}/stat") as fh:
                info = parse_proc_stat(fh.read())
            with open(f"/proc/{pid}/statm") as fh:
                info.update(parse_statm(fh.read()))
            table[pid] = info
        except (OSError, ValueError, IndexError):
            continue
    return table


def task_tree(table: dict[int, dict], pgids: set[int],
              root_pids: set[int]) -> list[int]:
    """pgid 匹配为主(重托管稳定),根 PID 后代为辅。"""
    out = {pid for pid, info in table.items()
           if info.get("pgrp") in pgids}
    children: dict[int, list[int]] = {}
    for pid, info in table.items():
        children.setdefault(info["ppid"], []).append(pid)
    stack = [p for p in root_pids if p in table]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(children.get(cur, ()))
    return sorted(out)


# ------------------------------------------------ 采样线程
class GuestSampler(threading.Thread):
    """guest 侧采样线程;emit 回调保证线程安全(单写者=supervisor)。"""

    def __init__(self, emit, interval: float = 5.0,
                 detail_interval: float = 30.0,
                 pgids: set[int] | None = None,
                 root_pids: set[int] | None = None,
                 run_id: str | None = None):
        super().__init__(daemon=True, name="r17-guest-sampler")
        self.emit = emit
        self.interval = interval
        self.detail_interval = detail_interval
        self.pgids = pgids or set()
        self.root_pids = root_pids or set()
        # WP3 §6.3:live 样本身份(绑定本次 run+源序号;同 seq 重复
        # 消费不增加有效样本数)
        self.run_id = run_id
        self._seq = 0
        self._stop_event = threading.Event()
        self._last_detail = -1e9
        # 实例身份:pid -> starttime_ticks(PID 复用检测)
        self._instance: dict[int, int] = {}
        self._cpu_prev: dict[int, tuple[int, int]] = {}
        self._io_prev: dict[int, dict] = {}
        self.coverage_gaps = 0
        self.last_sample_mono: float | None = None
        self.sampler_self_rss_kb = 0
        self.sampler_cpu_pct = 0.0
        self._proc_self_stat_prev: tuple[int, int] | None = None

    def stop(self) -> None:
        self._stop_event.set()

    def _sample(self, mono: float) -> dict:
        t0 = time.monotonic()
        self._seq += 1
        rec: dict = {
            "event": "guest_sample", "utc": utc_now_iso(),
            "mono": round(mono, 3), "seq": self._seq,
            "meminfo": read_meminfo(),
            "psi_memory": read_psi("/proc/pressure/memory"),
            "psi_cpu": read_psi("/proc/pressure/cpu"),
            "psi_io": read_psi("/proc/pressure/io"),
            "vmstat_swap": read_vmstat_swap(),
        }
        if self.run_id is not None:
            rec["run_id"] = self.run_id
        table = proc_table()
        if self.pgids or self.root_pids:
            pids = task_tree(table, self.pgids, self.root_pids)
            tasks = []
            tree_rss = 0
            now_detail = (mono - self._last_detail) >= self.detail_interval
            for pid in pids:
                info = table[pid]
                start = info["starttime_ticks"]
                prev_start = self._instance.get(pid)
                reused = prev_start is not None and prev_start != start
                self._instance[pid] = start
                cpu_ticks = info["utime_ticks"] + info["stime_ticks"]
                prev_cpu = self._cpu_prev.get(pid)
                # 复用/新实例:不产增量速率(避免负值/拼接)
                cpu_d = None
                if prev_cpu is not None and not reused:
                    cpu_d = max(0, cpu_ticks - prev_cpu) / CLK_TCK
                self._cpu_prev[pid] = cpu_ticks
                entry = {
                    "pid": pid, "ppid": info["ppid"],
                    "pgrp": info["pgrp"], "state": info["state"],
                    "comm": info["comm"][:32],
                    "inst_start_ticks": start,
                    "reused_pid": bool(reused),
                    "rss_kb": info["rss_kb"],
                    "threads": info["num_threads"],
                    "cpu_sec_total": round(cpu_ticks / CLK_TCK, 3),
                }
                if cpu_d is not None:
                    entry["cpu_sec_delta"] = round(cpu_d, 3)
                tree_rss += info["rss_kb"]
                io = read_pid_io(pid)
                if "unavailable" not in io:
                    prev_io = self._io_prev.get(pid)
                    if prev_io and not reused:
                        entry["io_read_kb_delta"] = max(
                            0, io.get("readbytes", 0)
                            - prev_io.get("readbytes", 0)) // 1024
                        entry["io_write_kb_delta"] = max(
                            0, io.get("writebytes", 0)
                            - prev_io.get("writebytes", 0)) // 1024
                    self._io_prev[pid] = io
                if now_detail:
                    pss = read_pid_smaps_rollup(pid)
                    if "unavailable" not in pss:
                        entry["pss_kb"] = pss.get("pss")
                        entry["private_kb"] = (
                            pss.get("privateclean", 0)
                            + pss.get("privatedirty", 0))
                    else:
                        entry["pss_kb"] = "unavailable"
                tasks.append(entry)
            rec["tasks"] = tasks
            rec["tasks_total_rss_kb"] = tree_rss
            rec["task_count"] = len(tasks)
            rec["task_cpu_sec_delta"] = round(
                sum(t.get("cpu_sec_delta", 0) for t in tasks
                    if isinstance(t.get("cpu_sec_delta"), float)), 3)
            if now_detail:
                self._last_detail = mono
            if pids:
                rec["cgroup_memory"] = read_cgroup_memory(pids[0])
        # 采样器自身开销
        me = table.get(os.getpid())
        if me:
            self.sampler_self_rss_kb = me["rss_kb"]
            ticks = me["utime_ticks"] + me["stime_ticks"]
            if self._proc_self_stat_prev is not None:
                d = max(0, ticks - self._proc_self_stat_prev)
                self.sampler_cpu_pct = round(
                    100.0 * d / CLK_TCK / max(self.interval, 1e-9), 2)
            self._proc_self_stat_prev = ticks
        rec["sampler_self_rss_kb"] = self.sampler_self_rss_kb
        rec["sampler_cpu_pct"] = self.sampler_cpu_pct
        rec["sample_cost_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return rec

    def sample_once(self) -> dict:
        """单次采样(测试与 supervisor 主循环共用同一路径)。"""
        return self._sample(time.monotonic())

    def run(self) -> None:
        start_mono = time.monotonic()
        self.emit({"event": "guest_sampler_start",
                   "utc": utc_now_iso(), "pid": os.getpid(),
                   "interval_s": self.interval,
                   "pgids": sorted(self.pgids),
                   "page_size": PAGE_SIZE, "clk_tck": CLK_TCK})
        while not self._stop_event.is_set():
            mono = time.monotonic() - start_mono
            try:
                self.emit(self._sample(mono))
            except Exception as exc:  # 采样缺陷不静默
                self.emit({"event": "guest_sampler_error",
                           "utc": utc_now_iso(),
                           "error": f"{type(exc).__name__}: {exc}"})
                self.coverage_gaps += 1
            self.last_sample_mono = time.monotonic()
            self._stop_event.wait(self.interval)
        self.emit({"event": "guest_sampler_end",
                   "utc": utc_now_iso(),
                   "coverage_gaps": self.coverage_gaps})
