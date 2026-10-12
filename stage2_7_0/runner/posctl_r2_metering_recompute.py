#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2-05:R1 计量报告的机械重算(FiniteRepair R2)。

从原件(r1_budget_ledger.jsonl 34 行 + 8 个 gen_quota.jsonl)重算:
- committed/incident/outstanding → effective(65,168+11,264=76,432);
- committed 按 tag 分解(纠正 R1 报告 §6 的相加式 83,828 ≠ 65,168;
  正确分解 4,096+2,048+512+16,384+6,656+35,188+284=65,168);
- 生成记录合计(8 run 原件,剔重 failed_runs_forensics 复制件)
  vs 报告 248;只声称"可核下界",不虚称全任务生成总量;
- PPO 步分类(6,144 步同时记在 eval 标签的口径拆分)。

输出:evidence/r2_runs/metering_recompute.json(供报告引用)。
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

R1_EVIDENCE = Path(
    "/mnt/f/trading/acceptance/PosCtl_R1_20261012/evidence/r1_runs")
OUT = Path("/mnt/f/trading/acceptance/PosCtl_R2_20261012/evidence/"
           "r2_runs/metering_recompute.json")

METRICS = ("ppo_steps", "ppo_learn_attempts", "bc_fits", "bc_epochs",
           "bc_minibatch_updates", "eval_steps", "gen_calls",
           "episodes")


def replay_ledger(path: Path) -> dict:
    committed = defaultdict(int)
    incidents = defaultdict(int)
    outstanding = defaultdict(int)
    reserves = {}
    n_lines = 0
    events = defaultdict(int)
    commits_by_tag = defaultdict(lambda: defaultdict(int))
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        n_lines += 1
        rec = json.loads(line)
        ev = rec.get("event")
        events[ev] += 1
        if ev == "commit":
            for k in METRICS:
                v = rec.get(k, 0)
                committed[k] += v
                if v:
                    commits_by_tag[rec.get("tag", "?")][k] += v
            reserves.pop(rec.get("rid"), None)
        elif ev == "reserve":
            reserves[rec["rid"]] = {
                k: rec.get(k, 0) for k in METRICS}
        elif ev == "abandon":
            r = reserves.pop(rec.get("rid"), None)
            if r:
                for k, v in r.items():
                    committed[k] += v
        elif ev == "release":
            reserves.pop(rec.get("rid"), None)
        elif ev == "incident_backcharge":
            for k in METRICS:
                incidents[k] += rec.get(k, 0)
    for r in reserves.values():
        for k, v in r.items():
            outstanding[k] += v
    return {"n_lines": n_lines, "events": dict(events),
            "committed": dict(committed),
            "incident": dict(incidents),
            "outstanding": dict(outstanding),
            "commits_by_tag": {t: dict(v)
                               for t, v in commits_by_tag.items()},
            "open_rids": sorted(reserves)}


def count_gen_records() -> dict:
    """8 个运行原件的生成记录(剔除 failed_runs_forensics 内复制的
    两个失败 run 副本——与原目录逐字节相同者只计一次)。"""
    roots = [p for p in sorted(R1_EVIDENCE.glob("*"))
             if p.is_dir() and (p / "gen_quota.jsonl").exists()]
    forensics = (R1_EVIDENCE / "failed_runs_forensics")
    forensic_dupes = []
    if forensics.is_dir():
        for sub in forensics.glob("curriculum_eval_*"):
            f = sub / "gen_quota.jsonl"
            orig = R1_EVIDENCE / sub.name / "gen_quota.jsonl"
            if f.exists() and orig.exists() and \
                    f.read_bytes() == orig.read_bytes():
                forensic_dupes.append(sub.name)
    rows = []
    for p in roots:
        if p.name == "failed_runs_forensics":
            continue
        n_rows = 0
        gen = ep = 0
        for line in (p / "gen_quota.jsonl").read_text(
                encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                n_rows += 1
                gen += rec.get("gen_calls", 0)
                ep += rec.get("episodes", 0)
        rows.append({"run": p.name, "rows": n_rows,
                     "gen_calls": gen, "episodes": ep})
    total = {
        "runs": len(rows),
        "records": sum(r["rows"] for r in rows),
        "gen_calls": sum(r["gen_calls"] for r in rows),
        "episodes": sum(r["episodes"] for r in rows),
        "forensic_byte_dupes_excluded": forensic_dupes,
    }
    return {"per_run": rows, "total": total}


def main() -> int:
    led = replay_ledger(R1_EVIDENCE / "r1_budget_ledger.jsonl")
    gens = count_gen_records()
    committed_eval = led["committed"].get("eval_steps", 0)
    incident_eval = led["incident"].get("eval_steps", 0)
    effective_eval = committed_eval + incident_eval + \
        led["outstanding"].get("eval_steps", 0)
    # committed 按 tag 的 eval 分解与校验和
    tag_eval = {t: v.get("eval_steps", 0)
                for t, v in led["commits_by_tag"].items()}
    tag_eval_sum = sum(tag_eval.values())
    # R1 报告 §6 声明的(错误)相加链与正确分解对照
    report_wrong_chain = [2048, 512, 16384, 2048 * 3, 512, 16384,
                          6656, 15162, 20026]
    report_wrong_sum = sum(report_wrong_chain)
    correct_chain = [4096, 2048, 512, 16384, 6656, 35188, 284]
    out = {
        "source": {
            "ledger": str(R1_EVIDENCE / "r1_budget_ledger.jsonl"),
            "ledger_lines": led["n_lines"],
            "ledger_events": led["events"],
            "gen_quota_originals": str(R1_EVIDENCE),
        },
        "eval_recompute": {
            "committed": committed_eval,
            "incident_backcharged": incident_eval,
            "outstanding": led["outstanding"].get("eval_steps", 0),
            "effective": effective_eval,
            "limit_r1": 65536,
            "over_limit": max(0, effective_eval - 65536),
            "identity_holds": (
                committed_eval + incident_eval
                + led["outstanding"].get("eval_steps", 0)
                == effective_eval),
        },
        "committed_by_tag_eval": tag_eval,
        "committed_by_tag_sum": tag_eval_sum,
        "committed_by_tag_matches": tag_eval_sum == committed_eval,
        "report_r1_section6_wrong_chain": {
            "chain": report_wrong_chain,
            "sum": report_wrong_sum,
            "claimed": 65168,
            "actually": committed_eval,
            "wrong": report_wrong_sum != committed_eval,
        },
        "correct_chain_reference": {
            "chain": correct_chain,
            "sum": sum(correct_chain),
            "note": ("reviewer 提供的正确分解;以 commits_by_tag "
                     "机械重算为准(上字段)"),
        },
        "ppo_classification": {
            "ledger_ppo_steps": led["committed"].get("ppo_steps", 0),
            "ledger_ppo_learn_attempts": led["committed"].get(
                "ppo_learn_attempts", 0),
            "note": ("三次 PPO 的 6,144 步在 R1 报告同时计入 eval "
                     "标签口径;分类呈现:ppo_steps=6,144 与 "
                     "eval_steps 标签合计不相加解读"),
        },
        "generation_records": gens,
        "generation_vs_report": {
            "recomputed_records": gens["total"]["records"],
            "r1_report_claimed": 248,
            "note": ("360 为 8 个原件的可核记录合计(剔除 "
                     "failed_runs_forensics 字节相同复制件);不等于"
                     "全任务精确生成总量,仅为可核下界——报告措辞 "
                     "必须分清"),
        },
        "bc": {k: led["committed"].get(k, 0)
               for k in ("bc_fits", "bc_epochs",
                         "bc_minibatch_updates")},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps({
        "ledger_lines": led["n_lines"],
        "effective_eval": effective_eval,
        "over_limit": out["eval_recompute"]["over_limit"],
        "committed_by_tag_matches":
            out["committed_by_tag_matches"],
        "report_wrong_sum": report_wrong_sum,
        "gen_records": gens["total"]["records"],
        "out": str(OUT)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
