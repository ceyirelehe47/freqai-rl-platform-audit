# -*- coding: utf-8 -*-
"""Fixture-mode hole check: 6 combinations on one tree (argv[1]=tag).

Run against C20 bytes -> expect all_consistent=True (escape);
run against C21 bytes -> expect all_consistent=False (reject with
bad-piece reason, not merely missing-piece).
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, "src")
from rl_curriculum.curriculum261_r17_cue_contract import (  # noqa: E402
    recompute_audit_semantics_from_report as rec,
    AUDIT_REQUIRED_CHECK_NAMES,
)

OUT = sys.argv[1] if len(sys.argv) > 1 else "holes_out"
TAG = sys.argv[2] if len(sys.argv) > 2 else "tree"
os.makedirs(OUT, exist_ok=True)

HM = {"1.0": 60, "2.0": 50}
NEV = 110
KM = 160.0 / NEV
SE = 0.02
RECALL_TOL = max(3.0 * math.sqrt(SE * SE + SE * SE), 0.005)
DIFF_TOL = max(3.0 * SE, 0.005)


def _vals(h):
    out = []
    for k, c in h.items():
        out.extend([float(k)] * int(c))
    return out


def frozen_k_tol(hm, hv):
    a, b = np.array(_vals(hm)), np.array(_vals(hv))
    pooled = math.sqrt(
        float(np.var(a, ddof=1)) / len(a)
        + float(np.var(b, ddof=1)) / len(b))
    return max(3.0 * pooled, 0.05)


K_TOL = frozen_k_tol(HM, HM)


def legal_report():
    return {
        "p_contract": 0.5,
        "monte_carlo": {"p_hat": 0.5, "tolerance": 0.001},
        "direct_generator": {
            n: {
                "block_cluster": {"se": SE, "ci95": [0.44, 0.56]},
                "empirical_recall": 0.5,
                "analytic_conditional": 0.5,
                "diff_tolerance": DIFF_TOL,
                "replay_ok": True, "bounds_ok": True,
                "cue_table_consistent_across_rungs": True,
                "max_replay_abs_error": 0.0,
                "aggregate": {
                    "k_mean": KM, "n_detected": NEV, "n_events": NEV,
                    "k_histogram": dict(HM)},
                "tail": {"n_events": 0},
            } for n in ("model", "validation")
        },
        "tail_mirror_bound_integrity": {
            "pass": True,
            "per_corpus": {
                n: {"ok": True, "violations": [], "n_violations": 0,
                    "exact_noise_replay_ok": True,
                    "bounds_ok_all_positions": True}
                for n in ("model", "validation")
            },
        },
        "global_k_audit": {
            "contract_version": "v1", "contract_digest": "d",
            "graph_integrity_ok": True, "n_eligible_cells": 4,
            "T_obs": 1.5, "argmax_cell": "m/v1",
            "final": {"tier": "tier2", "verdict": "PASS",
                      "indeterminate": False},
            "verdict": "PASS", "pass": True,
        },
        "once_vs_attempts": {
            "model_mode": "once", "validation_mode": "attempts",
            "first_pass_bitwise_check": {
                "n_blocks_checked": 2, "n_mismatches": 0,
                "bitwise_ok": True},
            "recall_model": 0.5, "recall_validation": 0.5,
            "abs_diff": 0.0, "tolerance": RECALL_TOL,
            "recall_modes_consistent": True,
            "k_mean_model": KM, "k_mean_validation": KM,
            "k_abs_diff": 0.0, "k_tolerance": K_TOL,
            "k_modes_consistent": True,
        },
        "aggregate_recompute_ok": True,
        "checks": {k: True for k in AUDIT_REQUIRED_CHECK_NAMES},
    }


def del_ova(r):
    del r["once_vs_attempts"]


def m_h1a(r):
    del_ova(r)
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"nan": NEV}


def m_h1b(r):
    del_ova(r)
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"4.0": NEV}


def m_h1c(r):
    del_ova(r)
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"]["n_events"] = 110.5


def m_h2b(r):
    r["once_vs_attempts"]["k_mean_model"] = float("nan")
    del r["once_vs_attempts"]["k_mean_validation"]


def m_h2c(r):
    r["once_vs_attempts"]["k_mean_validation"] = "nan"
    del r["once_vs_attempts"]["k_mean_model"]


def m_h3b(r):
    r["direct_generator"]["validation"]["aggregate"]["n_events"] = -1
    del r["direct_generator"]["validation"]["aggregate"]["k_histogram"]


CASES = [("H1aF no-ova+nan-key", m_h1a),
         ("H1bF no-ova+hist-mean4", m_h1b),
         ("H1cF no-ova+nev-110.5", m_h1c),
         ("H2bF km-NaN other-del", m_h2b),
         ("H2cF kv-nan-str other-del", m_h2c),
         ("H3bF nev--1 same-hist-del", m_h3b)]

rows = []
for tag, m in CASES:
    r = legal_report()
    m(r)
    r["engineering_fixture"] = True
    o = rec(r)
    rows.append({"tree": TAG, "case": tag,
                 "all_consistent": o["all_consistent"],
                 "fixture_mode": o["fixture_mode"],
                 "discrepancies": o["threshold_discrepancies"],
                 "fixture_delegated": o["fixture_delegated"]})
    print("%-30s all=%s" % (tag, o["all_consistent"]))
with open(os.path.join(OUT, "holes_%s.jsonl" % TAG), "w",
          encoding="utf-8") as f:
    for row in rows:
        f.write(json.dumps(row, ensure_ascii=False, default=repr) + "\n")
