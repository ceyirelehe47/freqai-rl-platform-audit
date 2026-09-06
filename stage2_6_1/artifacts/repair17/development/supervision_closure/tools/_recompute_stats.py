#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从关闭的原始遥测重算 summary 口径指标,与在线 summary 交叉核对。

只读;输入=run 目录;输出=stdout JSON(报告 §8 数据源)。
"""
import json
import sys
from pathlib import Path

rd = Path(sys.argv[1])
g = [json.loads(l) for l in
     (rd / "telemetry" / "guest_samples.jsonl").read_text(
         encoding="utf-8").splitlines() if l.strip()]
w = [json.loads(l) for l in
     (rd / "telemetry" / "win_samples.jsonl").read_text(
         encoding="utf-8").splitlines() if l.strip()]
g_samples = [r for r in g if r.get("event") == "guest_sample"]
w_samples = [r for r in w if r.get("event") == "sample"]


def fmin(seq, key):
    vals = [key(r) for r in seq if isinstance(key(r), (int, float))]
    return min(vals) if vals else None


def fmax(seq, key):
    vals = [key(r) for r in seq if isinstance(key(r), (int, float))]
    return max(vals) if vals else None


recomputed = {
    "guest_n": len(g_samples),
    "win_n": len(w_samples),
    "guest_memavail_min_gib": fmin(
        g_samples, lambda r: r.get("meminfo", {}).get("MemAvailable", 0)
        / 1024 / 1024 if isinstance(r.get("meminfo"), dict) else None),
    "win_free_phys_min_gib": fmin(
        w_samples, lambda r: (r.get("perf") or {}).get("phys_avail_gb")),
    "win_commit_max_pct": fmax(
        w_samples, lambda r: round(100.0 *
        (r.get("perf") or {}).get("commit_total_gb", 0) /
        max((r.get("perf") or {}).get("commit_limit_gb", 1e-9), 1e-9), 2)
        if isinstance((r.get("perf") or {}).get("commit_total_gb"),
                      (int, float)) else None),
    "task_tree_rss_max_gib": fmax(
        g_samples, lambda r: (r.get("tasks_total_rss_kb") or 0)
        / 1024 / 1024),
    "sampler_self_rss_max_kb": fmax(
        g_samples, lambda r: r.get("sampler_self_rss_kb")),
    "sampler_cpu_pct_max": fmax(
        g_samples, lambda r: r.get("sampler_cpu_pct")),
    "samples_with_task_tree": sum(
        1 for r in g_samples if r.get("tasks_total_rss_kb")),
}
summary = json.loads((rd / "summary.json").read_text(encoding="utf-8"))
peaks = summary.get("peaks", {})
cross = {}
for k, v in recomputed.items():
    if k in peaks and isinstance(v, (int, float)):
        cross[k] = {"recomputed": round(v, 4),
                    "summary": peaks[k],
                    "match": abs(v - peaks[k]) < 0.01}
print(json.dumps({
    "recomputed": {k: (round(v, 4) if isinstance(v, float) else v)
                   for k, v in recomputed.items()},
    "summary_peaks": peaks,
    "cross_check": cross,
    "coverage": summary.get("coverage"),
    "telemetry_bytes": summary.get("telemetry_bytes"),
    "duration_note": "5s 采样峰值非严格峰值;RSS 求和非去重物理占用",
}, ensure_ascii=False, indent=1))
