# -*- coding: utf-8 -*-
"""R17 fail-closed-integrity-delivery 轮专项测试(任务书 §8 验收矩阵)。

覆盖(WP0 反例 FC-1/2/3 修复后的新行为面):
  C02:线程前提查询失败/掩码还原失败——无普通成功降级(rc=7),
      恢复状态如实,不静默吞错;
  C03:INT 变体在前提失败边界(能力失效不因信号种类改变非成功);
  W01:真实采样写屏障→真实 budget_check 触发→真实收尾→屏障未释放
      时 record/完整性/实际 verifier 均不认完整→释放回收;
  W02:已启动但无关闭记录=未知,不被 None 掩盖(三态);
  W03:budget 出口与正常 finalize 共享同一关闭事实(join 段不跳过);
  P01/P02:summary 新发布边界故障矩阵(tmp 部分字节/可解析后失败/
      replace 失败)——残片只在私有临时名,角色 publish_failed,
      实际 build/verify 拒绝;
  P03:正常发布对照(无 tmp 残留,verify 通过)。

故障只注入本测试创建的进程/线程/文件/时序;生产策略未改
(预算值仅在测试进程内注入受控小值,§0.1)。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_curriculum261_r17_control_path_unit import (  # noqa: E402
    _find_runner_dir, requires_linux)

RUNNER_DIR = _find_runner_dir()
sys.path.insert(0, str(RUNNER_DIR))
from r17_supervision import Supervisor  # noqa: E402

_PS1_CAND = RUNNER_DIR / "r17_win_sampler.ps1"
PS1_DEFAULT = str(_PS1_CAND if _PS1_CAND.is_file() else Path(
    "/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/"
    "r17_win_sampler.ps1"))


def _sup(tmp_path, argv=("--", "true"), samples_source=""):
    argv = list(argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    args = argparse.Namespace(
        run_dir=str(tmp_path / "run"), task_kind="fixture",
        argv=argv, task_cwd=None, max_seconds=0,
        samples_source=samples_source,
        win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
        expect_artifact=[], obs_ready_deadline=30.0)
    return Supervisor(args)


def _replay_samples(base: Path, n: int = 40) -> str:
    import datetime as dt

    def utc():
        return dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z")

    perf = {"phys_avail_gb": 39.0, "commit_total_gb": 38.0,
            "commit_limit_gb": 83.0, "phys_total_gb": 63.0}
    vols = [{"vol": "F:", "present": True, "free_gb": 100.0,
             "size_gb": 500.0, "serial": "CFA1", "identity_match": True}]
    win = {"event": "sample", "seq": 1, "utc": utc(), "perf": perf,
           "vols": vols, "telemetry_out_writable": True}
    guest = {"event": "guest_sample", "utc": utc(),
             "meminfo": {"MemTotal": 40_000_000, "MemAvailable": 39_000_000},
             "psi_memory": {"full_avg10": 0.0},
             "vmstat_swap": {"pswpout": 0}}
    p = base / "samples.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for _ in range(n):
            fh.write(json.dumps({"win": win, "guest": guest}) + "\n")
    return f"file:{p}"


def _build_and_verify(tmp_path: Path):
    """实际 build+verify 消费(成功 reader 的真实判定面)。

    root 与 supervisor 的 run_record 相对基准同式(run_dir.parent.
    parent——直调形态 run_dir=tmp_path/"run" 时基准是 tmp_path 的
    父目录;不与 run_record 内路径基准差层)。
    """
    rr = tmp_path / "run" / "run_record.json"
    root = (tmp_path / "run").parent.parent
    man = tmp_path / "fcv_manifest.jsonl"
    anchor = tmp_path / "fcv_anchor.json"
    b = subprocess.run(
        [sys.executable, str(RUNNER_DIR / "r17_verify_delivery.py"),
         "build", "--run-record", str(rr), "--manifest-out", str(man),
         "--anchor-out", str(anchor), "--root", str(root)],
        capture_output=True, text=True, timeout=120)
    if b.returncode != 0:
        return b.returncode, [b.stdout, b.stderr]
    v = subprocess.run(
        [sys.executable, str(RUNNER_DIR / "r17_verify_delivery.py"),
         "verify", "--root", str(root), "--manifest", str(man),
         "--anchor-file", str(anchor), "--run-record", str(rr)],
        capture_output=True, text=True, timeout=120)
    return v.returncode, [v.stdout, v.stderr]


def _prep_streams(sup):
    for p in (sup.alerts_path, sup.biz_stdout, sup.biz_stderr):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n", encoding="utf-8")


# ================================================= C02:能力失效各形态
@requires_linux
class TestC02CapabilityFailureForms:
    def test_c02a_thread_query_failure_control_failure(self, tmp_path):
        """C02:线程前提查询失败(/proc 不可读形态,返回失败元组——
        生产实现内部捕获 OSError 返回 False,注入同形态)——rc=7,
        控制失败进 summary/run_record/verify;不静默降级。"""
        sup = _sup(tmp_path, samples_source=_replay_samples(tmp_path))
        sup.biz_rc = 0
        _prep_streams(sup)

        def unreadable_proc():
            # 注入:查询能力不可用(返回失败,与生产 OSError 分支
            # 同形态;非恒真 patch)
            return False, "proc_task_unreadable:probe"

        sup._cutoff_thread_premise = unreadable_proc
        rc = sup.run()
        assert rc == 7, f"查询失败=能力失效非成功,实际 {rc}"
        assert sup._control_failures and \
            sup._control_failures[0]["kind"] == \
            "cutoff_capability_unavailable"
        assert "proc_task_unreadable" in sup._cutoff_premise_detail
        rr = json.loads((tmp_path / "run" / "run_record.json")
                        .read_text(encoding="utf-8"))
        assert rr["control_failures"], "查询失败必须进 run_record"
        vrc, _ = _build_and_verify(tmp_path)
        assert vrc == 1, "verifier 拒绝控制失败包"

    def test_c02b_mask_restore_failure_control_failure(self, tmp_path):
        """C02:掩码还原(SIG_SETMASK)失败——不吞错;rc=7;C 已建立
        但掩码面异常仍是非成功;清理继续完成。"""
        sup = _sup(tmp_path, samples_source=_replay_samples(tmp_path))
        sup.biz_rc = 0
        _prep_streams(sup)
        real_sigmask = signal.pthread_sigmask
        calls = {"n": 0}

        def flaky_restore(how, sigs):
            # 签名与 signal.pthread_sigmask(how, sigs) 一致;
            # BLOCK(临界区进入)正常,SETMASK(还原)失败
            calls["n"] += 1
            if how == signal.SIG_SETMASK and calls["n"] >= 2:
                raise OSError(22, "probe: restore unavailable")
            return real_sigmask(how, sigs)

        signal.pthread_sigmask = flaky_restore
        try:
            rc = sup.run()
        finally:
            signal.pthread_sigmask = real_sigmask
            # 掩码面恢复:残留屏蔽会影响同进程后续测试(测试自身
            # 责任域,不依赖被测代码恢复)
            try:
                signal.pthread_sigmask(signal.SIG_UNBLOCK,
                                       {signal.SIGTERM, signal.SIGINT})
            except (ValueError, OSError):
                pass
        assert rc == 7, f"还原失败=控制失败非成功,实际 {rc}"
        kinds = [c["kind"] for c in sup._control_failures]
        assert "cutoff_mask_restore_failed" in kinds
        # C 已建立(前提核验成功路径不受影响)但记录如实
        assert sup._cutoff_certified is True
        rr = json.loads((tmp_path / "run" / "run_record.json")
                        .read_text(encoding="utf-8"))
        assert any(c["kind"] == "cutoff_mask_restore_failed"
                   for c in rr["control_failures"])
        assert rr["finalized"] is True, "失败记录仍完整封口"
        vrc, _ = _build_and_verify(tmp_path)
        assert vrc == 1


# ================================================= C03:INT 变体
@requires_linux
class TestC03IntVariant:
    def test_c03_int_in_failed_premise_no_success(self, tmp_path):
        """C03:INT 在前提失败 run(未屏蔽辅助线程在场)——与 TERM 同
        语义:能力失效非成功,不因信号种类/时序偶然返回成功。"""
        aux_hold = threading.Event()
        aux = threading.Thread(target=aux_hold.wait,
                               name="fc-aux-int", daemon=True)
        aux.start()
        try:
            sup = _sup(tmp_path, argv=("--", "bash", "-c", "sleep 1"),
                       samples_source=_replay_samples(tmp_path))
            orig = sup._consume_external_stop_sealed

            def sig_then_keep(self2=None):
                os.kill(os.getpid(), signal.SIGINT)
                time.sleep(0.05)  # 未屏蔽线程 tripped+主线程 handler 窗口
                return None

            # 在临界区前的检查点注入:信号必然已登记
            sup._consume_external_stop_sealed = sig_then_keep
            rc = sup.run()
            assert rc == 7, f"前提失败(辅助线程在场)+INT:非成功," \
                            f"实际 {rc}"
            assert sup._cutoff_premise_ok is False
            assert sup._external_stop_sig in (None, signal.SIGINT)
            assert sup._external_stop_consumed is False
            assert not (tmp_path / "run" / "post_cutoff_signal.json"
                        ).exists()
        finally:
            aux_hold.set()
            aux.join(timeout=5)
        assert aux.is_alive() is False


# ================================================= W01:预算先触发组合
@requires_linux
class TestW01BudgetBarrierFullChain:
    def test_w01_budget_first_barrier_record_and_verify(
            self, tmp_path):
        """W01 组合:真实 guest emit 写屏障→emit2 后由采样线程调用
        真实 budget_check()(受控预算 1B)→保护停止→正常收尾→屏障
        未释放时句柄/关闭状态/record/完整性/实际 verifier 均不认
        完整→释放→写者退出(不回写已终结结果)。"""
        child_src = r'''
import argparse, json, os, sys, threading, time
probe_dir, base, ps1 = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, probe_dir)
from r17_supervision import Supervisor

hold = threading.Event()
emit_n = {"n": 0}
orig_emit = Supervisor._emit_guest
tref = {"t": None}

def emit_patched(self, rec):
    emit_n["n"] += 1
    if emit_n["n"] == 2:
        orig_emit(self, rec)  # 真实文件写完成
        tref["t"] = threading.current_thread()
        print("PROBE_EMIT_IN_FLIGHT=True", flush=True)
        self.policy["telemetry_budget_bytes"] = 1
        self.budget_check()  # 真实方法+真实统计
        print("PROBE_BUDGET_CHECK_CALLED=True", flush=True)
        hold.wait(timeout=300.0)
        print("PROBE_EMIT_RELEASED=True", flush=True)
        return
    return orig_emit(self, rec)

Supervisor._emit_guest = emit_patched
args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=["bash", "-c", "sleep 8"], task_cwd=None, max_seconds=0,
    samples_source="", win_sampler_ps1=ps1, win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=45.0)
sup = Supervisor(args)
rc = sup.run()
print("PROBE_RUN_RC=%d" % rc, flush=True)
print("PROBE_GUEST_HANDLE_NONE=%s" % (sup.guest_sampler is None),
      flush=True)
st = sup._guest_close_state
print("PROBE_CLOSE_STATE=%r" % (st,), flush=True)
t = tref["t"]
print("PROBE_GUEST_THREAD_ALIVE=%s" % (t.is_alive() if t else None),
      flush=True)
rr = os.path.join(base, "run", "run_record.json")
d = json.loads(open(rr, encoding="utf-8").read())
print("PROBE_RR_EVIDENCE=%r" % d.get("evidence_complete"), flush=True)
w = (d.get("writers") or {}).get("guest") or {}
print("PROBE_RR_GUEST_ALIVE_AFTER=%r" % w.get("alive_after_join"),
      flush=True)
tg = [r for r in d.get("required", []) if r.get("role") == "telemetry_guest"]
print("PROBE_RR_TG_LIVE=%r" % (tg[0].get("live_writers") if tg else None),
      flush=True)
import subprocess as sp
man = os.path.join(base, "w1_manifest.jsonl")
anchor = os.path.join(base, "w1_anchor.json")
root = os.path.dirname(base)
b = sp.run([sys.executable, os.path.join(probe_dir,
        "r17_verify_delivery.py"), "build", "--run-record", rr,
        "--manifest-out", man, "--anchor-out", anchor, "--root", root],
        capture_output=True, text=True, timeout=120)
print("PROBE_BUILD_RC=%d" % b.returncode, flush=True)
if b.returncode == 0:
    v = sp.run([sys.executable, os.path.join(probe_dir,
            "r17_verify_delivery.py"), "verify", "--root", root,
            "--manifest", man, "--anchor-file", anchor,
            "--run-record", rr], capture_output=True, text=True,
            timeout=120)
    print("PROBE_VERIFY_RC_HELD=%d" % v.returncode, flush=True)
    print("PROBE_VERIFY_PROBLEMS=%s" % v.stdout.strip()[:200], flush=True)
# 屏障释放(测试 finally 语义:写者退出;不回写结果)
hold.set()
if t:
    t.join(timeout=10.0)
print("PROBE_GUEST_ALIVE_AFTER_RELEASE=%s"
      % (t.is_alive() if t else None), flush=True)
sys.exit(0)
'''
        base = tmp_path / "w01b"
        base.mkdir(parents=True)
        (base / "child.py").write_text(child_src, encoding="utf-8")
        p = subprocess.Popen(
            [sys.executable, str(base / "child.py"), str(RUNNER_DIR),
             str(base), PS1_DEFAULT],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            start_new_session=True)
        lines: list[str] = []

        def _reader():
            for ln in p.stdout:
                lines.append(ln.rstrip("\n"))

        rt = threading.Thread(target=_reader, daemon=True)
        rt.start()
        try:
            deadline = time.time() + 180.0
            rc = None
            while time.time() < deadline:
                rc = p.poll()
                if rc is not None:
                    break
                time.sleep(0.2)
            assert rc is not None, f"子进程未退出:{lines[-8:]}"
            kv = {}
            for ln in lines:
                if ln.startswith("PROBE_") and "=" in ln:
                    k, _, v = ln.partition("=")
                    kv.setdefault(k, v)
            assert kv.get("PROBE_BUDGET_CHECK_CALLED") == "True"
            assert kv.get("PROBE_RUN_RC") == "6", \
                f"活写者未确认=evidence 非完整非成功,实际 {kv}"
            assert kv.get("PROBE_GUEST_HANDLE_NONE") == "False", \
                "budget 出口不得清空已启动写者句柄"
            assert "alive_after_join" in kv.get("PROBE_CLOSE_STATE", "") \
                and "True" in kv.get("PROBE_CLOSE_STATE", ""), \
                f"关闭状态记录真实未知:{kv}"
            assert kv.get("PROBE_GUEST_THREAD_ALIVE") == "True"
            assert kv.get("PROBE_RR_EVIDENCE") == "False"
            assert kv.get("PROBE_RR_GUEST_ALIVE_AFTER") == "True"
            assert kv.get("PROBE_RR_TG_LIVE") == "True"
            assert kv.get("PROBE_BUILD_RC") == "0"
            assert kv.get("PROBE_VERIFY_RC_HELD") == "1", \
                f"实际 verifier 必须拒绝活写者包:{kv}"
            assert kv.get("PROBE_GUEST_ALIVE_AFTER_RELEASE") == "False"
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
            rt.join(timeout=5)


# ================================================= W02:三态未知
@requires_linux
class TestW02ThreeStateLifecycle:
    def test_w02c_started_unknown_not_masked_by_none(self, tmp_path):
        """W02:已启动写者无关闭记录(ever_started=True,close_state
        =None)=未知——_writer_live_for_role/_evidence_ok/writers 块
        均按未知处理,None 不再掩盖"曾有写者"。(replay 形态
        telemetry_guest 角色不登记——用 expect_artifact 显式登记
        该角色,使 record/verify 消费同一事实。)"""
        sup = _sup(tmp_path, samples_source=_replay_samples(tmp_path))
        sup.args.expect_artifact = [
            f"telemetry_guest={sup.guest_path}"]
        sup.expected = sup._declare_expected()
        sup.guest_path.parent.mkdir(parents=True, exist_ok=True)
        sup.guest_path.write_text("{}\n", encoding="utf-8")
        # 模拟曾启动:直接置生命周期事实(三态判定的消费面是被测
        # 对象;真实启动路径由 w01/w03 覆盖)
        sup._guest_ever_started = True
        assert sup._writer_live_for_role("telemetry_guest") is True
        assert sup._evidence_ok([]) is False
        sup.finalize_run_record()
        rr = json.loads((tmp_path / "run" / "run_record.json")
                        .read_text(encoding="utf-8"))
        assert rr["writers"]["guest"] == {"ever_started": True}, \
            "未知不被 None 掩盖"
        assert rr["evidence_complete"] is False
        tg = [r for r in rr["required"]
              if str(r.get("role", "")).endswith("telemetry_guest")]
        assert tg and tg[0].get("live_writers") is True
        vrc, _ = _build_and_verify(tmp_path)
        assert vrc == 1, "verifier 拒绝未知写者包"

    def test_w02d_never_started_not_rejected(self, tmp_path):
        """W02 对照:从未启动(直调形态,GuestSampler 未创建)——
        writers.guest=None 只代表 never_started,不误拒。"""
        sup = _sup(tmp_path, samples_source=_replay_samples(tmp_path))
        assert sup._guest_ever_started is False
        assert sup._writer_live_for_role("telemetry_guest") is False
        sup.biz_rc = 0
        _prep_streams(sup)
        sup.finalize()
        rr = json.loads((tmp_path / "run" / "run_record.json")
                        .read_text(encoding="utf-8"))
        assert rr["writers"]["guest"] is None, \
            "从未启动:None 语义唯一(不与未知混用)"
        assert rr["evidence_complete"] is True


# ================================================= W03:预算出口共享关闭
@requires_linux
class TestW03BudgetExitSharesClose:
    def test_w03_budget_stop_keeps_join_path(self, tmp_path):
        """W03:budget_check 停止后 finalize 的 join 段不跳过——
        已启动写者由共享收尾确认关闭(旧缺陷:stop 后立即置 None,
        join 段永不执行)。真实 guest 线程+真实 budget_check。"""
        sup = _sup(tmp_path, argv=("--", "true"),
                   samples_source=_replay_samples(tmp_path))
        sup.policy["telemetry_budget_bytes"] = 1
        # 真实启动采样线程(replay 模式手动 start,走掩码继承路径)
        sup.guest_sampler = __import__(
            "r17_guest_sampler", fromlist=["GuestSampler"]).GuestSampler(
            emit=lambda rec: sup._emit_guest(rec), interval=5.0,
            detail_interval=30.0, run_id=sup.run_id)
        sup._start_guest_sampler_shielded()
        assert sup._guest_ever_started is True
        time.sleep(0.3)
        sup.budget_check()  # 真实方法:stop 但**不清引用**
        assert sup.guest_sampler is not None, "budget 出口保留句柄"
        sup.biz_rc = 0
        _prep_streams(sup)
        sup.finalize()
        # join 段真实执行:无线程屏障,join 在预算内确认退出
        st = sup._guest_close_state
        assert st is not None and st["stop_requested"] is True \
            and st["started"] is True
        assert st["alive_after_join"] is False, \
            f"无线程屏障时 join 应确认退出:{st}"
        rr = json.loads((tmp_path / "run" / "run_record.json")
                        .read_text(encoding="utf-8"))
        assert rr["writers"]["guest"]["joined"] is True


# ================================================= P:发布边界故障矩阵
@requires_linux
class TestPPublishBoundaryMatrix:
    """P01/P02:真实文件边界注入(私有临时文件写/替换);P03 对照。

    write_summary 的发布边界:tmp.open("w")→write→flush→close→
    os.replace(tmp, summary.json)。注入点覆盖:
      tmp_partial:写 1 字节后失败(P01 部分字节形态)
      tmp_flush:可解析内容写完后 flush 失败(P02)
      replace:tmp 完整但替换失败(P02)
    不替换 write_summary 函数体,只在真实文件操作边界注入。
    """

    def _run_with_inject(self, tmp_path, stage):
        sup = _sup(tmp_path, samples_source=_replay_samples(tmp_path))
        sup.biz_rc = 0
        _prep_streams(sup)
        target = tmp_path / "run" / "summary.json"
        tmpf = tmp_path / "run" / ".summary.json.tmp"
        orig_open = pathlib.Path.open
        orig_replace = pathlib.Path.replace

        def open_patched(self, *a, **kw):
            if stage in ("tmp_partial", "tmp_flush") and \
                    os.fspath(self) == str(tmpf) and a and "w" in str(a[0]):
                fh = orig_open(self, *a, **kw)
                ow = fh.write

                def w(data):
                    if stage == "tmp_partial":
                        ow(data[:1])
                        fh.flush()
                        raise OSError(5, "probe: io error")
                    ow(data)  # 完整可解析内容
                    fh.flush()
                    raise OSError(5, "probe: flush error")
                fh.write = w
                return fh
            return orig_open(self, *a, **kw)

        def replace_patched(self, t, *a, **kw):
            if stage == "replace" and os.fspath(self) == str(tmpf) \
                    and os.fspath(t) == str(target):
                raise OSError(1, "probe: replace denied")
            return orig_replace(self, t, *a, **kw)

        pathlib.Path.open = open_patched
        pathlib.Path.replace = replace_patched
        try:
            sup.run()
        finally:
            pathlib.Path.open = orig_open
            pathlib.Path.replace = orig_replace
        return sup, target, tmpf

    def test_p01_partial_bytes_diagnostic_residue(self, tmp_path):
        """P01:写出 1 字节后失败——最终路径无文件(残片只在私有
        临时名=诊断残片,不冒充成品);publish_failed;evidence
        False;外层非零;实际 verifier 拒绝完整交付。"""
        sup, target, tmpf = self._run_with_inject(tmp_path, "tmp_partial")
        assert sup._summary_publish_failed is True
        assert sup._summary_publish_failure["stage"] == "write_or_replace"
        assert not target.exists(), "最终路径不得留半份内容"
        assert tmpf.exists() and tmpf.read_bytes() == b"{", \
            "失败临时件保留为诊断残片"
        assert sup.control_outcome() == 6
        rr = json.loads((tmp_path / "run" / "run_record.json")
                        .read_text(encoding="utf-8"))
        roles = {r["role"]: r for r in rr["required"]}
        assert roles["summary"]["status"] == "publish_failed"
        assert rr["evidence_complete"] is False
        assert "summary" in rr["missing_roles"]
        vrc, _ = _build_and_verify(tmp_path)
        assert vrc == 1, "实际 verifier 拒绝残片包"

    def test_p02a_parseable_then_flush_failure(self, tmp_path):
        """P02:完整可解析内容写完后 flush 失败——不以"JSON 可解析/
        字节存在"抵消已知失败;无旧文件回退;首因保留。"""
        sup, target, tmpf = self._run_with_inject(tmp_path, "tmp_flush")
        assert sup._summary_publish_failed is True
        assert not target.exists()
        assert tmpf.exists(), "诊断残片保留"
        assert json.loads(tmpf.read_text(encoding="utf-8"))["run_id"] == \
            sup.run_id, "残片内容本身可解析——仍不构成有效发布"
        rr = json.loads((tmp_path / "run" / "run_record.json")
                        .read_text(encoding="utf-8"))
        roles = {r["role"]: r for r in rr["required"]}
        assert roles["summary"]["status"] == "publish_failed"
        assert sup.control_outcome() == 6
        vrc, _ = _build_and_verify(tmp_path)
        assert vrc == 1

    def test_p02b_replace_failure_clean_target(self, tmp_path):
        """P02:tmp 完整但 replace 失败——最终路径干净;发布动作失败
        与内容失败同面(publish_failed);verifier 拒绝。"""
        sup, target, tmpf = self._run_with_inject(tmp_path, "replace")
        assert sup._summary_publish_failed is True
        assert not target.exists()
        assert tmpf.exists()
        rr = json.loads((tmp_path / "run" / "run_record.json")
                        .read_text(encoding="utf-8"))
        roles = {r["role"]: r for r in rr["required"]}
        assert roles["summary"]["status"] == "publish_failed"
        assert sup.control_outcome() == 6
        vrc, _ = _build_and_verify(tmp_path)
        assert vrc == 1

    def test_p03_normal_publish_no_residue(self, tmp_path):
        """P03 对照:正常发布——summary.json 存在且完整、无临时残
        留、evidence 完整、实际 verifier 通过(负例不误伤正常件)。"""
        sup, target, tmpf = self._run_with_inject(tmp_path, "none")
        assert sup._summary_publish_failed is False
        assert target.exists() and target.stat().st_size > 0
        assert not tmpf.exists(), "成功发布不留临时件"
        rr = json.loads((tmp_path / "run" / "run_record.json")
                        .read_text(encoding="utf-8"))
        roles = {r["role"]: r for r in rr["required"]}
        assert roles["summary"]["status"] == "present"
        assert rr["evidence_complete"] is True
        assert sup.control_outcome() == 0
        vrc, _ = _build_and_verify(tmp_path)
        assert vrc == 0, f"正常包 verify 必须通过:{vrc}"
