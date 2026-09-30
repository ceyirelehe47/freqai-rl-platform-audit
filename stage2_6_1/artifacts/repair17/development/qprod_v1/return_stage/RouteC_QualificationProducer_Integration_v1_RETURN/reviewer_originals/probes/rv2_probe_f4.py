# RV2 probe: F4 re-verification in deployment tree (C7=cda4e975).
# SYNTHETIC_ONLY: zero native generation/fit/update; create=False everywhere.
import os
import sys
from pathlib import Path

SRC = "/home/cryptorl/projects/crypto_rl/src"
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import rl_curriculum.curriculum261_qprod_context as cx

results = []


def rec(tag, ok, detail=""):
    results.append((tag, ok))
    print(("PASS " if ok else "FAIL ") + tag + (" :: " + detail if detail else ""))


roots = cx.protected_old_roots()
rec("F4a.roots-nonempty-in-deploy", bool(roots), "n=%d" % len(roots))
print("INFO roots:")
for p in roots:
    print("   ", p)
names = {p.name for p in roots}
rec("F4b.canonical-names-present",
    {"route_c_stage2_6_1_repair17", "route_c_stage2_6_1_repair18",
     "route_c_stage2_6_1_repair19"} <= names,
    str(sorted(n for n in names if n.startswith("route_c"))))
for prot in roots:
    tag = "F4c.reject:" + str(prot)
    try:
        cx.harden_root(prot / "rv2_probe_child", label="t", create=False)
        rec(tag, False, "ACCEPTED (must reject)")
    except cx.QProdContextError:
        rec(tag, True)

ghost = Path("/tmp/rv2_f4_ghost/deploy/artifacts/route_c_stage2_6_1_repair17")
os.environ["CURRICULUM261_R17_DEPLOYED_STATE_ROOT"] = str(ghost / "state")
try:
    r2 = cx.protected_old_roots()
    rec("F4d.env-root-in-protected",
        any(p == Path(os.path.realpath(str(ghost / "state"))) for p in r2))
    try:
        cx.harden_root(ghost / "state" / "child", label="t", create=False)
        rec("F4e.env-root-child-rejected", False, "ACCEPTED")
    except cx.QProdContextError:
        rec("F4e.env-root-child-rejected", True)
finally:
    del os.environ["CURRICULUM261_R17_DEPLOYED_STATE_ROOT"]

ok_dir = Path("/tmp/rv2_f4_ok/dir")
out = cx.harden_root(ok_dir, label="t", create=False)
rec("F4f.positive-control-accepted", out == Path(os.path.realpath(str(ok_dir))),
    str(out))

dep_art = Path("/home/cryptorl/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair17")
print("INFO deploy frozen root exists:", dep_art.exists(),
      "(existence irrelevant; protection is name-based)")

print("")
fails = [t for t, ok in results if not ok]
print("==== SUMMARY ==== total=%d pass=%d fail=%d"
      % (len(results), len(results) - len(fails), len(fails)))
for t in fails:
    print("FAILED:", t)
