#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 c3-entry-temp-ownership-closure(交接包路线):E04/E05 汇总判定。

分别消费六类必需证据,任何一项不成立整体 FAIL(不用其他包成功或
历史回执补认):
  1. 本轮受监护全量 run_record(finalized+evidence_complete+rc=0)+
     junit/stdout 哈希与 run_record 登记一致+末行自洽+slice unit 108
     项全过+交接包新测试 receipt_entry_cleanup 54 项全过;
  2. v6 包语义正例(交接包 reader PASS,复算全 True,reader_sha256=
     候选,回执 format=v4——交接包保留既有 format 版本号);
  3. v6 包隔离冷读 ok(含 P01 跨目录悬空/P03 非目录/T01 临时碰撞/
     P06 防回归/K01 必要键五负例);
  4. 旧行为反例三缺陷全部复现(旧 reader=接手版身份 9869ea6c);
  5. 同脚本交接包 reader 复跑翻转(旧缺陷全部不再复现,reader=候选);
  6. 候选身份绑定(语义回执/翻转回执 reader_sha256 与本轮部署 reader
     一致=7a5ccc19)。

用法:
  aggregate_v6.py --config <config.json> --out <aggregate_report.json>
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
                 "old_counterexamples", "fixed_flip",
                 "candidate_reader")
CANDIDATE_READER_SHA = "7a5ccc19b4e3ade4dd0e6b64861ae425cdb631c181149458a51f4ccbb52141dd"
OLD_READER_SHA = "9869ea6ccc319e7ebf6ad85cf3b70e669fcf59baeb11e46dc730aa8198853886"
#: 交接包新测试文件(classname 片段 → 期望项数);旧 slice 回到 108 项
SLICE_UNIT_FILE = "test_curriculum261_r17_c3_slice_unit"
SLICE_UNIT_COUNT = 108
RECEIPT_UNIT_FILE = "test_curriculum261_r17_receipt_entry_cleanup_unit"
RECEIPT_UNIT_COUNT = 54


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def check_full_run(record_path: Path, stdout_path: Path,
                   junit_path: Path) -> tuple[bool, list[str]]:
    probs: list[str] = []
    for label, p in (("full_run_record", record_path),
                     ("full_stdout", stdout_path),
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
    tail = stdout_path.read_text(encoding="utf-8").strip().splitlines()[-1]
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
    # 旧 slice unit(108 项,回到接手版数量)与交接包新测试(54 项)
    # 都必须在本 junit 中全过
    counts = {SLICE_UNIT_FILE: [0, 0], RECEIPT_UNIT_FILE: [0, 0]}
    for case in root.iter("testcase"):
        cls = case.get("classname", "") or ""
        for frag in counts:
            if frag in cls:
                counts[frag][0] += 1
                if list(case):
                    counts[frag][1] += 1
    if counts[SLICE_UNIT_FILE][0] != SLICE_UNIT_COUNT:
        probs.append(f"slice unit 项数 {counts[SLICE_UNIT_FILE][0]}"
                     f" != {SLICE_UNIT_COUNT}")
    if counts[SLICE_UNIT_FILE][1]:
        probs.append(f"slice unit 有 {counts[SLICE_UNIT_FILE][1]} 项未过")
    if counts[RECEIPT_UNIT_FILE][0] != RECEIPT_UNIT_COUNT:
        probs.append(f"receipt cleanup 项数 {counts[RECEIPT_UNIT_FILE][0]}"
                     f" != {RECEIPT_UNIT_COUNT}(缺交接包候选矩阵)")
    if counts[RECEIPT_UNIT_FILE][1]:
        probs.append(f"receipt cleanup 有 "
                     f"{counts[RECEIPT_UNIT_FILE][1]} 项未过")
    return (not probs), probs


def check_semantic(receipt: Path) -> tuple[bool, list[str]]:
    probs: list[str] = []
    doc = json.loads(receipt.read_text(encoding="utf-8"))
    if doc.get("readback_verdict") != "PASS":
        probs.append(f"语义正例 verdict={doc.get('readback_verdict')}")
    if doc.get("format") != "r17-c3-engineering-slice-readback-v4":
        probs.append(f"回执 format={doc.get('format')} 非 v4"
                     f"(交接包保留既有版本号)")
    checks = doc.get("checks", {})
    for key in ("envelope_digest", "p52_identity_body"):
        bad = [k for k, v in checks.get(key, {}).items() if v is not True]
        if bad:
            probs.append(f"{key} 存在非 True: {bad[:3]}")
    if checks.get("p52_orig_call_digest_recomputed") is not True:
        probs.append("p52 call digest 复算未通过")
    adm = doc.get("report_target_admission", {})
    if adm.get("admitted") is not True:
        probs.append("report_target_admission.admitted != True")
    if not adm.get("confirmed_target"):
        probs.append("回执缺 confirmed_target(检查目标未交付写者)")
    return (not probs), probs


def check_cold(report: Path) -> tuple[bool, list[str]]:
    probs: list[str] = []
    doc = json.loads(report.read_text(encoding="utf-8"))
    if doc.get("schema") != "c3-eto-cold-read-v6":
        probs.append(f"冷读 schema={doc.get('schema')} 非 v6")
    if doc.get("isolated", {}).get("ok") is not True:
        probs.append(f"隔离正例 ok={doc.get('isolated', {}).get('ok')}")
    negs = doc.get("negatives", {}).get("ok", {})
    if not negs:
        probs.append("冷读负例结果缺失")
    for k, v in negs.items():
        if v is not True:
            probs.append(f"负例未达预期 {k}={v}")
    return (not probs), probs


def check_counterexamples(path: Path) -> tuple[bool, list[str]]:
    """旧行为反例:三缺陷全部由接手版 reader 复现。"""
    probs: list[str] = []
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("reader_sha256") != OLD_READER_SHA:
        probs.append(f"旧反例 reader 身份非接手版: {doc.get('reader_sha256')}")
    cases = doc.get("cases", {})
    for name, c in cases.items():
        if c.get("old_defect_reproduced") is not True:
            probs.append(f"旧缺陷未复现 {name}")
    return (not probs), probs


def check_flip(path: Path) -> tuple[bool, list[str]]:
    """交接包 reader 同脚本复跑:三缺陷全部不再复现(翻转)。"""
    probs: list[str] = []
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("reader_sha256") != CANDIDATE_READER_SHA:
        probs.append(f"翻转回执 reader 身份非本轮候选: "
                     f"{doc.get('reader_sha256')}")
    cases = doc.get("cases", {})
    for name, c in cases.items():
        if c.get("old_defect_reproduced") is not False:
            probs.append(f"修复后缺陷仍复现 {name}")
    return (not probs), probs


def check_candidate_reader(path: Path) -> tuple[bool, list[str]]:
    probs: list[str] = []
    if not path.is_file():
        return False, [f"候选 reader 缺失: {path}"]
    got = sha256_file(path)
    if got != CANDIDATE_READER_SHA:
        probs.append(f"候选 reader 哈希漂移: {got}")
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
            results[key] = {"present": False, "ok": False}
            ok_all = False
            continue
        p = Path(val)
        if key == "full_run_record":
            ok, probs = check_full_run(
                p, Path(cfg["full_stdout"]), Path(cfg["full_junit"]))
        elif key in ("full_junit", "full_stdout"):
            continue
        elif key == "c3_semantic_receipt":
            ok, probs = check_semantic(p)
        elif key == "c3_cold_read_report":
            ok, probs = check_cold(p)
        elif key == "old_counterexamples":
            ok, probs = check_counterexamples(p)
        elif key == "fixed_flip":
            ok, probs = check_flip(p)
        else:
            ok, probs = check_candidate_reader(p)
        results[key] = {"present": True, "problems": probs, "ok": ok}
        if not ok:
            ok_all = False
    doc = {"schema": "c3-eto-aggregate-v6", "ok": ok_all,
           "results": results,
           "note": "必需证据分别消费;缺任一或任一不成立整体 FAIL"}
    Path(args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"aggregate_ok={str(ok_all).lower()}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
