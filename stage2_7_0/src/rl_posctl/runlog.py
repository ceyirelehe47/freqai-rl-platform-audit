# -*- coding: utf-8 -*-
"""运行原件保全(RouteC_PositionControl FiniteRepair R2→R3)。

新入口从**启动起**原字节保全 stdout/stderr(fd 级 tee,含子进程)、
argv、环境关键项、时序、rc 与唯一运行 ID;最早的参数拒绝也留痕
(写 rejected_* 目录,**不消费业务额度**)。

R1 教训(两次 curriculum-eval 事故):输出被 grep 过滤、账本入账
代码在函数末段 ⇒ 崩溃后既无原件也无计量。全部 runner 经 RunLog
包裹;失败现场停止不重写。

R3 重设(FiniteRepair R3 / FINDINGS R3-02,reviewer F2;旧实现的
四个实测反例:buffered print 丢失 / 控制台断连丢业务输出但 rc=0 /
os.write 后硬退出日志全空 / 固定 sleep 代替排空):
- **持久原件优先**:有 fork 时,日志由独立持久进程持有——业务
  进程(及其子进程)的输出经管道进入持久进程,**先写文件**、
  再尽力转发控制台;控制台故障(断连/BrokenPipe/停滞)只计
  console_write_errors,不影响原件继续落盘,也不因等控制台卡住;
- 业务进程硬退出(os._exit/SIGKILL)后,持久进程继续排空管道中
  **已离开业务进程用户态**的字节并落盘(status 文件为最终证词);
  仍在被杀进程用户态 Python 缓冲里未 flush 的字节不承诺恢复
  (边界如实记录,不把 started 当完整);
- 退出顺序:先 flush Python 文本缓冲(buffered print 进管道)→
  再恢复控制台 fd → 通知持久进程进入限时排空(等 EOF,不靠固定
  sleep)→ 收取状态;父包装先退时,子进程后续输出仍由持久进程
  排空到 EOF 或截止(deadline 内)并如实标记 truncated;
- 终态区分:参数拒绝(rejected_*,无业务额度)vs started-only
  (进程被杀,无 finished meta)vs finished(rc 已知/异常=−1)+
  持久进程状态(bytes_file/console_errors/truncated)。缺终态 rc
  不猜成 0(finished meta 只在明确得知 rc 时写 rc);
- 合并原件 run_output.raw.txt 的跨流(stdout/stderr)顺序 = 到达
  序近似(两管道单读者);**单流内字节顺序严格保持**,原字节
  (CRLF/CR/NUL/ANSI)不经过筛选重建(与 R2 行为一致);
- 无 fork 平台(Windows)回退线程泵(file-first 同语义),meta
  如实标注 persist_process=false。
"""

from __future__ import annotations

import json
import os
import select
import sys
import threading
import time
import uuid
from pathlib import Path

_ENV_KEYS = ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE",
             "POSCTL_R2_LEDGER", "POSCTL_R3_LEDGER", "PATH",
             "CUDA_VISIBLE_DEVICES")

PERSIST_PROCESS = hasattr(os, "fork")


def _run_id() -> str:
    return (time.strftime("%Y%m%dT%H%M%S")
            + "_" + uuid.uuid4().hex[:8])


def _write_all(fd: int, data: bytes) -> None:
    """fd 级全量写(处理部分写)。"""
    off = 0
    while off < len(data):
        off += os.write(fd, data[off:])


def _logger_loop(out_rd, err_rd, ctrl_rd, status_wr, file_fd,
                 console_fds: dict, status_path: str) -> None:
    """持久日志进程主循环(仅 os 级调用;经 fork 进入,永不返回)。

    - 文件先写(os.write file_fd),控制台转发尽力而为(非阻塞,
      失败/停滞只计数,绝不影响原件,也绝不卡住原件通道);
    - 控制通道收到 DRAIN <秒> 或 EOF(业务进程死亡)后进入限时
      排空:数据管道双双 EOF = complete;到截止仍有数据 = truncated
      (如实标记,不虚报完整);
    - 结束前把状态 JSON 同时写状态管道与状态文件(管道给在场的
      业务进程,文件给任何后来的读者——业务进程死亡也不丢证词)。
    """
    open_fds = {out_rd, err_rd, ctrl_rd}
    deadline = None
    bytes_file = bytes_out = bytes_err = 0
    console_errors = 0
    last_console_error = ""
    truncated = False
    stop_reason = ""
    fd_map = {out_rd: "out", err_rd: "err", ctrl_rd: "ctrl"}
    console_of = {"out": console_fds["out"], "err": console_fds["err"]}
    end_of = {"out": False, "err": False}
    # 控制台转发非阻塞:读端失联(满/停滞)立即放弃转发
    for cfd in console_of.values():
        try:
            os.set_blocking(cfd, False)
        except OSError:
            pass
    try:
        while open_fds:
            timeout = None
            if deadline is not None:
                timeout = max(0.0, deadline - time.time())
                if timeout <= 0.0 and not (
                        end_of["out"] and end_of["err"]):
                    truncated = True
                    stop_reason = ("drain deadline reached with data"
                                   " pipe(s) still open(后续输出未"
                                   "保全,如实截断)")
                    break
            try:
                ready, _, _ = select.select(
                    list(open_fds), [], [], timeout)
            except InterruptedError:
                continue
            if not ready:
                continue
            for fd in ready:
                if fd == ctrl_rd:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        open_fds.discard(fd)
                        os.close(fd)
                        # 业务进程死亡/退出:限时排空(给管道与
                        # 仍在写的子进程足够窗口)
                        if deadline is None:
                            deadline = time.time() + 30.0
                        continue
                    text = chunk.decode("utf-8", errors="replace")
                    for line in text.splitlines():
                        if line.startswith("DRAIN"):
                            try:
                                secs = float(line.split()[1])
                            except (IndexError, ValueError):
                                secs = 30.0
                            deadline = time.time() + max(0.05, secs)
                        elif line.strip() == "STOPNOW":
                            deadline = time.time() - 1.0
                    continue
                stream = fd_map[fd]
                chunk = os.read(fd, 65536)
                if not chunk:
                    end_of[stream] = True
                    open_fds.discard(fd)
                    os.close(fd)
                    continue
                _write_all(file_fd, chunk)     # 原件优先
                bytes_file += len(chunk)
                if stream == "out":
                    bytes_out += len(chunk)
                else:
                    bytes_err += len(chunk)
                try:
                    _write_all(console_of[stream], chunk)
                except BlockingIOError:
                    console_errors += 1
                    last_console_error = (
                        "console fd not accepting data (EAGAIN);"
                        " forwarding skipped, file preserved")
                except OSError as exc:
                    console_errors += 1
                    last_console_error = repr(exc)
    except BaseException as exc:        # 持久进程自身的如实证词
        truncated = True
        stop_reason = f"logger loop error: {exc!r}"
    complete = end_of["out"] and end_of["err"]
    status = {
        "phase": "logger_exit",
        "persist_kind": "process",
        "bytes_file": bytes_file,
        "bytes_stdout": bytes_out,
        "bytes_stderr": bytes_err,
        "console_write_errors": console_errors,
        "last_console_error": last_console_error or None,
        "complete": bool(complete and not truncated),
        "both_streams_eof": bool(complete),
        "truncated": bool(truncated),
        "stop_reason": stop_reason or None,
        "drain_deadline_was_set": deadline is not None,
        "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                   time.gmtime()),
    }
    try:
        os.fsync(file_fd)
        os.close(file_fd)
    except OSError:
        pass
    payload = (json.dumps(status, ensure_ascii=False)
               + "\n").encode("utf-8")
    try:
        sp = os.open(status_path,
                     os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        _write_all(sp, payload)
        os.fsync(sp)
        os.close(sp)
    except OSError:
        pass
    try:
        _write_all(status_wr, payload)
        os.close(status_wr)
    except OSError:
        pass
    for fd in set(console_of.values()):
        try:
            os.close(fd)
        except OSError:
            pass
    os._exit(0)


class RunLog:
    """fd 级 stdout/stderr 原字节 tee + 运行元数据落盘。

    用法:
        with RunLog(out_dir, argv=sys.argv) as rl:
            ... 业务 ...
            rl.rc = 0
        # 退出时自动写 run_meta.json(未设置 rc 时如实标注
        # rc_known=false——缺终态不猜 0;异常路径 rc=-1 留痕)

    文件:run_output.raw.txt(原字节,stdout/stderr 合并,含 ANSI/
    CRLF/NUL)、run_output.status.json(持久进程状态:字节数/控制台
    转发错误/是否完整或截断)、run_meta.json(运行身份与终态)。
    """

    def __init__(self, out_dir, argv=None, meta_extra=None, *,
                 drain_timeout: float = 60.0,
                 wait_status_timeout: float = 20.0) -> None:
        self.dir = Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.run_id = _run_id()
        self.argv = [str(a) for a in (argv if argv is not None
                                      else sys.argv)]
        self.meta_extra = dict(meta_extra or {})
        self.log_path = self.dir / "run_output.raw.txt"
        self.meta_path = self.dir / "run_meta.json"
        self.status_path = self.dir / "run_output.status.json"
        self.rc = None
        self.drain_timeout = float(drain_timeout)
        self.wait_status_timeout = float(wait_status_timeout)
        self._output_status = None
        self._logger_pid = None
        self._threads = []
        self._thread_status = None
        self._thread_lock = threading.Lock()
        self._ctrl_w = None
        self._stat_r = None
        self._t0 = None
        if self.log_path.exists():
            raise RuntimeError(
                f"日志原件已存在,拒绝混写旧 run(create-only):"
                f"{self.log_path};请使用新运行目录")

    # ------------------------------------------------------------ enter
    def __enter__(self) -> "RunLog":
        self._t0 = time.time()
        file_fd = os.open(self.log_path,
                          os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        console_out = os.dup(1)
        console_err = os.dup(2)
        out_r, out_w = os.pipe()
        err_r, err_w = os.pipe()
        ctrl_r, ctrl_w = os.pipe()
        stat_r, stat_w = os.pipe()
        self._console = {"out": console_out, "err": console_err}
        if PERSIST_PROCESS:
            pid = os.fork()
            if pid == 0:
                # ---- 持久日志进程:只保留需要的 fd,其余关闭
                try:
                    os.close(out_w)
                    os.close(err_w)
                    os.close(ctrl_w)
                    os.close(stat_r)
                    _logger_loop(out_r, err_r, ctrl_r, stat_w,
                                 file_fd,
                                 {"out": console_out,
                                  "err": console_err},
                                 str(self.status_path))
                except BaseException:
                    os._exit(70)
                os._exit(0)
            # ---- 业务进程(父)
            self._logger_pid = pid
            os.close(out_r)
            os.close(err_r)
            os.close(ctrl_r)
            os.close(stat_w)
            os.close(file_fd)          # 文件由持久进程独占
            self._ctrl_w = ctrl_w
            self._stat_r = stat_r
        else:
            # 无 fork 平台回退:线程泵,文件优先同语义(能力如实标注)
            os.close(ctrl_r)
            os.close(ctrl_w)
            os.close(stat_r)
            os.close(stat_w)
            self._thread_status = {
                "persist_kind": "threads",
                "bytes_file": 0, "console_write_errors": 0,
                "last_console_error": None}
            for rd, stream, cfd in ((out_r, "out", console_out),
                                    (err_r, "err", console_err)):
                t = threading.Thread(
                    target=self._thread_pump,
                    args=(rd, stream, cfd, file_fd), daemon=True)
                t.start()
                self._threads.append(t)
            self._thread_file_fd = file_fd
        os.dup2(out_w, 1)
        os.dup2(err_w, 2)
        os.close(out_w)
        os.close(err_w)
        self._write_meta(started=True)
        return self

    # ------------------------------------------------------------ pump
    def _thread_pump(self, rd: int, stream: str, console_fd: int,
                     file_fd: int) -> None:
        """回退线程泵:文件先写;控制台尽力(失败计数不中断)。"""
        try:
            while True:
                chunk = os.read(rd, 65536)
                if not chunk:
                    break
                _write_all(file_fd, chunk)
                with self._thread_lock:
                    self._thread_status["bytes_file"] += len(chunk)
                try:
                    _write_all(console_fd, chunk)
                except OSError as exc:
                    with self._thread_lock:
                        self._thread_status[
                            "console_write_errors"] += 1
                        self._thread_status[
                            "last_console_error"] = repr(exc)
        finally:
            os.close(rd)

    # ------------------------------------------------------------ exit
    def __exit__(self, exc_type, exc, tb) -> bool:
        # 1) 先 flush Python 文本缓冲:buffered print 的字节进入
        #    管道(旧实现先恢复 fd,缓冲内容直奔控制台而漏出原件)
        for s in (sys.stdout, sys.stderr):
            try:
                s.flush()
            except (ValueError, OSError):
                pass
        # 2) 异常最终回溯原字节落盘:写入管道(fd1 尚未恢复),
        #    由持久进程/线程收进原件
        if exc is not None and self.rc is None:
            self.rc = -1
            self.meta_extra["exception"] = repr(exc)
            import traceback
            try:
                _write_all(1, ("\n[RunLog final traceback]\n"
                               + traceback.format_exc())
                           .encode("utf-8", errors="replace"))
            except OSError:
                pass
        # 3) 恢复控制台 fd(此后 print 直接到控制台,不再入原件)
        try:
            os.dup2(self._console["out"], 1)
            os.dup2(self._console["err"], 2)
            os.close(self._console["out"])
            os.close(self._console["err"])
        except OSError:
            pass
        # 4) 通知排空并收状态(EOF 驱动,不靠固定 sleep)
        if PERSIST_PROCESS and self._logger_pid is not None:
            try:
                _write_all(self._ctrl_w,
                           ("DRAIN %s\n" % self.drain_timeout)
                           .encode("ascii"))
                os.close(self._ctrl_w)
            except OSError:
                pass
            self._output_status = self._await_logger_status()
        elif self._threads:
            t_end = time.time() + self.drain_timeout
            for t in self._threads:
                t.join(timeout=max(0.05, t_end - time.time()))
            alive = [t for t in self._threads if t.is_alive()]
            with self._thread_lock:
                st = dict(self._thread_status)
            st.update({
                "phase": "logger_exit",
                "complete": not alive,
                "truncated": bool(alive),
                "stop_reason": ("thread pump(s) still alive at drain"
                                " deadline" if alive else None),
                "ended_utc": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            try:
                os.fsync(self._thread_file_fd)
                os.close(self._thread_file_fd)
            except OSError:
                pass
            self._output_status = st
        if self.rc is None:
            self.rc = 1
        self._write_meta(started=False)
        return False            # 不吞异常

    def _await_logger_status(self):
        """限时等待持久进程状态;超时不杀(其后仍在排空,状态文件
        为最终证词),meta 如实标注 still_draining。"""
        deadline = time.time() + self.wait_status_timeout
        got = None
        buf = bytearray()
        while time.time() < deadline:
            try:
                ready, _, _ = select.select(
                    [self._stat_r], [], [],
                    max(0.0, deadline - time.time()))
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                chunk = os.read(self._stat_r, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf.extend(chunk)
            try:
                got = json.loads(bytes(buf).decode(
                    "utf-8", errors="replace").strip())
                break
            except ValueError:
                continue
        try:
            os.close(self._stat_r)
        except OSError:
            pass
        # 已取到状态 ⇒ logger 即将退出,可阻塞收尸;未取到(仍在
        # 排空)⇒ 只非阻塞探收,不悬挂业务进程
        self._reap_logger(block=bool(got is not None))
        if got is None:
            got = {"phase": "logger_alive",
                   "persist_kind": "process",
                   "still_draining": True,
                   "note": ("状态未在等待窗口内送达;最终证词见 "
                            + self.status_path.name)}
        return got

    def _reap_logger(self, block: bool) -> None:
        if self._logger_pid is None:
            return
        try:
            if block:
                os.waitpid(self._logger_pid, 0)
            else:
                os.waitpid(self._logger_pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            self._logger_pid = None

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
            "persist_process": bool(PERSIST_PROCESS),
        }
        if not started:
            rec["duration_s"] = round(time.time() - self._t0, 3)
            # rc 仅在明确得知时写入;进程被杀时无 finished meta,
            # 缺终态不猜 0。正常退出业务必须设 rl.rc。
            rec["rc"] = self.rc
            rec["rc_known"] = True
            if self._output_status is not None:
                rec["output_status"] = self._output_status
            rec["output_status_path"] = self.status_path.name
        rec.update(self.meta_extra)
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
