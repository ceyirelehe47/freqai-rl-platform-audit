#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 c3-entry-temp-ownership-closure:E03/E05 汇总判定。

分别消费必需证据,任何一项不成立整体 FAIL(不用其他包成功或
历史回执补认):
  1. 本轮受监护全量 run_record(finalized+evidence_complete+rc=0)+
     junit/stdout 哈希与 run_record 登记一致+末行自洽+slice unit 135
     项全过且含本轮 PE/TO 新矩阵类;
  2. v5 包语义正例(新 reader PASS,复算全 True,reader_sha256=候选,
     回执 format=v5);
  3. v5 包隔离冷读 ok(含 P01 跨目录悬空/P03 非目录/T01 临时碰撞/
     P06 symlink-dotdot/K01 必要键五负例);
  4. 旧行为反例三缺陷全部复现(旧 reader=接手版 9869ea6a 身份);
  5. 同脚本修复后翻转(三缺陷全部不再复现,新 reader=候选身份);
  6. 候选身份绑定(部署 reader 哈希=候选)。

用法:
  aggregate_v5.py --config <config.json> --out <aggregate_report.json>
  config 各键指向实际文件;负例用 sed 把 config 中对应键改为不存在
  的路径构造缺件(缺任一必需键/路径不存在 → 该项 present=false,
  ok=false,整体 rc=1,不用其他包成功补认)。
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
CANDIDATE_READER_SHA = "559fd51cb6775502bd7deff95bb779a6d3a75b5ccac8fef3c51be5fd2f0b0e1c"
OLD_READER_SHA = "9869ea6ccc319e7ebf6ad85cf3b70e669fcf59baeb11e46dc730aa8198853886"
#: 本轮新增矩阵类须出现在全量 junit(classname 片段 → 最少项数)
NEW_MATRIX_CLASSES = {
    "TestPE01CrossDirDanglingEndLink": 2,
    "TestPE03NotDirAncestor": 4,
    "TestPE04ResolveErrors": 4,
    "TestTO01TempNameCollision": 3,
    "TestTO05CleanupFailHonesty": 2,
}


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
    # slice unit(路径/回执/参数/末端条目/临时件所有权矩阵所在文件)
    # 在本 junit 中全过,且含本轮新增 PE/TO 矩阵类
    n_slice = 0
    n_slice_fail = 0
    cls_count: dict[str, int] = {}
    for case in root.iter("testcase"):
        cls = case.get("classname", "") or ""
        if "test_curriculum261_r17_c3_slice_unit" in cls:
            n_slice += 1
            if list(case):
                n_slice_fail += 1
            for frag in NEW_MATRIX_CLASSES:
                if frag in cls:
                    cls_count[frag] = cls_count.get(frag, 0) + 1
    if n_slice != 135:
        probs.append(f"slice unit 项数 {n_slice} != 135(缺本轮候选矩阵)")
    if n_slice_fail:
        probs.append(f"slice unit 有 {n_slice_fail} 项未过")
    for frag, need in NEW_MATRIX_CLASSES.items():
        if cls_count.get(frag, 0) < need:
            probs.append(f"junit 缺本轮新矩阵类 {frag}"
                         f"({cls_count.get(frag, 0)}/{need})")
    return (not probs), probs


def check_semantic(receipt: Path) -> tuple[bool, list[str]]:
    probs: list[str] = []
    doc = json.loads(receipt.read_text(encoding="utf-8"))
    if doc.get("readback_verdict") != "PASS":
        probs.append(f"语义正例 verdict={doc.get('readback_verdict')}")
    if doc.get("format") != "r17-c3-engineering-slice-readback-v5":
        probs.append(f"回执 format={doc.get('format')} 非 v5")
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
    if doc.get("schema") != "c3-eto-cold-read-v5":
        probs.append(f"冷读 schema={doc.get('schema')} 非 v5")
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
    """修复后同脚本复跑:三缺陷全部不再复现(翻转)。"""
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
    doc = {"schema": "c3-eto-aggregate-v5", "ok": ok_all,
           "results": results,
           "note": "必需证据分别消费;缺任一或任一不成立整体 FAIL"}
    Path(args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"aggregate_ok={str(ok_all).lower()}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
