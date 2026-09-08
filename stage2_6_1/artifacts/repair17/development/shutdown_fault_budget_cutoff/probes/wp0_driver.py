#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WP0 探针驱动:在接手快照副本上复现三项未闭合缺陷(任务书 §3)。

P1(USH-01a 二次错误):真实 main() 入口;业务+真实后代忽略 TERM;主循环
   crash 后,_terminal_shutdown 循环内第一次退出观察抛错——验证 supervisor
   返回时升级(KILL)是否未发生、业务组是否仍活。
P2(USH-01b 共享期限):缩窗工程预算(coop=2s, finalize=5s);停止阶段消耗
   大部分预算后进入辅助停止与 drain——记录每次请求的 timeout 与真实耗时,
   验证后续阶段是否重新获得全额。
P3(USH-02 最后窗口):真实 Python 3.11 模块 + sys.settrace 行级定位,在
   finalize 最后一次停止检查(检查点④)已判定、C 标记未建立的交错点发送
   真实 SIGTERM——验证 handler 登记的归属与最终结果。

只使用固定接手快照的临时工程副本;不触碰活跃部署与正式根;watchdog/
父进程兜底强杀只标测试兜底,不计产品保护成功。
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

WPO = Path.home() / "r17u2_wpo"
SNAP = WPO / "snapshot"
PY = sys.executable

BIZ_IGNORE_SRC = (
    "import os, signal, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "pid = os.fork()\n"
    "if pid == 0:\n"
    "    time.sleep(600)\n"
    "with open(sys.argv[1], 'w') as fh:\n"
    "    fh.write(str(os.getpid()))\n"
    "time.sleep(600)\n")

WIN_IGNORE_SRC = (
    "import os, signal, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "with open(sys.argv[1], 'w') as fh:\n"
    "    fh.write(str(os.getpid()))\n"
    "time.sleep(600)\n")


def _group_alive(pgid: int) -> list[int]:
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as fh:
                text = fh.read()
            rp = text.rindex(")")
            fields = text[rp + 2:].split()
            if int(fields[2]) == pgid and fields[0] != "Z":
                out.append(int(name))
        except (OSError, ValueError, IndexError):
            continue
    return out


def _killpg_safe(pgid: int, tag: str, notes: list[str]) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
        notes.append(f"{tag}: test-watchdog killpg({pgid}) 已执行")
    except OSError as exc:
        notes.append(f"{tag}: killpg({pgid}) 清理结果={exc}")


def _read_marker_pid(base: Path, name: str, wait_s: float = 30.0) -> int | None:
    p = base / name
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if p.is_file():
            try:
                return int(p.read_text().strip())
            except ValueError:
                return None
        time.sleep(0.2)
    return None


def _alerts_events(run_dir: Path) -> list[dict]:
    p = run_dir / "alerts" / "alerts.jsonl"
    if not p.is_file():
        p = run_dir / "alerts.jsonl"
    if not p.is_file():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            out.append({"_raw": ln})
    return out


def _run_child(base: Path, script_name: str, max_wait: float) -> tuple:
    child = base / script_name
    p = subprocess.Popen(
        [PY, str(child), str(SNAP), str(base)],
        start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines: list[str] = []
    done = threading.Event()

    def _reader():
        for ln in p.stdout:
            lines.append(ln.decode("utf-8", "replace").rstrip())
        done.set()
    threading.Thread(target=_reader, daemon=True).start()
    rc = None
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if p.poll() is not None:
            rc = p.returncode
            break
        time.sleep(0.3)
    watchdog = False
    if rc is None:
        p.kill()
        rc = p.wait(timeout=10)
        watchdog = True
        lines.append("PROBE_WATCHDOG_KILLED")
    done.wait(timeout=5)
    (base / "child_stdout.log").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    return rc, lines, watchdog


def _fresh_base(name: str) -> Path:
    """归档旧 base(保留原始证据),返回全新目录——marker/samples 均为
    本次运行产物,避免上一轮残留污染时序判定。"""
    base = WPO / name
    if base.exists():
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        base.rename(WPO / f"{name}_prev_{stamp}")
    base.mkdir(parents=True, exist_ok=True)
    return base


def probe_p1() -> dict:
    base = _fresh_base("p1")
    (base / "biz_ignore_term.py").write_text(BIZ_IGNORE_SRC, encoding="utf-8")
    src = (Path(__file__).parent / "p1_child.py").read_text(encoding="utf-8")
    (base / "p1_child.py").write_text(src, encoding="utf-8")
    rc, lines, watchdog = _run_child(base, "p1_child.py", max_wait=90.0)
    notes: list[str] = []
    # supervisor 返回后:业务组(leader+真实后代)是否仍活
    biz_pid2 = _read_marker_pid(base, "biz_ready.marker", wait_s=0.5)
    alive = _group_alive(biz_pid2) if biz_pid2 else []
    events = _alerts_events(base / "run")
    has_sigkill = any(e.get("event") == "sigkill_sent" for e in events)
    has_term = any(e.get("event") == "sigterm_sent" for e in events)
    has_obs_fail_marker = any("PROBE_INJECT_OBSERVE_FAIL" in ln
                              for ln in lines)
    has_crash_marker = any("PROBE_INJECT_CRASH" in ln for ln in lines)
    if alive and biz_pid2:
        _killpg_safe(biz_pid2, "p1", notes)
    res = {
        "probe": "P1-second-failure",
        "child_rc": rc,
        "watchdog_used": watchdog,
        "biz_leader_pid": biz_pid2,
        "business_group_alive_after_return": bool(alive),
        "alive_members": alive[:8],
        "sigterm_sent": has_term,
        "sigkill_sent": has_sigkill,
        "crash_marker": has_crash_marker,
        "observe_fail_marker": has_obs_fail_marker,
        "defect_confirmed": (rc == 3 and has_obs_fail_marker
                             and bool(alive) and not has_sigkill),
        "notes": notes,
    }
    (base / "p1_result.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def probe_p2() -> dict:
    base = _fresh_base("p2")
    (base / "biz_ignore_term.py").write_text(BIZ_IGNORE_SRC, encoding="utf-8")
    (base / "win_ignore.py").write_text(WIN_IGNORE_SRC, encoding="utf-8")
    src = (Path(__file__).parent / "p2_child.py").read_text(encoding="utf-8")
    (base / "p2_child.py").write_text(src, encoding="utf-8")
    rc, lines, watchdog = _run_child(base, "p2_child.py", max_wait=90.0)
    timeline = []
    budget = None
    for ln in lines:
        if ln.startswith("PROBE_TIMELINE="):
            timeline = json.loads(ln.split("=", 1)[1])
        elif ln.startswith("PROBE_BUDGET="):
            budget = float(ln.split("=", 1)[1])
    notes: list[str] = []
    phases = {e["phase"]: e for e in timeline if "phase" in e}
    t0 = phases.get("terminal_shutdown_enter", {}).get("t")
    analysis: dict = {}
    if t0 is not None and budget is not None:
        sws_in = phases.get("stop_win_sampler_enter", {}).get("t")
        sws_out = phases.get("stop_win_sampler_exit", {}).get("t")
        dr_in = phases.get("drain_enter", {})
        dr_out = phases.get("drain_exit", {}).get("t")
        ts_out = phases.get("terminal_shutdown_exit", {}).get("t")
        spend_ts = (ts_out - t0) if ts_out else None
        remaining_at_sws = budget - (sws_in - t0) if sws_in else None
        sws_spend = (sws_out - sws_in) if (sws_in and sws_out) else None
        remaining_at_drain = (budget - (dr_in.get("t") - t0)
                              if dr_in.get("t") else None)
        drain_req = dr_in.get("timeout_requested")
        total = (dr_out - t0) if dr_out else None
        analysis = {
            "budget_s": budget,
            "terminal_shutdown_spend_s": round(spend_ts, 3) if spend_ts else None,
            "remaining_at_stop_win_sampler_s":
                round(remaining_at_sws, 3) if remaining_at_sws is not None else None,
            "stop_win_sampler_spend_s": round(sws_spend, 3) if sws_spend else None,
            "stop_win_sampler_requested_s": 10,
            "remaining_at_drain_s":
                round(remaining_at_drain, 3) if remaining_at_drain is not None else None,
            "drain_requested_s": drain_req,
            "total_finalize_chain_spend_s": round(total, 3) if total else None,
        }
    events = _alerts_events(base / "run")
    has_wt = any(e.get("event") == "win_sampler_stop_timeout" for e in events)
    a = analysis
    defect = bool(
        a and a.get("drain_requested_s", 0) > max(
            0.0, a.get("remaining_at_drain_s") or 0.0)
        and (a.get("stop_win_sampler_spend_s") or 0) > (
            a.get("remaining_at_stop_win_sampler_s") or 0)
        and (a.get("total_finalize_chain_spend_s") or 0) > (a.get("budget_s") or 0))
    res = {
        "probe": "P2-shared-budget",
        "child_rc": rc,
        "watchdog_used": watchdog,
        "timeline": timeline,
        "analysis": analysis,
        "win_sampler_stop_timeout_event": has_wt,
        "defect_confirmed": defect,
        "notes": notes,
    }
    (base / "p2_result.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def probe_p3() -> dict:
    out: dict = {}
    for mode, tag in (("pre", "p3_pre"), ("in", "p3_in")):
        base = _fresh_base(tag)
        src = (Path(__file__).parent / "p3_child.py").read_text(
            encoding="utf-8")
        (base / "p3_child.py").write_text(src, encoding="utf-8")
        child = base / "p3_child.py"
        p = subprocess.Popen(
            [PY, str(child), str(SNAP), str(base), mode],
            start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        lines: list[str] = []
        done = threading.Event()

        def _reader():
            for ln in p.stdout:
                lines.append(ln.decode("utf-8", "replace").rstrip())
            done.set()
        threading.Thread(target=_reader, daemon=True).start()
        rc = None
        deadline = time.time() + 60.0
        while time.time() < deadline:
            if p.poll() is not None:
                rc = p.returncode
                break
            time.sleep(0.3)
        watchdog = False
        if rc is None:
            p.kill()
            rc = p.wait(timeout=10)
            watchdog = True
            lines.append("PROBE_WATCHDOG_KILLED")
        done.wait(timeout=5)
        (base / "child_stdout.log").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
        kv = {}
        for ln in lines:
            if ln.startswith("PROBE_") and "=" in ln:
                k, v = ln.split("=", 1)
                kv[k] = v
        summary = {}
        sp = base / "run" / "summary.json"
        if sp.is_file():
            try:
                summary = json.loads(sp.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                summary = {"_unreadable": True}
        receipt = {}
        rp = base / "run" / "post_cutoff_signal.json"
        if rp.is_file():
            try:
                receipt = json.loads(rp.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                receipt = {"_unreadable": True}
        sig = kv.get("PROBE_SIG")
        consumed = kv.get("PROBE_CONSUMED")
        post_file = kv.get("PROBE_POST_CUTOFF_FILE")
        if mode == "pre":
            # C 前登记(临界区进入行执行前,handler 已完成):必须被
            # 临界区内最后判定看到并消费——参与本 run 结果。
            verdict = (
                rc == 4 and sig is not None and str(consumed) == "True"
                and summary.get("external_stop_sig") is not None
                and summary.get("external_stop_consumed") is True
                and kv.get("PROBE_HANDLER_DONE") == "15"
                and str(post_file) == "False")
            defect = not verdict
            shape = "pre_cutoff_consumed"
        else:
            # 临界区内(C 标记赋值行,TERM/INT 已屏蔽):信号必然在 C
            # 之后才执行 handler——独立后置回执,不改结果与封口件。
            verdict = (
                rc == 0 and sig is not None and str(consumed) == "False"
                and summary.get("external_stop_sig") is None
                and str(post_file) == "True"
                and str(kv.get("PROBE_COUNT_AT_CUTOFF")) == "0"
                and receipt.get("sig_count_at_cutoff") == 0
                and receipt.get("sig_count_total") == 1)
            defect = not verdict
            shape = "in_cutoff_receipt"
        out[mode] = {
            "probe": f"P3-{shape}",
            "child_rc": rc,
            "watchdog_used": watchdog,
            "signal_sent_marker": any("PROBE_SIGNAL_SENT" in ln
                                      for ln in lines),
            "handler_registered_before_cutoff_store":
                kv.get("PROBE_HANDLER_DONE") == "15",
            "sup_external_stop_sig": sig,
            "sup_sig_count": kv.get("PROBE_SIG_COUNT"),
            "sup_consumed": consumed,
            "count_at_cutoff": kv.get("PROBE_COUNT_AT_CUTOFF"),
            "post_cutoff_signal_json_exists": post_file,
            "post_cutoff_receipt": receipt,
            "summary_external_stop_sig": summary.get("external_stop_sig"),
            "summary_external_stop_consumed": summary.get(
                "external_stop_consumed"),
            "closure_verdict": verdict,
            "defect_confirmed": defect,
            "notes": [],
        }
        (base / "p3_result.json").write_text(
            json.dumps(out[mode], ensure_ascii=False, indent=1),
            encoding="utf-8")
    return out


def main() -> int:
    if not SNAP.is_dir():
        print("ERROR: snapshot 缺失", file=sys.stderr)
        return 2
    out = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "handover_sha": "56f4d0060a4f3960700b7b32c4b58e4d1cb96dfc",
           "supervisor_snapshot": str(SNAP / "r17_supervision.py")}
    for fn in (probe_p1, probe_p2, probe_p3):
        print(f"==== running {fn.__name__} ====", flush=True)
        try:
            out[fn.__name__] = fn()
        except Exception as exc:  # 探针自身失败:保留事实,不伪造结果
            import traceback
            out[fn.__name__] = {"probe_error": str(exc),
                                "traceback": traceback.format_exc()[-2000:]}
    out["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (WPO / "wp0_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("==== wp0_summary ====")
    flat = {}
    for k, v in out.items():
        if not k.startswith("probe_"):
            continue
        if k == "probe_p3" and isinstance(v, dict):
            for m, sub in v.items():
                flat[f"p3_{m}"] = sub.get("defect_confirmed")
        elif isinstance(v, dict) and "defect_confirmed" in v:
            flat[k] = v["defect_confirmed"]
    print(json.dumps(flat, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
