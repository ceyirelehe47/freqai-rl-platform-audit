# QProd 返修轮2(R2)钉测试:REVIEW 深层缺口 14 反例固化。
# 对应复现探针 repro_round2.py(C9 复现 14/14 → C10 0/14)。
# 全部零原生/零 fit/零 optimizer(合成输入+fake 生成叶)。
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "route_c_stage2_6_2"))

import test_curriculum261_qprod_aggregate as ta
import test_curriculum261_qprod_levela as tl
from rl_curriculum.curriculum261_api import (
    CURRICULUM261_QPROD_ENGINEERING_NAMESPACES,
)
from rl_curriculum.curriculum261_qprod_aggregate import (
    _verify_coordinate, aggregate_research,
)
from rl_curriculum.curriculum261_qprod_context import (
    QProdContextError, QProdRunSession,
)
from rl_curriculum.curriculum261_qprod_coordinate import (
    _GenerationLedger, check_native_budget,
    coordinate_audit_plan_digest,
)
from rl_curriculum.curriculum261_qprod_levela import (
    judge_qualification_gates, run_level_a_rehearsal,
)
from rl_curriculum.curriculum261_qprod_plan import (
    load_research_plan, research_plan_structure_problems,
)
from rl_curriculum.curriculum261_r17_cue_contract import (
    cue_contract_audit_digest,
)
from rl_curriculum.ppo262_qprod_export import (
    QProdExportError, export_qualification_delivery,
)

import test_ppo262_qprod_export as te


# ---------------------------------------------------------------- Q1
def test_r2q1_cue_checks_fail_top_pass_rejected(tmp_path):
    """内部 checks/MC 失败但顶层 PASS(且 digest 公共函数重算自洽)
    不得通过 gate1。"""
    ctx = tl._ctx(tmp_path)
    session = QProdRunSession(ctx.state_root, level="level_a",
                              iteration_id=ctx.iteration_id)
    session.acquire({"entry": "t"})
    run_level_a_rehearsal(ctx, session, tl._fixture_inputs(tmp_path))
    art = ctx.artifact_root
    cue_p = art / "cue_contract_audit.json"
    cue = json.loads(cue_p.read_text(encoding="utf-8"))
    cue["checks"]["mc_close_to_analytic"] = False
    cue["monte_carlo"]["pass"] = False
    cue["pass"] = True  # 矛盾顶层
    cue["audit_digest"] = cue_contract_audit_digest(cue)
    cue_p.write_text(json.dumps(cue), encoding="utf-8")
    plan = json.loads((ctx.state_root / "qprod_qualification_plan.json"
                       ).read_text(encoding="utf-8"))
    raw = judge_qualification_gates(art, plan)
    assert raw["verdict"] == "FAIL"
    assert raw["gates"]["cue_audit_pass"]["pass"] is False


def test_r2q1_topology_empty_producers_fail_chain(tmp_path):
    """producer 集合缺失/为空而步骤名齐全 → 链 FAIL(不允许 17 步
    PASS)。"""
    ctx = tl._ctx(tmp_path)
    session = QProdRunSession(ctx.state_root, level="level_a",
                              iteration_id=ctx.iteration_id)
    session.acquire({"entry": "t"})
    inputs = dict(tl._fixture_inputs(tmp_path))
    topo = dict(inputs["gate_topology"])
    topo["artifact_producers"] = {}
    inputs["gate_topology"] = topo
    with pytest.raises(QProdContextError, match="producers"):
        run_level_a_rehearsal(ctx, session, inputs)


def _exportable(tmp_path):
    ctx, _ = te._producer(tmp_path)
    return ctx


def test_r2q1_raw_tamper_with_sha_update_rejected(tmp_path):
    """raw.verdict 篡改且 result.raw_evidence_sha256 同步更新(自洽
    伪造)仍拒:raw 内容级矛盾。"""
    ctx = _exportable(tmp_path)
    res_p = ctx.artifact_root / "qprod_qualification_result.json"
    raw_p = ctx.artifact_root / "qprod_qualification_raw.json"
    res = json.loads(res_p.read_text(encoding="utf-8"))
    raw = json.loads(raw_p.read_text(encoding="utf-8"))
    raw["verdict"] = "FAIL"
    raw_p.write_text(json.dumps(raw), encoding="utf-8")
    res["raw_evidence_sha256"] = hashlib.sha256(
        raw_p.read_bytes()).hexdigest()
    res_p.write_text(json.dumps(res), encoding="utf-8")
    with pytest.raises(QProdExportError):
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, tmp_path / "d",
            expected_scope="engineering")


def test_r2q1_result_iteration_mismatch_rejected(tmp_path):
    """result.iteration_id/source_iteration 与冻结计划不一致 → 拒。"""
    ctx = _exportable(tmp_path)
    res_p = ctx.artifact_root / "qprod_qualification_result.json"
    res = json.loads(res_p.read_text(encoding="utf-8"))
    res["iteration_id"] = "qprod_a_eng_v9"
    res["source_iteration"] = "qprod_a_eng_v9@producer"
    res_p.write_text(json.dumps(res), encoding="utf-8")
    with pytest.raises(QProdExportError):
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, tmp_path / "d",
            expected_scope="engineering")


def test_r2q1_ledger_fail_rejected(tmp_path):
    """链步账本 FAIL(即使 result/journal 保持 PASS)→ 拒。"""
    ctx = _exportable(tmp_path)
    led_p = ctx.artifact_root / "level_a_step_ledger.json"
    led = json.loads(led_p.read_text(encoding="utf-8"))
    led["verdict"] = "FAIL"
    led["steps"] = [dict(s, ok=False) if i == 3 else s
                    for i, s in enumerate(led["steps"])]
    led_p.write_text(json.dumps(led), encoding="utf-8")
    with pytest.raises(QProdExportError):
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, tmp_path / "d",
            expected_scope="engineering")


def test_r2q1_research_plan_prerequisite_missing_rejected(tmp_path):
    """数据前研究计划缺失(prior_plan_digest 绑定断裂)→ 拒。"""
    ctx = _exportable(tmp_path)
    (ctx.state_root / "qprod_research_plan.json").unlink()
    (ctx.state_root / "qprod_research_plan_digest.txt").unlink()
    with pytest.raises(QProdExportError):
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, tmp_path / "d",
            expected_scope="engineering")


def test_r2q1_session_acquire_missing_rejected(tmp_path):
    """journal 无 session_acquired(许可/会话消费来源缺失)→ 拒。"""
    ctx = _exportable(tmp_path)
    jp = ctx.state_root / "qprod_run_journal.jsonl"
    lines = [ln for ln in jp.read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    kept = [ln for ln in lines
            if json.loads(ln).get("event") != "session_acquired"]
    jp.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(QProdExportError):
        export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, tmp_path / "d",
            expected_scope="engineering")


# ---------------------------------------------------------------- Q2
def test_r2q2_attempts_nested_per_action_counting(tmp_path):
    """attempts 嵌套逐动作计数:5 attempts(每次 8 ep)=40,不是
    wrapper×8=16(once 8 + attempts 8)。"""

    class _FakeEp:
        def __init__(self):
            import pandas as pd

            self.df = pd.DataFrame({"x": [1.0]})
            self.hidden = pd.DataFrame({"y": [1.0]})

    def fake_once(ladder, seed, ns):
        return {r: {"A": _FakeEp(), "B": _FakeEp()}
                for r in ("D0", "D1", "D2", "D3")}

    class _FakeBlock:
        block_index = 0

        class _Log:
            selected_attempt = 4
            attempts = [0, 1, 2, 3, 4]
            seed_namespace = "qualification_r2"
            block_index = 0

        attempt_log = _Log()
        episodes = {}

    def fake_attempts(ladder, *, namespace, block_index):
        return _FakeBlock()

    import rl_curriculum.curriculum261_r6_tape as r6

    ledger = _GenerationLedger(quota_max_episode_leaf_calls=640,
                               coordinate_id="cx")
    orig_att = r6.generate_matched_block_with_attempts
    orig_once = r6.generate_matched_block_once
    r6.generate_matched_block_with_attempts = fake_attempts
    r6.generate_matched_block_once = fake_once
    try:
        h = ledger.bind()
        h["generate_once"](None, 1, "ns")
        h["generate_attempts"]({}, namespace="qualification_r2",
                               block_index=0)
    finally:
        r6.generate_matched_block_with_attempts = orig_att
        r6.generate_matched_block_once = orig_once
    # once(8) + attempts 5x8(40) = 48,不是 16(wrapper×8)
    assert ledger.episode_leaf_calls == 48
    t = ledger.totals()
    assert t["episode_leaf_calls"] == 48
    assert t["leaf_calls_total"] == 2  # wrapper 口径另记


def test_r2q2_attempts_quota_blocks_before_nested_action(tmp_path):
    """额度不足以覆盖嵌套最坏情况(max_attempts×8)时,attempts
    block 启动前拒绝——后续叶动作不发生。"""

    class _FakeBlock2:
        block_index = 0

        class _Log2:
            selected_attempt = 1
            attempts = [0, 1]
            seed_namespace = "qualification_r2"
            block_index = 0

        attempt_log = _Log2()
        episodes = {}

    calls = {"attempts": 0}

    def fake_attempts2(ladder, *, namespace, block_index):
        calls["attempts"] += 1
        return _FakeBlock2()

    import rl_curriculum.curriculum261_r6_tape as r6

    # 上限=9:一次 once(8) 后剩余 1 < 最坏 40 → attempts 拒启动
    ledger = _GenerationLedger(quota_max_episode_leaf_calls=9,
                               coordinate_id="cx")
    orig_att = r6.generate_matched_block_with_attempts
    r6.generate_matched_block_with_attempts = fake_attempts2
    try:
        h = ledger.bind()
        h["generate_attempts"]({}, namespace="qualification_r2",
                               block_index=0)
        raise AssertionError("should have raised")
    except Exception as exc:
        from rl_curriculum.curriculum261_qprod_coordinate import (
            QProdQuotaExceeded,
        )
        assert isinstance(exc, QProdQuotaExceeded)
    finally:
        r6.generate_matched_block_with_attempts = orig_att
    assert calls["attempts"] == 0, "额度不足时后续叶动作没有发生"
    assert ledger.episode_leaf_calls == 0


def test_r2q2_plan_requires_audit_budgets_declaration():
    """研究计划缺 rules.audit_budgets 声明 → 结构拒绝(动作前)。"""
    payload = {
        "format": "cur261-qprod-research-plan-v1",
        "level": "level_b", "iteration_id": "i",
        "profile": "engineering", "code_freeze_sha": "s",
        "coordinate_manifest": [
            {"coordinate_id": "c01",
             "model_namespace": "m1", "validation_namespace": "v1",
             "artifact_subdir": "d1"}],
        "rules": {
            "p0_fixed_reference": 0.9504, "p0_source_label": "x",
            "delta_definition": "P0 - recall(validation)",
            "margin": 0.003, "alpha": 0.05, "r_analysis": 1.5,
            "planned_k": 11},
        "quota": {}, "code_identity": {}, "stop_mode": "collect_all_k",
    }
    problems = research_plan_structure_problems(payload)
    assert any("audit_budgets" in p for p in problems)


def test_r2q2_native_budget_hard_gate(tmp_path):
    """原生 2/2 耗尽 → 第三次启动前拒绝;缺失预算文件 fail closed。"""
    budget = tmp_path / "qprod_native_budget.json"
    budget.write_text(json.dumps(
        {"max_runs": 2, "consumed_runs": 2}), encoding="utf-8")
    with pytest.raises(QProdContextError, match="原生执行预算耗尽"):
        check_native_budget(budget)
    # 部分剩余可过
    budget.write_text(json.dumps(
        {"max_runs": 2, "consumed_runs": 1}), encoding="utf-8")
    assert check_native_budget(budget)["max_runs"] == 2
    # 缺失不默认放行
    with pytest.raises(QProdContextError, match="原生预算文件缺失"):
        check_native_budget(tmp_path / "absent.json")


# ---------------------------------------------------------------- Q3
def _mk(tmp: Path):
    art, state, digest = ta._setup_plan(tmp)
    plan = load_research_plan(state)
    coord = plan["coordinate_manifest"][0]
    return art, state, plan, coord, art / coord["artifact_subdir"]


def _pbd_recompute(trace: Path) -> dict:
    """测试用:从 trace 重算 per-block 事件摘要(自洽伪造模拟)。"""
    from rl_curriculum.curriculum261_qprod_coordinate import (
        _per_block_event_digests,
    )
    return _per_block_event_digests(trace)


def _reseal(cd: Path):
    """改成员文件后同步更新 seal 成员摘要(自洽伪造模拟)。"""
    seal_p = cd / "qprod_coordinate_seal.json"
    seal = json.loads(seal_p.read_text(encoding="utf-8"))
    for name in (seal.get("members_sha256") or {}):
        f = cd / name
        if f.is_file():
            seal["members_sha256"][name] = hashlib.sha256(
                f.read_bytes()).hexdigest()
    seal_p.write_text(json.dumps(seal), encoding="utf-8")
    return seal


def test_r2q3_model_events_deleted_rejected(tmp_path):
    """删 model 语料事件(重算摘要自洽)→ 双语料对账拒。"""
    art, state, plan, coord, cd = _mk(tmp_path)
    ta._build_coordinate(art, coord["artifact_subdir"],
                         plan_digest=plan["research_plan_digest"])
    ev = cd / "cue_event_trace.jsonl"
    kept = [ln for ln in ev.read_text(encoding="utf-8").splitlines()
            if ln.strip()
            and json.loads(ln).get("corpus") != "model"]
    ev.write_text("\n".join(kept) + "\n", encoding="utf-8")
    seal = _reseal(cd)
    seal["per_block_event_digests"] = _pbd_recompute(ev)
    (cd / "qprod_coordinate_seal.json").write_text(
        json.dumps(seal), encoding="utf-8")
    v = _verify_coordinate(cd, coord, plan)
    assert v["state"] != "valid"
    assert any("model" in p for p in v["problems"])


def test_r2q3_duplicate_model_seed_rejected(tmp_path):
    """重复同一 model seed 替代另一块(条目数不变)→ 多重集拒。"""
    art, state, plan, coord, cd = _mk(tmp_path)
    ta._build_coordinate(art, coord["artifact_subdir"],
                         plan_digest=plan["research_plan_digest"])
    sl = cd / "qprod_block_seed_log.jsonl"
    entries = [json.loads(x) for x in
               sl.read_text(encoding="utf-8").splitlines() if x]
    once = [e for e in entries if e.get("kind") == "once"]
    once[1]["block_seed"] = once[0]["block_seed"]
    sl.write_text("\n".join(json.dumps(e) for e in entries) + "\n",
                  encoding="utf-8")
    _reseal(cd)
    v = _verify_coordinate(cd, coord, plan)
    assert v["state"] != "valid"
    assert any("多重集" in p for p in v["problems"])


def test_r2q3_qcap_budget_report_mismatch_rejected(tmp_path):
    """qcap/计划声明 500 而报告实际 2 → 三方对账拒。"""
    art, state, plan, coord, cd = _mk(tmp_path)
    ta._build_coordinate(art, coord["artifact_subdir"],
                         plan_digest=plan["research_plan_digest"])
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
    assert v["state"] != "valid"
    assert any("冻结预算与执行不一致" in p for p in v["problems"])


def test_r2q3_legacy_tolerance_bounded_to_e01_identity(tmp_path):
    """legacy 容忍仅限 E01 计划 digest 白名单;新对象缺 pbd 拒。"""
    art, state, plan, coord, cd = _mk(tmp_path)
    ta._build_coordinate(art, coord["artifact_subdir"],
                         plan_digest=plan["research_plan_digest"])
    seal_p = cd / "qprod_coordinate_seal.json"
    seal = json.loads(seal_p.read_text(encoding="utf-8"))
    seal.pop("per_block_event_digests", None)
    seal_p.write_text(json.dumps(seal), encoding="utf-8")
    v = _verify_coordinate(cd, coord, plan)
    assert v["state"] != "valid"
    assert any("legacy" in p or "E01" in p for p in v["problems"])


def test_r2q3_audit_fail_coordinate_excluded_from_primary(tmp_path):
    """R3-Q3(撤回 R2 规则):audit_pass=False 不再一律剔除——
    结构合法的统计 gate FAIL=有效统计负结果,保留进主分析并如实
    标注;K 不足/SE 退化如实 inconclusive,不删样凑绿。"""
    art, state, digest = ta._setup_plan(
        tmp_path, stop_mode="collect_all_k")
    plan = load_research_plan(state)
    for i, coord in enumerate(plan["coordinate_manifest"]):
        ta._build_coordinate(art, coord["artifact_subdir"],
                             plan_digest=digest, seed_tag=i)
        if i == 0:
            seal_p = art / coord["artifact_subdir"] / \
                "qprod_coordinate_seal.json"
            seal = json.loads(seal_p.read_text(encoding="utf-8"))
            seal["summary"]["audit_pass"] = False
            seal_p.write_text(json.dumps(seal), encoding="utf-8")
    agg = aggregate_research(art, state_root=state)
    c0 = agg["coordinates"][0]
    assert c0["state"] == "valid"
    assert c0.get("audit_fail") is True
    # 保留:不再有 audit_fail_excluded;是有效负结果标注
    assert "audit_fail_excluded" not in c0
    assert c0.get("negative_result_valid") is True
    assert c0.get("stats_gate") == "cue_contract_fail"
    # 主分析纳入统计 gate FAIL 坐标(valid 计数含它,如实标注)
    assert agg["valid_coordinate_count"] == len(
        plan["coordinate_manifest"])
    assert c0["coordinate_id"] in agg.get(
        "stats_gate_failed_coordinate_ids", [])


def test_r2q3_valid_e01_legacy_identity_still_readable():
    """E01 历史原件(白名单身份)在 reader 下实际执行读取——
    R3-R01:不再接受"原件不存在"skip;优先部署树可见的仓库归档
    真实路径(F:/ 仓库在 WSL=/mnt/f/trading/freqai-rl-audit),
    两处归档路径均缺失才视为环境真缺件(如实 FAIL,不静默跳过)。
    audit_pass=False=有效统计负结果:valid+如实标注,保留数值。"""
    candidates = [
        Path(__file__).resolve().parents[2]
        / "artifacts" / "repair17" / "development" / "qprod_v1",
        Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1"
             "/artifacts/repair17/development/qprod_v1"),
    ]
    roots = [r for r in candidates if (r / "native_smoke_run1").is_dir()]
    assert roots, (
        f"E01 归档原件两处候选路径均缺失 {candidates}"
        f"(R3-R01:不得默认 skip;归档真实路径必须可读)")
    root = roots[0]
    base = root / "native_smoke_run1" / "qprod_level_b_qprod_b_eng_v1"
    plan = load_research_plan(base / "state")
    coord = plan["coordinate_manifest"][0]
    v = _verify_coordinate(base / "artifacts"
                           / coord["artifact_subdir"], coord, plan)
    assert v["state"] == "valid", v["problems"]
    assert v["legacy_seal_without_event_binding"] is True
    # R3-Q3:真实 report.pass=False → 有效统计负结果(verify 层
    # 如实标 audit_fail;保留进主分析由 aggregate 层用例验证)
    assert v.get("audit_fail") is True
