# -*- coding: utf-8 -*-
"""R17 stop-publication 轮组合证据(任务书 §7 S/P/W 组)。

真实模块为主:runner 的 r17_supervision(发布树或 WSL 开发树同步面);
真实短命子进程+事件屏障+sys.settrace 行级定位;真实信号(进程级
TERM)、真实未屏蔽后台线程(本测试创建并登记的实例)、真实 Windows
采样器(ps1,非 replay 形态)与真实文件 I/O 故障(chmod/目录占用)。
外部 watchdog 只做测试兜底(不计产品保护行为)。

覆盖:
  S01 未屏蔽线程在场,临界区内发 TERM——handler 实际登记顺序参与
     决定(保守消费,不 outer=0);正常支持环境对照(cutoff 文件)。
  S02 C 前最后一刻经后台线程路由的既有登记不漏;C 后信号独立回执。
  S03 线程前提不满足/掩码能力失败——保守归因不降级为旧竞态;无信号
     时正常成功不受影响;不误杀无关线程。
  P01 独立观察者在候选准备/C 决定/发布完成三处读权威路径——C 前
     无完成件;中间态不当成功;发布后字节不变。
  P02 真实 summary 写入失败/run_record replace 失败——失败不被吞
     成成功;无合法完成件;外层非零。
  W01 guest 在途真实文件写入(emit 屏障暂停)join 超时——句柄保留、
     未确认状态如实、必要流不签完整;释放后文件变化不推翻判定。
  W02/W04 正常关闭对照:guest 预算内退出/未启动形态/真实 win 采样器
     关闭与写者收尾;关闭后遥测稳定;无残留。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
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

_PS1_CAND = RUNNER_DIR / "r17_win_sampler.ps1"
PS1_DEFAULT = str(_PS1_CAND if _PS1_CAND.is_file() else Path(
    "/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/"
    "r17_win_sampler.ps1"))


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


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _alert_events(run_dir) -> list[dict]:
    p = Path(run_dir) / "alerts" / "alerts.jsonl"
    out = []
    if p.is_file():
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
    return out


def _event_names(run_dir) -> list[str]:
    return [e.get("event") for e in _alert_events(run_dir)]


# 子进程模板:参数化 mode;s/p 组 replay;w01/w02a 非 replay(真实 ps1)。
SP_CHILD_SRC = r'''
import argparse, json, os, signal, sys, threading, time
probe_dir, base, mode = sys.argv[1], sys.argv[2], sys.argv[3]
ps1 = sys.argv[4] if len(sys.argv) > 4 else "/nonexistent.ps1"
sys.path.insert(0, probe_dir)
from r17_supervision import Supervisor

import datetime as _dt
def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")

def fire(name):
    with open(os.path.join(base, "marker_" + name), "w") as fh:
        fh.write("1")

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

live = mode in ("w01", "w02a")   # 非 replay:真实采样器
samples_path = os.path.join(base, "samples.jsonl")
if not live:
    with open(samples_path, "w", encoding="utf-8") as fh:
        for _ in range(40):
            fh.write(json.dumps({"win": win, "guest": guest}) + "\n")

# ---- s03b:掩码能力失败(patch 先于 Supervisor 构造) ----
if mode == "s03b":
    def broken_sigmask(*a, **k):
        raise OSError(22, "probe: pthread_sigmask unavailable")
    signal.pthread_sigmask = broken_sigmask

argv = ["bash", "-c", "echo sp_ok" if live else "sleep 1"]
args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=argv, task_cwd=None, max_seconds=0,
    samples_source="" if live else "file:" + samples_path,
    win_sampler_ps1=ps1, win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=45.0)
sup = Supervisor(args)

# ---- s01a/s03a:未屏蔽辅助线程(本测试创建并登记;run 后测试清理) ----
aux = None
if mode in ("s01a", "s03a"):
    aux = threading.Thread(target=lambda: time.sleep(120),
                           name="sp-probe-aux", daemon=True)
    aux.start()
    print("PROBE_AUX_STARTED", flush=True)

# ---- settrace 定位(S 组) ----
target_line = None
if mode in ("s01a",):
    key = "_external_stop_count_at_cutoff"
    with open(os.path.join(probe_dir, "r17_supervision.py"),
              encoding="utf-8") as fh:
        for i, ln in enumerate(fh, 1):
            if target_line is None and key in ln and ln.rstrip().endswith("\\"):
                target_line = i
    assert target_line is not None, "C 赋值行未定位"
    print("PROBE_TARGET_LINE=%d" % target_line, flush=True)
    fired = {"v": False}
    def _local(frame, event, arg):
        if event == "line" and frame.f_code.co_name == "finalize" \
                and not fired["v"] and frame.f_lineno == target_line:
            fired["v"] = True
            print("PROBE_THREADS_AT_C=%s"
                  % [t.name for t in threading.enumerate()], flush=True)
            print("PROBE_SIGNAL_SENT", flush=True)
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(0.05)
        return _local
    def _global(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "finalize" \
                and frame.f_code.co_filename.endswith("r17_supervision.py"):
            return _local
        return None
    sys.settrace(_global)
elif mode == "s02a":
    key = "self._cutoff_thread_premise()"
    with open(os.path.join(probe_dir, "r17_supervision.py"),
              encoding="utf-8") as fh:
        for i, ln in enumerate(fh, 1):
            if key in ln:
                target_line = i
                break
    assert target_line is not None, "前提核验行未定位"
    print("PROBE_TARGET_LINE=%d" % target_line, flush=True)
    fired = {"v": False}
    def _local(frame, event, arg):
        if event == "line" and frame.f_code.co_name == "finalize" \
                and not fired["v"] and frame.f_lineno == target_line:
            fired["v"] = True
            # C 前最后一刻经未屏蔽后台线程路由:发完即退(核验时不在场)
            done = threading.Event()
            def aux_fire():
                os.kill(os.getpid(), signal.SIGTERM)
                done.set()
            t = threading.Thread(target=aux_fire, daemon=True)
            t.start()
            done.wait(5.0)
            t.join(5.0)
            time.sleep(0.05)  # 主线程执行 handler(trace 回调 CALL 边界)
            print("PROBE_SIGNAL_SENT_VIA_AUX", flush=True)
        return _local
    def _global(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "finalize" \
                and frame.f_code.co_filename.endswith("r17_supervision.py"):
            return _local
        return None
    sys.settrace(_global)

# ---- p01:三观察点屏障 ----
if mode == "p01":
    real_prep = Supervisor._prepare_run_record_entries
    def hooked_prep(self2):
        out = real_prep(self2)
        fire("candidate_ready")
        time.sleep(1.2)   # 父进程观察窗口
        return out
    Supervisor._prepare_run_record_entries = hooked_prep
    real_ws = Supervisor.write_summary
    def hooked_ws(self2):
        fire("pre_publish")   # C 后、发布前
        time.sleep(1.2)
        return real_ws(self2)
    Supervisor.write_summary = hooked_ws
    real_frr = Supervisor.finalize_run_record
    def hooked_frr(self2):
        out = real_frr(self2)
        fire("published")
        return out
    Supervisor.finalize_run_record = hooked_frr

# ---- p02a:summary 真实写入失败(目录去写权限;完成后恢复) ----
if mode == "p02a":
    real_ws = Supervisor.write_summary
    def hooked_ws(self2):
        os.chmod(os.path.join(base, "run"), 0o500)
        try:
            return real_ws(self2)
        finally:
            os.chmod(os.path.join(base, "run"), 0o755)
    Supervisor.write_summary = hooked_ws

# ---- p02b:run_record replace 失败(目标被目录占用) ----
if mode == "p02b":
    real_frr = Supervisor.finalize_run_record
    def hooked_frr(self2):
        os.makedirs(os.path.join(base, "run", "run_record.json"),
                    exist_ok=True)
        return real_frr(self2)
    Supervisor.finalize_run_record = hooked_frr

# ---- w01:guest emit 屏障(业务退出后下一次 emit 阻塞) ----
guest_thread_ref = {"t": None}
if mode == "w01":
    block_flag = threading.Event()
    release_gate = threading.Event()
    real_emit = Supervisor._emit_guest
    def hooked_emit(self2, rec):
        if threading.current_thread().name == "r17-guest-sampler":
            guest_thread_ref["t"] = threading.current_thread()
        if block_flag.is_set():
            print("PROBE_EMIT_BLOCKED", flush=True)
            release_gate.wait(90.0)
            print("PROBE_EMIT_RELEASED", flush=True)
        return real_emit(self2, rec)
    Supervisor._emit_guest = hooked_emit
    real_obs = Supervisor._observe_business_exit
    obs_done = {"v": False}
    def hooked_obs(self2):
        if not obs_done["v"] and self2.biz_proc is not None \
                and self2.biz_proc.poll() is not None:
            obs_done["v"] = True
            print("PROBE_BIZ_EXIT_SEEN", flush=True)
            block_flag.set()
        return real_obs(self2)
    Supervisor._observe_business_exit = hooked_obs
    sup._w01_release = release_gate   # run 后释放(测试侧)

rc = sup.run()
print("PROBE_RUN_RC=%d" % rc, flush=True)
print("PROBE_SIG=%r" % sup._external_stop_sig, flush=True)
print("PROBE_SIG_COUNT=%d" % sup._external_stop_sig_count, flush=True)
print("PROBE_CONSUMED=%r" % sup._external_stop_consumed, flush=True)
print("PROBE_COUNT_AT_CUTOFF=%r"
      % sup._external_stop_count_at_cutoff, flush=True)
print("PROBE_PREMISE_OK=%r" % sup._cutoff_premise_ok, flush=True)
print("PROBE_PREMISE_DETAIL=%r" % sup._cutoff_premise_detail, flush=True)
print("PROBE_GUEST_REF=%r" % (sup.guest_sampler,), flush=True)
if aux is not None:
    print("PROBE_AUX_ALIVE=%s" % aux.is_alive(), flush=True)
    aux.join(timeout=0.1)
if mode == "w01":
    t = guest_thread_ref["t"]
    print("PROBE_GUEST_THREAD_IDENTIFIED=%s" % (t is not None), flush=True)
    if t is not None:
        print("PROBE_GUEST_THREAD_ALIVE=%s" % t.is_alive(), flush=True)
        gp = sup.guest_path
        try:
            size_before = os.path.getsize(gp)
        except OSError:
            size_before = None
        sup._w01_release.set()
        time.sleep(3.0)
        try:
            size_after = os.path.getsize(gp)
        except OSError:
            size_after = None
        print("PROBE_GUEST_FILE=%s->%s" % (size_before, size_after),
              flush=True)
        print("PROBE_GUEST_FILE_GREW=%s"
              % (size_before is not None and size_after is not None
                 and size_after > size_before), flush=True)
if mode == "w02a":
    print("PROBE_WIN_RC=%r"
          % (sup.win_proc.returncode if sup.win_proc else None),
          flush=True)
    wp = sup.win_path_guest
    h1 = None
    try:
        import hashlib as _h
        h1 = _h.sha256(open(wp, "rb").read()).hexdigest()
    except OSError:
        pass
    time.sleep(2.0)
    try:
        h2 = _h.sha256(open(wp, "rb").read()).hexdigest()
    except OSError:
        h2 = None
    print("PROBE_WIN_TEL_STABLE=%s" % (h1 is not None and h1 == h2),
          flush=True)
# 测试父进程兜底清理(不计产品行为):残留辅助采样进程
try:
    if sup.win_proc is not None and sup.win_proc.poll() is None:
        sup.win_proc.kill()
        sup.win_proc.wait(timeout=5)
except Exception:
    pass
sys.exit(rc if 0 <= rc < 256 else 0)
'''


def _run_sp_child(tmp_path, mode, max_wait=90.0, live=False):
    base = tmp_path / mode
    base.mkdir(parents=True, exist_ok=True)
    child = base / "sp_child.py"
    child.write_text(SP_CHILD_SRC, encoding="utf-8")
    argv = [sys.executable, str(child), str(RUNNER_DIR), str(base), mode]
    if live:
        argv.append(PS1_DEFAULT)
    p = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True)
    lines: list[str] = []

    def _reader():
        for ln in p.stdout:
            lines.append(ln.rstrip("\n"))

    rt = threading.Thread(target=_reader, daemon=True)
    rt.start()
    try:
        deadline = time.time() + max_wait
        rc = None
        while time.time() < deadline:
            rc = p.poll()
            if rc is not None:
                break
            time.sleep(0.2)
        if rc is None:
            p.kill()
            p.wait(timeout=10)
            pytest.fail(f"子进程 {max_wait}s 未退出;输出={lines[-8:]}")
        return rc, lines, base / "run", base
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=10)
        rt.join(timeout=5)


def _kv(lines):
    out = {}
    for ln in lines:
        if ln.startswith("PROBE_") and "=" in ln:
            k, _, v = ln.partition("=")
            out.setdefault(k, v)
    return out


# ================================================= S:真实多线程下的 C
@requires_linux
class TestS01UnshieldedThreadParticipates:
    def test_s01a_unshielded_thread_signal_at_cutoff_participates(
            self, tmp_path):
        """S01:真实 supervisor/writer;测试创建的未屏蔽后台线程在场;
        C 赋值语句处发真实 TERM——handler 在临界区内实际登记(经未
        屏蔽线程路由),不能被 outer=0 漏接:前提核验失败→保守复核
        消费→rc=4;辅助线程不被误杀;无伪 C 后回执。"""
        rc, lines, run_dir, base = _run_sp_child(tmp_path, "s01a")
        kv = _kv(lines)
        assert "PROBE_SIGNAL_SENT" in lines
        assert "sp-probe-aux" in kv.get("PROBE_THREADS_AT_C", "")
        assert rc == 4, f"临界区内经未屏蔽线程登记的停止必须参与结果," \
                        f"实际 rc={rc};{lines[-6:]}"
        assert kv.get("PROBE_CONSUMED") == "True"
        assert kv.get("PROBE_PREMISE_OK") == "False"
        assert kv.get("PROBE_AUX_ALIVE") == "True", "不误杀无关线程"
        # 前提失败发生在 seal 之后:alerts 批已封口拒绝新动作(既有
        # 合同),正式载体=summary.publication 块(同一事实)
        summary = _load(run_dir / "summary.json")
        assert summary["publication"]["cutoff_premise_ok"] is False
        assert "unshielded_threads" in (
            summary["publication"]["cutoff_premise_detail"] or "")
        assert summary["external_stop_consumed"] is True
        assert not (run_dir / "post_cutoff_signal.json").exists(), \
            "保守消费的信号不得伪称 C 后事件"

@requires_linux
class TestS02PendingSignalRouting:
    def test_s02a_bg_thread_route_before_cutoff_not_lost(self, tmp_path):
        """S02:C 前最后一刻(前提核验行)经未屏蔽后台线程路由发 TERM
        ——"实际登记顺序"合同:handler 执行落在最后判定之前→参与
        结果(rc=4);落在 C 之后(3.11 eval 检查点稀疏,tripped 的
        handler 可推迟到临界区后新帧执行)→独立回执承载+summary
        如实记录。两分支都不漏、不消失、不无痕。"""
        rc, lines, run_dir, base = _run_sp_child(tmp_path, "s02a")
        kv = _kv(lines)
        assert "PROBE_SIGNAL_SENT_VIA_AUX" in lines
        assert kv.get("PROBE_PREMISE_OK") == "True", \
            "辅助线程发完即退:核验时不在场,前提应成立"
        assert kv.get("PROBE_SIG") == str(signal.SIGTERM), "handler 必然执行"
        if kv.get("PROBE_CONSUMED") == "True":
            assert rc == 4, f"登记在判定前:参与结果,实际 {rc}"
            assert kv.get("PROBE_COUNT_AT_CUTOFF") == "1"
            assert not (run_dir / "post_cutoff_signal.json").exists()
        else:
            assert rc == 0, f"登记在 C 后:成功不改写+独立回执,实际 {rc}"
            assert kv.get("PROBE_COUNT_AT_CUTOFF") == "0"
            rec = _load(run_dir / "post_cutoff_signal.json")
            assert rec["sig_count_total"] >= 1
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_sig"] == signal.SIGTERM
        assert summary["external_stop_sig_count"] == 1


@requires_linux
class TestS03PremiseFailureFailClosed:
    def test_s03a_unshielded_thread_no_signal_normal_success(
            self, tmp_path):
        """S03:未屏蔽线程在场但无信号——前提失败如实记录,保守复核
        无增量,正常成功不受影响(不把所有运行一律拒绝);线程不被
        误杀;掩码/handler 恢复。"""
        rc, lines, run_dir, base = _run_sp_child(tmp_path, "s03a")
        kv = _kv(lines)
        assert rc == 0, f"无信号时正常成功,实际 {rc};{lines[-6:]}"
        assert kv.get("PROBE_PREMISE_OK") == "False"
        assert kv.get("PROBE_AUX_ALIVE") == "True"
        summary = _load(run_dir / "summary.json")
        assert summary["publication"]["cutoff_premise_ok"] is False
        assert "unshielded_threads" in (
            summary["publication"]["cutoff_premise_detail"] or "")
        assert summary["publication"]["cutoff_premise_detail"]
        rr = _load(run_dir / "run_record.json")
        assert rr["finalized"] is True
        assert rr["evidence_complete"] is True

    def test_s03b_sigmask_unavailable_fail_closed(self, tmp_path):
        """S03:pthread_sigmask 能力失败(patch 构造前)——不宣称挂起
        边界成立(前提失败记录);无信号时正常成功;handler 恢复。"""
        rc, lines, run_dir, base = _run_sp_child(tmp_path, "s03b")
        kv = _kv(lines)
        assert rc == 0, f"能力失败+无信号:正常成功,实际 {rc}"
        assert kv.get("PROBE_PREMISE_OK") == "False"
        assert "mask_unavailable" in kv.get("PROBE_PREMISE_DETAIL", "")
        summary = _load(run_dir / "summary.json")
        assert summary["publication"]["cutoff_premise_ok"] is False
        assert "mask_unavailable" in (
            summary["publication"]["cutoff_premise_detail"] or "")


# ================================================= P:发布边界
@requires_linux
class TestP01IndependentReader:
    def test_p01_reader_never_sees_premature_completion(self, tmp_path):
        """P01:独立观察者(父进程,轮询标记文件)在候选准备/C 决定/
        发布完成三处检查权威路径——C 前没有可被认可的完成件;发布
        中间态不能被 reader 当成功;发布完成后字节不再变化。"""
        base = tmp_path / "p01"
        base.mkdir(parents=True, exist_ok=True)
        (base / "sp_child.py").write_text(SP_CHILD_SRC, encoding="utf-8")
        run_dir = base / "run"
        p = subprocess.Popen(
            [sys.executable, str(base / "sp_child.py"), str(RUNNER_DIR),
             str(base), "p01"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, start_new_session=True)
        lines: list[str] = []

        def _reader():
            for ln in p.stdout:
                lines.append(ln.rstrip("\n"))

        rt = threading.Thread(target=_reader, daemon=True)
        rt.start()
        try:
            def _wait_marker(name, timeout=45.0):
                mk = base / f"marker_{name}"
                dl = time.time() + timeout
                while time.time() < dl and not mk.is_file():
                    if p.poll() is not None:
                        pytest.fail(f"子进程提前退出:{lines[-6:]}")
                    time.sleep(0.05)
                assert mk.is_file(), f"{timeout}s 未见屏障 {name}"

            # 观察点1:候选准备后(C 前)——无完成件
            _wait_marker("candidate_ready")
            assert not (run_dir / "run_record.json").exists(), \
                "C 前不得存在 run_record(候选是私有的)"
            assert not (run_dir / "summary.json").exists(), \
                "C 前不得公开 summary"
            # 观察点2:C 决定后、发布完成前——中间态不可被当成功
            _wait_marker("pre_publish")
            assert not (run_dir / "run_record.json").exists(), \
                "发布中间态:完成判据(run_record)尚未发布"
            # 观察点3:发布完成后——finalized 且字节不再变化
            _wait_marker("published")
            rr = _load(run_dir / "run_record.json")
            assert rr["finalized"] is True
            sm = _load(run_dir / "summary.json")
            assert sm["external_stop_consumed"] in (True, False, None)
            h_rr = _sha(run_dir / "run_record.json")
            h_sm = _sha(run_dir / "summary.json")
            dl = time.time() + 40
            while p.poll() is None and time.time() < dl:
                time.sleep(0.2)
            rc = p.poll()
            assert rc is not None, f"子进程未退出;{lines[-6:]}"
            assert rc == 0, f"正常路径成功,实际 {rc};{lines[-6:]}"
            time.sleep(1.0)  # 发布后静置:完成件字节不再变化
            assert _sha(run_dir / "run_record.json") == h_rr, \
                "已发布完成件不得覆写"
            assert _sha(run_dir / "summary.json") == h_sm, \
                "已发布 summary 不得覆写"
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
            rt.join(timeout=5)


@requires_linux
class TestP02RealPublishFailures:
    def test_p02a_summary_write_failure_no_fake_success(self, tmp_path):
        """P02:真实 summary 写入失败(run_dir 去写权限)——失败不被
        内部 catch 吞成成功:rc=6、summary 缺失、run_record 作为明确
        非成功终结证据(summary 条目 missing、evidence=false)。"""
        rc, lines, run_dir, base = _run_sp_child(tmp_path, "p02a")
        assert rc == 6, f"发布失败=证据不完整 rc=6,实际 {rc};{lines[-6:]}"
        assert not (run_dir / "summary.json").exists(), \
            "发布失败不补造文件"
        rr = _load(run_dir / "run_record.json")
        assert rr["finalized"] is True
        assert rr["evidence_complete"] is False
        assert "summary" in rr["missing_roles"]
        assert rr["business"]["rc"] == 0, "业务原始事实不改写"

    def test_p02b_run_record_replace_failure_no_completion(self, tmp_path):
        """P02:run_record 原子替换失败(目标被目录占用,C 后)——无
        合法完成件;summary 保留(其内容是发布时点真实快照);外层
        非零(rc=3);首因保留。"""
        rc, lines, run_dir, base = _run_sp_child(tmp_path, "p02b")
        assert rc == 3, f"发布失败外层 rc=3,实际 {rc};{lines[-6:]}"
        rr_path = run_dir / "run_record.json"
        assert rr_path.is_dir(), "目标被目录占用:无合法完成记录"
        sm = _load(run_dir / "summary.json")
        assert sm["publication"]["summary_failed"] is False
        evs = _event_names(run_dir)
        assert evs.count("supervisor_end") == 1


# ================================================= W:采样写者关闭
@requires_linux
class TestW01GuestInflightWrite:
    def test_w01_guest_emit_barrier_join_timeout_unconfirmed(
            self, tmp_path):
        """W01:guest 已进入真实文件写入(emit 内屏障暂停);stop/join
        超时——run 返回前仍保留未确认(句柄不置 None、线程身份保留、
        telemetry_guest 不签完整封口、evidence_complete=false、外层
        非成功);释放后文件变化不能推翻此前判定。"""
        rc, lines, run_dir, base = _run_sp_child(
            tmp_path, "w01", max_wait=120, live=True)
        kv = _kv(lines)
        assert "PROBE_EMIT_BLOCKED" in lines
        assert rc == 6, f"未确认关闭=证据不完整 rc=6,实际 {rc}"
        assert kv.get("PROBE_GUEST_REF", "").startswith(
            "<GuestSampler"), f"句柄保留,实际 {kv.get('PROBE_GUEST_REF')}"
        assert kv.get("PROBE_GUEST_THREAD_ALIVE") == "True"
        rr = _load(run_dir / "run_record.json")
        assert rr["evidence_complete"] is False
        tg = [e for e in rr["required"] if e["role"] == "telemetry_guest"]
        assert tg and tg[0].get("live_writers") is True
        writers = rr.get("writers") or {}
        assert writers.get("guest", {}).get("alive_after_join") is True
        assert writers.get("guest", {}).get("joined") is False
        evs = _event_names(run_dir)
        assert "guest_sampler_stop_unconfirmed" in evs
        # 释放后文件继续增长(证明封口时流未静止),旧判定不被推翻
        assert kv.get("PROBE_GUEST_FILE_GREW") == "True"
        assert rr["evidence_complete"] is False  # 判定不被事后推翻


@requires_linux
class TestW02W04NormalClosure:
    def test_w02a_w04_normal_close_full_evidence(self, tmp_path):
        """W02a/W04:真实 guest+win 采样器正常关闭对照——guest 预算
        内退出(句柄确认后清空)、win 实际写者退出可核对(stopped 事
        件=确认版)、io writer 哨兵关闭 join 确认;关闭后遥测稳定;
        evidence_complete=true;rc=0;无采样进程残留。"""
        rc, lines, run_dir, base = _run_sp_child(
            tmp_path, "w02a", max_wait=120, live=True)
        kv = _kv(lines)
        assert rc == 0, f"正常关闭对照应成功,实际 {rc};{lines[-8:]}"
        assert kv.get("PROBE_GUEST_REF") == "None", \
            "确认退出后句柄方可清空"
        assert kv.get("PROBE_WIN_TEL_STABLE") == "True", \
            "win 写者退出后遥测字节稳定"
        sup_rc_win = kv.get("PROBE_WIN_RC")
        assert sup_rc_win not in ("None", None, ""), \
            f"interop 进程退出码可核对,实际 {sup_rc_win!r}"
        rr = _load(run_dir / "run_record.json")
        assert rr["evidence_complete"] is True
        writers = rr.get("writers") or {}
        assert writers.get("guest", {}).get("joined") is True
        assert writers.get("guest", {}).get("alive_after_join") is False
        assert writers.get("win", {}).get("exited") is True
        assert writers.get("win", {}).get("unconfirmed") is False
        assert writers.get("io", {}).get("joined") is True
        evs = _event_names(run_dir)
        assert "win_sampler_stopped" in evs, "确认退出才记 stopped"
        assert "win_sampler_stop_unconfirmed" not in evs
        assert "guest_sampler_stop_unconfirmed" not in evs
        assert "io_writer_stop_unconfirmed" not in evs

    def test_w02b_replay_unstarted_thread_distinct(self, tmp_path):
        """W02b:replay 形态采样线程未启动——单独记录(started=
        False/joined=True),不产生伪错误,不影响完整证据。"""
        base = tmp_path / "w02b"
        base.mkdir(parents=True, exist_ok=True)
        sp = base / "samples.jsonl"
        _write_samples(sp)
        args = argparse.Namespace(
            run_dir=str(base / "run"), task_kind="fixture",
            argv=["bash", "-c", "sleep 1"], task_cwd=None, max_seconds=0,
            samples_source="file:" + str(sp),
            win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
            expect_artifact=[], obs_ready_deadline=30.0)
        sup = Supervisor(args)
        rc = sup.run()
        assert rc == 0
        assert sup.guest_sampler is None
        rr = _load(base / "run" / "run_record.json")
        writers = rr.get("writers") or {}
        assert writers.get("guest", {}).get("started") is False
        assert writers.get("guest", {}).get("joined") is True
        assert rr["evidence_complete"] is True
