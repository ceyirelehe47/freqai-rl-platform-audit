# -*- coding: utf-8 -*-
"""R17 统一有界收尾/停止截止点/异常组合(任务书 U/L 矩阵可夹具化项)。

真实模块为主:runner 的 r17_supervision(发布树或 WSL 开发树同步面);
真实短命子进程+事件屏障(挂钩点=实际方法边界,不靠 stdout 次数猜
阶段);外部 watchdog 只做测试兜底(不计入产品行为)。故障注入仅限
测试自己的文件、进程与隔离工程状态(生产入口不暴露注入通道);
u02 保留真实策略身份(coop=30s),其余缩窗项在用例内标注。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


def _find_runner_dir() -> Path:
    here = Path(__file__).resolve()
    for cand in (
            here.parents[3] / "stage2_6_1" / "runner",
            Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner"),
            Path.home() / "projects/crypto_rl/stage2_6_1_runner",
    ):
        if (cand / "r17_supervision.py").is_file():
            return cand
    raise FileNotFoundError("runner 执行面不可达")


RUNNER_DIR = _find_runner_dir()
sys.path.insert(0, str(RUNNER_DIR))

from r17_supervision import Supervisor  # noqa: E402

requires_linux = pytest.mark.skipif(
    os.name == "nt", reason="控制路径执行面只在 Linux/WSL 跑")


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _utc():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _write_samples(path: Path, n: int = 40) -> None:
    win = {"event": "sample", "seq": 1, "utc": _utc(),
           "perf": {"phys_avail_gb": 39.0, "commit_total_gb": 38.0,
                    "commit_limit_gb": 83.0, "phys_total_gb": 63.0},
           "vols": [
               {"vol": "F:", "present": True, "free_gb": 100.0,
                "size_gb": 500.0, "serial": "CFA1",
                "identity_match": True},
               {"vol": "C:", "present": True, "free_gb": 200.0,
                "size_gb": 900.0, "serial": "CCA1",
                "identity_match": True}],
           "telemetry_out_writable": True}
    guest = {"event": "guest_sample", "utc": _utc(),
             "meminfo": {"MemTotal": 40_000_000, "MemAvailable": 39_000_000},
             "psi_memory": {"full_avg10": 0.0},
             "vmstat_swap": {"pswpout": 0}}
    with path.open("w", encoding="utf-8") as fh:
        for _ in range(n):
            fh.write(json.dumps({"win": win, "guest": guest}) + "\n")


def _sup(base, argv=("--", "true"), task_kind="fixture"):
    """进程内构造(主线程;handler 可注册)。"""
    argv = list(argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    sp = base / "samples.jsonl"
    _write_samples(sp)
    args = argparse.Namespace(
        run_dir=str(base / "run"), task_kind=task_kind,
        argv=argv, task_cwd=None, max_seconds=0,
        samples_source="file:" + str(sp),
        win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
        expect_artifact=[], obs_ready_deadline=30.0)
    return Supervisor(args)


# 子进程模板:参数化 mode;挂钩点=实际方法边界;u02 走真实 main(),
# 其余走真实 run();l02 系在明确事件屏障向自身发真实 TERM。
USH_CHILD_SRC = r'''
import argparse, json, os, signal, sys, threading, time
runner_dir, base, mode = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, runner_dir)
from r17_supervision import Supervisor

import datetime as _dt
def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
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
         "psi_memory": {"full_avg10": 0.0}, "vmstat_swap": {"pswpout": 0}}
samples_path = os.path.join(base, "samples.jsonl")
with open(samples_path, "w", encoding="utf-8") as fh:
    for _ in range(40):
        fh.write(json.dumps({"win": win, "guest": guest}) + "\n")

argv = ["bash", "-c", "sleep 30"]
if mode == "u02":
    argv = [sys.executable, os.path.join(base, "biz_ignore_term.py"),
            os.path.join(base, "biz_ready.marker")]
elif mode == "u04a":
    argv = ["bash", "-c", "sleep 60 & exit 0"]  # leader 退+同组子孙活
elif mode in ("l02a", "l02b", "l02c", "l02d"):
    argv = ["bash", "-c", "sleep 1"]

fired = {"v": False}
def fire(tag):
    if not fired["v"]:
        fired["v"] = True
        print("PROBE_FIRED_AT=" + tag, flush=True)
        os.kill(os.getpid(), signal.SIGTERM)

if mode == "u02":
    # READY 证明(TERM 忽略已安装)先于异常注入;R17ALERT 通道持续
    # 阻塞(写线程侧);真实 main() 入口;保留真实 coop=30s 身份。
    ready = os.path.join(base, "biz_ready.marker")
    real_pump = Supervisor._pump_win_lines
    def boom(self2, mono):
        deadline = time.time() + 30
        while not os.path.exists(ready):
            if time.time() > deadline:
                raise RuntimeError("probe: biz READY 未出现")
            time.sleep(0.1)
        print("PROBE_INJECT", flush=True)
        raise RuntimeError("probe-injected pump failure")
    Supervisor._pump_win_lines = boom
    real_sync = Supervisor._stdout_sync
    gate = threading.Event()
    hit = threading.Event()
    def blocked_sync(self2, tag2, line):
        if tag2 == "R17ALERT" and not hit.is_set():
            hit.set()
            print("PROBE_ALERT_BLOCKED", flush=True)
            gate.wait(60.0)
        return real_sync(self2, tag2, line)
    Supervisor._stdout_sync = blocked_sync
    sys.argv = ["r17_supervision.py",
                "--run-dir", os.path.join(base, "run"),
                "--task-kind", "fixture", "--max-seconds", "300",
                "--samples-source", "file:" + samples_path,
                "--obs-ready-deadline", "30",
                "--"] + argv
    from r17_supervision import main as sup_main
    rc = sup_main()
    gate.set()
    print("PROBE_RUN_RC=%d" % rc, flush=True)
    sys.exit(rc if 0 <= rc < 256 else 0)

args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=argv, task_cwd=None, max_seconds=0,
    samples_source="file:" + samples_path,
    win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=30.0)
sup = Supervisor(args)

if mode == "u03a":
    # 注入点=统一收尾循环内(_terminal_state_confirmed 只被
    # _terminal_shutdown 调用):crash 已发生、handler 仍安装、
    # finalize 未开始——第二信号精确落进收尾窗口。
    real_pump = Supervisor._pump_win_lines
    calls = {"n": 0}
    def boom(self2, mono):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RuntimeError("probe-injected pump failure")
        return real_pump(self2, mono)
    Supervisor._pump_win_lines = boom
    real_tsc = Supervisor._terminal_state_confirmed
    hit2 = {"v": False}
    def hooked_tsc(self2):
        if not hit2["v"]:
            hit2["v"] = True
            print("PROBE_INJECT", flush=True)
            os.kill(os.getpid(), signal.SIGTERM)
        return real_tsc(self2)
    Supervisor._terminal_state_confirmed = hooked_tsc
elif mode == "l02a":
    real_fin = Supervisor.finalize
    def hooked_fin(self2):
        fire("finalize_begin")
        return real_fin(self2)
    Supervisor.finalize = hooked_fin
elif mode == "l02b":
    real_drain = sup.iow.drain
    def hooked_drain(timeout):
        fire("drain")
        return real_drain(timeout)
    sup.iow.drain = hooked_drain
elif mode == "l02c":
    real_ws = Supervisor.write_summary
    def hooked_ws(self2):
        fire("pre_summary")
        return real_ws(self2)
    Supervisor.write_summary = hooked_ws
elif mode == "l02d":
    # 真正的 C 后屏障:finalize() 完全返回(检查点④与 C 设点均已
    # 越)之后、结果决策之前的信号。finalize_run_record 之后、④
    # 之前的窗口由 l02c 的④捕获路径实证覆盖,不在此重复。
    real_fin = Supervisor.finalize
    def hooked_fin(self2):
        out = real_fin(self2)
        fire("post_finalize")
        return out
    Supervisor.finalize = hooked_fin
elif mode == "u06":
    real_adm = Supervisor.admission_check
    def hooked_adm(self2, win, guest_rec):
        res = real_adm(self2, win, guest_rec)
        fire("admission_done")
        return res
    Supervisor.admission_check = hooked_adm

rc = sup.run()
print("PROBE_RUN_RC=%d" % rc, flush=True)
sys.exit(rc if 0 <= rc < 256 else 0)
'''

BIZ_IGNORE_SRC = r'''
import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pid = os.fork()
if pid == 0:
    time.sleep(600)
with open(sys.argv[1], "w") as fh:
    fh.write(str(os.getpid()))
time.sleep(600)
'''


def _run_child(tmp_path, mode, *, expect_marker=None, sig=None,
               max_wait=60.0, marker_wait=30.0, delay_after_marker=0.5):
    """真实子进程;marker 事件定位;真实信号;有界退出观察;
    watchdog SIGKILL 仅测试兜底(单独记录,不计入产品行为)。"""
    base = tmp_path / mode
    base.mkdir(parents=True, exist_ok=True)
    if mode == "u02":
        (base / "biz_ignore_term.py").write_text(
            BIZ_IGNORE_SRC, encoding="utf-8")
    child = base / "ush_child.py"
    child.write_text(USH_CHILD_SRC, encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, str(child), str(RUNNER_DIR), str(base), mode],
        start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines: list[str] = []
    reader_done = threading.Event()

    def _reader():
        for ln in p.stdout:
            lines.append(ln.decode("utf-8", "replace").rstrip())
        reader_done.set()
    threading.Thread(target=_reader, daemon=True).start()
    if expect_marker:
        deadline = time.time() + marker_wait
        while time.time() < deadline:
            if any(expect_marker in ln for ln in lines):
                break
            time.sleep(0.2)
        else:
            p.kill()
            p.wait(timeout=10)
            reader_done.wait(timeout=5)
            pytest.fail(f"marker {expect_marker} 未出现;lines={lines[-8:]}")
        time.sleep(delay_after_marker)
    if sig is not None:
        p.send_signal(sig)
    rc = None
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if p.poll() is not None:
            rc = p.returncode
            break
        time.sleep(0.3)
    if rc is None:
        p.kill()  # 测试 watchdog 兜底
        rc = p.wait(timeout=10)
        lines.append("PROBE_WATCHDOG_KILLED")
    reader_done.wait(timeout=5)
    return rc, lines, base / "run"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ================================================= U02 异常组合(真实身份)
@requires_linux
class TestU02ExceptionCombo:
    def test_u02_exception_ignoring_term_business_killed_by_supervisor(
            self, tmp_path):
        """U02:READY 证明后注入主循环异常+通知持续阻塞+真实子孙+邻居
        ——忽略 TERM 的业务由被测 supervisor 自己 KILL 并确认退出;
        邻居存活;watchdog 不参与。保留真实 coop=30s 策略身份。"""
        neighbor = subprocess.Popen(
            ["sleep", "120"], start_new_session=True)
        biz_pgid = None
        try:
            rc, lines, run_dir = _run_child(
                tmp_path, "u02", expect_marker="PROBE_ALERT_BLOCKED",
                marker_wait=60, max_wait=120)
            assert "PROBE_WATCHDOG_KILLED" not in " ".join(lines), \
                "watchdog 兜底被触发=被测 supervisor 未在有界内完成"
            assert any("PROBE_RUN_RC=3" in ln for ln in lines)
            assert "PROBE_INJECT" in " ".join(lines), "异常注入已发生"
            summary = _load(run_dir / "summary.json")
            prot = summary["business"]["protector"]
            assert prot["term_sent"] is True
            assert prot["kill_sent"] is True, \
                "业务忽略 TERM:合作窗满必须由 supervisor 升级 KILL"
            assert prot["terminal_confirmed"] is True
            assert summary["business"]["rc"] == -9, \
                "KILL 后实际退出码被观察"
            biz_pgid = prot["pgid"]
            rr = _load(run_dir / "run_record.json")
            assert rr["evidence_complete"] is False, \
                "通知通道阻塞→drain 未确认→不签完整"
            assert _alive(neighbor.pid), "邻居不得被牵连"
        finally:
            if biz_pgid and biz_pgid > 1:
                try:
                    os.killpg(biz_pgid, signal.SIGKILL)
                except OSError:
                    pass
            neighbor.kill()
            neighbor.wait(timeout=10)


# ================================================= U03 同一停止链
@requires_linux
class TestU03SameStopChain:
    def test_u03a_crash_plus_external_second_signal_one_chain(
            self, tmp_path):
        """U03:crash 后收尾窗口内到达的外部信号——同一停止链消费,
        不重开窗口、不二次 finalize;首个 crash 事实不被覆盖。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "u03a", expect_marker="PROBE_INJECT",
            sig=signal.SIGTERM, max_wait=60)
        assert any("PROBE_RUN_RC=3" in ln for ln in lines)
        assert rc == 3, "crash 的外层结果不被第二信号改写"
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_sig"] == signal.SIGTERM, \
            "收尾窗口信号已登记(handler 覆盖收尾期)"
        assert summary["external_stop_consumed"] is True, \
            "C 前检查点消费,不新建第二条停止链"
        alerts = (run_dir / "alerts" / "alerts.jsonl").read_text(
            encoding="utf-8")
        assert alerts.count('"supervisor_end"') == 1, "finalize 只一次"
        assert "supervisor_crash" in alerts, "首个 crash 事实保留"

    def test_u03b_second_exception_during_shutdown_keeps_first(
            self, tmp_path):
        """U03:收尾中 write_summary 再抛(第二失败)——分段继续推进
        可独立执行的停止/封口,原 crash 事实不丢,不递归再入收尾。"""
        sup = _sup(tmp_path / "u03b", argv=("--", "bash", "-c", "sleep 8"))
        real_ws = Supervisor.write_summary
        state = {"crashed": False}

        def boom_pump(self2, mono):
            state["crashed"] = True
            raise RuntimeError("u03b 第一失败:pump")

        def boom_ws(self2):
            if state["crashed"]:
                raise OSError("u03b 第二失败:summary 发布")
            return real_ws(self2)

        Supervisor._pump_win_lines = boom_pump
        Supervisor.write_summary = boom_ws
        try:
            rc = sup.run()
        finally:
            Supervisor._pump_win_lines = _real_pump
            Supervisor.write_summary = real_ws
        assert rc == 3, "第二失败不覆盖整体失败事实,run 不再外抛"
        rd = Path(sup.args.run_dir)
        alerts = (rd / "alerts" / "alerts.jsonl").read_text(
            encoding="utf-8")
        assert "supervisor_crash" in alerts, "原失败事实保留"
        assert "supervisor_end" in alerts, "可独立执行的封口继续推进"
        assert not (rd / "summary.json").exists(), "发布失败不补造文件"


_real_pump = Supervisor._pump_win_lines


# ================================================= U04 残留/身份不明
@requires_linux
class TestU04ResidualAndUnconfirmed:
    def test_u04a_leader_exit_descendant_alive_cleaned(self, tmp_path):
        """U04:leader 正常退出而同组子孙仍活——residual_task 实际
        清理本任务(TERM→终态确认),rc 非 0,不误杀、不伪造成功。"""
        rc, lines, run_dir = _run_child(tmp_path, "u04a", max_wait=90)
        assert any("PROBE_RUN_RC=4" in ln for ln in lines), \
            "leader rc=0+残留清理=保护性中止 rc=4,不是普通成功"
        alerts = (run_dir / "alerts" / "alerts.jsonl").read_text(
            encoding="utf-8")
        assert "residual_task_after_leader_exit" in alerts
        summary = _load(run_dir / "summary.json")
        prot = summary["business"]["protector"]
        assert prot["terminal_confirmed"] is True, "清理被确认"
        assert not summary["residual_unconfirmed"]

    def test_u04b_identity_mismatch_unconfirmed_blocks(self, tmp_path):
        """U04:身份不明(登记实例不符)不盲杀——完成未确认如实保留,
        外层非 0,证据不完整(live_writers),不填 raw rc=0。"""
        sup = _sup(tmp_path / "u04b",
                   argv=("--", "bash", "-c", "sleep 60"))
        sup.policy["finalize_window_s"] = 4.0  # 工程夹具缩窗(标注)
        real_pump = Supervisor._pump_win_lines
        state = {"armed": False}

        def boom(self2, mono):
            if not state["armed"]:
                state["armed"] = True
                if self2.protector:  # 篡改登记身份(PID 复用形态)
                    self2.protector.leader_start = 12345
                raise RuntimeError("u04b 注入:crash+身份漂移")
            return real_pump(self2, mono)
        Supervisor._pump_win_lines = boom
        try:
            rc = sup.run()
        finally:
            Supervisor._pump_win_lines = _real_pump
        assert rc == 3, "crash 外层非 0"
        summary = _load(Path(sup.args.run_dir) / "summary.json")
        assert summary["residual_unconfirmed"] is True, "完成未确认"
        prot = summary["business"]["protector"]
        assert prot["identity_mismatch"] is True
        assert prot["term_sent"] is False, "身份不符不得发信号"
        rr = _load(Path(sup.args.run_dir) / "run_record.json")
        assert rr["evidence_complete"] is False


# ================================================= U06 零 spawn 不伪造
@requires_linux
class TestU06PreSpawn:
    def test_u06_pre_spawn_stop_zero_business_no_fake_logs(
            self, tmp_path):
        """U06:准入通过后、spawn 前的停止——零业务启动;未发生步骤
        不伪造原始日志(business 流不存在/无 business_started)。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "u06",
            expect_marker="PROBE_FIRED_AT=admission_done", max_wait=60)
        assert any("PROBE_RUN_RC=4" in ln for ln in lines)
        biz = run_dir / "business"
        assert not (biz / "stdout.log").exists()
        assert not (biz / "stderr.log").exists()
        alerts = (run_dir / "alerts" / "alerts.jsonl").read_text(
            encoding="utf-8")
        assert "business_started" not in alerts, "未发生步骤不伪造"
        summary = _load(run_dir / "summary.json")
        assert summary["business"]["rc"] is None
        assert summary["external_stop_consumed"] is True


# ================================================= L02/L03 截止点时间线
@requires_linux
class TestL02EventBarriers:
    @pytest.mark.parametrize("mode,mark", [
        ("l02a", "finalize_begin"),
        ("l02b", "drain"),
    ])
    def test_l02_pre_cutoff_barriers_consume(self, tmp_path, mode, mark):
        """L02:明确事件屏障(finalize 开始/drain)注入的停止——
        C 前意图决定最终结果:raw rc=0 保留、outer rc=4、消费一次;
        不靠 stdout 次数或长 sleep。

        stop-publication 轮勘误:l02c(pre_summary)从本参数化移除——
        发布时序移到停止决定 C 之后,该屏障点的信号已是真正的 C 后
        事件(见 test_l02c_publish_is_post_cutoff_receipt)。"""
        rc, lines, run_dir = _run_child(
            tmp_path, mode, expect_marker=f"PROBE_FIRED_AT={mark}",
            max_wait=60)
        assert any("PROBE_RUN_RC=4" in ln for ln in lines), \
            f"{mark} 屏障的停止属本次 run(C 前)"
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_consumed"] is True
        assert summary["business"]["rc"] == 0, "业务原始事实不改写"

    def test_l02c_publish_is_post_cutoff_receipt(self, tmp_path):
        """L02c(stop-publication 轮迁移):summary 发布屏障已在停止
        决定 C **之后**——屏障点注入的 TERM 是 C 后事件:不改已决定的
        结果(业务成功保持成功)、独立回执承载;对照 l02a/l02b(C 前
        屏障仍消费参与结果)。旧断言(该屏障消费→rc=4)随'发布先于
        决定'的缺陷一并废除。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "l02c",
            expect_marker="PROBE_FIRED_AT=pre_summary", max_wait=60)
        assert any("PROBE_RUN_RC=0" in ln for ln in lines), \
            "发布时点已在 C 后:屏障信号不倒改已决定的结果"
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_consumed"] is False
        assert summary["business"]["rc"] == 0
        post = run_dir / "post_cutoff_signal.json"
        assert post.is_file(), "C 后事件有独立回执"
        rec = _load(post)
        assert rec["sig_count_total"] >= 1
        rr = _load(run_dir / "run_record.json")
        assert rr["finalized"] is True
        assert rr["evidence_complete"] is True

    def test_l02d_post_cutoff_receipt_only(self, tmp_path):
        """L02/L03:finalize 完全返回(C 已越过)之后的信号——不改已
        发布结果,事实进独立后置回执;成功发布件保持完整。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "l02d",
            expect_marker="PROBE_FIRED_AT=post_finalize", max_wait=60)
        assert any("PROBE_RUN_RC=0" in ln for ln in lines), \
            "C 后信号不倒改已固定结果(业务成功保持成功)"
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_consumed"] is False, "C 后不重开"
        post = run_dir / "post_cutoff_signal.json"
        assert post.is_file(), "C 后事件有独立回执"
        rec = _load(post)
        assert rec["sig_count_total"] >= 1
        rr = _load(run_dir / "run_record.json")
        assert rr["finalized"] is True
        assert rr["evidence_complete"] is True

    def test_l03_publish_failure_overall_failure(self, tmp_path):
        """L03:summary 发布失败(write_summary 抛 OSError)——整体
        失败(rc 非 0),不得先置成功再忽略写入错误。"""
        sup = _sup(tmp_path / "l03")
        real_ws = Supervisor.write_summary

        def boom_ws(self2):
            raise OSError(28, "l03 注入:发布失败(设备满形态)")
        Supervisor.write_summary = boom_ws
        try:
            rc = sup.run()
        finally:
            Supervisor.write_summary = real_ws
        assert rc != 0, "发布失败=整体失败"
        rd = Path(sup.args.run_dir)
        assert not (rd / "summary.json").exists(), "发布失败不补造文件"
        alerts = (rd / "alerts" / "alerts.jsonl").read_text(
            encoding="utf-8")
        assert "supervisor_end" in alerts, "封口前批次如实保留"


# ================================================= L04 handler 生命周期
@requires_linux
class TestL04HandlerLifecycle:
    def test_l04_handler_restored_on_all_exits(self, tmp_path):
        """L04:成功/拒绝/异常/收尾失败各出口最终准确恢复旧 handler;
        不在业务处理前恢复;重复调用不残留上一实例状态。"""
        old_term = signal.signal(signal.SIGTERM, signal.SIG_IGN)
        old_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            # 出口1:成功(true 快速退出)
            assert _sup(tmp_path / "ok").run() == 0
            assert signal.getsignal(signal.SIGTERM) is signal.SIG_IGN
            assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
            # 出口2:启动拒绝(pytest kind 缺 junit→零 spawn rc=2)
            assert _sup(tmp_path / "rej", task_kind="pytest").run() == 2
            assert signal.getsignal(signal.SIGTERM) is signal.SIG_IGN
            # 出口3:主循环异常(统一收尾)
            def boom(self2, mono):
                raise RuntimeError("l04 注入")
            Supervisor._pump_win_lines = boom
            try:
                assert _sup(tmp_path / "crash",
                            argv=("--", "bash", "-c", "sleep 8")).run() == 3
            finally:
                Supervisor._pump_win_lines = _real_pump
            assert signal.getsignal(signal.SIGTERM) is signal.SIG_IGN, \
                "handler 覆盖异常收尾期,最终恢复旧值"
            # 出口4:收尾失败(write_summary 抛错)
            real_ws = Supervisor.write_summary

            def boom_ws(self2):
                raise OSError("l04 注入:发布失败")
            Supervisor.write_summary = boom_ws
            try:
                assert _sup(tmp_path / "pubfail").run() != 0
            finally:
                Supervisor.write_summary = real_ws
            assert signal.getsignal(signal.SIGTERM) is signal.SIG_IGN
            # 重复调用不残留:新一轮实例正常注册/恢复
            assert _sup(tmp_path / "again").run() == 0
            assert signal.getsignal(signal.SIGTERM) is signal.SIG_IGN
        finally:
            signal.signal(signal.SIGTERM, old_term)
            signal.signal(signal.SIGINT, old_int)
