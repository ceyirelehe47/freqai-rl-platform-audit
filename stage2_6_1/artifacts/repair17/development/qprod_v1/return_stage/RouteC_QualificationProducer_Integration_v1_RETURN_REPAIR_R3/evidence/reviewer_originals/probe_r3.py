# Independent reviewer probes for QProd R3 (C12). Zero native/fit/optimizer.
import hashlib
import json
import sys
import tempfile as tf
from pathlib import Path

sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/tests/route_c_stage2_6_2")
sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/tests/route_c_stage2_6_1")
sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/src")

import test_curriculum261_qprod_aggregate as ta
import test_curriculum261_qprod_levela as tl

from rl_curriculum.curriculum261_qprod_aggregate import (
    _verify_coordinate, aggregate_research)
from rl_curriculum.curriculum261_qprod_coordinate import (
    QProdQuotaExceeded, _GenerationLedger, _early_stop_boundary,
    coordinate_audit_plan_digest)
from rl_curriculum.curriculum261_qprod_context import QProdRunSession
from rl_curriculum.curriculum261_qprod_levela import (
    judge_qualification_gates, run_level_a_rehearsal)
from rl_curriculum.curriculum261_qprod_plan import load_research_plan
from rl_curriculum.curriculum261_r17_cue_contract import (
    cue_contract_audit_digest)

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name +
          (" :: " + str(detail) if detail != "" else ""))


def sha_tree(root):
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def rehearse(tmp):
    ctx = tl._ctx(tmp)
    session = QProdRunSession(ctx.state_root, level="level_a",
                              iteration_id=ctx.iteration_id)
    session.acquire({"entry": "reviewer-probe"})
    run_level_a_rehearsal(ctx, session, tl._fixture_inputs(tmp))
    plan = json.loads((ctx.state_root / "qprod_qualification_plan.json")
                      .read_text(encoding="utf-8"))
    return ctx, plan


# P1: genuine rehearsal -> gate1 passes (positive example must pass)
tmp1 = Path(tf.mkdtemp(prefix="r3p_pos_"))
ctx, plan = rehearse(tmp1)
raw = judge_qualification_gates(ctx.artifact_root, plan)
g = raw["gates"]["cue_audit_pass"]
check("P1 genuine rehearsal verdict PASS", raw["verdict"] == "PASS",
      raw["verdict"])
check("P1b cue gate pass + numbers/set consistent",
      g["pass"] is True
      and g["observed"]["numbers_consistent_with_checks"] is True
      and g["observed"]["checks_set_matches_authority"] is True,
      g["observed"].get("mc_close_recomputed"))

# P2: replace required check with foreign key -> reject
cue_p = ctx.artifact_root / "cue_contract_audit.json"
cue = json.loads(cue_p.read_text(encoding="utf-8"))
cue["checks"].pop("mc_close_to_analytic")
cue["checks"]["foreign_substitute_ok"] = True
cue["pass"] = True
cue["audit_digest"] = cue_contract_audit_digest(cue)
cue_p.write_text(json.dumps(cue), encoding="utf-8")
raw2 = judge_qualification_gates(ctx.artifact_root, plan)
check("P2 foreign substitute check rejected",
      raw2["verdict"] == "FAIL"
      and raw2["gates"]["cue_audit_pass"]["observed"]
      ["checks_set_matches_authority"] is False)

# P3: extra padding key added -> reject
tmp3 = Path(tf.mkdtemp(prefix="r3p_extra_"))
ctx3, plan3 = rehearse(tmp3)
cue_p3 = ctx3.artifact_root / "cue_contract_audit.json"
cue3 = json.loads(cue_p3.read_text(encoding="utf-8"))
cue3["checks"]["extra_padding_check"] = True
cue3["audit_digest"] = cue_contract_audit_digest(cue3)
cue_p3.write_text(json.dumps(cue3), encoding="utf-8")
raw3 = judge_qualification_gates(ctx3.artifact_root, plan3)
check("P3 extra check key rejected", raw3["verdict"] == "FAIL"
      and raw3["gates"]["cue_audit_pass"]["observed"]
      ["checks_set_matches_authority"] is False)

# P3b: stored check boolean contradicts fine numbers -> reject
tmp3b = Path(tf.mkdtemp(prefix="r3p_bool_"))
ctx3b, plan3b = rehearse(tmp3b)
cue_pb = ctx3b.artifact_root / "cue_contract_audit.json"
cueb = json.loads(cue_pb.read_text(encoding="utf-8"))
cueb["checks"]["mc_close_to_analytic"] = False
cueb["pass"] = False
cueb["audit_digest"] = cue_contract_audit_digest(cueb)
cue_pb.write_text(json.dumps(cueb), encoding="utf-8")
raw3b = judge_qualification_gates(ctx3b.artifact_root, plan3b)
check("P3b checks-False-vs-fine-numbers inconsistent rejected",
      raw3b["verdict"] == "FAIL"
      and raw3b["gates"]["cue_audit_pass"]["observed"]
      ["numbers_consistent_with_checks"] is False)

# P4: uncertain reservation blocks subsequent generation
import rl_curriculum.curriculum261_r6_tape as r6


class _FakeEp:
    def __init__(self):
        import pandas as pd
        self.df = pd.DataFrame({"x": [1.0]})
        self.hidden = pd.DataFrame({"y": [1.0]})


def fake_once(ladder, seed, ns):
    return {r: {"A": _FakeEp(), "B": _FakeEp()}
            for r in ("D0", "D1", "D2", "D3")}


class _Boom:
    block_index = 0

    def __init__(self):
        raise RuntimeError("probe crash")


led = _GenerationLedger(quota_max_episode_leaf_calls=60,
                        coordinate_id="probe")
o1 = r6.generate_matched_block_once
o2 = r6.generate_matched_block_with_attempts
r6.generate_matched_block_once = fake_once
r6.generate_matched_block_with_attempts = lambda *a, **k: _Boom()
qblocked = False
kept = False
try:
    h = led.bind()
    try:
        h["generate_attempts"]({}, namespace="calibration_r3",
                               block_index=0)
    except RuntimeError:
        pass
    kept = led.episode_leaf_calls == 40 and led.uncertain_blocks == 1
    try:
        h["generate_attempts"]({}, namespace="calibration_r3",
                               block_index=1)
    except QProdQuotaExceeded:
        qblocked = True
finally:
    r6.generate_matched_block_once = o1
    r6.generate_matched_block_with_attempts = o2
check("P4 reservation retained(40) and blocks next block(80>60)",
      kept and qblocked)

# P5: early-stop boundary (start side) same definition, degenerate SE safe
broot = Path(tf.mkdtemp(prefix="r3p_boundary_"))
cdir = broot / "c01"
cdir.mkdir(parents=True)
seal_p = cdir / "qprod_coordinate_seal.json"
seal_p.write_text(json.dumps({"summary": {
    "recall_validation": 0.5, "se_validation": 0.02,
    "audit_pass": False}}), encoding="utf-8")
rp = {"stop_mode": "early_stop_on_first_negative",
      "coordinate_manifest": [{"coordinate_id": "c01",
                               "artifact_subdir": "c01"}],
      "rules": {"p0_fixed_reference": 0.950431552876822,
                "margin": 0.003, "r_analysis": 1.5, "alpha": 0.05}}
b1 = _early_stop_boundary(rp, broot)
check("P5a boundary triggers on low recall (audit_fail included)",
      b1 == "c01", b1)
seal_p.write_text(json.dumps({"summary": {
    "recall_validation": 0.5, "se_validation": 0.0,
    "audit_pass": False}}), encoding="utf-8")
check("P5b degenerate SE does not trigger stop",
      _early_stop_boundary(rp, broot) is None)
rp2 = dict(rp)
rp2["stop_mode"] = "collect_all_k"
seal_p.write_text(json.dumps({"summary": {
    "recall_validation": 0.5, "se_validation": 0.02,
    "audit_pass": False}}), encoding="utf-8")
check("P5c collect-all never stops at boundary",
      _early_stop_boundary(rp2, broot) is None)

# P6: qcap block_range.start_index != 0 rejected (range linkage)
tmp6 = Path(tf.mkdtemp(prefix="r3p_range_"))
art6, state6, digest6 = ta._setup_plan(tmp6)
plan6 = load_research_plan(state6)
coord6 = plan6["coordinate_manifest"][0]
cd6 = art6 / coord6["artifact_subdir"]
ta._build_coordinate(art6, coord6["artifact_subdir"],
                     plan_digest=digest6)
qcap_p6 = cd6 / "qprod_coordinate_audit_plan.json"
qcap6 = json.loads(qcap_p6.read_text(encoding="utf-8"))
qcap6["block_range"] = {"start_index": 1, "count": 2}
qcap6.pop("coordinate_audit_plan_digest", None)
qcap6["coordinate_audit_plan_digest"] = coordinate_audit_plan_digest(qcap6)
qcap_p6.write_text(json.dumps(qcap6), encoding="utf-8")
(cd6 / "qprod_coordinate_audit_plan_digest.txt").write_text(
    qcap6["coordinate_audit_plan_digest"] + "\n", encoding="utf-8")
seal6_p = cd6 / "qprod_coordinate_seal.json"
seal6 = json.loads(seal6_p.read_text(encoding="utf-8"))
seal6["coordinate_audit_plan_digest"] = qcap6[
    "coordinate_audit_plan_digest"]
seal6_p.write_text(json.dumps(seal6), encoding="utf-8")
v6 = _verify_coordinate(cd6, coord6, plan6)
check("P6 qcap start_index!=0 rejected",
      v6["state"] != "valid"
      and any("start_index" in p or "范围" in p
              for p in v6["problems"]), v6["problems"][:2])

# P7: E01 independent read-only recompute, zero mutation, matches C12 file
qprod_root = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1"
                  "/artifacts/repair17/development/qprod_v1")
recompute = json.loads((qprod_root / "repair_round3_notclosed"
                        / "E01_RECOMPUTE_C12.json").read_text(
                            encoding="utf-8"))
for run in ("native_smoke_run1", "native_smoke_run2"):
    base = qprod_root / run / "qprod_level_b_qprod_b_eng_v1"
    before = sha_tree(base)
    agg = aggregate_research(base / "artifacts", state_root=base / "state")
    after = sha_tree(base)
    expect = recompute["runs"][run]
    got_failed = sorted(agg["stats_gate_failed_coordinate_ids"])
    check("P7 %s zero mutation" % run, before == after)
    check("P7 %s valid/primary/failed match C12 file" % run,
          agg["valid_coordinate_count"] == expect["valid"]
          and agg["primary"]["magnitude"] == expect["primary"]
          == "inconclusive"
          and got_failed == sorted(expect["stats_gate_failed"]),
          "valid=%s primary=%s failed=%s" % (
              agg["valid_coordinate_count"],
              agg["primary"]["magnitude"], got_failed))
    for c in expect["coords"]:
        if c["state"] != "valid":
            continue
        e = next(x for x in agg["coordinates"]
                 if x["coordinate_id"] == c["id"])
        okc = (e["state"] == "valid"
               and bool(e.get("audit_fail")) == bool(c["audit_fail"])
               and e.get("negative_result_valid") is True
               and abs(e["recall_validation"] - c["recall"]) < 1e-12
               and abs(float(e["se_validation"]) - c["se"]) < 1e-12)
        check("P7 %s/%s retained recall/se/nrv" % (run, c["id"]), okc,
              "recall=%s se=%s" % (e["recall_validation"],
                                   e["se_validation"]))

n_ok = sum(1 for _, ok in results if ok)
print("PROBE-SUMMARY %d/%d" % (n_ok, len(results)))
print("PROBE-FAILURES %s" % ([n for n, ok in results if not ok]
                             or "none"))
