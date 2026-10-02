# R11 pre-fix repro (C22=1361b4bb bytes): Q1 derived-diff dependency holes
# dg sources complete (k_mean 1/1, hist {"1":110}, n_events 110):
# derivable abs-diff 0, frozen K tol 0.05. Deleting a redundant derived
# copy (k_mean_validation [+ k_tolerance]) must NOT mask in-present
# k_abs_diff contradiction. Fixture mode = the 17-step PASS path.
import sys
sys.path.insert(0, "/tmp")
from repro_r10 import base_report
from rl_curriculum.curriculum261_r17_cue_contract import (
    recompute_audit_semantics_from_report as rec)


def run(tag, m, fixture=True):
    r = base_report()
    m(r)
    if fixture:
        r["engineering_fixture"] = True
    o = rec(r)
    print("%-46s fix=%-5s all=%s %s" % (
        tag, fixture, o["all_consistent"],
        o["threshold_discrepancies"][:1]
        if not o["all_consistent"] else ""))


def kad(r, v):
    r["once_vs_attempts"]["k_abs_diff"] = v


def del_kv(r):
    del r["once_vs_attempts"]["k_mean_validation"]


def del_kt(r):
    del r["once_vs_attempts"]["k_tolerance"]


# case1: k_abs_diff=-0.02 (negative abs-diff is self-illegal)
run("C1a  kad=-0.02 complete", lambda r: kad(r, -0.02))
run("C1b  kad=-0.02 +del k_mean_validation",
    lambda r: (kad(r, -0.02), del_kv(r)))
# case2: k_abs_diff=0.02 vs source-derived 0
run("C2a  kad=0.02 complete", lambda r: kad(r, 0.02))
run("C2b  kad=0.02 +del k_mean_validation",
    lambda r: (kad(r, 0.02), del_kv(r)))
# case3: k_abs_diff=0.5 + del self-reported k_tolerance
run("C3a  kad=0.5 complete", lambda r: kad(r, 0.5))
run("C3b  kad=0.5 +del k_mean_validation +del k_tolerance",
    lambda r: (kad(r, 0.5), del_kv(r), del_kt(r)))
# case4: k_abs_diff=0 same deletions -> legal delegation passes
run("C4   kad=0 +del k_mean_validation", lambda r: (
    kad(r, 0.0), del_kv(r)))
run("C4b  kad=0 +del kv +del k_tolerance", lambda r: (
    kad(r, 0.0), del_kv(r), del_kt(r)))
# controls
run("ctl legal complete", lambda r: None)
def del_km(r):
    del r["once_vs_attempts"]["k_mean_model"]


run("ctl del-km order", del_km)
run("ctl kad=0.02 +del k_mean_model", lambda r: (
    kad(r, 0.02), del_km(r)))
# no-fixture: missing required field rejects
r = base_report()
kad(r, 0.5)
del_kv(r)
o = rec(r)
print("%-46s fix=%-5s all=%s" % (
    "C3b-nofix (missing required -> reject)", False,
    o["all_consistent"]))
