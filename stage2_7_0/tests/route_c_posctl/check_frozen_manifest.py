# -*- coding: utf-8 -*-
"""冻结预期清单校验器(runner 一致性门调用;亦可独立负例测试)。

清单必须:存在、可解析(每行 '::' 且以 tests/ 开头,忽略 # 头)、
头声明数量与实际一致、数量>0。任何失败 exit 1。
用法: check_frozen_manifest.py <path>
"""
import sys
from pathlib import Path


def validate_frozen_manifest(path) -> dict:
    p = Path(path)
    if not p.is_file():
        raise SystemExit(
            "FROZEN_MANIFEST_MISSING: %s (official run must "
            "fail immediately, no skip)" % p)
    lines = p.read_text(encoding="utf-8",
                        errors="replace").splitlines()
    header = [ln for ln in lines
              if ln.startswith("#") and "cases" in ln]
    cases = [ln.strip() for ln in lines
             if ln.strip() and not ln.startswith("#")]
    if not cases:
        raise SystemExit("FROZEN_MANIFEST_EMPTY: %s" % p)
    bad = [c for c in cases
           if "::" not in c
           or not c.startswith("tests/")]
    if bad:
        raise SystemExit(
            "FROZEN_MANIFEST_UNPARSEABLE: bad lines %r"
            % bad[:3])
    declared = None
    if header:
        for tok in header[0].replace(";", " ").split():
            if tok.isdigit():
                declared = int(tok)
                break
    if declared is None:
        raise SystemExit(
            "FROZEN_MANIFEST_NO_DECLARED_COUNT: %s" % p)
    if len(cases) != declared:
        raise SystemExit(
            "FROZEN_MANIFEST_COUNT_MISMATCH: declared=%d "
            "actual=%d" % (declared, len(cases)))
    if len(set(cases)) != len(cases):
        dup = sorted({c for c in cases
                      if cases.count(c) > 1})[:3]
        raise SystemExit(
            "FROZEN_MANIFEST_DUPLICATE: %d duplicate "
            "nodeids e.g. %r (later set() would shrink to "
            "%d unique)" % (len(cases) - len(set(cases)),
                            dup, len(set(cases))))
    return {"declared": declared, "actual": len(cases),
            "cases": cases}


if __name__ == "__main__":
    info = validate_frozen_manifest(sys.argv[1])
    print("FROZEN_OK declared=%d actual=%d"
          % (info["declared"], info["actual"]))
