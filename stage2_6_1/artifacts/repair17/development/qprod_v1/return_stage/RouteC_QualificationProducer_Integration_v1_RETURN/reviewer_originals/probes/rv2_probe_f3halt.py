# RV2 probe: F3 corrupt-halt semantics + E01 recompute + E02 originals (C7).
# SYNTHETIC_ONLY; zero writes to originals/repo (probe output to /tmp only).
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/src")
from rl_curriculum.curriculum261_qprod_aggregate import aggregate_research
from rl_curriculum.curriculum261_qprod_plan import freeze_research_plan
from rl_curriculum.curriculum261_r17_cue_contract import (
    _cluster_bootstrap, _per_block_event_counts,
)
from rl_curriculum.curriculum261_r6_tape import derive261_block_seed

P0 = 0.950431552876822
ROOT = Path("/tmp/rv2_probes")


def synth_events(blocks, hits_per_block, n_events, seed_tag):
    events = []
    for b in range(blocks):
        hits = hits_per_block[b] if isinstance(hits_per_block, list) else hits_per_block
        for j in range(n_events):
            events.append({
                "corpus": "validation", "block_index": b,
                "cue_bar": 20 + ((j * 7 + seed_tag) % 200),
                "primary_present": 1, "k_actual": (j + seed_tag) % 5,
                "mirror_positions": [1, 2], "mirror_candidates": 2,
                "effective_sigma_bps": 26.0,
                "actual_noise": 0.001, "cue_read": 0.0106,
                "detected": bool(j < hits),
            })
    return events


def build_coord(art, subdir, plan_digest, *, hits, blocks=4, n_events=55,
                trace_bytes=None, seedlog_bytes=None):
    coord_dir = art / subdir
    coord_dir.mkdir(parents=True, exist_ok=True)
    events = synth_events(blocks, hits, n_events, (ord(subdir[-1]) * 7) % 97)
    if trace_bytes is not None:
        (coord_dir / "cue_event_trace.jsonl").write_bytes(trace_bytes)
        point, se = 0.99, 0.01
    else:
        (coord_dir / "cue_event_trace.jsonl").write_text(
            "\n".join(json.dumps(e, sort_keys=True) for e in events) + "\n",
            encoding="utf-8")
        boot = _cluster_bootstrap(_per_block_event_counts(events))
        point, se = boot["point"], boot["se"]
    model_ns = "cue_dev_r25_%s_model" % subdir
    validation_ns = "cue_dev_r25_%s_validation" % subdir
    report = {
        "format": "cur261-r17-cue-contract-audit-v1",
        "audit_namespaces": {"model": model_ns, "validation": validation_ns},
        "audit_blocks_per_corpus": blocks,
        "p_contract": 0.94,
        "direct_generator": {"validation": {
            "empirical_recall": point,
            "block_cluster": {"point": point, "se": se}}},
    }
    (coord_dir / "cue_contract_audit.json").write_text(
        json.dumps(report), encoding="utf-8")
    log = []
    for i in range(blocks):
        log.append({"kind": "once", "namespace": model_ns,
                    "block_seed": int(derive261_block_seed(model_ns, i, 0))})
        log.append({"kind": "attempts", "namespace": validation_ns,
                    "block_index": i,
                    "block_seed": int(derive261_block_seed(validation_ns, i, 0)),
                    "selected_attempt": 0, "attempts_made": 1})
    if seedlog_bytes is not None:
        (coord_dir / "qprod_block_seed_log.jsonl").write_bytes(seedlog_bytes)
    else:
        (coord_dir / "qprod_block_seed_log.jsonl").write_text(
            "\n".join(json.dumps(e, sort_keys=True) for e in log) + "\n",
            encoding="utf-8")
    members = {}
    for name in ("cue_contract_audit.json", "cue_event_trace.jsonl",
                 "qprod_block_seed_log.jsonl"):
        members[name] = hashlib.sha256(
            (coord_dir / name).read_bytes()).hexdigest()
    (coord_dir / "qprod_coordinate_seal.json").write_text(json.dumps({
        "format": "cur261-qprod-coordinate-seal-v1",
        "coordinate_id": subdir,
        "research_plan_digest": plan_digest,
        "audit_digest": "r15ca-synth",
        "members_sha256": members,
        "summary": {"recall_validation": point, "se_validation": se,
                    "p_contract_local": 0.94, "audit_pass": True,
                    "engineering_only": True, "blocks_per_corpus": blocks},
        "generation": {"leaf_calls_total": 8},
    }), encoding="utf-8")
    return coord_dir


def setup_plan(state, coords, stop_mode, planned_k=11):
    state.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "cur261-qprod-research-plan-v1",
        "level": "level_b", "iteration_id": "rv2probe",
        "profile": "engineering", "code_freeze_sha": "s",
        "coordinate_manifest": coords,
        "rules": {"p0_fixed_reference": P0, "p0_source_label": "rv2 synthetic",
                  "delta_definition": "P0 - recall(validation)",
                  "margin": 0.003, "alpha": 0.05, "r_analysis": 1.5,
                  "planned_k": planned_k},
        "quota": {}, "code_identity": {}, "stop_mode": stop_mode,
    }
    _, digest = freeze_research_plan(state, payload)
    return digest


def coords(prefix, n):
    return [{"coordinate_id": "%s%02d" % (prefix, i),
             "model_namespace": "cue_dev_r25_%s%02d_model" % (prefix, i),
             "validation_namespace": "cue_dev_r25_%s%02d_validation" % (prefix, i),
             "artifact_subdir": "%s%02d" % (prefix, i)} for i in range(1, n + 1)]


print("===== F3 halt semantics (direct; corrupt must stop even with K met) =====")
base = ROOT / "f3_halt"
art, state = base / "artifacts", base / "state"
digest = setup_plan(state, coords("c", 2), "collect_all_k", planned_k=1)
build_coord(art, "c01", digest, hits=52)
build_coord(art, "c02", digest, hits=52, trace_bytes=b"{not json\n")
rep = aggregate_research(art, state_root=state)
states = [c["state"] for c in rep["coordinates"]]
print("states:", states)
print("primary.magnitude:", rep["primary"]["magnitude"])
print("valid_coordinate_count:", rep["valid_coordinate_count"],
      "planned_k: 1 (K met yet halt required)")
ok = (states == ["valid", "technically_corrupt"]
      and rep["primary"]["magnitude"] == "halted_technically_corrupt")
print("F3-halt:", "PASS" if ok else "FAIL")

base2 = ROOT / "f3_seedlog"
art2, state2 = base2 / "artifacts", base2 / "state"
digest2 = setup_plan(state2, coords("c", 1), "collect_all_k")
build_coord(art2, "c01", digest2, hits=52,
            seedlog_bytes=b"{broken seed log\n")
rep2 = aggregate_research(art2, state_root=state2)
st2 = rep2["coordinates"][0]["state"]
pm2 = rep2["primary"]["magnitude"]
print("seed-log-corrupt state:", st2, "primary:", pm2)
print("F3-seedlog:", "PASS" if (st2 == "technically_corrupt"
      and pm2 == "halted_technically_corrupt") else "FAIL")

print("")
print("===== E01 read-only recompute under C7 =====")
QP = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/qprod_v1")


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

print("")
print("===== E02 originals (C7 re-run) =====")
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
    m["3.expected_eq_recorded"] = (len(flv.get("expected", [])) == 17 and
                                   flv.get("recorded_including_this_step")
                                   == flv.get("expected"))
    cf = json.loads((art / "qprod_code_freeze.json").read_text(encoding="utf-8"))
    csha = str(cf.get("code_freeze_sha") or cf.get("sha") or "")
    m["4.code_freeze_is_C7"] = csha.startswith("cda4e975")
    delivery = sorted(p for p in base.iterdir()
                      if p.is_dir() and p.name.startswith("delivery_"))
    d0 = delivery[0]
    rcpt = json.loads((d0 / "qprod_export_receipt.json").read_text(encoding="utf-8"))
    m["5.export_receipt_keys"] = sorted(rcpt.keys())
    m["6.delivery_files"] = sorted(p.name for p in d0.iterdir())
    cold = json.loads((art / "full_cold_reader_check.json").read_text(encoding="utf-8"))
    m["7.cold_envelope_ok"] = cold.get("envelope_load_ok") is True
    consumed = [x for x in (state / "qprod_permit_consumed.jsonl")
                .read_text(encoding="utf-8").splitlines() if x.strip()]
    auth = QP / "level_a_e2e" / ("authority_" + variant)
    auth_files = sorted(p.name for p in auth.iterdir()) if auth.is_dir() else []
    m["8.permit_consumed_once"] = (len(consumed) == 1 and
                                   any("consumption_auth" in n
                                       for n in auth_files))
    n_ok = sum(1 for v in m.values() if v is True)
    print("--", variant, "markers=%d/8" % n_ok)
    for k, v in m.items():
        print("   ", k, "=", v)
    print("    ledger execution modes:", modes)
    rej = sorted(p.name for p in base.glob("*rejected*.json"))
    print("    formal-reject evidence:", rej)
