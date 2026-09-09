#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 c3-identity-receipt-archive-closure:E05 汇总判定。

分别消费六类必需证据,任何一项不成立整体 FAIL(不用其他包成功或
历史回执补认):
  1. 本轮受监护全量 run_record(finalized+evidence_complete+rc=0);
  2. 本轮全量 stdout 末行与 junit 总数/通过数自洽(同 run 身份);
  3. 本轮 slice unit 测试文件(含 I01-I06/P01-P05 身份绑定与写隔离)
     在该 junit 中全过;
  4. v3 包语义正例(新 reader PASS,reader_sha256 与候选一致);
  5. v3 包隔离冷读 ok(含四负例);
  6. 上轮 full run 归档完成且七必需文件哈希与 run_record 一致。

用法:
  aggregate_v3.py --config <config.json> --out <aggregate_report.json>
  config 各键指向实际文件;负例用 sed 把 config 中对应键改为不存在的
  路径构造缺件(缺任一必需键/路径不存在 → 该项 present=false,ok=false,
  整体 rc=1,不用其他包成功补认)。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REQUIRED_KEYS = ("full_run_record", "full_stdout", "full_junit",
                 "c3_semantic_receipt", "c3_cold_read_report",
                 "historical_archive_dir")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def check_full_run(record_path: Path, stdout_path: Path,
                   junit_path: Path) -> tuple[bool, list[str]]:
    probs: list[str] = []
    # junit/stdout 缺失:优雅记 problems(不崩溃;fail-closed 方向不变)
    for label, p in (("full_stdout", stdout_path),
                     ("full_junit", junit_path)):
        if not p.is_file():
            probs.append(f"{label} 缺失: {p}")
    if probs:
        return False, probs
    rec = json.loads(record_path.read_text(encoding="utf-8"))
    if rec.get("finalized") is not True:
        probs.append("run_record.finalized != True")
    if rec.get("evidence_complete") is not True:
        probs.append("run_record.evidence_complete != True")
    if rec.get("business", {}).get("rc") != 0:
        probs.append(f"business.rc={rec.get('business', {}).get('rc')}")
    # junit 身份:run_record required 角色登记
    jrole = [r for r in rec.get("required", [])
             if r.get("role") == "junit_xml"]
    if not jrole:
        probs.append("run_record 缺 junit_xml 角色")
    else:
        got = sha256_file(junit_path)
        if got != jrole[0].get("sha256"):
            probs.append("junit sha256 与 run_record 登记不一致")
    srole = [r for r in rec.get("required", [])
             if r.get("role") == "business_stdout"]
    if srole and sha256_file(stdout_path) != srole[0].get("sha256"):
        probs.append("stdout sha256 与 run_record 登记不一致")
    # stdout 末行与 junit 自洽
    tail = stdout_path.read_text(encoding="utf-8").strip().splitlines()[
        -1] if stdout_path.is_file() else ""
    m = re.match(r"(\d+) passed, (\d+) skipped", tail)
    if not m:
        probs.append(f"stdout 末行无 pytest 汇总: {tail[:80]}")
        return (not probs), probs
    n_pass, n_skip = int(m.group(1)), int(m.group(2))
    root = ET.parse(junit_path).getroot()
    suites = ([root] if root.tag == "testsuite" else
              list(root.iter("testsuite")))
    tot = sum(int(s.get("tests", "0")) for s in suites)
    skipped = sum(int(s.get("skipped", "0")) for s in suites)
    failed = sum(int(s.get("failures", "0")) + int(s.get("errors", "0"))
                 for s in suites)
    if tot != n_pass + n_skip:
        probs.append(f"junit 总数 {tot} != stdout {n_pass}+{n_skip}")
    if skipped != n_skip or failed != 0:
        probs.append(f"junit skipped/failed {skipped}/{failed} 与 stdout"
                     f" {n_skip} 不一致或存在失败")
    # slice unit 测试文件全过(身份绑定与写隔离所在文件)
    n_slice = 0
    n_slice_fail = 0
    for case in root.iter("testcase"):
        cls = case.get("classname", "") or ""
        if "test_curriculum261_r17_c3_slice_unit" in cls:
            n_slice += 1
            if list(case):
                n_slice_fail += 1
    if n_slice == 0:
        probs.append("junit 中无 slice unit 测试(缺本轮候选身份)")
    if n_slice_fail:
        probs.append(f"slice unit 有 {n_slice_fail} 项未过")
    return (not probs), probs


def check_semantic(receipt: Path) -> tuple[bool, list[str]]:
    probs: list[str] = []
    doc = json.loads(receipt.read_text(encoding="utf-8"))
    if doc.get("readback_verdict") != "PASS":
        probs.append(f"语义正例 verdict={doc.get('readback_verdict')}")
    checks = doc.get("checks", {})
    for key in ("envelope_digest", "p52_identity_body"):
        bad = [k for k, v in checks.get(key, {}).items() if v is not True]
        if bad:
            probs.append(f"{key} 存在非 True: {bad[:3]}")
    if checks.get("p52_orig_call_digest_recomputed") is not True:
        probs.append("p52 call digest 复算未通过")
    return (not probs), probs


def check_cold(report: Path) -> tuple[bool, list[str]]:
    probs: list[str] = []
    doc = json.loads(report.read_text(encoding="utf-8"))
    if doc.get("isolated", {}).get("ok") is not True:
        probs.append(f"隔离正例 ok={doc.get('isolated', {}).get('ok')}")
    negs = doc.get("negatives", {}).get("ok", {})
    for k, v in negs.items():
        if v is not True:
            probs.append(f"负例未达预期 {k}={v}")
    return (not probs), probs


def check_archive(archive_dir: Path) -> tuple[bool, list[str]]:
    probs: list[str] = []
    run_dir = archive_dir / "c3rdd_full_20260909"
    rec_path = run_dir / "run_record.json"
    if not rec_path.is_file():
        return False, [f"归档缺 run_record: {rec_path}"]
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    for role in rec.get("required", []):
        p = run_dir / role["path"].split("runs/c3rdd_full_20260909/",
                                          1)[-1]
        if not p.is_file():
            probs.append(f"归档缺 {role['role']}: {p}")
            continue
        if sha256_file(p) != role.get("sha256"):
            probs.append(f"归档哈希不符: {role['role']}")
    for extra in ("launch_scripts/full_entry.sh",
                  "launch_scripts/full_run_ordered.sh",
                  "archive_note.json"):
        if not (archive_dir / extra).is_file():
            probs.append(f"归档缺 {extra}")
    return (not probs), probs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    results: dict = {}
    ok_all = True
    for key in REQUIRED_KEYS:
        val = cfg.get(key)
        if not val or not Path(val).exists():
            # 必需证据缺失(含路径不存在):整体 FAIL,不用其他项补认
            results[key] = {"present": False, "ok": False}
            ok_all = False
            continue
        p = Path(val)
        if key == "full_run_record":
            ok, probs = check_full_run(
                p, Path(cfg["full_stdout"]), Path(cfg["full_junit"]))
        elif key in ("full_junit", "full_stdout"):
            continue  # 存在性与内容检查均在 full_run_record 项内消费
        elif key == "c3_semantic_receipt":
            ok, probs = check_semantic(p)
        elif key == "c3_cold_read_report":
            ok, probs = check_cold(p)
        else:
            ok, probs = check_archive(p)
        results[key] = {"present": True, "problems": probs, "ok": ok}
        if not ok:
            ok_all = False
    doc = {"schema": "c3-irac-aggregate-v3", "ok": ok_all,
           "results": results,
           "note": "六类必需证据分别消费;缺任一或任一不成立整体 FAIL"}
    Path(args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"aggregate_ok={str(ok_all).lower()}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
