#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 运行监护 supervisor(任务书 WP1-WP5)。

职责分工(任务书 §3):本进程=任务控制者+告警判定+递交;Windows 采样器
(r17_win_sampler.ps1)=宿主遥测独立进程;guest 采样(r17_guest_sampler)
为内部线程。sampler 不做判定、不落 marker;判定/去重/递交/保护全部在
本进程策略引擎(确定性本地代码,不依赖模型在线)。

边界纪律(实现前审查 §7):
- 不导入/不调用执行治理接口,不写资格 journal/请求证据区;监护面拒绝
  记录写 run_supervision/rejected/;
- run_id 只影响日志/状态/路径,不进业务 RNG/namespace,不向业务子进程
  注入任何环境键(env 原样传递);
- 业务 stdout/stderr 直连 run 目录文件(无 PIPE;M15);
- 停止只作用于登记的业务进程组(TERM→30s 合作窗→KILL;M10/M11),
  按实例身份核验,绝不按进程名批量杀;
- 递交=stdout 单行 R17ALERT(宿主后台任务输出通道,TaskOutput 周期
  接收=模式 B)+ spool 持久化;不声称 Agent 已确认;
- 预算:遥测 256MiB/run,80% 降明细,核心事件无法保存→保护性中止
  保留前缀;监护自身开销每样本自记。

用法(经 r17_monitored_entry.sh;测试可直跑):
  r17_supervision.py --run-dir <dir> --task-kind <kind> \
      [--max-seconds N] [--samples-source file:...] -- <argv...>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r17_guest_sampler import GuestSampler, utc_now_iso  # noqa: E402

GIB = 1024 * 1024 * 1024

#: 固定工程保护策略(任务书 §7 表;工程保护值,非统计 gate,不改业务
#: verdict;仅允许运行前收紧,放宽需提交理由)。运行前登记内容哈希。
POLICY: dict[str, Any] = {
    "policy_id": "R17-SUPERVISION-POLICY-v1",
    "win_free_phys": {"warn_below_gib": 8.0, "warn_sustain_s": 30.0,
                      "crit_below_gib": 4.0, "crit_sustain_s": 15.0,
                      "crit_min_samples": 3},
    "win_commit": {"warn_ge_pct": 90.0, "warn_sustain_s": 30.0,
                   "crit_ge_pct": 95.0, "crit_sustain_s": 15.0,
                   "crit_min_samples": 3},
    "guest_memavail": {"warn_below_gib": 4.0, "warn_sustain_s": 30.0,
                       "crit_below_gib": 2.0, "crit_sustain_s": 15.0,
                       "crit_min_samples": 3,
                       "crit_psi_field": "full_avg10", "crit_psi_ge": 1.0},
    "cgroup": {"warn_util_ge_pct": 90.0, "crit_on_oom_events": True},
    "storage": {"ceiling_gib": 300.0, "warn_frac": 0.9,
                "unit": "df -BK used KiB -> GiB(1024^3)"},
    "keyvol": {"warn_below_gib": 20.0, "crit_below_gib": 5.0},
    "observation": {"stale_warn_s": 15.0, "stale_crit_s": 30.0},
    "cooldown_reminder_s": 60.0,
    "recover": {"win_free_ge_gib": 10.0, "win_commit_lt_pct": 85.0,
                "guest_memavail_ge_gib": 6.0, "sustain_s": 30.0},
    "coop_exit_window_s": 30.0,
    "telemetry_budget_bytes": 256 * 1024 * 1024,
    "telemetry_reduce_frac": 0.8,
    "finalize_window_s": 120.0,
    "default_max_seconds": 6 * 3600,
    "progress_stall_warn_s": 600.0,
}

BUSINESS_ERROR_PATTERNS = (
    # 业务结构失败(结构性生成拒绝等)与资源事件是不同类型(§7.2)
    "PairGenerationError",
)


def policy_digest(policy: dict[str, Any] | None = None) -> str:
    payload = json.dumps(policy or POLICY, sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 事件
class Incident:
    """同 run 同原因的一段持续异常(去重/升级/恢复;§7.2)。"""

    def __init__(self, iid: str, kind: str, severity: str,
                 detail: str, first_mono: float):
        self.id = iid
        self.kind = kind
        self.detail = detail
        self.severity = severity
        self.first_mono = first_mono
        self.last_mono = first_mono
        self.peak: dict[str, Any] = {}
        self.samples = 0
        self.recovered = False
        self.stopped_requested = False
        self.last_delivered_mono: float | None = None
        self.delivered_count = 0

    def to_dict(self) -> dict[str, Any]:
        return {"incident_id": self.id, "kind": self.kind,
                "detail": self.detail, "severity": self.severity,
                "first_seen_mono": round(self.first_mono, 1),
                "last_seen_mono": round(self.last_mono, 1),
                "samples": self.samples, "peak": self.peak,
                "recovered": self.recovered,
                "stopped_requested": self.stopped_requested,
                "delivered_count": self.delivered_count}

    def should_deliver(self, severity: str, mono: float,
                       cooldown: float) -> str | None:
        """返回交付动作:open/escalate/recover/reminder/None。"""
        if self.last_delivered_mono is None:
            return "open"
        if severity == "CRITICAL" and self.severity != "CRITICAL":
            return "escalate"
        if self.recovered:
            return "recover"
        if mono - self.last_delivered_mono >= cooldown:
            return "reminder"
        return None


# ---------------------------------------------------------- 持续条件窗
class SustainWindow:
    """低于/超过阈值持续 N 秒且至少 M 个有效样本;无数据不凑持续时间。"""

    def __init__(self) -> None:
        self.since: float | None = None
        self.count = 0

    def update(self, active: bool, mono: float) -> tuple[float, int] | None:
        if active:
            if self.since is None:
                self.since = mono
                self.count = 1
            else:
                self.count += 1
            return (mono - self.since, self.count)
        self.since = None
        self.count = 0
        return None

    def reset(self) -> None:
        self.since = None
        self.count = 0


# ---------------------------------------------------------- 策略引擎
class PolicyEngine:
    """纯判定(可测):输入最新两侧样本与任务树聚合+单调时间,输出触发。

    触发项:{"kind","severity","detail","metrics"};severity ∈ WARNING/
    CRITICAL/PROTECTION_UNAVAILABLE/WORKER。持续窗口状态自持。
    """

    def __init__(self, policy: dict[str, Any] | None = None):
        self.policy = policy or POLICY
        # 双级独立持续窗(W/CRITICAL 各自持续判定,单样本不重复计数)
        self.w_free_warn = SustainWindow()
        self.w_free_crit = SustainWindow()
        self.w_commit_warn = SustainWindow()
        self.w_commit_crit = SustainWindow()
        self.g_mem_crit = SustainWindow()
        self.g_mem_warn = SustainWindow()
        self._pswpout_prev: int | None = None
        self._oom_prev: dict[str, int] = {}
        self._progress_idle_since: float | None = None
        self._recover_since: float | None = None

    def _pct(self, used: float, limit: float) -> float | None:
        if limit <= 0:
            return None
        return 100.0 * used / limit

    def evaluate(self, mono: float, win: dict | None, guest: dict | None,
                 task: dict | None, storage_used_gib: float | None,
                 obs_stale_s: float | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        p = self.policy
        # ---- Windows 物理内存/commit(GetPerformanceInfo 口径) ----
        if win and isinstance(win.get("perf"), dict):
            perf = win["perf"]
            free = perf.get("phys_avail_gb")
            if isinstance(free, (int, float)):
                cw = p["win_free_phys"]
                dc = self.w_free_crit.update(
                    free < cw["crit_below_gib"], mono)
                if dc and dc[0] >= cw["crit_sustain_s"] and \
                        dc[1] >= cw["crit_min_samples"]:
                    out.append({"kind": "win_free_phys", "severity": "CRITICAL",
                                "detail": f"可用物理内存 {free}GiB < "
                                f"{cw['crit_below_gib']}GiB 持续 {dc[0]:.0f}s"
                                f"({dc[1]} 样本)",
                                "metrics": {"free_gib": free}})
                else:
                    dw = self.w_free_warn.update(
                        free < cw["warn_below_gib"], mono)
                    if dw and dw[0] >= cw["warn_sustain_s"]:
                        out.append({"kind": "win_free_phys",
                                    "severity": "WARNING",
                                    "detail": f"可用物理内存 {free}GiB < "
                                    f"{cw['warn_below_gib']}GiB 持续 "
                                    f"{dw[0]:.0f}s",
                                    "metrics": {"free_gib": free}})
            ct, cl = perf.get("commit_total_gb"), perf.get("commit_limit_gb")
            if isinstance(ct, (int, float)) and isinstance(cl, (int, float)):
                pct = self._pct(ct, cl)
                cc = p["win_commit"]
                if pct is not None:
                    dc = self.w_commit_crit.update(
                        pct >= cc["crit_ge_pct"], mono)
                    if dc and dc[0] >= cc["crit_sustain_s"] and \
                            dc[1] >= cc["crit_min_samples"]:
                        out.append({"kind": "win_commit", "severity": "CRITICAL",
                                    "detail": f"commit {pct:.1f}% ≥ "
                                    f"{cc['crit_ge_pct']}% 持续 {dc[0]:.0f}s"
                                    f"({dc[1]} 样本)",
                                    "metrics": {"pct": round(pct, 2)}})
                    else:
                        dw = self.w_commit_warn.update(
                            pct >= cc["warn_ge_pct"], mono)
                        if dw and dw[0] >= cc["warn_sustain_s"]:
                            out.append({"kind": "win_commit",
                                        "severity": "WARNING",
                                        "detail": f"commit {pct:.1f}% ≥ "
                                        f"{cc['warn_ge_pct']}% 持续 "
                                        f"{dw[0]:.0f}s",
                                        "metrics": {"pct": round(pct, 2)}})
        else:
            for w in (self.w_free_warn, self.w_free_crit,
                      self.w_commit_warn, self.w_commit_crit):
                w.update(False, mono)
        # ---- guest MemAvailable(+换出/PSI 组合条件) ----
        if guest and isinstance(guest.get("meminfo"), dict) and \
                "MemAvailable" in guest["meminfo"]:
            avail_gib = guest["meminfo"]["MemAvailable"] / 1024 / 1024
            gm = p["guest_memavail"]
            crit_low = avail_gib < gm["crit_below_gib"]
            psi = guest.get("psi_memory", {})
            psi_val = psi.get(gm["crit_psi_field"]) if isinstance(psi, dict) else None
            psi_hot = isinstance(psi_val, (int, float)) and \
                psi_val >= gm["crit_psi_ge"]
            swap = guest.get("vmstat_swap", {})
            pswpout = swap.get("pswpout") if isinstance(swap, dict) else None
            swap_growing = False
            if isinstance(pswpout, int):
                if self._pswpout_prev is not None:
                    swap_growing = pswpout > self._pswpout_prev
                self._pswpout_prev = pswpout
            # 数据同时失联:保护不可用,不能放行(§7)
            if crit_low and psi_val is None and pswpout is None:
                out.append({"kind": "guest_memavail", "severity":
                            "PROTECTION_UNAVAILABLE",
                            "detail": f"MemAvailable {avail_gib:.2f}GiB 低于 "
                            f"{gm['crit_below_gib']}GiB 且 PSI/换出数据同时"
                            "失联(不能证明安全也不能证明危险)",
                            "metrics": {"avail_gib": round(avail_gib, 3)}})
            else:
                crit_active = crit_low and (swap_growing or psi_hot)
                dc = self.g_mem_crit.update(crit_active, mono)
                if dc and dc[0] >= gm["crit_sustain_s"] and \
                        dc[1] >= gm["crit_min_samples"]:
                    out.append({"kind": "guest_memavail", "severity": "CRITICAL",
                                "detail": f"guest MemAvailable {avail_gib:.2f}"
                                f"GiB < {gm['crit_below_gib']}GiB 持续 "
                                f"{dc[0]:.0f}s 且持续换出/PSI 压力",
                                "metrics": {"avail_gib": round(avail_gib, 3),
                                            "psi_full_avg10": psi_val}})
                else:
                    dw = self.g_mem_warn.update(
                        avail_gib < gm["warn_below_gib"], mono)
                    if dw and dw[0] >= gm["warn_sustain_s"]:
                        out.append({"kind": "guest_memavail",
                                    "severity": "WARNING",
                                    "detail": f"guest MemAvailable "
                                    f"{avail_gib:.2f}GiB < "
                                    f"{gm['warn_below_gib']}GiB 持续 "
                                    f"{dw[0]:.0f}s",
                                    "metrics": {"avail_gib":
                                                round(avail_gib, 3)}})
        # ---- cgroup ----
        if task and isinstance(task.get("cgroup_memory"), dict):
            cg = task["cgroup_memory"]
            limit = cg.get("effective_limit")
            cur = cg.get("current")
            events = cg.get("events") or {}
            if isinstance(events, dict) and "unavailable" not in events:
                for k in ("oom_kill", "oom"):
                    if isinstance(events.get(k), int):
                        prev = self._oom_prev.get(k)
                        if prev is not None and events[k] > prev and \
                                self.policy["cgroup"]["crit_on_oom_events"]:
                            out.append({"kind": "cgroup_oom",
                                        "severity": "CRITICAL",
                                        "detail": f"cgroup memory.events.{k}"
                                        f" {prev}->{events[k]}(新增 OOM 事件)",
                                        "metrics": {"event": k,
                                                    "now": events[k]}})
                        self._oom_prev[k] = events[k]
            if isinstance(limit, int) and isinstance(cur, int) and limit > 0:
                pct = self._pct(cur, limit)
                if pct is not None and pct >= self.policy["cgroup"]["warn_util_ge_pct"]:
                    out.append({"kind": "cgroup_util", "severity": "WARNING",
                                "detail": f"任务 cgroup 内存 {pct:.1f}% ≥ "
                                f"{self.policy['cgroup']['warn_util_ge_pct']}%",
                                "metrics": {"pct": round(pct, 2),
                                            "path": cg.get("path")}})
        # ---- 存储 300GiB 上限(df used 口径) ----
        if storage_used_gib is not None:
            ceil = self.policy["storage"]["ceiling_gib"]
            if storage_used_gib >= ceil:
                out.append({"kind": "storage_ceiling", "severity": "CRITICAL",
                            "detail": f"WSL 根卷已用 {storage_used_gib:.1f}GiB "
                            f"≥ 上限 {ceil:.0f}GiB(口径 {self.policy['storage']['unit']})",
                            "metrics": {"used_gib": round(storage_used_gib, 1)}})
            elif storage_used_gib >= ceil * self.policy["storage"]["warn_frac"]:
                out.append({"kind": "storage_ceiling", "severity": "WARNING",
                            "detail": f"WSL 根卷已用 {storage_used_gib:.1f}GiB "
                            f"≥ 上限 {ceil:.0f}GiB 的 "
                            f"{int(self.policy['storage']['warn_frac']*100)}%",
                            "metrics": {"used_gib": round(storage_used_gib, 1)}})
        # ---- 关键输出卷(win 侧) ----
        if win and isinstance(win.get("vols"), list):
            for vs in win["vols"]:
                if not isinstance(vs, dict) or not vs.get("present"):
                    if isinstance(vs, dict):
                        out.append({"kind": "keyvol", "severity": "CRITICAL",
                                    "detail": f"关键卷 {vs.get('vol')} 失联",
                                    "metrics": vs})
                    continue
                free = vs.get("free_gb")
                kv = self.policy["keyvol"]
                if isinstance(free, (int, float)):
                    if free < kv["crit_below_gib"]:
                        out.append({"kind": "keyvol", "severity": "CRITICAL",
                                    "detail": f"关键卷 {vs['vol']} 可用 "
                                    f"{free}GiB < {kv['crit_below_gib']}GiB",
                                    "metrics": vs})
                    elif free < kv["warn_below_gib"]:
                        out.append({"kind": "keyvol", "severity": "WARNING",
                                    "detail": f"关键卷 {vs['vol']} 可用 "
                                    f"{free}GiB < {kv['warn_below_gib']}GiB",
                                    "metrics": vs})
                # 可写性按"必要证据位置"判定(ps1 遥测输出目录/应急
                # 目录探测);卷根权限不代表证据可写性
                if win.get("telemetry_out_writable") is False:
                    out.append({"kind": "keyvol", "severity": "CRITICAL",
                                "detail": "遥测输出目录可写探测失败"
                                "(必要证据无法写入)",
                                "metrics": vs})
                elif win.get("emergency_writable") is False:
                    out.append({"kind": "keyvol", "severity": "WARNING",
                                "detail": "应急保存目录可写探测失败"
                                "(独立故障域降级;核心遥测仍在)",
                                "metrics": vs})
        # ---- 观测失联 ----
        if obs_stale_s is not None:
            ob = self.policy["observation"]
            if obs_stale_s >= ob["stale_crit_s"]:
                out.append({"kind": "observation_stale", "severity": "CRITICAL",
                            "detail": f"观测流已 {obs_stale_s:.0f}s 无有效样本"
                            f"(≥{ob['stale_crit_s']:.0f}s;阻止新增步骤)",
                            "metrics": {"stale_s": round(obs_stale_s, 1)}})
            elif obs_stale_s >= ob["stale_warn_s"]:
                out.append({"kind": "observation_stale", "severity": "WARNING",
                            "detail": f"观测流 {obs_stale_s:.0f}s 无新样本",
                            "metrics": {"stale_s": round(obs_stale_s, 1)}})
        # ---- 进展未证实(W;不终止) ----
        if task is not None:
            cpu_d = task.get("task_cpu_sec_delta")
            n = task.get("task_count")
            if isinstance(cpu_d, (int, float)) and cpu_d <= 0.001 and \
                    isinstance(n, int) and n > 0:
                if self._progress_idle_since is None:
                    self._progress_idle_since = mono
                elif mono - self._progress_idle_since >= \
                        self.policy["progress_stall_warn_s"]:
                    out.append({"kind": "progress_stall", "severity": "WARNING",
                                "detail": f"任务树 CPU 增量≈0 已 "
                                f"{mono - self._progress_idle_since:.0f}s"
                                "(进展未证实;不推断死锁)",
                                "metrics": {"cpu_delta": cpu_d, "tasks": n}})
            else:
                self._progress_idle_since = None
        return out

    def recovered(self, mono: float, win: dict | None,
                  guest: dict | None) -> bool:
        """恢复迟滞(W 恢复需较宽余量持续 30s;§7.2)。CRITICAL 停止
        请求粘性,不受恢复影响。"""
        p = self.policy
        ok = True
        if win and isinstance(win.get("perf"), dict):
            free = win["perf"].get("phys_avail_gb")
            ct = win["perf"].get("commit_total_gb")
            cl = win["perf"].get("commit_limit_gb")
            if isinstance(free, (int, float)):
                ok = ok and free >= p["recover"]["win_free_ge_gib"]
            if isinstance(ct, (int, float)) and isinstance(cl, (int, float)) \
                    and cl > 0:
                ok = ok and 100.0 * ct / cl < p["recover"]["win_commit_lt_pct"]
        if guest and isinstance(guest.get("meminfo"), dict) and \
                "MemAvailable" in guest["meminfo"]:
            avail = guest["meminfo"]["MemAvailable"] / 1024 / 1024
            ok = ok and avail >= p["recover"]["guest_memavail_ge_gib"]
        if ok:
            if self._recover_since is None:
                self._recover_since = mono
            return mono - self._recover_since >= p["recover"]["sustain_s"]
        self._recover_since = None
        return False


# ------------------------------------------------------- win 样本读取
class WinSampleReader:
    """增量读取 win jsonl(容忍 UTF-8 BOM/半行;解析失败计数不静默)。"""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.parse_errors = 0
        self.last_lines: list[dict] = []
        self._buf = b""

    def read_new(self) -> list[dict]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.offset:
            self.offset = 0  # 文件被重建(不应发生):从头读,不丢告警
            self._buf = b""
        try:
            with self.path.open("rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
        except OSError:
            return []
        self.offset += len(data)
        self._buf += data
        lines = self._buf.split(b"\n")
        self._buf = lines.pop()  # 末尾可能是不完整行,留待下次
        out: list[dict] = []
        for raw in lines:
            if not raw.strip():
                continue
            text = raw.lstrip(b"\xef\xbb\xbf").decode("utf-8", "replace")
            try:
                obj = json.loads(text)
                out.append(obj)
            except ValueError:
                self.parse_errors += 1
        if out:
            self.last_lines = out[-8:]
        return out


# ------------------------------------------------------------- 保护
class Protector:
    """停止请求:TERM→合作窗→KILL;只作用于登记 pgid;记录事实。"""

    def __init__(self, pgid: int, coop_window_s: float,
                 log, samples: GuestSampler | None = None):
        self.pgid = pgid
        self.coop = coop_window_s
        self.log = log
        self.requested_at: float | None = None
        self.term_sent_at: float | None = None
        self.kill_sent_at: float | None = None
        self.terminal_at: float | None = None
        self.survivors: list[int] = []
        self.samples = samples
        self._kill_ineffective_reported = False

    def _alive(self) -> bool:
        try:
            os.kill(self.pgid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def request_stop(self, reason: str) -> dict[str, Any]:
        if self.requested_at is not None:
            return self.status()
        self.requested_at = time.monotonic()
        self.log({"event": "stop_requested", "utc": utc_now_iso(),
                  "reason": reason, "pgid": self.pgid})
        try:
            os.kill(self.pgid, signal.SIGTERM)
            self.term_sent_at = time.monotonic()
            self.log({"event": "sigterm_sent", "utc": utc_now_iso(),
                      "pgid": self.pgid})
        except ProcessLookupError:
            self.terminal_at = time.monotonic()
            self.log({"event": "already_gone", "utc": utc_now_iso()})
        return self.status()

    def poll(self, mono: float) -> bool:
        """合作窗轮询;超时升级 KILL。True=已终态。"""
        if self.terminal_at is not None or self.requested_at is None:
            return self.terminal_at is not None
        if self._alive():
            if self.kill_sent_at is None and self.term_sent_at is not None \
                    and mono - self.term_sent_at >= self.coop:
                try:
                    os.kill(self.pgid, signal.SIGKILL)
                    self.kill_sent_at = time.monotonic()
                    self.log({"event": "sigkill_sent", "utc": utc_now_iso(),
                              "pgid": self.pgid,
                              "note": "合作退出窗口超时,升级终止(仅登记"
                              "进程组)"})
                except ProcessLookupError:
                    self.terminal_at = time.monotonic()
            if self.kill_sent_at is not None and mono - self.kill_sent_at > 10:
                # kill 后仍存活:记录残留(常为不可中断 IO 等待);只报一次
                if not self._kill_ineffective_reported:
                    self.survivors = self._member_pids()
                    if not self.survivors:
                        self.terminal_at = time.monotonic()
                    else:
                        self.log({"event": "kill_ineffective",
                                  "utc": utc_now_iso(),
                                  "survivors": self.survivors[:32],
                                  "note": "停止已请求、完成未证实(可能处于"
                                  "不可中断 IO)"})
                        self._kill_ineffective_reported = True
                        self.terminal_at = None  # 未证实:保持非终态
            return False
        self.terminal_at = time.monotonic()
        self.log({"event": "task_tree_gone", "utc": utc_now_iso()})
        return True

    def _member_pids(self) -> list[int]:
        out = []
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/stat") as fh:
                    text = fh.read()
                rp = text.rindex(")")
                fields = text[rp + 2:].split()
                if int(fields[2]) == self.pgid:
                    out.append(int(name))
            except (OSError, ValueError, IndexError):
                continue
        return out

    def status(self) -> dict[str, Any]:
        return {"pgid": self.pgid,
                "requested": self.requested_at is not None,
                "term_sent": self.term_sent_at is not None,
                "kill_sent": self.kill_sent_at is not None,
                "terminal_confirmed": self.terminal_at is not None,
                "survivors": self.survivors[:32]}


# ----------------------------------------------------------- supervisor
class Supervisor:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.run_dir = Path(args.run_dir).resolve()
        self.run_id = self.run_dir.name
        self.tel_dir = self.run_dir / "telemetry"
        self.alert_dir = self.run_dir / "alerts"
        self.biz_dir = self.run_dir / "business"
        self.rec_dir = self.run_dir / "receipts"
        for d in (self.tel_dir, self.alert_dir, self.biz_dir, self.rec_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.policy = dict(POLICY)
        if args.max_seconds:
            self.policy["default_max_seconds"] = int(args.max_seconds)
        self.engine = PolicyEngine(self.policy)
        self.incidents: dict[str, Incident] = {}
        self.stop_requested_reasons: list[str] = []
        self.protector: Protector | None = None
        self.guest_sampler: GuestSampler | None = None
        self.win_reader: WinSampleReader | None = None
        self.win_proc: subprocess.Popen | None = None
        self.win_pid_windows: int | None = None
        self.emergency_win_dir: str | None = None
        self.biz_proc: subprocess.Popen | None = None
        self.biz_rc: int | None = None
        self.biz_signal: str | None = None
        self.biz_stdout = self.biz_dir / "stdout.log"
        self.biz_stderr = self.biz_dir / "stderr.log"
        self.guest_path = self.tel_dir / "guest_samples.jsonl"
        self.win_path_guest = self.tel_dir / "win_samples.jsonl"
        self.alerts_path = self.alert_dir / "alerts.jsonl"
        self.t0 = time.monotonic()
        self.last_win_line_mono: float | None = None
        self.last_guest_mono: float | None = None
        self.peak: dict[str, Any] = {}
        self.win_sampler_started = False
        self.reduced_detail = False
        self.telemetry_capped = False
        self.finalizing = False
        self.exit_code = 0
        self._finalize_done = False
        self._business_end_logged = False
        self.stage_marks: list[dict[str, Any]] = []
        self._started_utc = utc_now_iso()

    # ---------------- 基础 IO ----------------
    def log(self, obj: dict[str, Any]) -> None:
        obj = dict(obj)
        obj.setdefault("utc", utc_now_iso())
        obj.setdefault("mono", round(time.monotonic() - self.t0, 1))
        obj.setdefault("run_id", self.run_id)
        with self.alerts_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False,
                                separators=(",", ":")) + "\n")

    def stdout_line(self, tag: str, obj: dict[str, Any]) -> None:
        """递交面:宿主后台任务输出(TaskOutput 周期接收=模式 B)。"""
        obj = dict(obj)
        obj.setdefault("utc", utc_now_iso())
        obj.setdefault("run_id", self.run_id)
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        print(f"{tag} {line}", flush=True)

    # ---------------- 递交 ----------------
    def deliver(self, action: str, incident: Incident,
                metrics: dict[str, Any]) -> None:
        now = time.monotonic() - self.t0
        incident.last_delivered_mono = now
        incident.delivered_count += 1
        payload = {
            "action": action, "severity": incident.severity,
            "incident": incident.to_dict(), "metrics": metrics,
            "run_dir": str(self.run_dir),
            "note": "停止请求由本地策略执行,不等待模型回复" if
            incident.severity == "CRITICAL" else "当前任务继续",
        }
        self.log({"event": "alert_delivered", **payload})
        # 通道递交=写入宿主持久化任务输出(stdout);接收=Agent 工具读取
        self.stdout_line("R17ALERT", payload)

    # ---------------- 事件处理 ----------------
    def handle_triggers(self, triggers: list[dict[str, Any]]) -> None:
        mono = time.monotonic() - self.t0
        for tg in triggers:
            kind = tg["kind"]
            sev = tg["severity"]
            inc = self.incidents.get(kind)
            if inc is None:
                inc = Incident(f"{self.run_id[:14]}-{kind}-{int(mono)}",
                               kind, sev, tg["detail"], mono)
                self.incidents[kind] = inc
            escalated = sev == "CRITICAL" and inc.severity != "CRITICAL"
            inc.last_mono = mono
            inc.samples += 1
            m = tg.get("metrics", {})
            for k, v in m.items():
                cur = inc.peak.get(k)
                try:
                    if cur is None or (isinstance(v, (int, float)) and
                                       isinstance(cur, (int, float))
                                       and v > cur):
                        inc.peak[k] = v
                except TypeError:
                    pass
            if escalated:
                inc.severity = "CRITICAL"
            if sev == "WORKER":
                # 业务失败事件:单独递交,不改名资源事件
                self.stdout_line("R17ALERT", {
                    "action": "worker_event", "severity": "WORKER",
                    "kind": kind, "detail": tg["detail"], "metrics": m,
                    "run_dir": str(self.run_dir)})
                self.log({"event": "worker_event", "kind": kind,
                          "detail": tg["detail"], "metrics": m})
                continue
            action = inc.should_deliver(sev, mono,
                                        self.policy["cooldown_reminder_s"])
            if action:
                self.deliver(action, inc, m)
            # CRITICAL/保护不可用 → 保护性停止(不等待模型回复;粘性)
            if sev in ("CRITICAL", "PROTECTION_UNAVAILABLE") and \
                    not inc.stopped_requested:
                inc.stopped_requested = True
                reason = f"{kind}: {tg['detail']}"
                self.stop_requested_reasons.append(reason)
                if self.protector and self.biz_proc and \
                        self.biz_proc.poll() is None:
                    self.protector.request_stop(reason)
                else:
                    self.log({"event": "stop_requested_no_live_task",
                              "reason": reason,
                              "note": "业务已结束/未启动:阻止新增步骤"})

    def recover_warnings(self, mono: float, win: dict | None,
                         guest: dict | None) -> None:
        """恢复迟滞满足:W 级 incident 逐个关闭并递交恢复(交付后移除,
        新一轮异常重新 open);CRITICAL 粘性不自动恢复。"""
        if not self.engine.recovered(mono, win, guest):
            return
        for kind in list(self.incidents):
            inc = self.incidents[kind]
            if inc.severity == "WARNING" and not inc.recovered:
                inc.recovered = True
                self.deliver("recover", inc, {})
                del self.incidents[kind]

    def mark_stage(self, stage: str, note: str = "") -> None:
        rec = {"event": "stage_mark", "utc": utc_now_iso(), "stage": stage,
               "note": note}
        self.stage_marks.append(rec)
        self.log(rec)

    # ---------------- win 采样器生命周期 ----------------
    def _find_powershell(self) -> str | None:
        exe = shutil.which("powershell.exe")
        if exe:
            return exe
        for cand in (
                "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
                "/mnt/c/Windows/SysWOW64/WindowsPowerShell/v1.0/powershell.exe"):
            if Path(cand).exists():
                return cand
        return None

    def _wslpath(self, guest_path: Path | str) -> str | None:
        try:
            out = subprocess.run(["wslpath", "-w", str(guest_path)],
                                 capture_output=True, timeout=15, check=True)
            return out.stdout.decode("utf-8", "replace").strip()
        except (OSError, subprocess.SubprocessError):
            return None

    def start_win_sampler(self) -> bool:
        ps = self._find_powershell()
        if not ps:
            self.log({"event": "win_sampler_unavailable",
                      "reason": "interop powershell 不可达;host 保护条件"
                      "降级为不可判(已登记)"})
            self.stdout_line("R17LOG", {"event": "win_observation_degraded",
                                        "reason": "no_powershell_interop"})
            return False
        ps1_guest = Path(self.args.win_sampler_ps1)
        if not ps1_guest.is_file():
            self.log({"event": "win_sampler_unavailable",
                      "reason": f"ps1 不存在: {ps1_guest}"
                      "(.ps1 须在发布仓库 Windows 侧路径)"})
            return False
        ps1_win = self._wslpath(ps1_guest)
        out_win = self._wslpath(self.win_path_guest)
        if not ps1_win or not out_win:
            self.log({"event": "win_sampler_unavailable",
                      "reason": "wslpath 解析失败"})
            return False
        # 应急目录:宿主 LOCALAPPDATA(独立故障域;一次 interop 查询+缓存)
        try:
            r = subprocess.run([ps, "-NoProfile", "-Command",
                                "$env:LOCALAPPDATA"],
                               capture_output=True, timeout=30, check=True)
            la = r.stdout.decode("utf-8", "replace").strip().rstrip("\\")
            self.emergency_win_dir = (la + "\\r17_supervision_emergency")
        except (OSError, subprocess.SubprocessError):
            self.emergency_win_dir = None
        max_s = int(self.policy["default_max_seconds"]
                    + self.policy["finalize_window_s"] + 60)
        argv = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", ps1_win, "-RunId", self.run_id,
                "-OutFile", out_win, "-MaxSeconds", str(max_s),
                "-Volumes", self.args.win_volumes, "-IntervalSeconds", "5"]
        if self.emergency_win_dir:
            argv += ["-EmergencyDir", self.emergency_win_dir]
        self.win_proc = subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        self.win_reader = WinSampleReader(self.win_path_guest)
        self.win_sampler_started = True
        self.log({"event": "win_sampler_started",
                  "interop_pid": self.win_proc.pid,
                  "out_guest": str(self.win_path_guest),
                  "emergency_win_dir": self.emergency_win_dir,
                  "max_seconds": max_s})
        return True

    def stop_win_sampler(self) -> None:
        if self.win_proc is None:
            return
        pid = self.win_proc.pid
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.win_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.log({"event": "win_sampler_stop_timeout",
                      "interop_pid": pid})
        self.log({"event": "win_sampler_stopped",
                  "interop_pid": pid,
                  "windows_pid": self.win_pid_windows})

    # ---------------- 业务任务 ----------------
    def spawn_business(self) -> int:
        argv = list(self.args.argv)
        with self.biz_stdout.open("wb") as so, \
                self.biz_stderr.open("wb") as se:
            self.biz_proc = subprocess.Popen(
                argv, cwd=self.args.task_cwd or None,
                stdout=so, stderr=se,
                start_new_session=True)  # env 原样传递(不注入任何键)
        pgid = os.getpgid(self.biz_proc.pid)
        # 任务树跟踪联动:采样器在业务 spawn 前创建,此处注入登记
        # 进程组(pgid 主口径)+根 PID(后代为辅),此后采样覆盖任务树
        if self.guest_sampler:
            self.guest_sampler.pgids = {pgid}
            self.guest_sampler.root_pids = {self.biz_proc.pid}
        self.protector = Protector(
            pgid, self.policy["coop_exit_window_s"], self.log)
        self.log({"event": "business_started", "argv": argv,
                  "pid": self.biz_proc.pid, "pgid": pgid,
                  "cwd": self.args.task_cwd or "(inherit)"})
        self.stdout_line("R17LOG", {"event": "business_started",
                                    "pid": self.biz_proc.pid, "pgid": pgid,
                                    "argv": argv[:12]})
        return pgid

    def _scan_business_stderr(self) -> list[str]:
        """业务结构失败模式(读 stderr 尾部,有界)。"""
        found = []
        try:
            size = self.biz_stderr.stat().st_size
            with self.biz_stderr.open("rb") as fh:
                fh.seek(max(0, size - 65536))
                tail = fh.read().decode("utf-8", "replace")
            for pat in BUSINESS_ERROR_PATTERNS:
                if pat in tail:
                    found.append(pat)
        except OSError:
            pass
        return found

    # ---------------- 遥测预算 ----------------
    def telemetry_bytes(self) -> int:
        total = 0
        for p in (self.guest_path, self.win_path_guest, self.alerts_path):
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total

    def budget_check(self) -> None:
        b = self.telemetry_bytes()
        budget = self.policy["telemetry_budget_bytes"]
        if b >= budget * self.policy["telemetry_reduce_frac"] and \
                not self.reduced_detail and self.guest_sampler:
            self.reduced_detail = True
            self.guest_sampler.detail_interval *= 2
            self.log({"event": "telemetry_budget_reduce",
                      "bytes": b, "budget": budget,
                      "action": "detail_interval 翻倍"})
            self.stdout_line("R17LOG", {"event": "telemetry_budget_reduce",
                                        "bytes": b})
        if b >= budget:
            # 核心事件(alerts)继续,采样流停写,保留前缀
            if self.guest_sampler and not self.telemetry_capped:
                self.guest_sampler.stop()
                self.guest_sampler = None
                self.telemetry_capped = True
                self.log({"event": "telemetry_budget_exceeded",
                          "bytes": b, "note": "采样流停写保留前缀;"
                          "alerts 继续;保护逻辑仍在;失联判定改心跳"})
                self.stdout_line("R17ALERT", {
                    "action": "open", "severity": "WARNING",
                    "kind": "telemetry_budget",
                    "detail": f"遥测达预算 {b}B ≥ {budget}B;采样停写,"
                    "事件流继续", "run_dir": str(self.run_dir)})

    # ---------------- 应急兜底 ----------------
    def emergency_write(self, obj: dict[str, Any]) -> None:
        """/mnt/f 写失败时的 C: 独立故障域兜底(§7-15)。"""
        for base in ("/mnt/c/Users",):
            try:
                users = sorted(os.listdir(base))
            except OSError:
                continue
            for u in users:
                d = Path(base) / u / "AppData/Local/r17_supervision_emergency"
                if d.is_dir() or True:
                    try:
                        d.mkdir(parents=True, exist_ok=True)
                        with (d / f"emergency_{self.run_id}.jsonl").open(
                                "a", encoding="utf-8") as fh:
                            fh.write(json.dumps(
                                obj, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
                        return
                    except OSError:
                        continue

    # ---------------- 摘要与 run_record ----------------
    def write_summary(self) -> dict[str, Any]:
        summary = {
            "schema": "r17-supervision-summary-v1",
            "run_id": self.run_id, "policy_id": self.policy["policy_id"],
            "policy_sha256": policy_digest(self.policy),
            "argv": list(self.args.argv),
            "business": {"rc": self.biz_rc, "signal": self.biz_signal,
                         "protector": self.protector.status()
                         if self.protector else None},
            "stop_requested_reasons": self.stop_requested_reasons,
            "incidents": [i.to_dict() for i in self.incidents.values()],
            "peaks": self.peak,
            "coverage": {
                "guest_last_mono": self.last_guest_mono,
                "win_last_mono": self.last_win_line_mono,
                "win_parse_errors": self.win_reader.parse_errors
                if self.win_reader else None,
                "coverage_gaps": self.guest_sampler.coverage_gaps
                if self.guest_sampler else None,
            },
            "telemetry_bytes": self.telemetry_bytes(),
            "stage_marks": self.stage_marks,
            "emergency_win_dir": self.emergency_win_dir,
            "win_pids": {"interop":
                         self.win_proc.pid if self.win_proc else None,
                         "windows": self.win_pid_windows},
            "written_utc": utc_now_iso(),
        }
        try:
            (self.run_dir / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError:
            self.emergency_write({"event": "summary_write_failed",
                                  "run_id": self.run_id,
                                  "summary": summary})
        return summary

    def finalize_run_record(self) -> Path:
        """run_record.json(E4 接口;build 必需集合来源;原子写)。"""
        required = []
        root = self.run_dir.parent.parent  # run_supervision 根
        roles = [(self.guest_path, "telemetry"),
                 (self.win_path_guest, "telemetry"),
                 (self.alerts_path, "alerts"),
                 (self.biz_stdout, "business"),
                 (self.biz_stderr, "business"),
                 (self.run_dir / "summary.json", "summary")]
        for p, role in roles:
            if not p.is_file():
                continue  # 缺件保留缺口,不补造
            h = hashlib.sha256()
            n = 0
            with p.open("rb") as fh:
                while True:
                    chunk = fh.read(1 << 20)
                    if not chunk:
                        break
                    h.update(chunk)
                    n += len(chunk)
            required.append({"role": role,
                             "path": str(p.relative_to(root)).replace("\\", "/"),
                             "sha256": h.hexdigest(), "bytes": n})
        rec = {
            "schema": "r17-run-record-v1",
            "run_id": self.run_id,
            "task_kind": self.args.task_kind,
            "argv": list(self.args.argv),
            "started_utc": self._started_utc,
            "ended_utc": utc_now_iso(),
            "business": {"rc": self.biz_rc, "signal": self.biz_signal,
                         "pgid": self.protector.pgid
                         if self.protector else None},
            "policy": {"id": self.policy["policy_id"],
                       "sha256": policy_digest(self.policy)},
            "required": required,
            "finalized": True,
        }
        tmp = self.run_dir / ".run_record.tmp"
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.run_dir / "run_record.json")
        return self.run_dir / "run_record.json"

    # ---------------- 主循环 ----------------
    def run(self) -> int:
        self.stdout_line("R17LOG", {"event": "supervisor_start",
                                    "run_dir": str(self.run_dir),
                                    "policy": policy_digest(self.policy)})
        self.log({"event": "supervisor_start",
                  "policy_sha256": policy_digest(self.policy),
                  "argv": list(self.args.argv)})
        # 观测自动启动(WP1:不依赖手工开采样器)
        self.start_win_sampler()
        self.guest_sampler = GuestSampler(
            emit=lambda rec: self._emit_guest(rec), interval=5.0,
            detail_interval=30.0)
        # 样本回放模式(测试输入源):不启动线程,由文件喂样本
        replay = self.args.samples_source.startswith("file:") if \
            self.args.samples_source else False
        if not replay:
            self.guest_sampler.start()
        self.mark_stage("observation_ready")
        # 就绪检查(§5.4):核心观测可用才启动业务;该检查不阻止测试
        time.sleep(0.2 if replay else 3.0)
        if not replay:
            if self.guest_sampler.last_sample_mono is None:
                self.stdout_line("R17LOG", {"event":
                                            "guest_sampler_no_first_sample"})
        self.mark_stage("business_spawn")
        self.spawn_business()
        max_s = self.policy["default_max_seconds"]
        last_budget_check = 0.0
        last_storage_check = 0.0
        last_poll_mono = time.monotonic()
        # 信号:supervisor 自身被停→走收尾
        def _sig(sig, frame):
            self.log({"event": "supervisor_signal", "sig": sig})
            if self.protector and self.biz_proc and \
                    self.biz_proc.poll() is None:
                self.protector.request_stop(f"supervisor_signal_{sig}")
        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)
        replay_records = self._load_replay() if replay else []
        replay_idx = 0
        while True:
            mono = time.monotonic() - self.t0
            # ---- 样本获取 ----
            win_latest: dict | None = None
            if self.win_reader:
                for line in self.win_reader.read_new():
                    if line.get("event") == "sample":
                        win_latest = line
                        self.last_win_line_mono = mono
                    elif line.get("event") == "sampler_start":
                        self.win_pid_windows = line.get("pid")
                        self.log({"event": "win_sampler_ready",
                                  "windows_pid": self.win_pid_windows})
                    elif line.get("event") in ("vol_missing",
                                               "evidence_write_failed",
                                               "guest_vm_gone"):
                        # host 侧事件(Guest 不可见):升级递交
                        self.handle_triggers([{
                            "kind": f"win_{line['event']}",
                            "severity": "CRITICAL",
                            "detail": json.dumps(line, ensure_ascii=False)[:300],
                            "metrics": line}])
            if replay:
                if replay_idx < len(replay_records):
                    rec = replay_records[replay_idx]
                    replay_idx += 1
                    win_latest = rec.get("win")
                    if win_latest:
                        self.last_win_line_mono = mono
                    guest_rec = rec.get("guest")
                    if guest_rec:
                        self.last_guest_mono = mono
                else:
                    pass
            else:
                guest_rec = None
            task_agg = self._task_aggregate(guest_rec)
            # ---- 观测新鲜度 ----
            # 启动宽限 60s(采样器冷启动不算失联);遥测预算停写
            # (capped)时采样流不再更新,失联判定以主循环心跳代替
            # 并在覆盖记录中如实标注。
            stale = None
            if not replay:
                if self.telemetry_capped:
                    stale = None
                else:
                    newest = max(x for x in
                                 (self.last_win_line_mono,
                                  self.last_guest_mono)
                                 if x is not None) if (
                        self.last_win_line_mono or
                        self.last_guest_mono) else None
                    if newest is not None:
                        # clamp 竞态:guest 线程可能在主循环计算
                        # mono 之后更新 last_*_mono(采样时间略"未来"),
                        # 负差经 % 会翻成 ~60s 假失联(全量回归真实
                        # 负载下触发过的缺陷,禁再用取模做宽限)
                        stale = max(0.0, mono - newest)
                        if mono < 60.0:
                            stale = None  # 启动宽限:冷启动不判失联
            # ---- 业务退出监控 ----
            if self.biz_proc is not None and self.biz_proc.poll() is not None:
                rc = self.biz_proc.returncode
                self.biz_rc = rc
                self.biz_signal = f"SIG{-rc}" if rc < 0 else None
                if not self._business_end_logged:
                    self._business_end_logged = True
                    patterns = self._scan_business_stderr()
                    self.log({"event": "business_exited", "rc": rc,
                              "stderr_patterns": patterns})
                    self.stdout_line("R17LOG", {"event": "business_exited",
                                                "rc": rc})
                    if rc != 0:
                        trig = {"kind": "worker_exit", "severity": "WORKER",
                                "detail": f"业务进程 rc={rc}" +
                                (f";stderr 尾部含 {patterns}"
                                 if patterns else ""),
                                "metrics": {"rc": rc,
                                            "patterns": patterns}}
                        self.handle_triggers([trig])
                    self.mark_stage("business_exited", f"rc={rc}")
            # ---- 保护轮询 ----
            if self.protector:
                self.protector.poll(mono)
            # ---- 判定 ----
            storage_used = None
            if mono - last_storage_check >= 60:
                last_storage_check = mono
                storage_used = self._storage_used_gib()
            triggers = self.engine.evaluate(
                mono, win_latest, guest_rec, task_agg,
                storage_used, stale)
            self.recover_warnings(mono, win_latest, guest_rec)
            if triggers:
                self.handle_triggers(triggers)
            # ---- 峰值记录(不同阶段/进程不混加) ----
            self._update_peaks(win_latest, guest_rec, task_agg)
            # ---- 预算(30s 一次) ----
            if mono - last_budget_check >= 30:
                last_budget_check = mono
                self.budget_check()
            # ---- 退出条件 ----
            biz_done = self.biz_proc is not None and \
                self.biz_proc.poll() is not None
            prot_pending = self.protector is not None and \
                self.protector.requested_at is not None and \
                self.protector.terminal_at is None
            if biz_done and not prot_pending:
                break
            if biz_done and prot_pending:
                # 停止请求下业务已退但终态未证实:再等合作窗+10s
                if self.protector.kill_sent_at is None and \
                        mono - (self.protector.requested_at or 0) > \
                        self.policy["coop_exit_window_s"] + 10:
                    break
            if mono >= max_s:
                self.handle_triggers([{
                    "kind": "run_timeout", "severity": "CRITICAL",
                    "detail": f"达到预登记最大运行时长 {max_s}s",
                    "metrics": {}}])
                time.sleep(1)
                continue
            # ---- 节拍(回放模式加速) ----
            step = 0.05 if replay else 1.0
            now = time.monotonic()
            sleep_for = max(0.0, (last_poll_mono + step) - now)
            last_poll_mono = now
            time.sleep(min(sleep_for, 5.0))
        # ---- 收尾 ----
        self.finalize()
        return self.exit_code

    def _load_replay(self) -> list[dict]:
        path = Path(self.args.samples_source.split("file:", 1)[1])
        recs = []
        for line in path.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    continue
        return recs

    def _emit_guest(self, rec: dict) -> None:
        try:
            with self.guest_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False,
                                    separators=(",", ":")) + "\n")
        except OSError:
            self.emergency_write({"event": "guest_telemetry_write_failed",
                                  "run_id": self.run_id})
            return
        if rec.get("event") == "guest_sample":
            self.last_guest_mono = time.monotonic() - self.t0

    def _task_aggregate(self, guest_rec: dict | None) -> dict | None:
        if not guest_rec or guest_rec.get("event") != "guest_sample":
            return None
        return guest_rec

    def _storage_used_gib(self) -> float | None:
        try:
            out = subprocess.run(["df", "-BK", "--output=used", "/"],
                                 capture_output=True, timeout=15, check=True)
            line = out.stdout.decode().strip().split("\n")[-1]
            used_kib = int("".join(c for c in line if c.isdigit()))
            return used_kib / 1024 / 1024
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def _update_peaks(self, win: dict | None, guest: dict | None,
                      task: dict | None) -> None:
        def put(key, val, lower_better=True):
            if not isinstance(val, (int, float)):
                return
            cur = self.peak.get(key)
            if cur is None or (val < cur if lower_better else val > cur):
                self.peak[key] = val
        if win and isinstance(win.get("perf"), dict):
            put("win_free_phys_min_gib", win["perf"].get("phys_avail_gb"))
            put("win_commit_max_pct",
                round(100.0 * win["perf"]["commit_total_gb"] /
                      max(win["perf"]["commit_limit_gb"], 1e-9), 2)
                if isinstance(win["perf"].get("commit_total_gb"), (int, float))
                and isinstance(win["perf"].get("commit_limit_gb"), (int, float))
                else None, lower_better=False)
        if guest and isinstance(guest.get("meminfo"), dict):
            put("guest_memavail_min_gib",
                guest["meminfo"].get("MemAvailable", 0) / 1024 / 1024)
        if task:
            put("task_tree_rss_max_gib",
                (task.get("tasks_total_rss_kb") or 0) / 1024 / 1024,
                lower_better=False)
            put("task_cpu_max_delta_s", task.get("task_cpu_sec_delta"),
                lower_better=False)

    def finalize(self) -> None:
        if self._finalize_done:
            return
        self._finalize_done = True
        self.finalizing = True
        self.mark_stage("finalize_begin")
        # 有限收尾窗:等 guest 采样线程最后一轮
        if self.guest_sampler:
            self.guest_sampler.stop()
            if self.guest_sampler.is_alive():  # replay 模式未启动线程
                self.guest_sampler.join(timeout=15)
            self.guest_sampler = None
        self.stop_win_sampler()
        # 顺序合同:全部 alerts 写入(含 supervisor_end)必须先于
        # run_record 的哈希计算——否则清单记录与文件矛盾(build 拒绝)
        self.log({"event": "supervisor_end",
                  "incidents": len(self.incidents),
                  "business_rc": self.biz_rc})
        summary = self.write_summary()
        rr = self.finalize_run_record()
        self.stdout_line("R17LOG", {"event": "supervisor_end",
                                    "run_dir": str(self.run_dir),
                                    "incidents": len(self.incidents),
                                    "business_rc": self.biz_rc,
                                    "summary": str(self.run_dir /
                                                   "summary.json"),
                                    "run_record": str(rr)})


def main() -> int:
    ap = argparse.ArgumentParser(description="R17 运行监护 supervisor")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--task-kind", required=True,
                    choices=("pytest", "rehearsal", "c3diag",
                             "engineering", "fixture"))
    ap.add_argument("--task-cwd", default=None)
    ap.add_argument("--max-seconds", type=int, default=0)
    ap.add_argument("--samples-source", default="",
                    help="file:<jsonl>(测试输入源;生产入口不暴露)")
    ap.add_argument("--win-sampler-ps1", default=os.environ.get(
        "R17_WIN_SAMPLER_PS1",
        "/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/"
        "r17_win_sampler.ps1"),
        help="ps1 必须在 Windows 可达路径(发布仓库侧;.ps1 不入 WSL 同步面)")
    ap.add_argument("--win-volumes", default="C:,F:")
    ap.add_argument("argv", nargs=argparse.REMAINDER,
                    help="-- 之后为业务命令")
    args = ap.parse_args()
    if args.argv and args.argv[0] == "--":
        args.argv = args.argv[1:]
    if not args.argv:
        print("ERROR: 缺业务命令(-- <argv...>)", file=sys.stderr)
        return 2
    sup = Supervisor(args)
    try:
        return sup.run()
    except Exception as exc:  # 不静默消掉监护自身缺陷
        import traceback
        tb = traceback.format_exc()
        try:
            sup.log({"event": "supervisor_crash", "error": str(exc),
                     "traceback": tb[:4000]})
            sup.emergency_write({"event": "supervisor_crash",
                                 "run_id": sup.run_id, "error": str(exc)})
            if sup.biz_proc and sup.biz_proc.poll() is None and \
                    sup.protector:
                sup.protector.request_stop(f"supervisor_crash:{exc}")
        finally:
            crash_alert = json.dumps(
                {"action": "open", "severity": "CRITICAL",
                 "kind": "supervisor_crash", "detail": str(exc)[:300]},
                ensure_ascii=False)
            print(f"R17ALERT {crash_alert}", flush=True)
            try:
                sup.finalize()
            except Exception:
                pass
        return 3


if __name__ == "__main__":
    sys.exit(main())
