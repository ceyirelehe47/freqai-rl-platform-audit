# R11 reviewer independent probe: Q1 derived-diff dependency invariant.
# Zero native / zero generation / zero fit / zero optimizer / zero model load.
# Synthetic reports only; recomputes audit semantics from report values.
# usage: 02_probe.py <mode>   mode=c23 (deployed C23 bytes) | c22 (pre-fix shadow pkg)
import hashlib
import json
import math
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "c23"
if MODE == "c22":
    sys.path.insert(0, "/tmp/r11rev_c22_pkg")
sys.path.insert(1, "/home/cryptorl/projects/crypto_rl/src")
import rl_curriculum.curriculum261_r17_cue_contract as cc  # noqa: E402

_sha = hashlib.sha256(open(cc.__file__, "rb").read()).hexdigest()
print("mode=%s module=%s sha256=%s" % (MODE, cc.__file__, _sha))
rec = cc.recompute_audit_semantics_from_report
REQ = list(cc.AUDIT_REQUIRED_CHECK_NAMES)


def frozen_kt(hists, n_events):
    """Frozen bound max(3*pooled_se, 0.05) recomputed independently."""
    ks = []
    for h in hists:
        vals = []
        for k, c in h.items():
            vals.extend([float(k)] * int(c))
        ks.append(vals)
    import numpy as np
    pooled = math.sqrt(
        float(np.var(np.array(ks[0]), ddof=1)) / len(ks[0])
        + float(np.var(np.array(ks[1]), ddof=1)) / len(ks[1]))
    return max(3.0 * pooled, 0.05)


def legal(multi_key=False):
    """Addendum (9) support: both corpora k_mean=1, hist {"1":110},
    n_events=110 -> derivable abs-diff 0, frozen K tol 0.05."""
    if multi_key:
        hist = {"1": 55, "2": 55}
        km = 1.5
        kt = frozen_kt([hist, hist], 110)
    else:
        hist = {"1": 110}
        km = 1.0
        kt = 0.05
    recall_tol = max(3.0 * math.sqrt(0.01 ** 2 + 0.01 ** 2), 0.005)
    dg = {}
    for n in ("model", "validation"):
        dg[n] = {
            "block_cluster": {"se": 0.01, "ci95": [0.45, 0.55]},
            "empirical_recall": 0.5,
            "analytic_conditional": 0.5,
            "diff_tolerance": 0.03,
            "replay_ok": True, "bounds_ok": True,
            "cue_table_consistent_across_rungs": True,
            "max_replay_abs_error": 0.0,
            "aggregate": {"k_mean": km, "n_detected": 1,
                          "n_events": 110, "k_histogram": dict(hist)},
            "tail": {"n_events": 0},
        }
    return {
        "p_contract": 0.5,
        "monte_carlo": {"p_hat": 0.5, "tolerance": 0.001},
        "direct_generator": dg,
        "tail_mirror_bound_integrity": {
            "pass": True,
            "per_corpus": {
                n: {"ok": True, "violations": [], "n_violations": 0,
                    "exact_noise_replay_ok": True,
                    "bounds_ok_all_positions": True}
                for n in ("model", "validation")}},
        "global_k_audit": {
            "contract_version": "v1", "contract_digest": "d",
            "graph_integrity_ok": True, "n_eligible_cells": 4,
            "T_obs": 1.5, "argmax_cell": "m/v1",
            "final": {"tier": "tier2", "verdict": "PASS",
                      "indeterminate": False},
            "verdict": "PASS", "pass": True},
        "once_vs_attempts": {
            "model_mode": "once", "validation_mode": "attempts",
            "first_pass_bitwise_check": {
                "n_blocks_checked": 2, "n_mismatches": 0,
                "bitwise_ok": True},
            "recall_model": 0.5, "recall_validation": 0.5,
            "abs_diff": 0.0, "tolerance": recall_tol,
            "recall_modes_consistent": True,
            "k_mean_model": km, "k_mean_validation": km,
            "k_abs_diff": 0.0, "k_tolerance": kt,
            "k_modes_consistent": True},
        "aggregate_recompute_ok": True,
        "checks": {k: True for k in REQ},
    }


def run(tag, expect_consistent, mutate=None, fixture=True,
        drop_dg_kmean=False, drop_ova=False):
    r = legal()
    if drop_ova:
        del r["once_vs_attempts"]
    if mutate:
        mutate(r)
    if drop_dg_kmean:
        for n in ("model", "validation"):
            del r["direct_generator"][n]["aggregate"]["k_mean"]
    if fixture:
        r["engineering_fixture"] = True
    o = rec(r)
    cons = o["all_consistent"]
    ds = " | ".join(o["threshold_discrepancies"])
    ok = cons == expect_consistent
    print(json.dumps({
        "tag": tag, "fixture": fixture, "all_consistent": cons,
        "expected_consistent": expect_consistent, "ok": ok,
        "ova_consistent": o["recomputed"].get(
            "once_vs_attempts_consistent"),
        "delegated": [d for d in o.get("fixture_delegated", [])
                      if "k_" in d or "once_vs" in d],
        "msg_sample": ds[:220],
    }, ensure_ascii=False))
    return ok


def kad(v):
    def m(r):
        r["once_vs_attempts"]["k_abs_diff"] = v
    return m


def del_(key):
    def m(r):
        del r["once_vs_attempts"][key]
    return m


def seq(*ms):
    def m(r):
        for f in ms:
            f(r)
    return m


results = []
if MODE == "c22":
    # pre-fix escape matrix (C22 bytes): the three holes MUST escape
    results.append(run("C1b kad=-0.02 del_kv", True,
                       seq(kad(-0.02), del_("k_mean_validation"))))
    results.append(run("C2b kad=0.02 del_kv", True,
                       seq(kad(0.02), del_("k_mean_validation"))))
    results.append(run("C3b kad=0.5 del_kv del_kt", True,
                       seq(kad(0.5), del_("k_mean_validation"),
                           del_("k_tolerance"))))
    results.append(run("C1c kad=-0.02 del_km", True,
                       seq(kad(-0.02), del_("k_mean_model"))))
    results.append(run("ctl legal complete", True))
else:
    results.append(run("C1a kad=-0.02 complete", False, kad(-0.02)))
    results.append(run("C1b kad=-0.02 del_kv", False,
                       seq(kad(-0.02), del_("k_mean_validation"))))
    results.append(run("C1c kad=-0.02 del_km", False,
                       seq(kad(-0.02), del_("k_mean_model"))))
    results.append(run("C2a kad=0.02 complete", False, kad(0.02)))
    results.append(run("C2b kad=0.02 del_kv", False,
                       seq(kad(0.02), del_("k_mean_validation"))))
    results.append(run("C2c kad=0.02 del_km", False,
                       seq(kad(0.02), del_("k_mean_model"))))
    results.append(run("C3a kad=0.5 complete", False, kad(0.5)))
    results.append(run("C3b kad=0.5 del_kv del_kt", False,
                       seq(kad(0.5), del_("k_mean_validation"),
                           del_("k_tolerance"))))
    results.append(run("C3c kad=0.5 del_km del_kt", False,
                       seq(kad(0.5), del_("k_mean_model"),
                           del_("k_tolerance"))))
    results.append(run("C4 kad=0 del_kv", True,
                       seq(kad(0.0), del_("k_mean_validation"))))
    results.append(run("C4b kad=0 del_kv del_kt", True,
                       seq(kad(0.0), del_("k_mean_validation"),
                           del_("k_tolerance"))))
    results.append(run("C4c kad=0 del_km del_kt", True,
                       seq(kad(0.0), del_("k_mean_model"),
                           del_("k_tolerance"))))
    # single-field legality is independent of derivation availability:
    results.append(run("M kad=-0.02 both-sides-missing", False,
                       seq(kad(-0.02), del_("k_mean_validation"),
                           del_("k_mean_model")),
                       drop_dg_kmean=True))
    results.append(run("N kad=0.02 both-sides-missing", True,
                       seq(kad(0.02), del_("k_mean_validation"),
                           del_("k_mean_model")),
                       drop_dg_kmean=True))
    results.append(run("N-nofix both-sides-missing", False,
                       seq(kad(0.02), del_("k_mean_validation"),
                           del_("k_mean_model")),
                       fixture=False, drop_dg_kmean=True))
    # no-fixture paths
    results.append(run("O nofix legal complete", True, fixture=False))
    results.append(run("P nofix kad=0.5 del_kv", False,
                       seq(kad(0.5), del_("k_mean_validation")),
                       fixture=False))
    # frozen bound recomputed from histograms, self-report drift rejected
    results.append(run("Q wrong self kt=0.9", False,
                       seq(lambda r: r["once_vs_attempts"]
                           .__setitem__("k_tolerance", 0.9))))
    # consistency separate from bound: within bound but != derived 0
    results.append(run("R kad=0.04 within-bound mismatch", False,
                       kad(0.04)))
    # in-present bad support not cleansed by ova delegation (R10 keep)
    results.append(run("S bad-hist + ova-missing", False,
                       lambda r: (
                           r["direct_generator"]["model"]["aggregate"]
                           .__setitem__("k_histogram",
                                        {"1": 100, "2": 5})),
                       drop_ova=True))
    # single-key NaN prior (R9 keep)
    results.append(run("T k_mean_model=NaN", False,
                       seq(lambda r: r["once_vs_attempts"]
                           .__setitem__("k_mean_model",
                                        float("nan")))))
    # legal multi-key support
    r = legal(multi_key=True)
    r["engineering_fixture"] = True
    o = rec(r)
    ok = o["all_consistent"]
    print(json.dumps({"tag": "U multi-key legal", "ok": ok,
                      "all_consistent": o["all_consistent"],
                      "kt_frozen_used": frozen_kt(
                          [{"1": 55, "2": 55}, {"1": 55, "2": 55}],
                          110)}, ensure_ascii=False))
    results.append(ok)
    r = legal(multi_key=True)
    r["engineering_fixture"] = True
    r["once_vs_attempts"]["k_abs_diff"] = 0.02
    del r["once_vs_attempts"]["k_mean_validation"]
    o = rec(r)
    ok = not o["all_consistent"]
    print(json.dumps({"tag": "V multi-key kad=0.02 del_kv",
                      "ok": ok,
                      "all_consistent": o["all_consistent"],
                      "msg": " | ".join(
                          o["threshold_discrepancies"])[:200]},
                     ensure_ascii=False))
    results.append(ok)

print("SUMMARY %s: %d/%d ok" % (MODE, sum(1 for x in results if x),
                                len(results)))
sys.exit(0 if all(results) else 1)
