# Reviewer adversarial probe for QProd R5 (C15) - independent variants, not the 3 numbered cases.
import sys, json, tempfile, math
sys.path.insert(0, "src"); sys.path.insert(0, "tests/route_c_stage2_6_1"); sys.path.insert(0, "tests/route_c_stage2_6_2")
from pathlib import Path
import test_curriculum261_qprod_levela as tl
from rl_curriculum.curriculum261_qprod_context import QProdRunSession
from rl_curriculum.curriculum261_qprod_levela import run_level_a_rehearsal, judge_qualification_gates
from rl_curriculum.curriculum261_r17_cue_contract import (
    cue_contract_audit_digest, recompute_audit_semantics_from_report,
    AUDIT_DIFF_TOL_FLOOR, AUDIT_REQUIRED_CHECK_NAMES)

def rehearse(tmp):
    ctx = tl._ctx(tmp)
    s = QProdRunSession(ctx.state_root, level="level_a", iteration_id=ctx.iteration_id)
    s.acquire({"entry": "t"})
    run_level_a_rehearsal(ctx, s, tl._fixture_inputs(tmp))
    return ctx

def gate1(ctx):
    plan = json.loads((ctx.state_root / "qprod_qualification_plan.json").read_text(encoding="utf-8"))
    return judge_qualification_gates(ctx.artifact_root, plan)

def load_cue(ctx):
    p = ctx.artifact_root / "cue_contract_audit.json"
    return p, json.loads(p.read_text(encoding="utf-8"))

def save_cue(p, cue):
    cue["checks"] = {k: True for k in cue["checks"]}
    cue["pass"] = True
    cue["audit_digest"] = cue_contract_audit_digest(cue)
    p.write_text(json.dumps(cue), encoding="utf-8")

fails = []
def check(name, cond, extra=""):
    print("%-32s %s %s" % (name, "OK" if cond else "VIOLATION", extra))
    if not cond:
        fails.append(name)

with tempfile.TemporaryDirectory() as tds:
    # v0 legal control: untouched rehearsal must PASS; delegation honest+listed
    d = Path(tds) / "v0"; d.mkdir(parents=True); ctx = rehearse(d); raw = gate1(ctx)
    o = raw["gates"]["cue_audit_pass"]["observed"]
    det = o.get("frozen_semantics_detail", {})
    dlg = sorted(det.get("fixture_delegated", []))
    check("v0-legal-control-PASS", raw["verdict"] == "PASS",
          "verdict=%s sem=%s fixture_mode=%s delegated_n=%d" % (
              raw["verdict"], o["semantics_consistent"], det.get("fixture_mode"), len(dlg)))
    print("   delegated_full:", dlg)

    # v1 ova inserted fully self-consistent, then tolerance field drifted to 0.9
    d = Path(tds) / "v1"; d.mkdir(parents=True); ctx = rehearse(d)
    p, cue = load_cue(ctx)
    dg = cue["direct_generator"]
    rm = dg["model"]["empirical_recall"]; rv = dg["validation"]["empirical_recall"]
    se_m = float(dg["model"]["block_cluster"]["se"]); se_v = float(dg["validation"]["block_cluster"]["se"])
    tol = max(3.0 * math.sqrt(se_m * se_m + se_v * se_v), AUDIT_DIFF_TOL_FLOOR)
    cue["once_vs_attempts"] = {
        "recall_model": rm, "recall_validation": rv, "abs_diff": abs(rm - rv),
        "tolerance": 0.9,  # drift vs frozen formula
        "recall_modes_consistent": True, "k_modes_consistent": True,
        "first_pass_bitwise_check": {"bitwise_ok": True}}
    save_cue(p, cue); raw = gate1(ctx); o = raw["gates"]["cue_audit_pass"]["observed"]
    check("v1-ova-tol-drift-FAIL", raw["verdict"] == "FAIL" and o["semantics_consistent"] is False,
          "verdict=%s sem=%s tol_drift=%s ova_rec=%s" % (
              raw["verdict"], o["semantics_consistent"],
              any("阈值漂移" in x for x in o["threshold_drift"]),
              o["frozen_semantics_recomputed"].get("once_vs_attempts_consistent")))

    # v2 ti inserted: violations non-empty but n_violations=0, ok=True
    d = Path(tds) / "v2"; d.mkdir(parents=True); ctx = rehearse(d)
    p, cue = load_cue(ctx)
    cue["tail_mirror_bound_integrity"] = {"pass": True, "per_corpus": {
        n: {"ok": True, "violations": (["mirror:pos3"] if n == "validation" else []),
            "n_violations": 0, "exact_noise_replay_ok": True,
            "bounds_ok_all_positions": True}
        for n in ("model", "validation")}}
    save_cue(p, cue); raw = gate1(ctx); o = raw["gates"]["cue_audit_pass"]["observed"]
    check("v2-ti-count-mismatch-FAIL", raw["verdict"] == "FAIL",
          "verdict=%s ti_rec=%s" % (
              raw["verdict"],
              o["frozen_semantics_recomputed"].get("tail_mirror_bound_integrity_pass")))

    # v3 bad replay shadow WITH replay_ok=True kept, validation corpus only
    d = Path(tds) / "v3"; d.mkdir(parents=True); ctx = rehearse(d)
    p, cue = load_cue(ctx)
    cue["direct_generator"]["validation"]["max_replay_abs_error"] = 0.4
    cue["direct_generator"]["validation"]["replay_ok"] = True
    save_cue(p, cue); raw = gate1(ctx); o = raw["gates"]["cue_audit_pass"]["observed"]
    rc = o["frozen_semantics_recomputed"]
    check("v3-bad-shadow-true-flag-FAIL",
          raw["verdict"] == "FAIL" and rc.get("validation_corpus_ok") is False
          and rc.get("model_corpus_ok") is True,
          "verdict=%s model_ok=%s validation_ok=%s" % (
              raw["verdict"], rc.get("model_corpus_ok"), rc.get("validation_corpus_ok")))

    # v4 gk inserted: pass=True but verdict=INDETERMINATE
    d = Path(tds) / "v4"; d.mkdir(parents=True); ctx = rehearse(d)
    p, cue = load_cue(ctx)
    cue["global_k_audit"] = {"pass": True, "verdict": "INDETERMINATE"}
    save_cue(p, cue); raw = gate1(ctx); o = raw["gates"]["cue_audit_pass"]["observed"]
    check("v4-gk-indeterminate-FAIL", raw["verdict"] == "FAIL",
          "verdict=%s not_indet=%s" % (
              raw["verdict"],
              o["frozen_semantics_recomputed"].get("global_k_audit_not_indeterminate")))

    # v5 MC p_hat drift + widened mc tolerance field
    d = Path(tds) / "v5"; d.mkdir(parents=True); ctx = rehearse(d)
    p, cue = load_cue(ctx)
    cue["monte_carlo"]["p_hat"] = float(cue["p_contract"]) + 0.05
    cue["monte_carlo"]["tolerance"] = 1.0
    save_cue(p, cue); raw = gate1(ctx); o = raw["gates"]["cue_audit_pass"]["observed"]
    check("v5-mc-drift-frozen-tol-FAIL",
          raw["verdict"] == "FAIL"
          and o["frozen_semantics_recomputed"].get("mc_close_to_analytic") is False,
          "verdict=%s mc_rec=%s drift_mc=%s" % (
              raw["verdict"],
              o["frozen_semantics_recomputed"].get("mc_close_to_analytic"),
              any("monte_carlo.tolerance" in x for x in o["threshold_drift"])))

    # v6 strip engineering_fixture marker from the rehearsal report (absent support
    # fields then must go False, no delegation): full-gate no-fixture boundary
    d = Path(tds) / "v6"; d.mkdir(parents=True); ctx = rehearse(d)
    p, cue = load_cue(ctx)
    cue.pop("engineering_fixture", None)
    save_cue(p, cue); raw = gate1(ctx); o = raw["gates"]["cue_audit_pass"]["observed"]
    det = o.get("frozen_semantics_detail", {})
    check("v6-fixture-stripped-FAIL", raw["verdict"] == "FAIL"
          and det.get("fixture_mode") is False and det.get("fixture_delegated") == [],
          "verdict=%s sem=%s fixture_mode=%s delegated=%s" % (
              raw["verdict"], o["semantics_consistent"],
              det.get("fixture_mode"), det.get("fixture_delegated")))

    # v7 formal (no fixture marker) direct-helper: missing once_vs_attempts block
    formal = {
        "p_contract": 0.5,
        "monte_carlo": {"p_hat": 0.5, "tolerance": 0.001},
        "direct_generator": {
            n: {"block_cluster": {"se": 0.01, "ci95": [0.45, 0.55]},
                "empirical_recall": 0.5, "analytic_conditional": 0.5,
                "diff_tolerance": 0.03, "replay_ok": True, "bounds_ok": True,
                "cue_table_consistent_across_rungs": True,
                "max_replay_abs_error": 0.0,
                "tail": {"n_events": 0}}
            for n in ("model", "validation")},
        "tail_mirror_bound_integrity": {
            "pass": True,
            "per_corpus": {n: {"ok": True, "violations": [], "n_violations": 0,
                               "exact_noise_replay_ok": True,
                               "bounds_ok_all_positions": True}
                           for n in ("model", "validation")}},
        "global_k_audit": {"pass": True, "verdict": "CP"},
        "aggregate_recompute_ok": True,
    }
    formal["checks"] = {k: True for k in AUDIT_REQUIRED_CHECK_NAMES}
    r = recompute_audit_semantics_from_report(formal)
    check("v7-formal-missing-ova-False",
          r["all_consistent"] is False
          and r["recomputed"]["once_vs_attempts_consistent"] is False
          and r["fixture_mode"] is False and r["fixture_delegated"] == [],
          "ova_rec=%s delegated=%s" % (
              r["recomputed"]["once_vs_attempts_consistent"], r["fixture_delegated"]))

    # v8 ova source mismatch ONLY (validation field drifts +0.01 vs dg)
    d = Path(tds) / "v8"; d.mkdir(parents=True); ctx = rehearse(d)
    p, cue = load_cue(ctx)
    dg = cue["direct_generator"]
    rm = dg["model"]["empirical_recall"]; rv = dg["validation"]["empirical_recall"]
    se_m = float(dg["model"]["block_cluster"]["se"]); se_v = float(dg["validation"]["block_cluster"]["se"])
    tol = max(3.0 * math.sqrt(se_m * se_m + se_v * se_v), AUDIT_DIFF_TOL_FLOOR)
    cue["once_vs_attempts"] = {
        "recall_model": rm, "recall_validation": rv + 0.01,
        "abs_diff": abs(rm - (rv + 0.01)), "tolerance": tol,
        "recall_modes_consistent": True, "k_modes_consistent": True,
        "first_pass_bitwise_check": {"bitwise_ok": True}}
    save_cue(p, cue); raw = gate1(ctx); o = raw["gates"]["cue_audit_pass"]["observed"]
    check("v8-ova-source-mismatch-FAIL",
          raw["verdict"] == "FAIL"
          and o["frozen_semantics_recomputed"].get("once_vs_attempts_consistent") is False,
          "verdict=%s src_drift=%s" % (
              raw["verdict"],
              any("来源不一致" in x for x in o["threshold_drift"])))

print("ADV_SUMMARY:", "ALL_OK" if not fails else "VIOLATIONS=%s" % fails)
