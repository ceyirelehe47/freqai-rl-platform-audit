#!/usr/bin/env python3
"""QProd 返修轮2 复现探针(R2;零原生/零fit/零optimizer)。

对 C9(0d67a143 字节)验证本轮 REVIEW 指出的深层缺口是否可复现:
R2-Q1: 内部checks矛盾仍PASS / topology producers空集 / raw篡改+SHA
       更新仍导出 / result迭代错 / 账本FAIL仍导出 / 研究计划缺失仍导出
R2-Q2: attempts嵌套逐动作计数(wrapper×8漏计) / 研究计划无审计预算声明
       / 原生2/2无硬门
R2-Q3: 删model事件仍valid / 重复model seed仍valid / qcap预算与报告
       不对账 / legacy无身份限定 / audit FAIL坐标进主分析

每项 reproduced=True 表示缺陷存在(修复前)。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/src")
sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/tests"
                 "/route_c_stage2_6_1")
sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/tests"
                 "/route_c_stage2_6_2")

OUT = Path(os.environ.get(
    "REPRO_OUT", "/mnt/f/trading/tmp_qprod3/REPRO_Q123_ROUND2.json"))
CANDIDATE_LABEL = os.environ.get(
    "REPRO_CANDIDATE",
    "unlabeled(candidate injected via REPRO_CANDIDATE env)")

results: list[dict] = []


def record(cid: str, case: str, reproduced: bool, detail: str) -> None:
    results.append({"id": cid, "case": case,
                    "reproduced": bool(reproduced), "detail": detail})
    print(f"[{cid}] {case}: reproduced={reproduced}")


# ============================================================ R2-Q1
def q1_checks() -> None:
    import test_curriculum261_qprod_levela as tl
    from rl_curriculum.curriculum261_qprod_levela import (
        judge_qualification_gates,
    )
    from rl_curriculum.curriculum261_r17_cue_contract import (
        cue_contract_audit_digest,
    )

    with tempfile.TemporaryDirectory() as tds:
        tmp = Path(tds)
        ctx = tl._ctx(tmp)
        session = tl.QProdRunSession(
            ctx.state_root, level="level_a",
            iteration_id=ctx.iteration_id)
        session.acquire({"entry": "repro-r2"})
        inputs = tl._fixture_inputs(tmp)
        from rl_curriculum.curriculum261_qprod_levela import (
            run_level_a_rehearsal,
        )
        run_level_a_rehearsal(ctx, session, inputs)  # 先产正常链
        art = ctx.artifact_root
        # (1) 内部 checks 矛盾:mc_close_to_analytic=False 但 pass=True
        #     且 audit_digest 用公共函数重算(自洽)
        cue_p = art / "cue_contract_audit.json"
        cue = json.loads(cue_p.read_text(encoding="utf-8"))
        cue["checks"] = dict(cue.get("checks") or {})
        cue["checks"]["mc_close_to_analytic"] = False
        cue["monte_carlo"] = dict(cue.get("monte_carlo") or {})
        cue["monte_carlo"]["pass"] = False
        cue["pass"] = True  # 顶层仍 PASS(矛盾)
        cue["audit_digest"] = cue_contract_audit_digest(cue)
        cue_p.write_text(json.dumps(cue), encoding="utf-8")
        plan = json.loads((ctx.state_root
                           / "qprod_qualification_plan.json"
                           ).read_text(encoding="utf-8"))
        raw = judge_qualification_gates(art, plan)
        gate1 = raw["gates"]["cue_audit_pass"]["pass"]
        record("Q1", "cue-checks-fail-top-pass",
               raw["verdict"] == "PASS",
               "checks mismatch but gate1=%s verdict=%s"
               % (gate1, raw["verdict"]))

    with tempfile.TemporaryDirectory() as tds:
        tmp = Path(tds)
        ctx = tl._ctx(tmp)
        session = tl.QProdRunSession(
            ctx.state_root, level="level_a",
            iteration_id=ctx.iteration_id)
        session.acquire({"entry": "repro-r2"})
        inputs = tl._fixture_inputs(tmp)
        # (2) topology producer 集合为空但步骤名齐全
        topo = dict(inputs.get("gate_topology") or {})
        topo["artifact_producers"] = {}
        from rl_curriculum.curriculum261_qprod_levela import (
            run_level_a_rehearsal,
        )
        inputs2 = dict(inputs)
        inputs2["gate_topology"] = topo
        try:
            run_level_a_rehearsal(ctx, session, inputs2)
            record("Q1", "topology-empty-producers", True,
                   "producer空集仍17步PASS")
        except Exception as exc:
            record("Q1", "topology-empty-producers", False,
                   f"已拒绝: {type(exc).__name__}")


def q1_export() -> None:
    import test_ppo262_qprod_export as te
    from rl_curriculum.ppo262_qprod_export import (
        QProdExportError, export_qualification_delivery,
    )

    # (3) raw.verdict 篡改 + result.raw_evidence_sha256 同步更新
    with tempfile.TemporaryDirectory() as tds:
        tmp = Path(tds)
        ctx, _ = te._producer(tmp)
        res_p = ctx.artifact_root / "qprod_qualification_result.json"
        raw_p = ctx.artifact_root / "qprod_qualification_raw.json"
        res = json.loads(res_p.read_text(encoding="utf-8"))
        raw = json.loads(raw_p.read_text(encoding="utf-8"))
        raw["verdict"] = "FAIL"  # 内容与 result 矛盾
        raw_p.write_text(json.dumps(raw), encoding="utf-8")
        import hashlib

        res["raw_evidence_sha256"] = hashlib.sha256(
            raw_p.read_bytes()).hexdigest()  # SHA 一并正确更新
        res_p.write_text(json.dumps(res), encoding="utf-8")
        try:
            export_qualification_delivery(
                ctx.artifact_root, ctx.state_root, tmp / "d3",
                expected_scope="engineering")
            record("Q1", "raw-tamper-with-sha-update", True,
                   "raw内容矛盾+SHA更新仍导出成功")
        except QProdExportError:
            record("Q1", "raw-tamper-with-sha-update", False, "已拒绝")

    # (4) result.iteration_id 错(与计划不一致)
    with tempfile.TemporaryDirectory() as tds:
        tmp = Path(tds)
        ctx, _ = te._producer(tmp)
        res_p = ctx.artifact_root / "qprod_qualification_result.json"
        res = json.loads(res_p.read_text(encoding="utf-8"))
        res["iteration_id"] = "qprod_a_eng_v9"
        res["source_iteration"] = "qprod_a_eng_v9@producer"
        res_p.write_text(json.dumps(res), encoding="utf-8")
        try:
            export_qualification_delivery(
                ctx.artifact_root, ctx.state_root, tmp / "d4",
                expected_scope="engineering")
            record("Q1", "result-iteration-mismatch", True,
                   "iteration错仍导出成功")
        except QProdExportError:
            record("Q1", "result-iteration-mismatch", False, "已拒绝")

    # (5) 链步账本 FAIL 但 result/journal 保持 PASS
    with tempfile.TemporaryDirectory() as tds:
        tmp = Path(tds)
        ctx, _ = te._producer(tmp)
        led_p = (ctx.artifact_root / "level_a_step_ledger.json")
        led = json.loads(led_p.read_text(encoding="utf-8"))
        led["verdict"] = "FAIL"
        led["steps"] = [dict(s, ok=False) if i == 3 else s
                        for i, s in enumerate(led["steps"])]
        led_p.write_text(json.dumps(led), encoding="utf-8")
        try:
            export_qualification_delivery(
                ctx.artifact_root, ctx.state_root, tmp / "d5",
                expected_scope="engineering")
            record("Q1", "ledger-fail-exports", True,
                   "账本FAIL仍导出成功")
        except QProdExportError:
            record("Q1", "ledger-fail-exports", False, "已拒绝")

    # (6) 数据前研究计划缺失
    with tempfile.TemporaryDirectory() as tds:
        tmp = Path(tds)
        ctx, _ = te._producer(tmp)
        (ctx.state_root / "qprod_research_plan.json").unlink()
        (ctx.state_root / "qprod_research_plan_digest.txt").unlink()
        try:
            export_qualification_delivery(
                ctx.artifact_root, ctx.state_root, tmp / "d6",
                expected_scope="engineering")
            record("Q1", "research-plan-missing-exports", True,
                   "必要研究计划缺失仍导出成功")
        except QProdExportError:
            record("Q1", "research-plan-missing-exports", False,
                   "已拒绝")


# ============================================================ R2-Q2
def q2_quota() -> None:
    from rl_curriculum.curriculum261_qprod_coordinate import (
        _GenerationLedger,
    )

    # (7) attempts 嵌套:真实 5 attempts(每 attempt 8 ep)但计数=8
    class _FakeEp:
        pass

    class _FakeBlock:
        block_index = 0

        class _Log:
            selected_attempt = 4
            attempts = [1, 2, 3, 4, 5]
            seed_namespace = "qualification_r2"
            block_index = 0

        attempt_log = _Log()
        episodes = {}

    ledger = _GenerationLedger(quota_max_episode_leaf_calls=640,
                               coordinate_id="cx")
    calls = {"n": 0}

    def fake_attempts(ladder, *, namespace, block_index):
        calls["n"] += 1
        return _FakeBlock()


    ledger.bind()  # 初始化 _once_seq 等
    hooks = {"generate_attempts": None}
    # 直接调用内部包装(绕过 r6 绑定)
    import rl_curriculum.curriculum261_r6_tape as r6

    orig = r6.generate_matched_block_with_attempts
    r6.generate_matched_block_with_attempts = fake_attempts
    try:
        h = ledger.bind()
        # namespace 用合法注册值,避免 seed 派生真实计算(fake 只计数)
        h["generate_attempts"]({}, namespace="qualification_r2",
                               block_index=0)
    finally:
        r6.generate_matched_block_with_attempts = orig
    actual_actions = 5 * 8  # 5 attempts x 8 episodes
    counted = ledger.episode_leaf_calls
    record("Q2", "attempts-nested-undercount",
           counted == 8 and actual_actions == 40,
           f"计数={counted}(wrapper×8);真实动作={actual_actions}")


def q2_plan_budget() -> None:
    import test_curriculum261_qprod_coordinate as tc
    from rl_curriculum.curriculum261_qprod_plan import (
        freeze_research_plan, research_plan_structure_problems,
    )

    # (8) 研究计划无 audit_budgets 声明仍可冻结(lock 无计划级对账)
    with tempfile.TemporaryDirectory() as tds:
        tmp = Path(tds)
        ctx, payload = tc._setup(tmp, plan_freeze=False)
        problems = research_plan_structure_problems(payload)
        record("Q2", "plan-missing-audit-budgets",
               not problems,
               f"无audit_budgets声明结构问题={problems or '无'}")


def q2_native_budget() -> None:
    # (9) 原生 2/2 耗尽无运行时硬门(e01 脚本不检查预算文件)
    script = Path("/home/cryptorl/projects/crypto_rl/stage2_6_1_runner"
                  "/qprod_e01_native_smoke.sh")
    body = script.read_text(encoding="utf-8") if script.is_file() else ""
    has_gate = ("native_budget" in body or "budget.json" in body
                or "NATIVE_BUDGET" in body)
    record("Q2", "native-budget-hard-gate", not has_gate,
           f"e01脚本预算硬门存在={has_gate}")


# ============================================================ R2-Q3
def q3_reader() -> None:
    import test_curriculum261_qprod_aggregate as ta
    from rl_curriculum.curriculum261_qprod_aggregate import (
        _verify_coordinate,
    )
    from rl_curriculum.curriculum261_qprod_plan import load_research_plan

    def _mk(tmp: Path):
        art, state, digest = ta._setup_plan(tmp)
        plan = load_research_plan(state)
        coord = plan["coordinate_manifest"][0]
        return art, state, plan, coord, art / coord["artifact_subdir"]

    # (10) 删 model 事件(trace 只留 validation)
    with tempfile.TemporaryDirectory() as tds:
        tmp = Path(tds)
        art, state, plan, coord, cd = _mk(tmp)
        ta._build_coordinate(art, coord["artifact_subdir"],
                             plan_digest=plan["research_plan_digest"])
        ev = cd / "cue_event_trace.jsonl"
        lines = [ln for ln in ev.read_text(encoding="utf-8").splitlines()
                 if ln.strip()]
        kept = [ln for ln in lines
                if json.loads(ln).get("corpus") != "model"]
        ev.write_text("\n".join(kept) + "\n", encoding="utf-8")
        # 更新 seal 的事件相关摘要以模拟"自洽伪造": 重算 summary 数值
        v = _verify_coordinate(cd, coord, plan)
        record("Q3", "model-events-deleted",
               v["state"] == "valid",
               f"删model事件后state={v['state']},problems前3="
               f"{v['problems'][:3]}")

    # (11) 重复 model seed 替代另一块(once seed b0 x2,缺 b1)
    with tempfile.TemporaryDirectory() as tds:
        tmp = Path(tds)
        art, state, plan, coord, cd = _mk(tmp)
        ta._build_coordinate(art, coord["artifact_subdir"],
                             plan_digest=plan["research_plan_digest"])
        sl = cd / "qprod_block_seed_log.jsonl"
        entries = [json.loads(x) for x in
                   sl.read_text(encoding="utf-8").splitlines() if x]
        once = [e for e in entries if e.get("kind") == "once"]
        if len(once) >= 2:
            once[1]["block_seed"] = once[0]["block_seed"]
        sl.write_text("\n".join(json.dumps(e) for e in entries) + "\n",
                      encoding="utf-8")
        seal_p2 = cd / "qprod_coordinate_seal.json"
        seal2 = json.loads(seal_p2.read_text(encoding="utf-8"))
        import hashlib as _h

        seal2["members_sha256"]["qprod_block_seed_log.jsonl"] = _h.sha256(
            sl.read_bytes()).hexdigest()
        seal_p2.write_text(json.dumps(seal2), encoding="utf-8")
        v = _verify_coordinate(cd, coord, plan)
        record("Q3", "duplicate-model-seed",
               v["state"] == "valid",
               f"重复seed后state={v['state']},problems前3="
               f"{v['problems'][:3]}")

    # (12) qcap 预算与报告不对账(qcap 500 而报告 2)
    with tempfile.TemporaryDirectory() as tds:
        tmp = Path(tds)
        art, state, plan, coord, cd = _mk(tmp)
        ta._build_coordinate(art, coord["artifact_subdir"],
                             plan_digest=plan["research_plan_digest"])
        from rl_curriculum.curriculum261_qprod_coordinate import (
            coordinate_audit_plan_digest,
        )
        qcap_p = cd / "qprod_coordinate_audit_plan.json"
        qcap = json.loads(qcap_p.read_text(encoding="utf-8"))
        qcap["budgets"]["blocks_per_corpus"] = 500
        qcap["budgets"]["mc_events"] = 1
        qcap.pop("coordinate_audit_plan_digest", None)
        qcap["coordinate_audit_plan_digest"] = (
            coordinate_audit_plan_digest(qcap))
        qcap_p.write_text(json.dumps(qcap), encoding="utf-8")
        (cd / "qprod_coordinate_audit_plan_digest.txt").write_text(
            qcap["coordinate_audit_plan_digest"], encoding="utf-8")
        seal_p = cd / "qprod_coordinate_seal.json"
        seal = json.loads(seal_p.read_text(encoding="utf-8"))
        seal["coordinate_audit_plan_digest"] = qcap[
            "coordinate_audit_plan_digest"]
        seal_p.write_text(json.dumps(seal), encoding="utf-8")
        v = _verify_coordinate(cd, coord, plan)
        record("Q3", "qcap-budget-report-mismatch",
               v["state"] == "valid",
               f"qcap500/报告2后state={v['state']}")

    # (13) legacy 无身份限定(新 seal 缺 per_block_event_digests)
    with tempfile.TemporaryDirectory() as tds:
        tmp = Path(tds)
        art, state, plan, coord, cd = _mk(tmp)
        ta._build_coordinate(art, coord["artifact_subdir"],
                             plan_digest=plan["research_plan_digest"])
        seal_p = cd / "qprod_coordinate_seal.json"
        seal = json.loads(seal_p.read_text(encoding="utf-8"))
        seal.pop("per_block_event_digests", None)
        seal_p.write_text(json.dumps(seal), encoding="utf-8")
        v = _verify_coordinate(cd, coord, plan)
        record("Q3", "legacy-unbounded",
               v["state"] == "valid"
               and v.get("legacy_seal_without_event_binding") is True,
               f"非E01身份缺绑定state={v['state']},legacy="
               f"{v.get('legacy_seal_without_event_binding')}")

    # (14) audit FAIL 坐标进入主分析(summary.audit_pass=False)
    with tempfile.TemporaryDirectory() as tds:
        tmp = Path(tds)
        from rl_curriculum.curriculum261_qprod_aggregate import (
            aggregate_research,
        )
        art, state, digest = ta._setup_plan(tmp)
        plan = load_research_plan(state)
        coord = plan["coordinate_manifest"][0]
        ta._build_coordinate(art, coord["artifact_subdir"],
                             plan_digest=digest)
        cd = art / coord["artifact_subdir"]
        seal_p = cd / "qprod_coordinate_seal.json"
        seal = json.loads(seal_p.read_text(encoding="utf-8"))
        seal["summary"]["audit_pass"] = False
        seal_p.write_text(json.dumps(seal), encoding="utf-8")
        agg = aggregate_research(art, state_root=state)
        c0 = agg["coordinates"][0]
        consumed = (c0["state"] == "valid"
                    and "audit_fail" not in c0)
        record("Q3", "audit-fail-consumed",
               consumed,
               f"audit_pass=False坐标state={c0['state']},"
               f"进入主分析={consumed}")


def main() -> int:
    for fn in (q1_checks, q1_export, q2_quota, q2_plan_budget,
               q2_native_budget, q3_reader):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            record(fn.__name__, "probe-error", False,
                   f"{type(exc).__name__}: {exc}")
    n = sum(1 for r in results if r["reproduced"])
    print(f"\nREPRODUCED {n}/{len(results)}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "format": "cur261-qprod-repro-round2-v1",
        "candidate_under_test": CANDIDATE_LABEL,
        "zero_native": True, "synthetic_only": True,
        "results": results}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print("written", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
