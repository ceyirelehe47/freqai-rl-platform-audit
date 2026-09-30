# -*- coding: utf-8 -*-
"""QProd 返修轮复现探针(Q1/Q2/Q3;零原生生成/零fit/零optimizer)。

对当前候选(C7)逐项复现 ChatGPT 终验指出的缺陷,输出
REPRO_Q123.json(每项:构造、期望(修复后)、当前观察(缺陷证据))。
不触碰历史原件;全部在隔离临时目录。
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/src")
sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/tests"
                 "/route_c_stage2_6_1")
sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/tests"
                 "/route_c_stage2_6_2")

OUT = Path("/mnt/f/trading/tmp_qprod2/REPRO_Q123.json")
results = []


def rec(qid, name, construct, expect, observed, verdict):
    results.append({"id": qid, "case": name, "construct": construct,
                    "expected_after_fix": expect, "observed_now": observed,
                    "reproduced": verdict})
    print(f"[{qid}] {name}: reproduced={verdict}")


# ============================================================ Q1
import test_curriculum261_qprod_levela as tl
from rl_curriculum.curriculum261_qprod_context import QProdRunSession

# R1a: preplan_smoke pass=False -> 仍 17 步 PASS?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    ctx = tl._ctx(td)
    s = QProdRunSession(ctx.state_root, level="level_a",
                        iteration_id=ctx.iteration_id)
    s.acquire({})
    inputs = tl._fixture_inputs(td)
    inputs["preplan_smoke"] = {"pass": False, "format": "x"}
    try:
        tl.run_level_a_rehearsal(ctx, s, inputs)
        raised = None
    except Exception as exc:
        raised = f"{type(exc).__name__}: {exc}"
    led_path = ctx.artifact_root / "level_a_step_ledger.json"
    led = (json.loads(led_path.read_text())
           if led_path.is_file() else {"steps": [], "verdict": "?"})
    fixed = raised is not None and "preplan" in str(raised) \
        and led["verdict"] != "PASS"
    rec("Q1", "preplan-FAIL-still-17step-PASS",
        "rehearse with preplan_smoke.pass=False",
        "preplan FAIL -> plan-roundtrip 前置失败 -> 链 FAIL(<17 步)",
        {"raised": raised, "ledger_steps": len(led["steps"]),
         "ledger_verdict": led["verdict"]},
        not fixed)

# R1b: topology 缺失 -> 仍 PASS?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    ctx = tl._ctx(td)
    s = QProdRunSession(ctx.state_root, level="level_a",
                        iteration_id=ctx.iteration_id)
    s.acquire({})
    inputs = tl._fixture_inputs(td)
    inputs.pop("gate_topology")
    try:
        tl.run_level_a_rehearsal(ctx, s, inputs)
        raised = None
    except Exception as exc:
        raised = f"{type(exc).__name__}: {exc}"
    led_path = ctx.artifact_root / "level_a_step_ledger.json"
    led = (json.loads(led_path.read_text())
           if led_path.is_file() else {"steps": [], "verdict": "?"})
    prov = [e for e in led["steps"]
            if e["step"] == "provenance-verify"]
    fixed = raised is not None and "provenance" in str(raised) \
        and led["verdict"] != "PASS"
    rec("Q1", "missing-topology-still-PASS",
        "rehearse without gate_topology input",
        "provenance-verify FAIL(缺链外拓扑) -> 链 FAIL",
        {"raised": raised, "prov_steps": len(prov),
         "ledger_verdict": led["verdict"]},
        not fixed)

# R1c-e: 导出矛盾不拒
import test_ppo262_qprod_export as te
from rl_curriculum.ppo262_qprod_export import (
    QProdExportError, export_qualification_delivery,
)

# R1c: 删除 producer journal(真实终态缺失) -> 导出仍成功?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    ctx, out = te._producer(td)
    (ctx.state_root / "qprod_run_journal.jsonl").unlink()
    try:
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, td / "d",
            expected_scope="engineering")
        ok = True
    except QProdExportError:
        ok = False
    rec("Q1", "export-without-real-terminal",
        "producer journal deleted; export attempted",
        "导出拒绝(真实终态不可核)", {"export_succeeded": ok}, ok)

# R1d: 校准前置(qp plan calibration_artifacts digest)与盘上不符 ->
#      导出仍成功?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    ctx, out = te._producer(td)
    (ctx.artifact_root / "preprocessor_bundle_holdout.json").write_text(
        json.dumps({"tampered": True}), encoding="utf-8")
    try:
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, td / "d",
            expected_scope="engineering")
        ok = True
    except QProdExportError:
        ok = False
    rec("Q1", "export-calibration-prereq-tampered",
        "holdout calibration artifact bytes swapped after plan lock",
        "导出拒绝(校准前置 digest 不符)",
        {"export_succeeded": ok}, ok)

# R1e: raw 数据改坏(观测字段伪值)但外层 PASS/摘要自洽 -> 导出仍成功?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    ctx, out = te._producer(td)
    rp = ctx.artifact_root / "qprod_qualification_raw.json"
    raw = json.loads(rp.read_text())
    raw["gates"]["cue_audit_pass"]["observed"]["audit_digest"] = \
        "r15ca-FABULATED"
    rp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    try:
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, td / "d",
            expected_scope="engineering")
        ok = True
    except QProdExportError:
        ok = False
    rec("Q1", "export-raw-observations-tampered",
        "raw gate observed.audit_digest replaced by fake; verdicts kept",
        "导出拒绝(raw 与其证据复算不一致)",
        {"export_succeeded": ok}, ok)

# ============================================================ Q2
import test_curriculum261_qprod_permit as tp
from rl_curriculum.curriculum261_qprod_permit import validate_permit

# R2a: 0 配额许可通过验证(可进入审计)?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    ctx = tp._ctx(td)
    path, _ = tp._write_permit(
        td / "authority", ctx,
        quota={"max_leaf_calls_per_coordinate": 0,
               "max_successful_episodes_total": 0,
               "mc_events_per_coordinate": 0,
               "max_native_executions": 0})
    try:
        validate_permit(path, context=ctx)
        accepted = True
    except Exception:
        accepted = False
    rec("Q2", "zero-quota-permit-accepted",
        "permit quota all zeros",
        "验证拒绝(0 额度禁止进入审计)",
        {"validate_accepted": accepted}, accepted)

# R2b: 不支持的 max_attempts 静默接受?
import test_curriculum261_qprod_coordinate as tc
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    ctx, payload = tc._setup(td)
    coord = dict(tc.C01, max_attempts=3)
    d = td / "locks" / "coord_c01"
    try:
        tc.lock_coordinate_audit_plan(
            d, coordinate=coord, research_plan=payload)
        locked = True
    except Exception as exc:
        locked = f"rejected: {exc}"
    rec("Q2", "unsupported-max-attempts-locks",
        "manifest max_attempts=3 (core only supports structural 5)",
        "锁定拒绝(不支持值显式拒绝,不静默忽略)",
        {"locked": locked}, locked is True)

# R2c: block_start_index 非零静默接受?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    ctx, payload = tc._setup(td)
    coord = dict(tc.C01, block_start_index=100)
    d = td / "locks" / "coord_c01"
    try:
        tc.lock_coordinate_audit_plan(
            d, coordinate=coord, research_plan=payload)
        locked = True
    except Exception as exc:
        locked = f"rejected: {exc}"
    rec("Q2", "nonzero-block-start-locks",
        "manifest block_start_index=100 (core always starts at 0)",
        "锁定拒绝(预注册范围与真实生成不一致)",
        {"locked": locked}, locked is True)

# R2d: episode 单位缺账(现行账本只有 block 调用数/估算字段)?
from rl_curriculum.curriculum261_qprod_coordinate import (
    _GenerationLedger,
)
led = _GenerationLedger()
led.leaf_calls = {"once": 1, "attempts": 1, "bitwise_replay": 1}
t = led.totals()
rec("Q2", "episode-unit-missing",
    "ledger totals keys after 3 block-level calls",
    "账本以 episode 叶调用为单位记录并在叶边界执行配额",
    {"totals": t},
    not ("episode_leaf_calls" in t
         and t["episode_leaf_calls"] == t["leaf_calls_total"] * 8
         and "unit_note" in t))

# ============================================================ Q3
import test_curriculum261_qprod_aggregate as ta
from rl_curriculum.curriculum261_qprod_aggregate import (
    _verify_coordinate, aggregate_research,
)

def _coord_ok(art, sd, digest, **kw):
    ta._build_coordinate(art, sd, plan_digest=digest, **kw)
    return json.loads((art / sd / "qprod_coordinate_seal.json")
                      .read_text())

# R3a: seal 成员集为空 -> 仍 valid?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    art, state, digest = ta._setup_plan(td)
    _coord_ok(art, "c01", digest)
    sp = art / "c01" / "qprod_coordinate_seal.json"
    seal = json.loads(sp.read_text())
    seal["members_sha256"] = {}
    sp.write_text(json.dumps(seal), encoding="utf-8")
    plan = json.loads((state / "qprod_research_plan.json").read_text())
    v = _verify_coordinate(art / "c01", plan["coordinate_manifest"][0],
                           plan)
    rec("Q3", "empty-seal-member-set-accepted",
        "seal.members_sha256 emptied; all files still present",
        "拒(必需成员集合精确覆盖)",
        {"state": v["state"]}, v["state"] == "valid")

# R3b: 伪 audit digest -> 仍 valid?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    art, state, digest = ta._setup_plan(td)
    _coord_ok(art, "c01", digest)
    sp = art / "c01" / "qprod_coordinate_seal.json"
    seal = json.loads(sp.read_text())
    seal["audit_digest"] = "r15ca-FABRICATED"
    sp.write_text(json.dumps(seal), encoding="utf-8")
    plan = json.loads((state / "qprod_research_plan.json").read_text())
    v = _verify_coordinate(art / "c01", plan["coordinate_manifest"][0],
                           plan)
    rec("Q3", "fake-audit-digest-accepted",
        "seal.audit_digest replaced; report unchanged",
        "拒(audit digest 与报告公共函数复算不符)",
        {"state": v["state"]}, v["state"] == "valid")

# R3c: validation 事件 block 索引换位(多重集不变) -> 仍 valid?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    art, state, digest = ta._setup_plan(td)
    _coord_ok(art, "c01", digest)
    tp_ = art / "c01" / "cue_event_trace.jsonl"
    rows = [json.loads(x) for x in tp_.read_text().splitlines() if x]
    for r in rows:
        if r["corpus"] == "validation":
            r["block_index"] = 1 - r["block_index"]
    tp_.write_text("\n".join(json.dumps(r, sort_keys=True)
                             for r in rows) + "\n", encoding="utf-8")
    sp = art / "c01" / "qprod_coordinate_seal.json"
    seal = json.loads(sp.read_text())
    seal["members_sha256"]["cue_event_trace.jsonl"] = __import__(
        "hashlib").sha256(tp_.read_bytes()).hexdigest()
    sp.write_text(json.dumps(seal), encoding="utf-8")
    plan = json.loads((state / "qprod_research_plan.json").read_text())
    v = _verify_coordinate(art / "c01", plan["coordinate_manifest"][0],
                           plan)
    rec("Q3", "block-index-swap-accepted",
        "validation event block indices swapped 0<->1 (multiset same)",
        "拒(事件 block 归属与 seed 日志/计划 block 范围不符)",
        {"state": v["state"],
         "recall": v.get("recall_validation")}, v["state"] == "valid")

# R3d: seed 日志缺 validation attempts 条目 -> 仍 valid?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    art, state, digest = ta._setup_plan(td)
    _coord_ok(art, "c01", digest)
    lp = art / "c01" / "qprod_block_seed_log.jsonl"
    rows = [json.loads(x) for x in lp.read_text().splitlines() if x]
    rows = [r for r in rows if r.get("kind") != "attempts"]
    lp.write_text("\n".join(json.dumps(r, sort_keys=True)
                            for r in rows) + "\n", encoding="utf-8")
    sp = art / "c01" / "qprod_coordinate_seal.json"
    seal = json.loads(sp.read_text())
    seal["members_sha256"]["qprod_block_seed_log.jsonl"] = __import__(
        "hashlib").sha256(lp.read_bytes()).hexdigest()
    sp.write_text(json.dumps(seal), encoding="utf-8")
    plan = json.loads((state / "qprod_research_plan.json").read_text())
    v = _verify_coordinate(art / "c01", plan["coordinate_manifest"][0],
                           plan)
    rec("Q3", "missing-validation-seeds-accepted",
        "attempts (validation) seed log entries removed",
        "拒(validation seeds 缺失)",
        {"state": v["state"]}, v["state"] == "valid")

# R3e: 坐标审计计划(qcap)文件缺失 -> 仍 valid?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    art, state, digest = ta._setup_plan(td)
    _coord_ok(art, "c01", digest)
    plan_file = art / "c01" / "qprod_coordinate_audit_plan.json"
    if not plan_file.is_file():
        (art / "c01" / "qprod_coordinate_audit_plan.json").write_text(
            "{}", encoding="utf-8")  # builder 未产 qcap;先补一个再删
    plan_file.unlink()
    plan = json.loads((state / "qprod_research_plan.json").read_text())
    v = _verify_coordinate(art / "c01", plan["coordinate_manifest"][0],
                           plan)
    rec("Q3", "missing-frozen-coordinate-plan-accepted",
        "qprod_coordinate_audit_plan.json removed from coord dir",
        "拒(冻结坐标计划缺失/不绑定)",
        {"state": v["state"]}, v["state"] == "valid")

# R3f: early_stop 只写字段,不约束聚合消费?
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    art, state, digest = ta._setup_plan(
        td, stop_mode="early_stop_on_first_negative")
    ta._build_coordinate(art, "c01", seed_tag=0, hits_per_block=10,
                         n_events=55, plan_digest=digest)
    ta._build_coordinate(art, "c02", seed_tag=1, plan_digest=digest)
    r = aggregate_research(art, state_root=state)
    consumed = r["valid_coordinate_count"]
    dd = r["primary"].get("delta_bar_descriptive")
    rec("Q3", "early-stop-does-not-constrain-consumption",
        "c01 statistical negative; c02 produced afterwards",
        "c02 不进入主分析(停后不消费/标注违规),启动亦被拒",
        {"early_stopped_at": r["early_stopped_at"],
         "valid_coordinates_consumed": consumed,
         "delta_bar_uses_all": dd is not None},
        consumed == 2)

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(
    {"format": "cur261-qprod-repro-q123-v1",
     "candidate_under_test": "C7=cda4e975 (deploy tree synced)",
     "results": results}, indent=2, ensure_ascii=False))
n = sum(1 for r in results if r["reproduced"])
print(f"\nREPRODUCED {n}/{len(results)}")
