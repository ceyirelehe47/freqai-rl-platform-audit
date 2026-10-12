#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2 生成重复计量 54 的原始行绑定与算术说明(FiniteRepair R3-01)。

只读分析,不改写 R2 账本/来源日志任何字节。输出:
- R2 任务账本中,总预约 commit 行(smoke×2 + eval×1)与逐叶
  QuotaLedger commit 行对**同一批生成动作**的重复入账绑定
  (行号/事件/tag/rid/金额);
- 各 run 的来源日志(gen_quota.jsonl)叶级真实调用数;
- 算术:54 = smoke 6 + smoke 6 + eval 42(总账重复计入的生成数),
  704 为账本记录值而非去重值;704−54=650 只是已定位重复的机械
  扣重,不是已证明的去重总量,也不构成额度返还。

用法:python posctl_r3_metering_note.py \
        --ledger <r2_task_ledger.jsonl> \
        --runs-root <posctl_r2_runs> \
        --out <r3_metering_note.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _read_lines(path: Path):
    """逐行读取 JSONL,返回 [(line_no_1based, byte_offset, rec)]。"""
    out = []
    off = 0
    with path.open("rb") as fh:
        for i, raw in enumerate(fh, start=1):
            out.append((i, off, raw))
            off += len(raw)
    return [(i, o, json.loads(r.decode("utf-8")))
            for i, o, r in out if r.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True,
                    help="R2 任务账本 jsonl(只读)")
    ap.add_argument("--runs-root", required=True,
                    help="R2 运行根(含 smoke_*/curriculum_eval_*)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    ledger = Path(args.ledger)
    runs_root = Path(args.runs_root)

    events = _read_lines(ledger)
    total_reserve_commits = []      # 总预约结清行(runner 级)
    leaf_commits = []               # 叶级 reserve→commit(QuotaLedger)
    for ln, off, rec in events:
        ev = rec.get("event")
        tag = str(rec.get("tag", ""))
        if ev == "commit":
            gen = int(rec.get("gen_calls", 0)
                      or (rec.get("amounts") or {}).get(
                          "gen_calls", 0))
            if tag.startswith("posctl_r2_smoke_gen"):
                total_reserve_commits.append(
                    ("smoke_total", ln, off, rec.get("rid"),
                     tag, gen))
            elif tag == "posctl_r2_eval":
                total_reserve_commits.append(
                    ("eval_total", ln, off, rec.get("rid"),
                     tag, gen))
            elif tag.startswith("gen:"):
                leaf_commits.append(
                    ("leaf", ln, off, rec.get("rid"), tag, gen))
    dup_total = sum(g for _, _, _, _, _, g in total_reserve_commits)
    leaf_total = sum(g for _, _, _, _, _, g in leaf_commits)

    # 各 run 来源日志的叶级真实调用数(独立于任务账本)
    runs = []
    for d in sorted(runs_root.glob("smoke_*")) + sorted(
            runs_root.glob("curriculum_eval_*")):
        q = d / "gen_quota.jsonl"
        if not q.exists():
            continue
        calls = episodes = 0
        grant_rows = leaf_rows = 0
        for _, _, rec in _read_lines(q):
            calls += int(rec.get("gen_calls", 0))
            episodes += int(rec.get("episodes", 0))
            if rec.get("grant_rid"):
                grant_rows += 1
            elif rec.get("task_reserve_tag", "").startswith("gen"):
                leaf_rows += 1
        runs.append({"run_dir": d.name, "gen_calls": calls,
                     "episodes": episodes,
                     "journal_rows": grant_rows + leaf_rows})

    committed_gen = 0
    for _, _, rec in events:
        if rec.get("event") == "commit":
            committed_gen += int(
                rec.get("gen_calls", 0)
                or (rec.get("amounts") or {}).get(
                    "gen_calls", 0))
    note = {
        "boundary": ("只读分析;R2 账本与来源日志原字节不动;"
                     "本说明不构成额度返还,不覆盖旧账"),
        "ledger": str(ledger),
        "ledger_sha256_hint": "见回执/清单,本工具不改写任何原件",
        "total_reservation_settle_rows": [
            {"kind": k, "line": ln, "byte_offset": off,
             "rid": rid, "tag": tag, "gen_calls": g}
            for k, ln, off, rid, tag, g in total_reserve_commits],
        "leaf_level_commit_rows_count": len(leaf_commits),
        "leaf_level_commit_gen_total": leaf_total,
        "duplicate_gen_in_total_ledger": dup_total,
        "arithmetic": {
            "smoke_x2_plus_eval": [g for _, _, _, _, _, g
                                   in total_reserve_commits],
            "sum": dup_total,
            "expected": 54,
            "match": dup_total == 54,
        },
        "runs_journal": runs,
        "interpretation": (
            "R2 实现里总预约 commit 与 QuotaLedger 逐叶 commit 对"
            "同一批生成各记一次:任务账本 gen=704 是双计口径的记录"
            "值;其中 54(=6+6+42)可由原始行机械定位为重复。"
            "704−54=650 只是已定位重复的扣重,不证明全部消耗已观测,"
            "不自动返还/解锁历史额度。R3 起总预约=授权 grant,叶级"
            "draw 划拨,一次动作只记一次。"),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(note, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps(
        {"duplicate_total": dup_total,
         "expected": 54, "match": dup_total == 54,
         "leaf_rows": len(leaf_commits),
         "ledger_committed_gen": committed_gen,
         "out": str(out)},
        ensure_ascii=False, indent=1))
    return 0 if dup_total == 54 else 1


if __name__ == "__main__":
    raise SystemExit(main())
