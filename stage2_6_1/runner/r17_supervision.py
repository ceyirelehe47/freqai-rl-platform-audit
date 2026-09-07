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
import threading
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
    # B1/WP1:启动资源准入(工程准入条件,不是课程 gate;就绪=数据有效,
    # 准入=资源够开始重任务;两道判定分开记录)。首样本新鲜度=两个
    # 核心采样周期。
    "startup_admission": {
        "win_free_min_gib": 8.0, "win_commit_max_pct": 90.0,
        "guest_avail_min_gib": 4.0, "keyvol_min_free_gib": 20.0,
        "first_sample_max_age_s": 10.0},
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
    """低于/超过阈值持续 N 秒且至少 M 个有效样本;无数据不凑持续时间。

    S1 修复(WP1):重复消费同一条快照不得增加有效样本计数——
    count 仅在 new_sample=True(该来源出现新样本)时 +1;持续时长
    仍按调用方单调钟累计(基于最后已知事实持续成立的事实判定,
    采样断流由独立失联检测负责,不与本窗口混算)。
    """

    def __init__(self) -> None:
        self.since: float | None = None
        self.count = 0

    def update(self, active: bool, mono: float,
               new_sample: bool = True) -> tuple[float, int] | None:
        if active:
            if self.since is None:
                self.since = mono
                self.count = 1
            elif new_sample:
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
        # S1:样本身份跟踪(同一条快照重复消费不增加窗口样本计数)
        self._last_win_id: Any = None
        self._last_guest_id: Any = None

    @staticmethod
    def _sample_id(rec: dict | None) -> Any:
        """样本身份(utc);无身份字段=每次调用视为新样本(兼容注入)。"""
        if not isinstance(rec, dict):
            return None
        return rec.get("utc")

    def _is_new(self, source: str, rec: dict | None) -> bool:
        sid = self._sample_id(rec)
        if sid is None:
            return True
        key = "_last_win_id" if source == "win" else "_last_guest_id"
        prev = getattr(self, key)
        setattr(self, key, sid)
        return prev != sid

    def _pct(self, used: float, limit: float) -> float | None:
        if limit <= 0:
            return None
        return 100.0 * used / limit

    def evaluate(self, mono: float, win: dict | None, guest: dict | None,
                 task: dict | None, storage_used_gib: float | None,
                 obs_stale: dict[str, float | None] | float | None
                 ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        p = self.policy
        new_win = self._is_new("win", win)
        new_guest = self._is_new("guest", guest)
        # ---- Windows 物理内存/commit(GetPerformanceInfo 口径) ----
        if win and isinstance(win.get("perf"), dict):
            perf = win["perf"]
            free = perf.get("phys_avail_gb")
            if isinstance(free, (int, float)):
                cw = p["win_free_phys"]
                dc = self.w_free_crit.update(
                    free < cw["crit_below_gib"], mono, new_win)
                if dc and dc[0] >= cw["crit_sustain_s"] and \
                        dc[1] >= cw["crit_min_samples"]:
                    out.append({"kind": "win_free_phys", "severity": "CRITICAL",
                                "detail": f"可用物理内存 {free}GiB < "
                                f"{cw['crit_below_gib']}GiB 持续 {dc[0]:.0f}s"
                                f"({dc[1]} 样本)",
                                "metrics": {"free_gib": free}})
                else:
                    dw = self.w_free_warn.update(
                        free < cw["warn_below_gib"], mono, new_win)
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
                        pct >= cc["crit_ge_pct"], mono, new_win)
                    if dc and dc[0] >= cc["crit_sustain_s"] and \
                            dc[1] >= cc["crit_min_samples"]:
                        out.append({"kind": "win_commit", "severity": "CRITICAL",
                                    "detail": f"commit {pct:.1f}% ≥ "
                                    f"{cc['crit_ge_pct']}% 持续 {dc[0]:.0f}s"
                                    f"({dc[1]} 样本)",
                                    "metrics": {"pct": round(pct, 2)}})
                    else:
                        dw = self.w_commit_warn.update(
                            pct >= cc["warn_ge_pct"], mono, new_win)
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
                dc = self.g_mem_crit.update(crit_active, mono, new_guest)
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
                        avail_gib < gm["warn_below_gib"], mono, new_guest)
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
        # ---- 观测失联(每必要来源独立判活;WP1 §4.3) ----
        # obs_stale 兼容两种形态:dict{"win","guest"}(新,独立判活)或
        # float(旧,两源同值;回放/注入兼容)。
        if isinstance(obs_stale, dict):
            stale_map = obs_stale
        elif isinstance(obs_stale, (int, float)):
            stale_map = {"win": obs_stale, "guest": obs_stale}
        else:
            stale_map = {}
        ob = self.policy["observation"]
        for src in ("win", "guest"):
            sv = stale_map.get(src)
            if sv is None:
                continue
            if sv >= ob["stale_crit_s"]:
                out.append({"kind": f"observation_stale_{src}",
                            "severity": "CRITICAL",
                            "detail": f"{src} 观测流已 {sv:.0f}s 无有效样本"
                            f"(≥{ob['stale_crit_s']:.0f}s;阻止新增步骤)",
                            "metrics": {"stale_s": round(sv, 1)}})
            elif sv >= ob["stale_warn_s"]:
                out.append({"kind": f"observation_stale_{src}",
                            "severity": "WARNING",
                            "detail": f"{src} 观测流 {sv:.0f}s 无新样本",
                            "metrics": {"stale_s": round(sv, 1)}})
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


# ------------------------------------------------ 有效样本判定(B1/WP1)
def _finite_num(v) -> bool:
    """有限数值(bool 不是数值;NaN/Inf 拒绝)。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool) \
        and v == v and v not in (float("inf"), float("-inf"))


def validate_win_sample(line: dict | None, *, run_id: str | None = None,
                        ) -> tuple[bool, str]:
    """host 资源样本有效性:身份+结构+数值范围(§4.1)。

    解析成功/来源已启动/有效资源样本三层分开;就绪只认最后一层。
    零可用内存是**有效但危险**的数据(不误记缺测后放行,交给策略)。
    返回 (ok, reason);reason 词表供就绪拒绝与摘要披露。
    """
    if not isinstance(line, dict):
        return False, "not_object"
    if line.get("event") != "sample":
        return False, f"not_sample_event:{line.get('event')}"
    if run_id is not None and line.get("run_id") not in (None, run_id):
        # 无 run_id 的行(旧格式)宽容;带错 run_id 的行拒绝(错误运行身份)
        return False, "run_id_mismatch"
    perf = line.get("perf")
    if not isinstance(perf, dict):
        return False, "perf_missing"
    need = ("phys_avail_gb", "phys_total_gb",
            "commit_total_gb", "commit_limit_gb")
    for k in need:
        if not _finite_num(perf.get(k)):
            return False, f"perf_invalid:{k}"
    if perf["phys_total_gb"] <= 0 or perf["commit_limit_gb"] <= 0:
        return False, "perf_invalid:denominator"
    if perf["phys_avail_gb"] < 0 or perf["commit_total_gb"] < 0:
        return False, "perf_invalid:negative"
    # 单位/范围合理性(5% 容差):GiB 口径下可用>总量即单位错位
    if perf["phys_avail_gb"] > perf["phys_total_gb"] * 1.05:
        return False, "perf_invalid:avail_gt_total"
    if perf["commit_total_gb"] > perf["commit_limit_gb"] * 1.05:
        return False, "perf_invalid:commit_gt_limit"
    # 必要输出卷检查有本次有效结果(只验在场的卷记录结构)
    vols = line.get("vols")
    if vols is not None and not isinstance(vols, list):
        return False, "vols_invalid"
    return True, "ok"


def validate_guest_sample(rec: dict | None) -> tuple[bool, str]:
    """guest 资源样本有效性(§4.1):MemTotal/MemAvailable 有限、
    单位一致(kB)、0≤可用≤总量;utc 身份字段在场。"""
    if not isinstance(rec, dict):
        return False, "not_object"
    if rec.get("event") != "guest_sample":
        return False, f"not_sample_event:{rec.get('event')}"
    if not rec.get("utc"):
        return False, "utc_missing"
    mi = rec.get("meminfo")
    if not isinstance(mi, dict):
        return False, "meminfo_missing"
    mt, ma = mi.get("MemTotal"), mi.get("MemAvailable")
    if not _finite_num(mt) or not _finite_num(ma):
        return False, "meminfo_invalid"
    if mt <= 0:
        return False, "meminfo_invalid:total"
    if ma < 0 or ma > mt * 1.05:
        return False, "meminfo_invalid:range"
    return True, "ok"


# ------------------------------------------------------- win 样本读取
class WinSampleReader:
    """增量读取 win jsonl(容忍 UTF-8 BOM/半行;解析失败计数不静默)。

    B1 修复:saw_any(首条可解析行,诊断用)与 saw_valid(首条**有效
    资源样本**,就绪屏障消费)分层;start-only/空 sample/坏数值行
    不能证明观测能力。last_valid_mono 供新鲜度判定(不把文件
    mtime 或读取时刻当生成时刻:以本进程读到有效行的单调时刻计)。
    """

    def __init__(self, path: Path, run_id: str | None = None):
        self.path = path
        self.run_id = run_id
        self.offset = 0
        self.parse_errors = 0
        self.invalid_samples = 0
        self.invalid_reasons: list[str] = []
        self.last_lines: list[dict] = []
        self.saw_any = False    # 首条可解析 JSON 行(含 sampler_start)
        self.saw_valid = False  # 首条通过 validate_win_sample 的样本
        self.last_valid: dict | None = None
        self.last_valid_mono: float | None = None
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
            self.saw_any = True
        # 有效性分层:只有通过校验的 sample 行刷新有效首样本状态
        for obj in out:
            ok, reason = validate_win_sample(obj, run_id=self.run_id)
            if ok:
                self.saw_valid = True
                self.last_valid = obj
                self.last_valid_mono = time.monotonic()
            elif obj.get("event") == "sample":
                self.invalid_samples += 1
                if len(self.invalid_reasons) < 16:
                    self.invalid_reasons.append(reason)
        return out


# ------------------------------------------------------------- 保护
class Protector:
    """停止请求:TERM→合作窗→KILL;只作用于登记进程组;记录事实。

    S3 修复(WP2):
    - 信号全部经 os.killpg(进程组语义);os.kill(pgid,...) 只作用于
      同值正 PID,既到不了整个组、还可能命中无关进程;
    - 时钟统一:requested/term/kill/terminal 时间戳与 poll(mono) 同一
      基准(由 mono_fn 提供;supervisor 传 run-relative 相对钟)——
      绝对 time.monotonic() 与 run-relative 差值在长运行机器上为
      大负数,升级判定永不触发;
    - 实例身份:发信号前核验 leader pid 的 starttime 仍是登记实例
      (PID 复用防护)且 pgrp 仍是登记 pgid;不符则不发送,如实记
      identity_mismatch(完成未证实);
    - 探活按组成员扫描(leader 退出不等于任务树消失;越出可保证
      边界的后代不盲杀,残留如实记录)。
    """

    def __init__(self, pgid: int, coop_window_s: float, log,
                 samples: GuestSampler | None = None,
                 *, leader_pid: int | None = None,
                 leader_start_ticks: int | None = None,
                 mono_fn=None):
        self.pgid = pgid
        self.coop = coop_window_s
        self.log = log
        self.leader_pid = leader_pid
        self.leader_start = leader_start_ticks
        self.mono = mono_fn or time.monotonic
        self.requested_at: float | None = None
        self.term_sent_at: float | None = None
        self.kill_sent_at: float | None = None
        self.terminal_at: float | None = None
        self.survivors: list[int] = []
        self.samples = samples
        self.identity_mismatch = False
        self._kill_ineffective_reported = False
        # B2:控制路径(request_stop/poll)零 I/O——日志只入内存
        # pending 列表,由调用方在控制动作之后经 flush_logs() 递交
        # (丢失窗口=调用方 flush 周期;evidence 如实可查)。
        self.pending_logs: list[dict[str, Any]] = []

    # ---- 实例身份(/proc/<pid>/stat 的 pgrp+starttime) ----
    def _proc_identity(self, pid: int) -> tuple[int, int] | None:
        try:
            with open(f"/proc/{pid}/stat") as fh:
                text = fh.read()
            rp = text.rindex(")")
            fields = text[rp + 2:].split()
            return int(fields[2]), int(fields[19])  # pgrp, starttime
        except (OSError, ValueError, IndexError):
            return None

    def _identity_ok(self) -> bool:
        """发信号前置:登记 leader 仍是登记实例且仍属登记组。"""
        if self.leader_pid is None or self.leader_start is None:
            return True  # 未登记身份(旧调用兼容):退化为组存在性
        ident = self._proc_identity(self.leader_pid)
        if ident is None:
            # leader 已退出:组可能仍有成员;组身份仍以 killpg 目标为准
            return True
        pgrp, start = ident
        return pgrp == self.pgid and start == self.leader_start

    def _signal(self, sig: int) -> None:
        """组信号守卫:pgid 合法(>1 且非自身组)才发送。"""
        if self.pgid <= 1 or self.pgid == os.getpgrp():
            raise PermissionError(
                f"拒绝向非法/自身进程组发信号: pgid={self.pgid}")
        os.killpg(self.pgid, sig)

    def _alive(self) -> bool:
        """组成员扫描探活(不是只探 leader)。"""
        return bool(self._member_pids())

    def _safe_log(self, rec: dict[str, Any]) -> None:
        # B2:控制路径零 I/O——只入内存列表(append 不做任何文件/
        # 管道操作);flush_logs() 由控制动作之后的调用方执行。
        self.pending_logs.append(rec)

    def flush_logs(self) -> int:
        """把积压控制日志递交至 log 回调(返回条数;幂等)。

        回调本身仍应非阻塞(Supervisor.log=异步投递);本方法只在
        控制动作完成后由主循环/finalize 调用。
        """
        n = len(self.pending_logs)
        while self.pending_logs:
            rec = self.pending_logs.pop(0)
            try:
                self.log(rec)
            except Exception:  # noqa: BLE001 —— 递交失败不阻断后续
                pass
        return n

    def request_stop(self, reason: str) -> dict[str, Any]:
        if self.requested_at is not None:
            return self.status()
        if not self._identity_ok():
            self.identity_mismatch = True
            self.requested_at = self.mono()
            self._safe_log({"event": "identity_mismatch",
                            "utc": utc_now_iso(), "reason": reason,
                            "pgid": self.pgid,
                            "leader_pid": self.leader_pid,
                            "note": "登记实例身份不符(PID 复用/组漂移);"
                            "不发送信号;stop_requested+completion_"
                            "unconfirmed"})
            return self.status()
        self.requested_at = self.mono()
        # B2/WP2 修复:控制动作先于任何日志 I/O——_safe_log 不得在
        # 信号发送前执行(日志写盘阻塞时信号被无限延迟;try/except
        # 只能处理返回的异常,不能中断未返回的写)。_safe_log 本身
        # 已是异步投递(见 Supervisor.log),这里再固定顺序合同。
        try:
            self._signal(signal.SIGTERM)
            self.term_sent_at = self.mono()
            self._safe_log({"event": "sigterm_sent", "utc": utc_now_iso(),
                            "pgid": self.pgid,
                            "note": "已向登记进程组发送(killpg)"})
            self._safe_log({"event": "stop_requested", "utc": utc_now_iso(),
                            "reason": reason, "pgid": self.pgid})
        except ProcessLookupError:
            self.terminal_at = self.mono()
            self._safe_log({"event": "already_gone", "utc": utc_now_iso()})
        except PermissionError as exc:
            self._safe_log({"event": "signal_denied", "utc": utc_now_iso(),
                            "pgid": self.pgid, "error": str(exc)[:200],
                            "note": "权限不足;stop_requested+completion_"
                            "unconfirmed"})
        return self.status()

    def poll(self, mono: float) -> bool:
        """合作窗轮询;超时升级 KILL(组信号)。True=已终态。

        mono 与 self.mono() 同基准(时钟一致性由构造方保证)。
        """
        if self.terminal_at is not None or self.requested_at is None:
            return self.terminal_at is not None
        if self.identity_mismatch:
            # 身份不符:不发送任何后续信号;成员仍存活则如实保留
            members = self._member_pids()
            if members:
                self.survivors = members
                return False
            self.terminal_at = self.mono()
            return True
        if self._alive():
            if self.kill_sent_at is None and self.term_sent_at is not None \
                    and mono - self.term_sent_at >= self.coop:
                # B2:升级同样先发信号、后记日志(控制链不等待 I/O)
                try:
                    self._signal(signal.SIGKILL)
                    self.kill_sent_at = self.mono()
                    self._safe_log({"event": "sigkill_sent",
                                    "utc": utc_now_iso(),
                                    "pgid": self.pgid,
                                    "note": "合作退出窗口超时,升级终止"
                                    "(仅登记进程组;killpg)"})
                except ProcessLookupError:
                    self.terminal_at = self.mono()
                except PermissionError as exc:
                    self._safe_log({"event": "signal_denied",
                                    "utc": utc_now_iso(),
                                    "pgid": self.pgid,
                                    "error": str(exc)[:200]})
            if self.kill_sent_at is not None and \
                    mono - self.kill_sent_at > 10:
                # kill 后仍存活:记录残留(常为不可中断 IO);只报一次
                if not self._kill_ineffective_reported:
                    self.survivors = self._member_pids()
                    if not self.survivors:
                        self.terminal_at = self.mono()
                    else:
                        self._safe_log({"event": "kill_ineffective",
                                        "utc": utc_now_iso(),
                                        "survivors": self.survivors[:32],
                                        "note": "停止已请求、完成未证实"
                                        "(可能处于不可中断 IO)"})
                        self._kill_ineffective_reported = True
                        self.terminal_at = None  # 未证实:保持非终态
            return False
        self.terminal_at = self.mono()
        self._safe_log({"event": "task_tree_gone", "utc": utc_now_iso(),
                        "note": "按进程组成员扫描确认(非仅 leader 退出)"})
        return True

    def _member_pids(self) -> list[int]:
        """组内存活成员(zombie 不算:已被 kill 但父进程未 reap 的
        /proc 条目仍带原 pgrp,不过滤会把已终止任务树误判为存活)。"""
        out = []
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/stat") as fh:
                    text = fh.read()
                rp = text.rindex(")")
                fields = text[rp + 2:].split()
                if int(fields[2]) == self.pgid and fields[0] != "Z":
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
                "identity_mismatch": self.identity_mismatch,
                "survivors": self.survivors[:32]}


# ------------------------------------------------- 异步 I/O(B2/WP2)
class BoundedIOWriter:
    """控制路径与可能阻塞的 I/O 的小型隔离(§5.2;不建平台)。

    - submit(fn, critical):非阻塞投递(queue.put_nowait);队列满
      → 立即返回 False(critical 事件丢失计入 dropped_critical,
      由主循环触发 PROTECTION_UNAVAILABLE——关键证据持续不可写
      时不得继续计算)。
    - 单一守护写线程顺序执行提交的写动作:日志/stdout/应急写
      卡住只卡这一个线程,保护轮询(信号/升级/退出确认)不受影响。
    - drain(timeout):有界等待已投递事件全部执行(finalize 用;
      超时如实报 pending,不无限 join,不假装已持久化)。
    - 状态分层:pending(已排队)/executed(已尝试执行)/dropped
      (队列满丢弃)/dropped_critical——排队≠已递交≠已持久化。
    """

    def __init__(self, maxsize: int = 1024):
        import queue as _queue
        self._q: "queue.Queue" = _queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._stats = {"submitted": 0, "executed": 0, "dropped": 0,
                       "dropped_critical": 0, "io_stuck": False}
        self._thread = threading.Thread(
            target=self._loop, name="r17-io-writer", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            fn = self._q.get()
            try:
                fn()
            except BaseException:  # noqa: BLE001 —— 写线程永不死亡
                pass
            with self._lock:
                self._stats["executed"] += 1

    def submit(self, fn, *, critical: bool = False) -> bool:
        try:
            self._q.put_nowait(fn)
        except Exception:  # noqa: BLE001 —— queue.Full
            with self._lock:
                self._stats["dropped"] += 1
                if critical:
                    self._stats["dropped_critical"] += 1
            return False
        with self._lock:
            self._stats["submitted"] += 1
        return True

    def drain(self, timeout: float) -> int:
        """有界等待积压清空;返回剩余 pending 数(>0=写入未完成)。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._q.empty():
                    return 0
            time.sleep(0.02)
        with self._lock:
            pending = self._q.qsize()
            if pending:
                self._stats["io_stuck"] = True
            return pending

    def stats(self) -> dict[str, Any]:
        with self._lock:
            out = dict(self._stats)
        out["pending"] = self._q.qsize()
        return out


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
        # S1:采样线程→主循环的有界交接点(最近有效快照+线程锁)
        self._guest_lock = threading.Lock()
        self._guest_latest: dict | None = None
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
        # 递交面健康(模式 B;stdout 故障计数,不阻断任何保护)
        self.stdout_failures = 0
        self.log_failures = 0
        # S2:就绪屏障状态
        self.obs_ready_at_mono: float | None = None
        # B1:样本有效性/启动准入记录
        self.invalid_guest_samples = 0
        self.invalid_guest_reasons: list[str] = []
        self.admission: dict[str, Any] | None = None
        # B2:异步 I/O 执行单元(控制路径永不同步等待日志/告警写)
        self.iow = BoundedIOWriter()
        self._io_lost_critical_seen = 0
        # B4:leader 退出后的残留核验状态
        self._desc_check_done = False
        self._residual_handled = False
        self.residual_unconfirmed = False
        self._evidence_complete: bool | None = None
        # B5:启动前意图校验结果(_declare_expected 填充)
        self._startup_reject: str | None = None
        # S5:运行前登记必需产物角色(缺件保留为缺件,绝不从清单移除)
        self.expected: list[dict[str, Any]] = self._declare_expected()

    # ---------------- S5/B5:必需角色运行前登记 ----------------
    @staticmethod
    def _resolve_junit(argv: list[str]) -> tuple[str | None, str]:
        """从业务 argv 解析 JUnit 输出路径;返回 (path, form)。

        支持形态:元素级等号(--junitxml=P,含空格路径)、元素级分离
        (--junitxml P)。bash -c 串内只有等号形态可可靠解析;串内
        分离形态不可靠 → 返回 ambiguous_bash_c(调用方要求显式登记,
        而不是写万能 shell 解析器)。
        """
        for i, a in enumerate(argv):
            if not isinstance(a, str):
                continue
            if a == "--junitxml" and i + 1 < len(argv) and \
                    isinstance(argv[i + 1], str) and \
                    not argv[i + 1].startswith("-"):
                return argv[i + 1], "element_split"
            if a.startswith("--junitxml="):
                return a.split("=", 1)[1], "element_eq"
        joined = " ".join(a for a in argv if isinstance(a, str))
        m = re.search(r"--junitxml=(\S+)", joined)
        if m and m.group(1):
            return m.group(1), "embedded_eq"
        if re.search(r"--junitxml(?:\s|$)", joined):
            return None, "ambiguous_bash_c"
        return None, "absent"

    def _declare_expected(self) -> list[dict[str, Any]]:
        """按运行意图声明必要输出角色与预期路径(任何业务启动之前)。

        核心角色:双采样流/alerts/业务 stdout+stderr/summary/junit。
        B5/WP5 修复:task_kind=pytest 的 JUnit 是**类型必需角色**——
        由任务类型决定,不靠 --junitxml 字符串解析运气:元素级等号/
        分离两形态都识别;解析不出(bash -c 串内分离形态/缺失)时
        启动前拒绝(rc=2,零 spawn),除非 --expect-artifact
        junit_xml=PATH 显式登记;显式登记与 argv 解析冲突同样拒绝。
        """
        exp: list[dict[str, Any]] = []
        # replay(显式测试输入源,生产入口不暴露)下双采样流由回放
        # 输入文件替代,不登记为人造缺件;生产路径登记不变。
        replay = str(getattr(self.args, "samples_source", "") or "")\
            .startswith("file:")
        if not replay:
            exp += [
                {"role": "telemetry_guest", "path": self.guest_path},
                {"role": "telemetry_win", "path": self.win_path_guest},
            ]
        exp += [
            {"role": "alerts", "path": self.alerts_path},
            {"role": "business_stdout", "path": self.biz_stdout},
            {"role": "business_stderr", "path": self.biz_stderr},
            {"role": "summary", "path": self.run_dir / "summary.json"},
        ]
        argv = list(self.args.argv)
        junit_path, junit_form = self._resolve_junit(argv)
        declared = {}
        for spec in (getattr(self.args, "expect_artifact", None) or []):
            try:
                role, p = spec.split("=", 1)
            except ValueError:
                continue
            if role and p:
                declared[role] = p
                # junit_xml 显式登记映射到规范必需角色(不再是
                # declared: 前缀的任意项;§8.1)
                exp.append({"role": "junit_xml" if role == "junit_xml"
                            else f"declared:{role}",
                            "path": Path(p).resolve()})
        if self.args.task_kind == "pytest":
            dj = declared.get("junit_xml")
            if junit_path is None and junit_form == "ambiguous_bash_c":
                self._startup_reject = (
                    "junit_ambiguous_bash_c: pytest 的 JUnit 输出无法"
                    "从 bash -c 串内分离参数形态可靠解析;请改用"
                    "--junitxml=<path> 等号形态或 --expect-artifact "
                    "junit_xml=<path> 显式登记(启动前拒绝;零 spawn)")
            elif junit_path is None and dj is None:
                self._startup_reject = (
                    "junit_missing: task_kind=pytest 的必需角色"
                    " junit_xml 无法从业务 argv 确定(等号/分离形态"
                    "均未命中);用 --junitxml <path> 或"
                    " --expect-artifact junit_xml=<path> 显式登记"
                    "(启动前拒绝;零 spawn)")
            elif junit_path is not None and dj is not None and \
                    Path(junit_path).resolve() != Path(dj).resolve():
                self._startup_reject = (
                    f"junit_conflict: argv 解析({junit_path})与显式"
                    f"登记({dj})不一致(启动前拒绝;零 spawn)")
            elif junit_path is not None:
                exp.append({"role": "junit_xml",
                            "path": Path(junit_path).resolve()})
        elif junit_path is not None:
            # 非 pytest 任务传了 --junitxml:仍登记(有输出即证据)
            exp.append({"role": "junit_xml",
                        "path": Path(junit_path).resolve()})
        if self.args.task_kind == "c3diag":
            # C3 固定坐标诊断的业务交付(--out <path>)
            for i, a in enumerate(argv):
                p = None
                if a == "--out" and i + 1 < len(argv):
                    p = argv[i + 1]
                elif isinstance(a, str) and a.startswith("--out="):
                    p = a.split("=", 1)[1]
                if p:
                    exp.append({"role": "c3_diagnosis",
                                "path": Path(p).resolve()})
                    break
        return exp

    # ---------------- 基础 IO(B2:全部经有界队列,控制路径不等待) --
    def _log_sync(self, obj: dict[str, Any]) -> None:
        """alerts.jsonl 追加写(在 I/O 执行线程内运行)。"""
        try:
            with self.alerts_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(obj, ensure_ascii=False,
                                    separators=(",", ":")) + "\n")
        except OSError:
            self.log_failures += 1

    def log(self, obj: dict[str, Any]) -> None:
        obj = dict(obj)
        obj.setdefault("utc", utc_now_iso())
        obj.setdefault("mono", round(time.monotonic() - self.t0, 1))
        obj.setdefault("run_id", self.run_id)
        self.iow.submit(lambda: self._log_sync(obj),
                        critical=obj.get("severity") == "CRITICAL")

    def safe_log(self, obj: dict[str, Any]) -> None:
        """尽力而为日志:投递失败计数并继续(不阻断保护路径)。"""
        self.log(obj)

    def _stdout_sync(self, tag: str, line: str) -> None:
        try:
            print(f"{tag} {line}", flush=True)
        except (BrokenPipeError, OSError, ValueError):
            # ValueError: 已关闭流;BrokenPipe:消费者离开;均只计数
            self.stdout_failures += 1

    def stdout_line(self, tag: str, obj: dict[str, Any]) -> None:
        """递交面:宿主后台任务输出(TaskOutput 周期接收=模式 B)。

        B2 修复:print 经 I/O 执行线程——stdout 管道写满且消费者
        不再读时,阻塞的只是写线程(递交 pending 如实记录),判定
        与保护轮询不等待它(§5.3)。
        """
        obj = dict(obj)
        obj.setdefault("utc", utc_now_iso())
        obj.setdefault("run_id", self.run_id)
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        self.iow.submit(lambda: self._stdout_sync(tag, line),
                        critical=tag == "R17ALERT")

    # ---------------- 递交 ----------------
    def deliver(self, action: str, incident: Incident,
                metrics: dict[str, Any]) -> None:
        """尽力而为递交:任何 IO 失败不得回滚/阻断已调度的保护。

        delivered_count 在**投递成功入队**时递增(=投递尝试);排队
        ≠已持久化≠工具呈现——落盘/递交由 I/O 线程执行,状态经
        iow.stats() 与 alerts 文件分别可查(§5.2)。
        """
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
            # S4:升级判定必须在 severity 覆盖之前(should_deliver 读
            # 旧 severity;先覆盖会让 escalate 永不返回,升级告警被
            # 冷却吞掉——WARNING 首发后 60s 内转 CRITICAL 必须立即
            # 产生升级告警)。
            action = inc.should_deliver(sev, mono,
                                        self.policy["cooldown_reminder_s"])
            if escalated:
                inc.severity = "CRITICAL"
            if sev == "WORKER":
                # 业务失败事件:单独递交,不改名资源事件
                self.stdout_line("R17ALERT", {
                    "action": "worker_event", "severity": "WORKER",
                    "kind": kind, "detail": tg["detail"], "metrics": m,
                    "run_dir": str(self.run_dir)})
                self.safe_log({"event": "worker_event", "kind": kind,
                               "detail": tg["detail"], "metrics": m})
                continue
            # S4:粘性停止意图与控制路径先行(不等待任何通知 IO/回执);
            # 升级(escalated)与独立新 CRITICAL 均立即调度。
            needs_stop = sev in ("CRITICAL", "PROTECTION_UNAVAILABLE")
            if needs_stop and not inc.stopped_requested:
                inc.stopped_requested = True
                reason = f"{kind}: {tg['detail']}"
                self.stop_requested_reasons.append(reason)
                if self.protector and self.biz_proc and \
                        self.biz_proc.poll() is None:
                    self.protector.request_stop(reason)
                else:
                    self.safe_log({"event": "stop_requested_no_live_task",
                                   "reason": reason,
                                   "note": "业务已结束/未启动:阻止新增步骤"})
            # 递交尽力而为(在停止调度之后;IO 失败不回滚保护)
            if action:
                self.deliver(action, inc, m)

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

    def _wslpath_win2guest(self, win_path: str) -> str | None:
        """Windows 路径 → WSL 路径(wslpath -u)。"""
        try:
            out = subprocess.run(["wslpath", "-u", win_path],
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
        # 应急目录:宿主 LOCALAPPDATA(独立故障域;一次 interop 查询+缓存;
        # §5.3:只在启动时解析一次,emergency_write 只写该目录)。
        # 两种形态:win 形式传 ps1 参数;guest 形式供本进程写。
        self.emergency_win_dir_win: str | None = None
        try:
            r = subprocess.run([ps, "-NoProfile", "-Command",
                                "$env:LOCALAPPDATA"],
                               capture_output=True, timeout=30, check=True)
            la = r.stdout.decode("utf-8", "replace").strip().rstrip("\\")
            la_guest = self._wslpath_win2guest(la)
            self.emergency_win_dir_win = la + "\\r17_supervision_emergency"
            self.emergency_win_dir = (
                str(Path(la_guest) / "r17_supervision_emergency")
                if la_guest else None)
        except (OSError, subprocess.SubprocessError):
            self.emergency_win_dir = None
        max_s = int(self.policy["default_max_seconds"]
                    + self.policy["finalize_window_s"] + 60)
        argv = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", ps1_win, "-RunId", self.run_id,
                "-OutFile", out_win, "-MaxSeconds", str(max_s),
                "-Volumes", self.args.win_volumes, "-IntervalSeconds", "5"]
        if self.emergency_win_dir_win:
            argv += ["-EmergencyDir", self.emergency_win_dir_win]
        self.win_proc = subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        self.win_reader = WinSampleReader(self.win_path_guest,
                                          run_id=self.run_id)
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
        # S3:登记 leader 实例身份(starttime;PID 复用防护)+统一
        # run-relative 单调钟(与主循环 poll(mono) 同基准)
        leader_start = None
        try:
            with open(f"/proc/{self.biz_proc.pid}/stat") as fh:
                text = fh.read()
            leader_start = int(
                text[text.rindex(")") + 2:].split()[19])
        except (OSError, ValueError, IndexError):
            leader_start = None
        self.protector = Protector(
            pgid, self.policy["coop_exit_window_s"], self.log,
            leader_pid=self.biz_proc.pid,
            leader_start_ticks=leader_start,
            mono_fn=lambda: time.monotonic() - self.t0)
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
            # S2 修复:预算耗尽=核心证据无法继续保存——粘性触发保护
            # (保留前缀+真实缺测区间),不得停采样后以 stale=None +
            # 主循环心跳宣称保护有效。
            if not self.telemetry_capped:
                self.telemetry_capped = True
                self.log({"event": "telemetry_budget_exceeded",
                          "bytes": b, "budget": budget,
                          "note": "核心证据无法继续保存:保护性中止"
                          "(采样停写保留前缀;缺测区间如实记录)"})
                self.handle_triggers([{
                    "kind": "telemetry_budget",
                    "severity": "PROTECTION_UNAVAILABLE",
                    "detail": f"遥测达预算 {b}B ≥ {budget}B;核心证据"
                    "无法继续保存,保护性中止(保留前缀)",
                    "metrics": {"bytes": b, "budget": budget}}])
                if self.guest_sampler:
                    self.guest_sampler.stop()
                    self.guest_sampler = None

    # ---------------- 应急兜底 ----------------
    def _emergency_sync(self, obj: dict[str, Any]) -> None:
        # 在 I/O 执行线程内运行;只写启动时解析的当前用户目录
        try:
            import sys as _sys
            print("R17EMERG " + json.dumps(obj, ensure_ascii=False,
                                           separators=(",", ":")),
                  file=_sys.stderr, flush=True)
        except Exception:  # noqa: BLE001
            pass
        if not self.emergency_win_dir:
            return
        d = Path(self.emergency_win_dir)
        try:
            d.mkdir(parents=True, exist_ok=True)
            with (d / f"emergency_{self.run_id}.jsonl").open(
                    "a", encoding="utf-8") as fh:
                fh.write(json.dumps(
                    obj, ensure_ascii=False,
                    separators=(",", ":")) + "\n")
        except OSError:
            return

    def emergency_write(self, obj: dict[str, Any]) -> None:
        """C: 独立故障域兜底(§7-15;§5.3 修复;B2:经 I/O 线程)。

        只写启动时实际解析并验证的当前用户应急目录
        (start_win_sampler 记录的 emergency_win_dir,对应 ps1 侧
        $env:LOCALAPPDATA);不遍历 C:\\Users 尝试逐用户写文件,
        也不以恒真条件放开目录检查。目录未知/不可写:事件只能留在
        内存中的告警流与 stderr(如实缺失,不伪造成功)。
        """
        self.iow.submit(lambda: self._emergency_sync(obj), critical=True)

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
                "win_invalid_samples": self.win_reader.invalid_samples
                if self.win_reader else None,
                "guest_invalid_samples": self.invalid_guest_samples,
                "coverage_gaps": self.guest_sampler.coverage_gaps
                if self.guest_sampler else None,
                "obs_ready_at_mono": self.obs_ready_at_mono,
                "telemetry_capped": self.telemetry_capped,
                "stdout_failures": self.stdout_failures,
                "log_failures": self.log_failures,
            },
            "admission": self.admission,
            "io": self.iow.stats() if self.iow else None,
            "residual_unconfirmed": self.residual_unconfirmed,
            "startup_rejected": self._startup_reject,
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
        """run_record.json(schema v2;build 必需集合来源;原子写)。

        S5 修复(WP4):必需集合来自**运行前登记**(_declare_expected),
        不随现存文件缩小——缺件保留为 status="missing";真实空文件
        是 present+bytes=0;finalized=记录已封口,evidence_complete
        另行判定,缺件交付=不完整(verify 据此 FAIL)。
        """
        required = []
        root = self.run_dir.parent.parent  # run_supervision 根
        missing: list[str] = []
        # §7.2:业务流最终哈希必须在写入者退出后计算;停止完成未证实
        # (残留组仍可能写 stdout/stderr)时如实标 live_writers,不能
        # hash 一次便宜布原始流固定。
        writers_live = self.residual_unconfirmed or (
            self.protector is not None and
            self.protector.requested_at is not None and
            self.protector.terminal_at is None)
        for item in self.expected:
            p = Path(item["path"])
            entry = {"role": item["role"],
                     "path": str(p.relative_to(root)).replace("\\", "/")
                     if p.is_relative_to(root) else str(p)}
            if item["role"] in ("business_stdout", "business_stderr") \
                    and writers_live:
                entry["live_writers"] = True
            if not p.is_file():
                entry["status"] = "missing"
                missing.append(item["role"])
            else:
                h = hashlib.sha256()
                n = 0
                try:
                    with p.open("rb") as fh:
                        while True:
                            chunk = fh.read(1 << 20)
                            if not chunk:
                                break
                            h.update(chunk)
                            n += len(chunk)
                    entry.update({"status": "present",
                                  "sha256": h.hexdigest(), "bytes": n})
                except OSError:
                    entry["status"] = "unreadable"
                    missing.append(item["role"])
            required.append(entry)
        rec = {
            "schema": "r17-run-record-v2",
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
            "evidence_complete": not missing,
            "missing_roles": missing,
            "io": self.iow.stats() if self.iow else None,
            "finalized": True,
        }
        self._evidence_complete = not missing
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
        # B5:启动前意图校验(pytest 必需角色不可确定/冲突)→零 spawn
        # 拒绝本请求(记录与封口照常;业务文件保持不存在)。
        if self._startup_reject:
            self.log({"event": "startup_rejected",
                      "reason": self._startup_reject})
            self.stdout_line("R17LOG", {"event": "startup_rejected",
                                        "reason": self._startup_reject})
            self.finalize()
            return 2
        # 观测自动启动(WP1:不依赖手工开采样器)
        win_started = self.start_win_sampler()
        self.guest_sampler = GuestSampler(
            emit=lambda rec: self._emit_guest(rec), interval=5.0,
            detail_interval=30.0)
        # 样本回放模式(测试输入源):不启动线程,由文件喂样本
        replay = self.args.samples_source.startswith("file:") if \
            self.args.samples_source else False
        replay_records = self._load_replay() if replay else []
        if not replay:
            self.guest_sampler.start()
        self.mark_stage("observation_starting")
        # ---- S2/B1:就绪屏障(有效首样本;非固定 sleep;有界等待) ----
        ready, not_ready_detail = self._wait_observation_ready(
            replay=replay, win_started=win_started,
            deadline_s=float(getattr(self.args, "obs_ready_deadline",
                                     30.0) or 30.0))
        if not ready:
            self.log({"event": "observation_not_ready",
                      "detail": not_ready_detail,
                      "note": "核心观测不可用:拒绝启动业务(有界就绪"
                      "等待超时/采样器失败/无有效首样本);只关闭本请求"
                      "采样器"})
            self.stdout_line("R17LOG", {"event": "observation_not_ready",
                                        "detail": not_ready_detail})
            self._shutdown_samplers_only()
            self.finalize()
            self.exit_code = 93  # 观测未就绪(拒绝本请求)
            return self.exit_code
        self.obs_ready_at_mono = time.monotonic() - self.t0
        self.mark_stage("observation_ready",
                        f"ready_after={self.obs_ready_at_mono:.1f}s")
        # ---- B1:启动资源准入(有效≠可开始重任务;§4.2) --------------
        first_win = first_guest = None
        if replay:
            for rec in replay_records:
                if first_win is None and rec.get("win"):
                    first_win = rec["win"]
                if first_guest is None and rec.get("guest"):
                    first_guest = rec["guest"]
                if first_win is not None and first_guest is not None:
                    break
        else:
            first_win = self.win_reader.last_valid \
                if self.win_reader else None
            first_guest = self._guest_snapshot()
        admitted, admission_detail = self.admission_check(
            first_win, first_guest)
        if not admitted:
            self.log({"event": "startup_admission_denied",
                      "detail": admission_detail,
                      "note": "首样本有效但资源不足工程准入线:拒绝"
                      "启动重任务(本请求按既定准入结束,不自动重开)"})
            self.stdout_line("R17LOG", {
                "event": "startup_admission_denied",
                "detail": admission_detail})
            self._shutdown_samplers_only()
            self.finalize()
            self.exit_code = 94  # 资源准入不足(拒绝本请求)
            return self.exit_code
        self.mark_stage("startup_admitted", admission_detail)
        # 信号:supervisor 自身被停→受控收尾。B4 修复:注册提前到
        # spawn 之前——任何时点(含 spawn 与注册之间的微窗口)到达的
        # 停止请求都有受控行为;spawn 前已收到=拒绝启动业务。
        self._external_stop_sig: int | None = None

        def _sig(sig, frame):
            self._external_stop_sig = sig
            self.log({"event": "supervisor_signal", "sig": sig})
            if self.protector and self.biz_proc and \
                    self.biz_proc.poll() is None:
                self.protector.request_stop(f"supervisor_signal_{sig}")
        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)
        if self._external_stop_sig is not None:
            self.log({"event": "supervisor_stop_before_spawn",
                      "sig": self._external_stop_sig,
                      "note": "停止请求先于业务启动:拒绝启动并收尾"})
            self._shutdown_samplers_only()
            self.finalize()
            self.exit_code = 4
            return self.exit_code
        self.mark_stage("business_spawn")
        self.spawn_business()
        max_s = self.policy["default_max_seconds"]
        last_budget_check = 0.0
        last_storage_check = 0.0
        last_poll_mono = time.monotonic()
        replay_idx = 0
        while True:
            mono = time.monotonic() - self.t0
            # ---- 样本获取 ----
            win_latest = self._pump_win_lines(mono)
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
                # S1:真实采样线程→主循环交接(最近有效快照;与落盘流
                # 同一来源,策略/峰值/摘要消费同一数据)
                guest_rec = self._guest_snapshot()
            task_agg = self._task_aggregate(guest_rec)
            # ---- S2:观测新鲜度(每必要来源独立判活) ----
            # 预算耗尽(采样已停)时不再判失联(不误报),但 capped 本身
            # 已触发保护性中止;缺测区间在 coverage 里如实记录。
            stale_map: dict[str, float | None] = {}
            if not replay and not self.telemetry_capped:
                # 就绪屏障通过后立即启用判定;宽限=就绪后 5s(竞态
                # clamp,禁取模)
                grace = 5.0 if (
                    self.obs_ready_at_mono is not None and
                    mono >= self.obs_ready_at_mono) else None
                for src, last in (("win", self.last_win_line_mono),
                                  ("guest", self.last_guest_mono)):
                    if last is None:
                        stale_map[src] = None  # 就绪前/从未:不判
                        continue
                    st = max(0.0, mono - last)
                    if grace is not None and mono < \
                            self.obs_ready_at_mono + grace:
                        st = 0.0
                    stale_map[src] = st
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
            # ---- 保护轮询(B2:控制动作零 I/O;日志在动作后递交) ----
            if self.protector:
                self.protector.poll(mono)
                if self.protector.pending_logs:
                    self.protector.flush_logs()
            # ---- 判定 ----
            storage_used = None
            if mono - last_storage_check >= 60:
                last_storage_check = mono
                storage_used = self._storage_used_gib()
            triggers = self.engine.evaluate(
                mono, win_latest, guest_rec, task_agg,
                storage_used, stale_map or None)
            self.recover_warnings(mono, win_latest, guest_rec)
            if triggers:
                self.handle_triggers(triggers)
            # ---- 峰值记录(不同阶段/进程不混加) ----
            self._update_peaks(win_latest, guest_rec, task_agg)
            # ---- 预算(30s 一次) ----
            if mono - last_budget_check >= 30:
                last_budget_check = mono
                self.budget_check()
            # ---- B2:关键事件投递丢失=证据链断,粘性保护(§5.2) ----
            io_stats = self.iow.stats()
            if io_stats["dropped_critical"] > self._io_lost_critical_seen:
                self._io_lost_critical_seen = io_stats["dropped_critical"]
                self.handle_triggers([{
                    "kind": "io_evidence_lost", "severity":
                    "PROTECTION_UNAVAILABLE",
                    "detail": f"关键事件队列溢出丢弃 "
                    f"{io_stats['dropped_critical']} 条(证据无法保存;"
                    "保护性中止;不静默丢事件后继续)",
                    "metrics": dict(io_stats)}])
            # ---- B4:退出条件(正常 leader 退出≠任务树结束;§7.1) ----
            biz_done = self.biz_proc is not None and \
                self.biz_proc.poll() is not None
            prot_pending = self.protector is not None and \
                self.protector.requested_at is not None and \
                self.protector.terminal_at is None
            # 保护停止长期未证实(业务拒死/KILL 无效/身份不符):
            # 无论 leader 是否退出,诊断控制流都必须有界退出
            # (§7.2;不无限 continue 等有人手动关 WSL)。
            if prot_pending and self.biz_proc is not None:
                since_req = mono - (self.protector.requested_at or 0)
                if since_req > self.policy["coop_exit_window_s"] + 10 + 25:
                    self.residual_unconfirmed = \
                        bool(self.protector._member_pids())
                    if self.biz_proc.poll() is not None:
                        self.biz_rc = self.biz_proc.returncode
                    break
            if biz_done and not prot_pending:
                if self.protector is None:
                    break
                if not self._desc_check_done:
                    self._desc_check_done = True
                    self._desc_check_at = mono
                members = self.protector._member_pids()
                if not members:
                    break  # 登记组确认全部结束:正常收尾
                # leader 退出但登记组仍有活成员:residual 异常+有界收尾
                if not self._residual_handled:
                    self._residual_handled = True
                    self._desc_check_at = mono
                    self.safe_log({
                        "event": "residual_task_after_leader_exit",
                        "leader_rc": self.biz_rc,
                        "members": members[:32],
                        "note": "leader 退出≠任务树结束:受控清理登记组"
                        "(TERM→合作窗→KILL);rc=0 不代表整体成功"})
                    self.handle_triggers([{
                        "kind": "residual_task", "severity": "CRITICAL",
                        "detail": f"leader rc={self.biz_rc} 退出后登记组"
                        f"仍有 {len(members)} 个活成员(有限收尾)",
                        "metrics": {"members": len(members)}}])
                    # 实际清理:直接对登记组发停止(业务 leader 已退,
                    # 常规 handle_triggers 分支不覆盖此形态)
                    self.protector.request_stop(
                        "residual_task_after_leader_exit")
                prot_pending = self.protector.requested_at is not None \
                    and self.protector.terminal_at is None
            if biz_done and prot_pending and self.protector is not None:
                # 停止请求下业务已退:合作窗+确认窗后仍无终态=有界退出
                # (停止已请求、完成未证实:如实记录,拒绝下一重任务,
                # 不无限 continue 等有人手动关 WSL;§7.2)
                since_req = mono - (self.protector.requested_at or 0)
                hard_cap = self.policy["coop_exit_window_s"] + 10 + 25
                if self.protector.kill_sent_at is None and \
                        since_req > self.policy["coop_exit_window_s"] + 10:
                    break
                if self.protector.kill_sent_at is not None and \
                        mono - self.protector.kill_sent_at > 10 + 15:
                    self.residual_unconfirmed = \
                        bool(self.protector._member_pids())
                    break
                if since_req > hard_cap:
                    self.residual_unconfirmed = \
                        bool(self.protector._member_pids())
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
        return self.control_outcome()

    def control_outcome(self) -> int:
        """外层退出码与结果维度一致(§7.3;不重写业务 rc,但业务失败/
        保护中止/监护失败/残留未确认/证据不完整不得返回 0)。"""
        if self.exit_code:
            return self.exit_code  # 93 观测未就绪/94 准入不足/2 意图拒绝
        # 完成未证实(树仍在/身份不明)优先于"发生过保护"——残留
        # 风险是更强的"禁止下一重任务"信号(§7.2)
        if self.residual_unconfirmed:
            return 5
        if self.stop_requested_reasons and self.protector is not None \
                and self.protector.requested_at is not None:
            return 4  # 保护性中止(含 residual 受控清理且已证实)
        io = self.iow.stats() if self.iow else {}
        if io.get("dropped_critical"):
            return 6  # 关键证据事件丢失
        if self._evidence_complete is False:
            return 6  # 必需证据不完整
        if self.biz_rc not in (0, None):
            return self.biz_rc if self.biz_rc > 0 else 128 - self.biz_rc
        return 0

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
            # B1:无效样本落盘保留诊断,但不刷新有效快照与新鲜度
            ok, reason = validate_guest_sample(rec)
            if not ok:
                self.invalid_guest_samples += 1
                if len(self.invalid_guest_reasons) < 16:
                    self.invalid_guest_reasons.append(reason)
                return
            with self._guest_lock:
                self._guest_latest = rec
            self.last_guest_mono = time.monotonic() - self.t0

    def _guest_snapshot(self) -> dict | None:
        """最近有效 guest 快照(真实采样交接点;S1)。"""
        with self._guest_lock:
            return self._guest_latest

    def _pump_win_lines(self, mono: float) -> dict | None:
        """增量读 win 流并处理行内事件;返回最新有效样本(或 None)。

        B1 修复:无效 sample 行(坏数值/错误身份)不进入判定输入,
        不刷新失联计时;重复 sampler_start=来源重启,如实记录。
        """
        win_latest: dict | None = None
        if not self.win_reader:
            return None
        seen_start_pids: set[int] = set()
        for line in self.win_reader.read_new():
            ev = line.get("event")
            if ev == "sample":
                ok, _reason = validate_win_sample(
                    line, run_id=self.win_reader.run_id)
                if not ok:
                    continue  # 无效:不作为判定输入(reader 已计数)
                win_latest = line
                self.last_win_line_mono = mono
            elif ev == "sampler_start":
                pid = line.get("pid")
                if pid is not None:
                    if seen_start_pids and pid not in seen_start_pids:
                        # 同一流内新 sampler_start 且 pid 不同=来源重启
                        self.safe_log({
                            "event": "win_sampler_restarted",
                            "old_pid": max(seen_start_pids),
                            "new_pid": pid,
                            "note": "host 采样来源重启:有效性时间线"
                            "按新实例重新建立(§4.3)"})
                    seen_start_pids.add(pid)
                if self.win_pid_windows is not None and \
                        pid != self.win_pid_windows:
                    self.win_pid_windows = pid
                    self.safe_log({"event": "win_sampler_ready",
                                   "windows_pid": pid})
                elif self.win_pid_windows is None:
                    self.win_pid_windows = pid
                    self.log({"event": "win_sampler_ready",
                              "windows_pid": pid})
            elif ev in ("vol_missing", "evidence_write_failed",
                        "guest_vm_gone"):
                # host 侧事件(Guest 不可见):升级递交
                self.handle_triggers([{
                    "kind": f"win_{ev}",
                    "severity": "CRITICAL",
                    "detail": json.dumps(line, ensure_ascii=False)[:300],
                    "metrics": line}])
        return win_latest

    def _wait_observation_ready(self, *, replay: bool, win_started: bool,
                                deadline_s: float) -> tuple[bool, str]:
        """S2/B1 就绪屏障:必要 host/guest **有效**首样本齐备才放行。

        B1 修复:就绪不再消费 saw_any(任意可解析 JSON)——
        sampler_start/空 sample/坏数值行不能证明观测能力;host 需要
        validate_win_sample 通过(含 run 身份),guest 快照需要
        validate_guest_sample 通过;首样本还须新鲜(距本次就绪窗口
        内的产生时刻不超过两个核心采样周期)。replay(文件回放,
        显式测试输入源)直接就绪;win 采样器启动失败→不就绪;到期
        =拒绝本请求(零业务 spawn)。
        """
        if replay:
            return True, "replay"
        max_age = self.policy["startup_admission"][
            "first_sample_max_age_s"]
        deadline = time.monotonic() + deadline_s
        detail = ["?"]
        while time.monotonic() < deadline:
            if not win_started:
                return False, "win_sampler_start_failed"
            self._pump_win_lines(time.monotonic() - self.t0)
            reader = self.win_reader
            win_ok = bool(reader is not None and reader.saw_valid)
            if win_ok and reader.last_valid_mono is not None and \
                    time.monotonic() - reader.last_valid_mono > max_age:
                win_ok = False  # 唯一有效样本已陈旧:不充当就绪证据
            guest_snap = self._guest_snapshot()
            guest_ok, _ = validate_guest_sample(guest_snap)
            if guest_ok and self.last_guest_mono is not None and \
                    time.monotonic() - self.t0 - self.last_guest_mono \
                    > max_age:
                guest_ok = False
            if win_ok and guest_ok:
                return True, "both_sources_first_valid_sample"
            missing = []
            if not reader or not reader.saw_any:
                missing.append("win_no_lines")
            elif not win_ok:
                missing.append(
                    "win_no_valid_sample" if not reader.saw_valid
                    else "win_stale")
            if guest_snap is None:
                missing.append("guest_no_sample")
            elif not guest_ok:
                missing.append("guest_invalid_or_stale")
            detail = missing
            time.sleep(0.2)
        return False, "ready_deadline_exceeded:" + "+".join(detail)

    # ---------------- B1/WP1:启动资源准入 ----------------
    def admission_check(self, win: dict | None,
                        guest: dict | None) -> tuple[bool, str]:
        """有效≠可开始重任务:就绪通过后再做工程资源准入(§4.2)。

        默认新重任务要求:win 可用内存≥8GiB、commit<90%、guest
        MemAvailable≥4GiB、关键输出卷 present 且 free≥20GiB、
        未命中 300GiB 存储上限。缺某侧有效数据时按"不可判定"拒绝
        (不放宽准入);零可用内存=有效但危险→同样拒绝。这是工程
        准入条件,不是课程 gate;不为了开始任务临时放宽。
        """
        sa = self.policy["startup_admission"]
        reasons: list[str] = []
        ok, _ = validate_win_sample(win, run_id=getattr(
            self.win_reader, "run_id", None) if self.win_reader else None)
        if not ok:
            reasons.append("win_sample_invalid")
        else:
            perf = win["perf"]
            if perf["phys_avail_gb"] < sa["win_free_min_gib"]:
                reasons.append(
                    f"win_free {perf['phys_avail_gb']:.1f}GiB"
                    f"<{sa['win_free_min_gib']}GiB")
            pct = 100.0 * perf["commit_total_gb"] / \
                perf["commit_limit_gb"]
            if pct >= sa["win_commit_max_pct"]:
                reasons.append(
                    f"win_commit {pct:.1f}%>={sa['win_commit_max_pct']}%")
            vols = win.get("vols") or []
            present = [v for v in vols
                       if isinstance(v, dict) and v.get("present")]
            if present and min(v.get("free_gb", 0) for v in present) < \
                    sa["keyvol_min_free_gib"]:
                low = min((v.get("free_gb", 0) for v in present),
                          default=None)
                reasons.append(
                    f"keyvol_free {low}GiB<{sa['keyvol_min_free_gib']}GiB")
        gok, _ = validate_guest_sample(guest)
        if not gok:
            reasons.append("guest_sample_invalid")
        else:
            avail = guest["meminfo"]["MemAvailable"] / 1024 / 1024
            if avail < sa["guest_avail_min_gib"]:
                reasons.append(
                    f"guest_avail {avail:.1f}GiB"
                    f"<{sa['guest_avail_min_gib']}GiB")
        try:
            used = self._storage_used_gib()
        except Exception:  # noqa: BLE001 —— df 失败按不可判拒绝
            used = None
        if used is not None and used >= self.policy["storage"][
                "ceiling_gib"]:
            reasons.append(
                f"storage {used:.1f}GiB>=ceiling"
                f"{self.policy['storage']['ceiling_gib']}GiB")
        self.admission = {"ok": not reasons, "reasons": reasons,
                          "checked_utc": utc_now_iso()}
        return not reasons, ";".join(reasons) or "ok"

    def _shutdown_samplers_only(self) -> None:
        """就绪失败时的自我收尾:只关本请求的采样器,无业务可停。"""
        if self.guest_sampler is not None:
            self.guest_sampler.stop()
        self.stop_win_sampler()
        self.log({"event": "samplers_shutdown_after_not_ready"})

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
        # run_record 的哈希计算——否则清单记录与文件矛盾(build 拒绝)。
        # B2:alerts 经异步 I/O 线程落盘 → 写 supervisor_end 后**有界
        # drain**;写线程卡住时如实记 pending(不无限等,不假持久化)。
        if self.protector and self.protector.pending_logs:
            self.protector.flush_logs()
        self.log({"event": "supervisor_end",
                  "incidents": len(self.incidents),
                  "business_rc": self.biz_rc})
        self.iow.drain(15.0)
        summary = self.write_summary()
        self.iow.drain(5.0)
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
    ap.add_argument("--expect-artifact", action="append", default=[],
                    metavar="ROLE=PATH",
                    help="运行前登记的必需产物角色(S5;可重复;"
                         "缺件保留为 missing,不从清单移除)")
    ap.add_argument("--obs-ready-deadline", type=float, default=30.0,
                    help="S2 就绪屏障有界等待上限(秒);超时拒绝本请求")
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
            try:  # crash 路径的递交也尽力而为(stdout 可能已坏)
                print(f"R17ALERT {crash_alert}", flush=True)
            except (BrokenPipeError, OSError, ValueError):
                pass
            try:
                sup.finalize()
            except Exception:
                pass
        return 3


if __name__ == "__main__":
    sys.exit(main())
