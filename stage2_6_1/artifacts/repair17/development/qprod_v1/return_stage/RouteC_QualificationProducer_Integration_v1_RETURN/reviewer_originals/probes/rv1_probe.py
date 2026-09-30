# RV1 independent probes for RouteC_QualificationProducer_Integration_v1 (C6=f1bebc37).
# SYNTHETIC_ONLY: zero native generation, zero fit, zero optimizer.
import json
import hashlib
import sys
from pathlib import Path

SRC = "/home/cryptorl/projects/crypto_rl/src"
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from rl_curriculum.curriculum261_qprod_context import (
    QProdContextError, QProdOwnershipError, QProdRunSession,
    build_engineering_context, harden_root, protected_old_roots,
    resolve_formal_roots,
)
from rl_curriculum.curriculum261_qprod_permit import (
    QPROD_PERMIT_FORMAT, consume_permit, permit_digest, validate_permit,
)
from rl_curriculum.curriculum261_qprod_plan import (
    freeze_research_plan, research_plan_structure_problems,
)
from rl_curriculum.curriculum261_qprod_coordinate import (
    lock_coordinate_audit_plan, run_coordinate_audit_locked,
)
import rl_curriculum.curriculum261_qprod_aggregate as agg_mod
from rl_curriculum.curriculum261_qprod_aggregate import (
    aggregate_research, COORDINATE_STATE_CORRUPT,
)
from rl_curriculum.curriculum261_r17_cue_contract import (
    _cluster_bootstrap, _per_block_event_counts,
)
from rl_curriculum.curriculum261_r6_tape import derive261_block_seed
from rl_curriculum.curriculum261_api import (
    CURRICULUM261_QPROD_ENGINEERING_NAMESPACES,
)

PROBE_ROOT = Path("/tmp/rv1_probes")
RESULTS = []
P0 = 0.950431552876822
v4 = agg_mod._load_v4_module()


def rec(tag, ok, detail=""):
    RESULTS.append((tag, ok, detail))
    print(("PASS " if ok else "FAIL ") + tag + (" :: " + detail if detail else ""))


def expect_error(tag, fn, exc_types, needle=""):
    try:
        fn()
    except exc_types as exc:
        msg = str(exc)
        if needle and needle not in msg:
            rec(tag, False, "wrong reason: " + msg[:160])
        else:
            rec(tag, True, msg[:110])
    except BaseException as exc:
        rec(tag, False, "unexpected %s: %s" % (type(exc).__name__, str(exc)[:160]))
    else:
        rec(tag, False, "no error raised")


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
                trace_bytes=None):
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
        "level": "level_b", "iteration_id": "rv1probe",
        "profile": "engineering", "code_freeze_sha": "s",
        "coordinate_manifest": coords,
        "rules": {"p0_fixed_reference": P0, "p0_source_label": "rv1 synthetic",
                  "delta_definition": "P0 - recall(validation)",
                  "margin": 0.003, "alpha": 0.05, "r_analysis": 1.5,
                  "planned_k": planned_k},
        "quota": {}, "code_identity": {}, "stop_mode": stop_mode,
    }
    _, digest = freeze_research_plan(state, payload)
    return digest


def coords_n(n):
    return [{"coordinate_id": "c%02d" % i,
             "model_namespace": "cue_dev_r25_c%02d_model" % i,
             "validation_namespace": "cue_dev_r25_c%02d_validation" % i,
             "artifact_subdir": "c%02d" % i} for i in range(1, n + 1)]


PROBE_ROOT.mkdir(parents=True, exist_ok=True)

# ============ P1 early-stop direction ============
base = PROBE_ROOT / "p1_earlystop"
art, state = base / "artifacts", base / "state"
digest = setup_plan(state, coords_n(11), "early_stop_on_first_negative")
build_coord(art, "c01", digest, hits=[55, 55, 54, 53])
rep = aggregate_research(art, state_root=state)
c01 = rep["coordinates"][0]
rec("P1a.favorable-coordinate-is-valid", c01["state"] == "valid",
    "state=%s recall=%s" % (c01["state"], c01.get("recall_validation")))
single = v4.classify_primary(P0 - c01["recall_validation"],
                             [c01["se_validation"]], margin=0.003,
                             r_analysis=1.5, alpha=0.05, planned_k=None)
rec("P1b.single-magnitude-is-beyond-negative",
    single["magnitude"] == "beyond_negative_margin",
    "magnitude=%s delta=%.5f" % (single["magnitude"],
                                 P0 - c01["recall_validation"]))
rec("P1c.earlystop-should-not-trigger-on-favorable",
    rep["early_stopped_at"] is None
    and not c01.get("statistical_negative", False),
    "early_stopped_at=%s statistical_negative=%s" % (
        rep["early_stopped_at"], c01.get("statistical_negative")))

# ============ P2 corrupt trace ============
base = PROBE_ROOT / "p2_corrupt"
art, state = base / "artifacts", base / "state"
digest = setup_plan(state, coords_n(2), "collect_all_k")
build_coord(art, "c01", digest, hits=52, trace_bytes=b"{not json\n")
try:
    rep = aggregate_research(art, state_root=state)
    st = rep["coordinates"][0]["state"]
    rec("P2.corrupt-trace-classified-gracefully", False,
        "no crash but state=%s (corrupt halt unreachable)" % st)
except Exception as exc:
    rec("P2.corrupt-trace-classified-gracefully", False,
        "unhandled %s: %s" % (type(exc).__name__, str(exc)[:110]))
rec("P2b.corrupt-state-constant-defined",
    COORDINATE_STATE_CORRUPT == "technically_corrupt", "constant exists")

# ============ P3 permit negatives ============
base = PROBE_ROOT / "p3_permit"
auth = base / "authority"
auth.mkdir(parents=True, exist_ok=True)
(auth / "authority_identity.json").write_text(json.dumps(
    {"authority_id": "rv1_test_authority",
     "kind": "engineering_test_authority"}))
ctx_a = build_engineering_context(
    level="level_a", iteration_id="rv1a", base_dir=base / "runA",
    code_freeze_sha="freezeA", authority_dir=auth,
    namespaces_scope=CURRICULUM261_QPROD_ENGINEERING_NAMESPACES)
ctx_b = build_engineering_context(
    level="level_b", iteration_id="rv1b", base_dir=base / "runB",
    code_freeze_sha="freezeB", authority_dir=auth,
    namespaces_scope=CURRICULUM261_QPROD_ENGINEERING_NAMESPACES)


def mk_permit(path, *, level, it, sha, art_root, state_root, ns):
    p = {"format": QPROD_PERMIT_FORMAT, "permit_id": "rv1p-%s-%s" % (level, it),
         "task_level": level, "iteration_id": it, "code_freeze_sha": sha,
         "artifact_root": str(art_root), "state_root": str(state_root),
         "preregistered_input_scope": {"namespaces": list(ns),
                                       "coordinate_ids": ["c01"]},
         "quota": {"max_leaf_calls_per_coordinate": 320,
                   "max_successful_episodes_total": 64,
                   "mc_events_per_coordinate": 4096,
                   "max_native_executions": 2},
         "issuer": {"kind": "engineering_test_authority",
                    "authority_id": "rv1_test_authority"},
         "issued_utc": "2026-09-30T00:00:00+00:00"}
    p["permit_digest"] = permit_digest(p)
    Path(path).write_text(json.dumps(p), encoding="utf-8")
    return p


mk_permit(auth / "p_a.json", level="level_a", it="rv1a", sha="freezeA",
          art_root=ctx_a.artifact_root, state_root=ctx_a.state_root,
          ns=["cue_qprod_v1_c01_model"])
pb = mk_permit(auth / "p_b.json", level="level_b", it="rv1b", sha="freezeB",
               art_root=ctx_b.artifact_root, state_root=ctx_b.state_root,
               ns=["cue_qprod_v1_c01_model", "cue_qprod_v1_c01_validation"])
consume_permit(auth / "p_b.json", context=ctx_b)
expect_error("P3a.permit-replay-rejected",
             lambda: consume_permit(auth / "p_b.json", context=ctx_b),
             QProdContextError, "已消费")
expect_error("P3b.cross-level-permit-rejected",
             lambda: validate_permit(auth / "p_a.json", context=ctx_b),
             QProdContextError, "错层")
mk_permit(auth / "p_c.json", level="level_a", it="rv1a", sha="freezeWRONG",
          art_root=ctx_a.artifact_root, state_root=ctx_a.state_root,
          ns=["cue_qprod_v1_c01_model"])
expect_error("P3c.wrong-freeze-sha-rejected",
             lambda: validate_permit(auth / "p_c.json", context=ctx_a),
             QProdContextError, "冻结")
mk_permit(auth / "p_b2.json", level="level_b", it="rv1b", sha="freezeB",
          art_root=ctx_b.artifact_root, state_root=ctx_b.state_root,
          ns=["cue_qprod_v1_c99_model"])
expect_error("P3d.ns-outside-context-scope-rejected",
             lambda: validate_permit(auth / "p_b2.json", context=ctx_b),
             QProdContextError, "未声明")
outside = base / "outside_permit.json"
mk_permit(outside, level="level_b", it="rv1b", sha="freezeB",
          art_root=ctx_b.artifact_root, state_root=ctx_b.state_root,
          ns=["cue_qprod_v1_c01_model"])
expect_error("P3e.permit-outside-authority-rejected",
             lambda: validate_permit(outside, context=ctx_b),
             QProdContextError, "authority")

# ============ P4 context negatives ============
frozen = [r for r in protected_old_roots() if "repair17" in str(r)]
rec("P4a.protected-frozen-root-visible", bool(frozen), str(frozen[:1]))
if frozen:
    expect_error("P4b.base-inside-frozen-root-rejected",
                 lambda: harden_root(frozen[0] / "qprod_probe_x",
                                     label="probe"),
                 QProdContextError, "受保护历史根")
import os
os.environ["CURRICULUM261_QPROD_STATE_ROOT"] = "/tmp/evil"
expect_error("P4c.formal-env-redirection-rejected",
             lambda: resolve_formal_roots("/tmp/nonexistent_deploy",
                                          level="level_a", iteration_id="it"),
             QProdContextError, "环境重定向")
del os.environ["CURRICULUM261_QPROD_STATE_ROOT"]
expect_error("P4d.formal-without-deploy-config-rejected",
             lambda: resolve_formal_roots("/tmp/nonexistent_deploy",
                                          level="level_a", iteration_id="it"),
             QProdContextError, "缺失")
sess_dir = base / "sess"
s1 = QProdRunSession(sess_dir, level="level_a", iteration_id="rv1a")
s1.acquire()
s1.record_terminal(status="completed", verdict="PASS")
s1.release()
s2 = QProdRunSession(sess_dir, level="level_a", iteration_id="rv1a")
expect_error("P4e.terminal-no-reentry", lambda: s2.acquire(),
             QProdOwnershipError, "终态不可重入")
sess_dir2 = base / "sess2"
s3 = QProdRunSession(sess_dir2, level="level_a", iteration_id="rv1a")
s3.acquire()
s3._fh.close()
s4 = QProdRunSession(sess_dir2, level="level_a", iteration_id="rv1a")
expect_error("P4f.dead-owner-no-takeover", lambda: s4.acquire(),
             QProdOwnershipError, "不可接管")
dep = base / "deploy"
dep.mkdir(parents=True, exist_ok=True)
(dep / "qprod_deploy_config.json").write_text(json.dumps(
    {"format": "cur261-qprod-deploy-config-v1", "mode": "formal_ready",
     "formal_roots": {}}))
expect_error("P4g.engineering-entry-under-formal-ready-rejected",
             lambda: build_engineering_context(
                 level="level_a", iteration_id="x", base_dir=base / "runC",
                 code_freeze_sha="s", authority_dir=auth,
                 deploy_root_for_guard=dep),
             QProdContextError, "正式部署拒绝")

# ============ P5 plan structure negatives ============
bad = {"format": "cur261-qprod-research-plan-v1", "level": "level_b",
       "iteration_id": "rv1probe", "profile": "engineering",
       "code_freeze_sha": "s",
       "coordinate_manifest": [
           {"coordinate_id": "c01", "model_namespace": "nsA",
            "validation_namespace": "nsB", "artifact_subdir": "c01"},
           {"coordinate_id": "c02", "model_namespace": "nsC",
            "validation_namespace": "nsB", "artifact_subdir": "c02"}],
       "rules": {"p0_fixed_reference": 0.9, "p0_source_label": "x",
                 "delta_definition": "P0 - recall(validation)",
                 "margin": 0.003, "alpha": 0.05, "r_analysis": 1.5,
                 "planned_k": 11},
       "quota": {}, "code_identity": {}, "stop_mode": "collect_all_k"}
probs = research_plan_structure_problems(bad)
rec("P5a.duplicate-ns-across-coords-flagged",
    any("跨坐标重复" in p for p in probs), str(probs)[:150])
bad2 = json.loads(json.dumps(bad))
bad2["coordinate_manifest"] = [
    {"coordinate_id": "c01", "model_namespace": "nsA",
     "validation_namespace": "nsA", "artifact_subdir": "c01"}]
probs2 = research_plan_structure_problems(bad2)
rec("P5b.model-eq-validation-ns-flagged",
    any("相同" in p for p in probs2), str(probs2)[:150])

# ============ P6 coordinate negatives ============
base = PROBE_ROOT / "p6_coord"
auth6 = base / "authority"
auth6.mkdir(parents=True, exist_ok=True)
(auth6 / "authority_identity.json").write_text(json.dumps(
    {"authority_id": "rv1_test_authority"}))
ctx6 = build_engineering_context(
    level="level_b", iteration_id="rv1c", base_dir=base / "run",
    code_freeze_sha="fz", authority_dir=auth6,
    namespaces_scope=CURRICULUM261_QPROD_ENGINEERING_NAMESPACES)
digest6 = setup_plan(ctx6.state_root, [
    {"coordinate_id": "c01",
     "model_namespace": "cue_qprod_v1_c01_model",
     "validation_namespace": "cue_qprod_v1_c01_validation",
     "artifact_subdir": "coord_c01"}], "collect_all_k")
live = type("LP", (), {"permit": pb})()
try:
    run_coordinate_audit_locked(ctx6, live, "cXX",
                                coord_dir=ctx6.artifact_root / "coord_cXX",
                                ledger_path=base / "led.jsonl")
    rec("P6a.out-of-manifest-coordinate-refused", False, "no error")
except QProdContextError as exc:
    ref_file = ctx6.artifact_root / "refusal_cXX.json"
    ref = json.loads(ref_file.read_text()) if ref_file.is_file() else {}
    zero = ref.get("leaf_calls_snapshot", {}).get("leaf_calls_total") == 0
    rows = [json.loads(x) for x in
            (base / "led.jsonl").read_text().splitlines() if x.strip()]
    refused_row = any(r.get("action") == "refused" for r in rows)
    rec("P6a.out-of-manifest-coordinate-refused",
        ("清单" in str(exc)) and zero and refused_row,
        "leaf=%s refused_row=%s" % (ref.get("leaf_calls_snapshot"), refused_row))
plan6 = json.loads(
    (ctx6.state_root / "qprod_research_plan.json").read_text())
badcoord = dict(plan6["coordinate_manifest"][0])
badcoord["model_namespace"] = "rogue_unregistered_ns"
badcoord["artifact_subdir"] = "coord_badns"
expect_error("P6b.unregistered-namespace-lock-rejected",
             lambda: lock_coordinate_audit_plan(
                 ctx6.artifact_root / "coord_badns", coordinate=badcoord,
                 research_plan=plan6),
             QProdContextError, "未注册")
dwn = dict(plan6["coordinate_manifest"][0])
dwn["mc_events"] = 1000000
dwn["artifact_subdir"] = "coord_dwn"
expect_error("P6c.budget-downgrade-at-lock-rejected",
             lambda: lock_coordinate_audit_plan(
                 ctx6.artifact_root / "coord_dwn", coordinate=dwn,
                 research_plan=plan6),
             QProdContextError, "预算")
cdir = ctx6.artifact_root / "coord_c01"
cdir.mkdir(parents=True, exist_ok=True)
(cdir / "qprod_coordinate_seal.json").write_text("{}")
try:
    run_coordinate_audit_locked(ctx6, live, "c01", coord_dir=cdir,
                                ledger_path=base / "led.jsonl")
    rec("P6d.sealed-coordinate-reentry-refused", False, "no error")
except QProdContextError as exc:
    rec("P6d.sealed-coordinate-reentry-refused", "封存" in str(exc),
        str(exc)[:100])

print("")
print("==== SUMMARY ====")
fails = [r for r in RESULTS if not r[1]]
print("total=%d pass=%d fail=%d" % (len(RESULTS),
                                    len(RESULTS) - len(fails), len(fails)))
for tag, ok, detail in fails:
    print("FAILED: %s :: %s" % (tag, detail))
