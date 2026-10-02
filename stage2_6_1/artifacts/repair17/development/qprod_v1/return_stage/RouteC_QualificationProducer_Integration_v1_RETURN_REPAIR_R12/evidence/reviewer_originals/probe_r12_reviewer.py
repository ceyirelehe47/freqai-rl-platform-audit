# -*- coding: utf-8 -*-
"""Independent reviewer probe - QProd R12 (C24=6261d5ef) gate-vs-declaration.

Self-contained fixture (constructed here, not imported from any main-agent
script). Loads the DEPLOYED candidate function (C24 bytes) plus C22/C23
shadows extracted from git, and exercises the addendum (10) invariants.
"""
import hashlib
import importlib.util
import sys

DEPLOY = ("/home/cryptorl/projects/crypto_rl/src/rl_curriculum/"
          "curriculum261_r17_cue_contract.py")
SHADOW_C22 = "/mnt/f/trading/tmp_r12/reviewer/cue_c22_58d1a9ce.py"
SHADOW_C23 = "/mnt/f/trading/tmp_r12/reviewer/cue_c23_4566c23d.py"


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


m_c24 = load(DEPLOY, "cue_c24_reviewer")
m_c22 = load(SHADOW_C22, "cue_c22_reviewer")
m_c23 = load(SHADOW_C23, "cue_c23_reviewer")

REC = m_c24.recompute_audit_semantics_from_report
REQ = m_c24.AUDIT_REQUIRED_CHECK_NAMES

print("imports:")
print("  c24(deploy) sha256=%s name=%s" % (sha(DEPLOY), m_c24.__name__))
print("  c22(shadow) sha256=%s name=%s" % (sha(SHADOW_C22), m_c22.__name__))
print("  c23(shadow) sha256=%s name=%s" % (sha(SHADOW_C23), m_c23.__name__))
print("  AUDIT_MC_ABS_TOL=%r AUDIT_DIFF_TOL_FLOOR=%r "
      "AUDIT_DIFF_SE_FACTOR=%r _REPLAY_TOL_REF=%r"
      % (m_c24.AUDIT_MC_ABS_TOL, m_c24.AUDIT_DIFF_TOL_FLOOR,
         m_c24.AUDIT_DIFF_SE_FACTOR, m_c24._REPLAY_TOL_REF))
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


FNS = {"c24": lambda r: REC(r),
       "c23": lambda r: m_c23.recompute_audit_semantics_from_report(r),
       "c22": lambda r: m_c22.recompute_audit_semantics_from_report(r)}


def run(tag, maker, mods=("c24",)):
    outs = []
    first = ""
    deleg = []
    for m in mods:
        r = maker()
        try:
            o = FNS[m](r)
            outs.append("%s=%s" % (m, o["all_consistent"]))
            if m == "c24":
                first = (o["threshold_discrepancies"][:1] or [""])[0]
                deleg = [d for d in o["fixture_delegated"]
                         if "once_vs_attempts" in d]
        except Exception as exc:  # noqa: BLE001
            outs.append("%s=EXC(%s)" % (m, type(exc).__name__))
            first = "EXC"
            deleg = []
    print("%-52s %s" % (tag, "  ".join(outs)))
    if first:
        print("%-52s   disc: %s" % ("", first))
        if deleg:
            print("%-52s   deleg(ova): %s" % ("", deleg))


print("=== A. 1/4 (model K=1 validation K=4 real diff 3 > 0.05) fixture "
      "-> all REJECT ===")
run("A1 full kad=3 kt=0.05", lambda: build(1, 4, 3.0))
run("A2 del k_abs_diff", lambda: build(1, 4, None, del_kad=True))
run("A3 del k_abs_diff + del k_tolerance",
    lambda: build(1, 4, None, del_kad=True, del_kt=True))
print("=== A'. 1/4 non-fixture (formal) -> all REJECT ===")
run("A4 full kad=3 (no fixture)",
    lambda: build(1, 4, 3.0, fixture=False))
run("A5 del k_abs_diff (no fixture)",
    lambda: build(1, 4, None, del_kad=True, fixture=False))
run("A6 del kad+kt (no fixture)",
    lambda: build(1, 4, None, del_kad=True, del_kt=True,
                  fixture=False))
print()
print("=== B. 4/1 symmetric (model K=4 validation K=1) -> all REJECT ===")
run("B1 full kad=3", lambda: build(4, 1, 3.0))
run("B2 del k_abs_diff", lambda: build(4, 1, None, del_kad=True))
run("B3 del k_abs_diff + del k_tolerance",
    lambda: build(4, 1, None, del_kad=True, del_kt=True))
print()
print("=== C. legal 1/1 (real diff 0) fixture -> same deletions PASS ===")
run("C1 full kad=0", lambda: build(1, 1, 0.0))
run("C2 del k_abs_diff", lambda: build(1, 1, None, del_kad=True))
run("C3 del k_abs_diff + del k_tolerance",
    lambda: build(1, 1, None, del_kad=True, del_kt=True))
print()
print("=== D. both sides truly missing (ova kv + dg kv deleted) kad=0 ===")
run("D1 fixture -> delegation boundary",
    lambda: build(1, 1, 0.0, del_ova_kv=True, del_dg_kv=True))
run("D2 no-fixture -> REJECT",
    lambda: build(1, 1, 0.0, del_ova_kv=True, del_dg_kv=True,
                  fixture=False))
print()
print("=== E. R10 triple counterexamples must stay rejected (fixture) ===")
run("E1 kad=-0.02 complete", lambda: build(1, 1, -0.02))
run("E2 kad=-0.02 + del k_mean_validation",
    lambda: build(1, 1, -0.02, del_ova_kv=True))
run("E3 kad=0.02 complete", lambda: build(1, 1, 0.02))
run("E4 kad=0.02 + del k_mean_validation",
    lambda: build(1, 1, 0.02, del_ova_kv=True))
run("E5 kad=0.5 complete", lambda: build(1, 1, 0.5))
run("E6 kad=0.5 + del kv + del k_tolerance",
    lambda: build(1, 1, 0.5, del_ova_kv=True, del_kt=True))
print()
print("=== F. R11 legal delegation (kad=0) must PASS (fixture) ===")
run("F1 kad=0 + del k_mean_validation",
    lambda: build(1, 1, 0.0, del_ova_kv=True))
run("F2 kad=0 + del kv + del k_tolerance",
    lambda: build(1, 1, 0.0, del_ova_kv=True, del_kt=True))
print()
print("=== G. paired pre/post: C22 vs C23 vs C24 ===")
run("G1 1/4 del k_abs_diff",
    lambda: build(1, 4, None, del_kad=True), mods=("c22", "c23", "c24"))
run("G2 1/4 del kad+kt",
    lambda: build(1, 4, None, del_kad=True, del_kt=True),
    mods=("c22", "c23", "c24"))
run("G3 4/1 del k_abs_diff",
    lambda: build(4, 1, None, del_kad=True), mods=("c22", "c23", "c24"))
run("G4 legal 1/1 del k_abs_diff",
    lambda: build(1, 1, None, del_kad=True), mods=("c22", "c23", "c24"))
print()
print("=== H. robustness: non-numeric k_tolerance + frozen bound "
      "unavailable (val histogram deleted) ===")
run("H1 kad present kt='abc' val-hist-del",
    lambda: build(1, 1, 0.0, ktol_value="abc", del_val_hist=True),
    mods=("c22", "c23", "c24"))
run("H2 kad deleted kt='abc' val-hist-del",
    lambda: build(1, 1, None, del_kad=True, ktol_value="abc",
                  del_val_hist=True), mods=("c22", "c23", "c24"))
run("H3 kad present kt=[0.05] val-hist-del",
    lambda: build(1, 1, 0.0, ktol_value=[0.05], del_val_hist=True),
    mods=("c22", "c23", "c24"))
print()
print("=== I. ova derived means deleted (dg fallback provides both) ===")
run("I1 kad=3 del both ova k_mean (1/4 via dg)",
    lambda: build(1, 4, 3.0, del_ova_kv=True))
print()
print("done")
