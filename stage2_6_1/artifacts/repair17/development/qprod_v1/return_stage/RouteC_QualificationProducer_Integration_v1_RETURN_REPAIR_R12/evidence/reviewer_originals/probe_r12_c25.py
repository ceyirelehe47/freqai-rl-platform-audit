# -*- coding: utf-8 -*-
"""R12-P2 re-verification: 4-way C22/C23/C24/C25 on the addendum(10)
matrix + malformed-value robustness.  Deploy = C25.  Independent fixture."""
import hashlib
import importlib.util
import sys

DEPLOY_C25 = ("/home/cryptorl/projects/crypto_rl/src/rl_curriculum/"
              "curriculum261_r17_cue_contract.py")
S = "/mnt/f/trading/tmp_r12/reviewer/"
PATHS = {
    "c22": S + "cue_c22_58d1a9ce.py",
    "c23": S + "cue_c23_4566c23d.py",
    "c24": S + "cue_c24_6261d5ef.py",
    "c25": DEPLOY_C25,
}


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MODS = {k: load(p, "cue_%s_r12p2" % k) for k, p in PATHS.items()}
REQ = MODS["c25"].AUDIT_REQUIRED_CHECK_NAMES
print("candidate bytes:")
for k in ("c22", "c23", "c24", "c25"):
    print("  %s sha256=%s" % (k, sha(PATHS[k])))
print("  c25 pyfile=%s" % MODS["c25"].__file__)
print()


def base_report():
    return {
        "p_contract": 0.5,
        "monte_carlo": {"p_hat": 0.5, "tolerance": 0.001},
        "direct_generator": {
            n: {
                "block_cluster": {"se": 0.01, "ci95": [0.45, 0.55]},
                "empirical_recall": 0.5,
                "analytic_conditional": 0.5,
                "diff_tolerance": 0.03,
                "replay_ok": True, "bounds_ok": True,
                "cue_table_consistent_across_rungs": True,
                "max_replay_abs_error": 0.0,
                "aggregate": {"k_mean": 1.0, "n_detected": 1,
                              "n_events": 110,
                              "k_histogram": {"1": 110}},
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
            "abs_diff": 0.0, "tolerance": 0.042426406871192854,
            "recall_modes_consistent": True,
            "k_mean_model": 1.0, "k_mean_validation": 1.0,
            "k_abs_diff": 0.0, "k_tolerance": 0.05,
            "k_modes_consistent": True},
        "aggregate_recompute_ok": True,
        "checks": {k: True for k in REQ},
    }


def set_k(r, km, kv):
    ova = r["once_vs_attempts"]
    ova["k_mean_model"], ova["k_mean_validation"] = float(km), float(kv)
    dgm = r["direct_generator"]["model"]["aggregate"]
    dgv = r["direct_generator"]["validation"]["aggregate"]
    dgm["k_mean"], dgv["k_mean"] = float(km), float(kv)
    dgm["k_histogram"] = {str(int(km)): 110}
    dgv["k_histogram"] = {str(int(kv)): 110}


def build(km, kv, kad, del_kad=False, del_kt=False, fixture=True,
          del_ova_kv=False, del_dg_kv=False, ktol_value=0.05,
          del_val_hist=False):
    r = base_report()
    # fix accidental key typo guard: normalise key name
    for n in ("model", "validation"):
        blk = r["direct_generator"][n]
        if "cue_table_consistent_across_rungs" in blk:
            blk["cue_table_consistent_across_rungs"] = blk.pop(
                "cue_table_consistent_across_rungs")
    set_k(r, km, kv)
    ova = r["once_vs_attempts"]
    if kad is None:
        ova.pop("k_abs_diff", None)
    else:
        ova["k_abs_diff"] = kad
    if del_kad:
        ova.pop("k_abs_diff", None)
    if del_kt:
        ova.pop("k_tolerance", None)
    elif ktol_value is not None:
        ova["k_tolerance"] = ktol_value
    if del_ova_kv:
        ova.pop("k_mean_validation", None)
    if del_dg_kv:
        r["direct_generator"]["validation"]["aggregate"].pop("k_mean",
                                                             None)
    if del_val_hist:
        r["direct_generator"]["validation"]["aggregate"].pop(
            "k_histogram", None)
    if fixture:
        r["engineering_fixture"] = True
    return r


def call(mod, r):
    try:
        return repr(mod.recompute_audit_semantics_from_report(r)[
            "all_consistent"])
    except Exception as exc:  # noqa: BLE001
        return "EXC(%s)" % type(exc).__name__


CASES = []
def case(tag, maker, expect=None):
    CASES.append((tag, maker, expect))


def anyof(v):
    return v


case("A1 1/4 full kad=3", lambda: build(1, 4, 3.0),
     {"c25": "False"})
case("A2 1/4 del kad", lambda: build(1, 4, None, del_kad=True),
     {"c25": "False"})
case("A3 1/4 del kad+kt",
     lambda: build(1, 4, None, del_kad=True, del_kt=True),
     {"c25": "False"})
case("A4 1/4 full nofixture", lambda: build(1, 4, 3.0, fixture=False),
     {"c25": "False"})
case("A5 1/4 del kad nofixture",
     lambda: build(1, 4, None, del_kad=True, fixture=False),
     {"c25": "False"})
case("A6 1/4 del kad+kt nofixture",
     lambda: build(1, 4, None, del_kad=True, del_kt=True,
                   fixture=False), {"c25": "False"})
case("B1 4/1 full kad=3", lambda: build(4, 1, 3.0), {"c25": "False"})
case("B2 4/1 del kad", lambda: build(4, 1, None, del_kad=True),
     {"c25": "False"})
case("B3 4/1 del kad+kt",
     lambda: build(4, 1, None, del_kad=True, del_kt=True),
     {"c25": "False"})
case("C1 1/1 full kad=0", lambda: build(1, 1, 0.0), {"c25": "True"})
case("C2 1/1 del kad", lambda: build(1, 1, None, del_kad=True),
     {"c25": "True"})
case("C3 1/1 del kad+kt",
     lambda: build(1, 1, None, del_kad=True, del_kt=True),
     {"c25": "True"})
case("D1 both sides missing fixture",
     lambda: build(1, 1, 0.0, del_ova_kv=True, del_dg_kv=True),
     {"c25": "True"})
case("D2 both sides missing nofixture",
     lambda: build(1, 1, 0.0, del_ova_kv=True, del_dg_kv=True,
                   fixture=False), {"c25": "False"})
case("E1 kad=-0.02", lambda: build(1, 1, -0.02), {"c25": "False"})
case("E2 kad=-0.02 del kv",
     lambda: build(1, 1, -0.02, del_ova_kv=True), {"c25": "False"})
case("E3 kad=0.02", lambda: build(1, 1, 0.02), {"c25": "False"})
case("E4 kad=0.02 del kv",
     lambda: build(1, 1, 0.02, del_ova_kv=True), {"c25": "False"})
case("E5 kad=0.5", lambda: build(1, 1, 0.5), {"c25": "False"})
case("E6 kad=0.5 del kv+kt",
     lambda: build(1, 1, 0.5, del_ova_kv=True, del_kt=True),
     {"c25": "False"})
case("F1 kad=0 del kv",
     lambda: build(1, 1, 0.0, del_ova_kv=True), {"c25": "True"})
case("F2 kad=0 del kv+kt",
     lambda: build(1, 1, 0.0, del_ova_kv=True, del_kt=True),
     {"c25": "True"})
case("G1 1/4 del kad",
     lambda: build(1, 4, None, del_kad=True),
     {"c22": "False", "c23": "True", "c24": "False", "c25": "False"})
case("G2 1/4 del kad+kt",
     lambda: build(1, 4, None, del_kad=True, del_kt=True),
     {"c22": "False", "c23": "True", "c24": "False", "c25": "False"})
case("G3 4/1 del kad",
     lambda: build(4, 1, None, del_kad=True),
     {"c22": "False", "c23": "True", "c24": "False", "c25": "False"})
case("G4 1/1 del kad",
     lambda: build(1, 1, None, del_kad=True),
     {"c22": "True", "c23": "True", "c24": "True", "c25": "True"})
case("I1 1/4 del both ova k_mean (dg fallback)",
     lambda: build(1, 4, 3.0, del_ova_kv=True), {"c25": "False"})
case("H1 kad on kt='abc' vhist-del (pre-existing crash)",
     lambda: build(1, 1, 0.0, ktol_value="abc", del_val_hist=True))
case("H2 kad off kt='abc' vhist-del",
     lambda: build(1, 1, None, del_kad=True, ktol_value="abc",
                   del_val_hist=True),
     {"c24": "EXC(ValueError)", "c25": "False"})
case("H3 kad on kt=[0.05] vhist-del",
     lambda: build(1, 1, 0.0, ktol_value=[0.05], del_val_hist=True))
case("J2 kad off kt='abc' frozen avail",
     lambda: build(1, 1, None, del_kad=True, ktol_value="abc"),
     {"c25": "False"})
case("J3 kad off kt='abc' frozen unavail",
     lambda: build(1, 1, None, del_kad=True, ktol_value="abc",
                   del_val_hist=True),
     {"c24": "EXC(ValueError)", "c25": "False"})
case("J4 kad off kt=nan frozen unavail",
     lambda: build(1, 1, None, del_kad=True, ktol_value=float("nan"),
                   del_val_hist=True), {"c25": "False"})
case("J5 kad off kt off frozen unavail",
     lambda: build(1, 1, None, del_kad=True, del_kt=True,
                   del_val_hist=True), {"c25": "True"})
case("J6 kad off kt='abc' frozen unavail nofixture",
     lambda: build(1, 1, None, del_kad=True, ktol_value="abc",
                   del_val_hist=True, fixture=False),
     {"c24": "EXC(ValueError)", "c25": "False"})

print("%-52s %-8s %-8s %-8s %-8s %s"
      % ("case", "c22", "c23", "c24", "c25", "expect"))
bad = 0
for tag, maker, expect in CASES:
    vals = {k: call(MODS[k], maker()) for k in ("c22", "c23", "c24",
                                                "c25")}
    ok = "-"
    if expect:
        ok = "OK"
        for k, v in expect.items():
            if vals[k] != v:
                ok = "MISMATCH"
                bad += 1
    print("%-52s %-8s %-8s %-8s %-8s %s"
          % (tag, vals["c22"], vals["c23"], vals["c24"], vals["c25"],
             ok if expect else ""))

print()
print("expectation mismatches:", bad)

# direct semantic equivalence C25 vs C23 on H2/J3/J6 family
print()
print("C23 vs C25 equivalence on H2/J3/J6 family:")
for tag, mk in (("H2", lambda: build(1, 1, None, del_kad=True,
                                     ktol_value="abc",
                                     del_val_hist=True)),
                ("J3", lambda: build(1, 1, None, del_kad=True,
                                     ktol_value="abc",
                                     del_val_hist=True)),
                ("J6", lambda: build(1, 1, None, del_kad=True,
                                     ktol_value="abc",
                                     del_val_hist=True,
                                     fixture=False))):
    v23 = call(MODS["c23"], mk())
    v25 = call(MODS["c25"], mk())
    print("  %s c23=%s c25=%s equivalent=%s" % (tag, v23, v25,
                                                v23 == v25))
print("done")
