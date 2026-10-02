import json, sys
sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/src")
from rl_curriculum.curriculum261_r17_cue_contract import (
    cue_contract_audit_digest, recompute_audit_semantics_from_report)
p = ("/mnt/f/trading/tmp_r12/reviewer/e02_run/v1_r2_reference/"
     "qprod_level_a_qprod_a_eng_v1/artifacts/cue_contract_audit.json")
r = json.load(open(p))
decl = r.get("audit_digest")
rec = cue_contract_audit_digest(r)
print("declared_digest:", decl)
print("recomputed     :", rec)
print("match:", decl == rec)
sem = recompute_audit_semantics_from_report(r)
print("all_consistent:", sem["all_consistent"])
print("fixture_mode:", sem["fixture_mode"])
print("ova block:", json.dumps(r["once_vs_attempts"], ensure_ascii=False))
