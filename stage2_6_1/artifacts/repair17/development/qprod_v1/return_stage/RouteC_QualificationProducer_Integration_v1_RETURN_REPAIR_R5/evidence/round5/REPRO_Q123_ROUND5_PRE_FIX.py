import sys, json, tempfile, copy
sys.path.insert(0, "src"); sys.path.insert(0, "tests/route_c_stage2_6_1"); sys.path.insert(0, "tests/route_c_stage2_6_2")
from pathlib import Path
import test_curriculum261_qprod_levela as tl
from rl_curriculum.curriculum261_qprod_context import QProdRunSession
from rl_curriculum.curriculum261_qprod_levela import run_level_a_rehearsal, judge_qualification_gates
from rl_curriculum.curriculum261_r17_cue_contract import (
    cue_contract_audit_digest, recompute_audit_semantics_from_report,
    AUDIT_DIFF_TOL_FLOOR, AUDIT_DIFF_SE_FACTOR)

def rehearse(tmp):
    ctx = tl._ctx(tmp)
    s = QProdRunSession(ctx.state_root, level="level_a", iteration_id=ctx.iteration_id)
    s.acquire({"entry": "t"})
    run_level_a_rehearsal(ctx, s, tl._fixture_inputs(tmp))
    return ctx

def gate1(ctx):
    plan = json.loads((ctx.state_root / "qprod_qualification_plan.json").read_text(encoding="utf-8"))
    return judge_qualification_gates(ctx.artifact_root, plan)

with tempfile.TemporaryDirectory() as tds:
    # --- case1: ova consistent=True but numbers contradict direct_generator ---
    tmp = Path(tds) / "c1"; tmp.mkdir()
    ctx = rehearse(tmp)
    cue_p = ctx.artifact_root / "cue_contract_audit.json"
    cue = json.loads(cue_p.read_text(encoding="utf-8"))
    # 构造: ova 声明 recall 数值彼此矛盾 + 差值超容限, 但 consistent=True
    ova = cue.get("once_vs_attempts")
    if ova is None:
        ova = {"recall_model": 0.30, "recall_validation": 0.95,
               "recall_modes_consistent": True,
               "k_modes_consistent": True,
               "first_pass_bitwise_check": {"bitwise_ok": True}}
        cue["once_vs_attempts"] = ova
    else:
        ova["recall_model"] = 0.30; ova["recall_validation"] = 0.95
        ova["recall_modes_consistent"] = True
    cue["checks"] = {k: True for k in cue["checks"]}; cue["pass"] = True
    cue["audit_digest"] = cue_contract_audit_digest(cue)
    cue_p.write_text(json.dumps(cue), encoding="utf-8")
    raw = gate1(ctx)
    o1 = raw["gates"]["cue_audit_pass"]["observed"]
    print("case1 ova-contradiction: verdict=%s sem_consistent=%s ova_recomputed=%s" % (
        raw["verdict"], o1["semantics_consistent"],
        o1["frozen_semantics_recomputed"].get("once_vs_attempts_consistent")))

    # --- case2: tail integrity sub-input contradicts ok ---
    tmp = Path(tds) / "c2"; tmp.mkdir()
    ctx = rehearse(tmp)
    cue_p = ctx.artifact_root / "cue_contract_audit.json"
    cue = json.loads(cue_p.read_text(encoding="utf-8"))
    ti = cue.get("tail_mirror_bound_integrity")
    if ti is None:
        ti = {"pass": True, "per_corpus": {
            n: {"ok": True, "violations": [], "n_violations": 0,
                "exact_noise_replay_ok": False, "bounds_ok_all_positions": True}
            for n in ("model", "validation")}}
        cue["tail_mirror_bound_integrity"] = ti
    else:
        for n, sub in ti["per_corpus"].items():
            sub["exact_noise_replay_ok"] = False; sub["ok"] = True
            sub["violations"] = []; sub["n_violations"] = 0
        ti["pass"] = True
    cue["checks"] = {k: True for k in cue["checks"]}; cue["pass"] = True
    cue["audit_digest"] = cue_contract_audit_digest(cue)
    cue_p.write_text(json.dumps(cue), encoding="utf-8")
    raw = gate1(ctx)
    o2 = raw["gates"]["cue_audit_pass"]["observed"]
    print("case2 tail-sub-contradiction: verdict=%s sem_consistent=%s ti_recomputed=%s" % (
        raw["verdict"], o2["semantics_consistent"],
        o2["frozen_semantics_recomputed"].get("tail_mirror_bound_integrity_pass")))

    # --- case3: keep bad max_replay_abs_error, DELETE replay_ok (fixture delegation) ---
    tmp = Path(tds) / "c3"; tmp.mkdir()
    ctx = rehearse(tmp)
    cue_p = ctx.artifact_root / "cue_contract_audit.json"
    cue = json.loads(cue_p.read_text(encoding="utf-8"))
    m = cue["direct_generator"]["model"]
    m["max_replay_abs_error"] = 0.25
    m.pop("replay_ok", None)  # 删除支撑字段 → fixture 委托 True
    v = cue["direct_generator"]["validation"]; v.pop("replay_ok", None)
    cue["checks"] = {k: True for k in cue["checks"]}; cue["pass"] = True
    cue["audit_digest"] = cue_contract_audit_digest(cue)
    cue_p.write_text(json.dumps(cue), encoding="utf-8")
    raw = gate1(ctx)
    o3 = raw["gates"]["cue_audit_pass"]["observed"]
    fd = o3.get("frozen_semantics_detail", {}).get("fixture_delegated")
    print("case3 replay-err-kept-field-deleted: verdict=%s sem_consistent=%s delegated=%s" % (
        raw["verdict"], o3["semantics_consistent"], fd))
