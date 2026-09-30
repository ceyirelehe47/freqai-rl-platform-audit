# RV2 probe B: independent read-only consumption cold read + code freeze binding (C7).
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/src")
REPO = Path("/mnt/f/trading/freqai-rl-audit")
QP = REPO / "stage2_6_1/artifacts/repair17/development/qprod_v1/level_a_e2e"

print("===== code_identity binding vs repo C7 worktree =====")
for variant in ("v1_r2_reference", "v2_perturbed"):
    cf = json.loads((QP / variant / "qprod_level_a_qprod_a_eng_v1" / "artifacts"
                     / "qprod_code_freeze.json").read_text(encoding="utf-8"))
    ok_all = True
    for name, h in cf["code_identity"].items():
        f = REPO / "stage2_6_1/src/rl_curriculum" / name
        cur = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
        if cur != h:
            ok_all = False
            print("  DRIFT", variant, name, h[:12], "->", cur[:12])
    print(variant, "code_identity_all_match_C7_repo:", ok_all,
          "engineering_only:", cf.get("engineering_only"))

print("")
print("===== independent consumption cold read (read-only; C7 code) =====")
from rl_curriculum.ppo262_qualified_input import (
    QualifiedInputError, activated_profile_input, load_qualified_input,
)
from rl_curriculum.ppo262_entry_specs import prepare_smoke_inputs

CONSUMPTION_PROFILE = "ppo262_qprod_engineering_v1"
for variant in ("v1_r2_reference", "v2_perturbed"):
    base = QP / variant / "qprod_level_a_qprod_a_eng_v1"
    delivery = base / ("delivery_" + variant)
    auth = QP / ("authority_" + variant) / ("qprod_consumption_auth_delivery_"
                                            + variant + ".json")
    rcpt = json.loads((delivery / "qprod_export_receipt.json")
                      .read_text(encoding="utf-8"))
    # 1) formal scope must reject (read-only; nothing written)
    try:
        load_qualified_input(delivery, authorization_path=auth,
                             expected_scope="formal")
        print(variant, "formal-reject: FAIL (loaded!)")
    except QualifiedInputError as exc:
        print(variant, "formal-reject: PASS ::", str(exc)[:80])
    # 2) engineering cold load + profile assert (no writes)
    qi = load_qualified_input(delivery, authorization_path=auth,
                              expected_scope="engineering",
                              expected_profile=CONSUMPTION_PROFILE)
    with activated_profile_input(qi):
        spec = prepare_smoke_inputs()
        spec.assert_from_profile(qi)
        rung = spec.rung_params
        probe_params = {fam: {r: rung[fam][r]
                              for r in ("D0", "D3")}
                        for fam in ("c1_opportunity", "c3_cost")}
    b = rcpt["bindings"]
    bind_ok = (b == {"qualification_plan_digest": qi.bindings.qualification_plan_digest,
                     "parameter_pack_digest": qi.bindings.parameter_pack_digest,
                     "preprocessor_bundle_hash": qi.bindings.preprocessor_bundle_hash}
               if hasattr(qi, "bindings") and hasattr(qi.bindings,
                                                      "qualification_plan_digest")
               else None)
    print(variant, "engineering-load: OK; receipt_checks_all_true:",
          all(rcpt["checks"].values()), "| receipt==qi.bindings:", bind_ok)
    print("   rung probe:", json.dumps(probe_params)[:220])
