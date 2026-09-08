#!/usr/bin/env python3
"""资源复算:从已关闭的原始遥测流重算,与在线 summary 对比。

口径(WP 上轮约定一致):
- guest MemAvailable 最低值(有效样本;kB→GiB)
- win phys_avail 最低 / commit 峰值百分比(有效样本)
- 任务树 RSS 同刻求和峰值(诊断口径,非去重物理占用)
- 采样器自身 RSS/CPU(收尾样本)
未测到的值输出 unavailable,不写 0。
"""
import json
import sys
from pathlib import Path


def valid_win(obj):
    if not isinstance(obj, dict) or obj.get("event") != "sample":
        return False
    perf = obj.get("perf")
    if not isinstance(perf, dict):
        return False
    need = ("phys_avail_gb", "phys_total_gb",
            "commit_total_gb", "commit_limit_gb")
    for k in need:
        v = perf.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return False
    if perf["phys_total_gb"] <= 0 or perf["commit_limit_gb"] <= 0:
        return False
    return True


def main(run_dir: str) -> int:
    d = Path(run_dir)
    guest = d / "telemetry" / "guest_samples.jsonl"
    win = d / "telemetry" / "win_samples.jsonl"
    summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    out: dict = {"run_dir": str(d)}

    guest_min_avail = None
    tree_peak = None
    sampler_rss = None
    if guest.is_file():
        for line in guest.read_text(encoding="utf-8").splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("event") != "guest_sample":
                continue
            mi = o.get("meminfo") or {}
            ma = mi.get("MemAvailable")
            if isinstance(ma, (int, float)) and not isinstance(ma, bool):
                gib = ma / 1024 / 1024
                if guest_min_avail is None or gib < guest_min_avail:
                    guest_min_avail = round(gib, 3)
            rss = o.get("tasks_total_rss_kb")
            if isinstance(rss, (int, float)) and not isinstance(rss, bool):
                gib = rss / 1024 / 1024
                if tree_peak is None or gib > tree_peak:
                    tree_peak = round(gib, 3)
            sr = o.get("sampler_self_rss_kb")
            if isinstance(sr, (int, float)) and not isinstance(sr, bool):
                sampler_rss = round(sr / 1024, 1)
    out["guest_memavail_min_gib_recomputed"] = \
        guest_min_avail if guest_min_avail is not None else "unavailable"
    out["task_tree_rss_sum_peak_gib_recomputed"] = \
        tree_peak if tree_peak is not None else "unavailable"
    out["sampler_self_rss_mb_last"] = \
        sampler_rss if sampler_rss is not None else "unavailable"

    win_free_min = None
    commit_max = None
    if win.is_file():
        for line in win.read_text(encoding="utf-8").splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not valid_win(o):
                continue
            perf = o["perf"]
            if win_free_min is None or \
                    perf["phys_avail_gb"] < win_free_min:
                win_free_min = perf["phys_avail_gb"]
            pct = 100.0 * perf["commit_total_gb"] / perf["commit_limit_gb"]
            if commit_max is None or pct > commit_max:
                commit_max = round(pct, 2)
    out["win_free_phys_min_gib_recomputed"] = \
        round(win_free_min, 3) if win_free_min is not None else "unavailable"
    out["win_commit_max_pct_recomputed"] = \
        commit_max if commit_max is not None else "unavailable"

    peaks = summary.get("peaks") or {}
    out["summary_peaks_for_crosscheck"] = {
        "guest_memavail_min_gib": peaks.get("guest_memavail_min_gib",
                                            "unavailable"),
        "win_free_phys_min_gib": peaks.get("win_free_phys_min_gib",
                                           "unavailable"),
        "win_commit_max_pct": peaks.get("win_commit_max_pct",
                                        "unavailable"),
        "task_tree_rss_max_gib": peaks.get("task_tree_rss_max_gib",
                                           "unavailable"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
