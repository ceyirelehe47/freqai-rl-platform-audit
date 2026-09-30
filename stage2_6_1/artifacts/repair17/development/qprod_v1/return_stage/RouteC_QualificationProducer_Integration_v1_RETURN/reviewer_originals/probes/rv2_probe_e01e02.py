# RV2 probe: E02 originals (F2) + E01 read-only recompute + F3 halt (C7).
# SYNTHETIC_ONLY: zero native generation/fit/update; zero writes to originals.
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/src")
QP = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/qprod_v1")

print("===== E02 originals (C7 re-run; repo qprod_v1/level_a_e2e) =====")
for variant in ("v1_r2_reference", "v2_perturbed"):
    base = QP / "level_a_e2e" / variant / "qprod_level_a_qprod_a_eng_v1"
    art, state = base / "artifacts", base / "state"
    m = {}
    led = json.loads((art / "level_a_step_ledger.json").read_text(encoding="utf-8"))
    m["1.ledger_PASS_17_all_ok"] = (led.get("verdict") == "PASS"
                                    and len(led.get("steps", [])) == 17
                                    and all(s.get("ok") for s in led["steps"]))
    modes = {}
    for s in led["steps"]:
        modes[s["execution"]] = modes.get(s["execution"], 0) + 1
    flv = json.loads((art / "formal_log_verification.json").read_text(encoding="utf-8"))
    m["2.sequence_ok_true"] = flv.get("sequence_ok") is True
    m["3.expected17_recorded17_prefix"] = (
        len(flv.get("expected", [])) == 17 and
        len(flv.get("recorded_including_this_step", [])) == 17 and
        flv["recorded_including_this_step"] == flv["expected"])
    cf = json.loads((art / "qprod_code_freeze.json").read_text(encoding="utf-8"))
    csha = str(cf.get("code_freeze_sha") or cf.get("sha") or "")
    m["4.code_freeze_is_C7"] = csha.startswith("cda4e975")
    delivery = sorted(p for p in base.iterdir()
                      if p.is_dir() and p.name.startswith("delivery_"))
    d0 = delivery[0]
    rcpt = json.loads((d0 / "qprod_export_receipt.json").read_text(encoding="utf-8"))
    m["5.export_receipt_digests"] = sorted(rcpt.keys())
    six = sorted(p.name for p in d0.iterdir())
    m["6.delivery_files"] = six
    cold = json.loads((art / "full_cold_reader_check.json").read_text(encoding="utf-8"))
    m["7.cold_envelope_ok"] = cold.get("envelope_load_ok") is True
    consumed = [x for x in (state / "qprod_permit_consumed.jsonl")
                .read_text(encoding="utf-8").splitlines() if x.strip()]
    auth = QP / "level_a_e2e" / ("authority_" + variant)
    auth_files = sorted(p.name for p in auth.iterdir()) if auth.is_dir() else []
    m["8.permit_consumed_once"] = (len(consumed) == 1 and
                                   any("consumption_auth" in n for n in auth_files))
    n_ok = sum(1 for v in m.values() if v is True)
    print("--", variant, "markers=%d/8" % n_ok)
    for k, v in m.items():
        print("   ", k, "=", v)
    print("    ledger execution modes:", modes)
    rej = list(base.glob("export_rejected*.json")) + list(base.glob("*rejected*.json"))
    print("    formal-reject evidence:", [p.name for p in rej])

print("")
print("===== F3 halt semantics (direct probe; collect_all_k, valid+corrupt) =====")
sys.path.insert(0, "/mnt/f/trading/reviewer_qprod_v1/probes")
from rv1_probe import (build_coord, setup_plan, coords_n, PROBE_ROOT,
                       aggregate_research, v4, P0, COORDINATE_STATE_CORRUPT)
base = PROBE_ROOT / "rv2_f3_halt"
art, state = base / "artifacts", base / "state"
digest = setup_plan(state, coords_n(2), "collect_all_k")
build_coord(art, "c01", digest, hits=52)
build_coord(art, "c02", digest, hits=52, trace_bytes=b"{not json\n")
rep = aggregate_research(art, state_root=state)
states = [c["state"] for c in rep["coordinates"]]
print("states:", states)
print("primary.magnitude:", rep["primary"]["magnitude"])
print("valid_coordinate_count:", rep["valid_coordinate_count"])
ok = (states[0] == "valid" and states[1] == "technically_corrupt"
      and rep["primary"]["magnitude"] == "halted_technically_corrupt"
      and rep["valid_coordinate_count"] == 1)
print("F3-halt:", "PASS" if ok else "FAIL")

# seed-log corrupt variant
base2 = PROBE_ROOT / "rv2_f3_seedlog"
art2, state2 = base2 / "artifacts", base2 / "state"
digest2 = setup_plan(state2, coords_n(1), "collect_all_k")
build_coord(art2, "c01", digest2, hits=52)
seedlog = art2 / "c01" / "qprod_block_seed_log.jsonl"
seedlog.write_text("{broken seed log\n", encoding="utf-8")
seal_path = art2 / "c01" / "qprod_coordinate_seal.json"
seal = json.loads(seal_path.read_text(encoding="utf-8"))
seal["members_sha256"]["qprod_block_seed_log.jsonl"] = hashlib.sha256(
    seedlog.read_bytes()).hexdigest()
seal_path.write_text(json.dumps(seal), encoding="utf-8")
rep2 = aggregate_research(art2, state_root=state2)
st2 = rep2["coordinates"][0]["state"]
pm2 = rep2["primary"]["magnitude"]
print("seed-log-corrupt state:", st2, "primary:", pm2)
print("F3-seedlog:", "PASS" if (st2 == "technically_corrupt"
      and pm2 == "halted_technically_corrupt") else "FAIL")

print("")
print("===== E01 read-only recompute under C7 =====")
def scrub(r):
    r = json.loads(json.dumps(r))
    r.pop("aggregated_utc", None)
    return r

for run in ("native_smoke_run2", "native_smoke_run1"):
    base = QP / run / "qprod_level_b_qprod_b_eng_v1"
    art, state = base / "artifacts", base / "state"
    stored = json.loads((art / "qprod_aggregate_report.json")
                        .read_text(encoding="utf-8"))
    try:
        fresh = aggregate_research(art, state_root=state)
    except Exception as exc:
        print(run, "AGG FAILED:", type(exc).__name__, str(exc)[:200])
        continue
    print("--", run, ": rc_agg=0")
    print("   stop_mode:", fresh["stop_mode"],
          " early_stopped_at:", fresh["early_stopped_at"])
    print("   primary:", fresh["primary"].get("magnitude"),
          "| reason:", fresh["primary"].get("not_resolved_reason", ""))
    print("   valid:", fresh["valid_coordinate_count"], "/", fresh["planned_k"],
          " states:", [c["state"] for c in fresh["coordinates"]],
          " favorable:", [c.get("favorable_beyond_margin")
                          for c in fresh["coordinates"]])
    same = (stored["primary"].get("magnitude")
            == fresh["primary"].get("magnitude")
            and stored["valid_coordinate_count"]
            == fresh["valid_coordinate_count"]
            and all((a.get("state"),
                     round(float(a.get("recall_validation", 0) or 0), 12))
                    == (b.get("state"),
                        round(float(b.get("recall_validation", 0) or 0), 12))
                    for a, b in zip(stored["coordinates"],
                                    fresh["coordinates"])))
    print("   cold_read_reproduces:", same,
          " deep_equal_modulo_utc:", scrub(stored) == scrub(fresh))
