# -*- coding: utf-8 -*-
"""Extra reviewer probe: malformed-value robustness pre/post C24."""
import importlib.util
import sys
sys.path.insert(0, "/mnt/f/trading/tmp_r12/reviewer")
from probe_r12_reviewer import (  # noqa: E402
    build, m_c22, m_c23, REC)

FNS = {"c24": lambda r: REC(r),
       "c23": lambda r: m_c23.recompute_audit_semantics_from_report(r),
       "c22": lambda r: m_c22.recompute_audit_semantics_from_report(r)}


def run(tag, maker):
    out = []
    for m in ("c22", "c23", "c24"):
        try:
            o = FNS[m](maker())
            out.append("%s=%s" % (m, o["all_consistent"]))
        except Exception as exc:  # noqa: BLE001
            out.append("%s=EXC(%s)" % (m, type(exc).__name__))
    print("%-56s %s" % (tag, "  ".join(out)))


print("=== J. malformed-value robustness (fixture) ===")
run("J1 kad='x' (nonscalar str) frozen avail, kt=0.05",
    lambda: build(1, 1, "x"))
run("J2 kad absent kt='abc' frozen AVAILABLE",
    lambda: build(1, 1, None, del_kad=True, ktol_value="abc"))
run("J3 kad absent kt='abc' frozen UNAVAIL (val hist del)",
    lambda: build(1, 1, None, del_kad=True, ktol_value="abc",
                  del_val_hist=True))
run("J4 kad absent kt=float('nan') frozen UNAVAIL",
    lambda: build(1, 1, None, del_kad=True,
                  ktol_value=float("nan"), del_val_hist=True))
run("J5 kad absent kt absent  frozen UNAVAIL (val hist del)",
    lambda: build(1, 1, None, del_kad=True, del_kt=True,
                  del_val_hist=True))
run("J6 kad absent kt='abc' frozen UNAVAIL non-fixture",
    lambda: build(1, 1, None, del_kad=True, ktol_value="abc",
                  del_val_hist=True, fixture=False))
print("done")
