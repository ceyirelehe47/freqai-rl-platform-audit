# -*- coding: utf-8 -*-
"""运行原件保全(RouteC_PositionControl FiniteRepair R2 / R2-05)。

新入口从**启动起**原字节保全 stdout/stderr(fd 级 tee,含子进程)、
argv、环境关键项、时序、rc 与唯一运行 ID;最早的参数拒绝也留痕
(写 rejected_* 目录,**不消费业务额度**)。

R1 教训(两次 curriculum-eval 事故):输出被 grep 过滤、账本入账
代码在函数末段 ⇒ 崩溃后既无原件也无计量。R2 全部 runner 经
RunLog 包裹;失败现场停止不重写。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

_ENV_KEYS = ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE",
             "POSCTL_R2_LEDGER", "PATH", "CUDA_VISIBLE_DEVICES")


def _run_id() -> str:
    return (time.strftime("%Y%m%dT%H%M%S")
            + "_" + uuid.uuid4().hex[:8])


class RunLog:
    """fd 级 stdout/stderr 原字节 tee + 运行元数据落盘。

    用法:
        with RunLog(out_dir, argv=sys.argv) as rl:
            ... 业务 ...
            rl.rc = 0
        # 退出时自动写 run_meta.json(缺省 rc=非 0,异常路径也留痕)

    meta 字段:run_id/argv/env_subset/started/finished/duration_s/
    rc/host_python。tee 文件 = run_output.raw.txt(原字节,含 ANSI)。
    """

    def __init__(self, out_dir, argv=None, meta_extra=None) -> None:
        self.dir = Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.run_id = _run_id()
        self.argv = [str(a) for a in (argv if argv is not None
                                      else sys.argv)]
        self.meta_extra = dict(meta_extra or {})
        self.log_path = self.dir / "run_output.raw.txt"
        self.meta_path = self.dir / "run_meta.json"
        self.rc: int | None = None
        self._fh = None
        self._threads: list[threading.Thread] = []
        self._t0 = None

    # ------------------------------------------------------------ tee
    def __enter__(self) -> "RunLog":
        self._t0 = time.time()
        self._fh = open(self.log_path, "ab")
        self._orig = {"out": os.dup(1), "err": os.dup(2)}
        pipes = []
        for fd, _name in ((1, "out"), (2, "err")):
            r, w = os.pipe()
            os.dup2(w, fd)
            os.close(w)
            pipes.append((fd, r))
        for fd, r in pipes:
            t = threading.Thread(
                target=self._pump, args=(r, self._orig[
                    "out" if fd == 1 else "err"]), daemon=True)
            t.start()
            self._threads.append(t)
        self._write_meta(started=True)
        return self

    def _pump(self, rd: int, orig: int) -> None:
        try:
            while True:
                chunk = os.read(rd, 65536)
                if not chunk:
                    break
                os.write(orig, chunk)
                self._fh.write(chunk)
                self._fh.flush()
        finally:
            os.close(rd)

    def __exit__(self, exc_type, exc, tb) -> bool:
        # 先恢复 fd,再收线程,最后落 meta(异常也留痕)
        time.sleep(0.05)          # 尾部缓冲排空余量
        os.dup2(self._orig["out"], 1)
        os.dup2(self._orig["err"], 2)
        os.close(self._orig["out"])
        os.close(self._orig["err"])
        for t in self._threads:
            t.join(timeout=5.0)
        if exc is not None and self.rc is None:
            self.rc = -1
            self.meta_extra["exception"] = repr(exc)
            # 异常最终回溯原字节落盘(with 块外打印不经过 tee,
            # 在关闭日志前直接写入,保证失败原件完整)
            if self._fh is not None:
                import traceback
                self._fh.write(
                    ("\n[RunLog final traceback]\n"
                     + traceback.format_exc()).encode(
                         "utf-8", errors="replace"))
                self._fh.flush()
        if self._fh is not None:
            self._fh.close()
        if self.rc is None:
            self.rc = 1
        self._write_meta(started=False)
        return False            # 不吞异常

    # ------------------------------------------------------------ meta
    def _write_meta(self, *, started: bool) -> None:
        rec = {
            "run_id": self.run_id,
            "started_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._t0)),
            "phase": "started" if started else "finished",
            "argv": self.argv,
            "env_subset": {k: os.environ.get(k) for k in _ENV_KEYS},
            "cwd": os.getcwd(),
            "host_python": sys.version,
            **({"duration_s": round(time.time() - self._t0, 3)}
               if not started else {}),
            **({"rc": self.rc} if not started else {}),
            **self.meta_extra,
        }
        tmp = self.meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.meta_path)


def write_rejection(out_root, stage: str, reason: str,
                    argv=None, extra=None) -> Path:
    """参数/前置校验拒绝留痕(最早的拒绝也不丢;不消费业务额度)。

    写 <out_root>/rejected_<ts>_<id>/rejection.json(create-only)。
    返回目录路径;拒绝记录写失败时抛出(不静默吞)。
    """
    root = Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    d = root / f"rejected_{_run_id()}"
    d.mkdir(parents=False, exist_ok=False)
    rec = {
        "run_id": d.name,
        "stage": stage,
        "reason": reason,
        "argv": [str(a) for a in (argv if argv is not None
                                  else sys.argv)],
        "rejected_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                      time.gmtime()),
        "budget_consumed": False,
        **(extra or {}),
    }
    (d / "rejection.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return d
