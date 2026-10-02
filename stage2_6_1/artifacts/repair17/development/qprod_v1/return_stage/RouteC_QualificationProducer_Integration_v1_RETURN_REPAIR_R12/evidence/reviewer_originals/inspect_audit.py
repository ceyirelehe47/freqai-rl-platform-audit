import json
p = ("/mnt/f/trading/tmp_r12/reviewer/e02_run/v1_r2_reference/"
     "qprod_level_a_qprod_a_eng_v1/artifacts/cue_contract_audit.json")
r = json.load(open(p))
print("top keys:", sorted(r.keys()))
print("engineering_fixture:", r.get("engineering_fixture"))
print("checks:", json.dumps(r.get("checks"), ensure_ascii=False))
print("pass:", r.get("pass"))
for k in ("once_vs_attempts", "audit_statistics", "statistics"):
    if k in r:
        print(k, "->", json.dumps(r[k], ensure_ascii=False)[:400])
