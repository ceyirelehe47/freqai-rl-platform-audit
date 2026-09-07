#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RCF-02 接手快照反例:主线程持 writer 锁时 SIGTERM → handler 内
log 重入普通 threading.Lock → 同线程死锁。

用法: probe_signal_deadlock.py <快照仓库根> <工作临时目录>

父进程起真实子进程(import 快照模块,真实 Supervisor.run,replay
输入 + 业务 bash sleep 30)。子进程经测试挂钩把**首次 stdout 提交**
暂停在 BoundedIOWriter.submit 持锁区间内(put_nowait 处,打印
PROBE_HOLDING_LOCK 后有界暂停 8s),父进程据此发送真实 SIGTERM,
限时观察子进程:

  旧实现:handler 执行 self.log → iow.submit → with self._lock
    (主线程自持,普通 Lock 不可重入) → handler 永不返回 → 子进程
    永不退出 → 父进程 SIGKILL 兜底 → 反例成立(handler_did_not_
    return;停止意图/保护停摆);
  修复后:handler 立即返回(只登记意图),挂钩超时释放,run() 推进,
    正常控制路径消费停止意图 → 业务收 TERM → run() 有界返回。

外部 watchdog:父进程全程有界(等待上限 60s),SIGKILL 只是测试
兜底,不宣称被测 supervisor 成功保护。
退出码 0=反例成立(旧死锁复现),2=未复现(handler 已能返回),
3=脚本自身错误。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
WORK = Path(sys.argv[2]).resolve()

CHILD_SRC = r'''
import argparse, json, os, sys, threading, time
repo, base = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(repo, "stage2_6_1", "runner"))
from r17_supervision import Supervisor

import datetime as _dt
def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")

samples_path = os.path.join(base, "samples.jsonl")
perf = {"phys_avail_gb": 39.0, "commit_total_gb": 38.0,
        "commit_limit_gb": 83.0, "phys_total_gb": 63.0}
vols = [
    {"vol": "F:", "present": True, "free_gb": 100.0,
     "size_gb": 500.0, "serial": "CFA1", "identity_match": True},
    {"vol": "C:", "present": True, "free_gb": 200.0,
     "size_gb": 900.0, "serial": "CCA1", "identity_match": True}]
win = {"event": "sample", "seq": 1, "utc": utc_now(), "perf": perf,
       "vols": vols, "telemetry_out_writable": True}
guest = {"event": "guest_sample", "utc": utc_now(),
         "meminfo": {"MemTotal": 40_000_000, "MemAvailable": 39_000_000},
         "psi_memory": {"full_avg10": 0.0},
         "vmstat_swap": {"pswpout": 0}}
with open(samples_path, "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"win": win, "guest": guest}) + "\n")

args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=["bash", "-c", "sleep 30"], task_cwd=None, max_seconds=0,
    samples_source="file:" + samples_path,
    win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=30.0)
sup = Supervisor(args)

# 测试挂钩:第 2 次 stdout 提交(=business_started,replay 正常
# 序列 supervisor_start→business_started→supervisor_end;此时生产
# handler 已安装、业务已 spawn)暂停在 submit 持锁区间(put_nowait
# 之前已取得 writer Lock;挂钩只控制时序,不改锁与停止判断)。
# 首版反例挂在第 1 次提交(handler 注册之前)→SIGTERM 默认行为
# 直接杀死子进程(exit=-15)——顺带证实注册前窗口无受控收尾。
real_put = sup.iow._q.put_nowait
hit = threading.Event()
count = {"n": 0}
def hooked(act):
    if act.get("role") == "stdout":
        count["n"] += 1
        if count["n"] == 2 and not hit.is_set():
            hit.set()
            print("PROBE_HOLDING_LOCK", flush=True)
            time.sleep(8.0)
    return real_put(act)
sup.iow._q.put_nowait = hooked

rc = sup.run()
print("PROBE_RUN_RC=%d" % rc, flush=True)
sys.exit(0)
'''


def main() -> int:
    result: dict = {"probe": "rcf02_signal_deadlock",
                    "repo": str(REPO)}
    try:
        base = WORK / "rcf02"
        if base.exists():
            import shutil
            shutil.rmtree(base)
        base.mkdir(parents=True)
        child_path = base / "child_probe.py"
        child_path.write_text(CHILD_SRC, encoding="utf-8")

        py = sys.executable
        p = subprocess.Popen(
            [py, str(child_path), str(REPO), str(base)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, start_new_session=True)
        lines: list[str] = []
        holding = threading.Event()

        def _reader():
            for ln in p.stdout:  # 阻塞读直到 EOF
                ln = ln.rstrip("\n")
                lines.append(ln)
                if "PROBE_HOLDING_LOCK" in ln:
                    holding.set()

        rt = threading.Thread(target=_reader, daemon=True)
        rt.start()
        if not holding.wait(30.0):
            result["probe_result"] = "SCRIPT_ERROR"
            result["error"] = "30s 内未见 PROBE_HOLDING_LOCK(挂钩未命中)"
            result["child_output"] = lines
            p.kill()
            p.wait(timeout=10)
            print(json.dumps(result, ensure_ascii=False, indent=1))
            return 3
        result["holding_lock_seen_at"] = time.time()
        time.sleep(0.5)  # 确认主线程确实停在持锁区间
        p.send_signal(signal.SIGTERM)  # 真实 SIGTERM
        result["sigterm_sent"] = True
        # 有界观察:挂钩自身 8s 释放;正常收尾(就绪/准入/停止消费/
        # 业务 TERM 退出/finalize)在工程夹具下应数十秒内完成
        deadline = time.time() + 50.0
        rc = None
        while time.time() < deadline:
            rc = p.poll()
            if rc is not None:
                break
            time.sleep(0.2)
        if rc is None:
            # handler 未返回 → 主线程死锁 → 子进程不退出
            p.kill()
            p.wait(timeout=10)
            result["child_exit"] = "killed_by_probe_watchdog"
            result["handler_returned"] = False
            result["probe_result"] = "REPRODUCED"
            result["note"] = ("SIGTERM 后 50s 子进程未退出:handler 内 "
                              "log 重入 writer Lock 同线程死锁,停止"
                              "意图无人消费(handler_did_not_return)")
        else:
            result["child_exit"] = rc
            result["handler_returned"] = True
            result["probe_result"] = "NOT_REPRODUCED"
            result["note"] = ("handler 已能返回/子进程有界退出"
                              "(停止链由正常控制路径消费)")
        rt.join(timeout=5)
        result["child_output"] = lines
    except Exception as exc:  # noqa: BLE001 —— 反例脚本如实报自身错误
        result["probe_result"] = "SCRIPT_ERROR"
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["probe_result"] == "REPRODUCED" else 2


if __name__ == "__main__":
    sys.exit(main())
