#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C4d2 固定规格数值复算证据(FiniteRepair R3-03;纯数学,零 env 步)。

对冻结参数的 C4d2/horizon64 做四级固定规格细化复算,断言与
R2 报告值逐位一致(81/161/321/481 网格);输出各级 initial_value、
相邻差、err_bound 与分型(经验相邻差,非已证明误差上界)。
不采样模型、不训练、不换科学参数(纯数学计算不计 env 步;计算
范围与停止点如实记录)。

用法:python posctl_r3_refcheck.py --out <r3_refcheck.json>
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rl_posctl import profiles  # noqa: E402
from rl_posctl.curriculum import (  # noqa: E402
    error_report, spec_for, validate_refinements)

# R2 上传证据的四档固定规格(INDEPENDENT_REVIEW §6 表)
R2_VALUES = {
    (81, 16, 12): 0.0004235082060256445,
    (161, 32, 24): 0.00042658620079265037,
    (321, 64, 40): 0.00042775649727397645,
    (481, 96, 80): 0.00042780919891891706,
}
R2_LAST_DIFF = 5.270164494061312e-8


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    spec = spec_for("c4d2", seed=profiles.MASTER_SEED, horizon=64,
                    **profiles.TRAIN_SPEC_OVERRIDES)
    refinements = [(81, 16, 12), (161, 32, 24),
                   (321, 64, 40), (481, 96, 80)]
    validate_refinements(refinements)
    t0 = time.time()
    rep = error_report(spec, refinements=refinements)
    elapsed = time.time() - t0
    checks = []
    ok = True
    for lvl, val in zip(refinements, rep["values"]):
        expect = R2_VALUES[lvl]
        # 数值一致到跨环境数值精度:评审环境(py3.13/numpy)与
        # 本机 WSL(py3.11/numpy)末位实现漂移属预期;两级值各自
        # ~1e-16 相对精度 ⇒ 相邻差的相对不确定度可达 ~1e-8,
        # 值对齐用 1e-12,差对齐用 1e-7(依据=量级推算,不放宽到
        # 掩盖真实退化的程度)。
        match = (val == expect) or math.isclose(
            val, expect, rel_tol=1e-12, abs_tol=0.0)
        ok = ok and match
        checks.append({"level": list(lvl), "value": val,
                       "r2_reported": expect,
                       "match_rel_1e-12": match})
    last_diff = rep["adjacent_diffs"][-1]
    diff_ok = math.isclose(last_diff, R2_LAST_DIFF,
                           rel_tol=1e-7)
    ok = ok and diff_ok
    out = {
        "run": "posctl_r3_refcheck",
        "spec": "c4d2 horizon=64 冻结参数(不调参救援)",
        "refinements": [list(r) for r in refinements],
        "values": rep["values"],
        "adjacent_diffs": rep["adjacent_diffs"],
        "err_bound": rep["err_bound"],
        "err_bound_kind": rep["err_bound_kind"],
        "err_bound_note": rep["err_bound_note"],
        "checks_vs_r2_report": checks,
        "last_adjacent_diff_vs_r2": {
            "computed": last_diff, "r2_reported": R2_LAST_DIFF,
            "match": diff_ok},
        "all_positive": all(v > 0 for v in rep["values"]),
        "elapsed_s": round(elapsed, 1),
        "boundary": ("纯数学固定规格有限细化(四级即停,无参数网格"
                     "搜索);经验收敛差不是已证明误差上界;不构成"
                     "模型学习/正式资格主张"),
        "pass": bool(ok and all(v > 0 for v in rep["values"])),
    }
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                 encoding="utf-8")
    print(json.dumps({"pass": out["pass"],
                      "err_bound": rep["err_bound"],
                      "last_diff": last_diff, "elapsed_s":
                      out["elapsed_s"]},
                     ensure_ascii=False, indent=1))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
