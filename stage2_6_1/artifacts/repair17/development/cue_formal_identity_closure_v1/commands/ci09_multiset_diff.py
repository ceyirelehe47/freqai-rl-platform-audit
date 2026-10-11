#!/usr/bin/env python3
"""CI09 多重集对比:FR2 基线 junit vs 新候选 junit(test id 多重集)。"""
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

BASE = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/"
            "repair17/development/a2_runtime_closure_v1/evidence/"
            "regress261_d3/junit.xml")
NEW = Path("/home/cryptorl/regress_cue_identity_v1/junit.xml")
OUT = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/"
           "repair17/development/cue_formal_identity_closure_v1/"
           "commands/CI09_multiset_diff.json")


def ids_and_status(path: Path):
    root = ET.parse(path).getroot()
    cases = {}
    suites = root.iter("testsuite")
    for ts in suites:
        for tc in ts.iter("testcase"):
            key = f"{tc.get('classname', '')}::{tc.get('name', '')}"
            status = "passed"
            if tc.find("failure") is not None:
                status = "failure"
            elif tc.find("error") is not None:
                status = "error"
            elif tc.find("skipped") is not None:
                status = "skipped"
            cases[key] = status
    return cases


def main() -> int:
    base = ids_and_status(BASE)
    new = ids_and_status(NEW)
    b, n = Counter(base), Counter(new)
    added = sorted((n - b).elements())
    removed = sorted((b - n).elements())
    status_changes = {
        k: {"base": base[k], "new": new[k]}
        for k in sorted(set(base) & set(new)) if base[k] != new[k]}
    result = {
        "base_junit": str(BASE), "new_junit": str(NEW),
        "base_total": sum(b.values()), "new_total": sum(n.values()),
        "added": added, "removed": removed,
        "status_changes": status_changes,
        "summary": {
            "n_added": len(added), "n_removed": len(removed),
            "n_status_changes": len(status_changes),
            "removed_is_empty": not removed,
        },
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))
    print(f"base={result['base_total']} new={result['new_total']}")
    return 0 if not removed else 1


if __name__ == "__main__":
    sys.exit(main())
