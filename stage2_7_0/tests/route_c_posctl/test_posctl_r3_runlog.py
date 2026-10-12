# -*- coding: utf-8 -*-
"""R3-02 原字节日志(FiniteRepair R3;toy 真子进程,不运行模型)。

覆盖 reviewer F2 四反例 + 验收要求的 toy 矩阵:buffered print、
原字节 fd 输出(CRLF/CR/NUL)、跨大块、stdout/stderr 分流、异常
回溯、控制台先关闭、父包装退出后子进程继续输出、硬退出(os._exit
后已提交管道的字节可恢复)、正常/强制终止区分;单流字节严格保序,
原字节不筛选重建;不把 started 当完整、缺终态 rc 不猜 0。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from rl_posctl.runlog import PERSIST_PROCESS, RunLog

SRC = str(Path(__file__).resolve().parents[2] / "src")
PY = sys.executable


def _wait_status(out_dir: Path, timeout=30.0):
    p = out_dir / "run_output.status.json"
    t0 = time.time()
    while time.time() - t0 < timeout:
        if p.exists():
            try:
                st = json.loads(p.read_text(encoding="utf-8"))
                if st.get("phase") == "logger_exit":
                    return st
            except ValueError:
                pass
        time.sleep(0.1)
    return None


class TestToyOriginals:
    def test_buffered_print_and_normal_exit(self, tmp_path):
        """buffered print(不 flush)也必须进原件(旧:文件只有
        stderr 标记);正常退出 rc=0、complete。"""
        out = tmp_path / "s1"
        code = (
            "from rl_posctl.runlog import RunLog\n"
            "with RunLog({!r}) as rl:\n".format(str(out))
            + "    print('PY_STDOUT_MARKER')\n"
            + "    sys.stderr.write('PY_STDERR_MARKER\\n')\n"
            + "    rl.rc = 0\n")
        r = subprocess.run(
            [PY, "-c", "import sys; sys.path.insert(0,{!r})\n".format(
                SRC) + code],
            capture_output=True, text=True, timeout=90)
        raw = (out / "run_output.raw.txt").read_bytes()
        assert b"PY_STDOUT_MARKER" in raw
        assert b"PY_STDERR_MARKER" in raw
        meta = json.loads(
            (out / "run_meta.json").read_text(encoding="utf-8"))
        assert meta["phase"] == "finished"
        assert meta["rc"] == 0 and meta["rc_known"] is True
        st = _wait_status(out)
        assert st is not None and st["complete"] is True

    def test_raw_bytes_preserved_exact_per_stream(self, tmp_path):
        """原字节 CRLF/CR/NUL 逐位保全(单流内严格保序;不经筛选
        重建)。"""
        out = tmp_path / "s2"
        payload_out = b"OUT\r\nRAW\rEND\nBIG" + b"X" * 200000 + b"\n"
        payload_err = b"ERR\x00RAW\n"
        d = tmp_path / "s2d"
        d.mkdir()
        f = d / "in.bin"
        f.write_bytes(payload_out)
        f2 = d / "in_err.bin"
        f2.write_bytes(payload_err)
        code = (
            "import os as _os\n"
            "def _wall(fd, data):\n"
            "    off = 0\n"
            "    while off < len(data):\n"
            "        off += _os.write(fd, data[off:])\n"
            "from rl_posctl.runlog import RunLog\n"
            "fo = open({!r},'rb').read()\n".format(str(f))
            + "fe = open({!r},'rb').read()\n".format(str(f2))
            + "with RunLog({!r}) as rl:\n".format(str(out))
            + "    _wall(1, fo)\n"
            + "    _wall(2, fe)\n"
            + "    _wall(1, b'TAIL_STDOUT')\n"
            + "    rl.rc = 0\n")
        r = subprocess.run(
            [PY, "-c", "import sys, os; sys.path.insert(0,{!r})\n"
             .format(SRC) + code],
            capture_output=True, timeout=90)
        raw = (out / "run_output.raw.txt").read_bytes()
        # 单流字节严格保序(子序列);跨流为到达序合并,不保证
        # 连续;字节总量精确(无丢失/无添加/不经筛选重建)。
        def _subseq_pos(hay: bytes, needle: bytes) -> int:
            i = 0
            for b in needle:
                i = hay.find(bytes([b]), i)
                if i < 0:
                    return -1
                i += 1
            return i
        assert len(raw) == (len(payload_out) + len(payload_err)
                            + len(b"TAIL_STDOUT"))
        assert payload_err in raw
        end_payload = _subseq_pos(raw, payload_out)
        assert end_payload > 0
        assert _subseq_pos(raw[end_payload:],
                           b"TAIL_STDOUT") > 0

    def test_exception_traceback_and_rc(self, tmp_path):
        out = tmp_path / "s3"
        code = (
            "from rl_posctl.runlog import RunLog\n"
            "with RunLog({!r}) as rl:\n".format(str(out))
            + "    raise RuntimeError('boom-marker')\n")
        r = subprocess.run(
            [PY, "-c", "import sys; sys.path.insert(0,{!r})\n".format(
                SRC) + code],
            capture_output=True, text=True, timeout=90)
        assert r.returncode == 1
        raw = (out / "run_output.raw.txt").read_bytes()
        assert b"boom-marker" in raw
        meta = json.loads(
            (out / "run_meta.json").read_text(encoding="utf-8"))
        assert meta["rc"] == -1
        assert meta["exception"] == "RuntimeError('boom-marker')"

    def test_hard_exit_recovers_submitted_bytes(self, tmp_path):
        """os.write 返回后立即 os._exit(9):已离开用户态进入管道
        的字节由持久进程恢复落盘;meta 停在 started(缺终态不猜
        0),状态文件是最终证词。仍在被杀进程用户态未 flush 的
        字节不承诺恢复(边界)。"""
        out = tmp_path / "s4"
        code = (
            "from rl_posctl.runlog import RunLog\n"
            "rl = RunLog({!r}).__enter__()\n".format(str(out))
            + "os.write(1, b'HARDEXIT_MARKER\\n')\n"
            + "os._exit(9)\n")
        r = subprocess.run(
            [PY, "-c", "import sys, os; sys.path.insert(0,{!r})\n"
             .format(SRC) + code],
            capture_output=True, timeout=90)
        assert r.returncode == 9
        st = _wait_status(out)
        assert st is not None and st["complete"] is True
        raw = (out / "run_output.raw.txt").read_bytes()
        assert b"HARDEXIT_MARKER" in raw
        # 进程被杀:无 finished meta,不虚构 rc
        meta = json.loads(
            (out / "run_meta.json").read_text(encoding="utf-8"))
        assert meta["phase"] == "started"
        assert "rc" not in meta

    def test_console_closed_file_persists(self, tmp_path):
        """控制台读端先关闭:业务输出仍保全到原件,控制台转发
        错误被计数,不因等控制台卡死(旧:BrokenPipe 中断泵,
        业务标记丢失而主进程 rc=0)。"""
        out = tmp_path / "s5"
        code = (
            "from rl_posctl.runlog import RunLog\n"
            "rl = RunLog({!r}, drain_timeout=8).__enter__()\n"
            .format(str(out))
            + "os.write(1, b'BUSINESS_MARKER_BEFORE\\n')\n"
            + "os.write(2, b'BUSINESS_STDERR\\n')\n"
            + "os.kill(os.getpid(), signal.SIGKILL)\n")
        r_, w = os.pipe()
        p = subprocess.Popen(
            [PY, "-c", "import sys, os, signal; sys.path.insert("
             "0,{!r})\n".format(SRC) + code],
            stdout=w, stderr=subprocess.STDOUT)
        os.close(w)
        os.close(r_)            # 控制台读端立即消失
        p.wait(timeout=90)
        st = _wait_status(out)
        assert st is not None
        assert st["console_write_errors"] >= 1
        raw = (out / "run_output.raw.txt").read_bytes()
        assert b"BUSINESS_MARKER_BEFORE" in raw

    def test_parent_exits_grandchild_continues(self, tmp_path):
        """父包装 with 块先退;孙进程后续输出继续由持久进程保全
        (EOF 驱动,不靠固定 sleep)。"""
        out = tmp_path / "s6"
        gc = tmp_path / "grandchild.py"
        gc.write_text(
            "import os, time\n"
            "for i in range(8):\n"
            "    os.write(1, ('GC_LINE_%d\\n' % i).encode())\n"
            "    time.sleep(0.05)\n", encoding="utf-8")
        drv = tmp_path / "s6_driver.py"
        drv.write_text(
            "import sys, subprocess, os\n"
            "sys.path.insert(0, {!r})\n".format(SRC)
            + "from rl_posctl.runlog import RunLog\n"
            "with RunLog({!r}, drain_timeout=30) as rl:\n".format(
                str(out))
            + "    p = subprocess.Popen([sys.executable, "
            "{!r}])\n".format(str(gc))
            + "    os.write(1, b'PARENT_LEAVES\\n')\n"
            "    rl.rc = 0\n"
            "sys.exit(p.wait())\n", encoding="utf-8")
        r = subprocess.run([PY, str(drv)], capture_output=True,
                           text=True, timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        st = _wait_status(out)
        assert st is not None and st["complete"] is True
        raw = (out / "run_output.raw.txt").read_bytes()
        for i in range(8):
            assert ("GC_LINE_%d" % i).encode() in raw
        assert b"PARENT_LEAVES" in raw


class TestRunLogUnit:
    def test_refuse_mixed_write_into_existing_log(self, tmp_path):
        """日志原件已存在 → 拒绝混写旧 run(create-only)。"""
        d = tmp_path / "mix"
        d.mkdir()
        (d / "run_output.raw.txt").write_text("OLD", encoding="utf-8")
        with pytest.raises(RuntimeError, match="混写旧 run"):
            RunLog(d)

    def test_rejection_record_is_not_budget_consumption(
            self, tmp_path):
        from rl_posctl.runlog import write_rejection
        d = write_rejection(tmp_path, "stage-x", "原因",
                            argv=["a"])
        rec = json.loads(
            (d / "rejection.json").read_text(encoding="utf-8"))
        assert rec["budget_consumed"] is False
        assert rec["reason"] == "原因"

    @pytest.mark.skipif(not PERSIST_PROCESS,
                        reason="本平台无 fork,回退线程模式")
    def test_meta_declares_persist_mode(self, tmp_path):
        out = tmp_path / "s7"
        code = (
            "from rl_posctl.runlog import RunLog\n"
            "with RunLog({!r}) as rl:\n".format(str(out))
            + "    rl.rc = 3\n")
        subprocess.run(
            [PY, "-c", "import sys; sys.path.insert(0,{!r})\n".format(
                SRC) + code],
            capture_output=True, timeout=90)
        meta = json.loads(
            (out / "run_meta.json").read_text(encoding="utf-8"))
        assert meta["persist_process"] is PERSIST_PROCESS
        assert meta["rc"] == 3
