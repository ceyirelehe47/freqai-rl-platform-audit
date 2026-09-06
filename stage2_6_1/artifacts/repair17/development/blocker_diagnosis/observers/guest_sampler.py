#!/usr/bin/env python3
"""R17 阶段 B：WSL/Linux 侧资源采样器（任务书 §4 B1/B2/B4）。

常驻进程，独立于业务任务树；只读 /proc 与自身输出文件，不持有业务
锁/token/pipe（B3）。目标任务树以根 PID 文件登记（每行一个 PID；
文件可被外部随时追加），采样时按 /proc 重建后代集合。

用法: python3 guest_sampler.py <out.jsonl> [interval_s=5] [pids_file=""]
      pids_file 缺省时不追踪任务树（只采系统级）。
保护线（B4）只记录与落 marker 文件，不杀任何进程。
"""
import json
import os
import sys
import time

MEMINFO_KEYS = [
    "MemTotal", "MemFree", "MemAvailable", "AnonPages", "Cached",
    "SReclaimable", "Dirty", "Writeback", "SwapTotal", "SwapFree",
]


def utc_now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_meminfo():
    out = {}
    try:
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[0].rstrip(":") in MEMINFO_KEYS:
                    out[parts[0].rstrip(":")] = int(parts[1])  # kB
    except OSError:
        return {"unavailable": True}
    return out


def read_psi(path):
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError:
        return {"unavailable": True}
    # 格式: "some avg10=.. avg60=.. avg300=.. total=.\nfull avg10=.. ..."
    out = {}
    for seg in text.split("\n"):
        seg = seg.strip()
        if not seg:
            continue
        parts = seg.split()
        tag = parts[0]
        for kv in parts[1:]:
            if "=" in kv:
                k, v = kv.split("=", 1)
                try:
                    out[f"{tag}_{k}"] = float(v)
                except ValueError:
                    pass
    return out


def read_vmstat_swap():
    out = {}
    try:
        with open("/proc/vmstat") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) == 2 and parts[0] in ("pswpin", "pswpout"):
                    out[parts[0]] = int(parts[1])
    except OSError:
        pass
    return out


def proc_table():
    """返回 {pid: (ppid, state, rss_kb, threads, comm)}，一次扫描。"""
    table = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            with open(f"/proc/{pid}/stat") as fh:
                stat = fh.read()
            # comm 可能含空格/括号：取最后一个 ')' 之后
            rp = stat.rindex(")")
            fields = stat[rp + 2:].split()
            ppid = int(fields[1])
            state = fields[0]
            out = {"ppid": ppid, "state": state, "comm": stat[1:rp]}
            with open(f"/proc/{pid}/statm") as fh:
                statm = fh.read().split()
            out["rss_kb"] = int(statm[1]) * 4  # pages -> kB (4K 页)
            out["threads"] = int(fields[17])   # field 20 原始 = num_threads
            table[pid] = out
        except (OSError, ValueError, IndexError):
            continue
    return table


def descendants(table, roots):
    children = {}
    for pid, info in table.items():
        children.setdefault(info["ppid"], []).append(pid)
    seen = set()
    frontier = [r for r in roots if r in table]
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        frontier.extend(children.get(cur, ()))
    return seen


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    out_path = sys.argv[1]
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    pids_file = sys.argv[3] if len(sys.argv) > 3 else ""
    marker = os.path.join(os.path.dirname(out_path) or ".", "PROTECTION_STOP_GUEST")
    mem_low_streak = 0
    start_mono = time.monotonic()
    with open(out_path, "a") as out:
        def emit(obj):
            out.write(json.dumps(obj, separators=(",", ":")) + "\n")
            out.flush()
        emit({"event": "sampler_start", "utc": utc_now_iso(),
              "interval_s": interval, "pids_file": pids_file or None,
              "mono0": start_mono, "pid": os.getpid()})
        while True:
            rec = {"event": "sample", "utc": utc_now_iso(),
                   "mono": round(time.monotonic() - start_mono, 3),
                   "meminfo": read_meminfo(),
                   "psi_memory": read_psi("/proc/pressure/memory"),
                   "psi_io": read_psi("/proc/pressure/io"),
                   "vmstat_swap": read_vmstat_swap()}
            table = proc_table()
            roots = []
            if pids_file and os.path.exists(pids_file):
                try:
                    with open(pids_file) as fh:
                        roots = [int(x) for x in fh.read().split() if x.isdigit()]
                except OSError:
                    roots = []
            if roots:
                live = descendants(table, set(roots))
                tasks = []
                for pid in sorted(live):
                    info = table[pid]
                    tasks.append({"pid": pid, "ppid": info["ppid"],
                                  "state": info["state"],
                                  "rss_kb": info["rss_kb"],
                                  "threads": info["threads"],
                                  "comm": info["comm"][:32]})
                rec["tasks"] = tasks
                rec["tasks_total_rss_kb"] = sum(t["rss_kb"] for t in tasks)
            # 采样器自身
            me = table.get(os.getpid())
            if me:
                rec["sampler_self_rss_kb"] = me["rss_kb"]
            emit(rec)
            # B4：MemAvailable < 2GiB 连续 3 次 + 换出增长 → 记录+marker
            mi = rec["meminfo"]
            if "MemAvailable" in mi:
                if mi["MemAvailable"] < 2 * 1024 * 1024:
                    mem_low_streak += 1
                else:
                    mem_low_streak = 0
                if mem_low_streak >= 3:
                    emit({"event": "protection_stop", "utc": utc_now_iso(),
                          "mem_available_kb": mi["MemAvailable"],
                          "streak": mem_low_streak})
                    try:
                        with open(marker, "a") as mf:
                            mf.write(f"protection_stop {utc_now_iso()}\n")
                    except OSError:
                        pass
            time.sleep(interval)


if __name__ == "__main__":
    main()
