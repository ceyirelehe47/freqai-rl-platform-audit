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

外层退出码(control_outcome;run() 返回值):
  0 成功 / 2 意图拒绝 / 3 crash / 4 外部停止(保护性中止) /
  5 残留未证实 / 6 证据丢失或发布失败 /
  7 控制能力失效(WP1 fc-integrity:截止边界前提/掩码取得/还原
    无法证明——run 非成功,停止归属无法认证;summary/run_record
    的 control_failures 为同一事实) /
  93 观测未就绪 / 94 准入不足
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
    # WP3(result-seal):必需依赖集合从本机部署映射固定(F=活跃项目/
    # WSL/swap/发布路径所在卷;C=登记的应急备用,失效可如实降级不
    # 阻断)——不以样本里恰好出现哪些卷决定哪些资源"必需"。
    "startup_admission": {
        "win_free_min_gib": 8.0, "win_commit_max_pct": 90.0,
        "guest_avail_min_gib": 4.0, "keyvol_min_free_gib": 20.0,
        "first_sample_max_age_s": 10.0,
        "keyvol_required": ("F:",),   # 必需:缺记录/present=false/
        #  identity 不符/free unknown/writable false 均拒绝
        "keyvol_optional": ("C:",),   # 登记的应急备用:缺失降级记录
        #  跨 OS UTC 墙钟比较容差(旧日志重放防护;样本 utc 早于
        #  supervisor 启动-容差 → 不刷新有效状态)
        "source_utc_tolerance_s": 300.0},
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


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


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


def _parse_utc_iso(value: Any):
    """ISO UTC 解析(容错 'Z' 后缀);失败/非字符串返回 None。

    跨 OS UTC 墙钟比较只用于"旧日志重放"防护(样本生成时间远早于
    本 run 启动),配 startup_admission.source_utc_tolerance_s 容差;
    不建立时间同步服务(§6.3)。
    """
    if not isinstance(value, str) or not value:
        return None
    import datetime as _dtm
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = _dtm.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dtm.timezone.utc)
    return dt


def validate_win_sample(line: dict | None, *, run_id: str | None = None,
                        ) -> tuple[bool, str]:
    """host 资源样本有效性:身份+结构+数值范围(§4.1/§6.3)。

    解析成功/来源已启动/有效资源样本三层分开;就绪只认最后一层。
    零可用内存是**有效但危险**的数据(不误记缺测后放行,交给策略)。
    WP3:live 保护输入必须绑定本次 run 与源序号(run_id 匹配+utc
    生成时刻+seq 非负整数)——缺失这些字段的旧格式只能由历史只读
    reader 解释,不得作为当前 live 准入的兼容后门(§6.3)。
    返回 (ok, reason);reason 词表供就绪拒绝与摘要披露。
    """
    if not isinstance(line, dict):
        return False, "not_object"
    if line.get("event") != "sample":
        return False, f"not_sample_event:{line.get('event')}"
    if run_id is not None:
        rid = line.get("run_id")
        if rid is None:
            # RSA-02:live 消费绑定 run 身份时,缺失 run_id 的旧格式
            # 拒绝——历史解释只在只读 reader(run_id=None;§6.3),
            # 不得作为 live 准入/判定的兼容后门
            return False, "run_id_missing"
        if rid != run_id:
            return False, "run_id_mismatch"
    utc = line.get("utc")
    if not isinstance(utc, str) or not utc.strip():
        return False, "utc_missing"
    seq = line.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        return False, "seq_invalid"
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


def validate_guest_sample(rec: dict | None, *, run_id: str | None = None,
                          ) -> tuple[bool, str]:
    """guest 资源样本有效性(§4.1):MemTotal/MemAvailable 有限、
    单位一致(kB)、0≤可用≤总量;utc 身份字段在场。

    RSA-02:live 消费(调用方传 run_id)时与 win 侧同款身份闭合——
    run_id 必须匹配且 seq 为非负整数(GuestSampler 已生产该字段);
    缺省 run_id=None 保持历史只读宽容,不给回放/诊断面加后门。
    """
    if not isinstance(rec, dict):
        return False, "not_object"
    if rec.get("event") != "guest_sample":
        return False, f"not_sample_event:{rec.get('event')}"
    if not rec.get("utc"):
        return False, "utc_missing"
    if run_id is not None:
        rid = rec.get("run_id")
        if rid is None:
            return False, "run_id_missing"
        if rid != run_id:
            return False, "run_id_mismatch"
        seq = rec.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
            return False, "seq_invalid"
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
    不能证明观测能力。
    WP3 修复(§6.3/§6.4):同源序号重复消费不增加有效样本数、不
    刷新 last_valid;序号回退(来源重启迹象)不沿用;样本生成时间
    (utc)早于本 run 启动-容差的旧日志重放不进入有效状态;接收
    时刻(last_valid_mono)与源生成时刻(last_valid_src_utc)分开
    记录——读取延迟/积压不延长生成时间。
    WP1 修复(RCF-01):本次有效批次(new_valid)的生命周期在任何
    可能失败的 stat/open/read 之前建立——读取失败的提前返回维持
    "本轮没有接受新样本"事实,上一批 new_valid 不得残留被 pump
    继续消费(旧行为:失败读取持续刷新失联计时,掩盖真实断流,
    15/30s 失联保护失效);读取失败保留有界诊断(操作类别/计数,
    不充当样本、不刷新任何有效性)。
    """

    def __init__(self, path: Path, run_id: str | None = None, *,
                 started_iso: str | None = None,
                 predates_tolerance_s: float | None = None):
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
        self.last_valid_src_utc: str | None = None
        self.duplicate_seq = 0
        self.seq_regressions = 0
        self.stale_replayed = 0
        # WP1(RCF-01):读取失败有界诊断(§4.2)——类别+计数;只描述
        # 事实,不充当样本、不刷新有效性/身份/失联计时
        self.read_failures = 0
        self.read_failure_consecutive = 0
        self.read_failure_last_op: str | None = None
        self.read_failure_last_utc: str | None = None
        self.read_failure_last_err: str | None = None
        # RSA-02:有效样本输出边界——read_new 每次调用重置,只含
        # 通过 validate+seq 去重/回退+predates 全部闸门的样本;
        # 判定输入(pump/策略/失联计时/summary)只消费本列表,
        # 不得对原始行重做较弱校验后当有效输入
        self.new_valid: list[dict] = []
        self._seen_seq: set[int] = set()
        self._max_seq: int | None = None
        dt = _parse_utc_iso(started_iso)
        self._predates_cutoff = (
            dt.timestamp() - float(predates_tolerance_s)
            if dt is not None and predates_tolerance_s is not None
            else None)
        self._buf = b""

    def _predates_run(self, utc_field: Any) -> bool:
        if self._predates_cutoff is None:
            return False
        dt = _parse_utc_iso(utc_field)
        if dt is None:
            return True  # 有效样本必带 utc;不可解析=不可信时间基线
        return dt.timestamp() < self._predates_cutoff

    def _note_read_failure(self, op: str, exc: OSError) -> None:
        """有界读取失败诊断(§4.2):操作类别+异常类名+计数。

        只记事实:不得刷新样本生成身份/有效序号/last_valid_mono/
        pump 有效时间/低资源持续窗口的有效样本数;read_new 被调用
        本身也不代表"来源仍健康"。错误字符串只保留异常类名(有界,
        不携带可能无界的路径/OS 文本)。
        """
        self.read_failures += 1
        self.read_failure_consecutive += 1
        self.read_failure_last_op = op
        self.read_failure_last_utc = utc_now_iso()
        self.read_failure_last_err = type(exc).__name__

    def read_new(self) -> list[dict]:
        # WP1(RCF-01):本次有效批次在所有可能失败的 stat/open/read
        # 之前重建——两个提前返回出口都交付"本轮零新样本",旧批次
        # 不残留(旧行为:read_new 返回后 pump 继续消费上批 new_valid,
        # 失败读取刷新有效性,失联判定被掩盖)。
        self.new_valid = []
        try:
            size = self.path.stat().st_size
        except OSError as exc:
            self._note_read_failure("stat", exc)
            # 来源身份可能改变(消失/重建):重置游标与半行缓冲,
            # 不得把旧半行拼接到另一个来源的内容(§4.3);重读的
            # 旧行由 seq 身份闸拒收,不获得新有效性
            self.offset = 0
            self._buf = b""
            return []
        if size < self.offset:
            self.offset = 0  # 文件被重建(不应发生):从头读,不丢告警
            self._buf = b""
        try:
            with self.path.open("rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
        except OSError as exc:
            self._note_read_failure("read", exc)
            self.offset = 0
            self._buf = b""
            return []
        # stat/open/read 成功(含 EOF 无新行与截断重置分支——两者
        # 与读取失败是不同事实,均不产生失败诊断)
        self.read_failure_consecutive = 0
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
            except ValueError:
                self.parse_errors += 1
                continue
            if not isinstance(obj, dict):
                # RSA-02:合法 JSON 但非对象(null/标量/数组)不是可
                # 消费的行——计解析错误、不入返回(下游 line.get 的
                # AttributeError 根因修复;诊断计数如实保留)
                self.parse_errors += 1
                continue
            out.append(obj)
        if out:
            self.last_lines = out[-8:]
            self.saw_any = True
        # 有效性分层(RSA-02:拒绝结果即输出边界):只有通过校验+
        # seq 去重/回退+predates 全部闸门的样本进入 new_valid 与
        # 有效首样本状态;重复序号/序号回退/早于 run 启动的旧日志
        # 不刷新(§6.4)。返回值 out 仍含全部可解析 dict 行(诊断/
        # 事件面),但消费面不得把其中被拒的 sample 行当有效输入。
        # (new_valid 的生命周期已上提到方法开头——WP1/RCF-01)
        for obj in out:
            ok, reason = validate_win_sample(obj, run_id=self.run_id)
            if ok:
                seq = obj.get("seq")
                if seq in self._seen_seq:
                    self.duplicate_seq += 1
                    continue
                if self._max_seq is not None and seq < self._max_seq:
                    self.seq_regressions += 1
                    continue
                if self._predates_run(obj.get("utc")):
                    self.stale_replayed += 1
                    continue
                self._seen_seq.add(seq)
                self._max_seq = seq
                self.saw_valid = True
                self.last_valid = obj
                self.last_valid_mono = time.monotonic()
                self.last_valid_src_utc = obj.get("utc")
                self.new_valid.append(obj)
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

    WP2(result-seal)修复:每个被接受的动作有**完整生命周期**
    queued → in_flight → ok / failed;回调抛错不是成功(异常上抛
    计 failed,有界保留失败摘要:动作角色+错误);drain 等待已接受
    动作**全部成功完成**,不以 queue.empty 判完成——queue.get 取走
    ≠写入完成(在途动作必须等待,超时返回未确认);seal() 后新提交
    被拒(rejected_after_seal 计数,不伪装成功处理)。
    不变量:accepted = queued + in_flight + ok + failed;
    rejected_after_seal 在 accepted 之外单独计(§5.1)。

    RSA-01 修复(独立审查 §3):队列交接必须原子。
    - queue.get() 完成→in_flight+=1 之间存在空窗(两个计数都不含
      该动作),qsize()+in_flight 相加构造不出完整性证明——drain
      改用单一计数口径 pending = accepted - ok - failed(与队列
      内部互斥/线程调度无关,任何已接受未完成动作必然计入);
    - submit 的 sealed 检查→put→accepted 计数三段可被 seal+drain
      插入(通过检查的动作既未计入待完成集合也未被拒绝,封口后
      仍写文件)——三步合入同一锁临界区:通过 sealed 检查的动作
      必然已计入 accepted(put_nowait 非阻塞,持锁安全;与 Queue
      内部锁无嵌套死锁:唯一锁序=writer 锁→queue 锁)。
    in_flight/queued 保留为诊断维度,不参与 drain 判定。
    """

    # close() 的哨兵对象(不算已接受动作,不进 accepted 计数)
    _CLOSE_SENTINEL = object()

    def __init__(self, maxsize: int = 1024):
        import queue as _queue
        self._q: "queue.Queue" = _queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._stats = {"submitted": 0, "accepted": 0, "ok": 0,
                       "failed": 0, "in_flight": 0, "executed": 0,
                       "dropped": 0, "dropped_critical": 0,
                       "rejected_after_seal": 0, "io_stuck": False,
                       "closed": False, "thread_joined": False}
        self._failures: list[dict[str, Any]] = []  # 有界失败摘要
        self._sealed = False
        # WP1(stop-cutoff/SFB-01):受控线程从第一条指令起屏蔽 TERM/INT
        # ——pthread_sigmask 只作用于调用线程,新线程继承创建线程掩码;
        # 先在创建线程(主线程)屏蔽、再 spawn、再恢复,写线程终身屏蔽。
        # 信号只应经主线程 handler 登记路径处理;未屏蔽受控线程会让
        # 信号绕过截止点临界区的挂起边界(S1/signal(7):进程级信号投递
        # 给任一未屏蔽线程,CPython C handler 在接收线程 tripped 后,
        # Python handler 在主线程下一字节码边界执行——与主线程掩码无关)。
        # 掩码能力不可用(非 POSIX 线程形态)时记录事实,截止点前提检查
        # (Supervisor._cutoff_thread_premise)会如实消费该状态。
        self.thread_shielded = False
        old_mask = None
        try:
            old_mask = signal.pthread_sigmask(
                signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
            self.thread_shielded = True
        except (ValueError, OSError, AttributeError):
            old_mask = None
        try:
            self._thread = threading.Thread(
                target=self._loop, name="r17-io-writer", daemon=True)
            self._thread.start()
        finally:
            if old_mask is not None:
                try:
                    signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
                except (ValueError, OSError):
                    pass

    def _loop(self) -> None:
        while True:
            act = self._q.get()
            if act is self._CLOSE_SENTINEL:
                return  # 正常有界退出路径(哨兵;不算写动作)
            ok = False
            err: str | None = None
            with self._lock:
                self._stats["in_flight"] += 1
            try:
                act["fn"]()
                ok = True
            except BaseException as exc:  # noqa: BLE001 —— 写线程
                err = f"{type(exc).__name__}:{exc}"[:200]  # 永不死亡
            with self._lock:
                self._stats["in_flight"] -= 1
                if ok:
                    self._stats["ok"] += 1
                else:
                    self._stats["failed"] += 1
                    if len(self._failures) < 32:
                        self._failures.append({
                            "role": act.get("role") or "",
                            "critical": bool(act.get("critical")),
                            "error": err})
                self._stats["executed"] = (self._stats["ok"] +
                                           self._stats["failed"])
            self._q.task_done()

    def submit(self, fn, *, critical: bool = False,
               role: str = "") -> bool:
        # RSA-01:sealed 检查/入队/accepted 计数同一临界区——
        # 通过 sealed 检查的动作立即计入待完成集合(pending),并发的
        # seal/drain 必然看到它(等待其完成),不存在"未计入也未拒绝"
        # 的迟交(put_nowait 非阻塞,持锁安全)。
        act = {"fn": fn, "critical": critical, "role": role}
        with self._lock:
            if self._sealed:
                self._stats["rejected_after_seal"] += 1
                return False
            try:
                self._q.put_nowait(act)
            except Exception:  # noqa: BLE001 —— queue.Full
                self._stats["dropped"] += 1
                if critical:
                    self._stats["dropped_critical"] += 1
                return False
            self._stats["submitted"] += 1
            self._stats["accepted"] += 1
        return True

    def _pending_locked(self) -> int:
        """已接受未完成数(单一计数口径;RSA-01)。

        accepted-ok-failed 与队列内部状态无关:get→in_flight 计数
        空窗、submit 计数窗内的动作都必然已被 accepted 覆盖。
        """
        return (self._stats["accepted"] - self._stats["ok"]
                - self._stats["failed"])

    def drain(self, timeout: float) -> int:
        """有界等待已接受动作全部**成功完成**(§5.2)。

        返回未完成数(在途/排队/失败之和;>0=封口未达成——失败
        同样不能宣称完成)。队列为空但仍有在途动作时必须等待,
        超时如实返回;不无限 join,不清空队列把未完成变完成。
        """
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if self._pending_locked() == 0:
                    return self._stats["failed"]
            if time.monotonic() >= deadline:
                with self._lock:
                    pending = self._pending_locked()
                    if pending:
                        self._stats["io_stuck"] = True
                    return pending + self._stats["failed"]
            time.sleep(0.02)

    def seal(self) -> None:
        """封口边界:此后新提交被拒(已接受动作照常执行/可 drain;
        §5.2/§5.3——成功发布后不得再有迟写)。"""
        with self._lock:
            self._sealed = True

    def close(self, timeout: float) -> bool:
        """WP2-B/SFB-01:写线程可验证结束路径。

        前置:已 seal(封口后才有资格结束;未 seal 时先补 seal,防直调
        遗漏)。哨兵经同一把锁入队(绕过 submit 的 sealed 拒绝——哨兵
        不是写动作,不计 accepted/pending);写线程处理完队列中既有
        动作后消费哨兵退出。join(timeout) 后用 is_alive() 判真实退出
        (join 超时返回值恒为 None,不是结束证据;S3)。返回 joined。
        超时未退出:保留线程事实(stats.thread_joined=False),调用方
        的完整性判定消费该状态,不得把"已放弃等待"当"写者已关闭"。
        """
        with self._lock:
            self._sealed = True
            if not self._stats["closed"]:
                # put(block=False) 而非 put_nowait:哨兵不是写动作,
                # 不应经过外部对 put_nowait 的动作观测挂钩(挂钩假设
                # 载荷是动作 dict);与 queue.Full 语义一致,持锁安全。
                # 队列满时哨兵入队失败:closed 保持 False(关闭请求
                # 未送达),线程不会退出——join 如实未确认(验收观察②:
                # fail-closed 且不中断收尾,完整性判定消费 alive_after)。
                try:
                    self._q.put(self._CLOSE_SENTINEL, block=False)
                    self._stats["closed"] = True
                except Exception:  # noqa: BLE001 —— queue.Full
                    pass
        if not self._thread.is_alive():
            with self._lock:
                self._stats["thread_joined"] = True
            return True
        self._thread.join(timeout=max(0.0, timeout))
        joined = not self._thread.is_alive()
        with self._lock:
            self._stats["thread_joined"] = joined
        return joined

    def is_sealed(self) -> bool:
        with self._lock:
            return self._sealed

    def stats(self) -> dict[str, Any]:
        with self._lock:
            out = dict(self._stats)
            out["failures"] = list(self._failures)
            out["queued"] = self._q.qsize()
        out["pending"] = out["queued"]
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
        # RSA-02:guest 側同款身份/序號閘(live 消費閉合)——重複
        # seq/回退/早於 run 的 utc 不刷新有效快照與失聯計時
        self.guest_duplicate_seq = 0
        self.guest_seq_regressions = 0
        self.guest_stale_replayed = 0
        self._guest_seen_seq: set[int] = set()
        self._guest_max_seq: int | None = None
        _dt0 = _parse_utc_iso(self._started_utc)
        self._guest_predates_cutoff = (
            _dt0.timestamp() - float(
                self.policy["startup_admission"]["source_utc_tolerance_s"])
            if _dt0 is not None else None)
        self.admission: dict[str, Any] | None = None
        # B2:异步 I/O 执行单元(控制路径永不同步等待日志/告警写)
        self.iow = BoundedIOWriter()
        self._io_lost_critical_seen = 0
        # WP2:分批封口状态(drain 未确认数;0=alerts 批全部成功)
        self._io_drain_unconfirmed = 0
        # B4:leader 退出后的残留核验状态
        self._desc_check_done = False
        self._residual_handled = False
        self.residual_unconfirmed = False
        self._evidence_complete: bool | None = None
        # B5:启动前意图校验结果(_declare_expected 填充)
        self._startup_reject: str | None = None
        # WP2(RCF-02):外部停止意图(handler 只登记;正常控制路径
        # 消费)。必须在 __init__ 初始化——finalize/write_summary 存在
        # 不经 run() 的直接调用面(测试),懒初始化会 AttributeError。
        self._external_stop_sig: int | None = None
        self._external_stop_consumed = False
        # WP2(stop-cutoff):停止接受截止点 C 的状态面。sig_count 由
        # handler 纯自增(首个信号粘性+总数可判"C 后新到");C 在
        # finalize 尾部 sigmask 临界区内越过(原始证据已固定之后)。
        self._external_stop_sig_count = 0
        self._external_stop_count_at_cutoff: int | None = None
        self._stop_cutoff_reached = False
        # WP2-B(sampler-quiescence):必要原始流写者的关闭确认状态——
        # "动作已发送/等待已返回/写入者已退出"是三个事实,只有最后一项
        # 能支撑流的最终不可变身份(§6.1 表)。未确认(None 字段/False)
        # 时该流不得进入完整证据判定;句柄与身份保留,不用置 None 掩盖
        # 存活(SFB-03)。
        self._guest_close_state: dict[str, Any] | None = None
        self._win_close_state: dict[str, Any] | None = None
        self._io_close_state: dict[str, Any] | None = None
        # WP2-A(fail-closed):guest 写者生命周期三态分界——
        # never_started(False)/started_unconfirmed(True 且无确认
        # 关闭记录)/confirmed_exited(True 且 close_state.joined)。
        # None 引用不再同时代表"没有写者"与"曾有写者、引用丢了":
        # 曾启动而无关闭记录=未知,按仍有活写者处理。
        self._guest_ever_started = False
        # WP1(stop-cutoff):临界区线程前提核验结果(所有存活线程屏蔽
        # TERM/INT 才有"屏蔽中到达=必然解除后执行"的挂起边界;S1)。
        self._cutoff_premise_ok: bool | None = None
        self._cutoff_premise_detail: str | None = None
        # WP1(fc-integrity):控制能力失败事实(粘性列表;非空=run
        # 非成功,外层 rc=7)——必要截止边界的前提(掩码取得/线程
        # 屏蔽核验/掩码还原)无法证明或失败时登记;summary/run_
        # record/control_outcome/verifier 消费同一事实(与
        # evidence_complete 正交:证据可以完整地记录一次控制失败)。
        self._control_failures: list[dict[str, Any]] = []
        # WP1(fc-integrity):C 是否经前提核验认证——前提失败时不
        # 建立"已认证 C"(不伪造成功 C;post_cutoff 回执只在认证
        # 后生成,停止归属如实记为无法认证)。
        self._cutoff_certified = False
        # WP1(publication):对外完成件的发布状态(C 决定之后才发布;
        # 发布失败=run 非成功,不允许沿用旧完成件或候选冒充)。
        self._summary_publish_failed = False
        # WP2-B(fail-closed):发布失败的粘性细节(阶段/错误;只记首次,
        # 不因重入清除)——run_record/summary/诊断消费同一事实。
        self._summary_publish_failure: dict[str, Any] | None = None
        self._run_record_publish_failed = False
        self._rr_candidate_entries: list[dict[str, Any]] | None = None
        # WP1-B(shared-budget):整个 run 一份收尾预算——首次进入终止性
        # 处理(异常路径)或正常收尾(finalize/早拒绝)时建立绝对单调
        # deadline,此后停止/升级/核验/辅助停止/drain/发布所有受控等待
        # 只消费剩余时间,不再各自获得全额 timeout(§5.1/5.2)。run()
        # 开头随 external stop 状态一起重置(每个 run 一份;同一 run 内
        # 重复进入收尾方法复用同一 deadline,不重开)。
        self._finalize_deadline: float | None = None
        self._finalize_budget_est_at: float | None = None
        self._finalize_budget_reason: str | None = None
        self._finalize_budget_notes: list[dict[str, Any]] = []
        # WP1-A(secondary-failure):终止收尾循环内各步骤的二次错误
        # 有界登记(每步骤保留首错误与计数;不生成无界 traceback)。
        self._shutdown_step_failures: dict[str, dict[str, Any]] = {}
        # WP1(RCF-01):首次读取失败告警只发一次(有界)
        self._win_read_failure_logged = False
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
        """alerts.jsonl 追加写(在 I/O 执行线程内运行)。

        失败计数保留在 Supervisor 属性(摘要披露),同时**上抛**让
        writer 计 failed——回调吞错不是成功(§5.1)。
        """
        try:
            with self.alerts_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(obj, ensure_ascii=False,
                                    separators=(",", ":")) + "\n")
        except OSError:
            self.log_failures += 1
            raise

    def log(self, obj: dict[str, Any]) -> None:
        obj = dict(obj)
        obj.setdefault("utc", utc_now_iso())
        obj.setdefault("mono", round(time.monotonic() - self.t0, 1))
        obj.setdefault("run_id", self.run_id)
        self.iow.submit(lambda: self._log_sync(obj),
                        critical=obj.get("severity") == "CRITICAL",
                        role="alerts")

    def safe_log(self, obj: dict[str, Any]) -> None:
        """尽力而为日志:投递失败计数并继续(不阻断保护路径)。"""
        self.log(obj)

    def _stdout_sync(self, tag: str, line: str) -> None:
        try:
            print(f"{tag} {line}", flush=True)
        except (BrokenPipeError, OSError, ValueError):
            # ValueError: 已关闭流;BrokenPipe:消费者离开;计数保留
            # 在 Supervisor 属性,同时上抛让 writer 计 failed(§5.1)
            self.stdout_failures += 1
            raise

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
                        critical=tag == "R17ALERT", role="stdout")

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
                # WP2-A(SFB-02):第一次接受终止决定、准备请求停止时就
                # 建立本 run 唯一总 deadline——先于诊断与 Protector.
                # request_stop(§5.1:建立点必须早于第一次实际停止请求;
                # 随后业务合作退出/sampler 关闭/drain/发布全部只消费
                # 剩余时间,转异常与重复停止不续期)。WARNING 不进入
                # 本分支,不建立终止预算。
                self._ensure_finalize_budget(f"stop_accept:{kind}")
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
        self.win_reader = WinSampleReader(
            self.win_path_guest, run_id=self.run_id,
            started_iso=self._started_utc,
            predates_tolerance_s=self.policy["startup_admission"][
                "source_utc_tolerance_s"])
        self.win_sampler_started = True
        self.log({"event": "win_sampler_started",
                  "interop_pid": self.win_proc.pid,
                  "out_guest": str(self.win_path_guest),
                  "emergency_win_dir": self.emergency_win_dir,
                  "max_seconds": max_s})
        return True

    def stop_win_sampler(self) -> None:
        # WP1-B:辅助采样器停止也属于收尾链——建立/复用本 run 唯一
        # 预算,等待只消费剩余时间(§5.1:辅助采样与写者关闭阶段)。
        self._ensure_finalize_budget("stop_win_sampler")
        if self.win_proc is None:
            return
        pid = self.win_proc.pid
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        wait_allow = self._bounded_wait(10.0, "win_sampler_join")
        # WP2-B(SFB-03):所等候句柄=启动本 run 采样器的 interop 进程,
        # ps1 由该进程 -File 直跑并以 AppendAllText 写 OutFile(无子
        # 写进程)——wait 返回即实际写者退出。timeout 不能生成"已停止"
        # 事实:超时/退出核验不可用时记录"已请求、未确认",必要遥测
        # 流的可变性保留(完整性判定消费 _win_close_state,不写 stopped)。
        self._win_close_state = {
            "stop_requested": True, "interop_pid": pid,
            "waited": False, "exited": False, "unconfirmed": True}
        try:
            self.win_proc.wait(timeout=wait_allow)
            self._win_close_state.update(
                {"waited": True, "exited": True, "unconfirmed": False})
            self.log({"event": "win_sampler_stopped",
                      "interop_pid": pid,
                      "windows_pid": self.win_pid_windows})
        except subprocess.TimeoutExpired:
            self._win_close_state.update({"waited": True})
            self.log({"event": "win_sampler_stop_unconfirmed",
                      "interop_pid": pid,
                      "budget_remaining_s":
                          round(self._finalize_remaining(), 3),
                      "note": "停止已请求、完成未确认(受控等待只"
                              "消费剩余预算;不无限等;不得记录为已停"
                              "止;telemetry_win 流不进入完整证据判定)"})

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
                # WP2-A(SPSC-02A):只请求停止,**不清引用**——已启动
                # 写者的关闭事实由共享收尾(finalize join 段)确认;
                # 旧 stop() 后立即置 None 会让 budget 出口绕过写者
                # 关闭(句柄丢失=未知被掩盖,evidence 误报完整)。
                # stop 幂等(Event.set),finalize 段重复请求无副作用。
                if self.guest_sampler:
                    self.guest_sampler.stop()

    # ---------------- 应急兜底 ----------------
    def _emergency_sync(self, obj: dict[str, Any]) -> None:
        # I/O 执行线程内运行(seal 后应急回退时在调用者线程);
        # 只写启动时解析的当前用户目录
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

        RSA-01:批次已封口(seal 后)时 submit 被拒——应急通道回退为
        同步直写(异常路径上的一次受控 I/O,不静默丢弃);队列满
        (dropped)仍走既有保护触发路径,不在此放大。
        """
        if not self.iow.submit(lambda: self._emergency_sync(obj),
                               critical=True, role="emergency") and \
                self.iow.is_sealed():
            self._emergency_sync(obj)

    # ---------------- 摘要与 run_record ----------------
    def _build_summary(self) -> dict[str, Any]:
        """summary 纯构建(无 I/O;WP1:候选在停止决定 C 之前于内存/
        私有面准备,发布在 C 之后,由 write_summary 承担)。"""
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
                # RSA-02:拒绝结果贯穿摘要(同一 reader/emit 闸计数)
                "win_duplicate_seq": self.win_reader.duplicate_seq
                if self.win_reader else None,
                "win_seq_regressions": self.win_reader.seq_regressions
                if self.win_reader else None,
                "win_stale_replayed": self.win_reader.stale_replayed
                if self.win_reader else None,
                # WP1(RCF-01):读取失败有界诊断(事实面;不充当样本)
                "win_read_failures": self.win_reader.read_failures
                if self.win_reader else None,
                "win_read_failure_consecutive":
                    self.win_reader.read_failure_consecutive
                    if self.win_reader else None,
                "win_read_failure_last_op":
                    self.win_reader.read_failure_last_op
                    if self.win_reader else None,
                "win_read_failure_last_utc":
                    self.win_reader.read_failure_last_utc
                    if self.win_reader else None,
                "win_read_failure_last_err":
                    self.win_reader.read_failure_last_err
                    if self.win_reader else None,
                "guest_duplicate_seq": self.guest_duplicate_seq,
                "guest_seq_regressions": self.guest_seq_regressions,
                "guest_stale_replayed": self.guest_stale_replayed,
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
            # WP2-B(sampler-quiescence):必要流写者的关闭确认事实
            # (§6.1 表:请求/等待/真实退出三状态分列;未确认≠已停止)。
            # WP2-A:guest=None 仅代表从未启动——曾启动而无关闭记录
            # 记 {"ever_started": true}(未知不被 None 掩盖)。
            "writers": {
                "guest": dict(self._guest_close_state)
                if self._guest_close_state else (
                    {"ever_started": True}
                    if self._guest_ever_started else None),
                "win": dict(self._win_close_state)
                if self._win_close_state else None,
                "io": dict(self._io_close_state)
                if self._io_close_state else None,
                "business_live": self.residual_unconfirmed or (
                    self.protector is not None and
                    self.protector.requested_at is not None and
                    self.protector.terminal_at is None),
            },
            # WP1(publication):发布状态(C 后单次发布;失败=非成功)
            "publication": {
                "summary_failed": self._summary_publish_failed,
                "summary_failure": dict(self._summary_publish_failure)
                if self._summary_publish_failure else None,
                "run_record_failed": self._run_record_publish_failed,
                "cutoff_premise_ok": self._cutoff_premise_ok,
                "cutoff_premise_detail": self._cutoff_premise_detail,
                "control_failures": list(self._control_failures),
            },
            # WP2(RCF-02):外部停止意图事实(handler 只登记;null=从未)
            "external_stop_sig": self._external_stop_sig,
            "external_stop_consumed": self._external_stop_consumed,
            # WP2(stop-cutoff):信号总数(写入时刻;C 的判定/标记在
            # finalize 尾部 sigmask 临界区内越过,summary 是 C 的前置
            # 件,故 summary 内不记 C 状态;C 后事件由独立的
            # post_cutoff_signal.json 承载)
            "external_stop_sig_count": self._external_stop_sig_count,
            # WP1-B(shared-budget):本 run 唯一收尾预算的可核验事实
            # (§5.3:一次起点、各阶段请求/剩余/允许、写入时剩余)。
            "finalize_budget": {
                "window_s": self.policy["finalize_window_s"],
                "established_at_mono": self._finalize_budget_est_at,
                "establish_reason": self._finalize_budget_reason,
                "remaining_at_write":
                    round(self._finalize_remaining(), 3),
                "notes": list(self._finalize_budget_notes),
            },
            # WP1-A(secondary-failure):收尾二次错误有界事实
            "shutdown_step_failures": {
                k: dict(v) for k, v in
                self._shutdown_step_failures.items()},
            "telemetry_bytes": self.telemetry_bytes(),
            "stage_marks": self.stage_marks,
            "emergency_win_dir": self.emergency_win_dir,
            "win_pids": {"interop":
                         self.win_proc.pid if self.win_proc else None,
                         "windows": self.win_pid_windows},
            "written_utc": utc_now_iso(),
        }
        return summary

    def write_summary(self) -> dict[str, Any]:
        """发布 summary.json(停止决定 C 之后才调用;C 前候选为私有)。

        WP2-B(SPSC-02B/fc-integrity):发布走同目录私有临时文件完整
        写入+关闭后经 os.replace 替换——部分写入/flush/close/替换
        失败都不再在最终路径留下半份内容(失败临时件保留为诊断
        残片,不在 required 角色中冒充成品;S3:成功替换提供原子
        可见性,不扩大为掉电持久化证明)。最终路径已有文件=运行
        唯一性冲突,拒绝覆盖/复用旧件。发布失败落 _summary_publish_
        failed(粘性;_evidence_ok/control_outcome/run_record 同一
        消费),不吞掉失败后沿用旧文件/旧成功记录;候选 dict 照常
        返回供诊断(emergency 载荷)。
        """
        summary = self._build_summary()
        target = self.run_dir / "summary.json"
        tmp = self.run_dir / ".summary.json.tmp"
        if target.exists():
            # 本 run 的发布目标已有文件:不允许覆盖(已有运行唯一性;
            # 残片/旧件都不能被新发布顶替或冒充)
            self._summary_publish_failed = True
            self._summary_publish_failure = self._summary_publish_failure \
                or {"stage": "target_exists",
                    "target": str(target)}
            self.emergency_write({"event": "summary_write_failed",
                                  "run_id": self.run_id,
                                  "stage": "target_exists",
                                  "summary": summary})
            return summary
        try:
            payload = json.dumps(summary, ensure_ascii=False, indent=1)
            with tmp.open("w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
            tmp.replace(target)
        except OSError as exc:
            # 失败临时件保留为明确诊断残片(私有名,不进必需集合);
            # 已知发布失败后,最终路径上的任何字节都不再构成有效
            # 已发布角色(run_record 侧记 publish_failed)
            self._summary_publish_failed = True
            self._summary_publish_failure = self._summary_publish_failure \
                or {"stage": "write_or_replace",
                    "error": f"{type(exc).__name__}:{exc}"[:160]}
            self.emergency_write({"event": "summary_write_failed",
                                  "run_id": self.run_id,
                                  "stage": "write_or_replace",
                                  "error": f"{type(exc).__name__}:{exc}"
                                  [:160],
                                  "summary": summary})
        return summary

    def _evidence_ok(self, missing: list[str]) -> bool:
        """§5.4:文件存在≠证据完整。完整=必需角色全 present + 写入
        封口干净(drain 未确认=0、无失败写动作、无关键丢弃)+ 必要
        原始流的所有可能写入者均已确认不能再修改它(§6.4:业务进程
        组、guest/Windows 采样器、I/O 写线程三组关闭事实同一判定面;
        采样写者存活/未知时不得为流声明最终不可变身份,SFB-03)。
        WP2-B(fail-closed):已知必要发布失败=必要结果证据不完整
        ——即使最终路径上有字节可读、哈希可算(残片/旧件不能抵消
        已知失败;标志在本 run 内粘性,不因重入清除)。"""
        if missing:
            return False
        if self._summary_publish_failed:
            return False
        if self._io_drain_unconfirmed:
            return False
        # WP2-A(fail-closed):三态消费——已启动写者缺少关闭记录时
        # 按未知处理(None 不掩盖"曾有写者";join 返回值/停止请求/
        # daemon 都不是退出证明,S2)
        if self._guest_close_state is not None:
            if self._guest_close_state.get("alive_after_join"):
                return False
        elif self._guest_ever_started:
            return False
        if self._win_close_state is not None and \
                self._win_close_state.get("unconfirmed"):
            return False
        if self._io_close_state is not None and \
                self._io_close_state.get("alive_after"):
            return False
        st = self.iow.stats() if self.iow else {}
        if st.get("failed") or st.get("io_stuck") or \
                st.get("queued") or st.get("in_flight"):
            return False
        # RSA-01:完成性以 accepted==ok+failed 为准(单一计数口径;
        # queued/in_flight 是诊断冗余,一致性核对是独立防线)。
        if st.get("accepted", 0) != (st.get("ok", 0)
                                     + st.get("failed", 0)):
            return False
        if st.get("dropped_critical"):
            return False
        return True

    def _writer_live_for_role(self, role: str) -> bool:
        """WP2-B(§6.4):该必要角色原始流是否仍有未确认关闭的写入者。
        分角色写者映射:业务 leader+登记后代→business_*;guest 采样
        线程(emit 同步写 telemetry_guest)→telemetry_guest;win 采样
        进程(AppendAllText 直写 telemetry_win)→telemetry_win;I/O
        写线程→alerts。
        WP2-A(fail-closed):declared:<role>(--expect-artifact 显式
        登记的规范角色)继承同名角色的写者映射——登记通道不改变
        该流的写者事实。"""
        if role.startswith("declared:"):
            role = role.split(":", 1)[1]
        if role in ("business_stdout", "business_stderr"):
            return self.residual_unconfirmed or (
                self.protector is not None and
                self.protector.requested_at is not None and
                self.protector.terminal_at is None)
        if role == "telemetry_guest":
            if self._guest_close_state is not None:
                return bool(
                    self._guest_close_state.get("alive_after_join"))
            # WP2-A:曾启动而无关闭记录=未知,按仍可能写处理
            # (未启动=False,不误拒 replay/零启动形态)
            return self._guest_ever_started
        if role == "telemetry_win":
            return bool(self._win_close_state is not None and
                        self._win_close_state.get("unconfirmed"))
        if role == "alerts":
            return bool(self._io_close_state is not None and
                        self._io_close_state.get("alive_after"))
        return False

    def _any_live_writer(self) -> bool:
        """任一必要角色存在未确认写者(evidence_complete 的同源输入)。"""
        return any(self._writer_live_for_role(item["role"])
                   for item in self.expected)

    def _prepare_run_record_entries(self) -> tuple[list[dict[str, Any]],
                                                   list[str]]:
        """WP1(publication):run_record 必需角色条目的候选计算(C 前)。

        大文件哈希按 1MiB 分段、在写者关闭确认之后计算并缓存为私有
        候选(§4.3:C 前可在私有面准备摘要与原始文件哈希;候选不是
        完成件);summary 角色发布时序在 C 之后,其条目由
        finalize_run_record 发布时现算(不进候选)。live_writers=True
        的流:哈希只是当时截取的诊断快照,不构成最终不可变身份。
        """
        root = self.run_dir.parent.parent  # run_supervision 根
        entries: list[dict[str, Any]] = []
        missing: list[str] = []
        for item in self.expected:
            role = item["role"]
            if role == "summary":
                continue  # 发布时序在 run_record 之后,现算
            p = Path(item["path"])
            entry = {"role": role,
                     "path": str(p.relative_to(root)).replace("\\", "/")
                     if p.is_relative_to(root) else str(p)}
            if self._writer_live_for_role(role):
                entry["live_writers"] = True
            if not p.is_file():
                entry["status"] = "missing"
                missing.append(role)
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
                    missing.append(role)
            entries.append(entry)
        return entries, missing

    def finalize_run_record(self) -> Path:
        """run_record.json(schema v2;build 必需集合来源;原子写)。

        S5 修复(WP4):必需集合来自**运行前登记**(_declare_expected),
        不随现存文件缩小——缺件保留为 status="missing";真实空文件
        是 present+bytes=0;finalized=记录已封口,evidence_complete
        另行判定,缺件交付=不完整(verify 据此 FAIL)。

        WP1(publication):本方法只在停止决定 C **之后**发布(私有候选
        条目→决定→同一决定发布;C 前不存在 finalized=true 的对外完成
        件)。summary 角色条目在发布时现算(它由紧前的 summary 发布
        产生);其余角色消费 C 前候选哈希(写者已确认关闭的流在候选
        之后不再变化;未确认流标 live_writers,哈希仅为诊断快照)。
        """
        root = self.run_dir.parent.parent  # run_supervision 根
        if self._rr_candidate_entries is not None:
            required = [dict(e) for e in self._rr_candidate_entries]
            missing = [e["role"] for e in required
                       if e.get("status") in ("missing", "unreadable")]
        else:
            # 防御直调面(未走 finalize 顺序):现算非 summary 角色
            # (summary 条目统一由下方现算段生成——验收观察①:防御
            # 分支若不跳过会与现算段重复登记该角色)
            required = []
            missing = []
            for item in self.expected:
                if item["role"] == "summary":
                    continue
                p = Path(item["path"])
                entry = {"role": item["role"],
                         "path": str(p.relative_to(root))
                         .replace("\\", "/")
                         if p.is_relative_to(root) else str(p)}
                if self._writer_live_for_role(item["role"]):
                    entry["live_writers"] = True
                if not p.is_file():
                    entry["status"] = "missing"
                    missing.append(item["role"])
                else:
                    entry.update({"status": "present",
                                  "sha256": _file_sha256(p),
                                  "bytes": p.stat().st_size})
                required.append(entry)
        # summary 条目:发布时序在 run_record 之前,现算(哈希真实)
        # WP2-B(fail-closed):已知发布失败→status="publish_failed"
        # (必要角色无效,verify 据此 FAIL)——最终路径上有字节也不
        # 登记 present(残片/旧件不能抵消已知失败;目标非文件仍记
        # missing,两者都是非完整交付)。
        for item in self.expected:
            if item["role"] != "summary":
                continue
            p = Path(item["path"])
            entry = {"role": "summary",
                     "path": str(p.relative_to(root)).replace("\\", "/")
                     if p.is_relative_to(root) else str(p)}
            if self._writer_live_for_role("summary"):
                entry["live_writers"] = True
            if self._summary_publish_failed:
                entry["status"] = "publish_failed"
                if self._summary_publish_failure:
                    entry["failure"] = dict(self._summary_publish_failure)
                missing.append("summary")
            elif not p.is_file():
                entry["status"] = "missing"
                missing.append("summary")
            else:
                try:
                    entry.update({"status": "present",
                                  "sha256": _file_sha256(p),
                                  "bytes": p.stat().st_size})
                except OSError:
                    entry["status"] = "unreadable"
                    missing.append("summary")
            required.append(entry)
        # WP2-A:guest=None 仅代表从未启动(三态生命周期);
        # 曾启动而无关闭记录记 {"ever_started": true}。
        writers_block = {
            "guest": dict(self._guest_close_state)
            if self._guest_close_state else (
                {"ever_started": True}
                if self._guest_ever_started else None),
            "win": dict(self._win_close_state)
            if self._win_close_state else None,
            "io": dict(self._io_close_state)
            if self._io_close_state else None,
            "business_live": self.residual_unconfirmed or (
                self.protector is not None and
                self.protector.requested_at is not None and
                self.protector.terminal_at is None),
        }
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
            "evidence_complete": self._evidence_ok(missing) and
            not self._any_live_writer(),
            "missing_roles": missing,
            # WP1(fc-integrity):控制失败事实独立于 evidence_complete
            # (证据可完整记录一次控制失败;verify 按 control_failures
            # 非空拒绝"完整运行通过",读者不得把失败证据读成成功)。
            "control_failures": [dict(c) for c in self._control_failures],
            "cutoff_certified": self._cutoff_certified,
            "writers": writers_block,
            "io": self.iow.stats() if self.iow else None,
            "finalized": True,
        }
        self._evidence_complete = rec["evidence_complete"]
        tmp = self.run_dir / ".run_record.tmp"
        try:
            tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self.run_dir / "run_record.json")
        except OSError as exc:
            # WP1(P02):发布失败实际影响结果——不沿用旧完成件、不伪造
            # finalized;失败事实落 emergency,run 整体非成功(无合法
            # 完成记录;正常流程经 raise→run 统一收尾→外层 3,直调/
            # summary 失败面经 control_outcome 发布失败/证据不完整路径
            # 返回 6——两个出口都是非成功,验收观察③注)。
            self._run_record_publish_failed = True
            self._evidence_complete = False
            self.emergency_write({
                "event": "run_record_publish_failed",
                "run_id": self.run_id,
                "error": f"{type(exc).__name__}:{exc}"[:200],
                "note": "完成记录发布失败:本 run 无合法完成件"})
            raise
        return self.run_dir / "run_record.json"

    def _observe_business_exit(self) -> None:
        """业务退出观察(幂等):记录真实 rc/signal 与 business_exited。

        同一轮主循环内,退出条件块的 poll 可能先于下一轮监控段
        看到退出(TERM 后即死形态);break 前必须经本方法取得真实
        rc——任务树消失不等于已取得退出码,取得前不 break(§7.2),
        不能因观察时序把真实 rc 丢成 None。
        """
        if self.biz_proc is None or self.biz_proc.poll() is None:
            return
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
                        "metrics": {"rc": rc, "patterns": patterns}}
                self.handle_triggers([trig])
            self.mark_stage("business_exited", f"rc={rc}")

    # ---------------- 主循环 ----------------
    def _sig_external(self, sig, frame) -> None:
        """TERM/INT handler:只登记停止意图(§5.2 纯属性赋值)。

        RCF-02 修复:旧 handler 先 self.log(→iow.submit→writer 普通
        Lock)再 request_stop——主线程持锁时被信号打断,handler 在
        主线程执行,重入同锁即同线程死锁(handler 永不返回,停止
        与保护停摆;已实测复现)。本 handler 零 log/零锁/零 I/O/零
        进程操作;停止原因保留首次信号(重复信号不覆盖原因,粘性)。
        派发由正常控制路径消费(run 早期检查/主循环每轮检查)。
        """
        if self._external_stop_sig is None:
            self._external_stop_sig = sig
        # WP2(stop-cutoff):计数允许区分"C 前已消费的信号"与
        # "C 之后新到的事件"(首个信号粘性不覆盖;纯自增,零 I/O)。
        self._external_stop_sig_count += 1

    def _consume_external_stop(self) -> None:
        """正常控制路径消费外部停止意图(§5.3):粘性,只消费一次。

        停止调度(log/handle_triggers/request_stop)全部发生在正常
        上下文——无重入风险。走既有 PROTECTION_UNAVAILABLE 链:
        stop_requested_reasons+request_stop(业务活跃)或 no_live_
        task(阻止后续步骤);业务不活跃时保护链无从派发,外部停止
        仍必须是非成功收尾(exit_code=4,修补"业务自然退出后 TERM
        落到 rc=0"的既有洞)。
        """
        sig = self._external_stop_sig
        if sig is None or self._external_stop_consumed:
            return
        self._external_stop_consumed = True
        self.log({"event": "supervisor_signal", "sig": sig,
                  "note": "外部停止意图由正常控制路径消费(handler "
                          "只登记;停止调度在此发生)"})
        self.handle_triggers([{
            "kind": "supervisor_external_stop",
            "severity": "PROTECTION_UNAVAILABLE",
            "detail": f"supervisor 收到信号 {sig}:停止本 run 已登记"
                      f"任务(正常控制路径派发)",
            "metrics": {"sig": sig}}])
        if not (self.protector and
                self.protector.requested_at is not None):
            # 业务未启动/已退出:无保护链可派发;外部停止=非成功收尾
            # (不覆盖更早已定的拒绝码;外部停止与 2/93/94 不竞争语义)
            if not self.exit_code:
                self.exit_code = 4

    def _external_stop_early_window(self, note: str) -> None:
        """早窗口(启动拒绝/就绪屏障/准入)外部停止:零业务启动已由
        调用分支保证;停止事实入日志,整体 exit_code=4(外部停止不
        是成功收尾,不与拒绝码 2/93/94 竞争语义)。"""
        sig = self._external_stop_sig
        if sig is None:
            return
        # WP2-A(SFB-02):早窗口也是"第一次接受终止决定"——先建立
        # 总预算再消费,随后的 samplers-only 清理与 finalize 只消费
        # 剩余时间(§5.1:覆盖早拒绝后的辅助清理入口)。
        self._ensure_finalize_budget("stop_accept:supervisor_external_stop")
        self._external_stop_consumed = True
        self.log({"event": "supervisor_signal", "sig": sig, "note": note})

    # ---------------- WP1/WP2:统一收尾与截止点 ----------------
    def _install_signal_handlers(self):
        """注册最小停止意图 handler(可重入;返回恢复凭据)。

        嵌套安装(run 直调方一层、CLI main 一层)时各存各的旧值,
        恢复链保持正确:内层恢复到外层安装的 handler,外层最终恢复
        到真正的旧 handler。非主线程调用(测试形态)降级返回 None,
        不注册——非主线程形态不作为生产验收替代品(§4.4)。
        """
        try:
            old_term = signal.signal(signal.SIGTERM, self._sig_external)
            old_int = signal.signal(signal.SIGINT, self._sig_external)
        except ValueError:
            return None
        return (old_term, old_int)

    def _restore_signal_handlers(self, token) -> None:
        if token is None:
            return
        for signum, old in ((signal.SIGTERM, token[0]),
                            (signal.SIGINT, token[1])):
            if old is not None:
                try:
                    signal.signal(signum, old)
                except ValueError:
                    pass

    def _consume_external_stop_sealed(self) -> None:
        """原始流 seal 之后的 C 前消费(§5.3:封口后不重开原始流)。

        此处不能再走完整消费链(log/alert 会向已 seal 的 writer 提交
        动作而被拒)——结果层消费:置 consumed+exit_code=4;事实由
        随后的 summary 元数据承载(尚未发布)。"""
        if self._external_stop_sig is None or self._external_stop_consumed:
            return
        self._external_stop_consumed = True
        if not self.exit_code:
            self.exit_code = 4

    # ---------------- WP1-A/WP1-B:二次错误隔离与共享收尾预算 ----------------
    def _ensure_finalize_budget(self, reason: str) -> float:
        """建立/复用本 run 唯一的收尾 deadline(§5.1:一次建立、一直
        复用)。

        首次进入终止性处理(_terminal_shutdown)或正常收尾(finalize/
        早拒绝)时建立绝对单调 deadline;此后重复进入任何收尾方法
        (第二异常、重复信号、CLI 兜底)复用同一 deadline,不重新计时。
        建立点先于可能失败/阻塞的诊断(§5.1:首次终止事实与 deadline
        的建立放在诊断之前)。
        """
        if self._finalize_deadline is None:
            self._finalize_deadline = (
                time.monotonic() + self.policy["finalize_window_s"])
            self._finalize_budget_est_at = time.monotonic() - self.t0
            self._finalize_budget_reason = reason
            self._finalize_budget_notes.append({
                "phase": "budget_established", "requested":
                    self.policy["finalize_window_s"], "remaining":
                    self.policy["finalize_window_s"], "reason": reason})
        return self._finalize_deadline

    def _finalize_remaining(self) -> float:
        """当前剩余收尾预算(秒;未建立时返回全额窗口——防御,正常
        调用面都先经 _ensure_finalize_budget)。"""
        if self._finalize_deadline is None:
            return float(self.policy["finalize_window_s"])
        return max(0.0, self._finalize_deadline - time.monotonic())

    def _bounded_wait(self, cap_s: float, phase: str) -> float:
        """受控等待上限 = min(该阶段原上限, 当前剩余预算)(§5.2)。

        零剩余返回 0.0(不转换成 None/默认值/无期限等待)。记录一次
        (阶段, 原上限, 剩余, 实际允许)有界预算事实,供 summary/测试
        核验(§5.3);不做高频追踪。
        """
        rem = self._finalize_remaining()
        allow = min(float(cap_s), rem)
        if len(self._finalize_budget_notes) < 64:
            self._finalize_budget_notes.append({
                "phase": phase, "requested": float(cap_s),
                "remaining": round(rem, 3), "allowed": round(allow, 3)})
        return allow

    def _shutdown_step(self, name: str, fn, default=None):
        """终止收尾循环内单步执行兜底(§4.1:第二失败不放弃仍然可
        执行的保护)。

        该步抛错被有界吸收(每步骤保留首错误与计数;首条经 emergency
        同步落盘,后续只累计),返回 default——调用方继续推进不依赖该
        步的其余控制(poll/升级/核验)。不要求错误步骤本身恢复:永久
        错误可以一直失败,但不能连带禁用不依赖它的控制(§4.1)。
        """
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 —— 有界吸收,不弃控制
            rec = self._shutdown_step_failures.get(name)
            if rec is None:
                rec = {"count": 0, "first_error": str(exc)[:300],
                       "first_error_type": type(exc).__name__,
                       "first_at_mono": round(time.monotonic() - self.t0, 3)}
                self._shutdown_step_failures[name] = rec
                try:
                    self.emergency_write({
                        "event": "terminal_shutdown_step_failure",
                        "run_id": self.run_id, "step": name,
                        "error": str(exc)[:300],
                        "note": "收尾步骤二次失败被隔离;不依赖该步的"
                                "控制继续执行"})
                except Exception:
                    pass
            rec["count"] += 1
            return default

    def _terminal_state_confirmed(self) -> bool:
        """终态确认=直接业务 rc 已取得 且 登记组无活成员(§4.2)。

        leader 退出、TERM 已发送、单次扫描未见 PID——任何单项都不
        单独替代这两项事实。"""
        if self.biz_proc is not None and self.biz_proc.poll() is None:
            return False  # leader 仍活(rc 未取得)
        if self.protector is not None:
            if self.protector.requested_at is not None:
                if self.protector.terminal_at is not None:
                    return True
                return not bool(self.protector._member_pids())
            return True  # 从未请求停止且 leader 已退/未启动
        return True

    def _terminal_shutdown(self, reason: str) -> None:
        """终止性收尾(异常路径与 CLI 共享;§4.1/4.2/4.3)。

        正常路径的停止/升级/核验由主循环驱动同一 Protector 规则;
        本方法只在"进入终止性处理"后使用:不重跑刚抛错的采样/策略/
        报告逻辑,保留首个失败事实,推进已登记停止(合作窗满自动升级
        KILL),以共享剩余预算(policy.finalize_window_s=120s,自进入
        本方法起算;不因重复异常/重复信号重开)驱动到终态确认或预算
        尽(预算尽=完成未确认,如实置 residual_unconfirmed,不写成
        安全完成)。证据封口统一经 finalize(C 检查点在 finalize 内,
        与正常路径共享同一封口算法)。

        WP1-A(secondary-failure):循环内每步(poll/flush_logs/退出
        观察/终态核验)独立兜底——日志 flush 或退出观察再次抛错只
        有界登记该步失败,信号控制(poll→合作窗满→KILL)与成员核验
        继续执行(§4.1:不因非必要诊断失败放弃仍然可执行的保护;
        实际 poll/退出读取一次失败=本轮未知而非已退出,预算内下轮
        重读)。
        """
        deadline = self._ensure_finalize_budget(
            f"terminal_shutdown:{reason}")
        try:
            if self.biz_proc is not None and self.protector is not None \
                    and self.protector.requested_at is None:
                self.protector.request_stop(reason)
            while time.monotonic() < deadline:
                mono = time.monotonic() - self.t0
                if self.protector is not None:
                    prot = self.protector
                    self._shutdown_step("poll", lambda: prot.poll(mono))
                    if prot.pending_logs:
                        self._shutdown_step("flush_logs",
                                            prot.flush_logs)
                self._shutdown_step("observe_exit",
                                    self._observe_business_exit)
                if self._shutdown_step("state_confirmed",
                                       self._terminal_state_confirmed,
                                       default=False):
                    return
                time.sleep(0.2)
            # 预算尽:完成未确认(残留身份保留;外层非零;下一重任务
            # 被既有入口阻断;不填 raw rc=0,不写成安全完成)。
            # 残留核验自身失败≠无残留:未确认保持未确认(default=True)。
            residual = self._shutdown_step(
                "residual_scan",
                lambda: bool(self.protector._member_pids())
                if self.protector else False,
                default=True)
            self.residual_unconfirmed = bool(residual)
            try:
                self.emergency_write({
                    "event": "terminal_shutdown_budget_exhausted",
                    "run_id": self.run_id, "reason": reason,
                    "survivors": (self.protector.survivors[:32]
                                  if self.protector else [])})
            except Exception:
                pass
        finally:
            # §4.5:清理段每步独立兜底——再次抛错不中断可独立执行的
            # 其余步骤,记录第二失败,不递归再入一轮无预算 finalize。
            try:
                if self.protector is not None and \
                        self.protector.pending_logs:
                    self.protector.flush_logs()
            except Exception:
                pass
            try:
                self.finalize()
            except Exception as exc2:
                try:
                    self.emergency_write({
                        "event": "terminal_shutdown_second_failure",
                        "run_id": self.run_id,
                        "error": str(exc2)[:300],
                        "note": "封口阶段第二失败;原失败事实不覆盖"})
                except Exception:
                    pass

    def _handle_fatal_exception(self, exc: Exception) -> None:
        """run 体内的致命异常统一收尾(§4.5:保护先于通知;第二失败
        不丢原失败、不递归再入一轮收尾)。

        顺序合同:crash 事实记录(emergency 同步兜底)→ 通知入队
        (异步,不阻塞保护)→ 统一终止收尾(停止/升级/核验/封口)。
        每段独立 try/except:任何一段再抛错都继续推进可独立执行的
        下一段,原始异常不被覆盖。"""
        import traceback
        tb = traceback.format_exc()
        try:
            self.log({"event": "supervisor_crash",
                      "error": str(exc), "traceback": tb[:4000]})
            self.emergency_write({"event": "supervisor_crash",
                                  "run_id": self.run_id,
                                  "error": str(exc)})
        except Exception:
            pass
        try:
            # 通知必须在 finalize(seal)之前入队(§5.3);stdout 尽力
            # 而为,stderr/emergency 同步兜底已有,信息不丢。
            self.stdout_line("R17ALERT", {
                "action": "open", "severity": "CRITICAL",
                "kind": "supervisor_crash",
                "detail": str(exc)[:300]})
        except Exception:
            pass
        # 统一收尾自身再失败:保留原失败,记录第二失败,不递归收尾
        try:
            self._terminal_shutdown(f"supervisor_crash:{exc}")
        except Exception as exc2:
            try:
                self.emergency_write({
                    "event": "fatal_shutdown_second_failure",
                    "run_id": self.run_id,
                    "error": str(exc2)[:300]})
            except Exception:
                pass

    def _cutoff_thread_premise(self) -> tuple[bool, str]:
        """WP1(SFB-01):截止点临界区的线程前提核验。

        "主线程屏蔽期间信号必然挂起、解除后 handler 才执行"只在一个
        条件下成立:进程内**所有**存活线程都屏蔽了 TERM/INT(S1:
        pthread_sigmask 每线程独立;任一未屏蔽线程收到进程级信号即
        tripped,Python handler 将在主线程下一字节码边界执行——与主
        线程掩码无关)。受控线程(r17-io-writer/r17-guest-sampler)在
        创建时经掩码继承终身屏蔽;本方法在临界区内(主线程已 block)
        读 /proc/self/task/*/status 逐线程核验 SigBlk,发现未屏蔽
        线程即前提失败(§4.2:能力/前提不可用不成功降级——保守语义
        由 finalize 的临界区后分支处理)。读 /proc 失败同样视为前提
        未证实(失败关闭,不误报前提成立)。
        """
        sig_bit = (1 << (signal.SIGTERM - 1)) | \
                  (1 << (signal.SIGINT - 1))
        try:
            task_dir = Path("/proc/self/task")
            tids = [p.name for p in task_dir.iterdir()]
        except OSError as exc:
            return False, f"proc_task_unreadable:{type(exc).__name__}"
        unshielded = []
        for tid in tids:
            try:
                text = (task_dir / tid / "status").read_text()
            except OSError:
                # 线程恰好退出:不再是信号投递候选,不算前提破坏
                continue
            for ln in text.splitlines():
                if ln.startswith("SigBlk:"):
                    try:
                        blk = int(ln.split(":", 1)[1].strip(), 16)
                    except ValueError:
                        return False, f"sigblk_parse_failed:{tid}"
                    if not (blk & sig_bit) == sig_bit:
                        unshielded.append(tid)
                    break
        if unshielded:
            return False, "unshielded_threads:" + ",".join(
                sorted(unshielded)[:8])
        return True, "all_threads_shielded"

    def _record_post_cutoff_signal(self) -> None:
        """C 之后到达的信号=截止后事件(§5.3):只追加到独立后置
        回执,不修改已被哈希固定的 summary/run_record。

        WP2(cutoff-closure):旧"有信号且未消费就算 C 后"的防御兜底
        已删除——C 的 sigmask 临界区保证:未消费的登记必然被临界区
        内的最后判定看到并消费(参与结果),不可能落到 C 之后还保持
        未消费。此处只承载真正的 C 后新到信号(count>base)。
        WP1(fc-integrity):前提失败时 C 未建立(_stop_cutoff_reached
        保持 False)——不生成本回执("C 后"无法证明,不硬写时间
        顺序);已登记停止事实由 summary/run_record 如实记录。
        """
        if not self._stop_cutoff_reached:
            return
        base = self._external_stop_count_at_cutoff
        if base is None or self._external_stop_sig_count <= base:
            return
        try:
            rec = {"schema": "r17-post-cutoff-signal-v1",
                   "run_id": self.run_id,
                   "utc": utc_now_iso(),
                   "sig_count_total": self._external_stop_sig_count,
                   "sig_count_at_cutoff": base,
                   "first_sig": self._external_stop_sig,
                   "note": "停止接受截止点 C 之后到达的信号;"
                           "结果已固定,本回执不改写任何封口原件"}
            (self.run_dir / "post_cutoff_signal.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError:
            self.emergency_write({
                "event": "post_cutoff_signal_write_failed",
                "run_id": self.run_id})

    def run(self) -> int:
        """注册信号 handler(只登记意图)并驱动 _run_body。

        RCF-02 修复:注册提前到 run() 最开头——旧位置在就绪屏障与
        准入之后,注册前窗口(含 supervisor_start 日志/屏障等待)的
        TERM/INT 以默认行为直接杀死进程,受控收尾/finalize 永不
        执行(已实测 exit=-15)。signal.signal 仅主线程可用,非主
        线程调用(测试形态)降级为不注册。

        WP1(unified-shutdown):致命异常在 run 体内统一收尾——直接
        调用 run() 与 CLI main() 获得同一任务清理保证(§4.1);handler
        由最外层责任域(main 的 token)覆盖到异常收尾完成。结束后
        记录 C 后事件回执并恢复 handler(不留给下一次调用/测试)。
        """
        self._external_stop_sig = None
        self._external_stop_consumed = False
        self._external_stop_sig_count = 0
        # WP1-B:收尾预算与停止状态同一重置面——每个 run() 一份;
        # 同一 run 内所有收尾入口共享(重复进入不重开,L01)。
        self._finalize_deadline = None
        self._finalize_budget_est_at = None
        self._finalize_budget_reason = None
        self._finalize_budget_notes = []
        self._shutdown_step_failures = {}
        # WP2-B/WP1:写者关闭状态/截止点前提/发布状态/控制失败事实
        # 同一重置面(每个 run 一份;直调面由 __init__ 初始化兜底)。
        self._guest_close_state = None
        self._win_close_state = None
        self._io_close_state = None
        self._guest_ever_started = False
        self._cutoff_premise_ok = None
        self._cutoff_premise_detail = None
        self._control_failures = []
        self._cutoff_certified = False
        self._summary_publish_failed = False
        self._summary_publish_failure = None
        self._run_record_publish_failed = False
        self._rr_candidate_entries = None
        token = self._install_signal_handlers()
        try:
            try:
                return self._run_body()
            except Exception as exc:  # 统一收尾(run 直调=CLI 同保证)
                self._handle_fatal_exception(exc)
                return 3
        finally:
            self._record_post_cutoff_signal()
            self._restore_signal_handlers(token)

    def _start_guest_sampler_shielded(self) -> None:
        """WP1(SFB-01):guest 采样线程从第一条指令起屏蔽 TERM/INT。

        新线程继承创建线程掩码:主线程先 block、再 start、再恢复——
        采样线程终身屏蔽,信号只经主线程 handler 登记路径处理(与
        BoundedIOWriter 同一机制;掩码能力不可用时记录事实,截止点
        前提核验如实消费)。
        WP2-A(fail-closed):start 即置 _guest_ever_started——三态
        生命周期(never_started/started_unconfirmed/confirmed_exited)
        的分界点;此后 None 引用不再能冒充"从未有过写者"。"""
        if self.guest_sampler is None:
            return
        old_mask = None
        try:
            old_mask = signal.pthread_sigmask(
                signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
        except (ValueError, OSError, AttributeError):
            self.log({"event": "guest_sampler_shield_unavailable",
                      "note": "pthread_sigmask 不可用:采样线程未屏蔽;"
                              "截止点前提核验将如实报告"})
            old_mask = None
        try:
            self.guest_sampler.start()
            self._guest_ever_started = True
        finally:
            if old_mask is not None:
                try:
                    signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
                except (ValueError, OSError):
                    pass

    def _run_body(self) -> int:
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
            # 外部停止在拒绝收尾窗口到达:零业务启动不变,停止事实
            # 记录,exit_code=4(非成功收尾)优先于拒绝码 2
            self._external_stop_early_window(
                "启动拒绝收尾期间收到外部停止:零业务启动;受控收尾")
            if self._external_stop_consumed:
                self.exit_code = 4
            self.finalize()
            return self.exit_code if self.exit_code else 2
        # 观测自动启动(WP1:不依赖手工开采样器)。replay(显式测试
        # 输入源,生产入口不暴露)不启动生产采样器、不创建
        # win_reader——样本由回放文件喂,live run 身份绑定不作用于
        # 回放输入(RSA-02:_declare_expected 同款 replay 判定,
        # telemetry_win 角色亦不登记)
        replay = self.args.samples_source.startswith("file:") if \
            self.args.samples_source else False
        win_started = False if replay else self.start_win_sampler()
        self.guest_sampler = GuestSampler(
            emit=lambda rec: self._emit_guest(rec), interval=5.0,
            detail_interval=30.0, run_id=self.run_id)
        # 样本回放模式(测试输入源):不启动线程,由文件喂样本
        replay_records = self._load_replay() if replay else []
        if not replay:
            self._start_guest_sampler_shielded()
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
            # 就绪屏障期间外部停止(handler 已注册):零业务启动不变,
            # 停止事实记录,exit_code=4 优先于 93
            self._external_stop_early_window(
                "就绪屏障期间收到外部停止:拒绝启动业务;受控收尾")
            self._shutdown_samplers_only()
            self.finalize()
            self.exit_code = 4 if self._external_stop_consumed else 93
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
            # 准入窗口外部停止:零业务启动不变,exit_code=4 优先于 94
            self._external_stop_early_window(
                "启动准入拒绝收尾期间收到外部停止:零业务启动;受控收尾")
            self._shutdown_samplers_only()
            self.finalize()
            self.exit_code = 4 if self._external_stop_consumed else 94
            return self.exit_code
        self.mark_stage("startup_admitted", admission_detail)
        # B4:spawn 前停止检查(handler 已在 run() 开头注册,窗口覆盖
        # supervisor_start/就绪屏障/准入全程)——先于业务启动=拒绝
        # 启动并收尾,零业务 spawn。
        if self._external_stop_sig is not None:
            self._external_stop_early_window(
                "停止请求先于业务启动:拒绝启动并收尾(零业务 spawn)")
            self._shutdown_samplers_only()
            self.finalize()
            self.exit_code = 4
            return self.exit_code
        self.mark_stage("business_spawn")
        self.spawn_business()
        # spawn 与登记衔接窗口补做停止(§5.3:不丢失该窗口里的信号;
        # handler 不再直接派发,由正常控制路径在此/主循环消费)
        if self._external_stop_sig is not None:
            self._consume_external_stop()
        max_s = self.policy["default_max_seconds"]
        last_budget_check = 0.0
        last_storage_check = 0.0
        last_poll_mono = time.monotonic()
        replay_idx = 0
        while True:
            mono = time.monotonic() - self.t0
            # ---- WP2(RCF-02):外部停止意图消费(正常控制路径) ----
            # handler 只登记;每轮节拍(1s;replay 0.05s)在此派发实际
            # 停止(PEP 475:sleep 被信号中断执行 handler 后恢复,不
            # 影响本轮消费)。粘性:只消费一次;重复信号不新建第二条
            # 停止链(request_stop 幂等/合作窗不重开)。
            if self._external_stop_sig is not None and \
                    not self._external_stop_consumed:
                self._consume_external_stop()
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
            # ---- 业务退出监控(WP2/§7.2:rc 观察与退出条件统一;
            # 同轮竞态下退出条件块的 poll 可能先看到退出——两处
            # 都经幂等观察方法,真实 rc 不得因 break 时序丢失) ----
            self._observe_business_exit()
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
            if biz_done:
                # 同轮竞态:此处 poll 先看到退出时,统一经幂等观察
                # 取得真实 rc(不能因 break 时序把 rc 丢成 None)
                self._observe_business_exit()
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
        保护中止/监护失败/残留未确认/证据不完整不得返回 0)。
        WP1(fc-integrity):控制能力失效(截止边界前提/掩码取得/还原
        无法证明)→7——run 非成功,不依赖是否碰巧收到信号;现有
        0/2/3/4/5/6/93/94 语义不变,7 为本轮新增的专用控制失败码
        (退出码表同步登记;summary/run_record.control_failures 是
        同一事实的记录面)。"""
        if self.exit_code:
            return self.exit_code  # 93 观测未就绪/94 准入不足/2 意图拒绝
        if self._control_failures:
            return 7  # 控制能力失效:停止归属无法认证/掩码面异常
        # 完成未证实(树仍在/身份不明)优先于"发生过保护"——残留
        # 风险是更强的"禁止下一重任务"信号(§7.2)
        if self.residual_unconfirmed:
            return 5
        if self._summary_publish_failed or \
                self._run_record_publish_failed:
            return 6  # WP1(P02):结果发布失败=无合法完成件,非成功
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
            # RSA-02:live 身份闭合(run_id+seq;与 reader 同款闸)——
            # 重复 seq/序号回退/早于 run 启动的 utc 不刷新有效快照
            # 与失联计时,判定面只消费同一验证结果
            ok, reason = validate_guest_sample(rec, run_id=self.run_id)
            if not ok:
                self.invalid_guest_samples += 1
                if len(self.invalid_guest_reasons) < 16:
                    self.invalid_guest_reasons.append(reason)
                return
            seq = rec.get("seq")
            if seq in self._guest_seen_seq:
                self.guest_duplicate_seq += 1
                return
            if self._guest_max_seq is not None and seq < self._guest_max_seq:
                self.guest_seq_regressions += 1
                return
            u = _parse_utc_iso(rec.get("utc"))
            if self._guest_predates_cutoff is not None and (
                    u is None or
                    u.timestamp() < self._guest_predates_cutoff):
                # 不可解析时间基线=不可信(与 win 侧 _predates_run
                # 同语义);早于本 run 启动-容差=旧日志重放
                self.guest_stale_replayed += 1
                return
            self._guest_seen_seq.add(seq)
            self._guest_max_seq = seq
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
        RSA-02 修复:sample 行的有效性**唯一**由 reader 的闸门
        (validate+seq 去重/回退+predates)决定,输出边界=reader.
        new_valid——本方法不再对 sample 行重做较弱校验(旧行为把
        reader 已拒的重复/回退/旧时间样本重新当"刚收到的有效
        数据"刷新失联计时,掩盖真实断流)。事件行(sampler_start/
        vol_missing 等)仍从 read_new 返回值处理。
        """
        if not self.win_reader:
            return None
        seen_start_pids: set[int] = set()
        win_latest: dict | None = None
        for line in self.win_reader.read_new():
            ev = line.get("event")
            if ev == "sample":
                # 有效性与拒绝计数都在 reader(同一验证结果);
                # 本分支仅显式跳过,防止未来在此重加弱校验
                continue
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
        # 判定输入/失联计时只消费 reader 的有效样本边界(RSA-02)
        for line in self.win_reader.new_valid:
            win_latest = line
            self.last_win_line_mono = mono
        # WP1(RCF-01):首次读取失败有界告警(只发一次,正常控制上下
        # 文——非 handler);事实与失联语义分离:读取失败不刷新有效
        # 时间,stale 从最后真实有效样本继续累计(15/30s 判定可达)
        if self.win_reader.read_failure_consecutive and \
                not self._win_read_failure_logged:
            self._win_read_failure_logged = True
            self.safe_log({
                "event": "win_read_failure",
                "op": self.win_reader.read_failure_last_op,
                "err": self.win_reader.read_failure_last_err,
                "consecutive": self.win_reader.read_failure_consecutive,
                "total": self.win_reader.read_failures,
                "note": "win 遥测读取失败:本次有效批次为空;失联计时"
                        "不被读取失败刷新(15/30s 判定继续累计)"})
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
            # WP2(RCF-02):屏障等待期间外部停止——提前退出(不睡满
            # 整个就绪窗口才处理停止意图);零业务启动语义由调用分支
            # 保证,detail 标记供 run() 区分 exit_code=4
            if self._external_stop_sig is not None:
                return False, "external_stop"
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
        """有效≠可开始重任务:就绪通过后再做工程资源准入(§4.2/§6)。

        WP3(result-seal)修复:按**必需依赖集合**(keyvol_required,
        从部署映射固定;不以样本里恰好出现哪些卷决定必需)逐项要求
        完整有效状态——缺记录/present=false/free unknown/身份不核
        实/必要输出不可写/存储用量 unknown 均拒绝(unknown≠安全);
        登记的应急备用卷(C:)缺失只降级记录不阻断;非必需卷(如 E)
        离线不产生任何阻断。零可用内存=有效但危险→同样拒绝。
        这是工程准入条件,不是课程 gate;不为了开始任务临时放宽。
        """
        sa = self.policy["startup_admission"]
        reasons: list[str] = []
        optional_degraded: list[str] = []
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
            # ---- 必需卷:每项完整有效状态(§6.2 表) ----
            vols = win.get("vols") or []
            by_vol: dict[str, dict] = {}
            for v in vols:
                if not isinstance(v, dict):
                    reasons.append("vol_record_invalid")
                    continue
                key = str(v.get("vol") or "").strip().upper()
                if not key:
                    reasons.append("vol_record_invalid:no_vol_key")
                    continue
                if key in by_vol:
                    # 必要卷重复/冲突记录:拒绝,不任选有利一条
                    reasons.append(f"vol_duplicate:{key}")
                    continue
                by_vol[key] = v
            for req in sa["keyvol_required"]:
                v = by_vol.get(req)
                if v is None:
                    reasons.append(f"required_vol_missing:{req}")
                    continue
                if not v.get("present"):
                    reasons.append(f"required_vol_absent:{req}")
                    continue
                free = v.get("free_gb")
                if not _finite_num(free):
                    reasons.append(f"required_vol_free_unknown:{req}")
                elif free < sa["keyvol_min_free_gib"]:
                    reasons.append(
                        f"keyvol_free {req} {free:.1f}GiB"
                        f"<{sa['keyvol_min_free_gib']}GiB")
                if v.get("identity_match") is not True:
                    reasons.append(
                        f"required_vol_identity_unverified:{req}")
            for opt in sa["keyvol_optional"]:
                v = by_vol.get(opt)
                if not isinstance(v, dict) or not v.get("present"):
                    # 登记的应急备用:如实降级,不擅自升级为阻断
                    optional_degraded.append(opt)
            # ---- 必要输出可写性(运行用户对实际必要目录;§6.1) ----
            # win 侧:遥测输出目录探针(ps1 首样本即带;unknown≠true)
            if win.get("telemetry_out_writable") is not True:
                reasons.append("telemetry_out_unwritable_or_unknown")
            # Linux 侧:本 run 目录探针(写自己的已登记测试文件后删)
            probe = self.run_dir / ".admission_probe"
            try:
                probe.write_text("probe", encoding="utf-8")
                probe.unlink()
            except OSError:
                reasons.append("run_dir_unwritable")
        gok, _ = validate_guest_sample(guest)
        if not gok:
            reasons.append("guest_sample_invalid")
        else:
            avail = guest["meminfo"]["MemAvailable"] / 1024 / 1024
            if avail < sa["guest_avail_min_gib"]:
                reasons.append(
                    f"guest_avail {avail:.1f}GiB"
                    f"<{sa['guest_avail_min_gib']}GiB")
        # ---- 时间基线(§6.3):旧日志重放不得通过 ----
        tol = sa["source_utc_tolerance_s"]
        for name, rec in (("win", win), ("guest", guest)):
            if not isinstance(rec, dict):
                continue
            u = _parse_utc_iso(rec.get("utc"))
            started = _parse_utc_iso(self._started_utc)
            if u is not None and started is not None and \
                    (started - u).total_seconds() > tol:
                reasons.append(f"{name}_sample_predates_run")
        # ---- Linux 根卷使用量:unknown=不可判定,拒绝(§6.2) ----
        try:
            used = self._storage_used_gib()
        except Exception:  # noqa: BLE001 —— 查询失败按不可判拒绝
            used = None
        if used is None:
            reasons.append("storage_unknown")
        elif used >= self.policy["storage"]["ceiling_gib"]:
            reasons.append(
                f"storage {used:.1f}GiB>=ceiling"
                f"{self.policy['storage']['ceiling_gib']}GiB")
        self.admission = {"ok": not reasons, "reasons": reasons,
                          "optional_degraded": optional_degraded,
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
        # WP1-B:正常路径进入收尾时建立本 run 预算;若已由异常路径
        # (_terminal_shutdown)或早拒绝(stop_win_sampler)建立,复用
        # 同一 deadline——从正常循环转入异常处理不重新开始窗口,
        # 重复调用不续期(§5.1)。
        self._ensure_finalize_budget("finalize")
        # WP2(stop-cutoff)检查点①(finalize 开始;原始流仍可写):
        # 收尾窗口已登记的停止意图在此消费——截止点 C 之前的停止
        # 属于本次 run,参与最终结果(§5.1)。
        if self._external_stop_sig is not None and \
                not self._external_stop_consumed:
            self._consume_external_stop()
        # 有限收尾窗:等 guest 采样线程最后一轮(只消费剩余预算)。
        # WP2-B(SFB-03):join 超时返回值恒为 None,不是结束证据——
        # join 后用 is_alive() 判真实退出;未确认退出时**保留句柄与
        # 身份**(不置 None 掩盖存活),关闭状态进 _guest_close_state
        # 供完整性判定消费(必要遥测流不进入完整证据);replay 模式
        # 线程未启动(ident is None)不 join,单独记录。
        if self.guest_sampler is not None:
            gs = self.guest_sampler
            gs.stop()
            started = gs.ident is not None
            if gs.is_alive():
                gs.join(timeout=self._bounded_wait(15.0, "guest_join"))
            alive_after = bool(gs.is_alive())
            self._guest_close_state = {
                "stop_requested": True, "started": started,
                "joined": not alive_after,
                "alive_after_join": alive_after,
                "thread_ident": gs.ident,
            }
            if alive_after:
                # 在途 emit 写动作不受 stop 标志取消;句柄保留,
                # 不强杀线程、不改 daemon 冒充关闭(S3)
                self.log({"event": "guest_sampler_stop_unconfirmed",
                          "thread_ident": gs.ident,
                          "budget_remaining_s":
                              round(self._finalize_remaining(), 3),
                          "note": "停止已请求、join 超时未确认退出;"
                                  "telemetry_guest 流不进入完整证据判定;"
                                  "句柄保留,不置 None"})
            else:
                self.guest_sampler = None
        self.stop_win_sampler()
        # 顺序合同:全部 alerts 写入(含 supervisor_end)必须先于
        # run_record 的哈希计算——否则清单记录与文件矛盾(build 拒绝)。
        # B2:alerts 经异步 I/O 线程落盘 → 写 supervisor_end 后**有界
        # drain**;写线程卡住时如实记 pending(不无限等,不假持久化)。
        # WP1-A:收尾内的日志递交属诊断依赖,非发布步骤——再次失败
        # 只隔离记录,封口(seal/summary/run_record)继续(§4.1 表行5:
        # 诊断失败不弃可执行的清理;发布失败不签完整交付是另一事实)。
        if self.protector and self.protector.pending_logs:
            self._shutdown_step("flush_logs", self.protector.flush_logs)
        self.log({"event": "supervisor_end",
                  "incidents": len(self.incidents),
                  "business_rc": self.biz_rc})
        # 递交通知(独立后置位置;stdout 非交付文件)在封口**之前**
        # 入队:通知内容只引用确定路径(run_record/summary 路径在
        # 运行前即固定),不承诺"已写完"——它属于本批待完成动作,
        # 由随后的 drain 覆盖;管道写满只卡写线程,drain 超时如实
        # 计未确认(§5.3)。
        self.stdout_line("R17LOG", {"event": "supervisor_end",
                                    "run_dir": str(self.run_dir),
                                    "incidents": len(self.incidents),
                                    "business_rc": self.biz_rc,
                                    "summary": str(self.run_dir /
                                                   "summary.json"),
                                    "run_record": str(self.run_dir /
                                                      "run_record.json")})
        # WP2(stop-cutoff)检查点②(seal 前;原始流最后可写位置):
        # 上一检查点与 seal 之间(采样器停止/drain 前通知递交)到达
        # 的意图仍可走完整消费链。
        if self._external_stop_sig is not None and \
                not self._external_stop_consumed:
            self._consume_external_stop()
        # §5.3 分批封口(RSA-01:事前封口边界):producer 已停、最后
        # 一条 alerts/退出通知已入队——**先 seal**(此后任何新 submit
        # 被拒,不进入本批),**再 drain(15)** 确认已接受动作全部
        # 成功完成。只有封口+清空之后的 io 状态才是终态:哈希/
        # summary/run_record 消费终态计数,run_record 内嵌 io 即
        # 最终封口态(修复"写入时点态"勘误)。
        self.iow.seal()
        self._io_drain_unconfirmed = self.iow.drain(
            self._bounded_wait(15.0, "io_drain"))
        # WP2(stop-cutoff)检查点③(seal 后、临界区前):原始流已
        # 封口,不能为补一条日志解封——结果层消费(§5.3:截止点前
        # late-stop 由尚未发布的收尾元数据记录)。
        self._consume_external_stop_sealed()
        # WP2-B(SFB-03)/WP1:写线程可验证关闭(哨兵+有界 join)——
        # alerts 流的最终写入者退出确认;未确认时保留线程事实
        # (_io_close_state.alive_after=True),完整性判定据此拒绝
        # 完整证据(§6.5:证据已静止≠写者已关闭,两维度分别记录)。
        io_joined = self.iow.close(
            self._bounded_wait(5.0, "io_writer_join"))
        self._io_close_state = {
            "close_requested": True, "joined": io_joined,
            "alive_after": not io_joined,
            "thread_shielded": getattr(self.iow, "thread_shielded", False)}
        if not io_joined:
            self.log({"event": "io_writer_stop_unconfirmed",
                      "budget_remaining_s":
                          round(self._finalize_remaining(), 3),
                      "note": "哨兵已发、join 超时未确认退出;alerts 流"
                              "不进入完整证据判定"})
        # WP1(publication/SFB-01):C 前私有候选——必需角色哈希在各自
        # 写者关闭确认之后计算(§7.2 顺序合同)并缓存为私有候选;
        # summary 角色发布时序在 run_record 之前,发布时现算。候选
        # 不是完成件:此时刻权威路径上不存在 finalized=true 的
        # run_record,也不存在已公开的 summary(§4.3/P01)。
        self._rr_candidate_entries, _cand_missing = \
            self._prepare_run_record_entries()
        # WP2(stop-cutoff):停止决策边界 C——pthread_sigmask 临界区
        # 关闭"最后检查已判定、C 尚未建立"的登记窗口(§6.2)。
        # 顺序合同:[核验线程前提+屏蔽 TERM/INT] → 最后判定(有意向
        # 未消费→结果层消费,纯内存赋值) → C 两赋值 → [解除屏蔽]。
        # 边界保证的前提(SFB-01 修复):受控线程(r17-io-writer/
        # r17-guest-sampler)创建时经掩码继承终身屏蔽 TERM/INT,临界
        # 区内经 _cutoff_thread_premise 逐线程核验 SigBlk——"主线程
        # 屏蔽期间信号挂起、解除后 handler 才执行"只在全部线程屏蔽
        # 时成立(任一未屏蔽线程可 tripped 信号,Python handler 将在
        # 主线程下一字节码边界执行,与主线程掩码无关;S1/signal(7))。
        # WP1(fc-integrity,SPSC-01):前提不能证明时**不建立已认证
        # C**——旧"解除后 sleep(0.05) 保守复核再移动基线"分支已
        # 删除(固定延时给不出"之后不会再登记"的机制保证,S1);能力
        # 失效登记为控制失败(run 非成功,rc=7;停止归属如实记为
        # 无法认证,不伪造成功 C,也不把未知归属硬写成时间顺序)。
        # 临界边界内零 I/O、零进程等待、零普通锁(S1);/proc 逐线程
        # 读为前提核验的最小能力面,失败按前提未证实处理(失败关闭)。
        old_mask = None
        try:
            old_mask = signal.pthread_sigmask(
                signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
        except (ValueError, OSError) as exc:
            # 平台不支持(非主线程/无 sigmask 面):如实记录;与前提
            # 失败同等处理(不能宣称挂起边界成立,run 非成功)
            self.log({"event": "cutoff_mask_unavailable",
                      "error": str(exc)[:200],
                      "note": "pthread_sigmask 边界不可用;挂起边界"
                              "不成立,按控制能力失效处理"})
            self._cutoff_premise_ok = False
            self._cutoff_premise_detail = f"mask_unavailable:{exc}"[:120]
        if old_mask is not None:
            # 前提核验(此时主线程已 block;受控线程应经掩码继承处于
            # 屏蔽态)——逐线程核验 SigBlk,任何未屏蔽存活线程即失败
            self._cutoff_premise_ok, self._cutoff_premise_detail = \
                self._cutoff_thread_premise()
        if not self._cutoff_premise_ok:
            self.log({"event": "cutoff_thread_premise_failed",
                      "detail": self._cutoff_premise_detail,
                      "note": "存在未屏蔽 TERM/INT 的存活线程(或核验"
                              "不可用):挂起边界不成立;本 run 停止归属"
                              "无法认证,登记控制能力失效(run 非成功,"
                              "不伪造成功 C)"})
            self._control_failures.append({
                "kind": "cutoff_capability_unavailable",
                "detail": self._cutoff_premise_detail,
                "external_stop_sig": self._external_stop_sig,
                "external_stop_sig_count":
                    self._external_stop_sig_count,
                "note": "截止点边界的线程前提无法证明;停止归属"
                        "无法认证,run 按控制失败终结"})
        # 最后判定与 C 只在前提成立时建立(已认证 C);前提失败时
        # 已登记的停止事实保持原样进入结果层(summary/record 如实
        # 记录 sig/consumed 状态),不消费、不生成 post_cutoff 回执
        # (无法证明 C 后),也不再以任何固定延时复核。
        if self._cutoff_premise_ok:
            if self._external_stop_sig is not None and \
                    not self._external_stop_consumed:
                self._consume_external_stop_sealed()
            # WP2:C 越过——run 的取消接受关闭。前置条件已在本方法
            # 顺序内成立:任务树核验/producer 停止/seal+drain/写者
            # 关闭/原始内容候选固定。
            self._external_stop_count_at_cutoff = \
                self._external_stop_sig_count
            self._stop_cutoff_reached = True
            self._cutoff_certified = True
        if old_mask is not None:
            try:
                # 解除屏蔽:待决信号立即递送(全线程屏蔽前提成立时,
                # handler 登记必然发生在 C 之后,count>base → 后置
                # 回执,不参与已固定结果)。
                signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
            except (ValueError, OSError) as exc:
                # 还原失败不得静默吞成"已恢复"(C02):如实登记控制
                # 失败——即使 C 已建立,掩码面残留异常仍是非成功
                self.log({"event": "cutoff_mask_restore_failed",
                          "error": str(exc)[:200],
                          "note": "sigmask 还原失败:信号面状态异常,"
                                  "登记控制失败(run 非成功)"})
                self._control_failures.append({
                    "kind": "cutoff_mask_restore_failed",
                    "detail": f"{type(exc).__name__}:{exc}"[:160],
                    "note": "临界区屏蔽未确认恢复;run 按控制失败"
                            "终结"})
        # WP1(publication):对外发布只在停止决定之后——同一决定、
        # 单次发布:先 summary(其哈希被 run_record 引用),后 run_record
        # (完成判据)。C 前不存在对外完成件;发布失败=run 非成功
        # (control_outcome→6;无合法完成记录或明确的非成功/不完整
        # 终结证据),不沿用旧文件、不回改 C 决策、不重试覆写(§4.3)。
        # summary 发布失败仍发布 run_record(summary 条目 missing →
        # evidence_complete=false,作为明确的非成功终结证据)。
        self.write_summary()
        self.finalize_run_record()


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
    # WP1(unified-shutdown):handler 由最外层责任域(main)持有,
    # 覆盖 sup.run() 内部安装、其异常统一收尾与 finalize 全程;
    # run() 自身再装一层(嵌套 token)保证直调场景同样受保护。
    token = sup._install_signal_handlers()
    try:
        return sup.run()
    except Exception:  # run 自身收尾失败的最后防线(§4.5)
        import traceback
        tb = traceback.format_exc()
        try:
            sup.emergency_write({"event": "supervisor_outer_crash",
                                 "run_id": sup.run_id,
                                 "traceback": tb[:4000]})
            sup.finalize()
        except Exception:
            pass
        return 3
    finally:
        sup._restore_signal_handlers(token)


if __name__ == "__main__":
    sys.exit(main())
