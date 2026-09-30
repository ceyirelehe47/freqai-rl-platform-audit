# RV1 probe 3: P6 re-run with iteration-aligned plan (zero generation).
import json
import sys
from pathlib import Path
SRC = "/home/cryptorl/projects/crypto_rl/src"
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from rl_curriculum.curriculum261_qprod_context import (
    QProdContextError, build_engineering_context,
)
from rl_curriculum.curriculum261_qprod_plan import freeze_research_plan
from rl_curriculum.curriculum261_qprod_coordinate import (
    lock_coordinate_audit_plan, run_coordinate_audit_locked,
)
from rl_curriculum.curriculum261_api import (
    CURRICULUM261_QPROD_ENGINEERING_NAMESPACES,
)

base = Path("/tmp/rv1_probes/p6_fix")
auth = base / "authority"
auth.mkdir(parents=True, exist_ok=True)
(auth / "authority_identity.json").write_text(json.dumps(
    {"authority_id": "rv1_test_authority"}))
ctx = build_engineering_context(
    level="level_b", iteration_id="rv1d", base_dir=base / "run",
    code_freeze_sha="fz", authority_dir=auth,
    namespaces_scope=CURRICULUM261_QPROD_ENGINEERING_NAMESPACES)
payload = {
    "format": "cur261-qprod-research-plan-v1",
    "level": "level_b", "iteration_id": "rv1d",
    "profile": "engineering", "code_freeze_sha": "fz",
    "coordinate_manifest": [
        {"coordinate_id": "c01",
         "model_namespace": "cue_qprod_v1_c01_model",
         "validation_namespace": "cue_qprod_v1_c01_validation",
         "artifact_subdir": "coord_c01"}],
    "rules": {"p0_fixed_reference": 0.950431552876822,
              "p0_source_label": "rv1", "delta_definition":
              "P0 - recall(validation)", "margin": 0.003, "alpha": 0.05,
              "r_analysis": 1.5, "planned_k": 11},
    "quota": {}, "code_identity": {}, "stop_mode": "collect_all_k"}
_, digest = freeze_research_plan(ctx.state_root, payload)
plan = json.loads(
    (ctx.state_root / "qprod_research_plan.json").read_text())
pb = {"task_level": "level_b",
      "preregistered_input_scope": {"namespaces": [
          "cue_qprod_v1_c01_model", "cue_qprod_v1_c01_validation"]}}
live = type("LP", (), {"permit": pb})()

# P6a: out-of-manifest coordinate -> refusal, zero leaf calls, ledger row
try:
    run_coordinate_audit_locked(ctx, live, "cXX",
                                coord_dir=ctx.artifact_root / "coord_cXX",
                                ledger_path=base / "led.jsonl")
    print("FAIL P6a no error")
except QProdContextError as exc:
    ref = json.loads((ctx.artifact_root / "refusal_cXX.json").read_text())
    rows = [json.loads(x) for x in
            (base / "led.jsonl").read_text().splitlines() if x.strip()]
    ok = (("清单" in str(exc))
          and ref["leaf_calls_snapshot"]["leaf_calls_total"] == 0
          and any(r.get("action") == "refused" for r in rows))
    print(("PASS" if ok else "FAIL") +
          " P6a.out-of-manifest-refused reason=" + str(exc)[:70])

# P6d: sealed coordinate re-entry -> refusal (freshness)
cdir = ctx.artifact_root / "coord_c01"
cdir.mkdir(parents=True, exist_ok=True)
(cdir / "qprod_coordinate_seal.json").write_text("{}")
try:
    run_coordinate_audit_locked(ctx, live, "c01", coord_dir=cdir,
                                ledger_path=base / "led.jsonl")
    print("FAIL P6d no error")
except QProdContextError as exc:
    print(("PASS" if "封存" in str(exc) else "FAIL") +
          " P6d.sealed-reentry-refused reason=" + str(exc)[:70])

# P6e: interrupted coordinate re-entry -> refusal (no rescue by re-run)
cdir2 = ctx.artifact_root / "coord_c02"
cdir2.mkdir(parents=True, exist_ok=True)
(cdir2 / "qprod_coordinate_interrupted.json").write_text("{}")
try:
    run_coordinate_audit_locked(ctx, live, "c01", coord_dir=cdir2,
                                ledger_path=base / "led.jsonl")
    print("FAIL P6e no error")
except QProdContextError as exc:
    print(("PASS" if "中断" in str(exc) else "FAIL") +
          " P6e.interrupted-reentry-refused reason=" + str(exc)[:70])
