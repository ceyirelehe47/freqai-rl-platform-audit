#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JUnit/collection 多重集对比工具(F5 修复;RouteC_CueAudit R1)。

旧 commands/ci09_multiset_diff.py 的缺陷(IndependentReview_33407fd4 §F5):
1) ``cases[key]=status`` 字典阶段即合并重复测试身份;
2) ``Counter(dict)`` 把字符串状态当计数,两份相同全绿 JUnit 也 TypeError;
3) 状态与多重集混在一个映射,skip 原因不可比较。

本工具从原始 testcase 记录流直接构造多重集(身份×状态),单次遍历
``root.iter('testcase')``(覆盖嵌套 testsuite 且不重复计重),状态/
skip 原因/数量分离比较,机读输出 + rc 与结论一致:

- rc=0 : 仅合法新增(旧身份全保留、无状态劣化、无新增 skip/原因变化);
- rc=1 : 出现删除、数量减少、状态变更、新增 skip 或 skip 原因变化;
- rc=2 : 输入缺失/畸形(无法解析为 JUnit)。

不预填计数;结论只基于实测 JUnit/collection。
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

TOOL = "cur261-ci-multiset-compare-v2"


def _identity(tc: ET.Element) -> tuple[str, str]:
    """身份=(classname, name);不含文件名(跨文件比较)。"""
    return (tc.get("classname", "") or "", tc.get("name", "") or "")


def parse_junit_multiset(path: Path) -> dict:
    """单次遍历构造 {identity: Counter(status)} + skip 原因多重集。

    identity=(classname, name);重复身份保留全部多重性;状态按出现
    计数。skip 原因取 skipped 元素 message/文本,无则 '<none>'。
    畸形 XML/根不为 testsuite(s) → 抛 ValueError(由 main 转 rc=2)。
    """
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"JUnit XML 解析失败 {path}: {exc}") from exc
    if root.tag not in ("testsuite", "testsuites"):
        raise ValueError(f"非 JUnit 根元素 {root.tag!r}: {path}")
    entries: dict[tuple, Counter] = {}
    skip_reasons: Counter = Counter()
    n_cases = 0
    for tc in root.iter("testcase"):
        n_cases += 1
        ident = _identity(tc)
        if tc.find("failure") is not None:
            status = "failure"
        elif tc.find("error") is not None:
            status = "error"
        elif (sk := tc.find("skipped")) is not None:
            status = "skipped"
            reason = (sk.get("message") or sk.text or "<none>").strip()
            skip_reasons[(ident, reason)] += 1
        else:
            status = "passed"
        entries.setdefault(ident, Counter())[status] += 1
    return {"path": str(path), "n_cases": n_cases,
            "entries": entries, "skip_reasons": skip_reasons}


def compare_multisets(base: dict, new: dict) -> dict:
    """身份多重集 + 状态 + skip 原因分离比较(纯函数,可单测)。"""
    b_ids = Counter({k: sum(c.values()) for k, c in base["entries"].items()})
    n_ids = Counter({k: sum(c.values()) for k, c in new["entries"].items()})
    added = sorted(n_ids - b_ids)          # 旧中无该身份(任意数量)
    removed = sorted(b_ids - n_ids)        # 旧身份在新中消失
    count_reduced = sorted(
        k for k in (b_ids & n_ids) if n_ids[k] < b_ids[k])
    count_increased = sorted(
        k for k in (b_ids & n_ids) if n_ids[k] > b_ids[k])
    status_changes = []
    for k in sorted(set(base["entries"]) & set(new["entries"])):
        if base["entries"][k] != new["entries"][k]:
            status_changes.append({
                "identity": list(k),
                "base": dict(base["entries"][k]),
                "new": dict(new["entries"][k])})
    new_skips = sorted(new["skip_reasons"] - base["skip_reasons"])
    skip_reason_changes = sorted(
        (set(new["skip_reasons"]) ^ set(base["skip_reasons"])))
    verdict = "OK" if not (removed or count_reduced or status_changes
                           or new_skips) else "REGRESSED"
    return {
        "base_cases": base["n_cases"], "new_cases": new["n_cases"],
        "added": [list(k) for k in added],
        "removed": [list(k) for k in removed],
        "count_reduced": [list(k) for k in count_reduced],
        "count_increased": [list(k) for k in count_increased],
        "status_changes": status_changes,
        "new_skips": [[list(k), r] for k, r in new_skips],
        "skip_reason_set_changes": [
            [list(k), r] for k, r in skip_reason_changes],
        "verdict": verdict,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ci-multiset-compare")
    ap.add_argument("--base-junit", required=True)
    ap.add_argument("--new-junit", required=True)
    ap.add_argument("--out", required=True,
                    help="机读结果 JSON(create;已存在拒绝)")
    args = ap.parse_args(argv)
    base_p, new_p = Path(args.base_junit), Path(args.new_junit)
    for p in (base_p, new_p):
        if not p.is_file():
            print(f"输入缺失: {p}", file=sys.stderr)
            return 2
    try:
        base = parse_junit_multiset(base_p)
        new = parse_junit_multiset(new_p)
    except ValueError as exc:
        print(f"输入畸形: {exc}", file=sys.stderr)
        return 2
    result = {"tool": TOOL, **compare_multisets(base, new)}
    out = Path(args.out)
    if out.exists():
        print(f"输出已存在,拒绝覆盖: {out}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "base_cases", "new_cases", "verdict",
        "n_added", "n_removed") if k in result} | {
        "n_added": len(result["added"]),
        "n_removed": len(result["removed"])}, ensure_ascii=False))
    return 0 if result["verdict"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
