#!/usr/bin/env python3
"""汇总 R13 正式链报告数值。"""
import json
from pathlib import Path

ART = (Path.home() / "projects/crypto_rl/artifacts/"
       "route_c_stage2_6_1_repair13")

cue = json.loads((ART / "cue_contract_audit.json").read_text())
print("cue.model.recall:", round(
    cue["direct_generator"]["model"]["empirical_recall"], 6),
    "CI", [round(x, 6) for x in cue["direct_generator"]["model"][
        "block_cluster"]["ci95"]])
print("cue.validation.recall:", round(
    cue["direct_generator"]["validation"]["empirical_recall"], 6))
ova = cue["once_vs_attempts"]
print("once_vs_attempts bitwise_ok:", ova["first_pass_bitwise_check"][
    "bitwise_ok"], "n:", ova["first_pass_bitwise_check"][
    "n_blocks_checked"])
gk = cue["global_k_audit"]
f = gk.get("final") or {}
print("gk: cells", gk.get("n_cells"), "T_obs", round(
    gk.get("T_obs", 0), 4), "p", round(f.get("p_global", 0), 6),
    "B", f.get("n_null_replicates"), "verdict", f.get("verdict"))
cp = f.get("clopper_pearson") or gk.get("clopper_pearson") or {}
print("gk CP99:", cp if cp else "(见 artifact)")
tail = json.loads((ART / "tail_mirror_bound_integrity.json").read_text())
print("tail: pass", tail.get("pass"), "events",
      {k: v.get("n_events") for k, v in tail.items()
       if isinstance(v, dict) and "n_events" in v})

sel = json.loads((ART / "r13_sample_size_selection.json").read_text())
print("design: selected", sel["selected_candidate"], "n",
      sel["selected_block_count"], "qualified",
      sel["qualified_combinations"], "maximin",
      round(sel["maximin_score"], 4))

gate = json.loads((ART / "robustness_gate.json").read_text())
print("robustness:", {k: v for k, v in gate.items()
                      if isinstance(v, bool)})

sup = json.loads((ART / "supervised_learnability_main.json").read_text())
suph = json.loads(
    (ART / "supervised_learnability_holdout.json").read_text())
print("supervised main pass:", sup.get("pass"),
      "holdout pass:", suph.get("pass"))

ev = json.loads((ART / "generation_evidence_completeness.json").read_text())
print("gen evidence:", {k: ev[k] for k in (
    "expected_calls", "observed_calls", "missing_calls",
    "orphan_calls", "bad_envelopes", "n_problems", "pass")})

ns = json.loads(
    (ART / "seed_namespace_integrity_post_final.json").read_text())
print("ns post-final pass:", ns.get("pass"),
      "exposed:", ns.get("qualification_r13_exposed"),
      "aborted:", ns.get("iteration_aborted"))

q = json.loads((ART / "qualification_result.json").read_text())
print("final: verdict", q["verdict"], "blocks", q["selected_block_count"],
      "core_pairs", q["core_qualification_pairs"],
      "indep_pairs", q["c2_independent_guard_pairs"],
      "semantic_blocks", q["semantic_blocks"],
      "ref_equiv_episodes", q["reference_equivalence_episodes"],
      "unexplained", q["reference_equivalence_unexplained"])
semd = json.loads((ART / "qualification_cue_semantics.json").read_text()) \
    if (ART / "qualification_cue_semantics.json").is_file() else {}
print("qual cue semantics(LCB gate):", semd.get("pass"),
      "recall", semd.get("recall") if "recall" in semd else
      {k: round(v, 5) for k, v in semd.items()
       if isinstance(v, float)} if semd else "n/a")
