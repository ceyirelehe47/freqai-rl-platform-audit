# -*- coding: utf-8 -*-
"""R8 independent reviewer probe - values INDEPENDENT of
REPRO_R8_PRE_FIX.py (se=0.02, n_events=120, k_mean=2.0, different
garbage keys/negatives/mean-magnitudes). Proves content-based
rejection (no example-value special-casing)."""
import hashlib
import importlib.util
import math
import sys

sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/src")
from rl_curriculum.curriculum261_r17_cue_contract import (
    AUDIT_REQUIRED_CHECK_NAMES,
    recompute_audit_semantics_from_report as rec,
)
import rl_curriculum.curriculum261_r17_cue_contract as M

print("module:", M.__file__)
print("module-sha256:", hashlib.sha256(
    open(M.__file__, "rb").read()).hexdigest())
print("required_checks:", list(AUDIT_REQUIRED_CHECK_NAMES))

SE = 0.02
RECALL = 0.55
RECALL_TOL = 3.0 * math.sqrt(2 * SE * SE)
DIFF_TOL = max(3.0 * SE, 0.005)
NE = 120
KM_M = (50 * 1.0 + 70 * 2.0) / NE
KM_V = (52 * 1.0 + 68 * 2.0) / NE
VAR_M = (50.0 * (1.0 - KM_M) ** 2 + 70.0 * (2.0 - KM_M) ** 2) / (NE - 1)
VAR_V = (52.0 * (1.0 - KM_V) ** 2 + 68.0 * (2.0 - KM_V) ** 2) / (NE - 1)
POOLED = math.sqrt(VAR_M / NE + VAR_V / NE)
TOL_FROZEN = max(3.0 * POOLED, 0.05)
K_DIFF = abs(KM_M - KM_V)
RESULTS = []


def base():
    return {
        "p_contract": RECALL,
        "monte_carlo": {"p_hat": RECALL, "tolerance": 0.001},
        "direct_generator": {
            n: {
                "block_cluster": {"se": SE, "ci95": [0.35, 0.75]},
                "empirical_recall": RECALL,
                "analytic_conditional": RECALL,
                "diff_tolerance": DIFF_TOL,
                "replay_ok": True, "bounds_ok": True,
                "cue_table_consistent_across_rungs": True,
                "max_replay_abs_error": 0.0,
                "aggregate": {"k_mean": 2.0, "n_detected": 100,
                              "n_events": NE,
                              "k_histogram": {"2": NE}},
                "tail": {"n_events": 0},
            } for n in ("model", "validation")},
        "tail_mirror_bound_integrity": {
            "pass": True,
            "per_corpus": {
                n: {"ok": True, "violations": [], "n_violations": 0,
                    "exact_noise_replay_ok": True,
                    "bounds_ok_all_positions": True}
                for n in ("model", "validation")}},
        "global_k_audit": {
            "contract_version": "v9", "contract_digest": "d9",
            "graph_integrity_ok": True, "n_eligible_cells": 9,
            "T_obs": 2.5, "argmax_cell": "m/v9",
            "final": {"tier": "tier2", "verdict": "PASS",
                      "indeterminate": False},
            "verdict": "PASS", "pass": True},
        "once_vs_attempts": {
            "model_mode": "once", "validation_mode": "attempts",
            "first_pass_bitwise_check": {
                "n_blocks_checked": 4, "n_mismatches": 0,
                "bitwise_ok": True},
            "recall_model": RECALL, "recall_validation": RECALL,
            "abs_diff": 0.0, "tolerance": RECALL_TOL,
            "recall_modes_consistent": True,
            "k_mean_model": 2.0, "k_mean_validation": 2.0,
            "k_abs_diff": 0.0, "k_tolerance": 0.05,
            "k_modes_consistent": True},
        "aggregate_recompute_ok": True,
        "checks": {k: True for k in AUDIT_REQUIRED_CHECK_NAMES},
    }


def mk(fn):
    r = base()
    fn(r)
    return r


def run(tag, mutate, fixture=False, expect=None):
    r = base()
    mutate(r)
    if fixture:
        r["engineering_fixture"] = True
    out = rec(r)
    ok = True
    notes = []
    if expect == "reject" and out["all_consistent"] is not False:
        ok = False
        notes.append("EXPECTED-REJECT-BUT-PASSED")
    if expect == "pass" and out["all_consistent"] is not True:
        ok = False
        notes.append("EXPECTED-PASS-BUT-REJECTED")
    RESULTS.append((tag, expect, out["all_consistent"], ok))
    print("--- " + tag + " fixture=" + str(fixture)
          + " all_consistent=" + str(out["all_consistent"])
          + " => " + ("OK" if ok else "VIOLATION " + ";".join(notes)))
    for d in out["threshold_discrepancies"]:
        print("    disc: " + d)
    if out["fixture_delegated"]:
        print("    delegated: " + str(out["fixture_delegated"]))
    return out


def p1(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"5": NE}
run("P1 hist-mean-contradiction(val {5:120} vs declared mean 2.0)",
    p1, expect="reject")


def p2(r):
    r["direct_generator"]["model"]["aggregate"][
        "k_histogram"] = {"2": NE - 1}
run("P2 hist-total-contradiction(model {2:119} vs n_events 120)", p2,
    expect="reject")


def p3(r):
    r["direct_generator"]["model"]["aggregate"][
        "k_histogram"] = {"2": 119.5}
run("P3 fractional-count(model {2:119.5})", p3, expect="reject")
run("P3b fractional-count UNDER fixture", p3, fixture=True,
    expect="reject")


def p3n(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"2": 130, "9": -10}
run("P3n negative-count(val {2:130,9:-10})", p3n, expect="reject")


def p4(r):
    r["global_k_audit"]["graph_integrity_ok"] = False
run("P4 gk-integrity-false-with-PASS", p4, expect="reject")


def p4b(r):
    r["global_k_audit"]["verdict"] = "FAIL"
    r["global_k_audit"]["pass"] = False
    del r["global_k_audit"]["final"]
    r["checks"]["global_k_audit_pass"] = False
out4b = run("P4b control gk-FAIL-early-exit-no-final(declared "
            "consistent)", p4b, expect="pass")
assert not any("global_k" in d
               for d in out4b["threshold_discrepancies"]), \
    "P4b unexpected gk disc"
print("    P4b no gk-hierarchy disc confirmed")


def p5(r):
    del r["global_k_audit"]["final"]
run("P5 gk-PASS-missing-final no-fixture", p5, expect="reject")
o5f = run("P5b gk-PASS-missing-final fixture", p5, fixture=True,
          expect="pass")
assert o5f["fixture_delegated"] == ["global_k_audit.final"], \
    "P5b delegated=" + str(o5f["fixture_delegated"])
print("    P5b delegated exactly [global_k_audit.final]")


def p6(r):
    del r["tail_mirror_bound_integrity"]["per_corpus"]["validation"]
run("P6 tail-missing-validation no-fixture", p6, expect="reject")
run("P6b tail-missing-validation fixture(delegated)", p6, fixture=True,
    expect="pass")


def p6c(r):
    r["direct_generator"]["holdout"] = dict(
        r["direct_generator"]["model"])
run("P6c third-corpus-in-context tail-must-cover-holdout", p6c,
    expect="reject")


def p7(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"garbage-key-9": NE}
run("P7 illegal-hist no-fixture", p7, expect="reject")
o7 = run("P7b illegal-hist UNDER fixture(delegation revoked)", p7,
         fixture=True, expect="reject")
assert o7["fixture_mode"] is True, "P7b fixture_mode not True"
assert not any("malformed" in d
               for d in o7["fixture_delegated"]), \
    "P7b malformed delegated: " + str(o7["fixture_delegated"])
assert any("在场非法" in d
           for d in o7["threshold_discrepancies"])
print("    P7b fixture_mode=True, illegal NOT delegated, disc present")


def p8(r):
    m = r["direct_generator"]["model"]["aggregate"]
    v = r["direct_generator"]["validation"]["aggregate"]
    m["k_histogram"] = {"1": 50, "2": 70}
    v["k_histogram"] = {"1": 52, "2": 68}
    m["k_mean"] = KM_M
    v["k_mean"] = KM_V
    ova = r["once_vs_attempts"]
    ova["k_mean_model"] = KM_M
    ova["k_mean_validation"] = KM_V
    ova["k_abs_diff"] = K_DIFF
    ova["k_tolerance"] = TOL_FROZEN
o8 = run("P8 legal-manual-double-key fixture", p8, fixture=True,
         expect="pass")
assert o8["fixture_delegated"] == [], \
    "P8 delegated non-empty: " + str(o8["fixture_delegated"])
print("    P8 passes with ZERO delegation (genuine pass)")
run("P8b legal-manual-double-key no-fixture", p8, expect="pass")


def p9(r):
    p8(r)
    r["direct_generator"]["model"]["aggregate"][
        "k_histogram"] = {"2": 70, "1": 50}
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"2": 68, "1": 52}
o9 = run("P9 permuted-key-order fixture", p9, fixture=True,
         expect="pass")
assert rec(mk(p8))["recomputed"] == rec(mk(p9))["recomputed"], \
    "P9 permutation changed recomputed values"
print("    P9 recomputed identical under permutation: True")


def p10(r):
    del r["direct_generator"]["model"]["aggregate"]["k_histogram"]
run("P10 missing-hist-block fixture(delegate)", p10, fixture=True,
    expect="pass")
run("P10b missing-hist-block no-fixture(reject)", p10,
    expect="reject")


def p11a(r):
    r["direct_generator"]["model"]["aggregate"][
        "k_histogram"] = {"2": str(NE)}
run("P11a observation string-count {'2':'120'}", p11a)


def p11b(r):
    r["direct_generator"]["model"]["aggregate"][
        "k_histogram"] = {"2": True, "3": NE - 1}
run("P11b observation bool-count {2:True,3:119}", p11b)

old_path = "/mnt/f/trading/tmp_r8/reviewer/wsl_tmp/old_cue_r8_044a0307.py"
spec = importlib.util.spec_from_file_location("old_cue_r8", old_path)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
new_dig = M.cue_semantic_contract_digest()
old_dig = old.cue_semantic_contract_digest()
print("P12 semantic-contract digest new=" + new_dig)
print("P12 semantic-contract digest old=" + old_dig)
same = new_dig == old_dig
RESULTS.append(("P12 digest-domain-unchanged", "pass", same, same))
print("P12 digest domain unchanged: " + str(same))

print("==== SUMMARY ====")
fails = [t for (t, e, a, ok) in RESULTS if not ok]
for (t, e, a, ok) in RESULTS:
    print(("PASS " if ok else "FAIL ") + t + " expect=" + str(e)
          + " actual=" + str(a))
print("probe-verdict: " + ("ALL-OK" if not fails else
                           "VIOLATIONS: " + ";".join(fails)))
sys.exit(0 if not fails else 3)
