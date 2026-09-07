# -*- coding: utf-8 -*-
"""RSS-01 反例:main() 异常分支不推进停止升级/退出确认(接手版实测)。

真实 main() 入口(replay 观测源);业务=装 SIG_IGN 的 leader+真实子孙;
READY 文件证明 TERM 忽略已安装(先于异常注入);主循环异常注入
(pump raise);R17ALERT 通知通道持续阻塞;另设独立邻居进程。

缺陷形态(预期在接手版复现):main() 返回 3 时——
  - protector.term_sent=True 但 kill_sent=False(合作窗满不升级)
  - 业务 leader 与子孙仍存活
  - biz_rc=None(退出码从未观察)
  - 无残留核验;邻居应存活(不受牵连)

用法(WSL):
  R17U_SNAP=$HOME/r17u_snap_handover \
  python3 probe_rss01_exception_shutdown.py <输出json路径>
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SNAP = Path(os.environ["R17U_SNAP"])
OUT = Path(sys.argv[1])
BASE = Path(os.environ.get("R17U_BASE") or
            Path.home() / f"r17u_probe_rss01_{int(time.time())}")
BASE.mkdir(parents=True, exist_ok=True)

BIZ_SRC = r'''
import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pid = os.fork()          # 真实子孙:同进程组、同样忽略 TERM
if pid == 0:
    time.sleep(600)
with open(sys.argv[1], "w") as fh:
    fh.write(str(os.getpid()))
time.sleep(600)
'''

# 子进程:真实 main() 入口;READY 后注入主循环异常;R17ALERT 阻塞。
CHILD_SRC = r'''
import json, os, sys, threading, time
snap, base = sys.argv[1], sys.argv[2]
sys.path.insert(0, snap)
import r17_supervision as rs
Supervisor = rs.Supervisor
ready = os.path.join(base, "biz_ready.marker")

real_pump = Supervisor._pump_win_lines
def boom(self2, mono):
    # READY 证明(TERM 忽略已安装)先于异常注入(§7 U02 反例同款要求)
    deadline = time.time() + 30
    while not os.path.exists(ready):
        if time.time() > deadline:
            raise RuntimeError("probe: biz READY 未出现(注入放弃)")
        time.sleep(0.1)
    print("PROBE_INJECT", flush=True)
    raise RuntimeError("probe-injected pump failure")
Supervisor._pump_win_lines = boom

real_sync = Supervisor._stdout_sync
gate = threading.Event()
hit = threading.Event()
def blocked_sync(self2, tag, line):
    if tag == "R17ALERT" and not hit.is_set():
        hit.set()
        print("PROBE_ALERT_BLOCKED", flush=True)
        gate.wait(60.0)          # 通知通道持续阻塞(写线程侧)
    return real_sync(self2, tag, line)
Supervisor._stdout_sync = blocked_sync

import datetime as _dt
def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
win = {"event": "sample", "seq": 1, "utc": utc_now(),
       "perf": {"phys_avail_gb": 39.0, "commit_total_gb": 38.0,
                "commit_limit_gb": 83.0, "phys_total_gb": 63.0},
       "vols": [
           {"vol": "F:", "present": True, "free_gb": 100.0,
            "size_gb": 500.0, "serial": "CFA1", "identity_match": True},
           {"vol": "C:", "present": True, "free_gb": 200.0,
            "size_gb": 900.0, "serial": "CCA1", "identity_match": True}],
       "telemetry_out_writable": True}
guest = {"event": "guest_sample", "utc": utc_now(),
         "meminfo": {"MemTotal": 40_000_000, "MemAvailable": 39_000_000},
         "psi_memory": {"full_avg10": 0.0}, "vmstat_swap": {"pswpout": 0}}
samples = os.path.join(base, "samples.jsonl")
with open(samples, "w") as fh:
    fh.write(json.dumps({"win": win, "guest": guest}) + "\n")

sys.argv = ["r17_supervision.py",
            "--run-dir", os.path.join(base, "run"),
            "--task-kind", "fixture", "--max-seconds", "300",
            "--samples-source", "file:" + samples,
            "--obs-ready-deadline", "30",
            "--", sys.executable,
            os.path.join(base, "biz_ignore_term.py"), ready]
from r17_supervision import main as sup_main
rc = sup_main()
print("PROBE_MAIN_RC=%d" % rc, flush=True)
gate.set()   # 让写线程(若仍活着)释放,便于子进程退出
sys.exit(0)
'''


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def group_members(pgid: int) -> list[int]:
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as fh:
                text = fh.read()
            fields = text[text.rindex(")") + 2:].split()
            if int(fields[2]) == pgid and fields[0] != "Z":
                out.append(int(name))
        except (OSError, ValueError, IndexError):
            continue
    return out


def main() -> None:
    base = BASE
    (base / "biz_ignore_term.py").write_text(BIZ_SRC, encoding="utf-8")
    (base / "runner_child.py").write_text(CHILD_SRC, encoding="utf-8")
    ready = base / "biz_ready.marker"

    # 邻居:独立会话的无关进程(不属于任何被登记组)
    neighbor = subprocess.Popen(
        ["sleep", "300"], start_new_session=True)
    child = subprocess.Popen(
        [sys.executable, str(base / "runner_child.py"),
         str(SNAP), str(base)], start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    deadline = time.time() + 150
    lines: list[str] = []
    biz_pid = None
    summary = None
    child_rc = None
    while time.time() < deadline:
        if child.poll() is not None:
            child_rc = child.returncode
            break
        if ready.exists() and biz_pid is None:
            biz_pid = int(ready.read_text().strip())
        time.sleep(0.5)
    if child_rc is None:  # watchdog 兜底(测试侧;不计入产品行为)
        child.kill()
        child_rc = child.wait()
        lines.append("PROBE_WATCHDOG_KILLED_CHILD")
    out = child.communicate()[0].decode("utf-8", "replace")
    lines.extend(ln for ln in out.splitlines() if ln.startswith("PROBE"))

    sdir = base / "run"
    for cand in (sdir / "summary.json",):
        if cand.is_file():
            summary = json.loads(cand.read_text(encoding="utf-8"))
    prot = (summary or {}).get("business", {}).get("protector") or {}
    pgid = prot.get("pgid")
    time.sleep(2.0)  # 观察"返回后仍存活"是否持续(非退出中)
    members = group_members(pgid) if pgid else []
    result = {
        "probe": "rss01_exception_shutdown",
        "child_rc": child_rc,
        "main_returned_3": "PROBE_MAIN_RC=3" in " ".join(lines),
        "injected_after_ready": "PROBE_INJECT" in " ".join(lines),
        "alert_blocked": "PROBE_ALERT_BLOCKED" in " ".join(lines),
        "watchdog_used": "PROBE_WATCHDOG_KILLED_CHILD" in " ".join(lines),
        "term_sent": bool(prot.get("term_sent")),
        "kill_sent": bool(prot.get("kill_sent")),
        "terminal_confirmed": bool(prot.get("terminal_confirmed")),
        "biz_rc_in_summary": (summary or {}).get("business", {}).get("rc"),
        "biz_leader_pid": biz_pid,
        "biz_leader_alive_after_return": alive(biz_pid) if biz_pid else None,
        "biz_group_alive_after_return": bool(members),
        "biz_group_members": members[:8],
        "neighbor_pid": neighbor.pid,
        "neighbor_alive": alive(neighbor.pid),
        "lines": lines,
    }
    result["reproduced"] = bool(
        result["main_returned_3"] and result["term_sent"]
        and not result["kill_sent"]
        and result["biz_leader_alive_after_return"]
        and result["biz_group_alive_after_return"]
        and result["neighbor_alive"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    # 测试侧清理:只杀本 probe 建立的目标(业务组+邻居)
    if pgid and pgid > 1:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass
    if biz_pid and alive(biz_pid):
        try:
            os.kill(biz_pid, signal.SIGKILL)
        except OSError:
            pass
    neighbor.terminate()
    neighbor.wait(timeout=10)


if __name__ == "__main__":
    main()
