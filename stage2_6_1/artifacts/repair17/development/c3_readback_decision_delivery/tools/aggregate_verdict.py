#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 C3 读回决策交付轮:整体汇总入口(E05)。

单独子包(如 pytest 全量包)rc=0 不能替代 C3 业务包验证;汇总入口
要求全部适用证据同时成立,缺任一子包或其回执 → 整体 FAIL(rc=1)。

用法: aggregate_verdict.py --config <agg_config.json> --report <out.json>
配置字段(全部必需,缺文件即 FAIL):
  full_run_record     阶段五全量 run 的 run_record.json(finalized)
  full_verify_receipt 全量包冷读 verify 回执(verify_rc=0)
  c3_finalize_report  C3 关联包 finalize 报告(verifier_rc=0)
  c3_semantic_receipt C3 语义正例回执(readback_verdict=PASS)
  c3_cold_receipt     C3 包隔离冷读回执(rc=0)
rc:0=整体通过;1=任何子证据缺失/不满足;2=用法错误。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    problems: list[str] = []

    def load(key: str) -> dict | None:
        p = Path(cfg[key])
        if not p.is_file():
            problems.append(f"{key}: 回执/记录缺失 {p}")
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append(f"{key}: 解析失败 {exc}")
            return None

    rr = load("full_run_record")
    if rr is not None:
        if rr.get("finalized") is not True:
            problems.append("full_run_record: finalized != true")
        if rr.get("evidence_complete") is not True:
            problems.append("full_run_record: evidence_complete != true")

    fv = load("full_verify_receipt")
    if fv is not None and fv.get("verify_rc", fv.get("rc")) != 0:
        problems.append(f"full_verify_receipt: rc!=0 ({fv.get('verify_rc', fv.get('rc'))})")

    cf = load("c3_finalize_report")
    if cf is not None and cf.get("verifier_rc") != 0:
        problems.append(f"c3_finalize_report: verifier_rc={cf.get('verifier_rc')}")

    cs = load("c3_semantic_receipt")
    if cs is not None and cs.get("readback_verdict") != "PASS":
        problems.append("c3_semantic_receipt: verdict != PASS")

    cc = load("c3_cold_receipt")
    if cc is not None and cc.get("rc") != 0:
        problems.append(f"c3_cold_receipt: rc={cc.get('rc')}")

    report = {
        "format": "r17rdd-aggregate-verdict-v1",
        "config": cfg,
        "n_problems": len(problems),
        "problems": problems,
        "aggregate_verdict": "PASS" if not problems else "FAIL",
        "written_utc": utc_now(),
    }
    Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps({"aggregate_verdict": report["aggregate_verdict"],
                      "n_problems": len(problems)}, ensure_ascii=False))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
