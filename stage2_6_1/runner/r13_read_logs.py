#!/usr/bin/env python3
"""读取 R13 正式链各步日志尾行与关键 artifact 判定。"""
import json
from pathlib import Path

LOGS = Path.home() / "projects/crypto_rl/r13_formal_logs"
ART = (Path.home() / "projects/crypto_rl/artifacts/"
       "route_c_stage2_6_1_repair13")

for f in sorted(LOGS.glob("*.log")):
    tail = f.read_text(encoding="utf-8").strip().splitlines()
    print(f"== {f.name}: {tail[-1] if tail else '(empty)'}")

print()
print("== formal cue audit:")
cue = json.loads((ART / "cue_contract_audit.json").read_text())
gk = cue.get("global_k_audit") or {}
final = gk.get("final") or {}
print("  cue pass:", cue["pass"], "p_contract:", round(
    cue["p_contract"], 6))
print("  global_k pass:", gk.get("pass"), "T_obs:", gk.get("T_obs"),
      "p:", final.get("p_global"), "verdict:", final.get("verdict"))
tm = cue.get("tail_mirror_bound_integrity") or {}
print("  tail pass:", tm.get("pass"))

print("== design selection:")
sel = json.loads((ART / "r13_sample_size_selection.json").read_text())
print("  selected:", sel["selected_candidate"], "n=",
      sel["selected_block_count"], "qualified:",
      sel["qualified_combinations"], "semantic_gate:",
      sel["semantic_gate_pass"])

print("== calibration evidence:")
ev = json.loads((ART / "calibration_evidence.json").read_text())
print("  main/holdout independent:",
      ev["main_holdout_independent"])

print("== qualification:")
q = json.loads((ART / "qualification_result.json").read_text())
print("  verdict:", q["verdict"])
fails = [k for k, v in q["checks"].items() if v is False]
print("  failed checks:", fails if fails else "无")
print("  n_blocks:", q["selected_block_count"],
      "core_pairs:", q["core_qualification_pairs"],
      "total_episodes:", q["total_generated_episodes"])

print("== exposure marker:")
m = json.loads(
    (ART / "qualification_exposure_r13.json").read_text())
print("  status:", m["status"], "plan_digest:",
      m["plan_digest"][:20] + "...")

smoke = json.loads((ART / "ppo_256step_smoke.json").read_text())
print("== ppo smoke pass:", smoke["pass"])
