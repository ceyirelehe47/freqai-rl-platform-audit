#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R25 工程替身工作者探针(RouteC_R25_BindingAndDescendantClosure_v1 版)。

明确边界:本脚本不 import 任何研究生成模块、不生成任何研究语料;
只做有界 CPU/内存活动 + 心跳 + 进程实例登记,用于验证修正后的 R25
启动链(r25_batch_launcher_v2.sh 的 timeout --foreground 包装)下,
真实工作者(含子/孙进程)能进入 guest sampler 任务级遥测,以及受控
短超时后**已登记实例逐一退出**的核验。

C3-orphan-check 修复(本轮核心):
  旧 checker 只记根 PID,根退出后按当前 PPID 树找后代——根已消失时
  把后代集合当空、对存活孤儿返回 clean(独立审查已复现:根 PID 890
  退出、子 PID 900 存活,checker 返回 clean)。本版:
  1. 退出前登记:创建子/孙后**立即**把本任务实际拥有的实例身份
     (pid + /proc stat field22 starttime ticks,可区分同 PID 不同
     实例)写入持久 registry 文件(可靠持有者,不随根退出消失);
  2. checker(--check-registry)只读、逐实例核验,不依赖根存在:
     /proc 消失=dead_gone;存活且 starttime 一致=alive(必非
     clean);state Z=zombie_unreaped;starttime 不一致=
     pid_reused_old_dead(旧实例必已结束,不向新实例发信号);
     无法读取=unobservable(不 clean);
  3. registry 缺失/不完整/无法证明"确实未创建后代"→ 不 clean;
     空登记不默认成功;
  4. 清理与检测分离:checker 永不发信号;由驱动器/launcher 对
     (pid, start_ticks) 双重匹配的自有实例收尾。

模式:
  burn  --seconds N:~30% 单核负载;--spawn-child 派生合作子进程
                     (子再派生孙,均带 SIGTERM 责任清理);
  sleep --seconds N:纯睡眠(供短超时杀伤正例);
  orphan --seconds N:工程负例夹具——派生**无清理**的子/孙,握手后
                     写登记并立即退出,留下存活孤儿供 checker 反例;
  --check-registry F:只读核验登记文件(上述规则 2/3)。

退出码(check-registry):0=clean;2=存在僵尸(已终止未回收);
3=存在存活本任务实例;4=登记缺失/不完整;5=无法观测。
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REGISTRY_FORMAT = "r25-worker-registry-v1"
_CHILD_PROC: subprocess.Popen | None = None

_CHILD_CODE = r"""
import json, os, signal, subprocess, sys, time
g = subprocess.Popen([sys.executable, "-c",
                      "import time\nwhile True: time.sleep(3600)"])
print(json.dumps({"role": "child", "pid": os.getpid(),
                  "grandchild": g.pid}), flush=True)

def _term(signum, frame):
    g.terminate()
    try:
        g.wait(timeout=5)
    except subprocess.TimeoutExpired:
        g.kill(); g.wait()
    sys.exit(128 + signum)

signal.signal(signal.SIGTERM, _term)
try:
    time.sleep(float(sys.argv[1]))
finally:
    g.terminate()
    try:
        g.wait(timeout=5)
    except subprocess.TimeoutExpired:
        g.kill(); g.wait()
"""


# orphan 模式专用:子/孙均为无信号处理的纯睡眠者(负例需要"没被
# 谁清理"的存活后代;TTL 由驱动器参数限定,外部 finally 兜底回收)。
_ORPHAN_CHILD_CODE = r"""
import json, os, subprocess, sys, time
ttl = str(float(sys.argv[1]))
g = subprocess.Popen([sys.executable, "-c",
                      "import sys, time\ntime.sleep(float(sys.argv[1]))",
                      ttl])
print(json.dumps({"role": "orphan-child", "pid": os.getpid(),
                  "grandchild": g.pid}), flush=True)
time.sleep(float(ttl))
"""


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _identity(label: str) -> dict:
    return {
        "label": label,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "pgid": os.getpgid(0),
        "sid": os.getsid(0),
        "utc": _utc(),
    }


def _proc_ppids() -> dict[int, int]:
    out: dict[int, int] = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", encoding="utf-8") as fh:
                text = fh.read()
            rp = text.rindex(")")
            out[int(name)] = int(text[rp + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
    return out


def _proc_instance(pid: int) -> tuple[bool, str, int] | None:
    """(exists, state, start_ticks);None=无法观测。"""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return (False, "", -1)
    except OSError:
        return None
    try:
        rp = text.rindex(")")
        fields = text[rp + 2:].split()
        return (True, fields[0], int(fields[19]))  # state, starttime
    except (ValueError, IndexError):
        return None


def _descendants(table: dict[int, int], root: int) -> list[int]:
    children: dict[int, list[int]] = {}
    for pid, ppid in table.items():
        children.setdefault(ppid, []).append(pid)
    found: list[int] = []
    stack = [root]
    while stack:
        cur = stack.pop()
        if cur in found:
            continue
        found.append(cur)
        stack.extend(children.get(cur, ()))
    return found


def _spawn_child(seconds: float) -> tuple[subprocess.Popen, int, int]:
    """合作子进程(孙由子派生,均带 SIGTERM 责任清理);返回
    (proc, child_pid, grandchild_pid),经 stdout 握手获得 pids。"""
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD_CODE, str(min(seconds, 3600.0))],
        stdout=subprocess.PIPE, text=True)
    line = proc.stdout.readline()
    info = json.loads(line)
    return proc, int(info["pid"]), int(info["grandchild"])


def _write_registry(path: Path, *, label: str,
                    child: tuple[int, int] | None,
                    grand: int | None) -> None:
    """在允许根退出/进入长循环前登记本任务实例身份(持久持有者)。"""
    root_inst = _proc_instance(os.getpid())
    instances = [{"pid": os.getpid(),
                  "start_ticks": root_inst[2] if root_inst else -1,
                  "role": "root"}]
    created = False
    if child is not None:
        created = True
        ci = _proc_instance(child[0])
        instances.append({"pid": child[0],
                          "start_ticks": child[1]
                          if child[1] >= 0 else (ci[2] if ci else -1),
                          "role": "child"})
        if grand is not None:
            gi = _proc_instance(grand)
            instances.append({"pid": grand,
                              "start_ticks": gi[2] if gi else -1,
                              "role": "grandchild"})
    registry = {
        "format": REGISTRY_FORMAT,
        "created_utc": _utc(),
        "driver_label": label,
        "root_pid": os.getpid(),
        "created_descendants": created,
        # created_descendants=False 时:由创建者(本进程,未 spawn 任何
        # 子进程)显式声明并记录依据;空登记不默认成功。
        "no_descendants_verified": (not created),
        "no_descendants_basis": ("创建者未调用任何 spawn(--spawn-child "
                                 "未提供)") if not created else None,
        "instances": instances,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=1, ensure_ascii=False)
                    + "\n", encoding="utf-8")


def _check_registry(path: Path) -> int:
    """只读核验(绝不禁令/杀进程);按登记逐实例判定。"""
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "registry_invalid",
                          "rc": 4, "reason": str(exc)}))
        return 4
    if not isinstance(registry, dict) \
            or registry.get("format") != REGISTRY_FORMAT:
        print(json.dumps({"verdict": "registry_invalid", "rc": 4,
                          "reason": "format 不符"}))
        return 4
    instances = registry.get("instances")
    if not isinstance(instances, list) or not instances:
        print(json.dumps({"verdict": "registry_incomplete", "rc": 4,
                          "reason": "instances 缺失/为空(空登记不默认"
                                    "成功)"}))
        return 4
    for inst in instances:
        if not isinstance(inst, dict) or \
                not isinstance(inst.get("pid"), int) or \
                not isinstance(inst.get("start_ticks"), int):
            print(json.dumps({"verdict": "registry_incomplete", "rc": 4,
                              "reason": f"实例条目不完整: {inst!r}"}))
            return 4
    if not registry.get("created_descendants") and \
            not registry.get("no_descendants_verified"):
        print(json.dumps({"verdict": "registry_incomplete", "rc": 4,
                          "reason": "无后代声明缺可信依据"}))
        return 4

    results = []
    rc = 0
    for inst in instances:
        obs = _proc_instance(inst["pid"])
        if obs is None:
            status = "unobservable"
            rc = max(rc, 5)
        elif not obs[0]:
            status = "dead_gone"
        elif obs[2] != inst["start_ticks"]:
            # 同 PID 不同 starttime:实例身份不匹配——旧实例必已
            # 退出回收(pid 才可能被复用);不向新实例发信号。
            status = "pid_reused_old_dead"
        elif obs[1] == "Z":
            status = "zombie_unreaped"
            rc = max(rc, 2)
        else:
            status = "alive"
            rc = max(rc, 3)
        results.append({**inst, "status": status})
    verdict = {0: "clean", 2: "zombie_unreaped", 3: "leaked_alive",
               5: "unobservable"}[rc]
    print(json.dumps({"verdict": verdict, "rc": rc,
                      "checked_utc": _utc(),
                      "instances": results}, ensure_ascii=False))
    return rc


def _burn(seconds: float, label: str, heartbeat: Path) -> None:
    deadline = time.monotonic() + seconds
    n = 0
    with open(heartbeat, "a", encoding="utf-8") as fh:
        while time.monotonic() < deadline:
            t0 = time.monotonic()
            while time.monotonic() - t0 < 0.03:  # ~30ms 计算脉冲
                n += 1
                _ = sum(i * i for i in range(2000))
            fh.write(json.dumps(
                {**_identity(label), "iter": n}, ensure_ascii=False)
                + "\n")
            fh.flush()
            time.sleep(0.07)  # ~30% 单核,轻负载


def _install_sigterm_cleanup(child_pid: int | None) -> None:
    def _handler(signum, frame):
        if _CHILD_PROC is not None and _CHILD_PROC.poll() is None:
            _CHILD_PROC.terminate()
            try:
                _CHILD_PROC.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _CHILD_PROC.kill()
                _CHILD_PROC.wait()
        sys.exit(128 + signum)
    signal.signal(signal.SIGTERM, _handler)


def _terminate_child() -> None:
    if _CHILD_PROC is not None and _CHILD_PROC.poll() is None:
        _CHILD_PROC.terminate()
        try:
            _CHILD_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _CHILD_PROC.kill()
            _CHILD_PROC.wait()


def main(argv: list[str] | None = None) -> int:
    global _CHILD_PROC
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", default="worker")
    ap.add_argument("--mode",
                    choices=("burn", "sleep", "orphan"), default="burn")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--spawn-child", action="store_true")
    ap.add_argument("--heartbeat", default=None)
    ap.add_argument("--identity-out", default=None)
    ap.add_argument("--registry-out", default=None)
    ap.add_argument("--check-registry", action="store_true")
    ap.add_argument("--identity", default=None)
    args = ap.parse_args(argv)

    if args.check_registry:
        return _check_registry(Path(args.identity))

    ident = _identity(args.label)
    if args.identity_out:
        Path(args.identity_out).write_text(
            json.dumps(ident, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({**ident, "mode": args.mode,
                      "seconds": args.seconds}), flush=True)
    _install_sigterm_cleanup(None)
    registry_path = Path(args.registry_out) if args.registry_out else None

    if args.mode == "orphan":
        # 工程负例:留下无清理的存活子/孙后立即退出(不调用
        # _terminate_child;TTL 有限,驱动器 finally 兜底回收)。
        proc = subprocess.Popen(
            [sys.executable, "-c", _ORPHAN_CHILD_CODE,
             str(min(args.seconds, 300.0))],
            stdout=subprocess.PIPE, text=True)
        info = json.loads(proc.stdout.readline())
        if registry_path:
            _write_registry(
                registry_path, label=args.label,
                child=(int(info["pid"]), -1), grand=int(info["grandchild"]))
        print(json.dumps({"role": "orphan-root", "pid": os.getpid(),
                          "child": info["pid"],
                          "grandchild": info["grandchild"],
                          "registry": str(registry_path)}), flush=True)
        proc.stdout.close()
        return 0  # 立即退出,不等待不清理

    child_info: tuple[int, int] | None = None
    grand_pid: int | None = None
    if args.spawn_child:
        _CHILD_PROC, child_pid, grand_pid = _spawn_child(args.seconds)
        child_info = (child_pid, -1)
    if registry_path:
        # 进入长循环/退出前完成登记(先握手后登记,不靠 sleep 抢竞态)
        _write_registry(registry_path, label=args.label,
                        child=child_info, grand=grand_pid)
    if args.mode == "burn":
        _burn(args.seconds, args.label,
              Path(args.heartbeat or "/tmp/r25_worker_heartbeat.jsonl"))
    else:
        time.sleep(args.seconds)
    _terminate_child()
    print(json.dumps({**_identity(args.label), "ended": True}),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
