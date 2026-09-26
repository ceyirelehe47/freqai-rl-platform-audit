#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R25 工程替身工作者探针(RouteC_R25_EntryProvenance_ReadbackClosure_v1)。

明确边界:本脚本不 import 任何研究生成模块、不生成任何研究语料;
只做有界 CPU/内存活动 + 心跳,用于验证修正后的 R25 启动链
(r25_batch_launcher_v2.sh 的 timeout --foreground 包装)下,
真实工作者(含子/孙进程)能进入 guest sampler 任务级遥测,
以及受控短超时后子树真实退出、无存活后代。

责任清理契约(timeout --foreground 语义):TERM 只发给工作者本身,
工作者负责终止自己派生的子进程,子进程负责终止孙进程;
--check-subtree-gone 独立核验无存活后代,不轻信退出码。

模式:
  burn  --seconds N:约 30% 单核计算负载持续 N 秒;--spawn-child 时
                     (线程内)派生子进程,子进程再派生孙进程;
  sleep --seconds N:纯睡眠(供短超时杀伤正例,同样可 --spawn-child);
  --check-subtree-gone --identity F:核验身份文件登记的 pid 及其全部
                     后代已从 /proc 消失(有界等待 15s)。
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

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


def _identity(label: str) -> dict:
    return {
        "label": label,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "pgid": os.getpgid(0),
        "sid": os.getsid(0),
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _spawn_child(seconds: float) -> subprocess.Popen:
    """派生子进程(孙进程由子进程派生);不阻塞调用方。"""
    return subprocess.Popen(
        [sys.executable, "-c", _CHILD_CODE, str(min(seconds, 3600.0))])


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


def _check_subtree_gone(identity_path: Path) -> int:
    ident = json.loads(identity_path.read_text(encoding="utf-8"))
    target = int(ident["pid"])
    survivors: list[int] = []
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        table = _proc_ppids()
        survivors = _descendants(table, target) \
            if target in table else []
        if not survivors:
            print(json.dumps({"subtree_check": "clean",
                              "target_pid": target}))
            return 0
        time.sleep(0.5)
    print(json.dumps({"subtree_check": "LEAKED",
                      "target_pid": target,
                      "survivors": survivors}))
    return 4


def _install_sigterm_cleanup() -> None:
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


def main(argv: list[str] | None = None) -> int:
    global _CHILD_PROC
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", default="worker")
    ap.add_argument("--mode", choices=("burn", "sleep"), default="burn")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--spawn-child", action="store_true")
    ap.add_argument("--heartbeat", default=None)
    ap.add_argument("--identity-out", default=None)
    ap.add_argument("--check-subtree-gone", action="store_true")
    ap.add_argument("--identity", default=None)
    args = ap.parse_args(argv)

    if args.check_subtree_gone:
        return _check_subtree_gone(Path(args.identity))

    ident = _identity(args.label)
    if args.identity_out:
        Path(args.identity_out).write_text(
            json.dumps(ident, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({**ident, "mode": args.mode,
                      "seconds": args.seconds}), flush=True)
    _install_sigterm_cleanup()
    if args.spawn_child:
        _CHILD_PROC = _spawn_child(args.seconds)
    if args.mode == "burn":
        _burn(args.seconds, args.label,
              Path(args.heartbeat or "/tmp/r25_worker_heartbeat.jsonl"))
    else:
        time.sleep(args.seconds)
    if _CHILD_PROC is not None and _CHILD_PROC.poll() is None:
        _CHILD_PROC.terminate()
        try:
            _CHILD_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _CHILD_PROC.kill()
            _CHILD_PROC.wait()
    print(json.dumps({**_identity(args.label), "ended": True}),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
