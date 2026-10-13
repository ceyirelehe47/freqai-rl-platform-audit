#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 BC 诊断(BC-A 人工映射 + BC-B 同信息教师;各 2 臂×3 seed)。

前置:B 基础表示检查(psc_p0_repr.py b_precondition_pass)通过;
BC-B 需要 H=64 DP 参考(数学求解,非 env 步)。主 PPO 全新初始化,
不继承 BC 权重(证明:分域 seed + 独立记录)。

用法:
    python psc_p0_bc.py [--ledger <jsonl>] [--out <dir>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import torch as th

from rl_posctl.curriculum import reference_policy
from rl_posctl.runlog import RunLog, write_rejection  # noqa: E402
from rl_posctl.skill_p0 import p0bc  # noqa: E402
from rl_posctl.skill_p0.p0run import (  # noqa: E402
    RUNS_DIR, evidence_kib_settle, make_sampler_meter, open_ledger)
from rl_posctl.skill_p0.p0spec import (  # noqa: E402
    ARMS, BC_SEEDS, c1_spec)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--out", default=str(RUNS_DIR / "bc"))
    args = ap.parse_args()
    th.set_num_threads(1)
    out_root = Path(args.out)
    gate_path = out_root / "bc_report.json"
    if gate_path.exists():
        print(f"已有 bc_report.json:{gate_path}", file=sys.stderr)
        return 2
    repr_report = RUNS_DIR / "repr" / "repr_report.json"
    if not repr_report.exists():
        write_rejection(out_root, "psc_p0_bc",
                        f"缺少表示检查报告:{repr_report}", sys.argv)
        return 2
    repr_rec = json.loads(repr_report.read_text(encoding="utf-8"))
    if not repr_rec.get("b_precondition_pass"):
        write_rejection(
            out_root, "psc_p0_bc",
            "B 基础表示检查未通过(分布正确性/浓度门),"
            "按计划不开 BC/主 PPO;交付诊断", sys.argv)
        return 3
    ledger = open_ledger(args.ledger)
    meter = make_sampler_meter(ledger, "bc")
    report = {"fits": []}
    with RunLog(out_root, meta_extra={"runner": "psc_p0_bc"}):
        tables_a = p0bc.build_bc_a_tables()
        # 监督输入行:表构建一次性计量(去重;重用表不再计)
        rid = ledger.reserve("bc_rows:bc_a", supervised_rows=(
            len(tables_a["train"]["kinds"])
            + len(tables_a["val"]["kinds"])))
        ledger.commit(rid, "bc_rows:bc_a", supervised_rows=(
            len(tables_a["train"]["kinds"])
            + len(tables_a["val"]["kinds"])))
        spec = c1_spec("prequal", 0)
        ref = reference_policy(spec)
        tables_b = p0bc.build_bc_b_tables(ref)
        rid = ledger.reserve("bc_rows:bc_b", supervised_rows=(
            len(tables_b["train"]["kinds"])
            + len(tables_b["val"]["kinds"])))
        ledger.commit(rid, "bc_rows:bc_b", supervised_rows=(
            len(tables_b["train"]["kinds"])
            + len(tables_b["val"]["kinds"])))
        for arm in ARMS:
            for seed in BC_SEEDS:
                rec = p0bc.bc_fit(
                    arm=arm, seed=seed, tables=tables_a,
                    out_dir=out_root, ledger=ledger,
                    tag="bc_a", sampler_meter=meter)
                report["fits"].append(rec)
                print(f"BC-A {arm} {seed}: pass={rec['pass']}")
        for arm in ARMS:
            for seed in BC_SEEDS:
                rec = p0bc.bc_fit(
                    arm=arm, seed=seed, tables=tables_b,
                    out_dir=out_root, ledger=ledger,
                    tag="bc_b", sampler_meter=meter)
                report["fits"].append(rec)
                print(f"BC-B {arm} {seed}: pass={rec['pass']}")
        summary = {}
        for tag in ("bc_a", "bc_b"):
            for arm in ARMS:
                sel = [f for f in report["fits"]
                       if f["arm"] == arm and f["tag"] == tag]
                summary[f"{tag}_{arm}"] = {
                    "n": len(sel),
                    "n_pass": sum(1 for f in sel if f["pass"]),
                    "branch_acc": [round(
                        f["validation"]["branch_accuracy"], 4)
                        for f in sel]}
        report["summary"] = summary
        report["b_supervision_gate"] = bool(
            summary["bc_a_B"]["n_pass"] >= 2
            and summary["bc_b_B"]["n_pass"] >= 2)
        report["arm_a_expected_limitation"] = summary["bc_a_A"]
        ev = evidence_kib_settle(ledger, tag="bc")
        report["evidence_kib"] = ev
        gate_path.write_text(json.dumps(report, ensure_ascii=False,
                                        indent=1), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        print("b_supervision_gate:", report["b_supervision_gate"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
