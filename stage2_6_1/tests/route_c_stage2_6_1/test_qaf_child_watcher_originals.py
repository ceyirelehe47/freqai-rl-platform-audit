# -*- coding: utf-8 -*-
"""RouteC_CueAudit_FormalIdentityClosure_v1:CI08 观察器/原件测试。

- 观察器(qaf_child_watcher)三类终止形态与 create-only 输出:
  运行中→rc 已落盘→结束 / 异常结束(无 rc) / 停止请求;
  目标日志暂未存在只记录不报错;max_ticks 用尽如实记录。
- operator 完整原件落盘(write_child_log_originals):
  create-only、摘要/argv/cwd/rc 元数据、已存在即拒。
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

_BASE = Path(__file__).resolve().parents
TREE = next(b for b in _BASE if (b / "src" / "rl_curriculum").is_dir()
            or (b / "stage2_6_1" / "src" / "rl_curriculum").is_dir())
RUNNER_DIR = (TREE / "stage2_6_1" / "runner"
              if (TREE / "stage2_6_1" / "src" / "rl_curriculum").is_dir()
              else TREE / "stage2_6_1_runner")
if not (RUNNER_DIR / "qaf_child_watcher.py").is_file():
    # 部署树映射(stage2_6_1/runner -> $D/stage2_6_1_runner)
    RUNNER_DIR = Path.home() / "projects" / "crypto_rl" / (
        "stage2_6_1_runner")
sys.path.insert(0, str(RUNNER_DIR))

from qaf_child_watcher import ChildWatcher, main as watcher_main  # noqa: E402


def _spawn_marker_child(tmp_path, marker, lifetime, write_rc):
    alive = str(tmp_path / (marker + ".alive"))
    rc = str(tmp_path / (marker + ".rc"))
    code = (
        "import time\n"
        "open(%r, 'w').close()\n"
        "time.sleep(%r)\n" % (alive, float(lifetime))
    )
    if write_rc:
        code += "open(%r, 'w').write('0')\n" % rc
    return subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _run_watcher_thread(w):
    import threading
    box = {}

    def _go():
        box["rc"] = w.run()

    t = threading.Thread(target=_go)
    t.start()
    return t, box


def test_normal_termination_rc_recorded(tmp_path):
    """运行中→rc 落盘→结束:确认 tick 后 reason=rc_recorded。"""
    marker = f"wm{os.getpid()}a"
    child = _spawn_marker_child(tmp_path, marker, 0.4, write_rc=True)
    out = tmp_path / "watch.jsonl"
    w = ChildWatcher(pattern=marker, rc_file=tmp_path / f"{marker}.rc",
                     out_file=out, target_log=tmp_path / "nope.log",
                     interval_s=0.05, max_ticks=200)
    t, box = _run_watcher_thread(w)
    t.join(timeout=30)
    child.wait(timeout=30)
    assert not t.is_alive()
    assert box["rc"] == 0
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    finals = [r for r in rows if "final_reason" in r]
    assert finals[-1]["final_reason"] == "rc_recorded_and_process_ended"
    assert any(r["target_log"]["present"] is False for r in rows)
    # 存在"运行中"与"已结束"两类采样(真实生命周期观察到)
    assert any(r["target_alive"] for r in rows)
    assert any(not r["target_alive"] for r in rows)


def test_abnormal_end_no_rc(tmp_path):
    """异常结束:进程被杀且无 rc → grace 后 reason=abnormal_end。"""
    marker = f"wm{os.getpid()}b"
    child = _spawn_marker_child(tmp_path, marker, 30, write_rc=False)
    time.sleep(0.3)  # 让观察器先看到 alive
    out = tmp_path / "watch.jsonl"
    w = ChildWatcher(pattern=marker, rc_file=tmp_path / f"{marker}.rc",
                     out_file=out, interval_s=0.05, max_ticks=400,
                     grace_ticks=2)
    t, box = _run_watcher_thread(w)
    time.sleep(0.3)
    child.send_signal(signal.SIGKILL)
    child.wait(timeout=30)
    t.join(timeout=30)
    assert not t.is_alive()
    assert box["rc"] == 0
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    finals = [r for r in rows if "final_reason" in r]
    assert finals[-1]["final_reason"] == "abnormal_end_no_rc"


def test_stop_file_freezes_watcher(tmp_path):
    """停止请求:stop 文件出现即退出(封包前冻结诊断写入源)。"""
    marker = f"wm{os.getpid()}c"
    child = _spawn_marker_child(tmp_path, marker, 30, write_rc=False)
    time.sleep(0.2)
    stop = tmp_path / "stop"
    out = tmp_path / "watch.jsonl"
    w = ChildWatcher(pattern=marker, rc_file=tmp_path / f"{marker}.rc",
                     out_file=out, stop_file=stop, interval_s=0.05,
                     max_ticks=400)
    t, box = _run_watcher_thread(w)
    time.sleep(0.2)
    stop.write_text("", encoding="utf-8")
    t.join(timeout=30)
    child.send_signal(signal.SIGKILL)
    child.wait(timeout=30)
    assert box["rc"] == 0
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert rows[-1]["final_reason"] == "stop_requested"
    size = out.stat().st_size
    time.sleep(0.2)  # 静态性:退出后不再写
    assert out.stat().st_size == size


def test_create_only_output_refused(tmp_path):
    out = tmp_path / "watch.jsonl"
    out.write_text("{}", encoding="utf-8")
    w = ChildWatcher(pattern="none-such", rc_file=tmp_path / "rc",
                     out_file=out, interval_s=0.01, max_ticks=1)
    assert w.run() == 2
    assert out.read_text() == "{}"  # 原文件未被触碰


def test_max_ticks_exhausted(tmp_path):
    w = ChildWatcher(pattern="none-such", rc_file=tmp_path / "rc",
                     out_file=tmp_path / "w.jsonl", interval_s=0.01,
                     max_ticks=2)
    assert w.run() == 3
    rows = [json.loads(x) for x in
            (tmp_path / "w.jsonl").read_text().splitlines()]
    assert rows[-1]["final_reason"] == "max_ticks_exhausted"


def test_operator_child_log_originals(tmp_path):
    """operator 完整原件:create-only、元数据(argv/cwd/rc/摘要)、
    已存在即拒(fail closed)。"""
    sys.path.insert(0, str(RUNNER_DIR))
    import importlib
    op = importlib.import_module("qaf_v2_operator_entry")
    argv = [sys.executable, "launch", "--flag", "v"]
    stdout = "x" * 20_000
    stderr = "e" * 300
    op.write_child_log_originals(
        tmp_path, child="launch", argv=argv, cwd="/w", returncode=7,
        stdout=stdout, stderr=stderr)
    d = tmp_path / "operator_child_logs"
    got_out = (d / "execute_launch.stdout.full.txt").read_text("utf-8")
    assert got_out == stdout  # 完整原件,无 8000 截断
    assert (d / "execute_launch.stderr.full.txt").read_text(
        "utf-8") == stderr
    meta = json.loads(
        (d / "execute_launch.meta.json").read_text("utf-8"))
    import hashlib
    assert meta["argv"] == argv and meta["cwd"] == "/w"
    assert meta["returncode"] == 7
    assert meta["stdout_bytes"] == 20_000
    assert meta["stdout_sha256"] == hashlib.sha256(
        stdout.encode()).hexdigest()
    with pytest.raises(FileExistsError):
        op.write_child_log_originals(
            tmp_path, child="launch", argv=argv, cwd="/w",
            returncode=7, stdout=stdout, stderr=stderr)
